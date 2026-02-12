"""Pydantic schemas for architecture quality judge output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ArchRisk(BaseModel):
    """A single architecture risk finding."""

    severity: str  # CRITICAL, MAJOR, MINOR
    component_id: str = ""
    evidence: str = ""


class ArchJudgeOutput(BaseModel):
    """Structured output from the architecture quality judge."""

    scores: dict[str, int] = Field(default_factory=dict)  # cohesion, coupling, completeness, consistency, clarity, extensibility (1-5)
    overall: int = 3
    strengths: list[str] = Field(default_factory=list)
    risks: list[ArchRisk] = Field(default_factory=list)
    tradeoffs_noted: list[str] = Field(default_factory=list)
