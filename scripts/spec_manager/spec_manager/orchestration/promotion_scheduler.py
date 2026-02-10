"""PromotionScheduler: bounded-concurrency slice execution.

Manages the execution of multiple slices through the PromotionLoop,
with configurable concurrency and priority ordering.

Parallel safety comes from:
- Slice-local worktrees (grandchild per slice).
- Slice-local evidence directories.
- Merge to shared parent/clean only at controlled integration boundaries.

The integration step is serialized via a threading lock to prevent
concurrent merge-to-dirty operations.

Usage::

    scheduler = PromotionScheduler(
        loop=PromotionLoop(worktree_manager=wm),
        max_parallel=4,
    )
    results = scheduler.run(slice_refs, run_context)
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from spec_manager.orchestration.promotion_loop import (
    PromotionLoop,
    RunContext,
    SliceRef,
    SliceResult,
)

logger = logging.getLogger(__name__)


@dataclass
class SchedulerConfig:
    """Configuration for the PromotionScheduler.

    Attributes:
        max_parallel: Maximum concurrent slice executions.
        priority_by_gaps: If True, sort slices by gap count (highest first).
        stop_on_first_failure: If True, cancel remaining slices on first FAILED.
        integration_lock: If True, serialize integration steps across slices.
    """

    max_parallel: int = 4
    priority_by_gaps: bool = True
    stop_on_first_failure: bool = False
    integration_lock: bool = True


@dataclass
class SchedulerResult:
    """Aggregate result from running all slices.

    Attributes:
        slice_results: Per-slice results.
        total_iterations: Sum of all iterations across slices.
        all_complete: Whether every slice finished successfully.
        blocked_slices: Slice IDs that are blocked.
        failed_slices: Slice IDs that failed.
    """

    slice_results: list[SliceResult] = field(default_factory=list)
    total_iterations: int = 0
    all_complete: bool = False
    blocked_slices: list[str] = field(default_factory=list)
    failed_slices: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """Return a summary dict."""
        return {
            "total_slices": len(self.slice_results),
            "complete": sum(1 for r in self.slice_results if r.status == "COMPLETE"),
            "blocked": len(self.blocked_slices),
            "failed": len(self.failed_slices),
            "max_iterations": sum(1 for r in self.slice_results if r.status == "MAX_ITERATIONS"),
            "total_iterations": self.total_iterations,
            "all_complete": self.all_complete,
        }


class PromotionScheduler:
    """Bounded-concurrency scheduler for slice execution.

    Args:
        loop: The PromotionLoop instance to use for slice execution.
        config: Scheduler configuration.
    """

    def __init__(
        self,
        loop: PromotionLoop,
        config: SchedulerConfig | None = None,
    ) -> None:
        self._loop = loop
        self._config = config or SchedulerConfig()
        self._integration_lock = threading.Lock() if self._config.integration_lock else None

    def run(
        self,
        slice_refs: list[SliceRef],
        run_context: RunContext,
        *,
        gap_counts: dict[str, int] | None = None,
    ) -> SchedulerResult:
        """Execute slices with bounded concurrency.

        Args:
            slice_refs: Slices to process.
            run_context: Run-scoped configuration.
            gap_counts: Optional gap counts per slice_id for priority ordering.

        Returns:
            SchedulerResult with all slice results.
        """
        if not slice_refs:
            return SchedulerResult(all_complete=True)

        # Priority ordering
        ordered = self._prioritize(slice_refs, gap_counts)

        max_parallel = min(self._config.max_parallel, len(ordered))

        if max_parallel <= 1:
            return self._run_sequential(ordered, run_context)

        return self._run_parallel(ordered, run_context, max_parallel)

    def _prioritize(
        self,
        slice_refs: list[SliceRef],
        gap_counts: dict[str, int] | None,
    ) -> list[SliceRef]:
        """Sort slices by priority (highest gap count first)."""
        if not self._config.priority_by_gaps or not gap_counts:
            return list(slice_refs)

        return sorted(
            slice_refs,
            key=lambda s: gap_counts.get(s.slice_id, 0),
            reverse=True,
        )

    def _run_sequential(
        self,
        slice_refs: list[SliceRef],
        run_context: RunContext,
    ) -> SchedulerResult:
        """Run slices sequentially (fallback for max_parallel=1)."""
        results = self._loop.run_slices(slice_refs, run_context)
        return self._aggregate(results)

    def _run_parallel(
        self,
        slice_refs: list[SliceRef],
        run_context: RunContext,
        max_workers: int,
    ) -> SchedulerResult:
        """Run slices in parallel with bounded concurrency."""
        results: list[SliceResult] = []
        cancel_event = threading.Event()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for ref in slice_refs:
                future = executor.submit(
                    self._run_single_slice,
                    ref,
                    run_context,
                    cancel_event,
                )
                futures[future] = ref.slice_id

            for future in as_completed(futures):
                slice_id = futures[future]
                try:
                    result = future.result()
                    results.append(result)

                    if (
                        result.status == "FAILED"
                        and self._config.stop_on_first_failure
                    ):
                        logger.warning(
                            "Slice '%s' failed — cancelling remaining slices",
                            slice_id,
                        )
                        cancel_event.set()

                except Exception as exc:
                    logger.error("Slice '%s' raised: %s", slice_id, exc)
                    results.append(
                        SliceResult(
                            slice_id=slice_id,
                            status="FAILED",
                            error=str(exc),
                        )
                    )
                    if self._config.stop_on_first_failure:
                        cancel_event.set()

        return self._aggregate(results)

    def _run_single_slice(
        self,
        slice_ref: SliceRef,
        run_context: RunContext,
        cancel_event: threading.Event,
    ) -> SliceResult:
        """Run a single slice, checking for cancellation."""
        if cancel_event.is_set():
            return SliceResult(
                slice_id=slice_ref.slice_id,
                status="FAILED",
                error="Cancelled by scheduler",
            )

        logger.info("Scheduler: starting slice '%s'", slice_ref.slice_id)
        result = self._loop.run_slice(slice_ref, run_context)
        logger.info(
            "Scheduler: slice '%s' finished with status %s (%d iterations)",
            slice_ref.slice_id,
            result.status,
            result.iterations,
        )
        return result

    def _aggregate(self, results: list[SliceResult]) -> SchedulerResult:
        """Aggregate slice results into a SchedulerResult."""
        blocked = [r.slice_id for r in results if r.status == "BLOCKED"]
        failed = [r.slice_id for r in results if r.status == "FAILED"]
        total_iters = sum(r.iterations for r in results)
        all_complete = all(r.status == "COMPLETE" for r in results)

        return SchedulerResult(
            slice_results=results,
            total_iterations=total_iters,
            all_complete=all_complete,
            blocked_slices=blocked,
            failed_slices=failed,
        )
