"""Schemas for LLM-generated section spans (Phase 1 sectionization)."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class SectionSpan(BaseModel):
    """Represents a contiguous line range belonging to a logical section."""

    section_id: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    label: str

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
        """Validate sections cover exactly all lines with no gaps or overlaps."""
        if self.total_lines == 0:
            if self.sections:
                raise ValueError("sections must be empty when total_lines is 0")
            return self

        if not self.sections:
            raise ValueError("sections must not be empty")

        expected_start = 1
        for ordinal, section in enumerate(self.sections, start=1):
            expected_section_id = f"SEC-{self.file_id}-{ordinal:04d}"
            if section.section_id != expected_section_id:
                raise ValueError(
                    f"section_id must match {expected_section_id} for ordinal {ordinal}"
                )
            if section.start_line != expected_start:
                raise ValueError(
                    "sections must cover all lines exactly once with no gaps or overlaps"
                )
            expected_start = section.end_line + 1

        return self
