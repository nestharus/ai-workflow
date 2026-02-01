"""Schemas for QA judge structured output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QaCriterionResult(BaseModel):
    """Result for a single QA criterion check."""

    criterion: str
    passed: bool
    evidence: str | None = None


class QaJudgeOutput(BaseModel):
    """Structured evaluation of a single agent-step QA case."""

    case_id: str
    agent_name: str

    passed: bool
    score: float = Field(ge=0.0, le=100.0)
    summary: str

    criteria: list[QaCriterionResult] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)

    likely_root_causes: list[str] = Field(default_factory=list)
    suggested_fixes: list[str] = Field(default_factory=list)

    # Optional: observations from stderr / runner traces provided by the harness.
    trace_findings: list[str] = Field(default_factory=list)
