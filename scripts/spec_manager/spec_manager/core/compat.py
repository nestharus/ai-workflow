"""Atom ID parsing and upgrade utilities.

Supports both legacy (v1) and new (v2) atom ID formats:
- v1 (legacy): ATOM-F####-L#### (e.g. ATOM-F0001-L0042)
- v2 (new):    ATOM-F####-R####-L#### (e.g. ATOM-F0001-R0001-L0042)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LEGACY_ATOM_PATTERN = re.compile(
    r"^ATOM-(?P<file_id>F\d{4})-L(?P<line_no>\d{4})$"
)

NEW_ATOM_PATTERN = re.compile(
    r"^ATOM-(?P<file_uid>F\d{4})-(?P<rev_id>R\d{4})-L(?P<line_no>\d{4})$"
)

DEFAULT_LEGACY_REV_ID = "R0001"


@dataclass
class ParsedAtomId:
    """Parsed components of an atom ID."""

    file_uid: str
    rev_id: str
    line_no: int
    format: str  # "v1" or "v2"

    @property
    def atom_id(self) -> str:
        """Reconstruct the atom ID in v2 format."""
        return f"ATOM-{self.file_uid}-{self.rev_id}-L{self.line_no:04d}"


def parse_atom_id(atom_id: str) -> ParsedAtomId:
    """Parse an atom ID string into its components.

    Raises:
        ValueError: If the atom ID doesn't match any known format.
    """
    m = NEW_ATOM_PATTERN.match(atom_id)
    if m:
        return ParsedAtomId(
            file_uid=m.group("file_uid"),
            rev_id=m.group("rev_id"),
            line_no=int(m.group("line_no")),
            format="v2",
        )

    m = LEGACY_ATOM_PATTERN.match(atom_id)
    if m:
        return ParsedAtomId(
            file_uid=m.group("file_id"),
            rev_id=DEFAULT_LEGACY_REV_ID,
            line_no=int(m.group("line_no")),
            format="v1",
        )

    raise ValueError(f"Invalid atom ID format: {atom_id!r}")


def upgrade_atom_id(atom_id: str) -> str:
    """Upgrade a legacy v1 atom ID to v2 format.

    If already v2, returns unchanged. Raises ValueError for invalid IDs.
    """
    parsed = parse_atom_id(atom_id)
    return parsed.atom_id


def is_legacy_format(atom_id: str) -> bool:
    """Check if an atom ID is in legacy (v1) format."""
    return LEGACY_ATOM_PATTERN.match(atom_id) is not None


def is_new_format(atom_id: str) -> bool:
    """Check if an atom ID is in new (v2) format."""
    return NEW_ATOM_PATTERN.match(atom_id) is not None


def extract_file_uid(atom_id: str) -> str:
    """Extract the file UID from an atom ID."""
    return parse_atom_id(atom_id).file_uid


def extract_rev_id(atom_id: str) -> str:
    """Extract the revision ID from an atom ID."""
    return parse_atom_id(atom_id).rev_id


def extract_line_no(atom_id: str) -> int:
    """Extract the line number from an atom ID."""
    return parse_atom_id(atom_id).line_no
