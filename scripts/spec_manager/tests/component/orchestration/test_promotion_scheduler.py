"""Component tests for orchestration.promotion_scheduler module.

Tests ReactivePromotionScheduler bounded-concurrency execution, SchedulerConfig,
SchedulerResult, priority ordering, and aggregate result computation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest
from spec_manager.orchestration.promotion_loop import (
    PromotionLoop,
    RunContext,
    SliceRef,
    SliceResult,
)
from spec_manager.orchestration.promotion_scheduler import (
    ReactivePromotionScheduler,
    SchedulerConfig,
    SchedulerResult,
)

# ======================================================================
# Helpers
# ======================================================================


def _make_slice_ref(slice_id: str) -> SliceRef:
    """Create a SliceRef with a given slice_id."""
    return SliceRef(slice_id=slice_id, layer="l1", worktree_path="")


def _make_run_context() -> RunContext:
    """Create a standard RunContext for testing."""
    return RunContext(run_id="run-1", mode="auto", workspace_root="", max_iterations=5)


def _make_slice_result(
    slice_id: str,
    status: str = "COMPLETE",
    iterations: int = 1,
    error: str = "",
) -> SliceResult:
    """Create a SliceResult with given parameters."""
    return SliceResult(
        slice_id=slice_id,
        status=status,
        iterations=iterations,
        error=error,
    )


# ======================================================================
# SchedulerResult
# ======================================================================


class TestSchedulerResult:
    """Test SchedulerResult dataclass and summary()."""

    def test_defaults(self) -> None:
        """SchedulerResult has sensible defaults."""
        sr = SchedulerResult()
        assert sr.slice_results == []
        assert sr.total_iterations == 0
        assert sr.all_complete is False
        assert sr.blocked_slices == []
        assert sr.failed_slices == []

    def test_summary_returns_correct_counts(self) -> None:
        """summary() returns correct counts for all statuses."""
        sr = SchedulerResult(
            slice_results=[
                _make_slice_result("s1", "COMPLETE", iterations=3),
                _make_slice_result("s2", "COMPLETE", iterations=2),
                _make_slice_result("s3", "BLOCKED", iterations=1),
                _make_slice_result("s4", "FAILED", iterations=1),
                _make_slice_result("s5", "MAX_ITERATIONS", iterations=20),
            ],
            total_iterations=27,
            all_complete=False,
            blocked_slices=["s3"],
            failed_slices=["s4"],
        )

        summary = sr.summary()

        assert summary["total_slices"] == 5
        assert summary["complete"] == 2
        assert summary["blocked"] == 1
        assert summary["failed"] == 1
        assert summary["max_iterations"] == 1
        assert summary["total_iterations"] == 27
        assert summary["all_complete"] is False

    def test_summary_all_complete(self) -> None:
        """summary() shows all_complete=True when all slices complete."""
        sr = SchedulerResult(
            slice_results=[
                _make_slice_result("s1", "COMPLETE"),
                _make_slice_result("s2", "COMPLETE"),
            ],
            total_iterations=2,
            all_complete=True,
        )

        summary = sr.summary()
        assert summary["all_complete"] is True
        assert summary["complete"] == 2
        assert summary["blocked"] == 0
        assert summary["failed"] == 0

    def test_summary_empty(self) -> None:
        """summary() handles empty result set."""
        sr = SchedulerResult()
        summary = sr.summary()
        assert summary["total_slices"] == 0
        assert summary["complete"] == 0


# ======================================================================
# SchedulerConfig
# ======================================================================


class TestSchedulerConfig:
    """Test SchedulerConfig defaults."""

    def test_defaults(self) -> None:
        """SchedulerConfig has expected defaults."""
        config = SchedulerConfig()
        assert config.max_parallel == 4
        assert config.priority_by_gaps is True
        assert config.stop_on_first_failure is False
        assert config.integration_lock is True


# ======================================================================
# ReactivePromotionScheduler.run() with empty slices
# ======================================================================


class TestPromotionSchedulerRunEmpty:
    """Test ReactivePromotionScheduler.run() with empty slice_refs."""

    def test_empty_slice_refs_returns_all_complete(self) -> None:
        """run() with empty slice_refs returns all_complete=True."""
        mock_loop = MagicMock(spec=PromotionLoop)
        scheduler = ReactivePromotionScheduler(loop=mock_loop)

        result = scheduler.run([], _make_run_context())

        assert result.all_complete is True
        assert result.slice_results == []
        assert result.total_iterations == 0
        mock_loop.run_slice.assert_not_called()
        mock_loop.run_slices.assert_not_called()


# ======================================================================
# ReactivePromotionScheduler.run() with single slice
# ======================================================================


class TestPromotionSchedulerRunSingle:
    """Test ReactivePromotionScheduler.run() with a single slice."""

    def test_single_slice_delegates_to_run_slices(self) -> None:
        """run() with single slice delegates to loop.run_slices() (sequential)."""
        mock_loop = MagicMock(spec=PromotionLoop)
        mock_loop.run_slices.return_value = [
            _make_slice_result("s1", "COMPLETE", iterations=3),
        ]

        config = SchedulerConfig(max_parallel=1)
        scheduler = ReactivePromotionScheduler(loop=mock_loop, config=config)

        refs = [_make_slice_ref("s1")]
        result = scheduler.run(refs, _make_run_context())

        assert result.all_complete is True
        assert len(result.slice_results) == 1
        assert result.slice_results[0].slice_id == "s1"
        assert result.total_iterations == 3


# ======================================================================
# ReactivePromotionScheduler.run() sequential (max_parallel=1)
# ======================================================================


class TestPromotionSchedulerRunSequential:
    """Test ReactivePromotionScheduler.run() with max_parallel=1."""

    def test_runs_sequentially(self) -> None:
        """run() with max_parallel=1 calls run_slices (sequential path)."""
        mock_loop = MagicMock(spec=PromotionLoop)
        mock_loop.run_slices.return_value = [
            _make_slice_result("s1", "COMPLETE", iterations=2),
            _make_slice_result("s2", "COMPLETE", iterations=3),
        ]

        config = SchedulerConfig(max_parallel=1)
        scheduler = ReactivePromotionScheduler(loop=mock_loop, config=config)

        refs = [_make_slice_ref("s1"), _make_slice_ref("s2")]
        result = scheduler.run(refs, _make_run_context())

        assert result.all_complete is True
        assert len(result.slice_results) == 2
        assert result.total_iterations == 5
        mock_loop.run_slices.assert_called_once()

    def test_sequential_with_failures(self) -> None:
        """run() sequential identifies failed slices in aggregate."""
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
# ReactivePromotionScheduler._prioritize()
# ======================================================================


class TestPromotionSchedulerPrioritize:
    """Test ReactivePromotionScheduler._prioritize() sorting."""

    def test_sorts_by_gap_count_when_enabled(self) -> None:
        """_prioritize() sorts slices by gap count (highest first)."""
        mock_loop = MagicMock(spec=PromotionLoop)
        config = SchedulerConfig(priority_by_gaps=True)
        scheduler = ReactivePromotionScheduler(loop=mock_loop, config=config)

        refs = [
            _make_slice_ref("low"),
            _make_slice_ref("high"),
            _make_slice_ref("mid"),
        ]
        gap_counts = {"low": 2, "high": 10, "mid": 5}

        ordered = scheduler._prioritize(refs, gap_counts)

        assert [r.slice_id for r in ordered] == ["high", "mid", "low"]

    def test_preserves_order_when_disabled(self) -> None:
        """_prioritize() preserves original order when priority_by_gaps=False."""
        mock_loop = MagicMock(spec=PromotionLoop)
        config = SchedulerConfig(priority_by_gaps=False)
        scheduler = ReactivePromotionScheduler(loop=mock_loop, config=config)

        refs = [
            _make_slice_ref("first"),
            _make_slice_ref("second"),
            _make_slice_ref("third"),
        ]
        gap_counts = {"first": 1, "second": 10, "third": 5}

        ordered = scheduler._prioritize(refs, gap_counts)

        assert [r.slice_id for r in ordered] == ["first", "second", "third"]

    def test_preserves_order_when_no_gap_counts(self) -> None:
        """_prioritize() preserves order when gap_counts is None."""
        mock_loop = MagicMock(spec=PromotionLoop)
        config = SchedulerConfig(priority_by_gaps=True)
        scheduler = ReactivePromotionScheduler(loop=mock_loop, config=config)

        refs = [_make_slice_ref("a"), _make_slice_ref("b")]
        ordered = scheduler._prioritize(refs, None)

        assert [r.slice_id for r in ordered] == ["a", "b"]

    def test_missing_gap_count_defaults_to_zero(self) -> None:
        """_prioritize() treats missing slice IDs as 0 gap count."""
        mock_loop = MagicMock(spec=PromotionLoop)
        config = SchedulerConfig(priority_by_gaps=True)
        scheduler = ReactivePromotionScheduler(loop=mock_loop, config=config)

        refs = [_make_slice_ref("known"), _make_slice_ref("unknown")]
        gap_counts = {"known": 5}

        ordered = scheduler._prioritize(refs, gap_counts)

        assert ordered[0].slice_id == "known"
        assert ordered[1].slice_id == "unknown"


# ======================================================================
# ReactivePromotionScheduler._aggregate()
# ======================================================================


class TestPromotionSchedulerAggregate:
    """Test ReactivePromotionScheduler._aggregate() result computation."""

    def test_identifies_blocked_slices(self) -> None:
        """_aggregate() correctly identifies blocked slices."""
        mock_loop = MagicMock(spec=PromotionLoop)
        scheduler = ReactivePromotionScheduler(loop=mock_loop)

        results = [
            _make_slice_result("s1", "COMPLETE", iterations=1),
            _make_slice_result("s2", "BLOCKED", iterations=1),
            _make_slice_result("s3", "BLOCKED", iterations=2),
        ]

        agg = scheduler._aggregate(results)

        assert agg.blocked_slices == ["s2", "s3"]
        assert agg.failed_slices == []
        assert agg.all_complete is False

    def test_identifies_failed_slices(self) -> None:
        """_aggregate() correctly identifies failed slices."""
        mock_loop = MagicMock(spec=PromotionLoop)
        scheduler = ReactivePromotionScheduler(loop=mock_loop)

        results = [
            _make_slice_result("s1", "COMPLETE", iterations=2),
            _make_slice_result("s2", "FAILED", iterations=1, error="crash"),
        ]

        agg = scheduler._aggregate(results)

        assert agg.failed_slices == ["s2"]
        assert agg.blocked_slices == []
        assert agg.all_complete is False

    def test_all_complete_when_all_slices_complete(self) -> None:
        """_aggregate() sets all_complete=True when every slice is COMPLETE."""
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

    def test_sums_total_iterations(self) -> None:
        """_aggregate() sums iterations across all slices."""
        mock_loop = MagicMock(spec=PromotionLoop)
        scheduler = ReactivePromotionScheduler(loop=mock_loop)

        results = [
            _make_slice_result("s1", "COMPLETE", iterations=5),
            _make_slice_result("s2", "FAILED", iterations=2),
            _make_slice_result("s3", "BLOCKED", iterations=3),
        ]

        agg = scheduler._aggregate(results)
        assert agg.total_iterations == 10

    def test_empty_results(self) -> None:
        """_aggregate() handles empty results list."""
        mock_loop = MagicMock(spec=PromotionLoop)
        scheduler = ReactivePromotionScheduler(loop=mock_loop)

        agg = scheduler._aggregate([])

        assert agg.all_complete is True  # vacuously true: all() of empty is True
        assert agg.total_iterations == 0
        assert agg.blocked_slices == []
        assert agg.failed_slices == []


# ======================================================================
# ReactivePromotionScheduler.run() with parallel execution
# ======================================================================


class TestPromotionSchedulerRunParallel:
    """Test ReactivePromotionScheduler.run() with parallel execution."""

    def test_parallel_with_multiple_slices(self) -> None:
        """run() with max_parallel>1 and multiple slices uses parallel path."""
        mock_loop = MagicMock(spec=PromotionLoop)
        # run_slice is called per-slice in parallel path
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


class TestPromotionSchedulerRunWithGapPriority:
    """Test that run() respects gap-count priority ordering."""

    def test_priority_ordering_affects_execution(self) -> None:
        """run() passes gap_counts to _prioritize() and orders slices."""
        mock_loop = MagicMock(spec=PromotionLoop)
        mock_loop.run_slices.return_value = [
            _make_slice_result("high", "COMPLETE", iterations=1),
            _make_slice_result("low", "COMPLETE", iterations=1),
        ]

        config = SchedulerConfig(max_parallel=1, priority_by_gaps=True)
        scheduler = ReactivePromotionScheduler(loop=mock_loop, config=config)

        refs = [_make_slice_ref("low"), _make_slice_ref("high")]
        gap_counts = {"low": 1, "high": 10}

        scheduler.run(refs, _make_run_context(), gap_counts=gap_counts)

        # Verify run_slices was called with reordered refs
        actual_call_refs = mock_loop.run_slices.call_args[0][0]
        assert actual_call_refs[0].slice_id == "high"
        assert actual_call_refs[1].slice_id == "low"
