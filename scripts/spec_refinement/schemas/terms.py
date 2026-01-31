"""Schemas for LLM-extracted domain terms (Phase 1 term indexing)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SectionTerms(BaseModel):
    section_id: str
    terms: list[str]
    confidence: float = Field(ge=0.0, le=1.0)


class FileTerms(BaseModel):
    file_id: str
    section_terms: list[SectionTerms]
    global_terms: list[str]
