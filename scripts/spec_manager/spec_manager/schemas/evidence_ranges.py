"""Schemas for evidence ranges bridging atoms to sections (DS-EVID-0003).

Evidence ranges provide the canonical bridge between spans/sections and atoms,
enabling 100% atom accounting per INV-ACC-0101.

Evidence ID Format: EVID-{file_uid}-{rev_id}-L{start}-L{end}
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, model_validator

EVIDENCE_ID_PATTERN = re.compile(
    r"^EVID-(?P<file_uid>F\d{4})-(?P<rev_id>R\d{4})-L(?P<start>\d+)-L(?P<end>\d+)$"
)

# Bracketed citation format for human-readable documents (CON-0021)
EVID_CITATION_PATTERN = re.compile(r"\[EVID-F\d{4}-R\d{4}-L\d+-L\d+\]")


class EvidenceRange(BaseModel):
    """A contiguous range of atoms bridging spans to sections (DS-EVID-0003).

    Attributes:
        evidence_id: Unique identifier in format EVID-{file_uid}-{rev_id}-L{start}-L{end}
        file_uid: File UID (F####)
        rev_id: Revision ID (R####)
        start_line: Start line number (1-based)
        end_line: End line number (1-based, inclusive)
        atom_ids: List of atom IDs in this range
        section_id: Associated section ID (optional)
        label: Human-readable label (optional)
        content_sha256: SHA-256 hash of combined content (optional)
        tags: Set of tags for categorization
    """

    evidence_id: str
    file_uid: str
    rev_id: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    atom_ids: list[str]
    section_id: str | None = None
    label: str | None = None
    content_sha256: str | None = None
    tags: set[str] = Field(default_factory=set)

    @model_validator(mode="after")
    def validate_evidence_id_format(self) -> "EvidenceRange":
        """Validate evidence_id format and consistency with fields."""
        match = EVIDENCE_ID_PATTERN.fullmatch(self.evidence_id)
        if not match:
            raise ValueError(
                "evidence_id must match EVID-{file_uid}-{rev_id}-L{start}-L{end}"
            )
        if match.group("file_uid") != self.file_uid:
            raise ValueError("evidence_id file_uid must match file_uid field")
        if match.group("rev_id") != self.rev_id:
            raise ValueError("evidence_id rev_id must match rev_id field")
        return self

    @model_validator(mode="after")
    def validate_line_range(self) -> "EvidenceRange":
        """Ensure end_line >= start_line."""
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        return self

    @model_validator(mode="after")
    def validate_atom_ids_count(self) -> "EvidenceRange":
        """Ensure atom_ids count matches line range."""
        expected = self.end_line - self.start_line + 1
        if len(self.atom_ids) != expected:
            raise ValueError(
                f"atom_ids count ({len(self.atom_ids)}) must match line range ({expected})"
            )
        return self


class EvidenceRangesArtifact(BaseModel):
    """Container for evidence ranges per file (output artifact).

    Attributes:
        schema_version: Schema version string
        file_uid: File UID (F####)
        rev_id: Revision ID (R####)
        ranges: List of evidence ranges
        uncovered_atoms: List of atom IDs not covered by any range
    """

    schema_version: str = "1.0"
    file_uid: str
    rev_id: str
    ranges: list[EvidenceRange]
    uncovered_atoms: list[str] = Field(default_factory=list)
