"""Pydantic schemas for spec fidelity judge output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RequirementCoverage(BaseModel):
    """Coverage status for a single requirement."""

    requirement: str
    status: str = "missing"  # implemented, partial, missing
    evidence: str = ""


class SpecFidelityOutput(BaseModel):
    """Structured output from the spec fidelity judge."""

    coverage_estimate: float = 0.0
    requirements: list[RequirementCoverage] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    hallucinated_features: list[str] = Field(default_factory=list)
