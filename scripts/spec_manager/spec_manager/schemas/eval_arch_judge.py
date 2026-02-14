"""Pydantic schemas for architecture quality judge output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ArchRisk(BaseModel):
    """A single architecture risk finding."""

    model_config = ConfigDict(extra="forbid")

    severity: Literal["CRITICAL", "MAJOR", "MINOR"]
    component_id: str = ""
    evidence: str = ""


class ArchDimensionScores(BaseModel):
    """Required architecture judge dimensions (1-5 each)."""

    model_config = ConfigDict(extra="forbid")

    cohesion: int = Field(ge=1, le=5)
    coupling: int = Field(ge=1, le=5)
    completeness: int = Field(ge=1, le=5)
    consistency: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    extensibility: int = Field(ge=1, le=5)


class ArchJudgeOutput(BaseModel):
    """Structured output from the architecture quality judge."""

    model_config = ConfigDict(extra="forbid")

    scores: ArchDimensionScores
    overall: int = Field(ge=1, le=5)
    strengths: list[str] = Field(default_factory=list)
    risks: list[ArchRisk] = Field(default_factory=list)
    tradeoffs_noted: list[str] = Field(default_factory=list)
    non_prescriptive_note: str = ""
