"""Schemas for library labeler structured output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LibraryLabel(BaseModel):
    label: str
    sections: list[str]
    confidence: float = Field(ge=0.0, le=1.0)


class LibraryLabelerOutput(BaseModel):
    file_id: str
    candidate_labels: list[LibraryLabel]
    uncertain_labels: list[str]
