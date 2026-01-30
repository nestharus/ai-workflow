"""Library synthesis workflow for Phase 2 spec refinement."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from scripts.spec_refinement.workspace import Phase, PhaseStatus, WorkspaceManager

from .agent_utils import run_agent
from .formats import LibraryCharter, normalize_compound_pointers, parse_library_synthesis
from .progress import ProgressTracker

LIB_ID_RE = re.compile(r"^lib_\d{3}$")


def _build_synthesis_prompt(summary_bundle: dict[str, str]) -> str:
    sections = ["Synthesize libraries for Phase 2 using the summaries below."]
    sections.append("Use the exact markdown structure below with headings and bullet lists.")
    sections.append("Library IDs must follow lib_001, lib_002, etc.")
    sections.append("Evidence pointers must use [FILE_ID::SECTION].")
    sections.append("")
    sections.append("## Library Index")
    sections.append("- lib_001: <intent>")
    sections.append("")
    sections.append("## Library Charters")
    sections.append("### lib_001")
    sections.append("#### Intent")
    sections.append("<intent text>")
    sections.append("")
    sections.append("#### Boundaries")
    sections.append("<boundaries text>")
    sections.append("")
    sections.append("#### Responsibilities")
    sections.append("- <responsibility>")
    sections.append("")
    sections.append("#### Evidence")
    sections.append("- [FILE_ID::SECTION]")
    sections.append("")
    sections.append("#### Overlap Resolutions")
    sections.append("- <overlap description> -> <decision>")
    sections.append("")
    sections.append("---")
    sections.append("")
    sections.append("# Summaries")
    for file_id, summary in summary_bundle.items():
        sections.append(f"## {file_id}")
        sections.append(summary)
        sections.append("")
    return "\n".join(sections)


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


def _write_library_artifacts(manager: WorkspaceManager, charter: LibraryCharter) -> None:
    lib_dir = manager.structure.libraries_dir / charter.lib_id
    lib_dir.mkdir(parents=True, exist_ok=True)

    charter_path = lib_dir / "charter.md"
    charter_path.write_text(_format_charter(charter), encoding="utf-8")

    evidence_path = lib_dir / "evidence.json"
    evidence_payload = {"sources": charter.evidence_sources}
    evidence_path.write_text(json.dumps(evidence_payload, indent=2), encoding="utf-8")

    (lib_dir / "gaps.md").write_text("", encoding="utf-8")
    (lib_dir / "decisions.md").write_text("", encoding="utf-8")


def synthesize_libraries(run_id: str) -> dict[str, Any]:
    """Synthesize libraries from Phase 1 summaries."""
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized. Run init before synthesis.")

    summarization_status = manager.state.phases[Phase.SUMMARIZATION.value].status
    if summarization_status != PhaseStatus.COMPLETED:
        raise RuntimeError("Summarization phase must be completed before synthesis.")

    manager.start_phase(Phase.LIBRARY_SYNTHESIS)

    summary_files = sorted(manager.structure.summaries_dir.glob("*.what.md"))
    summary_bundle: dict[str, str] = {}
    for summary_path in summary_files:
        file_id = summary_path.stem.replace(".what", "")
        summary_bundle[file_id] = summary_path.read_text(encoding="utf-8")

    prompt = _build_synthesis_prompt(summary_bundle)
    try:
        output = run_agent(
            agent_name="opus-library-synthesizer",
            prompt=prompt,
            workspace=manager.workspace_path,
        )
    except RuntimeError as exc:
        manager.fail_phase(Phase.LIBRARY_SYNTHESIS, error=f"Agent execution failed: {exc}")
        return {"libraries_created": 0, "error": str(exc)}

    output = normalize_compound_pointers(output)
    try:
        charters, index_content = parse_library_synthesis(output)
    except Exception as exc:  # pragma: no cover - defensive logging
        manager.fail_phase(Phase.LIBRARY_SYNTHESIS, error=f"Failed to parse output: {exc}")
        return {"libraries_created": 0, "error": str(exc)}

    issues: list[dict[str, Any]] = []
    issues.extend(_validate_library_ids(charters))
    issues.extend(_validate_evidence_sources(charters, manager))
    issues.extend(_validate_overlap_resolutions(charters))
    if issues:
        from .repair import ArtifactType, repair_artifact

        try:
            repaired_output = repair_artifact(
                output=output,
                errors=issues,
                allowlists={
                    "file_ids": list(manager.state.file_manifest.keys()),
                    "library_ids": [charter.lib_id for charter in charters],
                },
                artifact_type=ArtifactType.CHARTER,
                manager=manager,
            )
            repaired_charters, repaired_index = parse_library_synthesis(repaired_output)
            repaired_issues: list[dict[str, Any]] = []
            repaired_issues.extend(_validate_library_ids(repaired_charters))
            repaired_issues.extend(_validate_evidence_sources(repaired_charters, manager))
            repaired_issues.extend(_validate_overlap_resolutions(repaired_charters))

            if not repaired_issues:
                charters = repaired_charters
                index_content = repaired_index
                issues = []
        except Exception as exc:
            issues.append(
                {
                    "type": "repair_failed",
                    "message": f"Charter repair failed: {exc}",
                }
            )

    id_issues = [i for i in issues if i["type"] in ("invalid_library_id", "duplicate_library_id")]
    if id_issues:
        manager.fail_phase(Phase.LIBRARY_SYNTHESIS, error="Invalid library IDs")
        return {"libraries_created": 0, "issues": id_issues}

    if not charters:
        manager.fail_phase(Phase.LIBRARY_SYNTHESIS, error="No libraries synthesized")
        return {"libraries_created": 0, "issues": issues}

    manager.structure.libraries_dir.mkdir(parents=True, exist_ok=True)
    index_path = manager.structure.libraries_dir / "library_index.md"
    index_path.write_text(index_content, encoding="utf-8")

    tracker = ProgressTracker(
        total=len(charters),
        description="Creating libraries",
        manager=manager,
    )

    for charter in charters:
        _write_library_artifacts(manager, charter)
        tracker.update(status=charter.lib_id)

    tracker.finish()

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
    }
    manager.complete_phase(Phase.LIBRARY_SYNTHESIS, outputs=outputs)

    return {
        "libraries_created": len(charters),
        "issues": issues,
        "outputs": outputs,
        "library_index": index_path,
    }
