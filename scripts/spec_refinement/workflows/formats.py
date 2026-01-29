"""Structured formats and parsers for spec refinement workflows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

EVIDENCE_POINTER_RE = re.compile(r"\[([^\[\]]+?)::([^\[\]]+?)\]")


@dataclass(frozen=True)
class FileSummary:
    file_id: str
    algorithms: list[dict[str, Any]]
    components: list[dict[str, Any]]
    workflows: list[dict[str, Any]]
    candidate_responsibilities: list[dict[str, Any]]
    dependencies: list[str]
    evidence_map: dict[str, list[str]]


FileSummary.__doc__ = "Summary of a file's algorithms, components, workflows, and responsibilities."


@dataclass(frozen=True)
class LibraryCharter:
    lib_id: str
    intent: str
    boundaries: str
    responsibilities: list[str]
    evidence_sources: list[dict[str, Any]]
    overlap_resolutions: list[dict[str, str]]


LibraryCharter.__doc__ = "Charter defining a library's intent, boundaries, and responsibilities."


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


def _extract_file_id(content: str) -> str:
    for line in content.splitlines():
        if "file id" in line.lower():
            parts = line.split(":", 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
    match = re.search(r"File Summary:\s*([\w\-\.]+)", content, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "unknown"


def _extract_pointers(text: str) -> list[str]:
    return [f"[{match.group(1)}::{match.group(2)}]" for match in EVIDENCE_POINTER_RE.finditer(text)]


def _strip_evidence(text: str) -> str:
    without_pointers = EVIDENCE_POINTER_RE.sub("", text)
    without_label = re.sub(r"(?i)\bEvidence\s*:\s*", "", without_pointers)
    return without_label.strip(" -|\t")


def _split_name_intent(text: str) -> tuple[str, str]:
    if "|" in text:
        parts = [part.strip() for part in text.split("|") if part.strip()]
        if len(parts) >= 2:
            return parts[0], " | ".join(parts[1:])
        if parts:
            return parts[0], ""
    for delimiter in (" -- ", " - ", ": "):
        if delimiter in text:
            name, intent = text.split(delimiter, 1)
            return name.strip(), intent.strip()
    return text.strip(), ""


def _parse_named_items(section_text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("-", "*")):
            continue
        raw = stripped.lstrip("-* ")
        evidence = _extract_pointers(raw)
        cleaned = _strip_evidence(raw)
        name, intent = _split_name_intent(cleaned)
        items.append({"name": name, "intent": intent, "evidence": evidence})
    return items


def _parse_responsibilities(section_text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("-", "*")):
            continue
        raw = stripped.lstrip("-* ")
        evidence = _extract_pointers(raw)
        description = _strip_evidence(raw)
        if description:
            items.append({"description": description, "evidence": evidence})
    return items


def _parse_dependencies(section_text: str) -> list[str]:
    deps = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("-", "*")):
            deps.append(stripped.lstrip("-* ").strip())
    if not deps and section_text.strip():
        deps = [part.strip() for part in section_text.split(",") if part.strip()]
    return deps


def _parse_evidence_map(section_text: str) -> dict[str, list[str]]:
    evidence_map: dict[str, list[str]] = {}
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("-", "*")):
            continue
        raw = stripped.lstrip("-* ")
        if ":" not in raw:
            continue
        section_label, rest = raw.split(":", 1)
        pointers = EVIDENCE_POINTER_RE.findall(rest)
        file_ids = [file_id for file_id, _ in pointers]
        if file_ids:
            evidence_map[section_label.strip()] = file_ids
    return evidence_map


def parse_file_summary(content: str) -> FileSummary:
    """Parse a file summary markdown string into a structured FileSummary."""
    file_id = _extract_file_id(content)
    sections = _extract_sections(content, level=2)

    def _get_section(*names: str) -> str:
        for name in names:
            if name in sections:
                return sections[name]
        return ""

    algorithms = _parse_named_items(_get_section("Algorithms", "ALGORITHMS"))
    components = _parse_named_items(_get_section("Components", "COMPONENTS"))
    workflows = _parse_named_items(_get_section("Workflows", "WORKFLOWS"))
    responsibilities = _parse_responsibilities(
        _get_section("Candidate Responsibilities", "CANDIDATE RESPONSIBILITIES")
    )
    dependencies = _parse_dependencies(_get_section("Dependencies", "DEPENDENCIES"))
    evidence_map = _parse_evidence_map(_get_section("Evidence Map", "EVIDENCE MAP"))

    return FileSummary(
        file_id=file_id,
        algorithms=algorithms,
        components=components,
        workflows=workflows,
        candidate_responsibilities=responsibilities,
        dependencies=dependencies,
        evidence_map=evidence_map,
    )


def _split_library_blocks(content: str) -> list[tuple[str, str]]:
    header_re = re.compile(r"^###\s+(lib_\d{3})\b.*$", re.MULTILINE)
    matches = list(header_re.finditer(content))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        lib_id = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        blocks.append((lib_id, content[start:end].strip()))
    return blocks


def _parse_overlap_resolutions(section_text: str) -> list[dict[str, str]]:
    resolutions: list[dict[str, str]] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("-", "*")):
            continue
        raw = stripped.lstrip("-* ").strip()
        if raw.lower() in {"none", "n/a", "no overlaps"}:
            continue
        if "->" in raw:
            description, decision = [part.strip() for part in raw.split("->", 1)]
        elif ":" in raw:
            description, decision = [part.strip() for part in raw.split(":", 1)]
        else:
            description, decision = raw, ""
        resolutions.append({"description": description, "decision": decision})
    return resolutions


def _extract_text_field(block: str, field: str) -> str:
    sections = _extract_sections(block, level=4)
    if field in sections and sections[field].strip():
        return sections[field].strip()
    for line in block.splitlines():
        if line.lower().startswith(f"{field.lower()}:"):
            return line.split(":", 1)[1].strip()
    return ""


def _extract_list_field(block: str, field: str) -> list[str]:
    sections = _extract_sections(block, level=4)
    text = sections.get(field, "")
    if not text:
        return []
    items = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("-", "*")):
            items.append(stripped.lstrip("-* ").strip())
    return items


def _extract_evidence_sources(block: str) -> list[dict[str, Any]]:
    sections = _extract_sections(block, level=4)
    evidence_text = sections.get("Evidence", "")
    pointers = EVIDENCE_POINTER_RE.findall(evidence_text)
    grouped: dict[str, set[str]] = {}
    for file_id, section in pointers:
        grouped.setdefault(file_id, set()).add(section)
    return [
        {"file_id": file_id, "sections": sorted(sections)} for file_id, sections in grouped.items()
    ]


def parse_library_synthesis(content: str) -> tuple[list[LibraryCharter], str]:
    """Parse a library synthesis markdown string into charters and index content."""
    sections = _extract_sections(content, level=2)
    index_section = sections.get("Library Index", "")
    index_entries: list[str] = []
    if index_section:
        for line in index_section.splitlines():
            stripped = line.strip()
            if not stripped.startswith(("-", "*")):
                continue
            raw = stripped.lstrip("-* ")
            index_entries.append(raw)

    charters: list[LibraryCharter] = []
    for lib_id, block in _split_library_blocks(content):
        intent = _extract_text_field(block, "Intent")
        boundaries = _extract_text_field(block, "Boundaries")
        responsibilities = _extract_list_field(block, "Responsibilities")
        evidence_sources = _extract_evidence_sources(block)
        overlap_text = _extract_sections(block, level=4).get("Overlap Resolutions", "")
        overlap_resolutions = _parse_overlap_resolutions(overlap_text)
        charters.append(
            LibraryCharter(
                lib_id=lib_id,
                intent=intent,
                boundaries=boundaries,
                responsibilities=responsibilities,
                evidence_sources=evidence_sources,
                overlap_resolutions=overlap_resolutions,
            )
        )

    if index_entries:
        index_lines = ["# Library Index", ""]
        for entry in index_entries:
            index_lines.append(f"- {entry}")
        index_content = "\n".join(index_lines).strip() + "\n"
    else:
        index_lines = ["# Library Index", ""]
        for charter in charters:
            intent = charter.intent or "Intent not provided"
            index_lines.append(f"- {charter.lib_id}: {intent}")
        index_content = "\n".join(index_lines).strip() + "\n"

    return charters, index_content


def parse_evidence_mapper_output(json_str: str) -> dict[str, Any]:
    """Parse glm-library-evidence-mapper JSON output."""
    import json

    data = json.loads(json_str)
    required_fields = ["file_id", "relevant_sections", "confidence", "rationale"]
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
    return data


def parse_gap_judge_output(json_str: str) -> dict[str, Any]:
    """Parse chatgpt-library-spec-gap-judge JSON output."""
    import json

    data = json.loads(json_str)
    required_fields = ["gaps", "total_gaps", "file_id"]
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
    return data


def parse_evidence_spotcheck_output(json_str: str) -> dict[str, Any]:
    """Parse chatgpt-evidence-gap-judge JSON output."""
    import json

    data = json.loads(json_str)
    required_fields = ["missing_sections", "scan_complete"]
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
    return data
