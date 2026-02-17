# TODO(single-layer): KEEP/EXTEND — JIT monitors are phase-independent infrastructure.
#   MonitorSpec conditions watch for workspace state changes (file exists, test passes,
#   work item resolved). Extend with shape-aware conditions: "shape X verifiers all pass",
#   "shape X dependency match clean" (Section 6.3). The monitor->wake-event->promotion-loop
#   pipeline is unchanged. Monitors operate identically across all 3 phases
#   (Libraries, Architecture, Quality).
# ALGORITHM(single-layer):
#   References: response3 Sections 6.3 and 9.3.
#   Data structures:
#     - PhaseId = Literal['libraries', 'architecture', 'quality'] (3 forward-only phases).
#     - Each phase runs its own PromotionLoop with IMPLEMENT step; monitors fire within whichever phase is active.
#     - Add MonitorCondition subclasses:
#       - ShapeVerifiersPassCondition {shape_id: ShapeId}
#       - ShapeDependencyCleanCondition {shape_id: ShapeId, policy: str = 'declared_superset'}
#     - Update _TYPE_MAP to include both new conditions.
#   Interface contracts:
#     - condition_from_dict must deserialize new condition types.
#     - MonitorSpec remains unchanged except conditions can now be shape-aware.
#   Control flow:
#     1. Persist/load shape-aware conditions through registry JSON.
#     2. Keep monitor lifecycle/wake pipeline unchanged.
#     3. Allow monitors to be registered per shape when work items are created.
#     4. Phases block if a finding is outside their authority (phase-local remediation or block); no backtracking to earlier phases.
#   Error handling:
#     - Invalid shape_id in condition payload fails monitor creation.
#   Integration points:
#     - Used by monitor_executor ConditionChecker.
#   Bounds and convergence monitoring (§§9.5-9.6):
#     - Add MonitorCondition subclasses for per-phase convergence enforcement:
#       - IterationCapCondition {phase: PhaseId, slice_id: str, max_iterations: int = 20}
#       - WorkItemCapCondition {phase: PhaseId, max_work_items: int = 50}
#       - StagnationCondition {phase: PhaseId, slice_id: str, verifier_id: str, window: int = 2}
#       - PhaseConvergenceCondition {phase: PhaseId} — skeleton non-draft + all verifiers pass + no open work items.
#     - These fire block/diagnostic wake events when caps are hit or convergence is reached.
#   Test requirements:
#     - Serialization round-trip for new condition types.
#     - Registry list/filter includes shape-aware monitors.
#     - Iteration/work-item cap conditions fire at correct thresholds.
#     - Stagnation condition fires after N same-verifier failures with no diff progress.
# IMPL(single-layer): `monitors.py` is the authoritative persisted-condition schema for
# monitor JSON files; shape-aware and convergence-bound condition payloads must be added
# here before executor/planner wiring so load/save contracts stay synchronized.
# IMPL(single-layer): Condition payloads carrying phase semantics should align to the
# shared forward-only phase vocabulary (`libraries`/`architecture`/`quality`) used by
# run state, work items, and lifecycle convergence checks.
# IMPL(single-layer): Bound-enforcement monitor specs (iteration/work-item/stagnation)
# should default timeout handling to FAIL/ESCALATE rather than RETRY so §9.5 caps can
# terminate bounded cycles with diagnostics instead of re-arming indefinitely.

