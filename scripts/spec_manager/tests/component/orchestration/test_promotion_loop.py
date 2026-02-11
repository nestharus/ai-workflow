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
    UnderSpecCheckStep,
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

    def test_gaps_produce_intentions(self) -> None:
        """PlanStep creates intentions from open gaps."""
        ctx = SliceContext()
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
        assert len(bundle.plan.intentions) == 2
        assert bundle.plan.intentions[0]["target_file"] == "a.py"
        assert "stub function" in bundle.plan.intentions[0]["approach"]


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
# UnderSpecCheckStep
# ======================================================================


class TestUnderSpecCheckStep:
    """Tests for UnderSpecCheckStep.run()."""

    def test_no_events_returns_ok(self) -> None:
        """UnderSpecCheckStep with no under-spec events returns OK."""
        ctx = SliceContext()
        bundle = EvidenceBundle()
        bundle.implementation = ImplementationRef(under_spec_events=[])

        step = UnderSpecCheckStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"

    def test_covered_events_return_ok(self, tmp_path: Path) -> None:
        """UnderSpecCheckStep with constraint-covered events returns OK."""
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

        ctx = SliceContext(slice_id="test-slice", workspace_root=str(tmp_path))
        bundle = EvidenceBundle()
        bundle.implementation = ImplementationRef(
            under_spec_events=[
                {"event_id": "evt-1", "kind": "AMBIGUITY", "question": "Which format?"}
            ]
        )

        step = UnderSpecCheckStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"

    @patch(
        "spec_manager.refinement.interactive.research.coordinator.run_agent",
        side_effect=RuntimeError("No LLM in test"),
    )
    def test_uncovered_events_return_blocked(self, _mock_agent, tmp_path: Path) -> None:
        """UnderSpecCheckStep with no matching constraints returns BLOCKED."""

        ctx = SliceContext(
            slice_id="test-slice",
            workspace_root=str(tmp_path),
            mode="auto",
        )
        bundle = EvidenceBundle()
        bundle.implementation = ImplementationRef(
            under_spec_events=[
                {"event_id": "evt-2", "kind": "MISSING_CONSTRAINT", "question": "What should X do?"}
            ]
        )

        step = UnderSpecCheckStep()
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
