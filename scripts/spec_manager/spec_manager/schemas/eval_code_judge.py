"""Pydantic schemas for code quality judge output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FileScore(BaseModel):
    """Quality scores for a single file."""

    path: str
    scores: dict[str, int] = Field(default_factory=dict)  # readability, maintainability, error_handling, consistency, contract_clarity (1-5)
    overall: int = 3
    notes: list[str] = Field(default_factory=list)
    risks: list[dict] = Field(default_factory=list)


class CodeJudgeOutput(BaseModel):
    """Structured output from the code quality judge."""

    files: list[FileScore] = Field(default_factory=list)
    overall: int = 3
    systemic_risks: list[dict] = Field(default_factory=list)  # severity + evidence dicts
