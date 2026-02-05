"""Schemas for LLM-generated section spans (Phase 1 sectionization).

Per DS-STRUCT-0001, sections track their atom_ids directly for 100% atom accounting.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class SectionSpan(BaseModel):
    """Represents a contiguous line range belonging to a logical section.

    Per DS-STRUCT-0001, sections now track file_uid, rev_id, and atom_ids
    for full provenance and atom accounting.

    Attributes:
        section_id: Unique identifier for this section
        file_uid: File UID (F####) - optional for backward compatibility
        rev_id: Revision ID (R####) - optional for backward compatibility
        start_line: Start line number (1-based)
        end_line: End line number (1-based, inclusive)
        label: Human-readable section label
        atom_ids: List of atom IDs contained in this section
        span_type: Type of span (BLOCK, LIST, TABLE, etc.)
        confidence: Confidence score for section boundary detection (0.0-1.0)
    """

    section_id: str
    file_uid: str | None = None
    rev_id: str | None = None
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    label: str
    atom_ids: list[str] = Field(default_factory=list)
    span_type: str | None = None
    confidence: float = 1.0

    @model_validator(mode="after")
    def validate_line_range(self) -> SectionSpan:
        """Ensure end_line is not less than start_line."""
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        return self


class FileSections(BaseModel):
    """Container for all section spans within a file with coverage validation."""

    file_id: str
    sections: list[SectionSpan]
    total_lines: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_section_coverage(self) -> FileSections:
        """Validate structural requirements for sections."""
        if self.total_lines == 0:
            if self.sections:
                raise ValueError("sections must be empty when total_lines is 0")
            return self

        if not self.sections:
            raise ValueError("sections must not be empty")

        return self
