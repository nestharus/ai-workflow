"""Evidence expansion workflow for Phase 3 spec refinement."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import json
import re

from scripts.dev.agent_runner import AgentRunner
from scripts.spec_refinement.workspace import Phase, PhaseStatus, WorkspaceManager

from .formats import (
    FileSummary,
    parse_evidence_mapper_output,
    parse_evidence_spotcheck_output,
    parse_file_summary,
)
from .progress import ProgressTracker

MAX_WORKERS = 4
STOPWORDS = {
    "the",
    "and",
    "with",
    "from",
    "into",
    "that",
    "this",
    "for",
    "of",
    "to",
    "in",
    "on",
    "by",
    "or",
    "is",
    "are",
    "be",
    "as",
    "at",
    "an",
    "a",
    "it",
    "its",
    "their",
    "these",
    "those",
    "not",
    "no",
    "yes",
    "via",
    "per",
    "but",
    "if",
    "when",
    "then",
    "also",
}


def _extract_sections(content: str, level: int) -> dict[str, str]:
    pattern = re.compile(rf"^{'#' * level}\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return {}

    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        sections[title] = content[start:end].strip()
    return sections


def _extract_list_items(section_text: str) -> list[str]:
    items = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("-", "*")):
            items.append(stripped.lstrip("-* ").strip())
    return items


def _parse_charter(content: str) -> dict[str, Any]:
    sections = _extract_sections(content, level=2)
    return {
        "intent": sections.get("Intent", "").strip(),
        "boundaries": sections.get("Boundaries", "").strip(),
        "responsibilities": _extract_list_items(sections.get("Responsibilities", "")),
    }


def _tokenize(text: str) -> set[str]:
    tokens = {token.lower() for token in re.findall(r"[A-Za-z0-9_]+", text)}
    return {token for token in tokens if len(token) >= 4 and token not in STOPWORDS}


def _charter_tokens(charter: dict[str, Any], lib_id: str) -> set[str]:
    parts = [charter.get("intent", ""), charter.get("boundaries", "")]
    parts.extend(charter.get("responsibilities", []))
    parts.append(lib_id)
    return _tokenize(" ".join(part for part in parts if part))


def _summary_tokens(parsed: FileSummary | None, raw_summary: str) -> set[str]:
    if parsed is None:
        return _tokenize(raw_summary)
    parts: list[str] = []
    for item in parsed.algorithms + parsed.components + parsed.workflows:
        parts.append(item.get("name", ""))
        parts.append(item.get("intent", ""))
    for item in parsed.candidate_responsibilities:
        parts.append(item.get("description", ""))
    parts.extend(parsed.dependencies)
    return _tokenize(" ".join(part for part in parts if part))


def _summary_mentions_charter(
    parsed: FileSummary | None, raw_summary: str, charter: dict[str, Any], lib_id: str
) -> bool:
    charter_token_set = _charter_tokens(charter, lib_id)
    if not charter_token_set:
        return True
    summary_token_set = _summary_tokens(parsed, raw_summary)
    return bool(charter_token_set & summary_token_set)


def _build_evidence_prompt(
    lib_id: str, charter_content: str, file_id: str, summary_content: str
) -> str:
    lines = [
        "Map the library charter to relevant sections in the file summary.",
        "Return JSON with keys: file_id, relevant_sections, confidence, rationale.",
        "Use section identifiers from the source file.",
        "",
        f"Library ID: {lib_id}",
        "",
        "Library Charter:",
        charter_content.strip(),
        "",
        f"File ID: {file_id}",
        "File Summary:",
        summary_content.strip(),
    ]
    return "\n".join(lines).strip() + "\n"


def _build_spotcheck_prompt(
    lib_id: str,
    charter_content: str,
    file_id: str,
    evidence_sections: list[str],
    file_content: str,
) -> str:
    section_list = ", ".join(evidence_sections) if evidence_sections else "None"
    lines = [
        "Audit evidence coverage for the library charter against the source file.",
        "Return JSON with keys: missing_sections, scan_complete.",
        "",
        f"Library ID: {lib_id}",
        "",
        "Library Charter:",
        charter_content.strip(),
        "",
        f"File ID: {file_id}",
        f"Current Evidence Sections: {section_list}",
        "",
        "Source File:",
        file_content.strip(),
    ]
    return "\n".join(lines).strip() + "\n"


def _load_evidence_payload(evidence_path: Path) -> dict[str, Any]:
    if not evidence_path.exists():
        return {"sources": []}
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"sources": []}
    if not isinstance(payload, dict):
        return {"sources": []}
    sources = payload.get("sources")
    if not isinstance(sources, list):
        payload["sources"] = []
    return payload


def _merge_evidence_sources(
    existing_sources: list[dict[str, Any]], entry: dict[str, Any]
) -> tuple[bool, int]:
    file_id = entry.get("file_id")
    sections = set(entry.get("sections", []))
    added_sections = 0
    for source in existing_sources:
        if source.get("file_id") != file_id:
            continue
        existing_sections = set(source.get("sections", []))
        merged = existing_sections | sections
        added_sections = len(merged) - len(existing_sections)
        source["sections"] = sorted(merged)
        if entry.get("confidence") is not None:
            existing_confidence = source.get("confidence")
            if existing_confidence is None or entry["confidence"] > existing_confidence:
                source["confidence"] = entry["confidence"]
                if entry.get("rationale"):
                    source["rationale"] = entry["rationale"]
            elif entry.get("rationale") and not source.get("rationale"):
                source["rationale"] = entry["rationale"]
        return False, added_sections
    existing_sources.append(entry)
    return True, len(sections)


def _validate_evidence_entry(
    entry: dict[str, Any], manager: WorkspaceManager, lib_id: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    issues: list[dict[str, Any]] = []
    file_id = entry.get("file_id")
    if not isinstance(file_id, str) or file_id not in manager.state.file_manifest:
        issues.append(
            {
                "type": "unknown_file_reference",
                "lib_id": lib_id,
                "file_id": file_id,
                "message": "Evidence references unknown file ID.",
            }
        )
        return issues, None

    sections = entry.get("sections")
    if not isinstance(sections, list):
        issues.append(
            {
                "type": "invalid_sections",
                "lib_id": lib_id,
                "file_id": file_id,
                "message": "Evidence sections must be a list.",
            }
        )
        sections = []

    valid_sections = set(manager.state.section_manifest.get(file_id, []))
    filtered_sections = []
    for section in sections:
        if section in valid_sections:
            filtered_sections.append(section)
            continue
        issues.append(
            {
                "type": "unknown_section_reference",
                "lib_id": lib_id,
                "file_id": file_id,
                "section": section,
                "message": "Evidence references unknown section.",
            }
        )

    confidence = entry.get("confidence")
    if confidence is not None:
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            issues.append(
                {
                    "type": "invalid_confidence",
                    "lib_id": lib_id,
                    "file_id": file_id,
                    "message": "Confidence is not numeric.",
                }
            )
            confidence_value = None
        else:
            if not 0.0 <= confidence_value <= 1.0:
                issues.append(
                    {
                        "type": "invalid_confidence",
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "message": "Confidence must be between 0.0 and 1.0.",
                    }
                )
                confidence_value = min(max(confidence_value, 0.0), 1.0)
        entry["confidence"] = confidence_value

    entry["sections"] = filtered_sections
    return issues, entry


def _process_pair(
    lib_id: str,
    charter_content: str,
    file_id: str,
    summary_content: str,
    config_path: Path,
) -> dict[str, Any]:
    prompt = _build_evidence_prompt(lib_id, charter_content, file_id, summary_content)
    runner = AgentRunner.from_agent_name(
        "glm-library-evidence-mapper", config_path, prompt_chars=len(prompt)
    )

    try:
        output = runner.run(prompt)
    except RuntimeError as exc:
        return {"lib_id": lib_id, "file_id": file_id, "error": f"Agent execution failed: {exc}"}

    try:
        data = parse_evidence_mapper_output(output)
    except Exception as exc:  # pragma: no cover - defensive logging
        return {
            "lib_id": lib_id,
            "file_id": file_id,
            "error": f"Failed to parse evidence output: {exc}",
        }

    return {"lib_id": lib_id, "file_id": file_id, "data": data}


def expand_evidence(run_id: str, config_path: Path) -> dict[str, Any]:
    """Expand evidence sources for all libraries (Phase 3)."""
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized. Run init before evidence expansion.")

    synthesis_status = manager.state.phases[Phase.LIBRARY_SYNTHESIS.value].status
    if synthesis_status != PhaseStatus.COMPLETED:
        raise RuntimeError("Library synthesis must be completed before evidence expansion.")

    manager.start_phase(Phase.EVIDENCE_EXPANSION)

    libraries_dir = manager.structure.libraries_dir
    summary_dir = manager.structure.summaries_dir
    lib_dirs = [lib_dir for lib_dir in sorted(libraries_dir.iterdir()) if lib_dir.is_dir()]

    summaries: dict[str, dict[str, Any]] = {}
    for summary_path in sorted(summary_dir.glob("*.what.md")):
        file_id = summary_path.stem.replace(".what", "")
        content = summary_path.read_text(encoding="utf-8")
        parsed: FileSummary | None = None
        try:
            parsed = parse_file_summary(content)
        except Exception:
            parsed = None
        summaries[file_id] = {"content": content, "parsed": parsed}

    pairs: list[tuple[str, str, str, str]] = []
    errors: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    per_lib_errors: dict[str, int] = {}

    for lib_dir in lib_dirs:
        lib_id = lib_dir.name
        charter_path = lib_dir / "charter.md"
        if not charter_path.exists():
            errors.append(
                {
                    "lib_id": lib_id,
                    "error": "Missing charter.md for library.",
                }
            )
            per_lib_errors[lib_id] = per_lib_errors.get(lib_id, 0) + 1
            continue
        charter_content = charter_path.read_text(encoding="utf-8")
        charter = _parse_charter(charter_content)

        for file_id, summary_info in summaries.items():
            parsed = summary_info["parsed"]
            raw_summary = summary_info["content"]
            if not _summary_mentions_charter(parsed, raw_summary, charter, lib_id):
                continue
            pairs.append((lib_id, charter_content, file_id, raw_summary))

    tracker = ProgressTracker(
        total=len(pairs),
        description="Expanding evidence",
        manager=manager,
    )

    results_by_lib: dict[str, list[dict[str, Any]]] = {lib_dir.name: [] for lib_dir in lib_dirs}

    if pairs:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [
                executor.submit(_process_pair, lib_id, charter, file_id, summary, config_path)
                for lib_id, charter, file_id, summary in pairs
            ]
            for future in as_completed(futures):
                result = future.result()
                lib_id = result.get("lib_id", "unknown")
                if "error" in result:
                    errors.append(result)
                    per_lib_errors[lib_id] = per_lib_errors.get(lib_id, 0) + 1
                else:
                    results_by_lib.setdefault(lib_id, []).append(result["data"])
                tracker.update(status=result.get("file_id", ""))
    tracker.finish()

    evidence_sources_added = 0
    libraries_expanded = 0

    for lib_dir in lib_dirs:
        lib_id = lib_dir.name
        entries = results_by_lib.get(lib_id, [])
        if not entries:
            continue
        evidence_path = lib_dir / "evidence.json"
        payload = _load_evidence_payload(evidence_path)
        sources = payload.get("sources", [])
        if not isinstance(sources, list):
            sources = []
            payload["sources"] = sources

        lib_added = False
        for entry in entries:
            candidate_entry = {
                "file_id": entry.get("file_id"),
                "sections": entry.get("relevant_sections", []),
                "confidence": entry.get("confidence"),
                "rationale": entry.get("rationale", ""),
            }
            entry_issues, normalized = _validate_evidence_entry(
                candidate_entry, manager, lib_id
            )
            issues.extend(entry_issues)
            if normalized is None:
                per_lib_errors[lib_id] = per_lib_errors.get(lib_id, 0) + 1
                continue
            confidence_value = normalized.get("confidence")
            if confidence_value is None or confidence_value < 0.5:
                continue

            added_source, added_sections = _merge_evidence_sources(sources, normalized)
            if added_source or added_sections:
                evidence_sources_added += 1
                lib_added = True

        if lib_added:
            libraries_expanded += 1
            evidence_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    phase_result = manager.state.phases[Phase.EVIDENCE_EXPANSION.value]
    phase_result.issues = errors + issues

    total_libs = len(lib_dirs)
    failed_libs = sum(1 for lib_id in per_lib_errors if per_lib_errors[lib_id] > 0)
    failure_ratio = (failed_libs / total_libs) if total_libs else 0
    outputs = {
        "libraries_expanded": libraries_expanded,
        "evidence_sources_added": evidence_sources_added,
    }

    if total_libs > 0 and failure_ratio > 0.5:
        manager.fail_phase(Phase.EVIDENCE_EXPANSION, error="Too many library failures")
    else:
        manager.complete_phase(Phase.EVIDENCE_EXPANSION, outputs=outputs)

    return {
        "libraries_expanded": libraries_expanded,
        "evidence_sources_added": evidence_sources_added,
        "errors": errors,
        "issues": issues,
        "outputs": outputs,
    }


def spotcheck_evidence(
    run_id: str, config_path: Path, lib_ids: list[str] | None = None
) -> dict[str, Any]:
    """Spot-check evidence coverage using ChatGPT XHigh (optional)."""
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized. Run init before evidence spot-check.")

    synthesis_status = manager.state.phases[Phase.LIBRARY_SYNTHESIS.value].status
    if synthesis_status != PhaseStatus.COMPLETED:
        raise RuntimeError("Library synthesis must be completed before evidence spot-check.")

    libraries_dir = manager.structure.libraries_dir
    lib_dirs = [lib_dir for lib_dir in sorted(libraries_dir.iterdir()) if lib_dir.is_dir()]
    if lib_ids:
        lib_dirs = [lib_dir for lib_dir in lib_dirs if lib_dir.name in set(lib_ids)]

    errors: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    missing_sections_added = 0
    libraries_checked = 0

    for lib_dir in lib_dirs:
        lib_id = lib_dir.name
        charter_path = lib_dir / "charter.md"
        if not charter_path.exists():
            errors.append({"lib_id": lib_id, "error": "Missing charter.md for library."})
            continue

        charter_content = charter_path.read_text(encoding="utf-8")
        evidence_path = lib_dir / "evidence.json"
        payload = _load_evidence_payload(evidence_path)
        sources = payload.get("sources", [])
        if not isinstance(sources, list):
            sources = []
            payload["sources"] = sources

        evidence_by_file: dict[str, dict[str, Any]] = {}
        for source in sources:
            file_id = source.get("file_id")
            if not isinstance(file_id, str):
                continue
            entry = evidence_by_file.setdefault(
                file_id, {"sections": set(), "confidence": None}
            )
            entry["sections"].update(source.get("sections", []))
            if source.get("confidence") is not None:
                try:
                    confidence_value = float(source["confidence"])
                except (TypeError, ValueError):
                    confidence_value = None
                if confidence_value is not None:
                    current = entry.get("confidence")
                    if current is None or confidence_value < current:
                        entry["confidence"] = confidence_value

        uncertain_files: list[tuple[str, float]] = []
        for file_id in manager.state.file_manifest:
            confidence = evidence_by_file.get(file_id, {}).get("confidence")
            if confidence is None:
                confidence = 0.0
            if confidence < 0.7 or file_id not in evidence_by_file:
                uncertain_files.append((file_id, confidence))

        uncertain_files.sort(key=lambda item: item[1])
        selected_files = [file_id for file_id, _ in uncertain_files[:5]]
        if not selected_files:
            continue

        libraries_checked += 1
        for file_id in selected_files:
            file_path = manager.get_file_path(file_id)
            if file_path is None or not file_path.exists():
                errors.append(
                    {
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "error": "Source file not found for spot-check.",
                    }
                )
                continue

            file_content = file_path.read_text(encoding="utf-8")
            existing_sections = sorted(
                evidence_by_file.get(file_id, {}).get("sections", set())
            )
            prompt = _build_spotcheck_prompt(
                lib_id, charter_content, file_id, existing_sections, file_content
            )
            runner = AgentRunner.from_agent_name(
                "chatgpt-evidence-gap-judge", config_path, prompt_chars=len(prompt)
            )

            try:
                output = runner.run(prompt)
            except RuntimeError as exc:
                errors.append(
                    {
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "error": f"Agent execution failed: {exc}",
                    }
                )
                continue

            try:
                data = parse_evidence_spotcheck_output(output)
            except Exception as exc:  # pragma: no cover - defensive logging
                errors.append(
                    {
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "error": f"Failed to parse spotcheck output: {exc}",
                    }
                )
                continue

            missing_sections = data.get("missing_sections", [])
            if not isinstance(missing_sections, list):
                continue

            new_sections: list[str] = []
            rationale_lines: list[str] = []
            confidence_values: list[float] = []
            valid_sections = set(manager.state.section_manifest.get(file_id, []))
            for item in missing_sections:
                section_label = item.get("section_label") if isinstance(item, dict) else None
                if not isinstance(section_label, str):
                    continue
                if section_label not in valid_sections:
                    issues.append(
                        {
                            "type": "unknown_section_reference",
                            "lib_id": lib_id,
                            "file_id": file_id,
                            "section": section_label,
                            "message": "Spotcheck references unknown section.",
                        }
                    )
                    continue
                new_sections.append(section_label)
                rationale = item.get("rationale", "") if isinstance(item, dict) else ""
                if rationale:
                    rationale_lines.append(f"{section_label}: {rationale}")
                confidence = item.get("confidence") if isinstance(item, dict) else None
                if confidence is not None:
                    try:
                        confidence_values.append(float(confidence))
                    except (TypeError, ValueError):
                        issues.append(
                            {
                                "type": "invalid_confidence",
                                "lib_id": lib_id,
                                "file_id": file_id,
                                "message": "Spotcheck confidence is not numeric.",
                            }
                        )

            if not new_sections:
                continue

            aggregated_confidence = max(confidence_values) if confidence_values else 0.7
            rationale_text = "\n".join(rationale_lines)
            candidate_entry = {
                "file_id": file_id,
                "sections": new_sections,
                "confidence": aggregated_confidence,
                "rationale": rationale_text,
            }
            entry_issues, normalized = _validate_evidence_entry(
                candidate_entry, manager, lib_id
            )
            issues.extend(entry_issues)
            if normalized is None:
                continue

            added_source, added_sections = _merge_evidence_sources(sources, normalized)
            if added_source or added_sections:
                missing_sections_added += added_sections if added_sections else len(new_sections)

        evidence_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    phase_result = manager.state.phases[Phase.EVIDENCE_EXPANSION.value]
    phase_result.issues = phase_result.issues + errors + issues

    return {
        "libraries_checked": libraries_checked,
        "missing_sections_added": missing_sections_added,
        "errors": errors,
        "issues": issues,
    }
