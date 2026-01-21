"""Workspace state management for spec processing.

The workspace maintains state across the 4 phases:
1. CLEANING: Validate and legalize
2. DISCOVERY: Decompose into batches
3. REVIEW: Apply batches
4. FINALIZATION: Confirm correctness
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from spec_manager.core.data_structures import (
    ComplianceMetrics,
    ConflictBundle,
    StrategyRecord,
)


class PhaseStatus(Enum):
    """Status of a workflow phase."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Phase(Enum):
    """Workflow phases."""

    CLEANING = "cleaning"
    DISCOVERY = "discovery"
    REVIEW = "review"
    FINALIZATION = "finalization"


@dataclass
class PhaseResult:
    """Result of a phase execution."""

    phase: Phase
    status: PhaseStatus
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CoverageSnapshot:
    """Snapshot of coverage tracking metrics.

    Tracks the number of units processed and their status breakdown
    at a point in time.

    Attributes:
        total_units: Total number of tracked units.
        mapped_units: Units successfully mapped.
        dropped_units: Units dropped/discarded.
        coverage_percent: Percentage of coverage (0.0-100.0).
        by_status: Count of units by status.
        timestamp: ISO timestamp of snapshot.
    """

    total_units: int
    mapped_units: int
    dropped_units: int
    coverage_percent: float
    by_status: dict[str, int] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "total_units": self.total_units,
            "mapped_units": self.mapped_units,
            "dropped_units": self.dropped_units,
            "coverage_percent": self.coverage_percent,
            "by_status": self.by_status,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoverageSnapshot:
        """Deserialize from dictionary."""
        return cls(
            total_units=data["total_units"],
            mapped_units=data["mapped_units"],
            dropped_units=data["dropped_units"],
            coverage_percent=data["coverage_percent"],
            by_status=data.get("by_status", {}),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
        )


