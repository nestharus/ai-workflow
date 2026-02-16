"""Library synthesis workflow for Phase 2 spec refinement."""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from spec_manager.refinement.formats import (
    EVIDENCE_POINTER_RE,
    LibraryCharter,
    LibraryEvent,
    LibraryEventType,
    build_evidence_pointer,
    migrate_evidence_json,
    migrate_pointers_to_new_format,
    parse_evidence_pointer,
)
from spec_manager.refinement.progress import ProgressTracker
from spec_manager.refinement.validation_utils import build_file_id_lookup, build_section_id_lookup
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

LIB_ID_RE = re.compile(r"^LIB-\d{4}$")
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


def _validate_event_monotonicity(
    events: list[LibraryEvent], *, expected_lib_id: str | None = None
) -> list[dict[str, Any]]:
    """Validate library event ordering, ID consistency, and timestamp monotonicity."""
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
    if expected_lib_id and lib_id != expected_lib_id:
        issues.append(
            {
                "type": "library_id_format_mismatch",
                "lib_id": lib_id,
                "expected_lib_id": expected_lib_id,
                "message": "Library event lib_id does not match directory name.",
            }
        )
    if not LIB_ID_RE.match(lib_id):
        issues.append(
            {
                "type": "library_event_invalid_id",
                "lib_id": lib_id,
                "message": "Library event lib_id does not match LIB-#### format.",
            }
        )
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
        if not LIB_ID_RE.match(event.lib_id):
            issues.append(
                {
                    "type": "library_event_invalid_id",
                    "lib_id": event.lib_id,
                    "index": index,
                    "message": "Library event lib_id does not match LIB-#### format.",
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


def _deduplicate_library_ids(charters: list[LibraryCharter]) -> list[LibraryCharter]:
    """Rename duplicate library IDs to ensure uniqueness.

    When the LLM produces multiple charters with the same ID, rename
    duplicates to the next available LIB-XXXX number.
    """
    seen: set[str] = set()
    max_ordinal = 0
    for charter in charters:
        match = LIB_ID_RE.match(charter.lib_id)
        if match:
            ordinal = int(charter.lib_id.split("-")[1])
            max_ordinal = max(max_ordinal, ordinal)

    result: list[LibraryCharter] = []
    for charter in charters:
        if charter.lib_id in seen:
            max_ordinal += 1
            charter = dataclasses.replace(charter, lib_id=f"LIB-{max_ordinal:04d}")
        seen.add(charter.lib_id)
        result.append(charter)

    return result


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
                    "message": "Library ID does not match LIB-#### format.",
                }
            )
    return issues


