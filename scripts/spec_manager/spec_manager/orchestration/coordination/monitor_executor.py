"""Hybrid event/poll runtime for JIT monitors.

The MonitorExecutor checks active monitors against current workspace
state and fires wake events when conditions are met.  ConditionChecker
is a read-only evaluator for individual condition types.
"""

from __future__ import annotations

import fnmatch
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .monitors import (
    CompoundCondition,
    ConstraintPresentCondition,
    GitSymbolExistsCondition,
    MonitorCondition,
    MonitorRegistry,
    MonitorSpec,
    SliceMergedCondition,
    WorkItemDoneCondition,
    condition_from_dict,
)
from .wake_queue import WakeEvent, WakeQueue

logger = logging.getLogger(__name__)


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
        constraints_store: Any = None,
    ) -> None:
        self._workspace_root = workspace_root
        self._work_item_store = work_item_store
        self._constraints_store = constraints_store

    def check(self, condition: MonitorCondition) -> bool:
        """Dispatch to the appropriate checker."""
        if isinstance(condition, GitSymbolExistsCondition):
            return self._check_git_symbol_exists(condition)
        if isinstance(condition, WorkItemDoneCondition):
            return self._check_work_item_done(condition)
        if isinstance(condition, ConstraintPresentCondition):
            return self._check_constraint_present(condition)
        if isinstance(condition, SliceMergedCondition):
            return self._check_slice_merged(condition)
        if isinstance(condition, CompoundCondition):
            return self._check_compound(condition)
        return False

    def _check_git_symbol_exists(self, cond: GitSymbolExistsCondition) -> bool:
        """Scan files matching file_glob for symbol_fqn string.

        For now this is a simple filesystem scan; a future version can
        use ``git show {ref}:{file}`` to check at a specific ref.
        """
        from spec_manager.core.language import source_rglob

        if not cond.symbol_fqn:
            return False
        root = self._workspace_root
        matched_files: list[Path] = []
        if cond.file_glob:
            for p in root.rglob("*"):
                if p.is_file() and fnmatch.fnmatch(str(p.relative_to(root)), cond.file_glob):
                    matched_files.append(p)
        else:
            matched_files = [p for p in source_rglob(root) if p.is_file()]

        for f in matched_files:
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if cond.symbol_fqn in content:
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
            if hasattr(self._constraints_store, "load_merged"):
                constraints = self._constraints_store.load_merged(cond.slice_id)
            else:
                constraints = self._constraints_store.load(cond.slice_id)
            return any(c.constraint_id == cond.constraint_id for c in constraints)

        # Fallback: file-existence check
        if not cond.constraint_key:
            return False
        constraint_dir = self._workspace_root / cond.constraint_dir
        if not constraint_dir.exists():
            return False
        return any(cond.constraint_key in p.name for p in constraint_dir.iterdir())

    def _check_slice_merged(self, cond: SliceMergedCondition) -> bool:
        """Check if the provider slice's merge marker exists."""
        if not cond.provider_slice_id:
            return False
        # Convention: merge marker at slices/<id>/merged_<layer>
        marker = self._workspace_root / "slices" / cond.provider_slice_id / f"merged_{cond.layer}"
        return marker.exists()

    def _check_compound(self, cond: CompoundCondition) -> bool:
        """Evaluate AND/OR over sub-conditions."""
        if not cond.conditions:
            return False
        sub_results: list[bool] = []
        for sub_dict in cond.conditions:
            try:
                sub_cond = condition_from_dict(sub_dict)
                sub_results.append(self.check(sub_cond))
            except (ValueError, KeyError):
                sub_results.append(False)

        if cond.operator == "AND":
            return all(sub_results)
        return any(sub_results)


# ------------------------------------------------------------------
# MonitorExecutor
# ------------------------------------------------------------------


class MonitorExecutor:
    """Hybrid event/poll runtime that checks monitors and fires wake events."""

    def __init__(
        self,
        registry: MonitorRegistry,
        checker: ConditionChecker,
        wake_queue: WakeQueue,
    ) -> None:
        self._registry = registry
        self._checker = checker
        self._wake_queue = wake_queue

    def run_once(self) -> list[str]:
        """Check all active monitors.  Return list of fired monitor_ids."""
        fired: list[str] = []
        for spec in self._registry.get_active():
            if self._is_timed_out(spec):
                self._handle_timeout(spec)
                continue
            if self._check_and_fire(spec):
                fired.append(spec.monitor_id)
        return fired

    def on_event(self, event_type: str) -> list[str]:
        """Check monitors that subscribe to *event_type*.

        Returns list of fired monitor_ids.
        """
        fired: list[str] = []
        for spec in self._registry.get_active():
            if event_type in spec.execution.event_triggers:
                if self._is_timed_out(spec):
                    self._handle_timeout(spec)
                    continue
                if self._check_and_fire(spec):
                    fired.append(spec.monitor_id)
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
            spec.status.failures += 1
            spec.status.last_checked_at = now
            spec.status.check_count += 1
            self._registry.update_status(
                spec.monitor_id,
                "ACTIVE",
                failures=spec.status.failures,
                last_checked_at=now,
                check_count=spec.status.check_count,
            )
            return False

        spec.status.last_checked_at = now
        spec.status.check_count += 1

        if result:
            self._registry.fire(spec.monitor_id)
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
            check_count=spec.status.check_count,
        )
        return False

    def _is_timed_out(self, spec: MonitorSpec) -> bool:
        """True if the monitor has exceeded its timeout."""
        if not spec.status.created_at:
            return False
        try:
            created = datetime.fromisoformat(spec.status.created_at)
            elapsed = (datetime.now(UTC) - created).total_seconds()
            return elapsed > spec.timeout.timeout_sec
        except (ValueError, TypeError):
            return False

    def _handle_timeout(self, spec: MonitorSpec) -> None:
        """Apply the timeout policy."""
        action = spec.timeout.on_timeout
        if action == "FAIL":
            self._registry.update_status(spec.monitor_id, "FAILED")
        elif action == "ESCALATE":
            self._registry.update_status(spec.monitor_id, "EXPIRED")
        elif action == "RETRY":
            # Reset created_at to give it another window
            now = datetime.now(UTC).isoformat()
            self._registry.update_status(
                spec.monitor_id,
                "ACTIVE",
                created_at=now,
                check_count=0,
                failures=0,
            )
        else:
            self._registry.update_status(spec.monitor_id, "EXPIRED")
