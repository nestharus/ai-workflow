"""Result types for promotion gate checks."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class GateCheckResult:
    """Result of a single gate check.

    Attributes:
        gate_id: Which gate was checked.
        passed: Whether the gate passed.
        mode: The configured mode (required/advisory).
        score: Numeric score (0.0-1.0) where applicable.
        findings: Detailed findings from the check.
        summary: Human-readable summary.
        duration_ms: How long the check took.
    """

    gate_id: str
    passed: bool
    mode: str
    score: float = 1.0
    findings: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "gate_id": self.gate_id,
            "passed": self.passed,
            "mode": self.mode,
            "score": self.score,
            "findings": self.findings,
            "summary": self.summary,
            "duration_ms": self.duration_ms,
        }


@dataclass
class PromotionReport:
    """Aggregate report from all promotion gate checks.

    Attributes:
        passed: Whether all required gates passed.
        gate_results: Results for each gate check.
        blockers: Gate checks that failed in REQUIRED mode.
        warnings: Gate checks that failed in ADVISORY mode.
        total_duration_ms: Total time for all checks.
    """

    passed: bool
    gate_results: list[GateCheckResult] = field(default_factory=list)
    blockers: list[GateCheckResult] = field(default_factory=list)
    warnings: list[GateCheckResult] = field(default_factory=list)
    total_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON output."""
        return {
            "passed": self.passed,
            "gate_results": [r.to_dict() for r in self.gate_results],
            "blockers": [r.to_dict() for r in self.blockers],
            "warnings": [r.to_dict() for r in self.warnings],
            "total_duration_ms": self.total_duration_ms,
        }

    def save(self, path: Path) -> None:
        """Write promotion report to disk as JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2),
            encoding="utf-8",
        )
