"""Schemas for deterministic line-atom coverage units (Phase 1 atomization).

Atom ID Format (v2): ATOM-{file_uid}-{rev_id}-L{line_no:04d}
Legacy Format (v1):  ATOM-{file_id}-L{line_no:04d}

The v2 format includes revision tracking for cross-revision atom matching
via stable fingerprints (DS-EVID-0001).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator

# New pattern: ATOM-{file_uid}-{rev_id}-L{line:04d}
ATOM_ID_PATTERN = re.compile(r"^ATOM-(?P<file_uid>F\d{4})-(?P<rev_id>R\d{4})-L(?P<line_no>\d{4})$")

# Legacy pattern for backward compatibility: ATOM-{file_id}-L{line:04d}
LEGACY_ATOM_ID_PATTERN = re.compile(r"^ATOM-(?P<file_id>F\d{4})-L(?P<line_no>\d{4})$")


class LineAtom(BaseModel):
    """A single line atom with hash-based identity (DS-EVID-0001).

    Attributes:
        atom_id: Unique identifier in format ATOM-{file_uid}-{rev_id}-L{line_no:04d}
        atom_fingerprint: Content-based fingerprint for cross-revision matching (64 hex chars)
        file_uid: File UID (F####)
        rev_id: Revision ID (R####)
        line_no: 1-based line number
        sequence_index: 0-based position in file
        section_id: Section containing this atom
        sha256: SHA-256 hash of line content (64 hex chars)
        text: Raw line text
    """

    atom_id: str
    atom_fingerprint: str = Field(min_length=64, max_length=64)
    file_uid: str
    rev_id: str
    line_no: int = Field(ge=1)
    sequence_index: int = Field(ge=0)
    section_id: str
    sha256: str = Field(min_length=64, max_length=64)
    text: str

    @field_validator("sha256", "atom_fingerprint")
    @classmethod
    def validate_hex_hash(cls, value: str) -> str:
        """Validate SHA256/fingerprint format."""
        if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError("hash must be 64 hex characters")
        return value

    @field_validator("file_uid")
    @classmethod
    def validate_file_uid(cls, value: str) -> str:
        """Validate file_uid format (F####)."""
        if not re.fullmatch(r"F\d{4}", value):
            raise ValueError("file_uid must match F#### pattern")
        return value

    @field_validator("rev_id")
    @classmethod
    def validate_rev_id(cls, value: str) -> str:
        """Validate rev_id format (R####)."""
        if not re.fullmatch(r"R\d{4}", value):
            raise ValueError("rev_id must match R#### pattern")
        return value

    @model_validator(mode="after")
    def validate_atom_id(self) -> LineAtom:
        """Validate atom_id format and consistency with other fields."""
        match = ATOM_ID_PATTERN.fullmatch(self.atom_id)
        if not match:
            raise ValueError("atom_id must match ATOM-{file_uid}-{rev_id}-L{line_no:04d} pattern")
        if match.group("file_uid") != self.file_uid:
            raise ValueError("atom_id file_uid must match file_uid field")
        if match.group("rev_id") != self.rev_id:
            raise ValueError("atom_id rev_id must match rev_id field")
        if int(match.group("line_no")) != self.line_no:
            raise ValueError("atom_id line number must match line_no")
        return self

    @model_validator(mode="after")
    def validate_sequence_index(self) -> LineAtom:
        """Validate sequence_index is consistent with line_no."""
        if self.sequence_index != self.line_no - 1:
            raise ValueError("sequence_index must be line_no - 1")
        return self


class LegacyLineAtom(BaseModel):
    """Legacy line atom format (v1) for backward compatibility.

    This model supports reading atoms created before the revision tracking
    update. Use LineAtom for new atoms.
    """

    atom_id: str
    line_no: int = Field(ge=1)
    section_id: str
    sha256: str = Field(min_length=64, max_length=64)
    text: str

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        """Validate SHA256 format."""
        if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError("sha256 must be 64 hex characters")
        return value

    @model_validator(mode="after")
    def validate_atom_id(self) -> LegacyLineAtom:
        """Validate atom_id format and consistency with line_no."""
        match = LEGACY_ATOM_ID_PATTERN.fullmatch(self.atom_id)
        if not match:
            raise ValueError("atom_id must match ATOM-{file_id}-L{line_no:04d} pattern")
        if int(match.group("line_no")) != self.line_no:
            raise ValueError("atom_id line number must match line_no")
        return self


def is_legacy_atom(atom_data: dict[str, object]) -> bool:
    """Check if atom data is in legacy format.

    Args:
        atom_data: Dictionary of atom fields

    Returns:
        True if legacy format (missing file_uid, rev_id, atom_fingerprint)
    """
    return "atom_fingerprint" not in atom_data or "file_uid" not in atom_data
