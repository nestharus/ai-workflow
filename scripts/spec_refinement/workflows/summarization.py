"""File summarization workflow for Phase 1 spec refinement."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from scripts.dev.agent_runner import AgentRunner
from scripts.spec_refinement.workspace import Phase, WorkspaceManager

from .formats import EVIDENCE_POINTER_RE, FileSummary, parse_file_summary
from .progress import ProgressTracker

MAX_WORKERS = 4


def _build_summary_prompt(file_id: str, file_path: Path, sections: list[str], content: str) -> str:
    section_list = ", ".join(sections) if sections else "None"
    lines = [
        "Summarize the following spec file for Phase 1. Provide structured markdown with "
        "the exact headings below. Use evidence pointers in the format [FILE_ID::SECTION].",
        "",
        f"File ID: {file_id}",
        f"File Path: {file_path}",
        f"Known Sections: {section_list}",
        "",
        f"# File Summary: {file_id}",
        f"File ID: {file_id}",
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
        "---",
        "",
        "FILE CONTENT:",
        f"{content}",
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

    file_id_lookup: dict[str, str] = {}
    for file_id, path_str in manager.state.file_manifest.items():
        file_id_lookup[file_id] = file_id
        file_id_lookup[path_str] = file_id
        try:
            file_id_lookup[str(Path(path_str).resolve())] = file_id
        except OSError:
            continue

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
        valid_sections = manager.state.section_manifest.get(resolved_file_id, [])
        if section_ref not in valid_sections:
            issues.append(
                {
                    "type": "unknown_section_reference",
                    "file_id": file_id,
                    "pointer": match.group(0),
                    "message": f"Unknown section reference: {section_ref}",
                }
            )

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "evidence" in stripped.lower() and not EVIDENCE_POINTER_RE.search(stripped):
            issues.append(
                {
                    "type": "malformed_evidence_pointer",
                    "file_id": file_id,
                    "line": stripped,
                    "message": "Evidence line missing pointer format.",
                }
            )

    return issues


def _process_file(
    file_id: str, file_path: Path, manager: WorkspaceManager, config_path: Path
) -> dict[str, Any]:
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"file_id": file_id, "error": f"Failed to read file: {exc}"}

    runner = AgentRunner.from_agent_name(
        "glm-file-what-summarizer", config_path, prompt_chars=len(content)
    )
    sections = manager.get_section_labels(file_id)
    prompt = _build_summary_prompt(file_id, file_path, sections, content)

    try:
        output = runner.run(prompt)
    except RuntimeError as exc:
        return {"file_id": file_id, "error": f"Agent execution failed: {exc}"}

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

    return {
        "file_id": file_id,
        "output_path": summary_path,
        "summary": parsed_summary,
        "issues": issues,
    }


def summarize_all(run_id: str, config_path: Path, parallel: bool = True) -> dict[str, Any]:
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
                executor.submit(_process_file, file_id, file_path, manager, config_path): file_id
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
            result = _process_file(file_id, file_path, manager, config_path)
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
