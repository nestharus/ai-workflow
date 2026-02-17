# TODO(single-layer): KEEP/EXTEND — MonitorExecutor checks conditions and fires wake
#   events. Extend ConditionChecker to evaluate shape-related conditions (verifier
#   status, dependency match, contract satisfaction). The hybrid event/poll model
#   is unchanged. Executor operates identically across all 3 phases
#   (Libraries, Architecture, Quality).
# ALGORITHM(single-layer):
#   References: response3 Sections 6.3 and 9.3.
#   Data structures:
#     - PhaseId = Literal['libraries', 'architecture', 'quality'] (3 forward-only phases).
#     - Each phase edits code via its own PromotionLoop with IMPLEMENT step; executor fires wake events within the active phase.
#     - ConditionChecker dependencies gain optional shape_match_provider and verifier_provider interfaces.
#   Interface contracts:
#     - def check(self, condition: MonitorCondition) -> bool dispatches to new checkers:
#       - _check_shape_verifiers_pass(cond)
#       - _check_shape_dependency_clean(cond)
#   Control flow:
#     1. For ShapeVerifiersPassCondition, load latest verifier summary and return true only when all required verifiers pass.
# IMPL(single-layer): `ShapeVerifiersPassCondition` should evaluate ACTIVE-shape
# verifier summaries for convergence authority; PROPOSAL-only diagnostics stay non-blocking.
#     2. For ShapeDependencyCleanCondition, load latest ShapeMatchReport and ensure dependency drift sets are empty.
# IMPL(single-layer): Treat matcher `status in {'AMBIGUOUS','BLOCKED'}` as not clean
# even when drift sets are empty, because these states indicate unresolved routing or
# missing deterministic evidence rather than convergence.
# IMPL(single-layer): Keep checker dispatch branches in lockstep with
# `coordination.monitors._TYPE_MAP`/`condition_from_dict`; newly persisted condition
# payload types must not be treated as implicitly passing when dispatch is missing.
# IMPL(single-layer): Condition evaluation must be grounded in deterministic matcher/
# verifier evidence (§6.3); call-graph outputs remain routing hints and must not be
# treated as direct pass/fail monitor authority.
#     3. Keep hybrid poll/event execution and wake queue logic unchanged.
#     4. Phases are forward-only (Libraries -> Architecture -> Quality); monitors that detect issues outside the active phase's authority cause a block, not backtracking.
#   Error handling:
#     - Missing provider/evidence returns False and logs debug warning; monitor remains active.
#   Integration points:
#     - Called by PromotionLoop COORDINATE/monitor tick within each phase's cycle.
#     - Calls routing.verifiers and routing.matcher caches.
#   Bounds and convergence enforcement (§§9.5-9.6):
#     - ConditionChecker dispatches to bound-enforcement checkers:
#       - _check_iteration_cap(cond): compare current iteration count against max_iterations_per_slice (default 20).
#       - _check_work_item_cap(cond): compare open work items against max_work_items_per_phase (default 50).
#       - _check_stagnation(cond): detect same verifier failing with no diff progress within stagnation_window (default 2).
#       - _check_phase_convergence(cond): skeleton non-draft + all shape verifiers pass + no open work items + within bounds.
#     - Cap/stagnation hits produce block-with-diagnostics wake events (not retry).
#     - Phase convergence success produces phase-complete wake event.
#   Test requirements:
#     - New condition checks pass/fail behavior.
#     - Missing evidence does not crash executor.
#     - Wake event generated when condition flips true.
#     - Bound enforcement: cap hits produce block events, not retries.
#     - Phase convergence fires only when all criteria met simultaneously.

