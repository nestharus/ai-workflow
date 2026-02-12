"""Tests for orchestration.coordination.monitor_executor."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from spec_manager.orchestration.coordination.monitor_executor import (
    ConditionChecker,
    MonitorExecutor,
)
from spec_manager.orchestration.coordination.monitors import (
    MonitorExecution,
    MonitorRegistry,
    MonitorSpec,
    MonitorStatus,
    MonitorTimeout,
    MonitorWake,
    SliceInfo,
)
from spec_manager.orchestration.coordination.wake_queue import WakeQueue

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


@dataclass
class _FakeWorkItem:
    work_item_id: str
    status: str


class _FakeWorkItemStore:
    """Minimal stand-in for WorkItemStore for testing."""

    def __init__(self) -> None:
        self._items: dict[str, _FakeWorkItem] = {}

    def add(self, item: _FakeWorkItem) -> None:
        self._items[item.work_item_id] = item

    def get(self, work_item_id: str) -> _FakeWorkItem | None:
        return self._items.get(work_item_id)


def _make_spec(
    monitor_id: str = "m1",
    condition: dict | None = None,
    slice_id: str = "risk-engine",
    layer: str = "L1",
    signal_id: str = "sig_1",
    timeout_sec: int = 7200,
    on_timeout: str = "ESCALATE",
    event_triggers: list[str] | None = None,
    created_at: str = "",
) -> MonitorSpec:
    if condition is None:
        condition = {"type": "work_item_done", "work_item_id": "wi_1"}
    if not created_at:
        created_at = datetime.now(UTC).isoformat()
    return MonitorSpec(
        monitor_id=monitor_id,
        run_id="run_1",
        waiting_slice=SliceInfo(layer=layer, slice_id=slice_id),
        signal_id=signal_id,
        condition=condition,
        execution=MonitorExecution(
            mode="hybrid",
            event_triggers=event_triggers or [],
        ),
        timeout=MonitorTimeout(
            timeout_sec=timeout_sec,
            on_timeout=on_timeout,  # type: ignore[arg-type]
        ),
        wake=MonitorWake(payload={"resume_step": "IMPLEMENT"}),
        status=MonitorStatus(
            state="ACTIVE",
            created_at=created_at,
        ),
    )


# ------------------------------------------------------------------
# ConditionChecker tests
# ------------------------------------------------------------------


class TestConditionCheckerWorkItemDone:
    def test_true_when_status_matches(self, tmp_path: Path) -> None:
        store = _FakeWorkItemStore()
        store.add(_FakeWorkItem("wi_1", "MERGED"))
        checker = ConditionChecker(tmp_path, work_item_store=store)

        from spec_manager.orchestration.coordination.monitors import WorkItemDoneCondition

        cond = WorkItemDoneCondition(work_item_id="wi_1", required_status="MERGED")
        assert checker.check(cond) is True

    def test_false_when_status_differs(self, tmp_path: Path) -> None:
        store = _FakeWorkItemStore()
        store.add(_FakeWorkItem("wi_1", "IN_PROGRESS"))
        checker = ConditionChecker(tmp_path, work_item_store=store)

        from spec_manager.orchestration.coordination.monitors import WorkItemDoneCondition

        cond = WorkItemDoneCondition(work_item_id="wi_1", required_status="MERGED")
        assert checker.check(cond) is False

    def test_false_when_item_missing(self, tmp_path: Path) -> None:
        store = _FakeWorkItemStore()
        checker = ConditionChecker(tmp_path, work_item_store=store)

        from spec_manager.orchestration.coordination.monitors import WorkItemDoneCondition

        cond = WorkItemDoneCondition(work_item_id="missing", required_status="MERGED")
        assert checker.check(cond) is False

    def test_false_when_no_store(self, tmp_path: Path) -> None:
        checker = ConditionChecker(tmp_path, work_item_store=None)

        from spec_manager.orchestration.coordination.monitors import WorkItemDoneCondition

        cond = WorkItemDoneCondition(work_item_id="wi_1")
        assert checker.check(cond) is False


class TestConditionCheckerConstraintPresent:
    def test_true_when_file_exists(self, tmp_path: Path) -> None:
        constraint_dir = tmp_path / "analysis" / "constraints"
        constraint_dir.mkdir(parents=True)
        (constraint_dir / "no_orm.yaml").write_text("constraint: true")

        checker = ConditionChecker(tmp_path)

        from spec_manager.orchestration.coordination.monitors import ConstraintPresentCondition

        cond = ConstraintPresentCondition(constraint_key="no_orm")
        assert checker.check(cond) is True

    def test_false_when_file_absent(self, tmp_path: Path) -> None:
        constraint_dir = tmp_path / "analysis" / "constraints"
        constraint_dir.mkdir(parents=True)

        checker = ConditionChecker(tmp_path)

        from spec_manager.orchestration.coordination.monitors import ConstraintPresentCondition

        cond = ConstraintPresentCondition(constraint_key="no_orm")
        assert checker.check(cond) is False

    def test_false_when_dir_absent(self, tmp_path: Path) -> None:
        checker = ConditionChecker(tmp_path)

        from spec_manager.orchestration.coordination.monitors import ConstraintPresentCondition

        cond = ConstraintPresentCondition(constraint_key="no_orm")
        assert checker.check(cond) is False

    def test_false_when_key_empty(self, tmp_path: Path) -> None:
        checker = ConditionChecker(tmp_path)

        from spec_manager.orchestration.coordination.monitors import ConstraintPresentCondition

        cond = ConstraintPresentCondition(constraint_key="")
        assert checker.check(cond) is False

    def test_uses_load_merged_when_available(self, tmp_path: Path) -> None:
        """Verify that ConditionChecker uses load_merged method when available."""
        from dataclasses import dataclass

        @dataclass
        class _MockConstraint:
            constraint_id: str

        class _MockConstraintsStoreWithLoadMerged:
            """Mock store that tracks which method was called."""

            def __init__(self) -> None:
                self.load_merged_called = False
                self.load_called = False
                self._constraints = [
                    _MockConstraint(constraint_id="CON-1"),
                    _MockConstraint(constraint_id="CON-2"),
                ]

            def load_merged(self, slice_id: str) -> list:
                self.load_merged_called = True
                return self._constraints

            def load(self, slice_id: str) -> list:
                self.load_called = True
                return self._constraints

        store = _MockConstraintsStoreWithLoadMerged()
        checker = ConditionChecker(tmp_path, constraints_store=store)

        from spec_manager.orchestration.coordination.monitors import ConstraintPresentCondition

        # Check for an existing constraint
        cond = ConstraintPresentCondition(
            constraint_id="CON-1",
            slice_id="my_slice",
        )
        result = checker.check(cond)

        # Verify load_merged was called, not load
        assert result is True
        assert store.load_merged_called is True
        assert store.load_called is False

    def test_falls_back_to_load_when_load_merged_not_available(self, tmp_path: Path) -> None:
        """Verify fallback to load() when load_merged() doesn't exist."""
        from dataclasses import dataclass

        @dataclass
        class _MockConstraint:
            constraint_id: str

        class _MockConstraintsStoreWithoutLoadMerged:
            """Mock store without load_merged method."""

            def __init__(self) -> None:
                self.load_called = False
                self._constraints = [
                    _MockConstraint(constraint_id="CON-3"),
                ]

            def load(self, slice_id: str) -> list:
                self.load_called = True
                return self._constraints

        store = _MockConstraintsStoreWithoutLoadMerged()
        checker = ConditionChecker(tmp_path, constraints_store=store)

        from spec_manager.orchestration.coordination.monitors import ConstraintPresentCondition

        cond = ConstraintPresentCondition(
            constraint_id="CON-3",
            slice_id="my_slice",
        )
        result = checker.check(cond)

        # Verify load was called as fallback
        assert result is True
        assert store.load_called is True


