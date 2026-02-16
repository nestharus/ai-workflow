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
        evidence_refs: Evidence paths/IDs that support this gate result.
        summary: Human-readable summary.
        duration_ms: How long the check took.
    """

    gate_id: str
    mode: str
    status: GateStatus | str | None = None
    passed: bool | None = None
    score: float = 1.0
    findings: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
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
                status = GateStatus.AMBIGUOUS
        elif self.passed is False:
            status = GateStatus.FAILED
        else:
            status = GateStatus.PASSED
        self.status = status

        if not passed_explicit or status_explicit:
            self.passed = self._status_counts_as_pass(status=self.status, mode=self.mode)
        else:
            self.passed = bool(self.passed)

        if not self.evidence_refs:
            self.evidence_refs = self._extract_evidence_refs(self.findings)
        else:
            self.evidence_refs = [
                str(ref).strip() for ref in self.evidence_refs if str(ref).strip()
            ]

    @staticmethod
    def _extract_evidence_refs(findings: list[dict[str, Any]]) -> list[str]:
        refs: list[str] = []
        if not isinstance(findings, list):
            return refs
        for finding in findings:
            if not isinstance(finding, dict):
                continue

            raw_refs = finding.get("evidence_refs")
            if isinstance(raw_refs, str) and raw_refs.strip():
                refs.append(raw_refs.strip())
            elif isinstance(raw_refs, list):
                refs.extend(str(ref).strip() for ref in raw_refs if str(ref).strip())

            for key in (
                "raw_excerpt_path",
                "excerpt_path",
                "artifact_path",
                "path",
                "file",
                "file_path",
            ):
                value = finding.get(key)
                if isinstance(value, str) and value.strip():
                    refs.append(value.strip())

        return list(dict.fromkeys(refs))

    @staticmethod
    def _status_counts_as_pass(status: GateStatus, mode: str) -> bool:
        """Map rich status to compatibility boolean for report plumbing."""
        del mode
        return status == GateStatus.PASSED

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "gate_id": self.gate_id,
            "passed": self.passed,
            "mode": self.mode,
            "status": self.status.value,
            "score": self.score,
            "findings": self.findings,
            "evidence_refs": self.evidence_refs,
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