"""Hybrid event/poll runtime for JIT monitors.

The MonitorExecutor checks active monitors against current workspace
state and fires wake events when conditions are met.  ConditionChecker
is a read-only evaluator for individual condition types.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import re
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from spec_manager.compliance.promotion.config import PhaseId
from spec_manager.orchestration.run_state import RunStateManager
from spec_manager.routing.matcher import (
    MatchPolicy,
    ShapeMatchReport,
    build_observed_dependency_graph,
    match_all_shapes,
)
from spec_manager.routing.shapes import ShapeId, ShapePackIndex, load_shape_pack
from spec_manager.routing.verifiers import VerifierRunSummary, run_all_active_shape_verifiers

from .monitors import (
    ConstraintPresentCondition,
    GitSymbolExistsCondition,
    IterationCapCondition,
    MonitorCondition,
    MonitorRegistry,
    MonitorSpec,
    PhaseConvergenceCondition,
    ShapeDependencyCleanCondition,
    ShapeVerifiersPassCondition,
    StagnationCondition,
    WorkItemCapCondition,
    WorkItemDoneCondition,
    condition_from_dict,
)
from .wake_queue import WakeEvent, WakeQueue

logger = logging.getLogger(__name__)


class ConstraintLookupStore(Protocol):
    """Constraint store contract needed by ConditionChecker."""

    def load_merged(self, slice_id: str) -> list[Any]:
        """Return merged constraints for a slice."""


class ShapeIndexProvider(Protocol):
    """Load the active shape index used by shape-aware monitor checks."""

    def __call__(self) -> ShapePackIndex:
        ...


class ShapeVerifierSummaryProvider(Protocol):
    """Build verifier summaries keyed by shape id."""

    def __call__(self, shape_index: ShapePackIndex) -> dict[ShapeId, VerifierRunSummary]:
        ...


class ShapeMatchReportProvider(Protocol):
    """Build matcher reports for shape dependency checks."""

    def __call__(
        self,
        shape_index: ShapePackIndex,
        observed_graph: dict[str, set[str]],
        policy: MatchPolicy,
    ) -> dict[ShapeId, ShapeMatchReport]:
        ...


# ------------------------------------------------------------------
# ConditionChecker
# ------------------------------------------------------------------


class ConditionChecker:
    """Evaluates MonitorConditions against current workspace state.

    Read-only and safe to call from any thread.
    """

    def __init__(
        self,
        workspace_root: Path,
        work_item_store: Any = None,
        constraints_store: ConstraintLookupStore | None = None,
        shape_index_provider: ShapeIndexProvider | None = None,
        verifier_provider: ShapeVerifierSummaryProvider | None = None,
        shape_match_provider: ShapeMatchReportProvider | None = None,
        run_state_manager: RunStateManager | None = None,
    ) -> None:
        self._workspace_root = workspace_root
        self._work_item_store = work_item_store
        self._constraints_store = constraints_store
        self._shape_index_provider = shape_index_provider
        self._verifier_provider = verifier_provider
        self._shape_match_provider = shape_match_provider
        self._run_state_manager = run_state_manager
        self._shape_index: ShapePackIndex | None = None
        self._shape_verifier_summaries: dict[ShapeId, VerifierRunSummary] | None = None
        self._shape_match_reports: dict[str, dict[ShapeId, ShapeMatchReport]] = {}

    def check(self, condition: MonitorCondition) -> bool:
        """Dispatch to the appropriate checker."""
        # IMPL(single-layer): Unknown/new condition payloads must evaluate False
        # until explicit deterministic checker wiring is added here.
        if isinstance(condition, GitSymbolExistsCondition):
            return self._check_git_symbol_exists(condition)
        if isinstance(condition, WorkItemDoneCondition):
            return self._check_work_item_done(condition)
        if isinstance(condition, ConstraintPresentCondition):
            return self._check_constraint_present(condition)
        if isinstance(condition, ShapeVerifiersPassCondition):
            return self._check_shape_verifiers_pass(condition)
        if isinstance(condition, ShapeDependencyCleanCondition):
            return self._check_shape_dependency_clean(condition)
        if isinstance(condition, IterationCapCondition):
            return self._check_iteration_cap(condition)
        if isinstance(condition, WorkItemCapCondition):
            return self._check_work_item_cap(condition)
        if isinstance(condition, StagnationCondition):
            return self._check_stagnation(condition)
        if isinstance(condition, PhaseConvergenceCondition):
            return self._check_phase_convergence(condition)
        return False

    def _check_git_symbol_exists(self, cond: GitSymbolExistsCondition) -> bool:
        """Check for a symbol signature at a specific git ref (read-only)."""
        if not cond.ref or not cond.symbol_fqn or not cond.signature_regex:
            return False

        try:
            signature_re = re.compile(cond.signature_regex, flags=re.MULTILINE)
        except re.error:
            logger.warning(
                "Monitor git_symbol_exists has invalid signature_regex for ref=%s: %r",
                cond.ref,
                cond.signature_regex,
            )
            return False

        files = self._git_list_files(cond.ref)
        if files is None:
            return False
        if cond.file_glob:
            files = [path for path in files if fnmatch.fnmatch(path, cond.file_glob)]
        if not files:
            return False

        for rel_path in files:
            content = self._git_show_file(cond.ref, rel_path)
            if content is None:
                continue
            if cond.symbol_fqn not in content:
                continue
            if signature_re.search(content):
                return True
        return False

    def _check_work_item_done(self, cond: WorkItemDoneCondition) -> bool:
        """Check if a work item has reached the required status."""
        if self._work_item_store is None:
            return False
        item = self._work_item_store.get(cond.work_item_id)
        if item is None:
            return False
        return item.status == cond.required_status

    def _check_constraint_present(self, cond: ConstraintPresentCondition) -> bool:
        """Check if a constraint exists.

        When *constraint_id* and *slice_id* are set and a constraints_store
        is available, look up the specific constraint by ID using
        ``load_merged`` (includes system-level constraints).  Otherwise
        fall back to checking for a file on disk whose name contains the
        *constraint_key*.
        """
        # Constraint-store-aware path: look for specific constraint by ID
        if cond.constraint_id and cond.slice_id and self._constraints_store is not None:
            constraints = self._constraints_store.load_merged(cond.slice_id)
            return any(c.constraint_id == cond.constraint_id for c in constraints)

        # Fallback: file-existence check
        if not cond.constraint_key:
            return False
        constraint_dir = self._workspace_root / cond.constraint_dir
        if not constraint_dir.exists():
            return False
        return any(cond.constraint_key in p.name for p in constraint_dir.iterdir())

    def _check_shape_verifiers_pass(self, cond: ShapeVerifiersPassCondition) -> bool:
        shape_index = self._shape_index_for_checks()
        if shape_index is None:
            logger.debug("ShapeVerifiersPassCondition missing shape index for shape=%s", cond.shape_id)
            return False
        shape = shape_index.shapes.get(cond.shape_id)
        if shape is None:
            logger.debug("ShapeVerifiersPassCondition missing shape=%s", cond.shape_id)
            return False
        if str(shape.status).strip().lower() != "active":
            logger.debug("ShapeVerifiersPassCondition ignored for non-ACTIVE shape=%s", cond.shape_id)
            return False
        summaries = self._shape_verifier_summaries()
        if summaries is None:
            logger.debug("ShapeVerifiersPassCondition missing verifier summaries for shape=%s", cond.shape_id)
            return False
        summary = summaries.get(cond.shape_id)
        if summary is None:
            logger.debug("ShapeVerifiersPassCondition no summary for shape=%s", cond.shape_id)
            return False
        return bool(summary.all_passed and not summary.non_ship_block)

    def _check_shape_dependency_clean(self, cond: ShapeDependencyCleanCondition) -> bool:
        shape_index = self._shape_index_for_checks()
        if shape_index is None:
            logger.debug(
                "ShapeDependencyCleanCondition missing shape index for shape=%s",
                cond.shape_id,
            )
            return False
        shape = shape_index.shapes.get(cond.shape_id)
        if shape is None:
            logger.debug("ShapeDependencyCleanCondition missing shape=%s", cond.shape_id)
            return False
        if str(shape.status).strip().lower() != "active":
            logger.debug("ShapeDependencyCleanCondition ignored for non-ACTIVE shape=%s", cond.shape_id)
            return False
        reports = self._shape_match_reports_for(cond.policy)
        if reports is None:
            logger.debug(
                "ShapeDependencyCleanCondition missing matcher reports for shape=%s policy=%s",
                cond.shape_id,
                cond.policy,
            )
            return False
        report = reports.get(cond.shape_id)
        if report is None:
            logger.debug(
                "ShapeDependencyCleanCondition missing report for shape=%s policy=%s",
                cond.shape_id,
                cond.policy,
            )
            return False
        if str(report.status).strip().upper() in {"AMBIGUOUS", "BLOCKED"}:
            return False
        if report.missing_dependencies or report.unexpected_dependencies:
            return False
        return True

    def _check_iteration_cap(self, cond: IterationCapCondition) -> bool:
        state = self._current_run_state()
        if state is None:
            logger.debug("IterationCapCondition missing run state for phase=%s", cond.phase)
            return False
        if cond.phase != state.active_phase:
            logger.debug(
                "IterationCapCondition ignored for inactive phase=%s (active=%s)",
                cond.phase,
                state.active_phase,
            )
            return False
        iteration_count = state.phase_iteration_counts.get(cond.phase, 0)
        return iteration_count >= cond.max_iterations

    def _check_work_item_cap(self, cond: WorkItemCapCondition) -> bool:
        state = self._current_run_state()
        if state is None:
            logger.debug("WorkItemCapCondition missing run state for phase=%s", cond.phase)
            return False
        if cond.phase != state.active_phase:
            logger.debug(
                "WorkItemCapCondition ignored for inactive phase=%s (active=%s)",
                cond.phase,
                state.active_phase,
            )
            return False
        open_work_items = self._open_work_item_count(phase=cond.phase, fallback_state=state)
        if open_work_items is None:
            logger.debug("WorkItemCapCondition missing open-work-item evidence for phase=%s", cond.phase)
            return False
        return open_work_items >= cond.max_work_items

    def _check_stagnation(self, cond: StagnationCondition) -> bool:
        state = self._current_run_state()
        if state is None:
            logger.debug("StagnationCondition missing run state for phase=%s", cond.phase)
            return False
        if cond.phase != state.active_phase:
            logger.debug(
                "StagnationCondition ignored for inactive phase=%s (active=%s)",
                cond.phase,
                state.active_phase,
            )
            return False
        if not cond.verifier_id:
            logger.debug("StagnationCondition missing verifier_id for phase=%s", cond.phase)
            return False
        failure_count = state.verifier_failure_counts.get(cond.verifier_id, 0)
        if failure_count <= 0:
            return False
        configured_window = self._stagnation_window_default()
        window = max(1, cond.window)
        allowed_remaining = max(0, configured_window - window + 1)
        return failure_count >= window and state.stagnation_window_remaining <= allowed_remaining

    def _check_phase_convergence(self, cond: PhaseConvergenceCondition) -> bool:
        state = self._current_run_state()
        if state is None:
            logger.debug("PhaseConvergenceCondition missing run state for phase=%s", cond.phase)
            return False
        if cond.phase != state.active_phase:
            logger.debug(
                "PhaseConvergenceCondition ignored for inactive phase=%s (active=%s)",
                cond.phase,
                state.active_phase,
            )
            return False
        if not self._all_active_shape_verifiers_pass():
            return False
        phase_convergence = state.phase_convergence.get(cond.phase)
        if not phase_convergence:
            return False
        if not all(phase_convergence.values()):
            return False
        open_work_items = self._open_work_item_count(phase=cond.phase, fallback_state=state)
        if open_work_items is None:
            logger.debug("PhaseConvergenceCondition missing open-work-item evidence for phase=%s", cond.phase)
            return False
        return open_work_items == 0

    def _shape_index_for_checks(self) -> ShapePackIndex | None:
        if self._shape_index is not None:
            return self._shape_index
        try:
            if self._shape_index_provider is not None:
                self._shape_index = self._shape_index_provider()
            else:
                self._shape_index = load_shape_pack(self._workspace_root)
            return self._shape_index
        except Exception:
            logger.debug("MonitorConditionChecker failed to load shape index", exc_info=True)
            return None

    def _shape_verifier_summaries(self) -> dict[ShapeId, VerifierRunSummary] | None:
        if self._shape_verifier_summaries is not None:
            return self._shape_verifier_summaries
        index = self._shape_index_for_checks()
        if index is None:
            logger.debug("MonitorConditionChecker cannot evaluate verifier summaries without shape index")
            return None
        try:
            if self._verifier_provider is not None:
                self._shape_verifier_summaries = self._verifier_provider(index)
            else:
                self._shape_verifier_summaries = run_all_active_shape_verifiers(
                    index,
                    self._workspace_root,
                )
            return self._shape_verifier_summaries
        except Exception:
            logger.debug("MonitorConditionChecker failed to load shape verifier summaries", exc_info=True)
            return None

    def _shape_match_reports_for(self, policy: str) -> dict[ShapeId, ShapeMatchReport] | None:
        normalized_policy = str(policy).strip().lower()
        if normalized_policy in self._shape_match_reports:
            return self._shape_match_reports[normalized_policy]
        index = self._shape_index_for_checks()
        if index is None:
            logger.debug("MonitorConditionChecker cannot evaluate matcher reports without shape index")
            return None
        summaries = self._shape_verifier_summaries()
        if summaries is None:
            logger.debug(
                "MonitorConditionChecker cannot evaluate matcher reports without verifier summaries"
            )
            return None
        try:
            observed_graph = build_observed_dependency_graph(self._workspace_root)
            policy_obj = MatchPolicy(dependency_mode=normalized_policy)
            if self._shape_match_provider is not None:
                reports = self._shape_match_provider(index, observed_graph, policy_obj)
            else:
                reports = match_all_shapes(
                    index=index,
                    observed_graph=observed_graph,
                    verifier_results_by_shape={
                        shape_id: summary.results for shape_id, summary in summaries.items()
                    },
                    policy=policy_obj,
                )
            self._shape_match_reports[normalized_policy] = reports
            return reports
        except Exception:
            logger.debug("MonitorConditionChecker failed to load matcher reports", exc_info=True)
            return None

    def _current_run_state(self):
        if self._run_state_manager is None:
            return None
        try:
            return self._run_state_manager.read_state()
        except Exception:
            logger.debug("MonitorConditionChecker failed to read run state", exc_info=True)
            return None

    def _stagnation_window_default(self) -> int:
        if self._run_state_manager is None:
            return 2
        try:
            config = self._run_state_manager.read_config()
            if config is None:
                return 2
            return max(1, int(config.stagnation_window))
        except Exception:
            logger.debug("MonitorConditionChecker failed to read run config for stagnation window", exc_info=True)
            return 2

    def _open_work_item_count(self, phase: PhaseId, *, fallback_state: Any | None = None) -> int | None:
        if self._work_item_store is not None:
            try:
                return len(self._work_item_store.list_open(phase=phase))
            except TypeError:
                logger.debug(
                    "MonitorConditionChecker cannot count open work items via list_open for phase=%s",
                    phase,
                )
            except AttributeError:
                logger.debug(
                    "MonitorConditionChecker work_item_store missing list_open for phase=%s",
                    phase,
                )
        if fallback_state is not None and hasattr(fallback_state, "open_work_item_count"):
            return int(fallback_state.open_work_item_count)
        state = self._current_run_state()
        if state is None:
            return None
        return int(state.open_work_item_count)

    def _all_active_shape_verifiers_pass(self) -> bool:
        index = self._shape_index_for_checks()
        if index is None:
            logger.debug("PhaseConvergenceCondition cannot evaluate verifier pass for missing shape index")
            return False
        summaries = self._shape_verifier_summaries()
        if summaries is None:
            logger.debug("PhaseConvergenceCondition cannot evaluate verifier pass")
            return False
        for shape_id, shape in index.shapes.items():
            if str(shape.status).strip().lower() != "active":
                continue
            summary = summaries.get(shape_id)
            if summary is None:
                logger.debug("PhaseConvergenceCondition missing summary for shape=%s", shape_id)
                return False
            if not summary.all_passed or summary.non_ship_block:
                return False
        return True

    def _git_list_files(self, ref: str) -> list[str] | None:
        output = self._run_git("ls-tree", "-r", "--name-only", ref)
        if output is None:
            return None
        return [line.strip() for line in output.splitlines() if line.strip()]

    def _git_show_file(self, ref: str, rel_path: str) -> str | None:
        return self._run_git("show", f"{ref}:{rel_path}")

    def _run_git(self, *args: str) -> str | None:
        proc = subprocess.run(
            ["git", "-C", str(self._workspace_root), *args],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            logger.debug(
                "git command failed (args=%s, code=%s): %s",
                args,
                proc.returncode,
                proc.stderr.strip(),
            )
            return None
        return proc.stdout


# ------------------------------------------------------------------
# MonitorExecutor
# ------------------------------------------------------------------


class MonitorExecutor:
    """Hybrid event/poll runtime that checks monitors and fires wake events."""

    _FAILURE_THRESHOLD = 5
    _MAX_BACKOFF_EXPONENT = 8

    def __init__(
        self,
        registry: MonitorRegistry,
        checker: ConditionChecker,
        wake_queue: WakeQueue,
    ) -> None:
        self._registry = registry
        self._checker = checker
        self._wake_queue = wake_queue
        self._planner_updates_path = self._registry.coordination_dir / "planner_updates.jsonl"
        self._planner_update_dead_letters_path = (
            self._registry.coordination_dir / "planner_updates_dead_letters.jsonl"
        )

    def run_once(self) -> list[str]:
        """Poll active monitors that are poll-eligible and due."""
        fired: list[str] = []
        for spec in self._registry.get_active():
            try:
                if spec.execution.mode not in {"poll", "hybrid"}:
                    continue
                if self._is_timed_out(spec):
                    self._handle_timeout(spec)
                    continue
                if not self._is_poll_due(spec):
                    continue
                if self._check_and_fire(spec):
                    fired.append(spec.monitor_id)
            except KeyError:
                logger.warning(
                    "Monitor status update failed during poll for monitor %s",
                    spec.monitor_id,
                    exc_info=True,
                )
        return fired

    def on_event(self, event_type: str) -> list[str]:
        """Check monitors that subscribe to *event_type*.

        Returns list of fired monitor_ids.
        """
        fired: list[str] = []
        for spec in self._registry.get_active():
            try:
                if spec.execution.mode not in {"event", "hybrid"}:
                    continue
                if event_type not in spec.execution.event_triggers:
                    continue
                if self._is_timed_out(spec):
                    self._handle_timeout(spec)
                    continue
                if self._check_and_fire(spec):
                    fired.append(spec.monitor_id)
            except KeyError:
                logger.warning(
                    "Monitor status update failed during event=%s for monitor %s",
                    event_type,
                    spec.monitor_id,
                    exc_info=True,
                )
        return fired

    def _check_and_fire(self, spec: MonitorSpec) -> bool:
        """Evaluate condition; fire + enqueue WakeEvent if met.

        Returns True if the monitor fired.
        """
        now = datetime.now(UTC).isoformat()
        try:
            condition = condition_from_dict(spec.condition)
            result = self._checker.check(condition)
        except Exception:
            logger.exception("Monitor %s checker error", spec.monitor_id)
            failures = spec.status.failures + 1
            check_count = spec.status.check_count + 1
            if failures >= self._FAILURE_THRESHOLD:
                self._registry.update_status(
                    spec.monitor_id,
                    "FAILED",
                    failures=failures,
                    last_checked_at=now,
                    check_count=check_count,
                    receipt_event="monitor_failed",
                    receipt_payload={
                        "reason": "checker_exception_threshold",
                        "failure_count": failures,
                    },
                )
                self._emit_planner_update(
                    monitor=spec,
                    event_type="monitor_failed",
                    reason="checker_exception_threshold",
                    extra={
                        "failure_count": failures,
                    },
                )
                return False

            self._registry.update_status(
                spec.monitor_id,
                "ACTIVE",
                failures=failures,
                last_checked_at=now,
                check_count=check_count,
            )
            return False

        check_count = spec.status.check_count + 1

        if result:
            self._registry.update_status(
                spec.monitor_id,
                "FIRED",
                last_checked_at=now,
                check_count=check_count,
                failures=0,
                receipt_event="monitor_fired",
            )
            # IMPL(single-layer): Wake routing is phase-local and forward-only; monitor
            # actions should not encode demotion/backtracking hops to earlier phases.
            wake = WakeEvent(
                monitor_id=spec.monitor_id,
                signal_id=spec.signal_id,
                slice_id=spec.waiting_slice.slice_id,
                layer=spec.waiting_slice.layer,
                reason=f"condition_met:{spec.condition.get('type', 'unknown')}",
                wake_payload=spec.wake.payload,
            )
            self._wake_queue.enqueue(wake)
            return True

        # Condition not met — update check metadata
        self._registry.update_status(
            spec.monitor_id,
            "ACTIVE",
            last_checked_at=now,
            check_count=check_count,
            failures=0,
        )
        return False

    def _is_timed_out(self, spec: MonitorSpec) -> bool:
        """True if the monitor has exceeded its timeout."""
        if not spec.status.created_at:
            return False
        created = self._parse_timestamp(spec.status.created_at)
        if created is None:
            return False
        elapsed = (datetime.now(UTC) - created).total_seconds()
        return elapsed > spec.timeout.timeout_sec

    def _is_poll_due(self, spec: MonitorSpec) -> bool:
        last_checked = self._parse_timestamp(spec.status.last_checked_at)
        if last_checked is None:
            return True
        elapsed = (datetime.now(UTC) - last_checked).total_seconds()
        return elapsed >= self._effective_poll_interval(spec)

    def _effective_poll_interval(self, spec: MonitorSpec) -> int:
        base_interval = max(1, int(spec.execution.poll_interval_sec))
        exponent = min(max(spec.status.failures, 0), self._MAX_BACKOFF_EXPONENT)
        return base_interval * (2**exponent)

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except (ValueError, TypeError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def _handle_timeout(self, spec: MonitorSpec) -> None:
        """Apply the timeout policy."""
        # IMPL(single-layer): Bounds/convergence monitors should use FAIL/ESCALATE
        # timeout policies; RETRY loops conflict with §9.5 bounded-cycle enforcement.
        action = spec.timeout.on_timeout
        if action == "FAIL":
            self._registry.update_status(
                spec.monitor_id,
                "FAILED",
                receipt_event="monitor_failed",
                receipt_payload={"reason": "timeout_fail"},
            )
        elif action == "ESCALATE":
            self._registry.update_status(
                spec.monitor_id,
                "EXPIRED",
                receipt_event="monitor_expired",
                receipt_payload={"reason": "timeout_escalate"},
            )
            self._emit_planner_update(
                monitor=spec,
                event_type="monitor_timeout",
                reason="timeout_escalate",
            )
        elif action == "RETRY":
            # Reset created_at to give it another window
            now = datetime.now(UTC).isoformat()
            self._registry.update_status(
                spec.monitor_id,
                "ACTIVE",
                created_at=now,
                check_count=0,
                failures=0,
                last_checked_at=None,
            )
        else:
            self._registry.update_status(
                spec.monitor_id,
                "EXPIRED",
                receipt_event="monitor_expired",
                receipt_payload={"reason": "timeout_default"},
            )

    def _emit_planner_update(
        self,
        *,
        monitor: MonitorSpec,
        event_type: str,
        reason: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        classification = self._classification_for_event(event_type)
        # IMPL(single-layer): Planner updates are the block/escalation handoff for
        # out-of-authority and timeout paths; include phase/shape diagnostics in
        # extension fields as shape-aware conditions are added.
        event: dict[str, Any] = {
            "type": event_type,
            "event_kind": event_type,
            "event_id": f"mon_{uuid.uuid4().hex[:12]}",
            "created_at": datetime.now(UTC).isoformat(),
            "source": "MONITOR_EXECUTOR",
            "classification": classification,
            "run_id": monitor.run_id,
            "monitor_id": monitor.monitor_id,
            "signal_id": monitor.signal_id,
            "slice_id": monitor.waiting_slice.slice_id,
            "layer": monitor.waiting_slice.layer,
            "condition_type": str(monitor.condition.get("type", "")),
            "reason": reason,
        }
        if extra:
            event.update(extra)
        try:
            self._planner_updates_path.parent.mkdir(parents=True, exist_ok=True)
            with self._planner_updates_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        except OSError as exc:
            logger.warning(
                "Failed to append planner update for monitor %s",
                monitor.monitor_id,
                exc_info=True,
            )
            self._record_planner_update_dead_letter(event=event, error=exc)

    @staticmethod
    def _classification_for_event(event_type: str) -> str:
        if event_type == "monitor_timeout":
            return "MONITOR_TIMEOUT"
        return "MONITOR_FAILED"

    def _record_planner_update_dead_letter(self, *, event: dict[str, Any], error: OSError) -> None:
        record = {
            "failed_at": datetime.now(UTC).isoformat(),
            "error_type": type(error).__name__,
            "error_message": str(error),
            "event": event,
        }
        try:
            self._planner_update_dead_letters_path.parent.mkdir(parents=True, exist_ok=True)
            with self._planner_update_dead_letters_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        except OSError:
            logger.error(
                "Failed to write planner update dead-letter for monitor %s",
                event.get("monitor_id", ""),
                exc_info=True,
            )
