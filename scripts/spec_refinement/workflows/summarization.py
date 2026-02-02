"""File summarization workflow for Phase 1 spec refinement."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from spec_manager.refinement.formats import (
    EVIDENCE_POINTER_RE,
    FileSummary,
    normalize_compound_pointers,
    parse_evidence_pointer,
    parse_file_summary,
)

from scripts.spec_refinement.workspace import Phase, PhaseStatus, WorkspaceManager

from .agent_utils import run_agent
from .progress import ProgressTracker
from .validation_utils import (
    build_file_id_lookup,
    build_section_alias_map,
    build_section_id_lookup,
    resolve_section_reference,
    strip_invalid_file_pointers,
)

MAX_WORKERS = 4


def _build_summary_prompt(
    file_id: str, file_path: Path, content: str, manager: WorkspaceManager
) -> str:
    sections_data = manager.read_file_sections(file_id) or {}
    section_ids = [
        s_id
        for section in sections_data.get("sections", [])
        if isinstance(section, dict)
        and (s_id := section.get("section_id")) is not None
        and isinstance(s_id, str)
    ]
    section_list = ", ".join(section_ids) if section_ids else "None"
    file_entry = manager.state.file_manifest.get(file_id, {})
    if isinstance(file_entry, dict):
        relpath = file_entry.get("relpath", str(file_path))
    elif isinstance(file_entry, str):
        relpath = file_entry
    else:
        relpath = str(file_path)
    example_section = section_ids[0] if section_ids else f"SEC-{file_id}-0001"
    example_pointer = f"[spec_snapshot/{relpath}::{example_section}]"
    lines = [
        "## OUTPUT CONTRACT (REQUIRED)",
        "",
        "Return structured markdown with EXACTLY these headings:",
        "- Algorithms",
        "- Components",
        "- Workflows",
        "- Candidate Responsibilities",
        "- Dependencies",
        "- Evidence Map",
        "",
        "REQUIRED RULES:",
        (
            "- Every inventory item MUST include evidence pointers in format "
            "[spec_snapshot/<relpath>::SECTION_ID]"
        ),
        "- Evidence pointers MUST cite contributing sections, not entire files",
        "- Section IDs MUST match the Known Sections allowlist exactly",
        f"- Valid section IDs for {file_id}: {section_list}",
        "- Do NOT invent section IDs",
        "- Keep summaries concise, focused on WHAT (not HOW)",
        "",
        "FORBIDDEN:",
        "- Citing entire files without section IDs",
        "- Inventing section IDs not in the allowlist",
        "- Including implementation details (HOW)",
        "",
        "## INPUT DATA",
        "",
        f"File ID: {file_id}",
        f"File Path: {file_path}",
        "",
        "Source File Content:",
        f"{content}",
        "",
        "## OUTPUT FORMAT",
        "",
        "# File Summary: {file_id}",
        "File ID: {file_id}",
        "",
        "## Algorithms",
        f"- <name> | <intent> | Evidence: {example_pointer}",
        "",
        "## Components",
        f"- <name> | <intent> | Evidence: {example_pointer}",
        "",
        "## Workflows",
        f"- <name> | <intent> | Evidence: {example_pointer}",
        "",
        "## Candidate Responsibilities",
        f"- <description> | Evidence: {example_pointer}",
        "",
        "## Dependencies",
        "- <dependency>",
        "",
        "## Evidence Map",
        f"- <SECTION_ID>: {example_pointer}",
        "",
    ]
    return "\n".join(lines)


def _validate_evidence_pointers(
    content: str, manager: WorkspaceManager, file_id: str
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    pointer_matches = list(EVIDENCE_POINTER_RE.finditer(content))
    if not pointer_matches:
        issues.append(
            {
                "type": "missing_evidence_pointers",
                "file_id": file_id,
                "message": "No evidence pointers found.",
            }
        )
        return issues

    file_id_lookup = build_file_id_lookup(
        manager.state.file_manifest, manager.structure.spec_snapshot_dir
    )
    section_alias_map = build_section_alias_map(manager.state.section_manifest)

    for match in pointer_matches:
        parsed = parse_evidence_pointer(match.group(0))
        if not parsed:
            continue
        file_ref = parsed["file_ref"]
        section_ref = parsed["section_ref"]
        resolved_file_id = file_id_lookup.get(file_ref)
        if resolved_file_id is None:
            issues.append(
                {
                    "type": "unknown_file_reference",
                    "file_id": file_id,
                    "pointer": match.group(0),
                    "message": f"Unknown file reference: {file_ref}",
                }
            )
            continue
        sections_data = manager.read_file_sections(resolved_file_id) or {}
        section_lookup = build_section_id_lookup(resolved_file_id, sections_data)
        if section_ref in section_lookup:
            continue
        canonical_section = resolve_section_reference(
            section_ref,
            resolved_file_id,
            section_alias_map,
            sections_data=sections_data,
        )
        if canonical_section is None:
            issues.append(
                {
                    "type": "unknown_section_reference",
                    "file_id": file_id,
                    "pointer": match.group(0),
                    "message": (
                        f"Unknown section reference: {section_ref} (file: {resolved_file_id})"
                    ),
                }
            )

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        lowered = stripped.lower()
        if "evidence" in lowered and not EVIDENCE_POINTER_RE.search(stripped):
            # Allow explicit "none specified" placeholders without pointers.
            if "evidence: n/a" in lowered or "evidence: none" in lowered:
                continue
            if lowered.startswith("- none specified"):
                continue
            issues.append(
                {
                    "type": "malformed_evidence_pointer",
                    "file_id": file_id,
                    "line": stripped,
                    "message": "Evidence line missing pointer format.",
                }
            )

    return issues


def _process_file(file_id: str, file_path: Path, manager: WorkspaceManager) -> dict[str, Any]:
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"file_id": file_id, "error": f"Failed to read file: {exc}"}

    prompt = _build_summary_prompt(file_id, file_path, content, manager)

    try:
        output = run_agent(
            agent_name="glm-file-what-summarizer",
            prompt=prompt,
            workspace=manager.workspace_path,
        )
    except RuntimeError as exc:
        return {"file_id": file_id, "error": f"Agent execution failed: {exc}"}

    output = normalize_compound_pointers(output)
    output = strip_invalid_file_pointers(output, manager.state.file_manifest)

    summary_path = manager.structure.summaries_dir / f"{file_id}.what.md"
    summary_path.write_text(output, encoding="utf-8")

    parsed_summary: FileSummary | None = None
    try:
        parsed_summary = parse_file_summary(output)
    except Exception as exc:  # pragma: no cover - defensive logging
        return {
            "file_id": file_id,
            "error": f"Failed to parse summary output: {exc}",
        }

    issues = _validate_evidence_pointers(output, manager, file_id)
    format_evidence: list[dict[str, Any]] = []
    if issues:
        from .repair import ArtifactType, get_repair_model, repair_artifact

        try:
            sections_data = manager.read_file_sections(file_id)
            if sections_data is None:
                section_ids = manager.get_section_labels(file_id)
            else:
                section_ids = [
                    str(section.get("section_id"))
                    for section in sections_data.get("sections", [])
                    if isinstance(section, dict) and isinstance(section.get("section_id"), str)
                ]
            file_refs = []
            for entry in manager.state.file_manifest.values():
                relpath = entry.get("relpath") if isinstance(entry, dict) else entry
                if isinstance(relpath, str) and relpath:
                    file_refs.append(f"spec_snapshot/{relpath}")
            repaired_output, repair_evidence = repair_artifact(
                output=output,
                errors=issues,
                allowlists={
                    "file_refs": sorted(set(file_refs)),
                    "sections": section_ids,
                },
                artifact_type=ArtifactType.SUMMARY,
                model_override=get_repair_model(),
                manager=manager,
            )
            format_evidence.extend(repair_evidence)
            repaired_issues = _validate_evidence_pointers(repaired_output, manager, file_id)
            if not repaired_issues:
                output = repaired_output
                issues = []
                summary_path.write_text(output, encoding="utf-8")
        except Exception as exc:
            issues.append(
                {
                    "type": "repair_failed",
                    "file_id": file_id,
                    "message": f"Repair attempt failed: {exc}",
                }
            )

    return {
        "file_id": file_id,
        "output_path": summary_path,
        "summary": parsed_summary,
        "issues": issues,
        "format_evidence": format_evidence,
    }


def summarize_all(run_id: str, parallel: bool = True) -> dict[str, Any]:
    """Summarize all workspace files with the file summarization agent."""
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized. Run init before summarization.")

    sectionization_result = manager.state.phases.get(Phase.SECTIONIZATION.value)
    if not sectionization_result or sectionization_result.status != PhaseStatus.COMPLETED:
        raise RuntimeError(
            "Phase 1 sectionization must be completed before summarization. "
            "Run 'spec sectionize' first."
        )

    manager.start_phase(Phase.SUMMARIZATION)
    files = manager.get_all_files()
    total_files = len(files)

    tracker = ProgressTracker(
        total=total_files,
        description="Summarizing files",
        manager=manager,
    )

    successes = 0
    errors: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    format_evidence: list[dict[str, Any]] = []

    if parallel and total_files > 0:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(_process_file, file_id, file_path, manager): file_id
                for file_id, file_path in files.items()
            }
            for future in as_completed(futures):
                result = future.result()
                format_evidence.extend(result.get("format_evidence", []))
                if "error" in result:
                    errors.append(result)
                else:
                    successes += 1
                    issues.extend(result.get("issues", []))
                tracker.update(status=result.get("file_id", ""))
    else:
        for file_id, file_path in files.items():
            result = _process_file(file_id, file_path, manager)
            format_evidence.extend(result.get("format_evidence", []))
            if "error" in result:
                errors.append(result)
            else:
                successes += 1
                issues.extend(result.get("issues", []))
            tracker.update(status=file_id)

    tracker.finish()

    phase_result = manager.state.phases[Phase.SUMMARIZATION.value]
    phase_result.issues = errors + issues

    failure_ratio = (len(errors) / total_files) if total_files else 0
    outputs = {"summaries_count": successes, "files_processed": total_files}

    if total_files > 0 and failure_ratio > 0.5:
        manager.fail_phase(Phase.SUMMARIZATION, error="Too many failures")
    else:
        manager.complete_phase(Phase.SUMMARIZATION, outputs=outputs)

    return {
        "summaries_written": successes,
        "files_processed": total_files,
        "errors": errors,
        "issues": issues,
        "format_evidence": format_evidence,
        "outputs": outputs,
    }