"""JIT monitor specifications and registry.

A MonitorSpec describes a condition to watch for, plus what to do when
the condition becomes true (fire a wake event).  The MonitorRegistry
stores specs on disk under ``coordination/monitors/`` and provides
lookup helpers for the executor and planner.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from spec_manager.compliance.promotion.config import PhaseId

logger = logging.getLogger(__name__)

_EXECUTION_MODES = {"hybrid", "poll", "event"}
_TIMEOUT_ACTIONS = {"ESCALATE", "FAIL", "RETRY"}
_WAKE_ACTIONS = {"WAKE_SLICE"}
_MONITOR_STATES = {"ACTIVE", "FIRED", "EXPIRED", "FAILED", "CANCELLED"}
_ALLOWED_MATCHER_POLICIES = {"declared_superset", "exact", "allowlist_only"}
_ALLOWED_PHASES = {"libraries", "architecture", "quality"}


def _require_enum(
    *,
    field_name: str,
    value: Any,
    allowed: set[str],
    normalize: str = "upper",
) -> str:
    raw = str(value).strip()
    if normalize == "lower":
        normalized = raw.lower()
    elif normalize == "upper":
        normalized = raw.upper()
    else:
        normalized = raw
    if normalized not in allowed:
        raise ValueError(
            f"Invalid monitor field '{field_name}': {raw!r}. Expected one of {sorted(allowed)}."
        )
    return normalized


def _require_non_empty(field_name: str, value: Any) -> str:
    raw = str(value).strip()
    if not raw:
        raise ValueError(f"Invalid monitor field '{field_name}': empty value.")
    return raw


def _require_positive_int(
    *, field_name: str, value: Any, default: int
) -> int:
    raw = default if value is None else value
    try:
        parsed = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid monitor field '{field_name}': {raw!r}. Expected a positive integer."
        ) from exc
    if parsed <= 0:
        raise ValueError(
            f"Invalid monitor field '{field_name}': {raw!r}. Must be > 0."
        )
    return parsed


def _require_phase_id(value: Any, *, default: PhaseId | None = None) -> PhaseId:
    if value is None or not str(value).strip():
        if default is not None:
            return default
    return cast(
        "PhaseId",
        _require_enum(
            field_name="phase",
            value=value,
            allowed=_ALLOWED_PHASES,
            normalize="lower",
        ),
    )


def _condition_shape_id(condition: dict[str, Any]) -> str:
    if not isinstance(condition, dict):
        return ""
    cond_type = str(condition.get("type", "")).strip()
    if cond_type in {"shape_verifiers_pass", "shape_dependency_clean"}:
        return str(condition.get("shape_id", "")).strip()
    return ""


def _condition_phase(condition: dict[str, Any]) -> str:
    if not isinstance(condition, dict):
        return ""
    cond_type = str(condition.get("type", "")).strip()
    if cond_type in {
        "iteration_cap",
        "work_item_cap",
        "stagnation",
        "phase_convergence",
    }:
        return str(condition.get("phase", "")).strip().lower()
    return ""


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
class ShapeVerifiersPassCondition(MonitorCondition):
    """True when required verifiers pass for the shape."""

    type: str = "shape_verifiers_pass"
    shape_id: str = ""


@dataclass
class ShapeDependencyCleanCondition(MonitorCondition):
    """True when shape dependency drift is clean for policy."""

    type: str = "shape_dependency_clean"
    shape_id: str = ""
    policy: str = "declared_superset"


@dataclass
class IterationCapCondition(MonitorCondition):
    """True when a phase reaches the per-slice iteration cap."""

    type: str = "iteration_cap"
    phase: PhaseId = "libraries"
    slice_id: str = ""
    max_iterations: int = 20


@dataclass
class WorkItemCapCondition(MonitorCondition):
    """True when open work items in phase exceed the cap."""

    type: str = "work_item_cap"
    phase: PhaseId = "libraries"
    max_work_items: int = 50


@dataclass
class StagnationCondition(MonitorCondition):
    """True when a verifier fails unchanged for a stagnation window."""

    type: str = "stagnation"
    phase: PhaseId = "libraries"
    slice_id: str = ""
    verifier_id: str = ""
    window: int = 2


@dataclass
class PhaseConvergenceCondition(MonitorCondition):
    """True when the active phase convergence criteria are satisfied."""

    type: str = "phase_convergence"
    phase: PhaseId = "libraries"


# ------------------------------------------------------------------
# Factory
# ------------------------------------------------------------------

# IMPL(single-layer): `_TYPE_MAP` is the single registry for condition type
# deserialization. Add/remove types atomically with `condition_from_dict` and executor
# dispatch updates; do not keep compatibility aliases for retired payload types.
_TYPE_MAP: dict[str, type[MonitorCondition]] = {
    "git_symbol_exists": GitSymbolExistsCondition,
    "work_item_done": WorkItemDoneCondition,
    "constraint_present": ConstraintPresentCondition,
    "shape_verifiers_pass": ShapeVerifiersPassCondition,
    "shape_dependency_clean": ShapeDependencyCleanCondition,
    "iteration_cap": IterationCapCondition,
    "work_item_cap": WorkItemCapCondition,
    "stagnation": StagnationCondition,
    "phase_convergence": PhaseConvergenceCondition,
}


def condition_from_dict(d: dict[str, Any]) -> MonitorCondition:
    """Dispatch on ``d["type"]`` to build the right condition dataclass."""
    # IMPL(single-layer): New shape-aware/bounds-aware condition branches should fail
    # closed on invalid required identifiers (e.g., shape/phase/slice/verifier IDs) so
    # monitors cannot silently enter ACTIVE state with non-authoritative inputs.
    if not isinstance(d, dict):
        raise TypeError("Condition payload must be a dict.")
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
    if cls is ShapeVerifiersPassCondition:
        return cls(shape_id=_require_non_empty("shape_id", d.get("shape_id")))
    if cls is ShapeDependencyCleanCondition:
        return cls(
            shape_id=_require_non_empty("shape_id", d.get("shape_id")),
            policy=_require_enum(
                field_name="policy",
                value=d.get("policy", "declared_superset"),
                allowed=_ALLOWED_MATCHER_POLICIES,
                normalize="lower",
            ),
        )
    if cls is IterationCapCondition:
        return cls(
            phase=_require_phase_id(d.get("phase"), default="libraries"),
            slice_id=_require_non_empty("slice_id", d.get("slice_id")),
            max_iterations=_require_positive_int(
                field_name="max_iterations",
                value=d.get("max_iterations", 20),
                default=20,
            ),
        )
    if cls is WorkItemCapCondition:
        return cls(
            phase=_require_phase_id(d.get("phase"), default="libraries"),
            max_work_items=_require_positive_int(
                field_name="max_work_items",
                value=d.get("max_work_items", 50),
                default=50,
            ),
        )
    if cls is StagnationCondition:
        return cls(
            phase=_require_phase_id(d.get("phase"), default="libraries"),
            slice_id=_require_non_empty("slice_id", d.get("slice_id")),
            verifier_id=_require_non_empty("verifier_id", d.get("verifier_id")),
            window=_require_positive_int(
                field_name="window",
                value=d.get("window", 2),
                default=2,
            ),
        )
    if cls is PhaseConvergenceCondition:
        return cls(phase=_require_phase_id(d.get("phase"), default="libraries"))
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
    last_checked_at: str | None = None
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

    # IMPL(single-layer): `condition` remains persisted as raw JSON payload; callers must
    # normalize through `condition_from_dict` at execution boundaries so registry storage
    # can carry heterogeneous condition types without ad-hoc per-caller parsing.
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
        created_at = status_d.get("created_at", "")
        if not isinstance(created_at, str):
            created_at = ""
        last_checked_at_raw = status_d.get("last_checked_at")
        last_checked_at = (
            last_checked_at_raw
            if isinstance(last_checked_at_raw, str) and last_checked_at_raw
            else None
        )
        mode = _require_enum(
            field_name="execution.mode",
            value=exec_d.get("mode", "hybrid"),
            allowed=_EXECUTION_MODES,
            normalize="lower",
        )
        on_timeout = _require_enum(
            field_name="timeout.on_timeout",
            value=timeout_d.get("on_timeout", "ESCALATE"),
            allowed=_TIMEOUT_ACTIONS,
            normalize="upper",
        )
        wake_action = _require_enum(
            field_name="wake.action",
            value=wake_d.get("action", "WAKE_SLICE"),
            allowed=_WAKE_ACTIONS,
            normalize="upper",
        )
        state = _require_enum(
            field_name="status.state",
            value=status_d.get("state", "ACTIVE"),
            allowed=_MONITOR_STATES,
            normalize="upper",
        )
        return cls(
            monitor_version=d.get("monitor_version", 1),
            monitor_id=d.get("monitor_id", ""),
            run_id=d.get("run_id", ""),
            waiting_slice=SliceInfo.from_dict(d.get("waiting_slice", {})),
            signal_id=d.get("signal_id", ""),
            condition=d.get("condition", {}),
            execution=MonitorExecution(
                mode=mode,
                poll_interval_sec=exec_d.get("poll_interval_sec", 20),
                event_triggers=exec_d.get("event_triggers", []),
            ),
            timeout=MonitorTimeout(
                timeout_sec=timeout_d.get("timeout_sec", 7200),
                on_timeout=on_timeout,
            ),
            wake=MonitorWake(
                action=wake_action,
                payload=wake_d.get("payload", {}),
            ),
            status=MonitorStatus(
                state=state,
                created_at=created_at,
                last_checked_at=last_checked_at,
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
        self._coordination_dir = coordination_dir
        self._monitors_dir = coordination_dir / "monitors"
        self._receipts_path = coordination_dir / "monitor_receipts.jsonl"
        self._monitors_dir.mkdir(parents=True, exist_ok=True)

    @property
    def coordination_dir(self) -> Path:
        """Run-scoped coordination directory that owns this registry."""
        return self._coordination_dir

    def register(self, spec: MonitorSpec) -> None:
        """Save a monitor spec to the registry."""
        if not isinstance(spec.condition, dict):
            raise TypeError("Monitor condition must be a dict.")
        condition_from_dict(spec.condition)
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
                except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
                    logger.warning("Skipping malformed monitor spec '%s': %s", p, exc)
                    continue
        return specs

    def get_active(self) -> list[MonitorSpec]:
        """Return all monitors with state == ACTIVE."""
        return [s for s in self._load_all() if s.status.state == "ACTIVE"]

    def get_for_slice(self, slice_id: str) -> list[MonitorSpec]:
        """Return all monitors watching on behalf of *slice_id*."""
        return [s for s in self._load_all() if s.waiting_slice.slice_id == slice_id]

    def get_for_shape(self, shape_id: str) -> list[MonitorSpec]:
        """Return all monitors tracking a specific shape."""
        target = str(shape_id).strip()
        if not target:
            return []
        return [
            s
            for s in self._load_all()
            if _condition_shape_id(s.condition) == target
        ]

    def get_for_phase(self, phase: PhaseId) -> list[MonitorSpec]:
        """Return all monitors associated with a specific phase."""
        normalized = _require_phase_id(phase)
        return [
            s
            for s in self._load_all()
            if _condition_phase(s.condition) == normalized
        ]

    def get_for_signal(self, signal_id: str) -> MonitorSpec | None:
        """Return the monitor associated with *signal_id*, if any."""
        for s in self._load_all():
            if s.signal_id == signal_id:
                return s
        return None

    def update_status(
        self,
        monitor_id: str,
        state: str,
        *,
        receipt_event: str | None = None,
        receipt_payload: dict[str, Any] | None = None,
        **updates: Any,
    ) -> None:
        """Update a monitor's status fields and re-save."""
        spec = self.get(monitor_id)
        if spec is None:
            raise KeyError(f"Monitor not found: {monitor_id}")
        normalized_state = _require_enum(
            field_name="status.state",
            value=state,
            allowed=_MONITOR_STATES,
            normalize="upper",
        )
        previous_state = spec.status.state
        spec.status.state = normalized_state  # type: ignore[assignment]
        for key, val in updates.items():
            if hasattr(spec.status, key):
                setattr(spec.status, key, val)
        spec.save(self._monitors_dir)
        self._append_receipt(
            spec,
            previous_state=previous_state,
            new_state=normalized_state,
            event=receipt_event,
            payload=receipt_payload,
        )

    def fire(self, monitor_id: str) -> None:
        """Mark a monitor as FIRED."""
        self.update_status(monitor_id, "FIRED", receipt_event="monitor_fired")

    def cancel_for_signal(self, signal_id: str) -> None:
        """Cancel the monitor associated with *signal_id*."""
        spec = self.get_for_signal(signal_id)
        if spec is not None:
            self.update_status(
                spec.monitor_id,
                "CANCELLED",
                receipt_event="monitor_cancelled",
                receipt_payload={"cancel_scope": "signal", "signal_id": signal_id},
            )

    def cancel_for_slice(self, slice_id: str) -> None:
        """Cancel all active monitors for *slice_id*."""
        for spec in self.get_for_slice(slice_id):
            if spec.status.state == "ACTIVE":
                self.update_status(
                    spec.monitor_id,
                    "CANCELLED",
                    receipt_event="monitor_cancelled",
                    receipt_payload={"cancel_scope": "slice", "slice_id": slice_id},
                )

    def _append_receipt(
        self,
        spec: MonitorSpec,
        *,
        previous_state: str,
        new_state: str,
        event: str | None,
        payload: dict[str, Any] | None,
    ) -> None:
        terminal_states = {"FIRED", "CANCELLED", "EXPIRED", "FAILED"}
        if new_state not in terminal_states or previous_state == new_state:
            return

        # IMPL(single-layer): Cap/stagnation/convergence monitors rely on receipt payload
        # diagnostics to distinguish block vs phase-complete wake outcomes downstream.
        record: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event or f"monitor_{new_state.lower()}",
            "monitor_id": spec.monitor_id,
            "run_id": spec.run_id,
            "signal_id": spec.signal_id,
            "waiting_slice": spec.waiting_slice.to_dict(),
            "condition_type": str(spec.condition.get("type", "")),
            "previous_state": previous_state,
            "new_state": new_state,
        }
        if payload:
            record["payload"] = payload

        self._receipts_path.parent.mkdir(parents=True, exist_ok=True)
        with self._receipts_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
