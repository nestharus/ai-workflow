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

from .monitors import (
    ConstraintPresentCondition,
    GitSymbolExistsCondition,
    MonitorCondition,
    MonitorRegistry,
    MonitorSpec,
    WorkItemDoneCondition,
    condition_from_dict,
)
from .wake_queue import WakeEvent, WakeQueue

logger = logging.getLogger(__name__)


class ConstraintLookupStore(Protocol):
    """Constraint store contract needed by ConditionChecker."""

    def load_merged(self, slice_id: str) -> list[Any]:
        """Return merged constraints for a slice."""


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
