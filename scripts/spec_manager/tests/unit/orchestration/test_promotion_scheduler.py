"""Unit tests for ReactivePromotionScheduler.

Tests bounded-concurrency execution, WAITING support, wake event
re-queuing, max_wait_cycles enforcement, and backwards compatibility.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from spec_manager.orchestration.promotion_loop import (
    PromotionLoop,
    RunContext,
    SliceRef,
    SliceResult,
)
from spec_manager.orchestration.promotion_scheduler import (
    PromotionScheduler,
    ReactivePromotionScheduler,
    SchedulerConfig,
    SchedulerResult,
)

# ======================================================================
# Helpers
# ======================================================================


def _make_slice_ref(slice_id: str) -> SliceRef:
    return SliceRef(slice_id=slice_id, layer="l1", worktree_path="")


def _make_run_context() -> RunContext:
    return RunContext(run_id="run-1", mode="auto", workspace_root="", max_iterations=5)


def _make_slice_result(
    slice_id: str,
    status: str = "COMPLETE",
    iterations: int = 1,
    error: str = "",
    wake_count: int = 0,
) -> SliceResult:
    return SliceResult(
        slice_id=slice_id,
        status=status,
        iterations=iterations,
        error=error,
        wake_count=wake_count,
    )


class FakeWakeQueue:
    """In-memory wake queue for testing."""

    def __init__(self) -> None:
        self._events: dict[str, list[dict]] = {}

    def enqueue_for(self, slice_id: str, event: dict | None = None) -> None:
        self._events.setdefault(slice_id, []).append(event or {"reason": "test"})

    def dequeue(self, slice_id: str) -> list[dict]:
        return self._events.pop(slice_id, [])

    def peek(self, slice_id: str | None = None) -> list[dict]:
        if slice_id is None:
            return [e for evts in self._events.values() for e in evts]
        return list(self._events.get(slice_id, []))


class FakeMonitorExecutor:
    """Fake monitor executor for testing."""

    def __init__(
        self, fire_on_call: int = 0, wake_queue: FakeWakeQueue | None = None, slice_id: str = ""
    ) -> None:
        self._call_count = 0
        self._fire_on_call = fire_on_call
        self._wake_queue = wake_queue
        self._slice_id = slice_id

    def run_once(self) -> list[str]:
        self._call_count += 1
        if self._fire_on_call and self._call_count >= self._fire_on_call:
            if self._wake_queue and self._slice_id:
                self._wake_queue.enqueue_for(self._slice_id)
            return ["monitor-1"]
        return []


# ======================================================================
# SchedulerConfig
# ======================================================================


class TestSchedulerConfig:
    """Test SchedulerConfig defaults and new fields."""

    def test_defaults(self) -> None:
        config = SchedulerConfig()
        assert config.max_parallel == 4
        assert config.priority_by_gaps is True
        assert config.stop_on_first_failure is False
        assert config.integration_lock is True
        assert config.monitor_poll_interval_sec == 20
        assert config.max_wait_cycles == 10
        assert config.max_idle_polls == 50

    def test_custom_values(self) -> None:
        config = SchedulerConfig(
            monitor_poll_interval_sec=5,
            max_wait_cycles=3,
        )
        assert config.monitor_poll_interval_sec == 5
        assert config.max_wait_cycles == 3


# ======================================================================
# SchedulerResult
# ======================================================================


class TestSchedulerResult:
    """Test SchedulerResult with new waiting_slices field."""

    def test_defaults(self) -> None:
        sr = SchedulerResult()
        assert sr.slice_results == []
        assert sr.total_iterations == 0
        assert sr.all_complete is False
        assert sr.blocked_slices == []
        assert sr.failed_slices == []
        assert sr.waiting_slices == []

    def test_summary_includes_waiting(self) -> None:
        sr = SchedulerResult(
            slice_results=[
                _make_slice_result("s1", "COMPLETE"),
                _make_slice_result("s2", "WAITING"),
            ],
            total_iterations=2,
            all_complete=False,
            waiting_slices=["s2"],
        )
        summary = sr.summary()
        assert summary["waiting"] == 1
        assert summary["complete"] == 1
        assert summary["all_complete"] is False

    def test_summary_all_fields(self) -> None:
        sr = SchedulerResult(
            slice_results=[
                _make_slice_result("s1", "COMPLETE", iterations=3),
                _make_slice_result("s2", "BLOCKED", iterations=1),
                _make_slice_result("s3", "FAILED", iterations=1),
                _make_slice_result("s4", "MAX_ITERATIONS", iterations=20),
            ],
            total_iterations=25,
            all_complete=False,
            blocked_slices=["s2"],
            failed_slices=["s3"],
            waiting_slices=[],
        )
        summary = sr.summary()
        assert summary["total_slices"] == 4
        assert summary["complete"] == 1
        assert summary["blocked"] == 1
        assert summary["failed"] == 1
        assert summary["waiting"] == 0
        assert summary["max_iterations"] == 1
        assert summary["total_iterations"] == 25


# ======================================================================
# Backwards compatibility alias
# ======================================================================


class TestBackwardsCompatibility:
    """Test that PromotionScheduler is an alias for ReactivePromotionScheduler."""

    def test_alias_points_to_reactive(self) -> None:
        assert PromotionScheduler is ReactivePromotionScheduler

    def test_can_instantiate_via_alias(self) -> None:
        mock_loop = MagicMock(spec=PromotionLoop)
        scheduler = PromotionScheduler(loop=mock_loop)
        assert isinstance(scheduler, ReactivePromotionScheduler)


# ======================================================================
# Basic run: all slices complete
# ======================================================================


class TestBasicRun:
    """Test basic run scenarios — all slices complete."""

    def test_empty_slice_refs_returns_all_complete(self) -> None:
        mock_loop = MagicMock(spec=PromotionLoop)
        scheduler = ReactivePromotionScheduler(loop=mock_loop)
        result = scheduler.run([], _make_run_context())
        assert result.all_complete is True
        assert result.slice_results == []

    def test_single_slice_sequential(self) -> None:
        mock_loop = MagicMock(spec=PromotionLoop)
        mock_loop.run_slices.return_value = [
            _make_slice_result("s1", "COMPLETE", iterations=3),
        ]
        config = SchedulerConfig(max_parallel=1)
        scheduler = ReactivePromotionScheduler(loop=mock_loop, config=config)

        result = scheduler.run([_make_slice_ref("s1")], _make_run_context())

        assert result.all_complete is True
        assert len(result.slice_results) == 1
        assert result.total_iterations == 3

    def test_parallel_all_complete(self) -> None:
        mock_loop = MagicMock(spec=PromotionLoop)
        mock_loop.run_slice.side_effect = [
            _make_slice_result("s1", "COMPLETE", iterations=2),
            _make_slice_result("s2", "COMPLETE", iterations=3),
        ]
        config = SchedulerConfig(max_parallel=4)
        scheduler = ReactivePromotionScheduler(loop=mock_loop, config=config)

        refs = [_make_slice_ref("s1"), _make_slice_ref("s2")]
        result = scheduler.run(refs, _make_run_context())

        assert result.all_complete is True
        assert len(result.slice_results) == 2
        assert result.total_iterations == 5
        assert mock_loop.run_slice.call_count == 2


# ======================================================================
# WAITING without reactive support → FAILED
# ======================================================================


class TestWaitingNoReactive:
    """WAITING without monitor executor becomes FAILED."""

    def test_waiting_becomes_failed_sequential(self) -> None:
        """WAITING in sequential path (max_parallel=1) becomes FAILED."""
        mock_loop = MagicMock(spec=PromotionLoop)
        mock_loop.run_slices.return_value = [
            _make_slice_result("s1", "WAITING", iterations=1),
        ]

        config = SchedulerConfig(max_parallel=1)
        scheduler = ReactivePromotionScheduler(loop=mock_loop, config=config)

        result = scheduler.run([_make_slice_ref("s1")], _make_run_context())

        assert result.all_complete is False
        assert result.failed_slices == ["s1"]
        assert result.waiting_slices == []
        sr = result.slice_results[0]
        assert sr.status == "FAILED"
        assert "WAITING not supported" in sr.error

    def test_waiting_becomes_failed_parallel(self) -> None:
        """WAITING in parallel path (no monitor) becomes FAILED."""
        mock_loop = MagicMock(spec=PromotionLoop)
        mock_loop.run_slice.return_value = _make_slice_result("s1", "WAITING", iterations=1)

        # max_parallel > number of slices forces parallel path
        config = SchedulerConfig(max_parallel=4)
        scheduler = ReactivePromotionScheduler(loop=mock_loop, config=config)

        refs = [_make_slice_ref("s1"), _make_slice_ref("s2")]
        mock_loop.run_slice.side_effect = [
            _make_slice_result("s1", "WAITING", iterations=1),
            _make_slice_result("s2", "COMPLETE", iterations=1),
        ]

        result = scheduler.run(refs, _make_run_context())

        assert result.all_complete is False
        assert "s1" in result.failed_slices
        assert result.waiting_slices == []


# ======================================================================
# WAITING with reactive support → waiting_slices
# ======================================================================


class TestWaitingWithReactive:
    """WAITING with monitor executor appears in waiting_slices."""

    def test_waiting_slice_tracked(self) -> None:
        """A slice that returns WAITING appears in waiting_slices when
        the monitor never fires and the scheduler exits via max_idle_polls."""
        wake_queue = FakeWakeQueue()
        monitor_exec = FakeMonitorExecutor()

        mock_loop = MagicMock(spec=PromotionLoop)
        mock_loop.run_slice.return_value = _make_slice_result("s1", "WAITING", iterations=1)

        config = SchedulerConfig(
            max_parallel=4,
            monitor_poll_interval_sec=0,  # fast for testing
            max_wait_cycles=100,  # high so we don't hit this
            max_idle_polls=2,  # exit quickly after 2 idle polls
        )
        scheduler = ReactivePromotionScheduler(
            loop=mock_loop,
            config=config,
            monitor_executor=monitor_exec,
            wake_queue=wake_queue,
        )

        result = scheduler.run([_make_slice_ref("s1")], _make_run_context())

        # The slice should end up as WAITING (exited via max_idle_polls)
        assert "s1" in result.waiting_slices


# ======================================================================
# Wake event re-queues waiting slice
# ======================================================================


class TestWakeEventRequeue:
    """Wake event re-queues a waiting slice."""

    def test_wake_requeues_and_completes(self) -> None:
        wake_queue = FakeWakeQueue()
        # The monitor fires on call 1, which enqueues a wake event
        monitor_exec = FakeMonitorExecutor(fire_on_call=1, wake_queue=wake_queue, slice_id="s1")

        call_count = 0

        def mock_run_slice(ref, ctx):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_slice_result("s1", "WAITING", iterations=1)
            return _make_slice_result("s1", "COMPLETE", iterations=1)

        mock_loop = MagicMock(spec=PromotionLoop)
        mock_loop.run_slice.side_effect = mock_run_slice

        config = SchedulerConfig(
            max_parallel=4,
            monitor_poll_interval_sec=0,  # fast
            max_wait_cycles=5,
            max_idle_polls=50,
        )
        scheduler = ReactivePromotionScheduler(
            loop=mock_loop,
            config=config,
            monitor_executor=monitor_exec,
            wake_queue=wake_queue,
        )

        result = scheduler.run([_make_slice_ref("s1")], _make_run_context())

        assert result.all_complete is True
        assert result.waiting_slices == []
        assert mock_loop.run_slice.call_count == 2


# ======================================================================
# Max wait cycles exceeded → FAILED
# ======================================================================


class TestMaxWaitCycles:
    """Slice exceeds max_wait_cycles → FAILED."""

    def test_exceeded_becomes_failed(self) -> None:
        wake_queue = FakeWakeQueue()
        wake_call = 0

        def monitor_run_once():
            nonlocal wake_call
            wake_call += 1
            # Always enqueue a wake event so the slice gets re-queued
            wake_queue.enqueue_for("s1")
            return ["monitor-1"]

        monitor_exec = MagicMock()
        monitor_exec.run_once = monitor_run_once

        mock_loop = MagicMock(spec=PromotionLoop)
        # Always return WAITING
        mock_loop.run_slice.return_value = _make_slice_result("s1", "WAITING", iterations=1)

        config = SchedulerConfig(
            max_parallel=4,
            monitor_poll_interval_sec=0,
            max_wait_cycles=2,
            max_idle_polls=50,
        )
        scheduler = ReactivePromotionScheduler(
            loop=mock_loop,
            config=config,
            monitor_executor=monitor_exec,
            wake_queue=wake_queue,
        )

        result = scheduler.run([_make_slice_ref("s1")], _make_run_context())

        assert result.all_complete is False
        assert "s1" in result.failed_slices
        # Should have been called: initial + re-queued up to max_wait_cycles
        assert mock_loop.run_slice.call_count >= 2


# ======================================================================
# Integration lock still serializes merges
# ======================================================================


class TestIntegrationLock:
    """Integration lock is created when configured."""

    def test_lock_created_by_default(self) -> None:
        mock_loop = MagicMock(spec=PromotionLoop)
        scheduler = ReactivePromotionScheduler(loop=mock_loop)
        assert scheduler._integration_lock is not None

    def test_no_lock_when_disabled(self) -> None:
        mock_loop = MagicMock(spec=PromotionLoop)
        config = SchedulerConfig(integration_lock=False)
        scheduler = ReactivePromotionScheduler(loop=mock_loop, config=config)
        assert scheduler._integration_lock is None


# ======================================================================
# Prioritization
# ======================================================================


class TestPrioritization:
    """Test priority ordering by gap count."""

    def test_sorts_by_gap_count(self) -> None:
        mock_loop = MagicMock(spec=PromotionLoop)
        config = SchedulerConfig(priority_by_gaps=True)
        scheduler = ReactivePromotionScheduler(loop=mock_loop, config=config)

        refs = [_make_slice_ref("low"), _make_slice_ref("high"), _make_slice_ref("mid")]
        gap_counts = {"low": 2, "high": 10, "mid": 5}

        ordered = scheduler._prioritize(refs, gap_counts)
        assert [r.slice_id for r in ordered] == ["high", "mid", "low"]

    def test_preserves_order_when_disabled(self) -> None:
        mock_loop = MagicMock(spec=PromotionLoop)
        config = SchedulerConfig(priority_by_gaps=False)
        scheduler = ReactivePromotionScheduler(loop=mock_loop, config=config)

        refs = [_make_slice_ref("a"), _make_slice_ref("b"), _make_slice_ref("c")]
        ordered = scheduler._prioritize(refs, {"a": 1, "b": 10, "c": 5})
        assert [r.slice_id for r in ordered] == ["a", "b", "c"]

    def test_preserves_order_when_no_gap_counts(self) -> None:
        mock_loop = MagicMock(spec=PromotionLoop)
        config = SchedulerConfig(priority_by_gaps=True)
        scheduler = ReactivePromotionScheduler(loop=mock_loop, config=config)

        refs = [_make_slice_ref("a"), _make_slice_ref("b")]
        ordered = scheduler._prioritize(refs, None)
        assert [r.slice_id for r in ordered] == ["a", "b"]


# ======================================================================
# stop_on_first_failure
# ======================================================================


class TestStopOnFirstFailure:
    """Test stop_on_first_failure cancels remaining slices."""

    def test_cancels_on_failure(self) -> None:
        def mock_run_slice(ref, ctx):
            if ref.slice_id == "s1":
                return _make_slice_result("s1", "FAILED", error="boom")
            # s2 may or may not run depending on thread timing
            return _make_slice_result(ref.slice_id, "COMPLETE")

        mock_loop = MagicMock(spec=PromotionLoop)
        mock_loop.run_slice.side_effect = mock_run_slice

        config = SchedulerConfig(max_parallel=4, stop_on_first_failure=True)
        scheduler = ReactivePromotionScheduler(loop=mock_loop, config=config)

        refs = [_make_slice_ref("s1"), _make_slice_ref("s2")]
        result = scheduler.run(refs, _make_run_context())

        assert result.all_complete is False
        assert "s1" in result.failed_slices


# ======================================================================
# Mixed results: some COMPLETE, some WAITING, some FAILED
# ======================================================================


class TestMixedResults:
    """Test mixed results across multiple slices."""

    def test_mixed_complete_failed(self) -> None:
        mock_loop = MagicMock(spec=PromotionLoop)
        mock_loop.run_slice.side_effect = [
            _make_slice_result("s1", "COMPLETE", iterations=2),
            _make_slice_result("s2", "FAILED", iterations=1, error="crash"),
            _make_slice_result("s3", "BLOCKED", iterations=1),
        ]

        config = SchedulerConfig(max_parallel=4)
        scheduler = ReactivePromotionScheduler(loop=mock_loop, config=config)

        refs = [_make_slice_ref("s1"), _make_slice_ref("s2"), _make_slice_ref("s3")]
        result = scheduler.run(refs, _make_run_context())

        assert result.all_complete is False
        assert "s2" in result.failed_slices
        assert "s3" in result.blocked_slices
        assert result.total_iterations == 4


# ======================================================================
# Aggregate
# ======================================================================


class TestAggregate:
    """Test _aggregate method directly."""

    def test_all_complete(self) -> None:
        mock_loop = MagicMock(spec=PromotionLoop)
        scheduler = ReactivePromotionScheduler(loop=mock_loop)

        results = [
            _make_slice_result("s1", "COMPLETE", iterations=1),
            _make_slice_result("s2", "COMPLETE", iterations=3),
        ]
        agg = scheduler._aggregate(results)

        assert agg.all_complete is True
        assert agg.total_iterations == 4
        assert agg.blocked_slices == []
        assert agg.failed_slices == []
        assert agg.waiting_slices == []

    def test_with_waiting(self) -> None:
        mock_loop = MagicMock(spec=PromotionLoop)
        scheduler = ReactivePromotionScheduler(loop=mock_loop)

        results = [
            _make_slice_result("s1", "COMPLETE"),
            _make_slice_result("s2", "WAITING"),
        ]
        agg = scheduler._aggregate(results, remaining_waiting=["s2"])

        assert agg.all_complete is False
        assert agg.waiting_slices == ["s2"]

    def test_empty_results(self) -> None:
        mock_loop = MagicMock(spec=PromotionLoop)
        scheduler = ReactivePromotionScheduler(loop=mock_loop)

        agg = scheduler._aggregate([])

        # all() of empty is True (vacuously true)
        assert agg.all_complete is True
        assert agg.total_iterations == 0

    def test_identifies_blocked_and_failed(self) -> None:
        mock_loop = MagicMock(spec=PromotionLoop)
        scheduler = ReactivePromotionScheduler(loop=mock_loop)

        results = [
            _make_slice_result("s1", "BLOCKED"),
            _make_slice_result("s2", "FAILED", error="x"),
            _make_slice_result("s3", "COMPLETE"),
        ]
        agg = scheduler._aggregate(results)

        assert agg.blocked_slices == ["s1"]
        assert agg.failed_slices == ["s2"]
        assert agg.all_complete is False


# ======================================================================
# Sequential path with failures
# ======================================================================


class TestSequential:
    """Test sequential execution path."""

    def test_sequential_with_failures(self) -> None:
        mock_loop = MagicMock(spec=PromotionLoop)
        mock_loop.run_slices.return_value = [
            _make_slice_result("s1", "COMPLETE", iterations=2),
            _make_slice_result("s2", "FAILED", iterations=1, error="boom"),
        ]

        config = SchedulerConfig(max_parallel=1)
        scheduler = ReactivePromotionScheduler(loop=mock_loop, config=config)

        refs = [_make_slice_ref("s1"), _make_slice_ref("s2")]
        result = scheduler.run(refs, _make_run_context())

        assert result.all_complete is False
        assert result.failed_slices == ["s2"]


# ======================================================================
# Gap priority ordering affects execution
# ======================================================================


class TestGapPriorityOrdering:
    """Test that gap counts affect execution ordering."""

    def test_priority_ordering_affects_execution(self) -> None:
        mock_loop = MagicMock(spec=PromotionLoop)
        mock_loop.run_slices.return_value = [
            _make_slice_result("high", "COMPLETE"),
            _make_slice_result("low", "COMPLETE"),
        ]

        config = SchedulerConfig(max_parallel=1, priority_by_gaps=True)
        scheduler = ReactivePromotionScheduler(loop=mock_loop, config=config)

        refs = [_make_slice_ref("low"), _make_slice_ref("high")]
        scheduler.run(refs, _make_run_context(), gap_counts={"low": 1, "high": 10})

        actual_call_refs = mock_loop.run_slices.call_args[0][0]
        assert actual_call_refs[0].slice_id == "high"
        assert actual_call_refs[1].slice_id == "low"