def _validate_evidence_sources(
    charters: list[LibraryCharter], manager: WorkspaceManager
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    file_lookup = build_file_id_lookup(
        manager.state.file_manifest, manager.structure.spec_snapshot_dir
    )
    for charter in charters:
        for source in charter.evidence_sources:
            if not isinstance(source, dict):
                issues.append(
                    {
                        "type": "invalid_evidence_source",
                        "lib_id": charter.lib_id,
                        "message": "Evidence source must be a mapping with file_id and sections.",
                    }
                )
                continue
            file_ref = source.get("file_id")
            if not isinstance(file_ref, str) or not file_ref:
                issues.append(
                    {
                        "type": "unknown_file_reference",
                        "lib_id": charter.lib_id,
                        "file_id": file_ref,
                        "message": "Evidence references unknown file ID.",
                    }
                )
                continue
            resolved_file_id = file_lookup.get(file_ref)
            if resolved_file_id is None:
                issues.append(
                    {
                        "type": "unknown_file_reference",
                        "lib_id": charter.lib_id,
                        "file_id": file_ref,
                        "message": "Evidence references unknown file ID.",
                    }
                )
                continue
            sections = source.get("sections", [])
            if not isinstance(sections, list):
                sections = []
            valid_sections = manager.state.section_manifest.get(resolved_file_id, [])
            for section in sections:
                if section not in valid_sections:
                    issues.append(
                        {
                            "type": "unknown_section_reference",
                            "lib_id": charter.lib_id,
                            "file_id": resolved_file_id,
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


def validate_library_ids(charters: list[LibraryCharter]) -> list[dict[str, Any]]:
    """Public projection for charter library ID validation."""
    return _validate_library_ids(charters)


def validate_evidence_sources(
    charters: list[LibraryCharter], manager: WorkspaceManager
) -> list[dict[str, Any]]:
    """Public projection for charter evidence-source validation."""
    return _validate_evidence_sources(charters, manager)


def validate_overlap_resolutions(charters: list[LibraryCharter]) -> list[dict[str, Any]]:
    """Public projection for overlap-resolution validation."""
    return _validate_overlap_resolutions(charters)


def _format_charter(charter: LibraryCharter, manager: WorkspaceManager) -> str:
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
    file_lookup = build_file_id_lookup(
        manager.state.file_manifest, manager.structure.spec_snapshot_dir
    )
    section_lookup_cache: dict[str, dict[str, str]] = {}
    if charter.evidence_sources:
        for source in charter.evidence_sources:
            if not isinstance(source, dict):
                continue
            file_ref = source.get("file_id")
            if not isinstance(file_ref, str) or not file_ref:
                continue
            resolved_file_id = file_lookup.get(file_ref)
            if resolved_file_id is None:
                logger.warning(
                    "Skipping evidence source for %s with unknown file reference '%s'",
                    charter.lib_id,
                    file_ref,
                )
                continue
            if resolved_file_id not in section_lookup_cache:
                sections_data = manager.read_file_sections(resolved_file_id) or {}
                section_lookup_cache[resolved_file_id] = build_section_id_lookup(
                    resolved_file_id, sections_data
                )
            section_lookup = section_lookup_cache[resolved_file_id]
            sections = source.get("sections", [])
            if not isinstance(sections, list):
                sections = []
            for section in sections:
                if not isinstance(section, str) or not section:
                    continue
                resolved_section = section_lookup.get(section, section)
                try:
                    pointer = build_evidence_pointer(
                        resolved_file_id, resolved_section, manager.state.file_manifest
                    )
                except KeyError as exc:
                    logger.warning(
                        "Skipping evidence pointer for %s (%s::%s): %s",
                        charter.lib_id,
                        resolved_file_id,
                        resolved_section,
                        exc,
                    )
                    continue
                lines.append(f"- {pointer}")
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
    charter_path.write_text(_format_charter(charter, manager), encoding="utf-8")

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

    charters = _deduplicate_library_ids(charters)
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

    pointers_migrated = 0
    migration_warnings: list[dict[str, Any]] = []

    def _count_legacy_pointers(text: str) -> int:
        count = 0
        for match in EVIDENCE_POINTER_RE.finditer(text):
            parsed = parse_evidence_pointer(match.group(0))
            if parsed and parsed["format"] == "legacy":
                count += 1
        return count

    for charter in charters:
        lib_dir = manager.structure.libraries_dir / charter.lib_id
        charter_path = lib_dir / "charter.md"
        if charter_path.exists():
            content = charter_path.read_text(encoding="utf-8")
            before_legacy = _count_legacy_pointers(content)
            migrated_content = migrate_pointers_to_new_format(content, manager)
            after_legacy = _count_legacy_pointers(migrated_content)
            migrated_count = max(0, before_legacy - after_legacy)
            if migrated_count:
                pointers_migrated += migrated_count
                logger.info(
                    "Migrated %s legacy pointers in %s",
                    migrated_count,
                    charter_path,
                )
            if migrated_content != content:
                charter_path.write_text(migrated_content, encoding="utf-8")
            if after_legacy > 0:
                warning = {
                    "type": "pointer_migration_incomplete",
                    "lib_id": charter.lib_id,
                    "remaining": after_legacy,
                    "message": "Legacy evidence pointers remain after migration.",
                }
                migration_warnings.append(warning)
                issues.append(warning)

        evidence_path = lib_dir / "evidence.json"
        if evidence_path.exists():
            report = migrate_evidence_json(evidence_path, manager)
            report_issues = report.get("issues", [])
            if isinstance(report_issues, list) and report_issues:
                for issue in report_issues:
                    if isinstance(issue, dict) and "lib_id" not in issue:
                        issue["lib_id"] = charter.lib_id
                    issues.append(issue)
                migration_warnings.extend(
                    [issue for issue in report_issues if isinstance(issue, dict)]
                )

    for charter in charters:
        lib_dir = manager.structure.libraries_dir / charter.lib_id
        event_issues = _validate_event_monotonicity(
            _read_library_events(lib_dir), expected_lib_id=charter.lib_id
        )
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
        "pointers_migrated": pointers_migrated,
        "migration_warnings": migration_warnings,
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
