"""File summarization workflow for Phase 1 spec refinement."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from scripts.spec_refinement.workspace import Phase, WorkspaceManager

from .agent_utils import run_agent
from .formats import (
    EVIDENCE_POINTER_RE,
    FileSummary,
    normalize_compound_pointers,
    parse_file_summary,
)
from .progress import ProgressTracker
from .validation_utils import (
    build_file_id_lookup,
    build_section_alias_map,
    resolve_section_reference,
    strip_invalid_file_pointers,
)

MAX_WORKERS = 4


def _build_summary_prompt(file_id: str, file_path: Path, sections: list[str], content: str) -> str:
    section_list = ", ".join(sections) if sections else "None"
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
        "- Every inventory item MUST include evidence pointers in format [FILE_ID::SECTION]",
        "- Evidence pointers MUST cite contributing sections, not entire files",
        "- Section labels MUST match the Known Sections allowlist exactly",
        f"- Valid section labels for {file_id}: {section_list}",
        "- Do NOT invent section labels",
        "- Keep summaries concise, focused on WHAT (not HOW)",
        "",
        "FORBIDDEN:",
        "- Citing entire files without section labels",
        "- Inventing section labels not in the allowlist",
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
        "- <name> | <intent> | Evidence: [FILE_ID::SECTION]",
        "",
        "## Components",
        "- <name> | <intent> | Evidence: [FILE_ID::SECTION]",
        "",
        "## Workflows",
        "- <name> | <intent> | Evidence: [FILE_ID::SECTION]",
        "",
        "## Candidate Responsibilities",
        "- <description> | Evidence: [FILE_ID::SECTION]",
        "",
        "## Dependencies",
        "- <dependency>",
        "",
        "## Evidence Map",
        "- <SECTION_ID>: [FILE_ID::SECTION_ID]",
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

    file_id_lookup = build_file_id_lookup(manager.state.file_manifest)
    section_alias_map = build_section_alias_map(manager.state.section_manifest)

    for match in pointer_matches:
        file_ref = match.group(1).strip()
        section_ref = match.group(2).strip()
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
        canonical_section = resolve_section_reference(
            section_ref,
            resolved_file_id,
            section_alias_map,
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

    sections = manager.get_section_labels(file_id)
    prompt = _build_summary_prompt(file_id, file_path, sections, content)

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
    if issues:
        from .repair import ArtifactType, get_repair_model, repair_artifact

        try:
            repaired_output = repair_artifact(
                output=output,
                errors=issues,
                allowlists={
                    "file_ids": list(manager.state.file_manifest.keys()),
                    "sections": manager.state.section_manifest.get(file_id, []),
                },
                artifact_type=ArtifactType.SUMMARY,
                model_override=get_repair_model(),
                manager=manager,
            )
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
    }


def summarize_all(run_id: str, parallel: bool = True) -> dict[str, Any]:
    """Summarize all workspace files with the file summarization agent."""
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized. Run init before summarization.")

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

    if parallel and total_files > 0:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(_process_file, file_id, file_path, manager): file_id
                for file_id, file_path in files.items()
            }
            for future in as_completed(futures):
                result = future.result()
                if "error" in result:
                    errors.append(result)
                else:
                    successes += 1
                    issues.extend(result.get("issues", []))
                tracker.update(status=result.get("file_id", ""))
    else:
        for file_id, file_path in files.items():
            result = _process_file(file_id, file_path, manager)
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
        "outputs": outputs,
    }
