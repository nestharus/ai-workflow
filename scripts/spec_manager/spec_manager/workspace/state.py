"""
Workspace state management for spec processing.

The workspace maintains state across the 4 phases:
1. STAGING: Validate and legalize
2. PLANNING: Decompose into batches
3. MERGING: Apply batches
4. VERIFICATION: Confirm correctness
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class PhaseStatus(Enum):
    """Status of a workflow phase."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Phase(Enum):
    """Workflow phases."""

    STAGING = "staging"
    PLANNING = "planning"
    MERGING = "merging"
    VERIFICATION = "verification"


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
class WorkspaceState:
    """
    Persistent state for spec workspace processing.

    Tracks:
    - Current phase and status
    - Phase results and issues
    - Input/output files
    - Processing history
    """

    spec_folder: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    current_phase: Phase = Phase.STAGING
    phases: dict[str, PhaseResult] = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)  # Input files to process
    processed: list[str] = field(default_factory=list)  # Files that have been processed
    ambiguous_inputs: list[str] = field(default_factory=list)  # Files with ambiguous ordering
    history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Initialize phase results
        for phase in Phase:
            if phase.value not in self.phases:
                self.phases[phase.value] = PhaseResult(
                    phase=phase, status=PhaseStatus.NOT_STARTED
                )

    def start_phase(self, phase: Phase) -> None:
        """Mark a phase as started."""
        self.current_phase = phase
        self.phases[phase.value].status = PhaseStatus.IN_PROGRESS
        self.phases[phase.value].started_at = datetime.now().isoformat()
        self._log_event("phase_started", {"phase": phase.value})

    def complete_phase(
        self, phase: Phase, outputs: dict[str, Any] | None = None
    ) -> None:
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
        phase_order = [Phase.STAGING, Phase.PLANNING, Phase.MERGING, Phase.VERIFICATION]

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
        return all(
            self.phases[phase.value].status == PhaseStatus.COMPLETED for phase in Phase
        )

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
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkspaceState:
        """Create state from dictionary."""
        state = cls(
            spec_folder=data["spec_folder"],
            created_at=data.get("created_at", datetime.now().isoformat()),
            current_phase=Phase(data.get("current_phase", "staging")),
            inputs=data.get("inputs", []),
            processed=data.get("processed", []),
            ambiguous_inputs=data.get("ambiguous_inputs", []),
            history=data.get("history", []),
        )

        # Restore phase results
        for name, phase_data in data.get("phases", {}).items():
            state.phases[name] = PhaseResult(
                phase=Phase(phase_data["phase"]),
                status=PhaseStatus(phase_data["status"]),
                started_at=phase_data.get("started_at"),
                completed_at=phase_data.get("completed_at"),
                error=phase_data.get("error"),
                outputs=phase_data.get("outputs", {}),
                issues=phase_data.get("issues", []),
            )

        return state

    def save(self, path: Path) -> None:
        """Save state to file."""
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> WorkspaceState:
        """Load state from file."""
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)
