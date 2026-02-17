# TODO(single-layer): RESTRUCTURE — RunState loses active_layer field, gains
#   active_phase: Literal["libraries","architecture","quality"].
#   RunConfig.mode (auto/interactive) KEEPS. Run directory structure unchanged.
#   Per-phase iteration tracking and stagnation detection need new state fields:
#   phase_iteration_counts (dict per phase), stagnation_window_remaining,
#   open_work_item_count.  Iteration caps: max_iterations_per_slice (default 20),
#   max_work_items_per_phase (default 50).
# ALGORITHM(single-layer):
#   References: response3 Section 9.3.
#   Data structures (authoritative shared interface):
#     - PhaseId = Literal['libraries', 'architecture', 'quality']
#     - RunConfig fields: {max_iterations_per_slice: int, max_work_items_per_phase: int, stagnation_window: int, mode: Literal['auto','interactive'], ...existing stable fields}.
#     - RunState fields: {active_phase: PhaseId|None, phase_iteration_counts: dict[PhaseId, int], open_work_item_count: int, stagnation_window_remaining: int, last_progress_hash: str, verifier_failure_counts: dict[str, int], blocked_reason: str|None, ...existing metadata}.
#   Interface contracts:
#     - def update_state(self, **patch: Any) -> RunState
#     - def increment_phase_iteration(self, phase: PhaseId) -> RunState
#     - def record_verifier_progress(self, verifier_id: str, progress_hash: str, passed: bool) -> RunState
#   Control flow:
#     1. Remove active_layer/layer-based counters.
#     2. Persist per-phase iteration counters after each PromotionLoop iteration within a phase.
#     3. Update open_work_item_count from WorkItemStore snapshot each iteration.
#     4. On repeated verifier failure with same progress hash, decrement stagnation_window_remaining; block at zero.
#     5. Three forward-only phases: Libraries -> Architecture -> Quality; no cycling back.
#     6. Each phase tracks its own iteration count independently; no global cycle counter.
#   Error handling:
#     - Unknown phase string rejects update with ValueError.
#     - Corrupt state file recovers with backup + empty defaults and diagnostic.
#   Integration points:
#     - Called by lifecycle, promotion loop, monitor executor.
#     - Exposes PhaseId to planner/router and phase-local remediation modules.
#   Test requirements:
#     - Serialization round-trip with new fields.
#     - Stagnation counter behavior across iterations within a single phase.
#     - Phase validation rejects invalid literals (e.g. 'build', 'algorithm').

