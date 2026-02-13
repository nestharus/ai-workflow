"""Component tests for orchestration.promotion_loop module.

Tests PromotionLoop.run_slice() convergence behavior, step implementations,
and run_slices() multi-slice processing.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from spec_manager.orchestration.demotion import DemotionTicket
from spec_manager.orchestration.evidence import (
    EvidenceBundle,
    GapReportRef,
    ImplementationRef,
    ManifestRef,
    PlanRef,
)
from spec_manager.orchestration.promotion_loop import (
    AnalyzeStep,
    CollectBaselineStep,
    CoordinateStep,
    GapExplorationStep,
    ImplementStep,
    IntegrateStep,
    PlanStep,
    PromoteStep,
    PromotionLoop,
    RunContext,
    SliceContext,
    SliceRef,
    SliceResult,
    StepResult,
    VerifyStep,
)

# ======================================================================
# Helpers
# ======================================================================


class NoGapsStep:
    """A step that clears all gaps (simulating full implementation)."""

    name = "NO_GAPS"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        bundle.gaps = GapReportRef(open_gaps=[])
        return StepResult(status="OK")


class PersistentGapsStep:
    """A step that always reports open gaps."""

    name = "PERSISTENT_GAPS"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        bundle.gaps = GapReportRef(open_gaps=[{"file": "stub.py", "kind": "unimplemented"}])
        return StepResult(status="OK")


class BlockingStep:
    """A step that returns BLOCKED status."""

    name = "BLOCKING"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        bundle.implementation = ImplementationRef(
            under_spec_events=[{"kind": "MISSING_CONSTRAINT", "question": "What should X do?"}]
        )
        bundle.status = "BLOCKED"
        return StepResult(
            status="BLOCKED",
            error="Under-specification: 1 unresolvable events",
        )


class RetryStep:
    """A step that returns RETRY on first call, then OK."""

    name = "RETRY_ONCE"

    def __init__(self) -> None:
        self._call_count = 0

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        self._call_count += 1
        if self._call_count <= 1:
            return StepResult(
                status="RETRY",
                emitted_tickets=[
                    DemotionTicket(
                        run_id=ctx.run_id,
                        slice_id=ctx.slice_id,
                        source="TEST_FAILURE",
                        diagnosis="merge conflict",
                    )
                ],
                error="conflict",
            )
        return StepResult(status="OK")


class FailStep:
    """A step that returns FAIL status."""

    name = "FAIL"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        return StepResult(status="FAIL", error="fatal error")


# ======================================================================
# StepResult
# ======================================================================


class TestStepResult:
    """Tests for StepResult dataclass."""

    def test_defaults(self) -> None:
        """StepResult has OK status and empty fields by default."""
        sr = StepResult()
        assert sr.status == "OK"
        assert sr.bundle_path == ""
        assert sr.emitted_tickets == []
        assert sr.notes_path is None
        assert sr.error == ""

    def test_custom_status(self) -> None:
        """StepResult can be constructed with any valid status."""
        for status in ("OK", "RETRY", "BLOCKED", "FAIL"):
            sr = StepResult(status=status)
            assert sr.status == status


# ======================================================================
# CollectBaselineStep
# ======================================================================


class TestCollectBaselineStep:
    """Tests for CollectBaselineStep.run()."""

    def test_populates_bundle_manifest(self, tmp_path: Path) -> None:
        """CollectBaselineStep populates bundle.manifest with file list."""
        # Create a slice directory with some files
        slice_root = tmp_path / "slice"
        slice_root.mkdir()
        (slice_root / "main.py").write_text("print('hello')")
        (slice_root / "utils.py").write_text("def helper(): pass")

        ctx = SliceContext(
            slice_root=str(slice_root),
            workspace_root=str(tmp_path),
            run_id="r1",
            slice_id="s1",
        )
        bundle = EvidenceBundle(
            run_id="r1",
            slice_id="s1",
            iteration=1,
            workspace_root=str(tmp_path),
        )

        step = CollectBaselineStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"
        assert len(bundle.manifest.files) == 2
        paths = [f["path"] for f in bundle.manifest.files]
        assert "main.py" in paths
        assert "utils.py" in paths

    def test_returns_fail_when_slice_root_missing(self, tmp_path: Path) -> None:
        """CollectBaselineStep returns FAIL when slice root does not exist."""
        ctx = SliceContext(
            slice_root=str(tmp_path / "nonexistent"),
            workspace_root=str(tmp_path),
        )
        bundle = EvidenceBundle()

        step = CollectBaselineStep()
        result = step.run(ctx, bundle)

        assert result.status == "FAIL"
        assert "does not exist" in result.error


# ======================================================================
# GapExplorationStep
# ======================================================================


class TestGapExplorationStep:
    """Tests for GapExplorationStep.run()."""

    def test_populates_bundle_gaps_empty_dir(self, tmp_path: Path) -> None:
        """GapExplorationStep with no .py files reports no gaps."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        ctx = SliceContext(slice_root=str(slice_root))
        bundle = EvidenceBundle()

        step = GapExplorationStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"
        assert bundle.gaps.open_gaps == []


