r"""Newline Handling.

All input files are normalized to LF (\n) newlines before processing to ensure
deterministic line-atom generation across platforms. This means:

1. CRLF (\r\n) → LF (\n)
2. CR (\r) → LF (\n)
3. LF (\n) → LF (\n) (unchanged)

Line splitting uses str.splitlines(keepends=False) after normalization.
SHA-256 hashes are computed on the normalized line text (UTF-8 encoded).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from scripts.spec_manager.spec_manager.schemas.sections import FileSections, SectionSpan
from scripts.spec_manager.spec_manager.schemas.validation_utils import (
    validate_section_coverage,
    validate_section_id_format,
)
from scripts.spec_refinement.core.gap import GapEvidence


def validate_sections(
    file_id: str,
    sections_path: Path,
    total_lines: int,
    evidence_output: Path,
) -> dict[str, Any]:
    """Validate section coverage for a file.

    Returns: {"valid": bool, "issues": list[str], "evidence_count": int}
    """
    issues: list[str] = []
    evidence_count = 0

    try:
        raw = sections_path.read_text(encoding="utf-8")
        sections = FileSections.model_validate_json(raw)
    except (OSError, ValidationError, ValueError, json.JSONDecodeError) as exc:
        issues.append(f"Failed to parse sections file: {exc}")
        evidence = GapEvidence(
            invariant_family="coverage",
            description="Section coverage validation failed",
            details={
                "file_id": file_id,
                "issues": issues,
                "sections_path": str(sections_path),
            },
            confidence=1.0,
            location=str(sections_path),
            detector="section-validator",
        )
        _emit_evidence(evidence, evidence_output)
        return {"valid": False, "issues": issues, "evidence_count": 1}

    coverage_issues = validate_section_coverage(
        sections.sections,
        total_lines,
    )
    issues.extend(coverage_issues)

    for index, section in enumerate(sections.sections, start=1):
        issues.extend(_validate_section_format(section, file_id, index))

    if issues:
        evidence = GapEvidence(
            invariant_family="coverage",
            description="Section coverage validation failed",
            details={
                "file_id": file_id,
                "issues": issues,
                "sections_path": str(sections_path),
            },
            confidence=1.0,
            location=str(sections_path),
            detector="section-validator",
        )
        _emit_evidence(evidence, evidence_output)
        evidence_count = 1

    return {"valid": not issues, "issues": issues, "evidence_count": evidence_count}


def _validate_section_format(
    section: SectionSpan,
    file_id: str,
    index: int,
) -> list[str]:
    issues: list[str] = []
    if not validate_section_id_format(section.section_id, file_id):
        issues.append(
            f"section {index} section_id {section.section_id} does not match "
            f"SEC-{file_id}-{{ordinal:04d}} format"
        )
        return issues

    try:
        ordinal = int(section.section_id.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        issues.append(
            f"section {index} section_id {section.section_id} does not match "
            f"SEC-{file_id}-{{ordinal:04d}} format"
        )
        return issues

    if ordinal != index:
        issues.append(
            f"section {index} section_id {section.section_id} does not match "
            f"expected ordinal {index:04d}"
        )

    return issues


def _emit_evidence(evidence: GapEvidence, output_path: Path) -> None:
    """Append evidence record to JSONL file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(evidence.to_dict(), sort_keys=True) + "\n")