class TestConditionCheckerCompound:
    def test_or_any_true(self, tmp_path: Path) -> None:
        store = _FakeWorkItemStore()
        store.add(_FakeWorkItem("wi_1", "MERGED"))
        checker = ConditionChecker(tmp_path, work_item_store=store)

        from spec_manager.orchestration.coordination.monitors import CompoundCondition

        cond = CompoundCondition(
            operator="OR",
            conditions=[
                {"type": "work_item_done", "work_item_id": "wi_1", "required_status": "MERGED"},
                {"type": "work_item_done", "work_item_id": "missing", "required_status": "MERGED"},
            ],
        )
        assert checker.check(cond) is True

    def test_and_all_must_be_true(self, tmp_path: Path) -> None:
        store = _FakeWorkItemStore()
        store.add(_FakeWorkItem("wi_1", "MERGED"))
        checker = ConditionChecker(tmp_path, work_item_store=store)

        from spec_manager.orchestration.coordination.monitors import CompoundCondition

        cond = CompoundCondition(
            operator="AND",
            conditions=[
                {"type": "work_item_done", "work_item_id": "wi_1", "required_status": "MERGED"},
                {"type": "work_item_done", "work_item_id": "missing", "required_status": "MERGED"},
            ],
        )
        assert checker.check(cond) is False

    def test_and_all_true(self, tmp_path: Path) -> None:
        store = _FakeWorkItemStore()
        store.add(_FakeWorkItem("wi_1", "MERGED"))
        store.add(_FakeWorkItem("wi_2", "MERGED"))
        checker = ConditionChecker(tmp_path, work_item_store=store)

        from spec_manager.orchestration.coordination.monitors import CompoundCondition

        cond = CompoundCondition(
            operator="AND",
            conditions=[
                {"type": "work_item_done", "work_item_id": "wi_1", "required_status": "MERGED"},
                {"type": "work_item_done", "work_item_id": "wi_2", "required_status": "MERGED"},
            ],
        )
        assert checker.check(cond) is True

    def test_empty_compound_is_false(self, tmp_path: Path) -> None:
        checker = ConditionChecker(tmp_path)

        from spec_manager.orchestration.coordination.monitors import CompoundCondition

        cond = CompoundCondition(operator="OR", conditions=[])
        assert checker.check(cond) is False