# ======================================================================
# PlanStep
# ======================================================================


class TestPlanStep:
    """Tests for PlanStep.run()."""

    def test_no_gaps_produces_empty_plan(self) -> None:
        """PlanStep with no gaps produces empty intentions list."""
        ctx = SliceContext()
        bundle = EvidenceBundle()
        bundle.gaps = GapReportRef(open_gaps=[])

        step = PlanStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"
        assert bundle.plan.intentions == []

    def test_l1_gaps_return_noop(self) -> None:
        """PlanStep with L1 layer returns no-op (empty intentions)."""
        ctx = SliceContext(layer="l1")
        bundle = EvidenceBundle()
        bundle.gaps = GapReportRef(
            open_gaps=[
                {"file": "a.py", "description": "stub function"},
                {"file": "b.py", "description": "missing impl"},
            ]
        )

        step = PlanStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"
        assert bundle.plan.intentions == []

    def test_l2_gaps_produce_intentions(self) -> None:
        """PlanStep creates wiring intentions from L2 gaps."""
        ctx = SliceContext(layer="l2")
        bundle = EvidenceBundle()
        bundle.gaps = GapReportRef(
            open_gaps=[
                {"file": "a.py", "description": "missing wiring", "component_id": "comp-1"},
                {"file": "b.py", "description": "unconsumed pin", "component_id": "comp-2"},
            ]
        )

        step = PlanStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"
        assert len(bundle.plan.intentions) == 2
        assert bundle.plan.intentions[0]["target_file"] == "a.py"
        assert "Wire:" in bundle.plan.intentions[0]["approach"]


# ======================================================================
# ImplementStep
# ======================================================================


class TestImplementStep:
    """Tests for ImplementStep.run()."""

    def test_no_intentions_produces_empty_impl(self) -> None:
        """ImplementStep with no plan intentions produces empty output."""
        ctx = SliceContext()
        bundle = EvidenceBundle()
        bundle.plan = PlanRef(intentions=[])

        step = ImplementStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"
        assert bundle.implementation.applied_edits == []

    def test_with_intentions_produces_impl(self) -> None:
        """ImplementStep with intentions records output."""
        ctx = SliceContext()
        bundle = EvidenceBundle()
        bundle.plan = PlanRef(intentions=[{"gap_id": "a.py"}])

        step = ImplementStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"
        assert isinstance(bundle.implementation, ImplementationRef)


# ======================================================================
# CoordinateStep (L2/L3 under-spec resolution path)
# ======================================================================


