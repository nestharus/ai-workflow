from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class PlanPhase(Enum):
    INIT = "init"
    DISCOVER = "discover"
    INTEGRATION_ANALYSIS = "integration_analysis"
    DECIDE = "decide"
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
            "history": deepcopy(self.history),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlannerStateMachine:
        if not isinstance(payload, dict):
            raise TypeError("PlannerStateMachine payload must be a dict")

        phase = cls._parse_phase(payload)
        status = cls._parse_status(payload)
        history = cls._parse_history(payload)
        return cls(phase=phase, status=status, history=history)

    # ---- internals ----

    @staticmethod
    def _parse_phase(payload: dict[str, Any]) -> PlanPhase:
        if "phase" not in payload:
            return PlanPhase.INIT
        phase_raw = payload.get("phase")
        if not isinstance(phase_raw, str) or not phase_raw.strip():
            raise ValueError(f"Invalid planner state phase: {phase_raw!r}")
        try:
            return PlanPhase(phase_raw.strip())
        except ValueError as exc:
            allowed = ", ".join(candidate.value for candidate in PlanPhase)
            raise ValueError(
                f"Unknown planner state phase {phase_raw!r}; expected one of: {allowed}"
            ) from exc

    @staticmethod
    def _parse_status(payload: dict[str, Any]) -> PlanStatus:
        if "status" not in payload:
            return PlanStatus.RUNNING
        status_raw = payload.get("status")
        if not isinstance(status_raw, str) or not status_raw.strip():
            raise ValueError(f"Invalid planner state status: {status_raw!r}")
        try:
            return PlanStatus(status_raw.strip())
        except ValueError as exc:
            allowed = ", ".join(candidate.value for candidate in PlanStatus)
            raise ValueError(
                f"Unknown planner state status {status_raw!r}; expected one of: {allowed}"
            ) from exc

    @classmethod
    def _parse_history(cls, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if "history" not in payload:
            return []
        history_raw = payload.get("history")
        if not isinstance(history_raw, list):
            return [
                cls._history_deserialization_error(
                    code="history_not_list",
                    raw_payload=history_raw,
                )
            ]

        history: list[dict[str, Any]] = []
        for index, entry in enumerate(history_raw):
            if isinstance(entry, dict):
                history.append(deepcopy(entry))
                continue
            history.append(
                cls._history_deserialization_error(
                    code="history_entry_not_dict",
                    raw_payload=entry,
                    index=index,
                )
            )
        return history

    @staticmethod
    def _history_deserialization_error(
        *,
        code: str,
        raw_payload: Any,
        index: int | None = None,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "deserialization_error": code,
            "raw_payload": deepcopy(raw_payload),
        }
        if index is not None:
            entry["history_index"] = index
        return entry

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
