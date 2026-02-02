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
        """Validate structural requirements for sections."""
        if self.total_lines == 0:
            if self.sections:
                raise ValueError("sections must be empty when total_lines is 0")
            return self

        if not self.sections:
            raise ValueError("sections must not be empty")

        return self
