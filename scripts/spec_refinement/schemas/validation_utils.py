"""Validation utilities for Phase 1 section and atom coverage checks."""

from __future__ import annotations

import re

from scripts.spec_refinement.schemas.atoms import LineAtom
from scripts.spec_refinement.schemas.sections import SectionSpan

SECTION_ID_PATTERN = re.compile(r"^SEC-(?P<file_id>[^-]+)-(?P<ordinal>\d{4})$")
ATOM_ID_PATTERN = re.compile(r"^ATOM-(?P<file_id>[^-]+)-L(?P<line_no>\d{4})$")


def validate_section_id_format(section_id: str, file_id: str) -> bool:
    """Return True when section_id matches SEC-{file_id}-{ordinal:04d}."""
    match = SECTION_ID_PATTERN.fullmatch(section_id)
    return bool(match and match.group("file_id") == file_id)


def validate_atom_id_format(atom_id: str, file_id: str, line_no: int) -> bool:
    """Return True when atom_id matches ATOM-{file_id}-L{line_no:04d}."""
    match = ATOM_ID_PATTERN.fullmatch(atom_id)
    return bool(match and match.group("file_id") == file_id and int(match.group("line_no")) == line_no)


def validate_section_coverage(sections: list[SectionSpan], total_lines: int) -> list[str]:
    """Return coverage issues for a file's section spans."""
    issues: list[str] = []

    if total_lines < 0:
        issues.append("total_lines must be >= 0")
        return issues

    if total_lines == 0:
        if sections:
            issues.append("sections must be empty when total_lines is 0")
        return issues

    if not sections:
        issues.append("sections must not be empty when total_lines > 0")
        return issues

    expected_start = 1
    for index, section in enumerate(sections, start=1):
        if section.start_line != expected_start:
            issues.append(
                f"section {index} start_line {section.start_line} does not match expected {expected_start}"
            )
        if section.end_line < section.start_line:
            issues.append(f"section {index} end_line {section.end_line} < start_line {section.start_line}")
        if section.end_line > total_lines:
            issues.append(
                f"section {index} end_line {section.end_line} exceeds total_lines {total_lines}"
            )
        expected_start = section.end_line + 1

    if expected_start != total_lines + 1:
        issues.append(
            f"sections do not cover all lines: expected end_line {total_lines}, got {expected_start - 1}"
        )

    return issues


def validate_atom_sequence(atoms: list[LineAtom]) -> list[str]:
    """Return sequencing issues for line atoms."""
    issues: list[str] = []

    if not atoms:
        issues.append("atoms must not be empty")
        return issues

    expected_line = 1
    file_id: str | None = None
    for index, atom in enumerate(atoms, start=1):
        match = ATOM_ID_PATTERN.fullmatch(atom.atom_id)
        if not match:
            issues.append(f"atom {index} atom_id {atom.atom_id} is not in expected format")
        else:
            parsed_file_id = match.group("file_id")
            parsed_line_no = int(match.group("line_no"))
            if file_id is None:
                file_id = parsed_file_id
            elif parsed_file_id != file_id:
                issues.append(
                    f"atom {index} file_id {parsed_file_id} does not match previous file_id {file_id}"
                )
            if parsed_line_no != atom.line_no:
                issues.append(
                    f"atom {index} line_no {atom.line_no} does not match atom_id {parsed_line_no}"
                )

        if atom.line_no != expected_line:
            issues.append(
                f"atom {index} line_no {atom.line_no} does not match expected {expected_line}"
            )
        expected_line += 1

    return issues