@dataclass
class WorkspaceState:
    """Persistent state for spec workspace processing.

    Tracks:
    - Current phase and status
    - Phase results and issues
    - Input/output files
    - Processing history
    """

    spec_folder: str
    schema_version: str = "2.0"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    current_phase: Phase = Phase.CLEANING
    phases: dict[str, PhaseResult] = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)  # Input files to process
    processed: list[str] = field(default_factory=list)  # Files that have been processed
    ambiguous_inputs: list[str] = field(default_factory=list)  # Files with ambiguous ordering
    history: list[dict[str, Any]] = field(default_factory=list)
    # v2.0 fields
    run_id: str | None = None
    input_hashes: dict[str, str] = field(default_factory=dict)
    metrics: ComplianceMetrics | None = None
    strategies: list[StrategyRecord] = field(default_factory=list)
    conflicts: list[ConflictBundle] = field(default_factory=list)
    coverage: CoverageSnapshot | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Initialize phase results
        for phase in Phase:
            if phase.value not in self.phases:
                self.phases[phase.value] = PhaseResult(phase=phase, status=PhaseStatus.NOT_STARTED)

    def start_phase(self, phase: Phase) -> None:
        """Mark a phase as started."""
        self.current_phase = phase
        self.phases[phase.value].status = PhaseStatus.IN_PROGRESS
        self.phases[phase.value].started_at = datetime.now().isoformat()
        self._log_event("phase_started", {"phase": phase.value})

    def complete_phase(self, phase: Phase, outputs: dict[str, Any] | None = None) -> None:
        """Mark a phase as completed."""
        self.phases[phase.value].status = PhaseStatus.COMPLETED
        self.phases[phase.value].completed_at = datetime.now().isoformat()
        if outputs:
            self.phases[phase.value].outputs = outputs
        self._log_event("phase_completed", {"phase": phase.value})

    def fail_phase(self, phase: Phase, error: str) -> None:
        """Mark a phase as failed."""
        self.phases[phase.value].status = PhaseStatus.FAILED
        self.phases[phase.value].completed_at = datetime.now().isoformat()
        self.phases[phase.value].error = error
        self._log_event("phase_failed", {"phase": phase.value, "error": error})

    def add_issue(self, phase: Phase, issue: dict[str, Any]) -> None:
        """Add an issue to a phase."""
        self.phases[phase.value].issues.append(issue)

    def get_phase_status(self, phase: Phase) -> PhaseStatus:
        """Get the status of a phase."""
        return self.phases[phase.value].status

    def get_phase_issues(self, phase: Phase) -> list[dict[str, Any]]:
        """Get issues for a phase."""
        return self.phases[phase.value].issues

    def get_next_phase(self) -> Phase | None:
        """Get the next phase to execute."""
        phase_order = [Phase.CLEANING, Phase.DISCOVERY, Phase.REVIEW, Phase.FINALIZATION]

        for phase in phase_order:
            status = self.get_phase_status(phase)
            if status == PhaseStatus.NOT_STARTED:
                return phase
            if status == PhaseStatus.IN_PROGRESS:
                return phase  # Resume current
            if status == PhaseStatus.FAILED:
                return phase  # Retry failed

        return None  # All completed

    def is_complete(self) -> bool:
        """Check if all phases are completed."""
        return all(self.phases[phase.value].status == PhaseStatus.COMPLETED for phase in Phase)

    def _log_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Log an event to history."""
        self.history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "event": event_type,
                **data,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert state to dictionary for JSON serialization."""
        return {
            "spec_folder": self.spec_folder,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "current_phase": self.current_phase.value,
            "phases": {
                name: {
                    "phase": result.phase.value,
                    "status": result.status.value,
                    "started_at": result.started_at,
                    "completed_at": result.completed_at,
                    "error": result.error,
                    "outputs": result.outputs,
                    "issues": result.issues,
                }
                for name, result in self.phases.items()
            },
            "inputs": self.inputs,
            "processed": self.processed,
            "ambiguous_inputs": self.ambiguous_inputs,
            "history": self.history,
            # v2.0 fields
            "run_id": self.run_id,
            "input_hashes": self.input_hashes,
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "strategies": [s.to_dict() for s in self.strategies],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "coverage": self.coverage.to_dict() if self.coverage else None,
            "outputs": self.outputs,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkspaceState:
        """Create state from dictionary.

        Args:
            data: Dictionary with state data. Must contain 'spec_folder' key.
                Phase values must be valid v2.0 Phase enum values.

        Returns:
            WorkspaceState instance.

        Raises:
            KeyError: If required keys are missing.
            ValueError: If phase values are invalid.
        """
        # Validate and parse current_phase
        raw_phase = data.get("current_phase", "cleaning")
        try:
            current_phase = Phase(raw_phase)
        except ValueError as e:
            raise ValueError(
                f"Invalid phase value '{raw_phase}'. Valid values are: {[p.value for p in Phase]}"
            ) from e

        state = cls(
            spec_folder=data["spec_folder"],
            schema_version=data.get("schema_version", "2.0"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            current_phase=current_phase,
            inputs=data.get("inputs", []),
            processed=data.get("processed", []),
            ambiguous_inputs=data.get("ambiguous_inputs", []),
            history=data.get("history", []),
            # v2.0 simple fields
            run_id=data.get("run_id"),
            input_hashes=data.get("input_hashes", {}),
            outputs=data.get("outputs", {}),
            errors=data.get("errors", []),
            warnings=data.get("warnings", []),
        )

        # Restore phase results with strict validation
        for name, phase_data in data.get("phases", {}).items():
            raw_result_phase = phase_data["phase"]
            try:
                result_phase = Phase(raw_result_phase)
            except ValueError as e:
                raise ValueError(
                    f"Invalid phase value '{raw_result_phase}' in phase '{name}'. "
                    f"Valid values are: {[p.value for p in Phase]}"
                ) from e

            # Validate status
            raw_status = phase_data["status"]
            try:
                status = PhaseStatus(raw_status)
            except ValueError as e:
                raise ValueError(
                    f"Invalid status value '{raw_status}' in phase '{name}'. "
                    f"Valid values are: {[s.value for s in PhaseStatus]}"
                ) from e

            state.phases[name] = PhaseResult(
                phase=result_phase,
                status=status,
                started_at=phase_data.get("started_at"),
                completed_at=phase_data.get("completed_at"),
                error=phase_data.get("error"),
                outputs=phase_data.get("outputs", {}),
                issues=phase_data.get("issues", []),
            )

        # Restore v2.0 complex fields
        if data.get("metrics"):
            state.metrics = ComplianceMetrics.from_dict(data["metrics"])
        state.strategies = [StrategyRecord.from_dict(s) for s in data.get("strategies", [])]
        state.conflicts = [ConflictBundle.from_dict(c) for c in data.get("conflicts", [])]
        if data.get("coverage"):
            state.coverage = CoverageSnapshot.from_dict(data["coverage"])

        return state

    def save(self, path: Path) -> None:
        """Save state to file."""
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> WorkspaceState:
        """Load state from file."""
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)
