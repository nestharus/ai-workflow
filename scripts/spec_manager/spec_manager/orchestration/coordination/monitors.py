"""JIT monitor specifications and registry.

A MonitorSpec describes a condition to watch for, plus what to do when
the condition becomes true (fire a wake event).  The MonitorRegistry
stores specs on disk under ``coordination/monitors/`` and provides
lookup helpers for the executor and planner.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

# ------------------------------------------------------------------
# Condition types
# ------------------------------------------------------------------


@dataclass
class MonitorCondition:
    """Base for all monitor condition types."""

    type: str = ""


@dataclass
class GitSymbolExistsCondition(MonitorCondition):
    """True when a symbol appears in files matching a glob at a git ref."""

    type: str = "git_symbol_exists"
    ref: str = ""
    file_glob: str = ""
    symbol_fqn: str = ""
    signature_regex: str = ""


@dataclass
class WorkItemDoneCondition(MonitorCondition):
    """True when a work item reaches the required status."""

    type: str = "work_item_done"
    work_item_id: str = ""
    required_status: str = "MERGED"


@dataclass
class ConstraintPresentCondition(MonitorCondition):
    """True when a constraint file exists on disk."""

    type: str = "constraint_present"
    constraint_key: str = ""
    constraint_dir: str = "analysis/constraints"
    constraint_id: str = ""
    slice_id: str = ""


@dataclass
class SliceMergedCondition(MonitorCondition):
    """True when a provider slice has been merged at a given layer."""

    type: str = "slice_merged"
    provider_slice_id: str = ""
    layer: str = ""


@dataclass
class CompoundCondition(MonitorCondition):
    """AND/OR composition over serialized sub-conditions."""

    type: str = "compound"
    operator: Literal["AND", "OR"] = "OR"
    conditions: list[dict] = field(default_factory=list)


@dataclass
class UserQuestionAnsweredCondition(MonitorCondition):
    """True when a user question has been answered and Planner has written the constraint."""

    type: str = "user_question_answered"
    question_id: str = ""
    canonical_key: str = ""


# ------------------------------------------------------------------
# Factory
# ------------------------------------------------------------------

_TYPE_MAP: dict[str, type[MonitorCondition]] = {
    "git_symbol_exists": GitSymbolExistsCondition,
    "work_item_done": WorkItemDoneCondition,
    "constraint_present": ConstraintPresentCondition,
    "slice_merged": SliceMergedCondition,
    "compound": CompoundCondition,
    "user_question_answered": UserQuestionAnsweredCondition,
}


def condition_from_dict(d: dict[str, Any]) -> MonitorCondition:
    """Dispatch on ``d["type"]`` to build the right condition dataclass."""
    cond_type = d.get("type", "")
    cls = _TYPE_MAP.get(cond_type)
    if cls is None:
        raise ValueError(f"Unknown condition type: {cond_type!r}")
    # Build from known fields for each type
    if cls is GitSymbolExistsCondition:
        return cls(
            ref=d.get("ref", ""),
            file_glob=d.get("file_glob", ""),
            symbol_fqn=d.get("symbol_fqn", ""),
            signature_regex=d.get("signature_regex", ""),
        )
    if cls is WorkItemDoneCondition:
        return cls(
            work_item_id=d.get("work_item_id", ""),
            required_status=d.get("required_status", "MERGED"),
        )
    if cls is ConstraintPresentCondition:
        return cls(
            constraint_key=d.get("constraint_key", ""),
            constraint_dir=d.get("constraint_dir", "analysis/constraints"),
            constraint_id=d.get("constraint_id", ""),
            slice_id=d.get("slice_id", ""),
        )
    if cls is SliceMergedCondition:
        return cls(
            provider_slice_id=d.get("provider_slice_id", ""),
            layer=d.get("layer", ""),
        )
    if cls is CompoundCondition:
        return cls(
            operator=d.get("operator", "OR"),
            conditions=d.get("conditions", []),
        )
    if cls is UserQuestionAnsweredCondition:
        return cls(
            question_id=d.get("question_id", ""),
            canonical_key=d.get("canonical_key", ""),
        )
    return MonitorCondition(type=cond_type)  # pragma: no cover


# ------------------------------------------------------------------
# Execution / timeout / wake / status sub-types
# ------------------------------------------------------------------


@dataclass
class MonitorExecution:
    """How the monitor should be evaluated."""

    mode: Literal["hybrid", "poll", "event"] = "hybrid"
    poll_interval_sec: int = 20
    event_triggers: list[str] = field(default_factory=list)


@dataclass
class MonitorTimeout:
    """What to do when the monitor times out."""

    timeout_sec: int = 7200
    on_timeout: Literal["ESCALATE", "FAIL", "RETRY"] = "ESCALATE"


@dataclass
class MonitorWake:
    """Action to take when the condition is met."""

    action: Literal["WAKE_SLICE"] = "WAKE_SLICE"
    payload: dict = field(default_factory=dict)


@dataclass
class MonitorStatus:
    """Mutable runtime state of a monitor."""

    state: Literal["ACTIVE", "FIRED", "EXPIRED", "FAILED", "CANCELLED"] = "ACTIVE"
    created_at: str = ""
    last_checked_at: str = ""
    check_count: int = 0
    failures: int = 0


# ------------------------------------------------------------------
# SliceInfo (lightweight, avoids importing heavy orchestration types)
# ------------------------------------------------------------------


@dataclass
class SliceInfo:
    """Minimal info about the slice a monitor is waiting on behalf of."""

    layer: str = ""
    slice_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"layer": self.layer, "slice_id": self.slice_id}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SliceInfo:
        return cls(layer=d.get("layer", ""), slice_id=d.get("slice_id", ""))


# ------------------------------------------------------------------
# MonitorSpec — the main type
# ------------------------------------------------------------------


@dataclass
class MonitorSpec:
    """Full specification of a JIT monitor."""

    monitor_version: int = 1
    monitor_id: str = ""
    run_id: str = ""
    waiting_slice: SliceInfo = field(default_factory=SliceInfo)
    signal_id: str = ""
    condition: dict = field(default_factory=dict)
    execution: MonitorExecution = field(default_factory=MonitorExecution)
    timeout: MonitorTimeout = field(default_factory=MonitorTimeout)
    wake: MonitorWake = field(default_factory=MonitorWake)
    status: MonitorStatus = field(default_factory=MonitorStatus)

    def __post_init__(self) -> None:
        if not self.monitor_id:
            self.monitor_id = os.urandom(8).hex()
        if not self.status.created_at:
            self.status.created_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "monitor_version": self.monitor_version,
            "monitor_id": self.monitor_id,
            "run_id": self.run_id,
            "waiting_slice": self.waiting_slice.to_dict(),
            "signal_id": self.signal_id,
            "condition": self.condition,
            "execution": {
                "mode": self.execution.mode,
                "poll_interval_sec": self.execution.poll_interval_sec,
                "event_triggers": list(self.execution.event_triggers),
            },
            "timeout": {
                "timeout_sec": self.timeout.timeout_sec,
                "on_timeout": self.timeout.on_timeout,
            },
            "wake": {
                "action": self.wake.action,
                "payload": self.wake.payload,
            },
            "status": {
                "state": self.status.state,
                "created_at": self.status.created_at,
                "last_checked_at": self.status.last_checked_at,
                "check_count": self.status.check_count,
                "failures": self.status.failures,
            },
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MonitorSpec:
        exec_d = d.get("execution", {})
        timeout_d = d.get("timeout", {})
        wake_d = d.get("wake", {})
        status_d = d.get("status", {})
        return cls(
            monitor_version=d.get("monitor_version", 1),
            monitor_id=d.get("monitor_id", ""),
            run_id=d.get("run_id", ""),
            waiting_slice=SliceInfo.from_dict(d.get("waiting_slice", {})),
            signal_id=d.get("signal_id", ""),
            condition=d.get("condition", {}),
            execution=MonitorExecution(
                mode=exec_d.get("mode", "hybrid"),
                poll_interval_sec=exec_d.get("poll_interval_sec", 20),
                event_triggers=exec_d.get("event_triggers", []),
            ),
            timeout=MonitorTimeout(
                timeout_sec=timeout_d.get("timeout_sec", 7200),
                on_timeout=timeout_d.get("on_timeout", "ESCALATE"),
            ),
            wake=MonitorWake(
                action=wake_d.get("action", "WAKE_SLICE"),
                payload=wake_d.get("payload", {}),
            ),
            status=MonitorStatus(
                state=status_d.get("state", "ACTIVE"),
                created_at=status_d.get("created_at", ""),
                last_checked_at=status_d.get("last_checked_at", ""),
                check_count=status_d.get("check_count", 0),
                failures=status_d.get("failures", 0),
            ),
        )

    def save(self, monitors_dir: Path) -> None:
        """Persist this spec as ``<monitors_dir>/<monitor_id>.json``."""
        monitors_dir.mkdir(parents=True, exist_ok=True)
        path = monitors_dir / f"{self.monitor_id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path) -> MonitorSpec:
        """Load a spec from a JSON file."""
        return cls.from_dict(json.loads(path.read_text()))


# ------------------------------------------------------------------
# MonitorRegistry
# ------------------------------------------------------------------


class MonitorRegistry:
    """File-backed registry of monitor specs.

    Stores each spec as ``<coordination_dir>/monitors/<monitor_id>.json``.
    """

    def __init__(self, coordination_dir: Path) -> None:
        self._monitors_dir = coordination_dir / "monitors"
        self._monitors_dir.mkdir(parents=True, exist_ok=True)

    def register(self, spec: MonitorSpec) -> None:
        """Save a monitor spec to the registry."""
        spec.save(self._monitors_dir)

    def get(self, monitor_id: str) -> MonitorSpec | None:
        """Load a single spec by id, or None if absent."""
        path = self._monitors_dir / f"{monitor_id}.json"
        if not path.exists():
            return None
        return MonitorSpec.load(path)

    def _load_all(self) -> list[MonitorSpec]:
        """Load every spec file in the monitors directory."""
        specs: list[MonitorSpec] = []
        if not self._monitors_dir.exists():
            return specs
        for p in sorted(self._monitors_dir.iterdir()):
            if p.suffix == ".json":
                try:
                    specs.append(MonitorSpec.load(p))
                except (json.JSONDecodeError, KeyError):
                    continue
        return specs

    def get_active(self) -> list[MonitorSpec]:
        """Return all monitors with state == ACTIVE."""
        return [s for s in self._load_all() if s.status.state == "ACTIVE"]

    def get_for_slice(self, slice_id: str) -> list[MonitorSpec]:
        """Return all monitors watching on behalf of *slice_id*."""
        return [s for s in self._load_all() if s.waiting_slice.slice_id == slice_id]

    def get_for_signal(self, signal_id: str) -> MonitorSpec | None:
        """Return the monitor associated with *signal_id*, if any."""
        for s in self._load_all():
            if s.signal_id == signal_id:
                return s
        return None

    def update_status(self, monitor_id: str, state: str, **updates: Any) -> None:
        """Update a monitor's status fields and re-save."""
        spec = self.get(monitor_id)
        if spec is None:
            return
        spec.status.state = state  # type: ignore[assignment]
        for key, val in updates.items():
            if hasattr(spec.status, key):
                setattr(spec.status, key, val)
        spec.save(self._monitors_dir)

    def fire(self, monitor_id: str) -> None:
        """Mark a monitor as FIRED."""
        self.update_status(monitor_id, "FIRED")

    def cancel_for_signal(self, signal_id: str) -> None:
        """Cancel the monitor associated with *signal_id*."""
        spec = self.get_for_signal(signal_id)
        if spec is not None:
            self.update_status(spec.monitor_id, "CANCELLED")

    def cancel_for_slice(self, slice_id: str) -> None:
        """Cancel all active monitors for *slice_id*."""
        for spec in self.get_for_slice(slice_id):
            if spec.status.state == "ACTIVE":
                self.update_status(spec.monitor_id, "CANCELLED")