class TestCoordinateStepUnderSpec:
    """Tests for CoordinateStep L2/L3 under-spec resolution."""

    def test_no_events_returns_ok(self) -> None:
        """CoordinateStep with no under-spec events returns OK."""
        ctx = SliceContext(layer="l2")
        bundle = EvidenceBundle()
        bundle.implementation = ImplementationRef(under_spec_events=[])

        step = CoordinateStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"

    def test_covered_events_return_ok(self, tmp_path: Path) -> None:
        """CoordinateStep (L2) with constraint-covered events returns OK."""
        import json

        # Pre-create constraints that cover the event
        constraints_dir = tmp_path / "analysis" / "constraints"
        constraints_dir.mkdir(parents=True)
        (constraints_dir / "test-slice.json").write_text(
            json.dumps(
                [
                    {
                        "constraint_id": "evt-1",
                        "question": "Which format?",
                        "answer": "Use JSON format for all data exchange.",
                        "source": "user",
                        "confidence": 1.0,
                        "validated": True,
                    }
                ]
            ),
            encoding="utf-8",
        )

        ctx = SliceContext(slice_id="test-slice", workspace_root=str(tmp_path), layer="l2")
        bundle = EvidenceBundle()
        bundle.implementation = ImplementationRef(
            under_spec_events=[
                {"event_id": "evt-1", "kind": "AMBIGUITY", "question": "Which format?"}
            ]
        )

        step = CoordinateStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"

    @patch(
        "spec_manager.refinement.interactive.research.coordinator.run_agent",
        side_effect=RuntimeError("No LLM in test"),
    )
    def test_uncovered_events_return_blocked(self, _mock_agent, tmp_path: Path) -> None:
        """CoordinateStep (L2) with no matching constraints returns BLOCKED."""

        ctx = SliceContext(
            slice_id="test-slice",
            workspace_root=str(tmp_path),
            mode="auto",
            layer="l2",
        )
        bundle = EvidenceBundle()
        bundle.implementation = ImplementationRef(
            under_spec_events=[
                {"event_id": "evt-2", "kind": "MISSING_CONSTRAINT", "question": "What should X do?"}
            ]
        )

        step = CoordinateStep()
        result = step.run(ctx, bundle)

        assert result.status == "BLOCKED"
        assert "unresolvable" in result.error
        assert bundle.status == "BLOCKED"


# ======================================================================
# Simple steps (Analyze, Promote, Verify)
# ======================================================================


class TestSimpleSteps:
    """Tests for Analyze, Promote, and Verify steps which return OK."""

    def test_analyze_returns_ok(self) -> None:
        """AnalyzeStep always returns OK (delegates to real modules later)."""
        step = AnalyzeStep()
        assert step.name == "ANALYZE"
        result = step.run(SliceContext(), EvidenceBundle())
        assert result.status == "OK"

    def test_promote_returns_ok(self) -> None:
        """PromoteStep always returns OK (delegates to real modules later)."""
        step = PromoteStep()
        assert step.name == "PROMOTE"
        result = step.run(SliceContext(), EvidenceBundle())
        assert result.status == "OK"

    def test_verify_returns_ok(self) -> None:
        """VerifyStep always returns OK (delegates to real modules later)."""
        step = VerifyStep()
        assert step.name == "VERIFY"
        result = step.run(SliceContext(), EvidenceBundle())
        assert result.status == "OK"


# ======================================================================
# IntegrateStep
# ======================================================================


class TestIntegrateStep:
    """Tests for IntegrateStep.run()."""

    def test_no_worktree_manager_returns_ok(self) -> None:
        """IntegrateStep without worktree_manager returns OK (no-op)."""
        step = IntegrateStep(worktree_manager=None)
        assert step.name == "INTEGRATE"
        result = step.run(SliceContext(), EvidenceBundle())
        assert result.status == "OK"


# ======================================================================
# PromotionLoop.run_slice()
# ======================================================================


class TestPromotionLoopRunSliceNoGaps:
    """Test PromotionLoop.run_slice() when there are no gaps."""

    def test_completes_in_one_iteration(self, tmp_path: Path) -> None:
        """run_slice() with no gaps completes in 1 iteration."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        loop = PromotionLoop(
            workspace_root=tmp_path,
            steps=[NoGapsStep()],
        )

        slice_ref = SliceRef(
            slice_id="auth",
            layer="l1",
            worktree_path=str(slice_root),
        )
        run_ctx = RunContext(
            run_id="run-1",
            workspace_root=str(tmp_path),
            max_iterations=10,
        )

        result = loop.run_slice(slice_ref, run_ctx)

        assert result.status == "COMPLETE"
        assert result.iterations == 1
        assert result.remaining_gaps == 0
        assert result.slice_id == "auth"


class TestPromotionLoopRunSliceWithGaps:
    """Test PromotionLoop.run_slice() when gaps persist."""

    def test_iterates_at_least_twice(self, tmp_path: Path) -> None:
        """run_slice() with persistent gaps runs until max_iterations."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        loop = PromotionLoop(
            workspace_root=tmp_path,
            steps=[PersistentGapsStep()],
        )

        slice_ref = SliceRef(
            slice_id="auth",
            layer="l1",
            worktree_path=str(slice_root),
        )
        run_ctx = RunContext(
            run_id="run-1",
            workspace_root=str(tmp_path),
            max_iterations=3,
            max_iterations_by_layer={"l1": 3, "l2": 3, "l3": 3},
        )

        result = loop.run_slice(slice_ref, run_ctx)

        assert result.status == "MAX_ITERATIONS"
        assert result.iterations == 3
        assert result.remaining_gaps > 0


