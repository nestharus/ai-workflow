"""Extract hollowed-out structure from a complete spec.md."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from spec_manager.schemas.hollowed_spec import (
    HollowedParagraph,
    HollowedSection,
    HollowedSpec,
    ParagraphKind,
)

# Minimal English stop words for keyword extraction.
# Non-English tokens are preserved and pass through unchanged.
STOP_WORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "has",
        "have",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "must",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "not",
        "no",
        "nor",
        "if",
        "then",
        "else",
        "when",
        "where",
        "how",
        "what",
        "which",
        "who",
        "whom",
        "each",
        "every",
        "all",
        "any",
        "some",
        "such",
        "than",
        "too",
        "very",
        "also",
        "just",
        "about",
        "above",
        "after",
        "again",
        "against",
        "below",
        "between",
        "both",
        "during",
        "from",
        "into",
        "more",
        "most",
        "other",
        "over",
        "same",
        "so",
        "only",
        "own",
        "here",
        "there",
        "once",
        "under",
        "until",
        "while",
        "up",
        "down",
        "out",
        "off",
        "through",
        "as",
    }
)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
ENTITY_REF_RE = re.compile(r"ENT-\d{4}")
TERM_RE = re.compile(r"[^\W\d_][\w]*", re.UNICODE)


def hollow_out_spec(lib_id: str, spec_content: str) -> HollowedSpec:
    """Parse a complete spec.md into a HollowedSpec with sections and paragraphs.

    Args:
        lib_id: Library ID (e.g. "LIB-0001")
        spec_content: Full text of the spec.md file

    Returns:
        HollowedSpec with populated sections, paragraphs, and indexes
    """
    spec_hash = hashlib.sha256(spec_content.encode("utf-8")).hexdigest()

    if not spec_content.strip():
        return HollowedSpec(lib_id=lib_id, spec_hash=spec_hash)

    raw_sections = _parse_sections(spec_content)
    sections: list[HollowedSection] = []
    paragraphs: dict[str, HollowedParagraph] = {}
    entity_index: dict[str, list[str]] = {}
    keyword_index: dict[str, list[str]] = {}

    para_ordinal = 0

    for raw_sec in raw_sections:
        section_id = raw_sec["section_id"]
        section_path = raw_sec["section_path"]
        paragraph_ids: list[str] = []

        # Split body into paragraphs at blank-line boundaries
        body_paragraphs = _split_into_paragraphs(raw_sec["body_lines"], raw_sec["body_start_line"])

        for para_text, line_start, line_end in body_paragraphs:
            para_ordinal += 1
            para_id = f"HPARA-{lib_id}-{para_ordinal:04d}"
            kind = _classify_paragraph(para_text)
            keywords = _extract_keywords(para_text)
            entity_refs = _extract_entity_refs(para_text)

            paragraph = HollowedParagraph(
                paragraph_id=para_id,
                section_path=section_path,
                kind=kind,
                text=para_text,
                keywords=keywords,
                entity_refs=entity_refs,
                line_start=line_start,
                line_end=line_end,
            )
            paragraphs[para_id] = paragraph
            paragraph_ids.append(para_id)

            # Update inverted indexes
            for kw in keywords:
                keyword_index.setdefault(kw, []).append(para_id)
            for ent in entity_refs:
                entity_index.setdefault(ent, []).append(para_id)

        section = HollowedSection(
            section_id=section_id,
            heading=raw_sec["heading"],
            level=raw_sec["level"],
            summary=raw_sec.get("summary", ""),
            paragraph_ids=paragraph_ids,
            child_section_ids=raw_sec.get("child_ids", []),
        )
        sections.append(section)

    # Build child_section_ids by tracking parent-child hierarchy
    _assign_child_section_ids(sections)

    return HollowedSpec(
        lib_id=lib_id,
        spec_hash=spec_hash,
        sections=sections,
        paragraphs=paragraphs,
        entity_index=entity_index,
        keyword_index=keyword_index,
    )


def _parse_sections(content: str) -> list[dict[str, Any]]:
    """Parse markdown headings into a section hierarchy."""
    lines = content.split("\n")
    sections: list[dict[str, Any]] = []
    section_ordinal = 0

    # Collect heading positions
    heading_positions: list[tuple[int, int, str]] = []  # (line_idx, level, heading_text)
    for idx, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if match:
            level = len(match.group(1))
            heading_text = match.group(2).strip()
            heading_positions.append((idx, level, heading_text))

    if not heading_positions:
        # No headings: treat entire content as a single section
        if content.strip():
            section_ordinal += 1
            sections.append(
                {
                    "section_id": f"HSEC-{section_ordinal:04d}",
                    "heading": "(root)",
                    "level": 1,
                    "section_path": "(root)",
                    "body_lines": lines,
                    "body_start_line": 1,
                    "child_ids": [],
                }
            )
        return sections

    # Build section path hierarchy
    path_stack: list[tuple[int, str]] = []  # (level, heading)

    for i, (line_idx, level, heading_text) in enumerate(heading_positions):
        section_ordinal += 1
        section_id = f"HSEC-{section_ordinal:04d}"

        # Update path stack
        while path_stack and path_stack[-1][0] >= level:
            path_stack.pop()
        path_stack.append((level, heading_text))
        section_path = ".".join(h for _, h in path_stack)

        # Determine body range: from line after heading to next heading or end
        body_start = line_idx + 1
        body_end = heading_positions[i + 1][0] if i + 1 < len(heading_positions) else len(lines)

        body_lines = lines[body_start:body_end]

        sections.append(
            {
                "section_id": section_id,
                "heading": heading_text,
                "level": level,
                "section_path": section_path,
                "body_lines": body_lines,
                "body_start_line": body_start + 1,  # 1-based
                "child_ids": [],
            }
        )

    return sections


def _assign_child_section_ids(sections: list[HollowedSection]) -> None:
    """Assign child_section_ids based on level hierarchy."""
    for i, section in enumerate(sections):
        children: list[str] = []
        for j in range(i + 1, len(sections)):
            if sections[j].level <= section.level:
                break
            if sections[j].level == section.level + 1:
                children.append(sections[j].section_id)
        section.child_section_ids = children


def _split_into_paragraphs(
    body_lines: list[str], body_start_line: int
) -> list[tuple[str, int, int]]:
    """Split body lines into paragraphs at blank-line boundaries.

    Returns list of (text, start_line, end_line) tuples (1-based lines).
    """
    paragraphs: list[tuple[str, int, int]] = []
    current_lines: list[str] = []
    current_start: int | None = None

    for offset, line in enumerate(body_lines):
        line_num = body_start_line + offset

        if not line.strip():
            if current_lines:
                text = "\n".join(current_lines)
                assert current_start is not None
                paragraphs.append((text, current_start, line_num - 1))
                current_lines = []
                current_start = None
        else:
            if current_start is None:
                current_start = line_num
            current_lines.append(line)

    if current_lines and current_start is not None:
        end_line = body_start_line + len(body_lines) - 1
        text = "\n".join(current_lines)
        paragraphs.append((text, current_start, end_line))

    return paragraphs


def _classify_paragraph(text: str) -> ParagraphKind:
    """Classify a text block by its structural type."""
    stripped = text.strip()

    # Check for code block
    if stripped.startswith("```") or (stripped.startswith("    ") and "\n" in stripped):
        return ParagraphKind.CODE_BLOCK

    # Check for table (pipes with header separator)
    lines = stripped.split("\n")
    if len(lines) >= 2:
        has_pipes = all("|" in line for line in lines)
        has_separator = any(re.match(r"^\s*\|?[\s\-:|]+\|", line) for line in lines)
        if has_pipes and has_separator:
            return ParagraphKind.TABLE

    # Check for heading
    if _HEADING_RE.match(stripped):
        return ParagraphKind.HEADING

    # Check for bullet list
    bullet_lines = [
        line
        for line in lines
        if line.strip().startswith(("-", "*", "+")) or re.match(r"^\s*\d+\.", line.strip())
    ]
    if bullet_lines and len(bullet_lines) >= len(lines) * 0.5:
        return ParagraphKind.BULLET_LIST

    return ParagraphKind.PROSE


def extract_terms(text: str, *, min_length: int = 3) -> list[str]:
    """Extract deduplicated search terms from free-form text.

    Tokenization is Unicode-aware and accepts any script's letter-leading tokens.
    """
    words = TERM_RE.findall(text)
    terms: list[str] = []
    seen: set[str] = set()

    for word in words:
        lower = word.lower()
        if len(lower) < min_length:
            continue
        if lower in STOP_WORDS:
            continue
        if lower in seen:
            continue
        seen.add(lower)
        terms.append(lower)

    return terms


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from a paragraph.

    Uses a stop-word filter and extracts terms that appear in technical
    specification contexts. Keywords are lowercased, deduplicated, and
    limited to terms >= 3 characters.
    """
    return extract_terms(text)


def _extract_entity_refs(text: str) -> list[str]:
    """Extract entity references (ENT-####) from paragraph text."""
    refs = ENTITY_REF_RE.findall(text)
    return sorted(set(refs))
