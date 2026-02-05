"""Compatibility layer for legacy atom ID formats.

This module provides utilities for parsing and upgrading atom IDs between
the legacy format (v1) and the new format (v2) with revision tracking.

Legacy format (v1): ATOM-{file_id}-L{line_no:04d}
New format (v2):    ATOM-{file_uid}-{rev_id}-L{line_no:04d}

When parsing legacy IDs, rev_id defaults to R0001.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# Pattern for new format: ATOM-F####-R####-L####
NEW_ATOM_PATTERN = re.compile(
    r"^ATOM-(?P<file_uid>F\d{4})-(?P<rev_id>R\d{4})-L(?P<line_no>\d{4})$"
)

# Pattern for legacy format: ATOM-F####-L####
LEGACY_ATOM_PATTERN = re.compile(
    r"^ATOM-(?P<file_id>F\d{4})-L(?P<line_no>\d{4})$"
)

# Default revision ID for legacy atoms
DEFAULT_LEGACY_REV_ID = "R0001"


@dataclass
class ParsedAtomId:
    """Parsed components of an atom ID."""

    file_uid: str
    rev_id: str
    line_no: int
    format: Literal["v1", "v2"]

    @property
    def atom_id(self) -> str:
        """Reconstruct the atom ID in v2 format."""
        return f"ATOM-{self.file_uid}-{self.rev_id}-L{self.line_no:04d}"


def parse_atom_id(atom_id: str) -> ParsedAtomId:
    """Parse atom ID, supporting both legacy and new formats.

    Args:
        atom_id: Atom identifier string

    Returns:
        ParsedAtomId with extracted components

    Raises:
        ValueError: If atom_id does not match any known format
    """
    # Try new format first
    new_match = NEW_ATOM_PATTERN.fullmatch(atom_id)
    if new_match:
        return ParsedAtomId(
            file_uid=new_match.group("file_uid"),
            rev_id=new_match.group("rev_id"),
            line_no=int(new_match.group("line_no")),
            format="v2",
        )

    # Fall back to legacy format
    legacy_match = LEGACY_ATOM_PATTERN.fullmatch(atom_id)
    if legacy_match:
        return ParsedAtomId(
            file_uid=legacy_match.group("file_id"),  # file_id -> file_uid
            rev_id=DEFAULT_LEGACY_REV_ID,  # Default revision for legacy
            line_no=int(legacy_match.group("line_no")),
            format="v1",
        )

    raise ValueError(f"Invalid atom ID format: {atom_id}")


def upgrade_atom_id(legacy_id: str) -> str:
    """Convert legacy atom ID to new format.

    Args:
        legacy_id: Atom ID (v1 or v2 format)

    Returns:
        Atom ID in v2 format

    Raises:
        ValueError: If legacy_id does not match any known format
    """
    parsed = parse_atom_id(legacy_id)
    if parsed.format == "v2":
        return legacy_id
    return parsed.atom_id


def is_legacy_format(atom_id: str) -> bool:
    """Check if atom ID is in legacy (v1) format.

    Args:
        atom_id: Atom identifier string

    Returns:
        True if legacy format, False otherwise
    """
    return LEGACY_ATOM_PATTERN.fullmatch(atom_id) is not None


def is_new_format(atom_id: str) -> bool:
    """Check if atom ID is in new (v2) format.

    Args:
        atom_id: Atom identifier string

    Returns:
        True if new format, False otherwise
    """
    return NEW_ATOM_PATTERN.fullmatch(atom_id) is not None


def extract_file_uid(atom_id: str) -> str:
    """Extract file UID from an atom ID.

    Args:
        atom_id: Atom identifier string

    Returns:
        File UID (F####)

    Raises:
        ValueError: If atom_id does not match any known format
    """
    return parse_atom_id(atom_id).file_uid


def extract_rev_id(atom_id: str) -> str:
    """Extract revision ID from an atom ID.

    For legacy format atoms, returns the default revision ID (R0001).

    Args:
        atom_id: Atom identifier string

    Returns:
        Revision ID (R####)

    Raises:
        ValueError: If atom_id does not match any known format
    """
    return parse_atom_id(atom_id).rev_id


def extract_line_no(atom_id: str) -> int:
    """Extract line number from an atom ID.

    Args:
        atom_id: Atom identifier string

    Returns:
        Line number (1-based)

    Raises:
        ValueError: If atom_id does not match any known format
    """
    return parse_atom_id(atom_id).line_no