class TestPromotionLoopRunSliceBlocked:
    """Test PromotionLoop.run_slice() when under-spec blocks progress."""

    def test_returns_blocked(self, tmp_path: Path) -> None:
        """run_slice() with BLOCKED step returns BLOCKED status."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        loop = PromotionLoop(
            workspace_root=tmp_path,
            steps=[BlockingStep()],
        )

        slice_ref = SliceRef(
            slice_id="auth",
            layer="l1",
            worktree_path=str(slice_root),
        )
        run_ctx = RunContext(
            run_id="run-1",
            workspace_root=str(tmp_path),
            max_iterations=10,
            max_iterations_by_layer={"l1": 10, "l2": 10, "l3": 10},
        )

        result = loop.run_slice(slice_ref, run_ctx)

        assert result.status == "BLOCKED"
        assert result.iterations == 1
        assert result.blocked_questions == ["What should X do?"]


class TestPromotionLoopRunSliceMaxIterations:
    """Test PromotionLoop.run_slice() hitting max_iterations."""

    def test_returns_max_iterations(self, tmp_path: Path) -> None:
        """run_slice() returns MAX_ITERATIONS when loop does not converge."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        loop = PromotionLoop(
            workspace_root=tmp_path,
            steps=[PersistentGapsStep()],
        )

        slice_ref = SliceRef(
            slice_id="auth",
            layer="l1",
            worktree_path=str(slice_root),
        )
        run_ctx = RunContext(
            run_id="run-1",
            workspace_root=str(tmp_path),
            max_iterations=2,
            max_iterations_by_layer={"l1": 2, "l2": 2, "l3": 2},
        )

        result = loop.run_slice(slice_ref, run_ctx)

        assert result.status == "MAX_ITERATIONS"
        assert result.iterations == 2


class TestPromotionLoopRunSliceRetry:
    """Test PromotionLoop.run_slice() with RETRY step."""

    def test_retry_restarts_iteration(self, tmp_path: Path) -> None:
        """run_slice() retries when step returns RETRY, then converges."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        retry_step = RetryStep()

        loop = PromotionLoop(
            workspace_root=tmp_path,
            steps=[retry_step, NoGapsStep()],
        )

        slice_ref = SliceRef(
            slice_id="auth",
            worktree_path=str(slice_root),
        )
        run_ctx = RunContext(
            run_id="run-1",
            workspace_root=str(tmp_path),
            max_iterations=5,
        )

        result = loop.run_slice(slice_ref, run_ctx)

        assert result.status == "COMPLETE"
        # First iteration: retry_step returns RETRY -> restart
        # Second iteration: retry_step returns OK, no_gaps clears gaps -> COMPLETE
        assert result.iterations == 2
        assert len(result.demotion_tickets) == 1


class TestPromotionLoopRunSliceFail:
    """Test PromotionLoop.run_slice() with FAIL step."""

    def test_returns_failed(self, tmp_path: Path) -> None:
        """run_slice() returns FAILED when a step returns FAIL."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        loop = PromotionLoop(
            workspace_root=tmp_path,
            steps=[FailStep()],
        )

        slice_ref = SliceRef(
            slice_id="auth",
            worktree_path=str(slice_root),
        )
        run_ctx = RunContext(
            run_id="run-1",
            workspace_root=str(tmp_path),
            max_iterations=5,
        )

        result = loop.run_slice(slice_ref, run_ctx)

        assert result.status == "FAILED"
        assert result.error == "fatal error"


# ======================================================================
# PromotionLoop.run_slices()
# ======================================================================