class TestConditionCheckerGitSymbolExists:
    def test_true_when_symbol_found(self, tmp_path: Path) -> None:
        lib_dir = tmp_path / "libraries"
        lib_dir.mkdir()
        (lib_dir / "risk.py").write_text("class RiskEngine:\n    def check_exposure(self): ...\n")

        checker = ConditionChecker(tmp_path)

        from spec_manager.orchestration.coordination.monitors import GitSymbolExistsCondition

        cond = GitSymbolExistsCondition(
            ref="",
            file_glob="libraries/*.py",
            symbol_fqn="check_exposure",
        )
        assert checker.check(cond) is True

    def test_false_when_symbol_not_found(self, tmp_path: Path) -> None:
        lib_dir = tmp_path / "libraries"
        lib_dir.mkdir()
        (lib_dir / "risk.py").write_text("class RiskEngine:\n    pass\n")

        checker = ConditionChecker(tmp_path)

        from spec_manager.orchestration.coordination.monitors import GitSymbolExistsCondition

        cond = GitSymbolExistsCondition(
            ref="",
            file_glob="libraries/*.py",
            symbol_fqn="check_exposure",
        )
        assert checker.check(cond) is False

    def test_false_when_empty_symbol(self, tmp_path: Path) -> None:
        checker = ConditionChecker(tmp_path)

        from spec_manager.orchestration.coordination.monitors import GitSymbolExistsCondition

        cond = GitSymbolExistsCondition(symbol_fqn="")
        assert checker.check(cond) is False


class TestConditionCheckerSliceMerged:
    def test_true_when_marker_exists(self, tmp_path: Path) -> None:
        marker_dir = tmp_path / "slices" / "auth-lib"
        marker_dir.mkdir(parents=True)
        (marker_dir / "merged_L1").write_text("")

        checker = ConditionChecker(tmp_path)

        from spec_manager.orchestration.coordination.monitors import SliceMergedCondition

        cond = SliceMergedCondition(provider_slice_id="auth-lib", layer="L1")
        assert checker.check(cond) is True

    def test_false_when_marker_absent(self, tmp_path: Path) -> None:
        checker = ConditionChecker(tmp_path)

        from spec_manager.orchestration.coordination.monitors import SliceMergedCondition

        cond = SliceMergedCondition(provider_slice_id="auth-lib", layer="L1")
        assert checker.check(cond) is False


