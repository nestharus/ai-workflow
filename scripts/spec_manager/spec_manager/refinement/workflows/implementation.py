# This module will be extended in subsequent phases with:
# - execute_task() - main task execution orchestrator
# - run_implementation_phase() - phase entrypoint
# - run_tests() - test execution and capture
# Current phase: context bundle building only

import json
import logging
import re
from pathlib import Path

from spec_manager.schemas import (
    DecisionsIndex,
    SpecIndex,
    TaskSchema,
)

logger = logging.getLogger(__name__)


def _load_spec_index_for_lib(run_root: Path, lib_id: str) -> SpecIndex | None:
    spec_index_path = run_root / "spec_snapshot" / "libraries" / lib_id / "spec_index.json"
    if not spec_index_path.exists():
        logger.warning("spec_index.json not found for %s", lib_id)
        return None
    try:
        payload = json.loads(spec_index_path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.warning("Failed to read spec_index.json for %s: %s", lib_id, exc)
        return None
    except json.JSONDecodeError as exc:
        logger.warning("Invalid spec_index.json for %s: %s", lib_id, exc)
        return None
    try:
        return SpecIndex.model_validate(payload)
    except Exception as exc:
        logger.warning("Spec index validation failed for %s: %s", lib_id, exc)
        return None


def _load_decisions_index_for_lib(run_root: Path, lib_id: str) -> DecisionsIndex | None:
    decisions_index_path = (
        run_root / "spec_snapshot" / "libraries" / lib_id / "decisions_index.json"
    )
    if not decisions_index_path.exists():
        return None
    try:
        payload = json.loads(decisions_index_path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.warning("Failed to read decisions_index.json for %s: %s", lib_id, exc)
        return None
    except json.JSONDecodeError as exc:
        logger.warning("Invalid decisions_index.json for %s: %s", lib_id, exc)
        return None
    try:
        return DecisionsIndex.model_validate(payload)
    except Exception as exc:
        logger.warning("Decisions index validation failed for %s: %s", lib_id, exc)
        return None


def _extract_lib_id_from_element(element_id: str) -> str:
    match = re.search(r"LIB-\d{4}", element_id)
    return match.group(0) if match else "unknown"


def _extract_lib_ids_from_edge(edge_id: str) -> tuple[str, str]:
    parts = edge_id.split("-")
    if len(parts) < 5:
        return ("unknown", "unknown")
    return (f"{parts[1]}-{parts[2]}", f"{parts[3]}-{parts[4]}")


def _read_spec_md_for_lib(run_root: Path, lib_id: str) -> str | None:
    spec_md_path = run_root / "spec_snapshot" / "libraries" / lib_id / "spec.md"
    if not spec_md_path.exists():
        return None
    try:
        return spec_md_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to read spec.md for %s: %s", lib_id, exc)
        return None


def _extract_snippet_from_spec_md(spec_content: str, element_id: str) -> str | None:
    lines = spec_content.splitlines()
    current_section = ""
    anchor_re = re.compile(rf"^\s*[-*]\s*{re.escape(element_id)}\s*:")

    for i, line in enumerate(lines):
        section_match = re.match(r"^##\s+(.+)$", line)
        if section_match:
            current_section = section_match.group(1).strip()
            continue

        if not anchor_re.match(line):
            continue

        text = re.sub(r"^\s*[-*]\s*(?:REQ|FLOW|INV)-LIB-\d{4}-\d+:\s*", "", line).strip()

        sub_lines: list[str] = []
        for j in range(i + 1, len(lines)):
            next_line = lines[j]
            if not next_line.strip():
                break
            if re.match(r"^\s{2,}[-*]\s+", next_line):
                sub_lines.append(next_line.strip())
            else:
                break

        section_label = current_section if current_section else "Unknown"
        snippet = f"**{element_id}** ({section_label}): {text}"
        if sub_lines:
            snippet += "\n" + "\n".join(f"  {sl}" for sl in sub_lines)
        return snippet

    return None


def _gather_element_snippets(run_root: Path, element_ids: list[str]) -> dict[str, str]:
    snippets: dict[str, str] = {}
    grouped: dict[str, list[str]] = {}
    for element_id in element_ids:
        lib_id = _extract_lib_id_from_element(element_id)
        grouped.setdefault(lib_id, []).append(element_id)

    for lib_id, ids in grouped.items():
        if lib_id == "unknown":
            for element_id in ids:
                logger.warning("Unable to parse library ID from element %s", element_id)
                snippets[element_id] = f"**{element_id}**: [Element not found]"
            continue

        spec_content = _read_spec_md_for_lib(run_root, lib_id)
        remaining_ids: list[str] = []

        if spec_content is not None:
            for element_id in ids:
                snippet = _extract_snippet_from_spec_md(spec_content, element_id)
                if snippet is not None:
                    snippets[element_id] = snippet
                else:
                    remaining_ids.append(element_id)
        else:
            remaining_ids = list(ids)

        if not remaining_ids:
            continue

        spec_index = _load_spec_index_for_lib(run_root, lib_id)
        if spec_index is None:
            for element_id in remaining_ids:
                logger.warning("Spec index missing for %s when looking up %s", lib_id, element_id)
                snippets[element_id] = f"**{element_id}**: [Element not found]"
            continue
        lookup = {element.element_id: element for element in spec_index.elements}
        for element_id in remaining_ids:
            element = lookup.get(element_id)
            if element is None:
                logger.warning("Element %s not found in spec index for %s", element_id, lib_id)
                snippets[element_id] = f"**{element_id}**: [Element not found]"
                continue
            snippets[element_id] = f"**{element.element_id}** ({element.kind}): {element.text}"

    return snippets


def _gather_decision_snippets(run_root: Path, decision_ids: list[str]) -> dict[str, str]:
    snippets: dict[str, str] = {}
    grouped: dict[str, list[str]] = {}
    for decision_id in decision_ids:
        lib_id = _extract_lib_id_from_element(decision_id)
        grouped.setdefault(lib_id, []).append(decision_id)

    for lib_id, ids in grouped.items():
        if lib_id == "unknown":
            for decision_id in ids:
                logger.warning("Unable to parse library ID from decision %s", decision_id)
                snippets[decision_id] = f"**{decision_id}**: [Decision not found]"
            continue
        decisions_index = _load_decisions_index_for_lib(run_root, lib_id)
        if decisions_index is None:
            for decision_id in ids:
                logger.warning(
                    "Decisions index missing for %s when looking up %s", lib_id, decision_id
                )
                snippets[decision_id] = f"**{decision_id}**: [Decision not found]"
            continue
        lookup = {decision.decision_id: decision for decision in decisions_index.decisions}
        for decision_id in ids:
            decision = lookup.get(decision_id)
            if decision is None:
                logger.warning(
                    "Decision %s not found in decisions index for %s", decision_id, lib_id
                )
                snippets[decision_id] = f"**{decision_id}**: [Decision not found]"
                continue
            context = decision.context or "N/A"
            snippets[decision_id] = (
                f"**{decision.decision_id}** ({decision.status}): {decision.question}\n"
                f"Context: {context}"
            )

    return snippets


def _format_interface_contract_json(edge_id: str, payload: object) -> str:
    summary_lines = [f"**{edge_id}** (json)"]
    if isinstance(payload, dict):
        for key in sorted(payload.keys()):
            value = payload[key]
            rendered = json.dumps(value, ensure_ascii=True)
            summary_lines.append(f"- {key}: {rendered}")
    else:
        summary_lines.append(f"- content: {json.dumps(payload, ensure_ascii=True)}")
    return "\n".join(summary_lines)


def _gather_interface_contracts(run_root: Path, edge_ids: list[str]) -> dict[str, str]:
    contracts: dict[str, str] = {}
    for edge_id in edge_ids:
        consumer_lib, _provider_lib = _extract_lib_ids_from_edge(edge_id)
        if consumer_lib == "unknown":
            logger.warning("Unable to parse library IDs from edge %s", edge_id)
            contracts[edge_id] = f"**{edge_id}**: [Interface contract not found]"
            continue
        interface_dir = run_root / "spec_snapshot" / "libraries" / consumer_lib / "interfaces"
        markdown_path = interface_dir / f"{edge_id}.md"
        content: str | None = None
        if markdown_path.exists():
            try:
                content = markdown_path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning("Failed to read interface contract %s: %s", markdown_path, exc)
                content = f"**{edge_id}**: [Error reading interface contract]"
        else:
            json_path = interface_dir / f"{edge_id}.json"
            if json_path.exists():
                try:
                    payload = json.loads(json_path.read_text(encoding="utf-8"))
                except OSError as exc:
                    logger.warning("Failed to read interface contract %s: %s", json_path, exc)
                    content = f"**{edge_id}**: [Error reading interface contract]"
                except json.JSONDecodeError as exc:
                    logger.warning("Invalid interface contract %s: %s", json_path, exc)
                    content = f"**{edge_id}**: [Error reading interface contract]"
                else:
                    content = _format_interface_contract_json(edge_id, payload)
            else:
                logger.warning("Interface contract not found for edge %s", edge_id)
                content = f"**{edge_id}**: [Interface contract not found]"

        if content is None:
            content = f"**{edge_id}**: [Interface contract not found]"
        if len(content) > 2000:
            content = f"{content[:2000]}...[truncated]"
        contracts[edge_id] = content

    return contracts


def _read_file_with_limit(file_path: Path, max_chars: int = 5000) -> str:
    if not file_path.exists():
        return f"[Missing file: {file_path}]"
    try:
        total_size = file_path.stat().st_size
    except OSError as exc:
        return f"[Error reading file: {exc}]"
    try:
        with file_path.open("rb") as handle:
            probe = handle.read(min(total_size, 8192))
    except OSError as exc:
        return f"[Error reading file: {exc}]"
    if b"\x00" in probe:
        return f"[Binary file: {file_path.name}]"
    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"[Binary file: {file_path.name}]"
    except OSError as exc:
        return f"[Error reading file: {exc}]"
    if len(text) <= max_chars:
        return text
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    head_budget = max_chars // 2
    tail_budget = max_chars - head_budget
    head_chars = 0
    head_end = 0
    for i, line in enumerate(lines):
        if head_chars + len(line) > head_budget and head_end > 0:
            break
        head_chars += len(line)
        head_end = i + 1
    tail_chars = 0
    tail_start = total_lines
    for i in range(total_lines - 1, head_end - 1, -1):
        if tail_chars + len(lines[i]) > tail_budget and tail_start < total_lines:
            break
        tail_chars += len(lines[i])
        tail_start = i
    if tail_start <= head_end:
        head_text = "".join(lines[:head_end]).rstrip("\n")
        return (
            f"{head_text}\n\n"
            f"...[File truncated: showing lines 1\u2013{head_end} of {total_lines} "
            f"total lines ({len(text)} characters)]"
        )
    head_text = "".join(lines[:head_end]).rstrip("\n")
    tail_text = "".join(lines[tail_start:]).rstrip("\n")
    omitted_count = tail_start - head_end
    return (
        f"{head_text}\n\n"
        f"...[Lines {head_end + 1}\u2013{tail_start} omitted ({omitted_count} lines)]\n\n"
        f"{tail_text}\n\n"
        f"...[File truncated: showing lines 1\u2013{head_end} and "
        f"{tail_start + 1}\u2013{total_lines} of {total_lines} total lines "
        f"({len(text)} characters)]"
    )


def _gather_suggested_files_content(repo_root: Path, suggested_files: list[str]) -> dict[str, str]:
    contents: dict[str, str] = {}
    for file_path in suggested_files:
        resolved_path = repo_root / file_path
        contents[file_path] = _read_file_with_limit(resolved_path, max_chars=5000)
    return contents


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _truncate_section(content: str, max_chars: int, section_name: str) -> str:
    if len(content) <= max_chars:
        return content
    estimated_tokens = _estimate_tokens(content)
    truncated = content[:max_chars]
    return (
        f"{truncated}\n\n...[{section_name} truncated: showing {max_chars} of {len(content)} "
        f"characters (~{estimated_tokens} tokens)]"
    )


def build_context_bundle(run_root: Path, task_id: str, repo_root: Path) -> str:
    task_path = run_root / "tasks" / task_id / "task.json"
    task = TaskSchema.model_validate_json(task_path.read_text(encoding="utf-8"))

    element_snippets = _gather_element_snippets(run_root, task.covers.elements)
    decision_snippets = _gather_decision_snippets(run_root, task.covers.decisions)
    interface_contracts = _gather_interface_contracts(run_root, task.covers.edges)
    file_contents = _gather_suggested_files_content(repo_root, task.suggested_files)

    acceptance_criteria = (
        "\n".join(
            f"{index + 1}. {criterion}" for index, criterion in enumerate(task.acceptance_criteria)
        )
        if task.acceptance_criteria
        else "None"
    )

    section_1_lines = [
        "# Task Requirements",
        "",
        "## Task ID",
        task.task_id,
        "",
        "## Title",
        task.title,
        "",
        "## Description",
        task.description,
        "",
        "## Priority",
        task.priority,
        "",
        "## Component",
        task.component,
        "",
        "## Libraries",
        ", ".join(task.libraries) if task.libraries else "None",
        "",
        "## Acceptance Criteria",
        acceptance_criteria,
        "",
        "## Risk Notes",
        task.risk_notes or "None",
        "",
        "## Validation Notes",
        task.validation_notes or "None",
    ]
    section_1 = "\n".join(section_1_lines)

    section_2_lines = ["# Relevant Specs / Interfaces", "", "## Covered Elements"]
    if task.covers.elements:
        for element_id in task.covers.elements:
            section_2_lines.append(
                element_snippets.get(element_id, f"**{element_id}**: [Element not found]")
            )
    else:
        section_2_lines.append("None")

    section_2_lines.extend(["", "## Covered Decisions"])
    if task.covers.decisions:
        for decision_id in task.covers.decisions:
            section_2_lines.append(
                decision_snippets.get(decision_id, f"**{decision_id}**: [Decision not found]")
            )
    else:
        section_2_lines.append("None")

    section_2_lines.extend(["", "## Interface Contracts"])
    if task.covers.edges:
        for edge_id in task.covers.edges:
            section_2_lines.append(
                interface_contracts.get(edge_id, f"**{edge_id}**: [Interface contract not found]")
            )
    else:
        section_2_lines.append("None")

    section_2_lines.extend(["", "## Citations"])
    if task.citations:
        section_2_lines.extend(f"- {citation}" for citation in task.citations)
    else:
        section_2_lines.append("None")

    section_2 = "\n".join(section_2_lines)

    section_3_lines = ["# Relevant Code Context", "", "## Suggested Files"]
    if file_contents:
        for file_path, content in file_contents.items():
            section_3_lines.extend(
                [
                    "",
                    f"### File: {file_path}",
                    "",
                    "```",
                    content,
                    "```",
                ]
            )
    else:
        section_3_lines.append("None")

    section_3 = "\n".join(section_3_lines)

    section_1 = _truncate_section(section_1, 10000, "Task Requirements")
    section_2 = _truncate_section(section_2, 20000, "Relevant Specs / Interfaces")
    section_3 = _truncate_section(section_3, 20000, "Relevant Code Context")

    total_limit = 50000
    sections = [section_1, section_2, section_3]
    total_length = sum(len(section) for section in sections)
    attempts = 0
    while total_length > total_limit and attempts < 3:
        scale = total_limit / total_length
        section_1 = _truncate_section(
            section_1, max(1, int(len(section_1) * scale)), "Task Requirements"
        )
        section_2 = _truncate_section(
            section_2,
            max(1, int(len(section_2) * scale)),
            "Relevant Specs / Interfaces",
        )
        section_3 = _truncate_section(
            section_3,
            max(1, int(len(section_3) * scale)),
            "Relevant Code Context",
        )
        sections = [section_1, section_2, section_3]
        total_length = sum(len(section) for section in sections)
        attempts += 1

    return "\n\n".join([section_1, section_2, section_3])


def write_context_bundle(run_root: Path, task_id: str, content: str) -> Path:
    output_path = run_root / "tasks" / task_id / "context_bundle.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    logger.info("Wrote context bundle for %s: %s", task_id, output_path)
    return output_path


__all__ = [
    "build_context_bundle",
    "write_context_bundle",
]
