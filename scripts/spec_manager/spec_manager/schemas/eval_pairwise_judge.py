"""Pydantic schemas for pairwise comparison judge output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PairwiseOutput(BaseModel):
    """Structured output from the pairwise comparison judge."""

    winner: str = "TIE"  # A, B, TIE
    scores: dict[str, dict[str, int]] = Field(default_factory=dict)  # {"A": {...}, "B": {...}}
    key_differences: list[str] = Field(default_factory=list)
    risks: list[dict] = Field(default_factory=list)