# ------------------------------------------------------------------
# MonitorExecutor tests
# ------------------------------------------------------------------


class TestMonitorExecutorRunOnce:
    def test_fires_ready_monitors(self, tmp_path: Path) -> None:
        coord_dir = tmp_path / "coord"
        store = _FakeWorkItemStore()
        store.add(_FakeWorkItem("wi_1", "MERGED"))

        reg = MonitorRegistry(coord_dir)
        spec = _make_spec(
            monitor_id="m1",
            condition={
                "type": "work_item_done",
                "work_item_id": "wi_1",
                "required_status": "MERGED",
            },
        )
        reg.register(spec)

        checker = ConditionChecker(tmp_path, work_item_store=store)
        wake_q = WakeQueue(coord_dir)
        executor = MonitorExecutor(reg, checker, wake_q)

        fired = executor.run_once()

        assert fired == ["m1"]
        loaded = reg.get("m1")
        assert loaded is not None
        assert loaded.status.state == "FIRED"

        # Verify wake event enqueued
        events = wake_q.peek()
        assert len(events) == 1
        assert events[0].monitor_id == "m1"
        assert events[0].signal_id == "sig_1"
        assert events[0].slice_id == "risk-engine"

    def test_does_not_fire_unmet_condition(self, tmp_path: Path) -> None:
        coord_dir = tmp_path / "coord"
        store = _FakeWorkItemStore()
        store.add(_FakeWorkItem("wi_1", "IN_PROGRESS"))

        reg = MonitorRegistry(coord_dir)
        spec = _make_spec(
            monitor_id="m1",
            condition={
                "type": "work_item_done",
                "work_item_id": "wi_1",
                "required_status": "MERGED",
            },
        )
        reg.register(spec)

        checker = ConditionChecker(tmp_path, work_item_store=store)
        wake_q = WakeQueue(coord_dir)
        executor = MonitorExecutor(reg, checker, wake_q)

        fired = executor.run_once()

        assert fired == []
        loaded = reg.get("m1")
        assert loaded is not None
        assert loaded.status.state == "ACTIVE"
        assert loaded.status.check_count == 1

    def test_multiple_monitors(self, tmp_path: Path) -> None:
        coord_dir = tmp_path / "coord"
        store = _FakeWorkItemStore()
        store.add(_FakeWorkItem("wi_1", "MERGED"))
        store.add(_FakeWorkItem("wi_2", "IN_PROGRESS"))

        reg = MonitorRegistry(coord_dir)
        reg.register(
            _make_spec(
                monitor_id="m1",
                signal_id="sig_1",
                condition={
                    "type": "work_item_done",
                    "work_item_id": "wi_1",
                    "required_status": "MERGED",
                },
            )
        )
        reg.register(
            _make_spec(
                monitor_id="m2",
                signal_id="sig_2",
                condition={
                    "type": "work_item_done",
                    "work_item_id": "wi_2",
                    "required_status": "MERGED",
                },
            )
        )

        checker = ConditionChecker(tmp_path, work_item_store=store)
        wake_q = WakeQueue(coord_dir)
        executor = MonitorExecutor(reg, checker, wake_q)

        fired = executor.run_once()

        assert fired == ["m1"]


