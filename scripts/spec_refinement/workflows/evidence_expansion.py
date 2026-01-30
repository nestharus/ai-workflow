"""Evidence expansion workflow for Phase 3 spec refinement."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from scripts.spec_refinement.workspace import Phase, PhaseStatus, WorkspaceManager

from .agent_utils import run_agent
from .formats import (
    _extract_json_payload,
    parse_evidence_mapper_output,
    parse_evidence_spotcheck_output,
)
from .progress import ProgressTracker

MAX_WORKERS = 4


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


def _compute_pair_priority(
    file_id: str,
    lib_id: str,
    file_labels: dict[str, Any],
    charter_content: str,
    summary_content: str,
    manager: WorkspaceManager,
) -> tuple[float, str]:
    """Compute priority score for a file-library pair.

    Returns:
        (priority_score, rationale) where priority_score is 0.0-1.0
    """
    file_entry = file_labels.get(file_id)
    if not isinstance(file_entry, dict):
        return 0.3, "not_in_labeler_output"

    candidate_labels = file_entry.get("candidate_labels", [])
    if not isinstance(candidate_labels, list):
        candidate_labels = []

    charter = _parse_charter(charter_content)
    intent = charter.get("intent", "")
    boundaries = charter.get("boundaries", "")
    charter_text = f"{intent}\n{boundaries}".lower()

    matched_entry: dict[str, Any] | None = None
    matched_confidence = -1.0
    for entry in candidate_labels:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label", "")).strip()
        if not label:
            continue
        if label.lower() not in charter_text:
            continue
        try:
            confidence_value = float(entry.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence_value = 0.0
        if confidence_value > matched_confidence:
            matched_confidence = confidence_value
            matched_entry = entry

    if matched_entry is None:
        return 0.3, "not_in_labeler_output"

    try:
        confidence = float(matched_entry.get("confidence", 0.0))
    except (TypeError, ValueError):
        return 0.3, "not_in_labeler_output"

    if confidence >= 0.7:
        return confidence, "high_confidence_from_labeler"
    if confidence < 0.4:
        return confidence, "low_confidence_skip"

    prompt = (
        "\n".join(
            [
                "Determine if the file is relevant to the library based on semantic "
                "overlap, not keyword matching.",
                "Return JSON with keys: relevant (yes/no/uncertain), rationale, "
                "confidence (0.0-1.0).",
                "",
                f"Library ID: {lib_id}",
                "Library Intent:",
                intent.strip() or "None",
                "",
                "Library Boundaries:",
                boundaries.strip() or "None",
                "",
                f"Labeler Confidence: {confidence:.2f}",
                "",
                "File Summary:",
                summary_content.strip(),
            ]
        ).strip()
        + "\n"
    )

    try:
        output = run_agent(
            agent_name="glm-library-relevance-classifier",
            prompt=prompt,
            workspace=manager.workspace_path,
        )
    except RuntimeError:
        return 0.5, "classifier_uncertain"

    try:
        data = json.loads(_extract_json_payload(output))
    except Exception:
        return 0.5, "classifier_uncertain"

    relevant = str(data.get("relevant", "")).strip().lower()
    if relevant == "yes":
        return 0.7, "classifier_confirmed"
    if relevant == "no":
        return 0.2, "classifier_rejected"
    return 0.5, "classifier_uncertain"


def _build_evidence_prompt(
    lib_id: str,
    charter_content: str,
    file_id: str,
    summary_content: str,
    valid_sections: list[str],
) -> str:
    """Build prompt for evidence mapping.

    IMPORTANT: The model must choose section labels from `valid_sections` (exact match).
    """
    section_list = ", ".join(valid_sections) if valid_sections else "None"
    lines = [
        "You are mapping a library charter to relevant SOURCE FILE sections.",
        "Return JSON with keys: file_id, relevant_sections, confidence, rationale.",
        "",
        "Hard rules:",
        (
            f"- relevant_sections MUST be chosen from this exact allow-list "
            f"for {file_id}: {section_list}"
        ),
        "- Do NOT return file-summary headings like 'Components' or 'Workflows'.",
        (
            "- Prefer the minimal set of sections needed. Include a section only "
            "if it directly supports the charter or explicitly mentions the library "
            "(e.g., in dependencies/integration notes)."
        ),
        (
            "- If nothing is relevant, return an empty relevant_sections list and "
            "set confidence <= 0.4."
        ),
        "",
        f"Library ID: {lib_id}",
        "",
        "Library Charter:",
        charter_content.strip(),
        "",
        f"File ID: {file_id}",
        "File Summary (contains evidence pointers and an Evidence Map):",
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
    filtered_sections: list[str] = []
    seen_sections: set[str] = set()

    for section in sections:
        if not isinstance(section, str):
            continue
        raw = section.strip()
        if not raw:
            continue

        # Prefer exact matches, but tolerate common formatting differences.
        candidate = raw
        if candidate not in valid_sections:
            normalized = candidate.upper().replace(" ", "_")
            if normalized in valid_sections:
                candidate = normalized
            else:
                normalized = candidate.upper()
                if normalized in valid_sections:
                    candidate = normalized

        if candidate not in valid_sections:
            issues.append(
                {
                    "type": "unknown_section_reference",
                    "lib_id": lib_id,
                    "file_id": file_id,
                    "section": raw,
                    "message": "Evidence references unknown section.",
                }
            )
            continue

        if candidate in seen_sections:
            continue
        seen_sections.add(candidate)
        filtered_sections.append(candidate)

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
            if confidence_value is not None and not 0.0 <= confidence_value <= 1.0:
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

    # Guard against over-broad cross-file evidence. If the file appears to primarily
    # describe a different library, only keep sections that explicitly mention the
    # target library ID. This prevents importing unrelated requirements/constraints
    # from other libraries into the evidence set.
    file_path = manager.get_file_path(file_id)
    if file_path is not None and file_path.exists() and filtered_sections:
        import re
        from collections import Counter

        content = file_path.read_text(encoding="utf-8")

        # Heuristic: infer the "primary" library a file describes from (lib_###) mentions.
        mentions = re.findall(r"\((lib_[0-9]+)\)", content[:8000])
        primary_lib_id = None
        if mentions:
            counts = Counter(mentions)
            primary_lib_id = counts.most_common(1)[0][0]

        # Extract section blocks keyed by bracket label markers like [INTRO].
        section_blocks: dict[str, str] = {}
        matches = list(re.finditer(r"^\[([A-Z_]+)\] *$", content, re.MULTILINE))
        for idx, match in enumerate(matches):
            label = match.group(1).strip()
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
            section_blocks[label] = content[start:end]

        if primary_lib_id is None or primary_lib_id != lib_id:
            mention_filtered: list[str] = []
            for section in filtered_sections:
                section_text = section_blocks.get(section, "")
                if lib_id in section_text:
                    mention_filtered.append(section)
                    continue
                # Silent normalization: the mapper sometimes over-selects sections in
                # cross-file contexts. Dropping non-mentioning sections is expected.
            filtered_sections = mention_filtered
            entry["sections"] = filtered_sections

    if not filtered_sections:
        return issues, None

    normalized = entry
    if "priority" in entry:
        normalized["priority"] = entry["priority"]
    if "priority_rationale" in entry:
        normalized["priority_rationale"] = entry["priority_rationale"]

    return issues, normalized


def _process_pair(
    lib_id: str,
    charter_content: str,
    file_id: str,
    summary_content: str,
    valid_sections: list[str],
    workspace: Path,
    priority: float,
    rationale: str,
) -> dict[str, Any]:
    prompt = _build_evidence_prompt(
        lib_id, charter_content, file_id, summary_content, valid_sections
    )

    try:
        output = run_agent(
            agent_name="glm-library-evidence-mapper",
            prompt=prompt,
            workspace=workspace,
        )
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

    return {
        "lib_id": lib_id,
        "file_id": file_id,
        "data": data,
        "priority": priority,
        "rationale": rationale,
    }


def expand_evidence(run_id: str) -> dict[str, Any]:
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
        summaries[file_id] = {"content": content}

    pairs: list[tuple[str, str, str, str, list[str], float, str]] = []
    errors: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    per_lib_errors: dict[str, int] = {}

    # Load Phase 2A labeler output for priority ranking
    file_labels_path = manager.structure.libraries_dir / "file_labels.json"
    file_labels: dict[str, Any] = {}
    if file_labels_path.exists():
        try:
            file_labels = json.loads(file_labels_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            issues.append(
                {
                    "type": "file_labels_load_failed",
                    "message": "Failed to load file_labels.json for priority ranking",
                }
            )

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

        for file_id, summary_info in summaries.items():
            raw_summary = summary_info["content"]
            priority, rationale = _compute_pair_priority(
                file_id=file_id,
                lib_id=lib_id,
                file_labels=file_labels,
                charter_content=charter_content,
                summary_content=raw_summary,
                manager=manager,
            )

            # Only skip if priority is very low AND there's a fallback audit path
            # (spotcheck_evidence provides the fallback)
            if priority < 0.3:
                continue

            pairs.append(
                (
                    lib_id,
                    charter_content,
                    file_id,
                    raw_summary,
                    manager.get_section_labels(file_id),
                    priority,
                    rationale,
                )
            )

    tracker = ProgressTracker(
        total=len(pairs),
        description="Expanding evidence",
        manager=manager,
    )

    results_by_lib: dict[str, list[dict[str, Any]]] = {lib_dir.name: [] for lib_dir in lib_dirs}

    if pairs:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [
                executor.submit(
                    _process_pair,
                    lib_id,
                    charter,
                    file_id,
                    summary,
                    valid_sections,
                    manager.workspace_path,
                    priority,
                    rationale,
                )
                for lib_id, charter, file_id, summary, valid_sections, priority, rationale in pairs
            ]
            for future in as_completed(futures):
                result = future.result()
                lib_id = result.get("lib_id", "unknown")
                if "error" in result:
                    errors.append(result)
                    per_lib_errors[lib_id] = per_lib_errors.get(lib_id, 0) + 1
                else:
                    results_by_lib.setdefault(lib_id, []).append(result)
                tracker.update(status=result.get("file_id", ""))
    tracker.finish()

    evidence_sources_added = 0
    libraries_expanded = 0

    for lib_dir in lib_dirs:
        lib_id = lib_dir.name
        results = results_by_lib.get(lib_id, [])
        if not results:
            continue
        evidence_path = lib_dir / "evidence.json"
        payload = _load_evidence_payload(evidence_path)
        sources = payload.get("sources", [])
        if not isinstance(sources, list):
            sources = []
            payload["sources"] = sources

        lib_added = False
        for result in results:
            entry = result.get("data", {})
            candidate_entry = {
                "file_id": entry.get("file_id"),
                "sections": entry.get("relevant_sections", []),
                "confidence": entry.get("confidence"),
                "rationale": entry.get("rationale", ""),
                "priority": result.get("priority", 0.5),
                "priority_rationale": result.get("rationale", ""),
            }
            entry_issues, normalized = _validate_evidence_entry(candidate_entry, manager, lib_id)
            issues.extend(entry_issues)
            if entry_issues and normalized is None:
                from .repair import ArtifactType, repair_artifact

                try:
                    entry_json = json.dumps(candidate_entry, indent=2)
                    repaired_json = repair_artifact(
                        output=entry_json,
                        errors=entry_issues,
                        allowlists={
                            "file_ids": list(manager.state.file_manifest.keys()),
                            "sections": manager.state.section_manifest.get(
                                candidate_entry.get("file_id") or "", []
                            ),
                        },
                        artifact_type=ArtifactType.EVIDENCE_JSON,
                        manager=manager,
                    )
                    repaired_entry = json.loads(repaired_json)
                    repaired_issues, repaired_normalized = _validate_evidence_entry(
                        repaired_entry,
                        manager,
                        lib_id,
                    )
                    if not repaired_issues and repaired_normalized is not None:
                        normalized = repaired_normalized
                        issues = [i for i in issues if i not in entry_issues]
                except Exception as exc:
                    issues.append(
                        {
                            "type": "repair_failed",
                            "lib_id": lib_id,
                            "file_id": candidate_entry.get("file_id"),
                            "message": f"Evidence entry repair failed: {exc}",
                        }
                    )
            if normalized is None:
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


def spotcheck_evidence(run_id: str, lib_ids: list[str] | None = None) -> dict[str, Any]:
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
            entry = evidence_by_file.setdefault(file_id, {"sections": set(), "confidence": None})
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

        # Prioritize files with low priority scores from evidence expansion
        uncertain_files: list[tuple[str, float, float]] = []
        for file_id in manager.state.file_manifest:
            evidence_entry = evidence_by_file.get(file_id, {})
            confidence = evidence_entry.get("confidence") or 0.0

            # Load priority from evidence.json if available
            priority = 0.5  # default
            for source in sources:
                if source.get("file_id") == file_id and "priority" in source:
                    priority = source["priority"]
                    break

            # Select files with low confidence OR low priority
            if confidence < 0.7 or priority < 0.5 or file_id not in evidence_by_file:
                uncertain_files.append((file_id, confidence, priority))

        # Sort by priority (ascending) then confidence (ascending)
        uncertain_files.sort(key=lambda item: (item[2], item[1]))
        selected_files = [file_id for file_id, _, _ in uncertain_files[:5]]
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
            existing_sections = sorted(evidence_by_file.get(file_id, {}).get("sections", set()))
            prompt = _build_spotcheck_prompt(
                lib_id, charter_content, file_id, existing_sections, file_content
            )

            try:
                output = run_agent(
                    agent_name="chatgpt-evidence-gap-judge",
                    prompt=prompt,
                    workspace=manager.workspace_path,
                )
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
            entry_issues, normalized = _validate_evidence_entry(candidate_entry, manager, lib_id)
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
