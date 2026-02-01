"""Schema for run-level gaps report (compliance gate failure)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RunLevelGapsReport:
    """Run-level gaps report when compliance gate fails."""

    run_id: str | None
    final_pass: int
    compliance_score: float
    compliance_threshold: float
    gate_mode: str
    status: str
    blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    evidence_summary: dict[str, Any]
    gaps_summary: dict[str, Any]
    convergence_failure: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON."""
        return {
            "run_id": self.run_id,
            "final_pass": self.final_pass,
            "compliance_score": self.compliance_score,
            "compliance_threshold": self.compliance_threshold,
            "gate_mode": self.gate_mode,
            "status": self.status,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "evidence_summary": self.evidence_summary,
            "gaps_summary": self.gaps_summary,
            "convergence_failure": self.convergence_failure,
        }