class TestMonitorExecutorTimeout:
    def test_escalate_on_timeout(self, tmp_path: Path) -> None:
        coord_dir = tmp_path / "coord"
        past = (datetime.now(UTC) - timedelta(hours=3)).isoformat()

        reg = MonitorRegistry(coord_dir)
        spec = _make_spec(
            monitor_id="m_timeout",
            timeout_sec=3600,
            on_timeout="ESCALATE",
            created_at=past,
        )
        reg.register(spec)

        checker = ConditionChecker(tmp_path)
        wake_q = WakeQueue(coord_dir)
        executor = MonitorExecutor(reg, checker, wake_q)

        fired = executor.run_once()

        assert fired == []
        loaded = reg.get("m_timeout")
        assert loaded is not None
        assert loaded.status.state == "EXPIRED"

    def test_fail_on_timeout(self, tmp_path: Path) -> None:
        coord_dir = tmp_path / "coord"
        past = (datetime.now(UTC) - timedelta(hours=3)).isoformat()

        reg = MonitorRegistry(coord_dir)
        spec = _make_spec(
            monitor_id="m_fail",
            timeout_sec=3600,
            on_timeout="FAIL",
            created_at=past,
        )
        reg.register(spec)

        checker = ConditionChecker(tmp_path)
        wake_q = WakeQueue(coord_dir)
        executor = MonitorExecutor(reg, checker, wake_q)

        fired = executor.run_once()

        assert fired == []
        loaded = reg.get("m_fail")
        assert loaded is not None
        assert loaded.status.state == "FAILED"

    def test_retry_on_timeout_resets(self, tmp_path: Path) -> None:
        coord_dir = tmp_path / "coord"
        past = (datetime.now(UTC) - timedelta(hours=3)).isoformat()

        reg = MonitorRegistry(coord_dir)
        spec = _make_spec(
            monitor_id="m_retry",
            timeout_sec=3600,
            on_timeout="RETRY",
            created_at=past,
        )
        reg.register(spec)

        checker = ConditionChecker(tmp_path)
        wake_q = WakeQueue(coord_dir)
        executor = MonitorExecutor(reg, checker, wake_q)

        fired = executor.run_once()

        assert fired == []
        loaded = reg.get("m_retry")
        assert loaded is not None
        # Should stay ACTIVE with reset counters
        assert loaded.status.state == "ACTIVE"
        assert loaded.status.check_count == 0


class TestMonitorExecutorCheckerFailures:
    def test_increments_failure_count(self, tmp_path: Path) -> None:
        coord_dir = tmp_path / "coord"

        reg = MonitorRegistry(coord_dir)
        spec = _make_spec(
            monitor_id="m_err",
            condition={"type": "work_item_done", "work_item_id": "wi_1"},
        )
        reg.register(spec)

        # Checker with no store will not raise, but let's use a bad condition type
        # that will cause condition_from_dict to raise
        spec2 = _make_spec(
            monitor_id="m_bad",
            condition={"type": "nonexistent_type"},
        )
        reg.register(spec2)

        checker = ConditionChecker(tmp_path)
        wake_q = WakeQueue(coord_dir)
        executor = MonitorExecutor(reg, checker, wake_q)

        fired = executor.run_once()

        # m_bad should have incremented failure count
        loaded = reg.get("m_bad")
        assert loaded is not None
        assert loaded.status.state == "ACTIVE"
        assert loaded.status.failures == 1
        assert loaded.status.check_count == 1
        assert "m_bad" not in fired


class TestMonitorExecutorOnEvent:
    def test_checks_only_subscribed_monitors(self, tmp_path: Path) -> None:
        coord_dir = tmp_path / "coord"
        store = _FakeWorkItemStore()
        store.add(_FakeWorkItem("wi_1", "MERGED"))
        store.add(_FakeWorkItem("wi_2", "MERGED"))

        reg = MonitorRegistry(coord_dir)
        # m1 subscribes to SLICE_MERGED
        reg.register(
            _make_spec(
                monitor_id="m1",
                signal_id="sig_1",
                event_triggers=["SLICE_MERGED"],
                condition={
                    "type": "work_item_done",
                    "work_item_id": "wi_1",
                    "required_status": "MERGED",
                },
            )
        )
        # m2 does not subscribe to SLICE_MERGED
        reg.register(
            _make_spec(
                monitor_id="m2",
                signal_id="sig_2",
                event_triggers=["GIT_DIRTY_ADVANCED"],
                condition={
                    "type": "work_item_done",
                    "work_item_id": "wi_2",
                    "required_status": "MERGED",
                },
            )
        )

        checker = ConditionChecker(tmp_path, work_item_store=store)
        wake_q = WakeQueue(coord_dir)
        executor = MonitorExecutor(reg, checker, wake_q)

        fired = executor.on_event("SLICE_MERGED")

        # Only m1 should have been checked and fired
        assert fired == ["m1"]

        # m2 should still be ACTIVE
        m2 = reg.get("m2")
        assert m2 is not None
        assert m2.status.state == "ACTIVE"
