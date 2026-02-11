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