class TestPromotionLoopRunSlices:
    """Tests for PromotionLoop.run_slices() multi-slice processing."""

    def test_processes_multiple_slices(self, tmp_path: Path) -> None:
        """run_slices() processes all slices and returns results."""
        s1 = tmp_path / "s1"
        s2 = tmp_path / "s2"
        s1.mkdir()
        s2.mkdir()

        loop = PromotionLoop(
            workspace_root=tmp_path,
            steps=[NoGapsStep()],
        )

        refs = [
            SliceRef(slice_id="auth", worktree_path=str(s1)),
            SliceRef(slice_id="payment", worktree_path=str(s2)),
        ]
        ctx = RunContext(
            run_id="run-1",
            workspace_root=str(tmp_path),
        )

        results = loop.run_slices(refs, ctx)

        assert len(results) == 2
        assert results[0].slice_id == "auth"
        assert results[0].status == "COMPLETE"
        assert results[1].slice_id == "payment"
        assert results[1].status == "COMPLETE"

    def test_continues_after_failure(self, tmp_path: Path) -> None:
        """run_slices() continues processing after a slice failure."""
        s1 = tmp_path / "s1"
        s2 = tmp_path / "s2"
        s1.mkdir()
        s2.mkdir()

        loop = PromotionLoop(
            workspace_root=tmp_path,
            steps=[FailStep()],
        )

        refs = [
            SliceRef(slice_id="failing", worktree_path=str(s1)),
            SliceRef(slice_id="also-failing", worktree_path=str(s2)),
        ]
        ctx = RunContext(
            run_id="run-1",
            workspace_root=str(tmp_path),
        )

        results = loop.run_slices(refs, ctx)

        assert len(results) == 2
        assert results[0].status == "FAILED"
        assert results[1].status == "FAILED"


# ======================================================================
# CoordinateStep
# ======================================================================


class TestCoordinateStep:
    """Tests for CoordinateStep."""

    def test_no_under_spec_events_returns_ok(self) -> None:
        """CoordinateStep with no under-spec events returns OK for L1."""
        ctx = SliceContext(layer="l1")
        bundle = EvidenceBundle()
        bundle.implementation = ImplementationRef(under_spec_events=[])

        step = CoordinateStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"

    def test_l1_with_signals_returns_waiting(self, tmp_path: Path) -> None:
        """CoordinateStep with under-spec events on L1 returns WAITING."""
        ctx = SliceContext(
            slice_id="test-slice",
            layer="l1",
            workspace_root=str(tmp_path),
            run_id="run-1",
        )
        bundle = EvidenceBundle(
            run_id="run-1",
            slice_id="test-slice",
            iteration=1,
            workspace_root=str(tmp_path),
        )
        bundle.implementation = ImplementationRef(
            under_spec_events=[
                {"kind": "MISSING_CONSTRAINT", "question": "What format for output?"}
            ]
        )

        step = CoordinateStep()
        result = step.run(ctx, bundle)

        assert result.status == "WAITING"

    def test_l1_with_planner_calls_triage(self, tmp_path: Path) -> None:
        """CoordinateStep invokes planner.triage_signal for L1 signals."""
        planner = MagicMock()
        ctx = SliceContext(
            slice_id="test-slice",
            layer="l1",
            workspace_root=str(tmp_path),
            run_id="run-1",
        )
        bundle = EvidenceBundle(
            run_id="run-1",
            slice_id="test-slice",
            iteration=1,
            workspace_root=str(tmp_path),
        )
        bundle.implementation = ImplementationRef(
            under_spec_events=[{"kind": "AMBIGUITY", "question": "Which API version?"}]
        )

        step = CoordinateStep(planner=planner)
        result = step.run(ctx, bundle)

        assert result.status == "WAITING"
        assert planner.triage_signal.call_count == 1

    def test_l1_writes_signals_to_iteration_dir(self, tmp_path: Path) -> None:
        """CoordinateStep writes signals.json to iteration directory."""
        ctx = SliceContext(
            slice_id="test-slice",
            layer="l1",
            workspace_root=str(tmp_path),
            run_id="run-1",
        )
        bundle = EvidenceBundle(
            run_id="run-1",
            slice_id="test-slice",
            iteration=1,
            workspace_root=str(tmp_path),
        )
        bundle.implementation = ImplementationRef(
            under_spec_events=[{"kind": "MISSING_CONSTRAINT", "question": "What format?"}]
        )

        step = CoordinateStep()
        result = step.run(ctx, bundle)

        assert result.status == "WAITING"
        # Verify signals.json was written
        iteration_dir = bundle.iter_dir(tmp_path)
        signals_path = iteration_dir / "signals.json"
        assert signals_path.exists()

    @patch(
        "spec_manager.refinement.interactive.research.coordinator.run_agent",
        side_effect=RuntimeError("No LLM in test"),
    )
    def test_l2_delegates_to_under_spec(self, _mock_agent, tmp_path: Path) -> None:
        """CoordinateStep for L2 uses existing under-spec logic."""
        ctx = SliceContext(
            slice_id="test-slice",
            layer="l2",
            workspace_root=str(tmp_path),
            mode="auto",
        )
        bundle = EvidenceBundle()
        bundle.implementation = ImplementationRef(
            under_spec_events=[
                {"event_id": "evt-1", "kind": "MISSING_CONSTRAINT", "question": "What should X do?"}
            ]
        )

        step = CoordinateStep()
        result = step.run(ctx, bundle)

        # L2/L3 uses UnderSpecManager which blocks on unresolvable events
        assert result.status == "BLOCKED"
        assert "unresolvable" in result.error
        assert bundle.status == "BLOCKED"

    def test_l3_no_events_returns_ok(self) -> None:
        """CoordinateStep with no events for L3 returns OK."""
        ctx = SliceContext(layer="l3")
        bundle = EvidenceBundle()
        bundle.implementation = ImplementationRef(under_spec_events=[])

        step = CoordinateStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"


