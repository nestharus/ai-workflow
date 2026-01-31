"""Schemas for library labeler structured output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LibraryLabel(BaseModel):
    """A library label assignment with confidence information."""

    label: str
    sections: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


class LibraryLabelUncertain(BaseModel):
    """An uncertain library label assignment requiring further review."""

    label: str
    rationale: str


class LibraryLabelerOutput(BaseModel):
    """The output of the library labeler for a single file."""

    file_id: str
    candidate_labels: list[LibraryLabel]
    uncertain_labels: list[LibraryLabelUncertain]
