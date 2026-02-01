"""Spec building workflow for Phase 4 spec refinement."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.spec_refinement.core.gap import Gap, GapEvidence, GapSynthesizer, format_gap_table
from scripts.spec_refinement.core.gap_queue import GapQueue
from scripts.spec_refinement.workspace import Phase, PhaseStatus, WorkspaceManager

from .agent_utils import run_agent
from .formats import EVIDENCE_POINTER_RE, parse_gap_judge_output, parse_spec_patch_output
from .progress import ProgressTracker
from .spec_patches import (
    VALID_SPEC_SECTIONS,
    SpecDocument,
    apply_patch,
    parse_patch_json,
    render_spec,
    validate_patch_citations,
    validate_patch_operation,
)
from .validation_utils import (
    build_file_id_lookup,
    build_section_alias_map,
    build_section_id_lookup,
    resolve_section_reference,
)

MAX_ITERATIONS_DEFAULT = 5
VALID_GAP_SEVERITIES = {"must", "should", "nice-to-have"}
SEVERITY_MAP = {"must": "error", "should": "warning", "nice-to-have": "info"}
MAX_RELEVANT_LINES_PER_SECTION = 12
GAP_AUDIT_FILE_ID = "evidence_union"


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


def _extract_evidence_section_blocks(content: str) -> dict[str, str]:
    explicit_matches = list(re.finditer(r"\[([A-Z_]+)\]", content))
    if explicit_matches:
        blocks: dict[str, str] = {}
        for index, match in enumerate(explicit_matches):
            label = match.group(1).strip()
            start = match.end()
            end = (
                explicit_matches[index + 1].start()
                if index + 1 < len(explicit_matches)
                else len(content)
            )
            text = content[start:end].strip()
            if label in blocks and text:
                blocks[label] = f"{blocks[label].rstrip()}\n{text}"
            else:
                blocks[label] = text
        return blocks

    heading_matches = list(re.finditer(r"^##\s+(.+)$", content, re.MULTILINE))
    if not heading_matches:
        return {}
    blocks = {}
    for index, match in enumerate(heading_matches):
        heading = match.group(1).strip()
        if not heading:
            continue
        label = heading.upper().replace(" ", "_")
        start = match.end()
        end = (
            heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(content)
        )
        text = content[start:end].strip()
        if label in blocks and text:
            blocks[label] = f"{blocks[label].rstrip()}\n{text}"
        else:
            blocks[label] = text
    return blocks


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


def _resolve_file_relpath(file_id: str, manager: WorkspaceManager) -> str:
    file_entry = manager.state.file_manifest.get(file_id)
    if isinstance(file_entry, dict):
        relpath = file_entry.get("relpath")
    elif isinstance(file_entry, str):
        relpath = file_entry
    else:
        relpath = None
    return relpath or ""


def _build_file_ref(file_id: str, manager: WorkspaceManager) -> str:
    relpath = _resolve_file_relpath(file_id, manager)
    return f"spec_snapshot/{relpath}" if relpath else file_id


def _build_file_ref_list(file_manifest: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for _, entry in file_manifest.items():
        relpath = None
        if isinstance(entry, dict):
            relpath = entry.get("relpath")
        elif isinstance(entry, str):
            relpath = entry
        if isinstance(relpath, str) and relpath:
            refs.append(f"spec_snapshot/{relpath}")
    return sorted(dict.fromkeys(refs))


def _collect_section_ids(
    file_id: str, manager: WorkspaceManager
) -> tuple[dict[str, Any], list[str]]:
    sections_data = manager.read_file_sections(file_id) or {}
    section_lookup = build_section_id_lookup(file_id, sections_data)
    section_ids = sorted(
        {value for value in section_lookup.values() if isinstance(value, str) and value}
    )
    if not section_ids:
        section_ids = [section for section in manager.get_section_labels(file_id) if section]
    return sections_data, section_ids


def _build_spec_template(lib_id: str, charter: dict[str, Any]) -> str:
    lines = [
        f"# Library Spec: {lib_id}",
        "",
        "## Intent",
        charter.get("intent", ""),
        "",
        "## Boundaries",
        charter.get("boundaries", ""),
        "",
        "## Requirements",
        "<!-- Requirements will be added during integration -->",
        "",
        "## Constraints",
        "<!-- Constraints will be added during integration -->",
        "",
        "## Dependencies",
        "<!-- Dependencies will be added during integration -->",
        "",
        "## Decisions Needed",
        "<!-- Ambiguities/contradictions will be recorded here -->",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _initialize_spec(lib_dir: Path, charter_content: str, lib_id: str) -> Path:
    spec_path = lib_dir / "spec.md"
    if spec_path.exists() and spec_path.read_text(encoding="utf-8").strip():
        return spec_path
    charter = _parse_charter(charter_content)
    spec_path.write_text(_build_spec_template(lib_id, charter), encoding="utf-8")
    return spec_path


def _build_full_spec_prompt_for_metrics(
    lib_id: str,
    charter_content: str,
    spec_content: str,
    file_id: str,
    file_ref: str,
    file_content: str,
    evidence_sections: list[str],
    valid_section_ids: list[str],
    gaps: list[Gap] | None = None,
) -> str:
    section_list = ", ".join(evidence_sections) if evidence_sections else "None"
    valid_list = ", ".join(valid_section_ids) if valid_section_ids else "None"
    example_section = valid_section_ids[0] if valid_section_ids else f"SEC-{file_id}-0001"
    example_pointer = f"[{file_ref}::{example_section}]"
    lines = [
        "## OUTPUT CONTRACT (REQUIRED)",
        "",
        "Return ONLY the updated spec markdown. No preamble, no code fences.",
        "",
        "REQUIRED RULES:",
        "- Preserve evidence-backed content; add missing details with citations "
        "[spec_snapshot/<relpath>::SECTION_ID].",
        "- Boundaries/Requirements/Constraints/Dependencies bullets MUST include at least "
        " one valid evidence pointer. Add missing citations to existing bullets too (including "
        " those originating from the charter).",
        "- When closing gaps, preserve key terms from the source/gap text verbatim.",
        "- If the gap list indicates an unsupported claim, move it to Decisions Needed as an "
        " explicit open question/assumption.",
        "- Never cite derived artifacts (charter, libraries, runs). Only cite SOURCE files via "
        " [spec_snapshot/<relpath>::SECTION_ID].",
        f"- Valid section IDs for citations in {file_ref}: {valid_list}",
        "",
        "FORBIDDEN:",
        "- Citing derived artifacts (charter, libraries, runs).",
        "- Paraphrasing key terms from gaps.",
        "",
        "## INPUT DATA",
        "",
        f"Library ID: {lib_id}",
        "",
        "Library Charter:",
        charter_content.strip(),
        "",
        f"Evidence Sections (anchors, not exclusive): {section_list}",
        f"Valid Section IDs For Citations in {file_ref}: {valid_list}",
        "",
        "Current Spec:",
        spec_content.strip(),
        "",
    ]
    if gaps:
        lines.extend(
            [
                "Focus on closing the following gaps:",
                format_gap_table(gaps),
                "",
            ]
        )
    lines.extend(
        [
            "Source File:",
            f"File ID: {file_id}",
            f"File Reference: {file_ref}",
            file_content.strip(),
        ]
    )
    lines.extend(
        [
            "",
            "## OUTPUT FORMAT",
            "",
            f"# Library Spec: {lib_id}",
            "## Boundaries",
            f"- Handles request intake and routing. {example_pointer}",
            "## Requirements",
            f"- Validate payloads before processing. {example_pointer}",
            "## Decisions Needed",
            f"- Confirm retention policy for incoming requests. {example_pointer}",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _summarize_spec_sections(spec_doc: SpecDocument) -> list[str]:
    return [
        f"- {section}: {spec_doc.count_bullets(section)} bullets" for section in VALID_SPEC_SECTIONS
    ]


def _select_relevant_spec_sections(
    spec_doc: SpecDocument, file_id: str, file_id_lookup: dict[str, str]
) -> dict[str, list[str]]:
    relevant: dict[str, list[str]] = {}
    for section_name, lines in spec_doc.section_lines.items():
        matches = []
        for line in lines:
            for match in EVIDENCE_POINTER_RE.finditer(line):
                file_ref = match.group(1).strip()
                resolved_file_id = file_id_lookup.get(file_ref)
                if resolved_file_id == file_id:
                    matches.append(line.strip())
                    break
        if matches:
            if len(matches) > MAX_RELEVANT_LINES_PER_SECTION:
                omitted = len(matches) - MAX_RELEVANT_LINES_PER_SECTION
                matches = matches[:MAX_RELEVANT_LINES_PER_SECTION]
                matches.append(f"... ({omitted} more omitted)")
            relevant[section_name] = matches
    return relevant


def _format_relevant_sections(
    relevant: dict[str, list[str]], section_order: list[str]
) -> list[str]:
    if not relevant:
        return ["None"]

    ordered = [section for section in VALID_SPEC_SECTIONS if section in relevant]
    for section in section_order:
        if section in relevant and section not in ordered:
            ordered.append(section)

    lines: list[str] = []
    for section in ordered:
        lines.append(f"[{section}]")
        lines.extend(relevant[section])
        lines.append("")
    return lines[:-1] if lines and not lines[-1] else lines


def _build_patch_prompt(
    lib_id: str,
    charter_content: str,
    spec_content: str,
    file_id: str,
    file_ref: str,
    file_content: str,
    evidence_sections: list[str],
    valid_section_ids: list[str],
    valid_file_refs: list[str],
    file_id_lookup: dict[str, str],
    gaps: list[Gap] | None = None,
) -> str:
    spec_doc = SpecDocument(spec_content)
    summaries = _summarize_spec_sections(spec_doc)
    relevant_sections = _select_relevant_spec_sections(spec_doc, file_id, file_id_lookup)
    relevant_lines = _format_relevant_sections(relevant_sections, spec_doc.section_order)
    section_list = ", ".join(evidence_sections) if evidence_sections else "None"
    valid_list = ", ".join(valid_section_ids) if valid_section_ids else "None"
    file_ref_list = ", ".join(valid_file_refs) if valid_file_refs else "None"
    valid_spec_sections = ", ".join(VALID_SPEC_SECTIONS)
    example_section = valid_section_ids[0] if valid_section_ids else f"SEC-{file_id}-0001"
    example_pointer = f"[{file_ref}::{example_section}]"
    lines = [
        "## OUTPUT CONTRACT (REQUIRED)",
        "",
        "Return ONLY a JSON object with keys: file_id, lib_id, patches. "
        "No preamble, no code fences.",
        "",
        "REQUIRED SCHEMA:",
        '{ "file_id": "F####", "lib_id": "lib_###", "patches": [ {'
        '"op": "add|edit|move", "section": "Spec Section", '
        '"bullet_index": int|null, "source_section": "Spec Section|null", '
        '"content": "text", "citations": ["[spec_snapshot/<relpath>::SECTION_ID]"] } ] }',
        "",
        "REQUIRED RULES:",
        "- Allowed ops: add, edit, move. Delete operations are FORBIDDEN",
        f"- Valid spec sections: {valid_spec_sections}",
        "- Each operation MUST target a valid spec section",
        "- Use add for new content, edit to refine an existing bullet, move to reclassify "
        "to Decisions Needed",
        "- Every bullet in Boundaries/Requirements/Constraints/Dependencies MUST include at "
        "least one citation",
        "- Citations MUST reference SOURCE files only (spec_snapshot/<relpath>::SECTION_ID format)",
        f"- Valid file references for citations (spec_snapshot/<relpath>): {file_ref_list}",
        f"- Valid section IDs for {file_ref}: {valid_list}",
        "- When closing gaps, preserve key terms from source/gap text verbatim",
        "- If gap indicates unsupported claim, move to Decisions Needed",
        "",
        "FORBIDDEN:",
        "- Delete operations",
        "- Citing derived artifacts (charter, libraries, runs)",
        "- Inventing section IDs not in allowlist",
        "- Paraphrasing key terms from gaps",
        "",
        "## INPUT DATA",
        "",
        f"Library ID: {lib_id}",
        f"Current File ID: {file_id}",
        f"Current File Reference: {file_ref}",
        "",
        "Library Charter:",
        charter_content.strip(),
        "",
        f"Evidence Sections (anchors, not exclusive): {section_list}",
        f"Valid Section IDs For Citations in {file_ref}: {valid_list}",
        "",
        "Current Spec Section Summaries:",
        *summaries,
        "",
        "Relevant Spec Sections (citations to current file):",
        *relevant_lines,
        "",
    ]
    if gaps:
        lines.extend(
            [
                "Focus on closing the following gaps:",
                format_gap_table(gaps),
                "",
            ]
        )
    lines.extend(
        [
            "Source File:",
            f"File ID: {file_id}",
            file_content.strip(),
            "",
            "## OUTPUT FORMAT",
            "",
            "Example:",
            '{ "file_id": "F0001", "lib_id": "lib_001", "patches": ['
            '{"op": "add", "section": "Requirements", "bullet_index": null, '
            f'"source_section": null, "content": "...", "citations": ["{example_pointer}"]{{}}'
            "] }",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _filter_open_gaps_for_file(gaps: list[Gap], file_ref: str) -> list[Gap]:
    needle = f"[{file_ref}::"
    return [
        gap
        for gap in gaps
        if gap.status == "open"
        and any(isinstance(src, str) and src.startswith(needle) for src in gap.source)
    ]


def _detect_remainder_content(
    spec_content: str,
    file_id: str,
    file_content: str,
    evidence_sections: list[str],
    manager: WorkspaceManager,
) -> list[GapEvidence]:
    _ = file_content
    file_id_lookup = build_file_id_lookup(
        manager.state.file_manifest, manager.structure.spec_snapshot_dir
    )
    section_alias_map = build_section_alias_map(manager.state.section_manifest)
    sections_data = manager.read_file_sections(file_id) or {}
    section_lookup = build_section_id_lookup(file_id, sections_data)

    pointers = EVIDENCE_POINTER_RE.findall(spec_content)
    cited_sections: set[str] = set()
    for file_ref, section_ref in pointers:
        resolved_file_id = file_id_lookup.get(file_ref)
        if resolved_file_id != file_id:
            continue
        canonical_section = resolve_section_reference(
            section_ref,
            resolved_file_id,
            section_alias_map,
            sections_data=sections_data,
        )
        if canonical_section:
            cited_sections.add(canonical_section)

    resolved_evidence_sections: set[str] = set()
    for section in evidence_sections:
        if not isinstance(section, str):
            continue
        raw = section.strip()
        if not raw:
            continue
        canonical = section_lookup.get(raw)
        if canonical is None:
            canonical = resolve_section_reference(
                raw,
                file_id,
                section_alias_map,
                sections_data=sections_data,
            )
        resolved_evidence_sections.add(canonical or raw)

    uncited = resolved_evidence_sections - cited_sections

    lib_id = "unknown"
    for line in spec_content.splitlines():
        if line.startswith("# Library Spec:"):
            lib_id = line.split(":", 1)[1].strip() or "unknown"
            break

    evidence_list: list[GapEvidence] = []
    for section in sorted(uncited):
        file_entry = manager.state.file_manifest.get(file_id, {})
        relpath = None
        if isinstance(file_entry, dict):
            relpath = file_entry.get("relpath")
        elif isinstance(file_entry, str):
            relpath = file_entry
        file_ref = f"spec_snapshot/{relpath}" if relpath else file_id
        evidence_list.append(
            GapEvidence(
                invariant_family="coverage",
                description=f"Section {section} not cited in spec",
                details={
                    "source": f"[{file_ref}::{section}]",
                    "derived_artifact_target": f"libraries/{lib_id}/spec.md",
                    "severity": "warning",
                    "gap_type": "coverage_failure",
                },
                confidence=1.0,
                detector="spec-remainder-detector",
            )
        )
    return evidence_list


def _extract_spec_markdown(output: str, lib_id: str) -> str:
    """Strip agent chatter and return the spec markdown document.

    Some models occasionally prepend short natural-language commentary.
    Keep extraction deterministic by anchoring on the required title.
    """
    needle = f"# Library Spec: {lib_id}"
    idx = output.find(needle)
    if idx == -1:
        return output
    doc = output[idx:].lstrip()
    # Strip a stray trailing code fence (some models occasionally append one).
    stripped = doc.rstrip()
    lines = stripped.splitlines()
    if lines and lines[-1].strip() == "```":
        doc = "\n".join(lines[:-1]).rstrip() + "\n"
    return doc


def _build_gap_prompt(
    spec_content: str,
    file_id: str,
    file_ref: str,
    file_content: str,
    evidence_sections: list[str],
    valid_section_ids: list[str],
) -> str:
    section_list = ", ".join(evidence_sections) if evidence_sections else "None"
    valid_list = ", ".join(valid_section_ids) if valid_section_ids else "None"
    lines = [
        "## OUTPUT CONTRACT (REQUIRED)",
        "",
        "Return ONLY valid JSON. No preamble, no code fences.",
        "",
        "REQUIRED SCHEMA:",
        '{"gaps": [{"source": "string", "missing_content": "string", "where_in_spec": "string", '
        '"severity": "must|should|nice-to-have"}], "total_gaps": int, "file_id": "string"}',
        "",
        "REQUIRED RULES:",
        "- Only report gaps for statements explicitly present in the source (within Scope)",
        "- Do NOT infer or invent new requirements/behaviors not stated in the source",
        "- If the spec already captures the detail anywhere (including Decisions Needed), "
        "it is NOT a gap",
        f"- Scope: only consider gaps from these source sections for {file_ref}: {section_list}",
        "- Use source pointers in [spec_snapshot/<relpath>::SECTION_ID] format",
        f"- Valid section IDs for citations in {file_ref}: {valid_list}",
        "- If Scope is None/empty, return gaps=[] and total_gaps=0",
        "",
        "FORBIDDEN:",
        "- Gaps outside the scope sections",
        "- Invented requirements or behaviors",
        "",
        "## INPUT DATA",
        "",
        "Spec:",
        spec_content.strip(),
        "",
        "Source File:",
        f"File ID: {file_id}",
        f"File Reference: {file_ref}",
        file_content.strip(),
        "",
        "## OUTPUT FORMAT",
        "",
        "Example:",
        '{"gaps": [], "total_gaps": 0, "file_id": "F0001"}',
    ]
    return "\n".join(lines).strip() + "\n"


def _build_evidence_union(
    lib_id: str,
    manager: WorkspaceManager,
    evidence_map: dict[str, list[str]],
    issues: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    union_lines: list[str] = []
    union_sources: list[str] = []

    for file_id, evidence_sections in evidence_map.items():
        if not evidence_sections:
            continue
        file_path = manager.get_file_path(file_id)
        if file_path is None or not file_path.exists():
            continue
        file_content = file_path.read_text(encoding="utf-8")
        section_blocks = _extract_evidence_section_blocks(file_content)
        for section in evidence_sections:
            file_entry = manager.state.file_manifest.get(file_id, {})
            relpath = None
            if isinstance(file_entry, dict):
                relpath = file_entry.get("relpath")
            elif isinstance(file_entry, str):
                relpath = file_entry
            file_ref = f"spec_snapshot/{relpath}" if relpath else file_id
            pointer = f"[{file_ref}::{section}]"
            union_sources.append(pointer)
            union_lines.append(pointer)
            section_text = section_blocks.get(section)
            if section_text:
                union_lines.append(section_text.strip())
            else:
                issues.append(
                    {
                        "type": "evidence_section_missing",
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "section": section,
                        "message": "Evidence section content not found for gap audit.",
                    }
                )
                union_lines.append("(Section content not found.)")
            union_lines.append("")

    if union_lines and not union_lines[-1].strip():
        union_lines = union_lines[:-1]

    return union_lines, union_sources


def _build_gap_audit_prompt(
    spec_content: str,
    evidence_union: list[str],
    evidence_sources: list[str],
) -> str:
    source_list = ", ".join(evidence_sources) if evidence_sources else "None"
    union_block = evidence_union if evidence_union else ["None"]
    lines = [
        "Review the spec against the evidence union and report gaps.",
        "Return JSON with keys: gaps, total_gaps, file_id.",
        "Only report gaps for statements explicitly present in the evidence union below.",
        "Do NOT infer or invent new requirements/behaviors that are not stated.",
        "If the spec already captures the detail anywhere (including Decisions"
        " Needed), it is NOT a gap.",
        "Use source pointers in [spec_snapshot/<relpath>::SECTION_ID] format.",
        "Source must match one of the Evidence Union Sources listed below.",
        f'Set file_id to "{GAP_AUDIT_FILE_ID}".',
        "",
        f"Evidence Union Sources: {source_list}",
        "",
        "Spec:",
        spec_content.strip(),
        "",
        "Evidence Union:",
        *union_block,
    ]
    return "\n".join(lines).strip() + "\n"


def _validate_spec_citations(
    content: str, manager: WorkspaceManager, lib_id: str
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    pointer_matches = list(EVIDENCE_POINTER_RE.finditer(content))
    if not pointer_matches:
        issues.append(
            {
                "type": "missing_evidence_pointers",
                "lib_id": lib_id,
                "message": "No evidence pointers found.",
            }
        )
        return issues

    file_id_lookup = build_file_id_lookup(
        manager.state.file_manifest, manager.structure.spec_snapshot_dir
    )
    section_alias_map = build_section_alias_map(manager.state.section_manifest)
    sections_cache: dict[str, dict[str, Any]] = {}

    for match in pointer_matches:
        file_ref = match.group(1).strip()
        section_ref = match.group(2).strip()
        resolved_file_id = file_id_lookup.get(file_ref)
        if resolved_file_id is None:
            issues.append(
                {
                    "type": "unknown_file_reference",
                    "lib_id": lib_id,
                    "pointer": match.group(0),
                    "message": f"Unknown file reference: {file_ref}",
                }
            )
            continue
        sections_data = sections_cache.get(resolved_file_id)
        if sections_data is None:
            sections_data = manager.read_file_sections(resolved_file_id) or {}
            sections_cache[resolved_file_id] = sections_data
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
                    "lib_id": lib_id,
                    "pointer": match.group(0),
                    "message": (
                        f"Unknown section reference: {section_ref} (file: {resolved_file_id})"
                    ),
                }
            )

    sections = _extract_sections(content, level=2)
    for section_name in ("Boundaries", "Requirements", "Constraints", "Dependencies"):
        section_text = sections.get(section_name, "")
        for line in section_text.splitlines():
            stripped = line.strip()
            if not stripped.startswith(("-", "*")):
                continue
            if not EVIDENCE_POINTER_RE.search(stripped):
                issues.append(
                    {
                        "type": "missing_citation",
                        "lib_id": lib_id,
                        "section": section_name,
                        "line": stripped,
                        "message": "Bullet missing evidence pointer.",
                    }
                )

    return issues


def _read_evidence_sources(lib_dir: Path) -> list[dict[str, Any]]:
    evidence_path = lib_dir / "evidence.json"
    if not evidence_path.exists():
        return []
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    sources = payload.get("sources", [])
    return sources if isinstance(sources, list) else []


def _normalize_evidence_sources(
    sources: list[dict[str, Any]],
) -> dict[str, list[str]]:
    merged: dict[str, set[str]] = {}
    for source in sources:
        file_id = source.get("file_id")
        if not isinstance(file_id, str):
            continue
        sections = source.get("sections", [])
        if not isinstance(sections, list):
            sections = []
        merged.setdefault(file_id, set()).update(section for section in sections if section)
    return {file_id: sorted(sections) for file_id, sections in merged.items()}


def _update_decisions(lib_dir: Path, spec_content: str) -> None:
    sections = _extract_sections(spec_content, level=2)
    decisions_text = sections.get("Decisions Needed", "").strip()
    decisions_path = lib_dir / "decisions.md"
    if decisions_text:
        decisions_path.write_text(f"## Decisions Needed\n\n{decisions_text}\n", encoding="utf-8")
    else:
        decisions_path.write_text("", encoding="utf-8")


def _gap_signature(gaps: list[Gap]) -> tuple[str, ...]:
    return tuple(sorted(gap.id for gap in gaps if gap.status == "open"))


def _log_history_event(manager: WorkspaceManager, event: str, payload: dict[str, Any]) -> None:
    manager.state.history.append(
        {
            "timestamp": datetime.now().isoformat(),
            "event": event,
            **payload,
        }
    )


def _build_gaps_from_judge(
    lib_id: str,
    file_id: str,
    raw_gaps: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    detector: str = "chatgpt-library-spec-gap-judge",
) -> list[GapEvidence]:
    evidence_list: list[GapEvidence] = []
    for gap_finding in raw_gaps:
        if not isinstance(gap_finding, dict):
            continue
        severity_raw = str(gap_finding.get("severity", "")).strip().lower()
        if severity_raw not in VALID_GAP_SEVERITIES:
            issues.append(
                {
                    "type": "invalid_gap_severity",
                    "lib_id": lib_id,
                    "file_id": file_id,
                    "severity": severity_raw,
                    "message": "Gap severity must be must/should/nice-to-have.",
                }
            )
            severity_raw = "nice-to-have"
        mapped_severity = SEVERITY_MAP[severity_raw]
        evidence_list.append(
            GapEvidence(
                invariant_family="content",
                description=gap_finding.get("missing_content", ""),
                details={
                    "source": gap_finding.get("source", file_id),
                    "derived_artifact_target": f"libraries/{lib_id}/spec.md",
                    "where_in_spec": gap_finding.get("where_in_spec", ""),
                    "severity": mapped_severity,
                    "reported_severity": severity_raw,
                    "gap_type": "missing_detail",
                },
                confidence=1.0,
                location=gap_finding.get("source", file_id),
                detector=detector,
            )
        )
    return evidence_list


def _build_library_spec(
    manager: WorkspaceManager,
    lib_dir: Path,
    max_iterations: int,
) -> dict[str, Any]:
    lib_id = lib_dir.name
    errors: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    iterations = 0
    converged = False

    charter_path = lib_dir / "charter.md"
    if not charter_path.exists():
        return {
            "lib_id": lib_id,
            "errors": [{"lib_id": lib_id, "error": "Missing charter.md for library."}],
            "issues": [],
            "iterations": 0,
            "converged": False,
            "failed": True,
            "coverage_metrics": {},
        }

    charter_content = charter_path.read_text(encoding="utf-8")
    spec_path = _initialize_spec(lib_dir, charter_content, lib_id)

    sources = _read_evidence_sources(lib_dir)
    evidence_map = _normalize_evidence_sources(sources)
    if not evidence_map:
        return {
            "lib_id": lib_id,
            "errors": [{"lib_id": lib_id, "error": "No evidence sources available for library."}],
            "issues": [],
            "iterations": 0,
            "converged": False,
            "failed": True,
            "coverage_metrics": {},
        }

    file_id_lookup = build_file_id_lookup(
        manager.state.file_manifest, manager.structure.spec_snapshot_dir
    )
    section_alias_map = build_section_alias_map(manager.state.section_manifest)
    valid_file_refs = _build_file_ref_list(manager.state.file_manifest)
    section_id_allowlists: dict[str, list[str]] = {}
    for manifest_file_id in manager.state.file_manifest:
        manifest_file_ref = _build_file_ref(manifest_file_id, manager)
        _, section_ids = _collect_section_ids(manifest_file_id, manager)
        section_id_allowlists[manifest_file_ref] = section_ids

    existing_gaps = manager.read_library_gaps(lib_id)
    gap_queue = manager.get_library_gap_queue(lib_id)
    if not (lib_dir / "gap_queue.json").exists():
        gap_queue = GapQueue(gaps=existing_gaps)
    gap_history: list[tuple[str, ...]] = []
    total_patches_applied = 0
    total_files_processed = 0
    total_prompt_size_old = 0
    total_prompt_size_new = 0
    coverage_metrics: dict[str, Any] = {}

    for iteration in range(max_iterations):
        iterations += 1
        gap_focus = (
            [gap for gap in existing_gaps if gap.status == "open"] if iteration > 0 else None
        )

        for file_id, sections in evidence_map.items():
            file_path = manager.get_file_path(file_id)
            if file_path is None or not file_path.exists():
                errors.append(
                    {
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "error": "Source file not found.",
                    }
                )
                continue

            file_content = file_path.read_text(encoding="utf-8")
            current_spec = spec_path.read_text(encoding="utf-8")
            file_ref = _build_file_ref(file_id, manager)
            _, valid_section_ids = _collect_section_ids(file_id, manager)
            file_gaps = _filter_open_gaps_for_file(gap_focus, file_ref) if gap_focus else None
            prompt = _build_patch_prompt(
                lib_id,
                charter_content,
                current_spec,
                file_id,
                file_ref,
                file_content,
                sections,
                valid_section_ids,
                valid_file_refs,
                file_id_lookup,
                gaps=file_gaps,
            )
            legacy_prompt_size = len(
                _build_full_spec_prompt_for_metrics(
                    lib_id,
                    charter_content,
                    current_spec,
                    file_id,
                    file_ref,
                    file_content,
                    sections,
                    valid_section_ids,
                    gaps=file_gaps,
                )
            )
            new_prompt_size = len(prompt)
            total_prompt_size_old += legacy_prompt_size
            total_prompt_size_new += new_prompt_size
            reduction_pct = (
                ((legacy_prompt_size - new_prompt_size) / legacy_prompt_size) * 100
                if legacy_prompt_size
                else 0.0
            )
            total_files_processed += 1
            _log_history_event(
                manager,
                "spec_patch_prompt_stats",
                {
                    "lib_id": lib_id,
                    "file_id": file_id,
                    "old_prompt_size": legacy_prompt_size,
                    "new_prompt_size": new_prompt_size,
                    "reduction_pct": round(reduction_pct, 2),
                },
            )
            try:
                output = run_agent(
                    agent_name="glm-library-spec-integrator",
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

            output_text = output

            try:
                patch_payload = parse_spec_patch_output(output)
                patch_json = json.dumps(
                    {
                        "operations": patch_payload.get("patches", []),
                        "lib_id": patch_payload.get("lib_id", "unknown"),
                        "file_id": patch_payload.get("file_id", "unknown"),
                    }
                )
                patch_set = parse_patch_json(patch_json)
            except Exception as exc:
                errors.append(
                    {
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "error": f"Failed to parse patch output: {exc}",
                    }
                )
                continue

            valid_ops = []
            for operation in patch_set.operations:
                op_errors = validate_patch_operation(operation, VALID_SPEC_SECTIONS)
                if op_errors:
                    issues.append(
                        {
                            "type": "invalid_patch_operation",
                            "lib_id": lib_id,
                            "file_id": file_id,
                            "operation": {
                                "op": operation.op,
                                "section": operation.section,
                                "bullet_index": operation.bullet_index,
                            },
                            "message": "; ".join(op_errors),
                        }
                    )
                    _log_history_event(
                        manager,
                        "spec_patch_operation_invalid",
                        {
                            "lib_id": lib_id,
                            "file_id": file_id,
                            "errors": op_errors,
                        },
                    )
                    continue
                valid_ops.append(operation)

            citation_issues = validate_patch_citations(
                valid_ops,
                file_id_lookup,
                section_alias_map,
                lib_id=lib_id,
            )
            if citation_issues:
                issues.extend(citation_issues)
                _log_history_event(
                    manager,
                    "spec_patch_validation_failed",
                    {
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "errors": citation_issues,
                    },
                )
                from .repair import ArtifactType, get_repair_model, repair_artifact

                try:
                    repaired_output = repair_artifact(
                        output=output_text,
                        errors=citation_issues,
                        allowlists={
                            "file_refs": valid_file_refs,
                            "sections": section_id_allowlists,
                        },
                        artifact_type=ArtifactType.SPEC_PATCHES,
                        model_override=get_repair_model(),
                        manager=manager,
                    )
                    repaired_patch_set = parse_patch_json(repaired_output)
                    repaired_ops = []
                    for operation in repaired_patch_set.operations:
                        op_errors = validate_patch_operation(operation, VALID_SPEC_SECTIONS)
                        if op_errors:
                            issues.append(
                                {
                                    "type": "invalid_patch_operation",
                                    "lib_id": lib_id,
                                    "file_id": file_id,
                                    "operation": {
                                        "op": operation.op,
                                        "section": operation.section,
                                        "bullet_index": operation.bullet_index,
                                    },
                                    "message": "; ".join(op_errors),
                                }
                            )
                            continue
                        repaired_ops.append(operation)
                    repaired_issues = validate_patch_citations(
                        repaired_ops,
                        file_id_lookup,
                        section_alias_map,
                        lib_id=lib_id,
                    )
                    if not repaired_issues:
                        valid_ops = repaired_ops
                        issues = [issue for issue in issues if issue not in citation_issues]
                except Exception as exc:
                    issues.append(
                        {
                            "type": "repair_failed",
                            "lib_id": lib_id,
                            "message": f"Spec patch repair failed: {exc}",
                        }
                    )

            spec_doc = SpecDocument(current_spec)
            applied_ops = []
            for operation in valid_ops:
                try:
                    apply_patch(spec_doc, operation)
                    applied_ops.append(operation)
                except Exception as exc:
                    issues.append(
                        {
                            "type": "patch_apply_failed",
                            "lib_id": lib_id,
                            "file_id": file_id,
                            "operation": {
                                "op": operation.op,
                                "section": operation.section,
                                "bullet_index": operation.bullet_index,
                            },
                            "message": str(exc),
                        }
                    )

            updated_spec = render_spec(spec_doc, lib_id)
            spec_path.write_text(updated_spec, encoding="utf-8")
            _update_decisions(lib_dir, updated_spec)

            patch_counts = {"add": 0, "edit": 0, "move": 0}
            for operation in applied_ops:
                if operation.op in patch_counts:
                    patch_counts[operation.op] += 1
            total_patches_applied += len(applied_ops)
            _log_history_event(
                manager,
                "spec_patch_counts",
                {
                    "lib_id": lib_id,
                    "file_id": file_id,
                    "counts": patch_counts,
                },
            )

        spec_content = spec_path.read_text(encoding="utf-8")
        evidence_list: list[GapEvidence] = []

        for file_id, evidence_sections in evidence_map.items():
            file_path = manager.get_file_path(file_id)
            if file_path is None or not file_path.exists():
                continue
            file_content = file_path.read_text(encoding="utf-8")
            file_ref = _build_file_ref(file_id, manager)
            _, valid_section_ids = _collect_section_ids(file_id, manager)
            prompt = _build_gap_prompt(
                spec_content,
                file_id,
                file_ref,
                file_content,
                evidence_sections,
                valid_section_ids,
            )
            try:
                output = run_agent(
                    agent_name="chatgpt-library-spec-gap-judge",
                    prompt=prompt,
                    workspace=manager.workspace_path,
                )
            except RuntimeError as exc:
                errors.append(
                    {
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "error": f"Gap judge failed: {exc}",
                    }
                )
                continue

            try:
                data = parse_gap_judge_output(output)
            except Exception as exc:  # pragma: no cover - defensive logging
                errors.append(
                    {
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "error": f"Failed to parse gap output: {exc}",
                    }
                )
                continue

            raw_gaps = data.get("gaps", [])
            evidence_list.extend(_build_gaps_from_judge(lib_id, file_id, raw_gaps, issues))
            remainder_evidence = _detect_remainder_content(
                spec_content,
                file_id,
                file_content,
                evidence_sections,
                manager,
            )
            evidence_list.extend(remainder_evidence)

        audit_union, audit_sources = _build_evidence_union(
            lib_id,
            manager,
            evidence_map,
            issues,
        )
        audit_prompt = _build_gap_audit_prompt(spec_content, audit_union, audit_sources)
        try:
            audit_output = run_agent(
                agent_name="chatgpt-library-spec-gap-judge",
                prompt=audit_prompt,
                workspace=manager.workspace_path,
            )
        except RuntimeError as exc:
            errors.append(
                {
                    "lib_id": lib_id,
                    "file_id": GAP_AUDIT_FILE_ID,
                    "error": f"Gap audit failed: {exc}",
                }
            )
        else:
            try:
                audit_data = parse_gap_judge_output(audit_output)
            except Exception as exc:  # pragma: no cover - defensive logging
                errors.append(
                    {
                        "lib_id": lib_id,
                        "file_id": GAP_AUDIT_FILE_ID,
                        "error": f"Failed to parse gap audit output: {exc}",
                    }
                )
            else:
                raw_gaps = audit_data.get("gaps", [])
                evidence_list.extend(
                    _build_gaps_from_judge(
                        lib_id,
                        GAP_AUDIT_FILE_ID,
                        raw_gaps,
                        issues,
                        detector="gpt-5.2-xhigh-gap-audit",
                    )
                )

        synthesizer = GapSynthesizer()
        new_gaps = synthesizer.cluster_evidence(evidence_list) if evidence_list else []
        existing_gaps = synthesizer.merge_gaps(existing_gaps, new_gaps)

        if not new_gaps:
            existing_gaps = []

        gap_queue.update(existing_gaps)
        coverage_metrics = gap_queue.get_coverage_metrics()
        _log_history_event(
            manager,
            "gap_coverage_metrics",
            {
                "lib_id": lib_id,
                **coverage_metrics,
            },
        )

        manager.write_library_gaps(
            lib_id,
            existing_gaps,
            gap_queue=gap_queue,
            update_queue=False,
        )

        if not new_gaps or gap_queue.is_stagnant:
            gap_queue.mark_progress()
            manager.write_library_gap_queue(lib_id, gap_queue)
            manager.record_gap_audit(
                Phase.SPEC_BUILDING,
                gaps=existing_gaps,
                converged=True,
                coverage_metrics=coverage_metrics,
            )
            converged = True
            break

        manager.record_gap_audit(
            Phase.SPEC_BUILDING,
            gaps=existing_gaps,
            converged=False,
            coverage_metrics=coverage_metrics,
        )

        signature = _gap_signature(existing_gaps)
        gap_history.append(signature)

    return {
        "lib_id": lib_id,
        "errors": errors,
        "issues": issues,
        "iterations": iterations,
        "converged": converged,
        "failed": not converged and bool(existing_gaps),
        "patches_applied": total_patches_applied,
        "files_processed": total_files_processed,
        "prompt_size_old": total_prompt_size_old,
        "prompt_size_new": total_prompt_size_new,
        "context_reduction_pct": (
            ((total_prompt_size_old - total_prompt_size_new) / total_prompt_size_old) * 100
            if total_prompt_size_old
            else 0.0
        ),
        "coverage_metrics": coverage_metrics,
    }


def build_specs(run_id: str, max_iterations: int = MAX_ITERATIONS_DEFAULT) -> dict[str, Any]:
    """Build library specs with audit-driven gap closure (Phase 4)."""
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized. Run init before spec building.")

    expansion_status = manager.state.phases[Phase.EVIDENCE_EXPANSION.value].status
    if expansion_status != PhaseStatus.COMPLETED:
        raise RuntimeError("Evidence expansion must be completed before spec building.")

    manager.start_phase(Phase.SPEC_BUILDING)

    libraries_dir = manager.structure.libraries_dir
    lib_dirs = [lib_dir for lib_dir in sorted(libraries_dir.iterdir()) if lib_dir.is_dir()]

    tracker = ProgressTracker(
        total=len(lib_dirs),
        description="Building library specs",
        manager=manager,
    )

    libraries_built = 0
    total_iterations = 0
    converged_count = 0
    total_patches_applied = 0
    total_files_processed = 0
    total_prompt_size_old = 0
    total_prompt_size_new = 0
    errors: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    failed_libraries = 0
    coverage_ratios: list[float] = []
    coverage_by_library: dict[str, dict[str, Any]] = {}

    for lib_dir in lib_dirs:
        result = _build_library_spec(manager, lib_dir, max_iterations)
        total_iterations += result.get("iterations", 0)
        total_patches_applied += result.get("patches_applied", 0)
        total_files_processed += result.get("files_processed", 0)
        total_prompt_size_old += result.get("prompt_size_old", 0)
        total_prompt_size_new += result.get("prompt_size_new", 0)
        errors.extend(result.get("errors", []))
        issues.extend(result.get("issues", []))
        metrics = result.get("coverage_metrics")
        if isinstance(metrics, dict) and metrics:
            coverage_by_library[lib_dir.name] = metrics
            ratio = metrics.get("convergence_ratio")
            if isinstance(ratio, (int, float)):
                coverage_ratios.append(float(ratio))
        if result.get("failed"):
            failed_libraries += 1
        else:
            libraries_built += 1
            if result.get("converged"):
                converged_count += 1
        tracker.update(status=lib_dir.name)

    tracker.finish()

    phase_result = manager.state.phases[Phase.SPEC_BUILDING.value]
    phase_result.issues = errors + issues

    total_libs = len(lib_dirs)
    failure_ratio = (failed_libraries / total_libs) if total_libs else 0
    avg_patches_per_file = (
        total_patches_applied / total_files_processed if total_files_processed else 0.0
    )
    context_reduction_pct = (
        ((total_prompt_size_old - total_prompt_size_new) / total_prompt_size_old) * 100
        if total_prompt_size_old
        else 0.0
    )
    avg_convergence_ratio = sum(coverage_ratios) / len(coverage_ratios) if coverage_ratios else 1.0
    coverage_payload = {
        "total_coverage_ratio": avg_convergence_ratio,
        "libraries": coverage_by_library,
    }
    outputs = {
        "libraries_built": libraries_built,
        "total_iterations": total_iterations,
        "converged_count": converged_count,
        "total_patches_applied": total_patches_applied,
        "avg_patches_per_file": round(avg_patches_per_file, 2),
        "context_reduction_pct": round(context_reduction_pct, 2),
        "total_coverage_ratio": round(avg_convergence_ratio, 2),
        "coverage_metrics": coverage_payload,
    }

    if total_libs > 0 and failure_ratio > 0.5:
        manager.fail_phase(Phase.SPEC_BUILDING, error="Too many library failures")
    else:
        manager.complete_phase(Phase.SPEC_BUILDING, outputs=outputs)

    return {
        "libraries_built": libraries_built,
        "total_iterations": total_iterations,
        "converged_count": converged_count,
        "errors": errors,
        "issues": issues,
        "outputs": outputs,
        "coverage_metrics": coverage_by_library,
        "total_coverage_ratio": avg_convergence_ratio,
    }
