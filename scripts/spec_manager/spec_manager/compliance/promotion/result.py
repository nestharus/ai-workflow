"""Result types for promotion gate checks."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class GateStatus(Enum):
    """Status for a gate outcome."""

    PASSED = "passed"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"
    STALE_EVIDENCE = "stale_evidence"


@dataclass
class GateCheckResult:
    """Result of a single gate check.

    Attributes:
        gate_id: Which gate was checked.
        mode: The configured mode (required/advisory).
        status: Rich gate status (pass/fail/ambiguous/stale evidence).
        passed: Compatibility boolean used by older callers/reports.
        score: Numeric score (0.0-1.0) where applicable.
        findings: Detailed findings from the check.
        summary: Human-readable summary.
        duration_ms: How long the check took.
    """

    gate_id: str
    mode: str
    status: GateStatus | str | None = None
    passed: bool | None = None
    score: float = 1.0
    findings: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    duration_ms: float = 0.0

    def __post_init__(self) -> None:
        """Normalize status/passed for backward compatibility."""
        status_explicit = self.status is not None
        passed_explicit = self.passed is not None

        if isinstance(self.status, GateStatus):
            status = self.status
        elif isinstance(self.status, str):
            try:
                status = GateStatus(self.status)
            except ValueError:
                status = GateStatus.PASSED
        elif self.passed is False:
            status = GateStatus.FAILED
        else:
            status = GateStatus.PASSED
        self.status = status

        if not passed_explicit or status_explicit:
            self.passed = self._status_counts_as_pass(status=self.status, mode=self.mode)
        else:
            self.passed = bool(self.passed)

    @staticmethod
    def _status_counts_as_pass(status: GateStatus, mode: str) -> bool:
        """Map rich status to compatibility boolean for report plumbing."""
        return status == GateStatus.PASSED or (
            status == GateStatus.AMBIGUOUS and mode == "advisory"
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "gate_id": self.gate_id,
            "passed": self.passed,
            "mode": self.mode,
            "status": self.status.value,
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