"""Run configuration and state persistence for PDD lifecycle.

Persists run inputs (``run_config.json``) and mutable state
(``run_state.json``) under ``.pdd_runs/<run_id>/``.

Usage::

    state_mgr = RunStateManager(workspace_root=Path("."), run_id="abc")
    state_mgr.write_config(RunConfig(mode="auto", ...))
    state_mgr.update_state(active_phase="libraries")
    current = state_mgr.read_state()
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, cast

from spec_manager.compliance.promotion.config import PhaseId

logger = logging.getLogger(__name__)

# IMPL(single-layer): Canonical forward-only phase order used by run state.
_PHASE_SEQUENCE: tuple[PhaseId, PhaseId, PhaseId] = ("libraries", "architecture", "quality")
_PHASE_RANK: dict[PhaseId, int] = {phase: idx for idx, phase in enumerate(_PHASE_SEQUENCE)}
_PHASE_CONVERGENCE_FIELDS: dict[PhaseId, tuple[str, ...]] = {
    "libraries": (
        "skeleton_non_draft",
        "library_shape_verifiers_pass",
        "dependency_drift_resolved",
        "no_open_work_items",
        "within_iteration_bounds",
    ),
    "architecture": (
        "skeleton_non_draft",
        "contract_verifiers_pass",
        "import_boundary_rules_satisfied",
        "no_open_work_items",
        "within_iteration_bounds",
    ),
    "quality": (
        "all_tests_pass",
        "contract_verifiers_pass",
        "refactor_items_closed",
        "diff_impact_policy_satisfied",
        "within_iteration_bounds",
    ),
}


def _validate_phase_id(phase: Any) -> PhaseId:
    if not isinstance(phase, str) or phase not in _PHASE_RANK:
        raise ValueError(f"Unknown phase '{phase}'. Expected one of: {', '.join(_PHASE_SEQUENCE)}.")
    return cast("PhaseId", phase)


def _default_phase_iteration_counts() -> dict[PhaseId, int]:
    return {phase: 0 for phase in _PHASE_SEQUENCE}


def _normalize_phase_iteration_counts(raw: dict[Any, Any] | None) -> dict[PhaseId, int]:
    normalized = _default_phase_iteration_counts()
    if raw is None:
        return normalized
    for key, value in raw.items():
        phase = _validate_phase_id(key)
        normalized[phase] = max(0, int(value))
    return normalized


def _default_phase_convergence() -> dict[PhaseId, dict[str, bool]]:
    return {
        phase: {field_name: False for field_name in _PHASE_CONVERGENCE_FIELDS[phase]}
        for phase in _PHASE_SEQUENCE
    }


def _normalize_phase_convergence(raw: dict[Any, Any] | None) -> dict[PhaseId, dict[str, bool]]:
    normalized = _default_phase_convergence()
    if raw is None:
        return normalized
    for key, value in raw.items():
        phase = _validate_phase_id(key)
        if not isinstance(value, dict):
            raise TypeError(f"Convergence payload for phase '{phase}' must be a dict.")
        allowed_fields = set(_PHASE_CONVERGENCE_FIELDS[phase])
        for field_name, status in value.items():
            if field_name not in allowed_fields:
                raise ValueError(f"Unknown convergence field '{field_name}' for phase '{phase}'.")
            normalized[phase][field_name] = bool(status)
    return normalized


@dataclass
class RunConfig:
    """Immutable run configuration written once at pipeline start."""

    run_id: str = ""
    mode: str = "auto"
    input_folder: str = ""
    # IMPL(single-layer): Replace layer-specific iteration caps with phase-local bounds.
    max_iterations_per_slice: int = 20
    max_work_items_per_phase: int = 50
    stagnation_window: int = 2
    max_approval_iterations: int = 3
    max_transition_rounds: int = 3
    retry_budget: int = 3
    test_commands: dict[str, str] = field(default_factory=dict)
    model_ids: dict[str, str] = field(default_factory=dict)
    model_profile_name: str = ""
    enable_snapshots: bool = True
    enable_quality_scoring: bool = False
    created_at: float = 0.0
    _extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunConfig:
        known = {f.name for f in __import__("dataclasses").fields(cls)}
        payload = {k: v for k, v in data.items() if k in known}
        extra = {k: v for k, v in data.items() if k not in known}
        if extra:
            payload["_extra"] = extra
        return cls(**payload)


@dataclass
class RunState:
    """Mutable run state updated after each phase iteration."""

    run_id: str = ""
    # IMPL(single-layer): Forward-only phase state replaces active_layer tracking.
    active_phase: PhaseId = "libraries"
    phase: str = ""  # e.g., "intake", "libraries", "architecture", "quality", "done"
    phases_completed: list[PhaseId] = field(default_factory=list)
    shas: dict[str, str] = field(default_factory=dict)  # phase/checkpoint → clean SHA
    budgets_consumed: dict[str, int] = field(default_factory=dict)
    phase_iteration_counts: dict[PhaseId, int] = field(
        default_factory=_default_phase_iteration_counts
    )
    phase_convergence: dict[PhaseId, dict[str, bool]] = field(
        default_factory=_default_phase_convergence
    )
    open_work_item_count: int = 0
    stagnation_window_remaining: int = 2
    last_progress_hash: str = ""
    verifier_failure_counts: dict[str, int] = field(default_factory=dict)
    blocked_reason: str | None = None
    total_iterations: int = 0
    total_demotions: int = 0
    stagnated_slices: list[str] = field(default_factory=list)
    blocked_slices: list[str] = field(default_factory=list)
    updated_at: float = 0.0
    _extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def __post_init__(self) -> None:
        self.active_phase = _validate_phase_id(self.active_phase)
        self.phase_iteration_counts = _normalize_phase_iteration_counts(self.phase_iteration_counts)
        self.phase_convergence = _normalize_phase_convergence(self.phase_convergence)
        self.open_work_item_count = max(0, int(self.open_work_item_count))
        self.stagnation_window_remaining = max(0, int(self.stagnation_window_remaining))
        if self.phases_completed:
            self.phases_completed = [_validate_phase_id(phase) for phase in self.phases_completed]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunState:
        known = {f.name for f in __import__("dataclasses").fields(cls)}
        payload = {k: v for k, v in data.items() if k in known}
        extra = {k: v for k, v in data.items() if k not in known}
        if extra:
            payload["_extra"] = extra
        return cls(**payload)


class RunStateManager:
    """Reads/writes run config and state files."""

    def __init__(self, workspace_root: Path, run_id: str) -> None:
        self.workspace_root = workspace_root
        self.run_id = run_id
        self._run_dir = workspace_root / ".pdd_runs" / run_id

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    @property
    def config_path(self) -> Path:
        return self._run_dir / "run_config.json"

    @property
    def state_path(self) -> Path:
        return self._run_dir / "run_state.json"

    def write_config(self, config: RunConfig) -> Path:
        """Write run_config.json (called once at pipeline start)."""
        self._run_dir.mkdir(parents=True, exist_ok=True)
        if not config.created_at:
            config.created_at = time.time()
        self.config_path.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
        return self.config_path

    def read_config(self) -> RunConfig | None:
        """Read run_config.json, or None if not found."""
        if not self.config_path.exists():
            return None
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        return RunConfig.from_dict(data)

    def _write_state(self, state: RunState) -> RunState:
        state.updated_at = time.time()
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
        return state

    def _default_stagnation_window(self) -> int:
        config = self.read_config()
        if config is None:
            return 2
        return max(0, int(config.stagnation_window))

    def update_state(self, **kwargs: Any) -> RunState:
        """Update run_state.json with the given fields."""
        state = self.read_state() or RunState(run_id=self.run_id)
        for key, value in kwargs.items():
            if key == "active_phase":
                next_phase = _validate_phase_id(value)
                if _PHASE_RANK[next_phase] < _PHASE_RANK[state.active_phase]:
                    msg = (
                        f"Cannot move active_phase backwards"
                        f" from {state.active_phase} to {next_phase}."
                    )
                    raise ValueError(msg)
                if _PHASE_RANK[next_phase] > _PHASE_RANK[state.active_phase]:
                    state.phases_completed = [
                        phase
                        for phase in state.phases_completed
                        if _PHASE_RANK[phase] <= _PHASE_RANK[state.active_phase]
                    ]
                    if state.active_phase not in state.phases_completed:
                        state.phases_completed.append(state.active_phase)
                state.active_phase = next_phase
            elif key == "phase_iteration_counts":
                if not isinstance(value, dict):
                    raise ValueError("phase_iteration_counts must be a dict[PhaseId, int].")
                state.phase_iteration_counts = _normalize_phase_iteration_counts(value)
            elif key == "phase_convergence":
                if not isinstance(value, dict):
                    raise ValueError("phase_convergence must be a dict[PhaseId, dict[str, bool]].")
                state.phase_convergence = _normalize_phase_convergence(value)
            elif key == "open_work_item_count":
                state.open_work_item_count = max(0, int(value))
            elif key == "stagnation_window_remaining":
                state.stagnation_window_remaining = max(0, int(value))
            elif hasattr(state, key):
                setattr(state, key, value)
            else:
                state._extra[key] = value
        return self._write_state(state)

    def increment_phase_iteration(self, phase: PhaseId) -> RunState:
        # IMPL(single-layer): Per-phase iteration accounting is independent by phase.
        state = self.read_state() or RunState(run_id=self.run_id)
        phase_id = _validate_phase_id(phase)
        if _PHASE_RANK[phase_id] < _PHASE_RANK[state.active_phase]:
            msg = (
                f"Cannot increment past phase '{phase_id}'"
                f" after active phase '{state.active_phase}'."
            )
            raise ValueError(msg)
        if _PHASE_RANK[phase_id] > _PHASE_RANK[state.active_phase]:
            state = self.update_state(active_phase=phase_id)
        state.phase_iteration_counts[phase_id] = state.phase_iteration_counts.get(phase_id, 0) + 1
        state.total_iterations += 1
        config = self.read_config()
        max_iterations = config.max_iterations_per_slice if config else 20
        state.phase_convergence[phase_id]["within_iteration_bounds"] = (
            state.phase_iteration_counts[phase_id] <= max_iterations
        )
        if state.phase_iteration_counts[phase_id] > max_iterations:
            state.blocked_reason = (
                f"Phase '{phase_id}' exceeded max_iterations_per_slice={max_iterations}."
            )
        return self._write_state(state)

    def record_verifier_progress(
        self, verifier_id: str, progress_hash: str, passed: bool
    ) -> RunState:
        # IMPL(single-layer): Stagnation tracks repeated verifier failure with unchanged progress.
        state = self.read_state() or RunState(run_id=self.run_id)
        verifier = verifier_id.strip()
        if not verifier:
            raise ValueError("verifier_id must be non-empty.")
        normalized_hash = progress_hash.strip()
        if not normalized_hash:
            raise ValueError("progress_hash must be non-empty.")

        if passed:
            state.verifier_failure_counts.pop(verifier, None)
            state.stagnation_window_remaining = self._default_stagnation_window()
            state.last_progress_hash = normalized_hash
            return self._write_state(state)

        prior_failures = state.verifier_failure_counts.get(verifier, 0)
        state.verifier_failure_counts[verifier] = prior_failures + 1
        if normalized_hash == state.last_progress_hash:
            state.stagnation_window_remaining = max(0, state.stagnation_window_remaining - 1)
        else:
            state.stagnation_window_remaining = self._default_stagnation_window()
        state.last_progress_hash = normalized_hash
        if state.stagnation_window_remaining == 0:
            state.blocked_reason = (
                f"Stagnation limit reached in phase '{state.active_phase}' for verifier '{verifier}'."
            )
        return self._write_state(state)

    def advance_phase(self) -> RunState:
        # IMPL(single-layer): Phase transitions are forward-only: Libraries -> Architecture -> Quality.
        state = self.read_state() or RunState(run_id=self.run_id)
        current_index = _PHASE_RANK[state.active_phase]
        if current_index >= len(_PHASE_SEQUENCE) - 1:
            return state
        current_phase = state.active_phase
        next_phase = _PHASE_SEQUENCE[current_index + 1]
        if current_phase not in state.phases_completed:
            state.phases_completed.append(current_phase)
        state.active_phase = next_phase
        state.stagnation_window_remaining = self._default_stagnation_window()
        state.last_progress_hash = ""
        state.verifier_failure_counts = {}
        return self._write_state(state)

    def update_phase_convergence(self, phase: PhaseId, **criteria: bool) -> RunState:
        # IMPL(single-layer): Persist per-phase deterministic convergence criteria (Section 9.6).
        state = self.read_state() or RunState(run_id=self.run_id)
        phase_id = _validate_phase_id(phase)
        allowed_fields = set(_PHASE_CONVERGENCE_FIELDS[phase_id])
        for field_name, status in criteria.items():
            if field_name not in allowed_fields:
                raise ValueError(
                    f"Unknown convergence field '{field_name}' for phase '{phase_id}'."
                )
            state.phase_convergence[phase_id][field_name] = bool(status)
        return self._write_state(state)

    def is_phase_converged(self, phase: PhaseId) -> bool:
        state = self.read_state() or RunState(run_id=self.run_id)
        phase_id = _validate_phase_id(phase)
        return all(state.phase_convergence[phase_id].values())

    def read_state(self) -> RunState | None:
        """Read run_state.json, or None if not found."""
        if not self.state_path.exists():
            return None
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return RunState.from_dict(data)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            # IMPL(single-layer): Recover corrupt run_state with backup + clean defaults.
            backup = self.state_path.with_name(
                f"{self.state_path.name}.corrupt.{int(time.time())}.bak"
            )
            try:
                self.state_path.replace(backup)
            except OSError:
                logger.exception("Failed to backup corrupt run_state.json at %s", self.state_path)
            logger.warning("Recovered corrupt run_state.json from %s (%s)", self.state_path, exc)
            recovered = RunState(run_id=self.run_id)
            recovered._extra["recovery_diagnostic"] = f"Recovered corrupt run_state.json: {exc}"
            return self._write_state(recovered)

    def ensure_directories(self) -> None:
        """Create the standard run directory structure."""
        dirs = [
            self._run_dir / "slices",
            self._run_dir / "demotions",
            self._run_dir / "ci" / "l1" / "batches",
            self._run_dir / "ci" / "l2" / "batches",
            self._run_dir / "ci" / "l3" / "batches",
        ]
        reports_dir = self.workspace_root / "reports" / "pdd" / self.run_id
        dirs.extend(
            [
                reports_dir / "architecture",
                reports_dir / "quality",
                reports_dir / "alignment",
            ]
        )
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
