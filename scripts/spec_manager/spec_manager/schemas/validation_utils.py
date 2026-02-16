"""Validation utilities for Phase 1 section and atom coverage checks."""

from __future__ import annotations

import re
from datetime import datetime

from .atoms import ATOM_ID_PATTERN, LineAtom
from .sections import SectionSpan

LIB_ID_RE = re.compile(r"^LIB-\d{4}$")
ELEMENT_ID_RE = re.compile(
    r"^(?:DTL-LIB-\d{4}-\d{4}|CON-LIB-\d{4}-\d{4}|ANL-LIB-\d{4}-\d{4}|OVW-LIB-\d{4}-\d{4})$"
)
EDGE_ID_RE = re.compile(r"^EDGE-LIB-\d{4}-LIB-\d{4}$")
TASK_ID_RE = re.compile(r"^TASK-\d{4}$")
DECISION_ID_RE = re.compile(r"^ANL-LIB-\d{4}-\d{4}$")
SECTION_ID_PATTERN = re.compile(r"^SEC-(?P<file_uid>F\d{4})-(?P<ordinal>\d{4})$")


def validate_iso8601(value: str) -> str:
    """Validate an ISO-8601 timestamp with date-time precision."""
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("value must be ISO-8601") from exc
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("value must be ISO-8601")
    return value


def validate_section_id_format(section_id: str, file_uid: str) -> bool:
    """Return True when section_id matches SEC-{file_uid}-{ordinal:04d}."""
    match = SECTION_ID_PATTERN.fullmatch(section_id)
    return bool(match and match.group("file_uid") == file_uid)


def validate_atom_id_format(atom_id: str, file_uid: str, rev_id: str, line_no: int) -> bool:
    """Return True when atom_id matches ATOM-{file_uid}-{rev_id}-L{line_no:04d}."""
    match = ATOM_ID_PATTERN.fullmatch(atom_id)
    return bool(
        match
        and match.group("file_uid") == file_uid
        and match.group("rev_id") == rev_id
        and int(match.group("line_no")) == line_no
    )


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
                f"section {index} start_line {section.start_line} does not "
                f"match expected {expected_start}"
            )
        if section.end_line < section.start_line:
            issues.append(
                f"section {index} end_line {section.end_line} < start_line {section.start_line}"
            )
        if section.end_line > total_lines:
            issues.append(
                f"section {index} end_line {section.end_line} exceeds total_lines {total_lines}"
            )
        expected_start = section.end_line + 1

    if expected_start != total_lines + 1:
        issues.append(
            f"sections do not cover all lines: expected end_line {total_lines}, "
            f"got {expected_start - 1}"
        )

    return issues


def validate_atom_sequence(atoms: list[LineAtom], total_lines: int | None = None) -> list[str]:
    """Return sequencing issues for line atoms."""
    issues: list[str] = []

    if total_lines is not None and total_lines < 0:
        issues.append("total_lines must be >= 0")
        return issues

    if not atoms:
        if total_lines == 0:
            return issues
        issues.append("atoms must not be empty")
        return issues

    if total_lines == 0:
        issues.append("atoms must be empty when total_lines is 0")
        return issues

    expected_line = 1
    file_uid: str | None = None
    rev_id: str | None = None
    for index, atom in enumerate(atoms, start=1):
        match = ATOM_ID_PATTERN.fullmatch(atom.atom_id)
        if not match:
            issues.append(f"atom {index} atom_id {atom.atom_id} is not in expected format")
        else:
            parsed_file_uid = match.group("file_uid")
            parsed_rev_id = match.group("rev_id")
            parsed_line_no = int(match.group("line_no"))
            if file_uid is None:
                file_uid = parsed_file_uid
            elif parsed_file_uid != file_uid:
                issues.append(
                    f"atom {index} file_uid {parsed_file_uid} does not match "
                    f"previous file_uid {file_uid}"
                )
            if rev_id is None:
                rev_id = parsed_rev_id
            elif parsed_rev_id != rev_id:
                issues.append(
                    f"atom {index} rev_id {parsed_rev_id} does not match previous rev_id {rev_id}"
                )
            if parsed_file_uid != atom.file_uid:
                issues.append(
                    f"atom {index} file_uid {atom.file_uid} "
                    f"does not match atom_id {parsed_file_uid}"
                )
            if parsed_rev_id != atom.rev_id:
                issues.append(
                    f"atom {index} rev_id {atom.rev_id} does not match atom_id {parsed_rev_id}"
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