# ======================================================================
# ImplementStep L1 without intentions
# ======================================================================


class TestImplementStepL1NoIntentions:
    """Tests for ImplementStep L1 running without plan intentions."""

    def test_l1_runs_without_intentions(self, tmp_path: Path) -> None:
        """ImplementStep for L1 proceeds even with empty intentions."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()
        (slice_root / "main.py").write_text("# SPEC: implement greeting\ndef greet(): pass")

        ctx = SliceContext(
            layer="l1",
            slice_root=str(slice_root),
            workspace_root=str(tmp_path),
            run_id="run-1",
        )
        bundle = EvidenceBundle(
            run_id="run-1",
            slice_id="test",
            iteration=1,
            workspace_root=str(tmp_path),
        )
        bundle.plan = PlanRef(intentions=[])  # no intentions

        step = ImplementStep()
        result = step.run(ctx, bundle)

        # L1 should still attempt implementation even with no intentions
        assert result.status == "OK"
        assert isinstance(bundle.implementation, ImplementationRef)

    def test_l2_skips_without_intentions(self) -> None:
        """ImplementStep for L2 returns early with no intentions."""
        ctx = SliceContext(layer="l2")
        bundle = EvidenceBundle()
        bundle.plan = PlanRef(intentions=[])

        step = ImplementStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"
        assert bundle.implementation.applied_edits == []


# ======================================================================
# StepResult and SliceResult with WAITING
# ======================================================================


class TestWaitingStatus:
    """Tests for WAITING status in StepResult and SliceResult."""

    def test_step_result_waiting(self) -> None:
        """StepResult supports WAITING status."""
        sr = StepResult(status="WAITING")
        assert sr.status == "WAITING"

    def test_slice_result_waiting(self) -> None:
        """SliceResult supports WAITING status with pending_signals and wake_count."""
        sr = SliceResult(
            slice_id="test",
            status="WAITING",
            pending_signals=[{"question": "What?", "kind": "AMBIGUITY"}],
            wake_count=2,
        )
        assert sr.status == "WAITING"
        assert len(sr.pending_signals) == 1
        assert sr.wake_count == 2

    def test_slice_result_defaults(self) -> None:
        """SliceResult defaults have empty pending_signals and zero wake_count."""
        sr = SliceResult()
        assert sr.pending_signals == []
        assert sr.wake_count == 0


# ======================================================================
# PromotionLoop handles WAITING
# ======================================================================


class WaitingStep:
    """A step that returns WAITING status."""

    name = "WAITING_STEP"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        bundle.implementation = ImplementationRef(
            under_spec_events=[{"kind": "MISSING_CONSTRAINT", "question": "What should X do?"}]
        )
        return StepResult(status="WAITING")


class TestPromotionLoopWaiting:
    """Tests for PromotionLoop.run_slice() with WAITING steps."""

    def test_returns_waiting(self, tmp_path: Path) -> None:
        """run_slice() with WAITING step returns WAITING status."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        loop = PromotionLoop(
            workspace_root=tmp_path,
            steps=[WaitingStep()],
        )

        slice_ref = SliceRef(
            slice_id="auth",
            layer="l1",
            worktree_path=str(slice_root),
        )
        run_ctx = RunContext(
            run_id="run-1",
            workspace_root=str(tmp_path),
            max_iterations=10,
        )

        result = loop.run_slice(slice_ref, run_ctx)

        assert result.status == "WAITING"
        assert result.iterations == 1
        assert result.wake_count == 1
        assert len(result.pending_signals) == 1
        assert result.pending_signals[0]["question"] == "What should X do?"

    def test_waiting_does_not_count_for_stagnation(self, tmp_path: Path) -> None:
        """WAITING iterations should not be appended to gap_history for stagnation."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        # A WAITING step returns early from the loop, so gap_history doesn't grow.
        # This means a slice that goes WAITING repeatedly won't trigger stagnation.
        loop = PromotionLoop(
            workspace_root=tmp_path,
            steps=[WaitingStep()],
        )

        slice_ref = SliceRef(
            slice_id="auth",
            layer="l1",
            worktree_path=str(slice_root),
        )
        run_ctx = RunContext(
            run_id="run-1",
            workspace_root=str(tmp_path),
            max_iterations=10,
        )

        result = loop.run_slice(slice_ref, run_ctx)

        # WAITING returns immediately — no stagnation possible
        assert result.status == "WAITING"
        assert result.iterations == 1


# ======================================================================
# RunContext.max_wait_cycles
# ======================================================================


class TestRunContextMaxWaitCycles:
    """Tests for max_wait_cycles on RunContext."""

    def test_default_max_wait_cycles(self) -> None:
        """RunContext has max_wait_cycles=10 by default."""
        ctx = RunContext()
        assert ctx.max_wait_cycles == 10

    def test_custom_max_wait_cycles(self) -> None:
        """RunContext allows custom max_wait_cycles."""
        ctx = RunContext(max_wait_cycles=5)
        assert ctx.max_wait_cycles == 5


# ======================================================================
# CoordinateStep L1 UserQuestionSignal emission (Gap 4)
# ======================================================================


class TestCoordinateStepL1UserQuestionSignals:
    """Tests for CoordinateStep._coordinate_l1() UserQuestionSignal emission."""

    def test_emits_user_question_signals(self, tmp_path: Path) -> None:
        """_coordinate_l1 emits UserQuestionSignals for events with question field."""
        from spec_manager.orchestration.intent_agent.signals import (
            UserQuestionSignalStore,
        )

        ctx = SliceContext(
            slice_id="test-slice",
            layer="l1",
            workspace_root=str(tmp_path),
            run_id="run-uq",
        )
        bundle = EvidenceBundle(
            run_id="run-uq",
            slice_id="test-slice",
            iteration=1,
            workspace_root=str(tmp_path),
        )
        bundle.implementation = ImplementationRef(
            under_spec_events=[
                {
                    "event_id": "evt-1",
                    "kind": "MISSING_CONSTRAINT",
                    "question": "What format for output?",
                },
                {
                    "event_id": "evt-2",
                    "kind": "AMBIGUITY",
                    "question": "Which API version?",
                },
            ]
        )

        step = CoordinateStep()
        result = step.run(ctx, bundle)

        assert result.status == "WAITING"

        # Read back UserQuestionSignals
        run_dir = tmp_path / ".pdd_runs" / "run-uq"
        store = UserQuestionSignalStore(run_dir)
        signals = store.read_all()

        assert len(signals) == 2
        assert signals[0].source.kind == "PROMOTION_LOOP"
        assert signals[0].source.slice_id == "test-slice"
        assert signals[0].source.layer == "l1"
        assert signals[0].source.trace_id == "evt-1"
        assert signals[0].question.text == "What format for output?"
        assert signals[0].question.canonical_key_hint == "coordinate_l1.evt-1"  # gitleaks:allow
        assert signals[0].context.blocking.severity == "BLOCKING"
        assert "test-slice" in signals[0].context.blocking.blocked_slices
        assert signals[0].run_id == "run-uq"

        assert signals[1].source.trace_id == "evt-2"
        assert signals[1].question.text == "Which API version?"

    def test_skips_events_without_question(self, tmp_path: Path) -> None:
        """_coordinate_l1 skips UserQuestionSignals for events with empty question."""
        from spec_manager.orchestration.intent_agent.signals import (
            UserQuestionSignalStore,
        )

        ctx = SliceContext(
            slice_id="test-slice",
            layer="l1",
            workspace_root=str(tmp_path),
            run_id="run-skip",
        )
        bundle = EvidenceBundle(
            run_id="run-skip",
            slice_id="test-slice",
            iteration=1,
            workspace_root=str(tmp_path),
        )
        bundle.implementation = ImplementationRef(
            under_spec_events=[
                {"event_id": "evt-1", "kind": "MISSING_CONSTRAINT", "question": "Real question?"},
                {"event_id": "evt-no-q", "kind": "MISSING_CONSTRAINT", "question": ""},
                {"event_id": "evt-no-q2", "kind": "AMBIGUITY"},  # no question key at all
            ]
        )

        step = CoordinateStep()
        result = step.run(ctx, bundle)

        assert result.status == "WAITING"

        # Only one signal — the event with an actual question
        run_dir = tmp_path / ".pdd_runs" / "run-skip"
        store = UserQuestionSignalStore(run_dir)
        signals = store.read_all()

        assert len(signals) == 1
        assert signals[0].question.text == "Real question?"

    def test_payload_contains_raw_event(self, tmp_path: Path) -> None:
        """_coordinate_l1 stores the raw event dict as signal payload."""
        from spec_manager.orchestration.intent_agent.signals import (
            UserQuestionSignalStore,
        )

        ctx = SliceContext(
            slice_id="test-slice",
            layer="l1",
            workspace_root=str(tmp_path),
            run_id="run-payload",
        )
        bundle = EvidenceBundle(
            run_id="run-payload",
            slice_id="test-slice",
            iteration=1,
            workspace_root=str(tmp_path),
        )
        raw_event = {
            "event_id": "evt-p",
            "kind": "MISSING_CONSTRAINT",
            "question": "What timeout?",
            "context": {"api": "payments"},
        }
        bundle.implementation = ImplementationRef(under_spec_events=[raw_event])

        step = CoordinateStep()
        step.run(ctx, bundle)

        run_dir = tmp_path / ".pdd_runs" / "run-payload"
        store = UserQuestionSignalStore(run_dir)
        signals = store.read_all()

        assert len(signals) == 1
        assert signals[0].payload == raw_event

    def test_coordination_signals_still_written(self, tmp_path: Path) -> None:
        """_coordinate_l1 still writes CoordinationSignals alongside UserQuestionSignals."""
        ctx = SliceContext(
            slice_id="test-slice",
            layer="l1",
            workspace_root=str(tmp_path),
            run_id="run-both",
        )
        bundle = EvidenceBundle(
            run_id="run-both",
            slice_id="test-slice",
            iteration=1,
            workspace_root=str(tmp_path),
        )
        bundle.implementation = ImplementationRef(
            under_spec_events=[
                {"event_id": "evt-1", "kind": "MISSING_CONSTRAINT", "question": "What format?"}
            ]
        )

        step = CoordinateStep()
        result = step.run(ctx, bundle)

        assert result.status == "WAITING"

        # CoordinationSignals written to iteration dir
        iteration_dir = bundle.iter_dir(tmp_path)
        signals_path = iteration_dir / "signals.json"
        assert signals_path.exists()

        # UserQuestionSignals also written
        from spec_manager.orchestration.intent_agent.signals import (
            UserQuestionSignalStore,
        )

        run_dir = tmp_path / ".pdd_runs" / "run-both"
        store = UserQuestionSignalStore(run_dir)
        signals = store.read_all()
        assert len(signals) == 1
