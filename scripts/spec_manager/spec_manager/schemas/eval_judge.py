"""Pydantic schemas for eval detail-capture judge output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ItemMatch(BaseModel):
    """Match decision for a single expected item."""

    expected_index: int
    actual_index: int | None = None
    matched: bool
    rationale: str


class EvalJudgeOutput(BaseModel):
    """Structured output from the eval detail-capture judge."""

    matches: list[ItemMatch]
    unmatched_actual: list[int] = Field(default_factory=list)
    summary: str = ""
