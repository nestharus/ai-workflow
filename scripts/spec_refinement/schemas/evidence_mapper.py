"""Schemas for evidence mapper structured output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EvidenceMapperOutput(BaseModel):
    file_id: str
    relevant_sections: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    priority: float | None = None
    priority_rationale: str | None = None
