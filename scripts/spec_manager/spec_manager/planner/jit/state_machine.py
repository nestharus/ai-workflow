from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class PlanPhase(Enum):
    INIT = "init"
    DISCOVER = "discover"
    INTEGRATION_ANALYSIS = "integration_analysis"
    GAP_UNDERSTANDING = "gap_understanding"
    RESEARCH = "research"
    DESIGN = "design"
    VALIDATE = "validate"
    COMPLETE = "complete"
    BLOCKED = "blocked"


class PlanStatus(Enum):
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class PlannerStateMachine:
    """Lightweight state tracker for planning micro-phases.

    Used within a single ``planner.plan()`` call to drive phase
    transitions and record a history trace for inspection.  Not
    persisted across process boundaries.
    """

    phase: PlanPhase = PlanPhase.INIT
    status: PlanStatus = PlanStatus.RUNNING
    history: list[dict[str, Any]] = field(default_factory=list)

    # ---- transitions ----

    def advance(self, to_phase: PlanPhase) -> None:
        """Advance to *to_phase*, recording the transition in history."""
        self._record(from_phase=self.phase, to_phase=to_phase)
        self.phase = to_phase
        self.status = PlanStatus.RUNNING

    def block(self, reason: str) -> None:
        """Move to BLOCKED phase with *reason*."""
        self._record(
            from_phase=self.phase,
            to_phase=PlanPhase.BLOCKED,
            reason=reason,
        )
        self.phase = PlanPhase.BLOCKED
        self.status = PlanStatus.PAUSED

    def complete(self) -> None:
        """Mark the state machine as complete."""
        self._record(from_phase=self.phase, to_phase=PlanPhase.COMPLETE)
        self.phase = PlanPhase.COMPLETE
        self.status = PlanStatus.COMPLETED

    def wait_for_input(self, prompt: str = "") -> None:
        """Pause execution and wait for user input."""
        self._record(
            from_phase=self.phase,
            to_phase=self.phase,
            status=PlanStatus.WAITING_INPUT,
            prompt=str(prompt or ""),
        )
        self.status = PlanStatus.WAITING_INPUT

    def resume(self) -> None:
        """Resume execution from a paused state."""
        self._record(
            from_phase=self.phase,
            to_phase=self.phase,
            status=PlanStatus.RUNNING,
        )
        self.status = PlanStatus.RUNNING

    def error(self, msg: str) -> None:
        """Mark as errored with *msg*."""
        self._record(
            from_phase=self.phase,
            to_phase=self.phase,
            error=msg,
        )
        self.status = PlanStatus.ERROR

    # ---- serialisation ----

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "status": self.status.value,
            "history": list(self.history),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlannerStateMachine:
        phase_raw = str(payload.get("phase", PlanPhase.INIT.value) or PlanPhase.INIT.value)
        status_raw = str(
            payload.get("status", PlanStatus.RUNNING.value) or PlanStatus.RUNNING.value
        )
        phase = PlanPhase.INIT
        status = PlanStatus.RUNNING
        for candidate in PlanPhase:
            if candidate.value == phase_raw:
                phase = candidate
                break
        for candidate in PlanStatus:
            if candidate.value == status_raw:
                status = candidate
                break
        history_raw = payload.get("history", [])
        history = (
            [row for row in history_raw if isinstance(row, dict)]
            if isinstance(history_raw, list)
            else []
        )
        return cls(phase=phase, status=status, history=history)

    # ---- internals ----

    def _record(self, **kwargs: Any) -> None:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
        }
        for key, val in kwargs.items():
            if isinstance(val, Enum):
                entry[key] = val.value
            else:
                entry[key] = val
        self.history.append(entry)
