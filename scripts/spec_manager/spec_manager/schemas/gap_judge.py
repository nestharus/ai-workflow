"""Schemas for gap judge structured output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class GapFinding(BaseModel):
    source: str
    missing_content: str
    where_in_spec: str
    severity: Literal["must", "should", "nice-to-have"]


class GapJudgeOutput(BaseModel):
    gaps: list[GapFinding]
    total_gaps: int
    file_id: str
