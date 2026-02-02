"""Phase 1 sectionization workflow for spec refinement."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from spec_manager.refinement.core.gap import GapEvidence, GapSynthesizer
from spec_manager.refinement.workspace import Phase, WorkspaceManager
from spec_manager.schemas.sections import FileSections

from .agent_utils import run_agent
from .atom_emitter import emit_atoms
from .progress import ProgressTracker
from .schema_validator import (
    validate_atoms_schema,
    validate_sections_schema,
    validate_terms_schema,
)
from .section_validator import validate_sections

MAX_WORKERS = 4


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _read_snapshot_content(file_path: Path) -> tuple[str, int]:
    raw_bytes = file_path.read_bytes()
    content = raw_bytes.decode("utf-8")
    normalized = _normalize_newlines(content)
    return normalized, len(normalized.splitlines(keepends=False))


def _build_section_span_prompt(
    file_id: str,
    file_path: Path,
    content: str,
    total_lines: int,
) -> str:
    lines = [
        "## OUTPUT CONTRACT (REQUIRED)",
        "",
        "Return JSON array ONLY. No prose, no markdown, no code fences.",
        "REQUIRED RULES:",
        "- Output must be a JSON array of objects.",
        "- Each object MUST include: section_id, start_line, end_line, label.",
        f"- Section IDs MUST be SEC-{file_id}-{{ordinal:04d}} in line order (start at 0001).",
        "- start_line/end_line are 1-based, inclusive.",
        f"- Cover every line from 1..{total_lines} exactly once (no gaps, no overlaps).",
        "- Labels should be short and descriptive.",
        "",
        "## INPUT DATA",
        "",
        f"File ID: {file_id}",
        f"File Path: {file_path}",
        f"Total Lines: {total_lines}",
        "",
        "Source File Content:",
        f"{content}",
        "",
        "## OUTPUT FORMAT",
        "",
        "[",
        f'  {{"section_id": "SEC-{file_id}-0001", "start_line": 1, "end_line": 12, '
        '"label": "OVERVIEW"}},',
        f'  {{"section_id": "SEC-{file_id}-0002", "start_line": 13, "end_line": 27, '
        '"label": "DETAILS"}}',
        "]",
    ]
    return "\n".join(lines)


def _build_section_map_prompt(
    file_id: str,
    file_path: Path,
    content: str,
    sections: list[dict[str, Any]] | None,
) -> str:
    section_lines: list[str] = []
    if sections:
        for section in sections:
            section_id = section.get("section_id")
            label = section.get("label", "")
            if isinstance(section_id, str):
                section_lines.append(f"- {section_id}: {label}")
    section_block = "\n".join(section_lines) if section_lines else "None"
    lines = [
        "## OUTPUT CONTRACT (REQUIRED)",
        "",
        "Return Markdown ONLY. No code fences.",
        "REQUIRED RULES:",
        "- Provide a hierarchical bullet list of sections in reading order.",
        "- Use the known section IDs exactly when provided.",
        "- Keep it concise and structural (no prose paragraphs).",
        "",
        "## INPUT DATA",
        "",
        f"File ID: {file_id}",
        f"File Path: {file_path}",
        "",
        "Known Sections:",
        section_block,
        "",
        "Source File Content:",
        f"{content}",
        "",
        "## OUTPUT FORMAT",
        "",
        f"# Section Map: {file_id}",
        f"- SEC-{file_id}-0001: <label>",
        "  - <optional child subsection>",
        f"- SEC-{file_id}-0002: <label>",
    ]
    return "\n".join(lines)


def _build_terms_prompt(
    file_id: str,
    file_path: Path,
    content: str,
    section_ids: list[str],
) -> str:
    section_list = ", ".join(section_ids) if section_ids else "None"
    lines = [
        "## OUTPUT CONTRACT (REQUIRED)",
        "",
        "Return JSON object ONLY. No prose, no markdown, no code fences.",
        "REQUIRED RULES:",
        "- Output must match the FileTerms schema.",
        "- Include file_id, section_terms, global_terms.",
        "- section_terms is a list of {section_id, terms, confidence}.",
        "- confidence is between 0.0 and 1.0.",
        "- Use Known Sections exactly when provided; do not invent IDs outside the format.",
        f"- Section IDs must follow SEC-{file_id}-{{ordinal:04d}}.",
        "",
        "## INPUT DATA",
        "",
        f"File ID: {file_id}",
        f"File Path: {file_path}",
        f"Known Sections: {section_list}",
        "",
        "Source File Content:",
        f"{content}",
        "",
        "## OUTPUT FORMAT",
        "",
        "{",
        f'  "file_id": "{file_id}",',
        '  "section_terms": [',
        f'    {{"section_id": "SEC-{file_id}-0001", "terms": ["..."], "confidence": 0.78}}',
        "  ],",
        '  "global_terms": ["..."]',
        "}",
    ]
    return "\n".join(lines)


def _count_evidence_lines(evidence_path: Path) -> int:
    if not evidence_path.exists():
        return 0
    try:
        with evidence_path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return 0


def _append_issues(
    issues: list[dict[str, Any]],
    *,
    file_id: str,
    issue_type: str,
    messages: list[str],
) -> None:
    for message in messages:
        issues.append({"type": issue_type, "file_id": file_id, "message": message})


def _prepare_gap_evidence(payload: dict[str, Any]) -> GapEvidence:
    evidence = GapEvidence.from_dict(payload)
    details = dict(evidence.details)
    file_id = details.get("file_id")
    if "derived_artifact_target" not in details and isinstance(file_id, str):
        details["derived_artifact_target"] = file_id
    if "source" not in details:
        source_candidates = []
        for key in ("sections_path", "file_path", "terms_path", "atoms_path"):
            value = details.get(key)
            if isinstance(value, str) and value:
                source_candidates.append(value)
        if not source_candidates and evidence.location:
            source_candidates.append(evidence.location)
        if source_candidates:
            details["source"] = source_candidates
    evidence.details = details
    return evidence


def _process_file_sectionization(
    file_id: str,
    file_path: Path,
    manager: WorkspaceManager,
) -> dict[str, Any]:
    evidence_output = manager.structure.pass_01_dir / "evidence" / f"{file_id}.jsonl"
    if evidence_output.exists():
        evidence_output.unlink()

    try:
        content, total_lines = _read_snapshot_content(file_path)
    except (OSError, UnicodeDecodeError) as exc:
        return {"file_id": file_id, "error": f"Failed to read file: {exc}"}

    errors: list[str] = []
    issues: list[dict[str, Any]] = []
    evidence_count = 0
    sections_payload: dict[str, Any] | None = None
    sections_path: Path | None = None
    terms_path: Path | None = None
    atoms_path: Path | None = None
    atoms_written = 0

    section_prompt = _build_section_span_prompt(file_id, file_path, content, total_lines)
    try:
        section_output = run_agent(
            agent_name="glm-section-span-lister",
            prompt=section_prompt,
            workspace=manager.workspace_path,
        )
    except RuntimeError as exc:
        errors.append(f"Section span agent failed: {exc}")
        section_output = None

    if section_output:
        try:
            parsed = json.loads(section_output)
            if not isinstance(parsed, list):
                raise TypeError("Expected JSON array of sections")
            sections_payload = {
                "file_id": file_id,
                "sections": parsed,
                "total_lines": total_lines,
            }
            sections_path = manager.write_file_sections(file_id, sections_payload)
        except (json.JSONDecodeError, ValidationError, TypeError, OSError) as exc:
            errors.append(f"Failed to parse/write sections: {exc}")

    section_ids: list[str] = []
    if sections_payload:
        for section in sections_payload.get("sections", []):
            if isinstance(section, dict) and isinstance(section.get("section_id"), str):
                section_ids.append(section["section_id"])

    map_prompt = _build_section_map_prompt(
        file_id,
        file_path,
        content,
        sections_payload.get("sections") if sections_payload else None,
    )
    try:
        map_output = run_agent(
            agent_name="glm-section-map-builder",
            prompt=map_prompt,
            workspace=manager.workspace_path,
        )
        map_path = manager.structure.manifest_sections_dir / f"{file_id}.section_map.md"
        map_path.write_text(map_output, encoding="utf-8")
    except RuntimeError as exc:
        errors.append(f"Section map agent failed: {exc}")

    terms_prompt = _build_terms_prompt(file_id, file_path, content, section_ids)
    try:
        terms_output = run_agent(
            agent_name="glm-terms-per-section",
            prompt=terms_prompt,
            workspace=manager.workspace_path,
        )
    except RuntimeError as exc:
        errors.append(f"Terms agent failed: {exc}")
        terms_output = None

    if terms_output:
        try:
            parsed_terms = json.loads(terms_output)
            if not isinstance(parsed_terms, dict):
                raise TypeError("Expected JSON object for terms payload")
            terms_path = manager.write_file_terms(file_id, parsed_terms)
        except (json.JSONDecodeError, ValidationError, TypeError, OSError) as exc:
            errors.append(f"Failed to parse/write terms: {exc}")

    validation_ok = True

    if sections_path:
        sections_validation = validate_sections(
            file_id=file_id,
            sections_path=sections_path,
            total_lines=total_lines,
            evidence_output=evidence_output,
        )
        evidence_count += sections_validation.get("evidence_count", 0)
        if not sections_validation.get("valid", True):
            validation_ok = False
            _append_issues(
                issues,
                file_id=file_id,
                issue_type="section_validation",
                messages=sections_validation.get("issues", []),
            )

        sections_model: FileSections | None = None
        try:
            sections_model = FileSections.model_validate_json(
                sections_path.read_text(encoding="utf-8")
            )
        except (ValidationError, OSError) as exc:
            errors.append(f"Failed to load sections for atom emission: {exc}")

        if sections_model is not None:
            atoms_path = manager.structure.manifest_atoms_dir / f"{file_id}.atoms.jsonl"
            if atoms_path.exists():
                atoms_path.unlink()
            before_atoms = _count_evidence_lines(evidence_output)
            atoms_written = emit_atoms(
                file_id=file_id,
                file_path=file_path,
                sections=sections_model,
                output_path=atoms_path,
                evidence_output=evidence_output,
            )
            after_atoms = _count_evidence_lines(evidence_output)
            if after_atoms > before_atoms:
                validation_ok = False
                evidence_count += after_atoms - before_atoms
                issues.append(
                    {
                        "type": "atom_emission",
                        "file_id": file_id,
                        "message": "Atom emission validation failed.",
                    }
                )

        schema_sections = validate_sections_schema(
            sections_path=sections_path,
            file_id=file_id,
            evidence_output=evidence_output,
        )
        evidence_count += schema_sections.get("evidence_count", 0)
        if not schema_sections.get("valid", True):
            validation_ok = False
            _append_issues(
                issues,
                file_id=file_id,
                issue_type="sections_schema",
                messages=schema_sections.get("issues", []),
            )

        if atoms_path is not None:
            atoms_schema = validate_atoms_schema(
                atoms_path=atoms_path,
                file_id=file_id,
                evidence_output=evidence_output,
            )
            evidence_count += atoms_schema.get("evidence_count", 0)
            if not atoms_schema.get("valid", True):
                validation_ok = False
                _append_issues(
                    issues,
                    file_id=file_id,
                    issue_type="atoms_schema",
                    messages=atoms_schema.get("issues", []),
                )

    if terms_path:
        terms_schema = validate_terms_schema(
            terms_path=terms_path,
            file_id=file_id,
            evidence_output=evidence_output,
        )
        evidence_count += terms_schema.get("evidence_count", 0)
        if not terms_schema.get("valid", True):
            validation_ok = False
            _append_issues(
                issues,
                file_id=file_id,
                issue_type="terms_schema",
                messages=terms_schema.get("issues", []),
            )

    success = validation_ok and not errors

    result: dict[str, Any] = {
        "file_id": file_id,
        "success": success,
        "issues": issues,
        "evidence_count": evidence_count,
        "sections_written": 1 if sections_path else 0,
        "atoms_written": atoms_written,
        "terms_written": 1 if terms_path else 0,
        "evidence_path": evidence_output if evidence_output.exists() else None,
    }
    if errors:
        result["error"] = "; ".join(errors)
        result["success"] = False
    return result


def _aggregate_evidence(
    manager: WorkspaceManager,
) -> tuple[Path, list[GapEvidence], list[dict[str, Any]]]:
    pass_dir = manager.structure.pass_01_dir
    evidence_dir = pass_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    aggregate_path = pass_dir / "evidence.jsonl"

    evidence_records: list[GapEvidence] = []
    issues: list[dict[str, Any]] = []

    with aggregate_path.open("w", encoding="utf-8") as output:
        for evidence_path in sorted(evidence_dir.glob("*.jsonl")):
            try:
                with evidence_path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        stripped = line.strip()
                        if not stripped:
                            continue
                        output.write(stripped + "\n")
                        try:
                            payload = json.loads(stripped)
                            if not isinstance(payload, dict):
                                raise TypeError("Evidence payload must be a JSON object")
                            evidence_records.append(_prepare_gap_evidence(payload))
                        except (json.JSONDecodeError, ValueError) as exc:
                            issues.append(
                                {
                                    "type": "evidence_parse",
                                    "file_id": evidence_path.stem,
                                    "message": f"Failed to parse evidence record: {exc}",
                                }
                            )
            except OSError as exc:
                issues.append(
                    {
                        "type": "evidence_read",
                        "file_id": evidence_path.stem,
                        "message": f"Failed to read evidence file: {exc}",
                    }
                )

    return aggregate_path, evidence_records, issues


def _write_gaps(pass_dir: Path, evidence_records: list[GapEvidence]) -> Path:
    gaps_path = pass_dir / "gaps.json"
    synthesizer = GapSynthesizer()
    gaps = synthesizer.cluster_evidence(evidence_records) if evidence_records else []
    gaps_path.write_text(
        json.dumps([gap.to_dict() for gap in gaps], indent=2),
        encoding="utf-8",
    )
    return gaps_path


def sectionize_all(run_id: str, parallel: bool = True) -> dict[str, Any]:
    """Run Phase 1 sectionization over all workspace files."""
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized. Run init before sectionization.")

    manager.start_phase(Phase.SECTIONIZATION)
    files = manager.get_all_files()
    total_files = len(files)

    tracker = ProgressTracker(
        total=total_files,
        description="Sectionizing files",
        manager=manager,
    )

    errors: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    sections_written = 0
    terms_written = 0
    atoms_written = 0
    failures = 0

    if parallel and total_files > 0:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(_process_file_sectionization, file_id, file_path, manager): file_id
                for file_id, file_path in files.items()
            }
            for future in as_completed(futures):
                result = future.result()
                if "error" in result:
                    errors.append({"file_id": result.get("file_id"), "error": result.get("error")})
                if not result.get("success", False):
                    failures += 1
                issues.extend(result.get("issues", []))
                sections_written += int(result.get("sections_written", 0))
                terms_written += int(result.get("terms_written", 0))
                atoms_written += int(result.get("atoms_written", 0))
                tracker.update(status=result.get("file_id", ""))
    else:
        for file_id, file_path in files.items():
            result = _process_file_sectionization(file_id, file_path, manager)
            if "error" in result:
                errors.append({"file_id": result.get("file_id"), "error": result.get("error")})
            if not result.get("success", False):
                failures += 1
            issues.extend(result.get("issues", []))
            sections_written += int(result.get("sections_written", 0))
            terms_written += int(result.get("terms_written", 0))
            atoms_written += int(result.get("atoms_written", 0))
            tracker.update(status=file_id)

    tracker.finish()

    evidence_path, evidence_records, evidence_issues = _aggregate_evidence(manager)
    issues.extend(evidence_issues)
    gaps_path = _write_gaps(manager.structure.pass_01_dir, evidence_records)

    phase_result = manager.state.phases[Phase.SECTIONIZATION.value]
    phase_result.issues = errors + issues

    outputs = {
        "files_processed": total_files,
        "sections_written": sections_written,
        "atoms_written": atoms_written,
        "terms_written": terms_written,
        "evidence_path": str(evidence_path),
        "gaps_path": str(gaps_path),
    }

    evidence_failure = bool(evidence_issues)
    success = failures == 0 and not evidence_failure

    if success:
        manager.complete_phase(Phase.SECTIONIZATION, outputs=outputs)
    else:
        phase_result.outputs = outputs
        error_details: list[str] = []
        if failures:
            error_details.append(f"{failures} file failure(s)")
        if evidence_failure:
            error_details.append(f"{len(evidence_issues)} evidence issue(s)")
        error_message = "Sectionization failed"
        if error_details:
            error_message = f"{error_message}: {', '.join(error_details)}"
        manager.fail_phase(Phase.SECTIONIZATION, error=error_message)

    return {
        "files_processed": total_files,
        "sections_written": sections_written,
        "atoms_written": atoms_written,
        "terms_written": terms_written,
        "success": success,
        "errors": errors,
        "issues": issues,
        "outputs": outputs,
    }
