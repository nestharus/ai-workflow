"""Library synthesis workflow for Phase 2 spec refinement."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from spec_manager.refinement.formats import LibraryCharter, LibraryEvent, LibraryEventType
from spec_manager.refinement.progress import ProgressTracker
from spec_manager.refinement.workspace import Phase, PhaseStatus, WorkspaceManager

from .library_labeling import (
    CharterResults,
    _validate_concern_coverage,
    _write_concern_evidence,
    aggregate_labels,
    build_library_shapes,
    generate_all_charters,
    judge_concern_assignments,
    label_all_files,
    refine_library_labels,
    resolve_all_overlaps,
    validate_library_shapes,
)

LIB_ID_RE = re.compile(r"^lib_\d{3}$")
logger = logging.getLogger(__name__)


def _write_library_event(lib_dir: Path, event: LibraryEvent) -> None:
    """Append a library event to events.jsonl with an atomic rewrite."""
    events = _read_library_events(lib_dir)
    events.append(event)
    _rewrite_library_events(lib_dir, events)


def _rewrite_library_events(lib_dir: Path, events: list[LibraryEvent]) -> None:
    """Rewrite events.jsonl atomically from a list of events."""
    lib_dir.mkdir(parents=True, exist_ok=True)
    events_path = lib_dir / "events.jsonl"
    payload_lines = [json.dumps(event.to_dict()) for event in events]
    payload = "\n".join(payload_lines)
    if payload:
        payload += "\n"
    temp_path = lib_dir / f".{events_path.name}.tmp"
    temp_path.write_text(payload, encoding="utf-8")
    temp_path.replace(events_path)


def _read_library_events(lib_dir: Path) -> list[LibraryEvent]:
    """Read library events from events.jsonl."""
    events_path = lib_dir / "events.jsonl"
    if not events_path.exists():
        return []
    events: list[LibraryEvent] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        events.append(LibraryEvent.from_dict(payload))
    return events


def _validate_event_monotonicity(events: list[LibraryEvent]) -> list[dict[str, Any]]:
    """Validate library event ordering and timestamp monotonicity."""
    issues: list[dict[str, Any]] = []
    if not events:
        issues.append(
            {
                "type": "library_events_missing",
                "message": "No library events recorded.",
            }
        )
        return issues

    lib_id = events[0].lib_id
    created_indices = [
        index
        for index, event in enumerate(events)
        if event.event_type == LibraryEventType.LIBRARY_CREATED
    ]
    if not created_indices:
        issues.append(
            {
                "type": "library_created_missing",
                "lib_id": lib_id,
                "message": "Library has no LIBRARY_CREATED event.",
            }
        )
    elif created_indices[0] != 0:
        issues.append(
            {
                "type": "library_created_not_first",
                "lib_id": lib_id,
                "message": "LIBRARY_CREATED must be the first event.",
            }
        )
    if len(created_indices) > 1:
        issues.append(
            {
                "type": "library_created_duplicate",
                "lib_id": lib_id,
                "message": "Multiple LIBRARY_CREATED events detected.",
            }
        )

    for index, event in enumerate(events):
        if event.lib_id != lib_id:
            issues.append(
                {
                    "type": "conflicting_event",
                    "lib_id": lib_id,
                    "index": index,
                    "conflicting_lib_id": event.lib_id,
                    "message": (
                        f"Event at index {index} has lib_id '{event.lib_id}' "
                        f"which conflicts with expected '{lib_id}'."
                    ),
                }
            )

    last_timestamp: datetime | None = None
    for index, event in enumerate(events):
        try:
            timestamp = datetime.fromisoformat(event.timestamp)
        except ValueError:
            issues.append(
                {
                    "type": "library_event_timestamp_invalid",
                    "lib_id": lib_id,
                    "index": index,
                    "message": "Invalid timestamp format.",
                }
            )
            continue
        if last_timestamp and timestamp < last_timestamp:
            issues.append(
                {
                    "type": "library_event_timestamp_not_monotonic",
                    "lib_id": lib_id,
                    "index": index,
                    "message": "Library event timestamps must be monotonic.",
                }
            )
        last_timestamp = timestamp

    return issues


def _record_library_rename(
    manager: WorkspaceManager, lib_id: str, old_name: str, new_name: str, reason: str
) -> None:
    """Record a library rename event for future evolution workflows."""
    lib_dir = manager.structure.libraries_dir / lib_id
    event = LibraryEvent(
        event_type=LibraryEventType.LIBRARY_RENAMED,
        timestamp=datetime.now().isoformat(),
        lib_id=lib_id,
        metadata={"old_name": old_name, "new_name": new_name, "reason": reason},
        previous_state=None,
    )
    _write_library_event(lib_dir, event)


def _record_boundary_change(
    manager: WorkspaceManager,
    lib_id: str,
    added_files: list[str],
    removed_files: list[str],
    reason: str,
) -> None:
    """Record a boundary change event for future evolution workflows."""
    lib_dir = manager.structure.libraries_dir / lib_id
    event = LibraryEvent(
        event_type=LibraryEventType.BOUNDARY_CHANGED,
        timestamp=datetime.now().isoformat(),
        lib_id=lib_id,
        metadata={
            "added_files": added_files,
            "removed_files": removed_files,
            "reason": reason,
        },
        previous_state=None,
    )
    _write_library_event(lib_dir, event)


def _validate_library_ids(charters: list[LibraryCharter]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for charter in charters:
        if charter.lib_id in seen:
            issues.append(
                {
                    "type": "duplicate_library_id",
                    "lib_id": charter.lib_id,
                    "message": "Duplicate library ID found.",
                }
            )
        seen.add(charter.lib_id)
        if not LIB_ID_RE.match(charter.lib_id):
            issues.append(
                {
                    "type": "invalid_library_id",
                    "lib_id": charter.lib_id,
                    "message": "Library ID does not match lib_### format.",
                }
            )
    return issues


def _validate_evidence_sources(
    charters: list[LibraryCharter], manager: WorkspaceManager
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for charter in charters:
        for source in charter.evidence_sources:
            file_id = source.get("file_id")
            sections = source.get("sections", [])
            if file_id not in manager.state.file_manifest:
                issues.append(
                    {
                        "type": "unknown_file_reference",
                        "lib_id": charter.lib_id,
                        "file_id": file_id,
                        "message": "Evidence references unknown file ID.",
                    }
                )
                continue
            valid_sections = manager.state.section_manifest.get(file_id, [])
            for section in sections:
                if section not in valid_sections:
                    issues.append(
                        {
                            "type": "unknown_section_reference",
                            "lib_id": charter.lib_id,
                            "file_id": file_id,
                            "section": section,
                            "message": "Evidence references unknown section.",
                        }
                    )
    return issues


def _validate_overlap_resolutions(charters: list[LibraryCharter]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for charter in charters:
        for resolution in charter.overlap_resolutions:
            description = (resolution.get("description") or "").strip()
            decision = (resolution.get("decision") or "").strip()
            if decision:
                continue
            if not description:
                issues.append(
                    {
                        "type": "overlap_resolution_missing_decision",
                        "lib_id": charter.lib_id,
                        "description": resolution.get("description"),
                        "message": "Overlap resolution missing decision.",
                    }
                )
                continue
            # "No overlaps"/"none identified" are themselves valid resolution statements.
            lowered = description.lower()
            if "none identified" in lowered or re.search(
                r"\\bno\\b[^\\n\\.]{0,40}\\boverlap\\b", lowered
            ):
                continue
            issues.append(
                {
                    "type": "overlap_resolution_missing_decision",
                    "lib_id": charter.lib_id,
                    "description": description,
                    "message": "Overlap resolution missing decision.",
                }
            )
    return issues


def _format_charter(charter: LibraryCharter) -> str:
    lines = [f"# Library Charter: {charter.lib_id}", ""]
    lines.extend(["## Intent", charter.intent or "", ""])
    lines.extend(["## Boundaries", charter.boundaries or "", ""])
    lines.append("## Responsibilities")
    if charter.responsibilities:
        for item in charter.responsibilities:
            lines.append(f"- {item}")
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Evidence")
    if charter.evidence_sources:
        for source in charter.evidence_sources:
            file_id = source.get("file_id")
            sections = source.get("sections", [])
            for section in sections:
                lines.append(f"- [{file_id}::{section}]")
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Overlap Resolutions")
    if charter.overlap_resolutions:
        for resolution in charter.overlap_resolutions:
            description = resolution.get("description", "")
            decision = resolution.get("decision", "")
            if decision:
                lines.append(f"- {description} -> {decision}")
            else:
                lines.append(f"- {description}")
    else:
        lines.append("- None")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _build_library_index(charters: list[LibraryCharter]) -> str:
    lines = ["# Library Index", ""]
    for charter in charters:
        intent = charter.intent or "Intent not provided"
        lines.append(f"- {charter.lib_id}: {intent}")
    return "\n".join(lines).strip() + "\n"


def _write_library_artifacts(
    manager: WorkspaceManager, charter: LibraryCharter, created_from: list[str]
) -> None:
    lib_dir = manager.structure.libraries_dir / charter.lib_id
    lib_dir.mkdir(parents=True, exist_ok=True)

    charter_path = lib_dir / "charter.md"
    charter_path.write_text(_format_charter(charter), encoding="utf-8")

    evidence_path = lib_dir / "evidence.json"
    evidence_payload = {"sources": charter.evidence_sources}
    evidence_path.write_text(json.dumps(evidence_payload, indent=2), encoding="utf-8")

    (lib_dir / "gaps.md").write_text("", encoding="utf-8")
    (lib_dir / "decisions.md").write_text("", encoding="utf-8")

    existing_events = _read_library_events(lib_dir)
    created_event = next(
        (
            event
            for event in existing_events
            if event.event_type == LibraryEventType.LIBRARY_CREATED
        ),
        None,
    )
    if created_event is None:
        initial_files = sorted(
            {
                str(source.get("file_id"))
                for source in charter.evidence_sources
                if source.get("file_id")
            }
        )
        created_event = LibraryEvent(
            event_type=LibraryEventType.LIBRARY_CREATED,
            timestamp=datetime.now().isoformat(),
            lib_id=charter.lib_id,
            metadata={
                "created_from": created_from,
                "initial_intent": charter.intent,
                "initial_files": initial_files,
            },
            previous_state=None,
        )
        _rewrite_library_events(lib_dir, [created_event, *existing_events])
    elif existing_events and existing_events[0].event_type != LibraryEventType.LIBRARY_CREATED:
        reordered = [created_event, *[event for event in existing_events if event != created_event]]
        _rewrite_library_events(lib_dir, reordered)


def synthesize_libraries(run_id: str) -> dict[str, Any]:
    """Synthesize libraries from Phase 1 summaries."""
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized. Run init before synthesis.")

    summarization_status = manager.state.phases[Phase.SUMMARIZATION.value].status
    if summarization_status != PhaseStatus.COMPLETED:
        raise RuntimeError("Summarization phase must be completed before synthesis.")

    manager.start_phase(Phase.LIBRARY_SYNTHESIS)

    issues: list[dict[str, Any]] = []

    label_results = label_all_files(manager)
    file_labels = label_results.get("file_labels", {})
    issues.extend(label_results.get("issues", []))

    # Build and validate library shapes

    library_shapes = build_library_shapes(file_labels)
    shape_issues = validate_library_shapes(library_shapes)
    issues.extend(shape_issues)

    # Persist library shapes for Phase 8 overlap reasoning
    manager.write_library_shapes(library_shapes)

    label_clusters = aggregate_labels(file_labels)
    manager.structure.libraries_dir.mkdir(parents=True, exist_ok=True)
    clusters_path = manager.structure.libraries_dir / "label_clusters.json"
    clusters_path.write_text(json.dumps(label_clusters, indent=2), encoding="utf-8")

    try:
        refined_labels = refine_library_labels(label_clusters, manager)
    except Exception as exc:
        manager.save_state()
        manager.fail_phase(Phase.LIBRARY_SYNTHESIS, error=f"Label refinement failed: {exc}")
        return {
            "libraries_created": 0,
            "issues": [{"type": "label_refinement_failed", "message": str(exc)}],
        }

    if not refined_labels:
        manager.save_state()
        manager.fail_phase(Phase.LIBRARY_SYNTHESIS, error="No refined labels returned")
        return {"libraries_created": 0, "issues": issues}

    created_from_map: dict[str, list[str]] = {}
    for item in refined_labels:
        lib_id = str(item.get("lib_id", "")).strip()
        merged_from = item.get("merged_from", [])
        if isinstance(merged_from, list):
            created_from_map[lib_id] = [
                str(label).strip() for label in merged_from if str(label).strip()
            ]
        else:
            created_from_map[lib_id] = []

    charter_results = generate_all_charters(refined_labels, file_labels, manager)
    charters = list(charter_results)
    if isinstance(charter_results, CharterResults):
        issues.extend(charter_results.issues)

    if not charters:
        manager.fail_phase(Phase.LIBRARY_SYNTHESIS, error="No libraries synthesized")
        return {"libraries_created": 0, "issues": issues}

    issues.extend(_validate_library_ids(charters))
    issues.extend(_validate_evidence_sources(charters, manager))
    issues.extend(_validate_overlap_resolutions(charters))

    id_issues = [i for i in issues if i["type"] in ("invalid_library_id", "duplicate_library_id")]
    if id_issues:
        manager.fail_phase(Phase.LIBRARY_SYNTHESIS, error="Invalid library IDs")
        return {"libraries_created": 0, "issues": id_issues}

    try:
        overlap_decisions = resolve_all_overlaps(charters, manager)
    except Exception as exc:
        issues.append(
            {
                "type": "overlap_resolution_failed",
                "message": f"Overlap resolution failed: {exc}",
            }
        )
        overlap_decisions = []

    concern_assignment_metrics = {
        "total_assigned": 0,
        "total_gaps": 0,
        "total_decisions": 0,
    }

    try:
        judge_result = judge_concern_assignments(charters, manager)
        issues.extend(judge_result.get("issues", []))
        issues.extend(_validate_concern_coverage(judge_result, manager))

        if judge_result.get("gaps") or judge_result.get("decisions"):
            evidence_path = _write_concern_evidence(judge_result, manager)
            logger.info("Wrote concern evidence to %s", evidence_path)

        total_concerns = (
            len(judge_result.get("assignments", []))
            + len(judge_result.get("gaps", []))
            + len(judge_result.get("decisions", []))
        )
        if total_concerns == 0:
            issues.append(
                {
                    "type": "concern_assignment_incomplete",
                    "message": "Judge returned no assignments, gaps, or decisions",
                }
            )

        concern_assignment_metrics = {
            "total_assigned": len(judge_result.get("assignments", [])),
            "total_gaps": len(judge_result.get("gaps", [])),
            "total_decisions": len(judge_result.get("decisions", [])),
        }
    except Exception as exc:
        issues.append(
            {
                "type": "concern_assignment_failed",
                "message": f"Concern assignment judge failed: {exc}",
            }
        )

    index_content = _build_library_index(charters)
    index_path = manager.structure.libraries_dir / "library_index.md"
    index_path.write_text(index_content, encoding="utf-8")

    tracker = ProgressTracker(
        total=len(charters),
        description="Creating libraries",
        manager=manager,
    )

    for charter in charters:
        created_from = created_from_map.get(charter.lib_id, [])
        _write_library_artifacts(manager, charter, created_from)
        tracker.update(status=charter.lib_id)

    tracker.finish()

    for charter in charters:
        lib_dir = manager.structure.libraries_dir / charter.lib_id
        event_issues = _validate_event_monotonicity(_read_library_events(lib_dir))
        for issue in event_issues:
            if "lib_id" not in issue:
                issue["lib_id"] = charter.lib_id
            issues.append(issue)

    libraries_dir = manager.structure.libraries_dir
    library_dirs = {
        path.name
        for path in libraries_dir.iterdir()
        if path.is_dir() and LIB_ID_RE.match(path.name)
    }
    allocated_ids = manager.state.allocated_library_ids
    missing_dirs = sorted(allocated_ids - library_dirs)
    extra_dirs = sorted(library_dirs - allocated_ids)
    if missing_dirs:
        issues.append(
            {
                "type": "missing_library_directory",
                "lib_ids": missing_dirs,
                "message": "Allocated library IDs missing directories.",
            }
        )
    if extra_dirs:
        issues.append(
            {
                "type": "untracked_library_directory",
                "lib_ids": extra_dirs,
                "message": "Library directories exist without allocated IDs.",
            }
        )

    phase_result = manager.state.phases[Phase.LIBRARY_SYNTHESIS.value]
    phase_result.issues = issues

    overlap_resolutions: list[dict[str, str]] = []
    for charter in charters:
        for resolution in charter.overlap_resolutions:
            overlap_resolutions.append(
                {
                    "lib_id": charter.lib_id,
                    "description": resolution.get("description", ""),
                    "decision": resolution.get("decision", ""),
                }
            )

    outputs = {
        "libraries_count": len(charters),
        "overlap_resolutions": overlap_resolutions,
        "concern_assignments": concern_assignment_metrics,
    }
    if overlap_decisions:
        outputs["overlap_decisions"] = overlap_decisions

    manager.complete_phase(Phase.LIBRARY_SYNTHESIS, outputs=outputs)
    manager.save_state()

    return {
        "libraries_created": len(charters),
        "issues": issues,
        "outputs": outputs,
        "library_index": index_path,
    }
