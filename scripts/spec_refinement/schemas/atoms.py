"""Schemas for deterministic line-atom coverage units (Phase 1 atomization)."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator

ATOM_ID_PATTERN = re.compile(r"^ATOM-(?P<file_id>[^-]+)-L(?P<line_no>\d{4})$")


class LineAtom(BaseModel):
    """A single line atom with hash-based identity."""

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
    def validate_atom_id(self) -> LineAtom:
        """Validate atom_id format and consistency with line_no."""
        match = ATOM_ID_PATTERN.fullmatch(self.atom_id)
        if not match:
            raise ValueError("atom_id must match ATOM-{file_id}-L{line_no:04d} pattern")
        if int(match.group("line_no")) != self.line_no:
            raise ValueError("atom_id line number must match line_no")
        return self
