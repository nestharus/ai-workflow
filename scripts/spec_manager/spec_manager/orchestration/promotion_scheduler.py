"""ReactivePromotionScheduler: bounded-concurrency slice execution with WAITING support.

Manages the execution of multiple slices through the PromotionLoop,
with configurable concurrency, priority ordering, and reactive wake
support via MonitorExecutor and WakeQueue.

When a slice returns WAITING, the scheduler moves it to a waiting set
instead of treating it as a failure.  A background monitor thread
periodically checks conditions and enqueues WakeEvents.  The main loop
dequeues events and re-queues the corresponding slices.

Parallel safety comes from:
- Slice-local worktrees (grandchild per slice).
- Slice-local evidence directories.
- Merge to shared parent/clean only at controlled integration boundaries.

The integration step is serialized via a threading lock to prevent
concurrent merge-to-dirty operations.

Usage::

    scheduler = ReactivePromotionScheduler(
        loop=PromotionLoop(worktree_manager=wm),
        config=SchedulerConfig(max_parallel=4),
        monitor_executor=monitor_executor,
        wake_queue=wake_queue,
    )
    results = scheduler.run(slice_refs, run_context)
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from pathlib import Path
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
    """Configuration for the ReactivePromotionScheduler.

    Attributes:
        max_parallel: Maximum concurrent slice executions.
        priority_by_gaps: If True, sort slices by gap count (highest first).
        stop_on_first_failure: If True, cancel remaining slices on first FAILED.
        integration_lock: If True, serialize integration steps across slices.
        monitor_poll_interval_sec: Seconds between monitor executor poll cycles.
        max_wait_cycles: Maximum times a slice can be woken before escalating to FAILED.
        max_idle_polls: Maximum consecutive idle monitor polls (no wake events)
            before the scheduler escalates remaining waiting slices to FAILED.
    """

    max_parallel: int = 4
    priority_by_gaps: bool = True
    stop_on_first_failure: bool = False
    integration_lock: bool = True
    monitor_poll_interval_sec: int = 20
    max_wait_cycles: int = 10
    max_idle_polls: int = 50


@dataclass
class SchedulerResult:
    """Aggregate result from running all slices.

    Attributes:
        slice_results: Per-slice results.
        total_iterations: Sum of all iterations across slices.
        all_complete: Whether every slice finished successfully.
        blocked_slices: Slice IDs that are blocked.
        failed_slices: Slice IDs that failed.
        waiting_slices: Slice IDs that are still waiting (not woken).
    """

    slice_results: list[SliceResult] = field(default_factory=list)
    total_iterations: int = 0
    all_complete: bool = False
    blocked_slices: list[str] = field(default_factory=list)
    failed_slices: list[str] = field(default_factory=list)
    waiting_slices: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """Return a summary dict."""
        return {
            "total_slices": len(self.slice_results),
            "complete": sum(1 for r in self.slice_results if r.status == "COMPLETE"),
            "skipped": sum(1 for r in self.slice_results if r.status == "SKIPPED"),
            "blocked": len(self.blocked_slices),
            "failed": len(self.failed_slices),
            "waiting": len(self.waiting_slices),
            "max_iterations": sum(1 for r in self.slice_results if r.status == "MAX_ITERATIONS"),
            "total_iterations": self.total_iterations,
            "all_complete": self.all_complete,
        }


class ReactivePromotionScheduler:
    """Bounded-concurrency scheduler with reactive wake support.

    When constructed without monitor_executor/wake_queue, behaves like
    the old PromotionScheduler (WAITING becomes FAILED).

    Args:
        loop: The PromotionLoop instance to use for slice execution.
        config: Scheduler configuration.
        monitor_executor: Optional MonitorExecutor for checking conditions.
        wake_queue: Optional WakeQueue for receiving wake events.
    """

    def __init__(
        self,
        loop: PromotionLoop,
        config: SchedulerConfig | None = None,
        monitor_executor: Any | None = None,
        wake_queue: Any | None = None,
    ) -> None:
        self._loop = loop
        self._config = config or SchedulerConfig()
        self._integration_lock = threading.Lock() if self._config.integration_lock else None
        self._monitor_executor = monitor_executor
        self._wake_queue = wake_queue

    def run(
        self,
        slice_refs: list[SliceRef],
        run_context: RunContext,
        *,
        gap_counts: dict[str, int] | None = None,
        on_slice_result: Callable[[SliceResult], None] | None = None,
    ) -> SchedulerResult:
        """Execute slices with bounded concurrency and reactive wake support.

        Args:
            slice_refs: Slices to process.
            run_context: Run-scoped configuration.
            gap_counts: Optional gap counts per slice_id for priority ordering.
            on_slice_result: Optional callback invoked whenever a slice emits
                a terminal result within the scheduler event loop.

        Returns:
            SchedulerResult with all slice results.
        """
        if not slice_refs:
            return SchedulerResult(all_complete=True)

        # Priority ordering
        ordered = self._prioritize(slice_refs, gap_counts)

        max_parallel = min(self._config.max_parallel, len(ordered))

        if max_parallel <= 1 and not self._has_reactive_support():
            return self._run_sequential(
                ordered,
                run_context,
                on_slice_result=on_slice_result,
            )

        return self._run_reactive(
            ordered,
            run_context,
            max(max_parallel, 1),
            on_slice_result=on_slice_result,
        )

    def _has_reactive_support(self) -> bool:
        """True if monitor executor and wake queue are available."""
        return self._monitor_executor is not None and self._wake_queue is not None

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
        *,
        on_slice_result: Callable[[SliceResult], None] | None = None,
    ) -> SchedulerResult:
        """Run slices sequentially (fallback for max_parallel=1, no reactive).

        WAITING results are converted to FAILED since there is no
        reactive support in the sequential path.
        """
        results = self._loop.run_slices(slice_refs, run_context)
        # Convert WAITING to FAILED in sequential mode (no reactive support)
        converted: list[SliceResult] = []
        for r in results:
            if r.status == "WAITING":
                emitted = SliceResult(
                    slice_id=r.slice_id,
                    status="FAILED",
                    iterations=r.iterations,
                    error="WAITING not supported (no monitor executor)",
                )
            else:
                emitted = r
            converted.append(emitted)
            self._notify_slice_result(emitted, on_slice_result)
        return self._aggregate(converted)

    @staticmethod
    def _notify_slice_result(
        result: SliceResult,
        on_slice_result: Callable[[SliceResult], None] | None,
    ) -> None:
        """Invoke ``on_slice_result`` without allowing callback failures to abort scheduling."""
        if on_slice_result is None:
            return
        try:
            on_slice_result(result)
        except Exception:
            logger.exception(
                "on_slice_result callback raised for slice '%s'",
                result.slice_id,
            )

    def _run_reactive(
        self,
        slice_refs: list[SliceRef],
        run_context: RunContext,
        max_workers: int,
        *,
        on_slice_result: Callable[[SliceResult], None] | None = None,
    ) -> SchedulerResult:
        """Run slices with reactive wake support.

        Main event loop:
        1. Start all slices in thread pool
        2. As futures complete:
           - COMPLETE: record success
           - WAITING: add to waiting_set, track wake_count
           - FAILED/BLOCKED/etc: record failure
        3. Periodically run monitor_executor.run_once() (if available)
        4. Check wake_queue for events (if available)
        5. When wake event matches a waiting slice, re-queue it
        6. Terminate when ready_queue empty AND waiting_set empty
        """
        completed_results: list[SliceResult] = []
        cancel_event = threading.Event()
        monitor_signal = threading.Event()

        # Waiting state: slice_id → SliceRef
        waiting_set: dict[str, SliceRef] = {}
        # Track wake counts separately: slice_id → count
        wake_counts: dict[str, int] = {}
        # Consecutive idle polls (no wake events and no active futures)
        idle_polls = 0

        # Start monitor thread if reactive support is available
        monitor_stop = threading.Event()
        monitor_thread = None
        if self._has_reactive_support():
            monitor_thread = threading.Thread(
                target=self._monitor_loop,
                args=(monitor_stop, monitor_signal),
                daemon=True,
            )
            monitor_thread.start()

        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit initial batch
                active_futures: dict[Future, str] = {}
                for ref in slice_refs:
                    future = executor.submit(
                        self._run_single_slice,
                        ref,
                        run_context,
                        cancel_event,
                    )
                    active_futures[future] = ref.slice_id

                while active_futures or waiting_set:
                    # Collect completed futures
                    newly_done: list[Future] = []
                    for f in list(active_futures):
                        if f.done():
                            newly_done.append(f)

                    if not newly_done and active_futures:
                        # Wait briefly for any future to complete
                        try:
                            done_iter = as_completed(active_futures, timeout=1.0)
                            for f in done_iter:
                                newly_done.append(f)
                                break  # Process one at a time for responsiveness
                        except TimeoutError:
                            pass  # Expected — polling loop, not an error

                    if newly_done:
                        idle_polls = 0

                    for future in newly_done:
                        slice_id = active_futures.pop(future)
                        try:
                            result = future.result()
                        except Exception as exc:
                            logger.exception("Slice '%s' raised", slice_id)
                            result = SliceResult(
                                slice_id=slice_id,
                                status="FAILED",
                                error=str(exc),
                            )

                        if result.status == "WAITING":
                            if self._has_reactive_support():
                                # Move to waiting set, preserve wake count
                                waiting_set[slice_id] = SliceRef(
                                    slice_id=slice_id,
                                    layer=(result.slice_id and "l1") or "l1",
                                )
                                # Recover ref from original map
                                for ref in slice_refs:
                                    if ref.slice_id == slice_id:
                                        waiting_set[slice_id] = ref
                                        break
                                wake_counts.setdefault(slice_id, 0)
                                logger.info(
                                    "Slice '%s' is WAITING (wake_count=%d)",
                                    slice_id,
                                    wake_counts[slice_id],
                                )
                            else:
                                # No reactive support — treat WAITING as FAILED
                                emitted = SliceResult(
                                    slice_id=slice_id,
                                    status="FAILED",
                                    iterations=result.iterations,
                                    error="WAITING not supported (no monitor executor)",
                                )
                                completed_results.append(emitted)
                                self._notify_slice_result(emitted, on_slice_result)
                                if self._config.stop_on_first_failure:
                                    cancel_event.set()
                        elif result.status == "FAILED":
                            completed_results.append(result)
                            self._notify_slice_result(result, on_slice_result)
                            if self._config.stop_on_first_failure:
                                logger.warning(
                                    "Slice '%s' failed — cancelling remaining slices",
                                    slice_id,
                                )
                                cancel_event.set()
                        else:
                            # COMPLETE, BLOCKED, MAX_ITERATIONS, STAGNATED
                            completed_results.append(result)
                            self._notify_slice_result(result, on_slice_result)

                    # Check wake queue for events that can re-queue waiting slices
                    if self._has_reactive_support() and waiting_set:
                        woken = self._process_wake_events(
                            waiting_set,
                            wake_counts,
                            executor,
                            active_futures,
                            run_context,
                            cancel_event,
                        )
                        if woken:
                            idle_polls = 0
                        for woken_id in woken:
                            logger.info("Re-queued slice '%s' after wake event", woken_id)

                    # Check for slices that exceeded max_wait_cycles
                    exceeded = [
                        sid
                        for sid in list(waiting_set)
                        if wake_counts.get(sid, 0) >= self._config.max_wait_cycles
                    ]
                    for sid in exceeded:
                        waiting_set.pop(sid)
                        wc = wake_counts.get(sid, 0)
                        logger.warning(
                            "Slice '%s' exceeded max_wait_cycles (%d) — marking FAILED",
                            sid,
                            wc,
                        )
                        emitted = SliceResult(
                            slice_id=sid,
                            status="FAILED",
                            error=f"Exceeded max_wait_cycles ({wc})",
                            wake_count=wc,
                        )
                        completed_results.append(emitted)
                        self._notify_slice_result(emitted, on_slice_result)
                        if self._config.stop_on_first_failure:
                            cancel_event.set()

                    # If no active futures and only waiting slices remain,
                    # wait for a monitor signal or timeout
                    if not active_futures and waiting_set:
                        if not self._has_reactive_support():
                            # No reactive support; fail all waiting slices
                            for sid in list(waiting_set):
                                wc = wake_counts.get(sid, 0)
                                emitted = SliceResult(
                                    slice_id=sid,
                                    status="FAILED",
                                    error="WAITING not supported",
                                    wake_count=wc,
                                )
                                completed_results.append(emitted)
                                self._notify_slice_result(emitted, on_slice_result)
                            waiting_set.clear()
                        else:
                            idle_polls += 1
                            if idle_polls >= self._config.max_idle_polls:
                                logger.warning(
                                    "Scheduler exceeded max_idle_polls (%d) — "
                                    "escalating %d waiting slices to FAILED",
                                    self._config.max_idle_polls,
                                    len(waiting_set),
                                )
                                for sid in list(waiting_set):
                                    wc = wake_counts.get(sid, 0)
                                    emitted = SliceResult(
                                        slice_id=sid,
                                        status="FAILED",
                                        error=(
                                            "Exceeded max_idle_polls while waiting "
                                            "for monitor wake events"
                                        ),
                                        wake_count=wc,
                                    )
                                    completed_results.append(emitted)
                                    self._notify_slice_result(emitted, on_slice_result)
                                waiting_set.clear()
                                break
                            # Wait for monitor to signal or timeout
                            monitor_signal.wait(timeout=self._config.monitor_poll_interval_sec)
                            monitor_signal.clear()

                    # Bail if cancelled and no active futures
                    if cancel_event.is_set() and not active_futures:
                        for sid in list(waiting_set):
                            wc = wake_counts.get(sid, 0)
                            emitted = SliceResult(
                                slice_id=sid,
                                status="FAILED",
                                error="Cancelled by scheduler",
                                wake_count=wc,
                            )
                            completed_results.append(emitted)
                            self._notify_slice_result(emitted, on_slice_result)
                        waiting_set.clear()
                        break

        finally:
            # Stop monitor thread
            if monitor_thread is not None:
                monitor_stop.set()
                monitor_signal.set()  # Unblock any wait
                monitor_thread.join(timeout=5.0)

        # Defensive fallback: scheduler exits with terminal outcomes only.
        remaining_waiting = list(waiting_set.keys())
        for sid in remaining_waiting:
            wc = wake_counts.get(sid, 0)
            completed_results.append(
                SliceResult(
                    slice_id=sid,
                    status="FAILED",
                    error="Scheduler terminated while slice was still waiting",
                    wake_count=wc,
                )
            )

        return self._aggregate(completed_results, [])

    def _process_wake_events(
        self,
        waiting_set: dict[str, SliceRef],
        wake_counts: dict[str, int],
        executor: ThreadPoolExecutor,
        active_futures: dict[Future, str],
        run_context: RunContext,
        cancel_event: threading.Event,
    ) -> list[str]:
        """Dequeue wake events and re-queue matching slices.

        Returns list of slice IDs that were re-queued.
        """
        assert self._wake_queue is not None
        woken: list[str] = []
        for sid in list(waiting_set.keys()):
            raw_events = self._wake_queue.dequeue(sid)
            events = [self._wake_event_payload(event) for event in raw_events]
            if not events:
                continue

            wake_counts[sid] = wake_counts.get(sid, 0) + 1

            # Check max_wait_cycles before re-queuing
            if wake_counts[sid] > self._config.max_wait_cycles:
                # Will be caught by the exceeded check in the main loop
                continue

            ref = waiting_set[sid]
            resume_ref = self._build_resume_slice_ref(
                ref=ref,
                wake_count=wake_counts[sid],
                wake_events=events,
            )
            sync_ok, sync_error = self._sync_slice_for_resume(
                slice_ref=resume_ref,
                run_context=run_context,
            )
            if not sync_ok:
                waiting_set[sid] = self._mark_resume_merge_conflict(
                    ref=resume_ref,
                    error=sync_error,
                    wake_events=events,
                )
                logger.warning(
                    "Wake sync failed for slice '%s'; waiting for triage-compatible wake event: %s",
                    sid,
                    sync_error,
                )
                continue

            waiting_set.pop(sid, None)
            future = executor.submit(
                self._run_single_slice,
                resume_ref,
                run_context,
                cancel_event,
            )
            active_futures[future] = sid
            woken.append(sid)
        return woken

    @staticmethod
    def _wake_event_payload(event: Any) -> dict[str, Any]:
        """Normalize wake queue entries into dict payloads."""
        if isinstance(event, dict):
            return dict(event)
        to_dict = getattr(event, "to_dict", None)
        if callable(to_dict):
            try:
                payload = to_dict()
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                return payload
        payload: dict[str, Any] = {}
        for key in (
            "event_id",
            "timestamp",
            "monitor_id",
            "signal_id",
            "slice_id",
            "layer",
            "reason",
            "artifact_key",
            "wake_payload",
        ):
            value = getattr(event, key, None)
            if value is None:
                continue
            payload[key] = value
        return payload

    @staticmethod
    def _build_resume_slice_ref(
        *,
        ref: SliceRef,
        wake_count: int,
        wake_events: list[dict[str, Any]],
    ) -> SliceRef:
        """Copy wake context into slice metadata for resumed runs."""
        metadata = dict(ref.metadata) if isinstance(ref.metadata, dict) else {}
        metadata["wake_count"] = max(wake_count, 0)
        metadata["wake_events"] = list(wake_events)

        if wake_events:
            last_event = wake_events[-1]
            signal_id = str(last_event.get("signal_id", "")).strip()
            if signal_id:
                metadata["last_signal_id"] = signal_id
            wake_payload = last_event.get("wake_payload")
            metadata["wake_payload"] = wake_payload if isinstance(wake_payload, dict) else {}
            metadata["wake_reason"] = str(last_event.get("reason", "")).strip()
            metadata["wake_artifact_key"] = str(last_event.get("artifact_key", "")).strip()
        return replace(ref, metadata=metadata)

    @staticmethod
    def _mark_resume_merge_conflict(
        *,
        ref: SliceRef,
        error: str,
        wake_events: list[dict[str, Any]],
    ) -> SliceRef:
        """Attach merge-conflict resume context without re-queuing normal execution."""
        metadata = dict(ref.metadata) if isinstance(ref.metadata, dict) else {}
        last_signal = str(metadata.get("last_signal_id", "")).strip() or (
            f"{ref.slice_id}:wake-sync-merge-conflict"
        )
        wake_payload = (
            dict(metadata.get("wake_payload", {}))
            if isinstance(metadata.get("wake_payload", {}), dict)
            else {}
        )
        wake_payload["wake_sync_status"] = "MERGE_CONFLICT"
        wake_payload["wake_sync_error"] = str(error).strip()
        wake_payload["layer"] = str(ref.layer)
        metadata["last_signal_id"] = last_signal
        metadata["wake_payload"] = wake_payload
        metadata["wake_requires_triage"] = True

        merge_event = {
            "signal_id": last_signal,
            "slice_id": ref.slice_id,
            "layer": str(ref.layer),
            "reason": "wake_sync_merge_conflict",
            "artifact_key": f"{ref.layer}/dirty",
            "wake_payload": wake_payload,
        }
        metadata["wake_events"] = [*wake_events, merge_event]
        return replace(ref, metadata=metadata)

    def _sync_slice_for_resume(
        self,
        *,
        slice_ref: SliceRef,
        run_context: RunContext,
    ) -> tuple[bool, str]:
        """Sync a waking slice against layer dirty before re-queueing execution."""
        wm = getattr(self._loop, "_wm", None)
        if wm is None or not hasattr(wm, "vcs") or not hasattr(wm, "layer_branch"):
            return True, ""

        slice_worktree = None
        try:
            slice_worktree = wm.get_slice_worktree(slice_ref.layer, slice_ref.slice_id)
        except Exception:
            slice_worktree = None
        if slice_worktree is None and str(slice_ref.worktree_path).strip():
            slice_worktree = Path(slice_ref.worktree_path)
        if slice_worktree is None:
            return False, f"Slice worktree missing for wake sync ({slice_ref.slice_id})"

        worktree_path = Path(slice_worktree)
        if not worktree_path.exists():
            return False, f"Slice worktree path does not exist: {worktree_path}"

        try:
            fetched, fetch_error = wm.vcs.fetch(worktree_path, remote="origin")
        except Exception as exc:
            fetched, fetch_error = False, str(exc)
        if not fetched and fetch_error:
            logger.warning(
                "git fetch origin failed before wake rebase for slice '%s': %s",
                slice_ref.slice_id,
                fetch_error,
            )

        try:
            dirty_branch = wm.layer_branch(slice_ref.layer, "dirty")
        except Exception:
            dirty_branch = f"pdd/{run_context.run_id}/{slice_ref.layer}/dirty"

        try:
            rebased, rebase_error = wm.vcs.rebase(worktree_path, dirty_branch)
        except Exception as exc:
            return False, str(exc)
        if not rebased:
            return False, str(rebase_error or "Unknown rebase failure")
        return True, ""

    def _monitor_loop(
        self,
        stop_event: threading.Event,
        signal_event: threading.Event,
    ) -> None:
        """Background thread: periodically run monitor_executor.run_once()."""
        assert self._monitor_executor is not None
        while not stop_event.is_set():
            try:
                fired = self._monitor_executor.run_once()
                if fired:
                    signal_event.set()
            except Exception:
                logger.exception("MonitorExecutor.run_once() raised")
            stop_event.wait(timeout=self._config.monitor_poll_interval_sec)

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
        ctx_config = dict(run_context.config) if isinstance(run_context.config, dict) else {}
        if self._integration_lock is not None:
            ctx_config["_integration_lock"] = self._integration_lock
        slice_run_context = replace(run_context, config=ctx_config)
        result = self._loop.run_slice(slice_ref, slice_run_context)
        logger.info(
            "Scheduler: slice '%s' finished with status %s (%d iterations)",
            slice_ref.slice_id,
            result.status,
            result.iterations,
        )
        return result

    def _aggregate(
        self,
        results: list[SliceResult],
        remaining_waiting: list[str] | None = None,
    ) -> SchedulerResult:
        """Aggregate slice results into a SchedulerResult."""
        blocked = [r.slice_id for r in results if r.status == "BLOCKED"]
        failed = [r.slice_id for r in results if r.status == "FAILED"]
        waiting = (
            remaining_waiting
            if remaining_waiting is not None
            else [r.slice_id for r in results if r.status == "WAITING"]
        )
        total_iters = sum(r.iterations for r in results)
        all_complete = all(r.status in {"COMPLETE", "SKIPPED"} for r in results)

        return SchedulerResult(
            slice_results=results,
            total_iterations=total_iters,
            all_complete=all_complete,
            blocked_slices=blocked,
            failed_slices=failed,
            waiting_slices=waiting,
        )


# Backwards-compatible alias so existing imports keep working
PromotionScheduler = ReactivePromotionScheduler  # type: ignore[assignment,misc]
