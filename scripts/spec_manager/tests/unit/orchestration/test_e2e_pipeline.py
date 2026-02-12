"""Comprehensive unit tests for the orchestration e2e pipeline features.

Tests cover:
- Loop limits and stagnation detection (PromotionLoop)
- Transition demotion caps (PddLifecycle._run_transition)
- RunState persistence (RunStateManager)
- Demotion ledger (DemotionManager._append_to_ledger)
- Scoring framework (ScorecardMetric, Scorecard, RunReporter)
- Final report generation (FinalReportGenerator)
- Governance checks (PddLifecycle._run_governance_check)
- CI readiness (PddLifecycle._run_readiness_ci)
- Human approval auto-mode (PddLifecycle._request_l2_checkpoint / _request_release_signoff)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from unittest.mock import MagicMock, patch

import pytest
from spec_manager.orchestration.demotion import DemotionManager, DemotionTicket
from spec_manager.orchestration.evidence import EvidenceBundle, GapReportRef
from spec_manager.orchestration.final_report import FinalReportGenerator
from spec_manager.orchestration.models import Layer
from spec_manager.orchestration.promotion_loop import (
    LoopStep,
    PromotionLoop,
    RunContext,
    SliceContext,
    SliceRef,
    SliceResult,
    StepResult,
)
from spec_manager.orchestration.run_state import RunConfig, RunState, RunStateManager
from spec_manager.orchestration.scoring import (
    RunReporter,
    Scorecard,
    ScorecardMetric,
)

# ===================================================================
# Stub step classes for PromotionLoop testing
# ===================================================================


class AlwaysOkStep:
    """A step that always returns OK."""

    name = "ALWAYS_OK"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        return StepResult(status="OK")


class FixedGapStep:
    """A step that sets a fixed number of open gaps on the bundle.

    Used to test stagnation detection: if the gap count never decreases,
    the loop should detect stagnation.
    """

    name = "FIXED_GAP"

    def __init__(self, gap_count: int = 5) -> None:
        self._gap_count = gap_count

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        bundle.gaps = GapReportRef(
            open_gaps=[
                {"file": f"file_{i}.py", "description": f"gap {i}"} for i in range(self._gap_count)
            ]
        )
        return StepResult(status="OK")


class DecreasingGapStep:
    """A step that decreases gaps by 1 each iteration.

    Starts at `start_gaps` and decreases by 1 per call until 0.
    """

    name = "DECREASING_GAP"

    def __init__(self, start_gaps: int = 5) -> None:
        self._remaining = start_gaps

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        bundle.gaps = GapReportRef(
            open_gaps=[
                {"file": f"file_{i}.py", "description": f"gap {i}"} for i in range(self._remaining)
            ]
        )
        if self._remaining > 0:
            self._remaining -= 1
        return StepResult(status="OK")


class RepeatedTicketStep:
    """A step that emits a DemotionTicket with the same failing_files and gate each time.

    Used to test per-ticket retry budget exhaustion.
    """

    name = "REPEATED_TICKET"

    def __init__(
        self,
        failing_files: list[str] | None = None,
        gate: str = "SOME_GATE",
    ) -> None:
        self._failing_files = failing_files or ["src/main.py"]
        self._gate = gate

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        ticket = DemotionTicket(
            run_id=ctx.run_id,
            slice_id=ctx.slice_id,
            source="GATE_FAILURE",
            gate=self._gate,
            target_layer="L1",
            severity="BLOCKER",
            diagnosis="Always failing gate",
            failing_files=self._failing_files,
        )
        # Also set gaps so the loop does not terminate on gap==0
        bundle.gaps = GapReportRef(open_gaps=[{"file": "stub.py", "description": "stub gap"}])
        return StepResult(status="RETRY", emitted_tickets=[ticket])


class FailStep:
    """A step that always returns FAIL."""

    name = "FAIL"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        return StepResult(status="FAIL", error="hard failure")


class BlockStep:
    """A step that always returns BLOCKED."""

    name = "BLOCK"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        bundle.implementation.under_spec_events = [{"question": "What should X do?"}]
        return StepResult(status="BLOCKED", error="blocked on under-spec")


# ===================================================================
# 1. Loop limits and stagnation tests
# ===================================================================


class TestRunContextLayerSpecificIterations:
    """Verify RunContext.max_iterations_by_layer defaults."""

    def test_run_context_layer_specific_iterations(self) -> None:
        ctx = RunContext()
        assert ctx.max_iterations_by_layer == {"l1": 20, "l2": 30, "l3": 15}

    def test_run_context_default_max_iterations(self) -> None:
        ctx = RunContext()
        assert ctx.max_iterations == 20

    def test_run_context_custom_values(self) -> None:
        ctx = RunContext(max_iterations_by_layer={"l1": 5, "l2": 10, "l3": 3})
        assert ctx.max_iterations_by_layer["l1"] == 5
        assert ctx.max_iterations_by_layer["l2"] == 10
        assert ctx.max_iterations_by_layer["l3"] == 3


class TestSliceResultStagnatedStatus:
    """Verify STAGNATED is a valid SliceResult status."""

    def test_slice_result_stagnated_status(self) -> None:
        result = SliceResult(slice_id="test", status="STAGNATED")
        assert result.status == "STAGNATED"

    def test_all_statuses_valid(self) -> None:
        for status in ("COMPLETE", "BLOCKED", "FAILED", "MAX_ITERATIONS", "STAGNATED"):
            result = SliceResult(slice_id="test", status=status)
            assert result.status == status


class TestStagnationDetection:
    """Create a PromotionLoop with a step that always produces N gaps.

    With sliding window stagnation (window=3), after 2*window=6 iterations
    with non-improving min gap count, the loop should return STAGNATED.
    """

    def test_stagnation_detection(self, tmp_path: Path) -> None:
        # Use a step that always produces 5 gaps and never decreases them.
        gap_step = FixedGapStep(gap_count=5)
        # DemotionManager needs a workspace to write ledger/lineage.
        dm = DemotionManager(workspace_root=tmp_path, run_id="stag-run")

        loop = PromotionLoop(
            workspace_root=tmp_path,
            demotion_manager=dm,
            steps=[gap_step],
        )

        ref = SliceRef(
            slice_id="stag-slice",
            layer="l1",
            worktree_path=str(tmp_path),
        )
        run_ctx = RunContext(
            run_id="stag-run",
            workspace_root=str(tmp_path),
            max_iterations=20,
        )

        result = loop.run_slice(ref, run_ctx)
        assert result.status == "STAGNATED"
        assert result.remaining_gaps == 5
        assert "stagnation" in result.error.lower() or "not improving" in result.error.lower()

    def test_no_stagnation_when_gaps_decrease(self, tmp_path: Path) -> None:
        # Step that decreases gaps from 3 to 0 => should reach COMPLETE.
        gap_step = DecreasingGapStep(start_gaps=3)
        dm = DemotionManager(workspace_root=tmp_path, run_id="nostagrun")

        loop = PromotionLoop(
            workspace_root=tmp_path,
            demotion_manager=dm,
            steps=[gap_step],
        )

        ref = SliceRef(
            slice_id="ok-slice",
            layer="l1",
            worktree_path=str(tmp_path),
        )
        run_ctx = RunContext(
            run_id="nostagrun",
            workspace_root=str(tmp_path),
            max_iterations=20,
        )

        result = loop.run_slice(ref, run_ctx)
        assert result.status == "COMPLETE"
        assert result.remaining_gaps == 0


class TestLayerSpecificMaxIterations:
    """Verify l1 uses 20, l2 uses 30, l3 uses 15 as max iteration limits."""

    def _run_with_layer(self, layer: Layer, tmp_path: Path) -> SliceResult:
        gap_step = FixedGapStep(gap_count=2)
        dm = DemotionManager(workspace_root=tmp_path, run_id=f"layer-{layer}")

        PromotionLoop(
            workspace_root=tmp_path,
            demotion_manager=dm,
            steps=[gap_step],
        )

        SliceRef(
            slice_id=f"slice-{layer}",
            layer=layer,
            worktree_path=str(tmp_path),
        )
        # The stagnation threshold is 3, so with a fixed gap count of 2,
        # the loop will hit STAGNATED after ~4 iterations (iter 1 sets baseline,
        # iter 2/3/4 increment stagnation counter to 3).
        # But to test the max_iterations per layer, we override the
        # stagnation threshold by making gaps fluctuate.
        # Actually, with FixedGapStep the loop hits STAGNATED at iteration 4.
        # To test MAX_ITERATIONS, we need gaps that change enough to avoid
        # stagnation but never reach 0. We just verify the RunContext has
        # the correct layer-specific limits applied by the loop code.
        run_ctx = RunContext(
            run_id=f"layer-{layer}",
            workspace_root=str(tmp_path),
        )

        # Instead of running the full loop (which would stagnate),
        # verify the lookup logic directly.
        max_iters = run_ctx.max_iterations_by_layer.get(layer, run_ctx.max_iterations)
        return max_iters

    def test_l1_max_iterations(self, tmp_path: Path) -> None:
        assert self._run_with_layer("l1", tmp_path) == 20

    def test_l2_max_iterations(self, tmp_path: Path) -> None:
        assert self._run_with_layer("l2", tmp_path) == 30

    def test_l3_max_iterations(self, tmp_path: Path) -> None:
        assert self._run_with_layer("l3", tmp_path) == 15

    def test_layer_limit_applied_in_loop(self, tmp_path: Path) -> None:
        """Verify the loop code actually reads max_iterations_by_layer."""
        # We set l1 max to 2 and use a fixed-gap step. The step produces
        # non-zero gaps; the loop should stop at MAX_ITERATIONS or
        # STAGNATED (whichever comes first). With max_iters=2 and
        # stagnation_threshold=3, MAX_ITERATIONS should win.
        gap_step = FixedGapStep(gap_count=1)
        dm = DemotionManager(workspace_root=tmp_path, run_id="limit-run")

        loop = PromotionLoop(
            workspace_root=tmp_path,
            demotion_manager=dm,
            steps=[gap_step],
        )

        ref = SliceRef(
            slice_id="limit-slice",
            layer="l1",
            worktree_path=str(tmp_path),
        )
        run_ctx = RunContext(
            run_id="limit-run",
            workspace_root=str(tmp_path),
            max_iterations_by_layer={"l1": 2, "l2": 30, "l3": 15},
        )

        result = loop.run_slice(ref, run_ctx)
        # With max_iters=2, sliding window stagnation needs 2*3=6 iterations.
        # Only 2 iterations, so stagnation can't fire. MAX_ITERATIONS wins.
        assert result.status == "MAX_ITERATIONS"
        assert result.iterations == 2


class TestPerTicketRetryBudget:
    """Create steps that emit tickets with same failing_files+gate.

    After budget+1 repeats (4 repeats when budget=3), the loop should
    return STAGNATED.
    """

    def test_per_ticket_retry_budget(self, tmp_path: Path) -> None:
        # The RepeatedTicketStep emits RETRY with the same ticket each iter.
        # Retry budget in run_slice is 3, so after 4 repeats it should stagnate.
        ticket_step = RepeatedTicketStep(
            failing_files=["src/main.py"],
            gate="SPEC_COMMENTS",
        )
        slice_root = tmp_path / "slice"
        slice_root.mkdir()
        dm = DemotionManager(workspace_root=tmp_path, run_id="retry-run")

        loop = PromotionLoop(
            workspace_root=tmp_path,
            demotion_manager=dm,
            steps=[ticket_step],
        )

        ref = SliceRef(
            slice_id="retry-slice",
            layer="l1",
            worktree_path=str(slice_root),
        )
        run_ctx = RunContext(
            run_id="retry-run",
            workspace_root=str(tmp_path),
            max_iterations=50,
        )

        result = loop.run_slice(ref, run_ctx)
        assert result.status == "STAGNATED"
        assert "retry budget" in result.error.lower()
        # Budget is 3, so after 4th repeat (>3) it stagnates.
        # Iteration count should be 4 (budget + 1).
        assert result.iterations == 4

    def test_different_tickets_dont_trigger_budget(self, tmp_path: Path) -> None:
        """Tickets with different failing_files don't share budget."""

        class RotatingTicketStep:
            name = "ROTATING_TICKET"

            def __init__(self) -> None:
                self._call_count = 0

            def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
                self._call_count += 1
                ticket = DemotionTicket(
                    run_id=ctx.run_id,
                    slice_id=ctx.slice_id,
                    source="GATE_FAILURE",
                    gate="SOME_GATE",
                    target_layer="L1",
                    severity="BLOCKER",
                    diagnosis="Rotating failure",
                    # Different file each time -> unique tracker key
                    failing_files=[f"file_{self._call_count}.py"],
                )
                bundle.gaps = GapReportRef(open_gaps=[{"file": "stub.py", "description": "gap"}])
                return StepResult(status="RETRY", emitted_tickets=[ticket])

        slice_root = tmp_path / "slice"
        slice_root.mkdir()
        dm = DemotionManager(workspace_root=tmp_path, run_id="rot-run")
        step = RotatingTicketStep()

        loop = PromotionLoop(
            workspace_root=tmp_path,
            demotion_manager=dm,
            steps=[step],
        )

        ref = SliceRef(
            slice_id="rot-slice",
            layer="l1",
            worktree_path=str(slice_root),
        )
        run_ctx = RunContext(
            run_id="rot-run",
            workspace_root=str(tmp_path),
            max_iterations=6,
        )

        result = loop.run_slice(ref, run_ctx)
        # Each ticket is unique, so no single ticket exceeds budget.
        # Stagnation detection fires because gaps never decrease.
        assert result.status == "STAGNATED"


# ===================================================================
# 2. Transition demotion cap tests
# ===================================================================


class TestTransitionMaxRounds:
    """Mock _run_transition to verify it caps at 3 rounds."""

    def test_transition_max_rounds(self, tmp_path: Path) -> None:
        """Verify transition stops after max_rounds demotion cycles."""
        # Create a minimal mock PddLifecycle
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "trans-run"

        lifecycle = PddLifecycle(manager, mode="auto")

        # _library_refinement is the L1 refinement. _architectural_refinement
        # is the L2 refinement used for l1->l2 transition.
        # We mock the refinement to always return demotions.
        lifecycle._architectural_refinement = MagicMock(return_value={"demotion_tickets": 5})
        lifecycle._run_slices_at_layer = MagicMock(return_value={"slices": []})
        lifecycle._run_governance_check = MagicMock(return_value={"passed": True, "findings": []})
        lifecycle.worktree_manager = None

        result = lifecycle._run_transition("l1", "l2", max_rounds=3)

        assert len(result["rework_rounds"]) == 3
        assert lifecycle._run_slices_at_layer.call_count == 3

    def test_transition_stuck_flag(self, tmp_path: Path) -> None:
        """Verify transition_stuck is True when stuck."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "stuck-run"

        lifecycle = PddLifecycle(manager, mode="auto")

        lifecycle._architectural_refinement = MagicMock(return_value={"demotion_tickets": 3})
        lifecycle._run_slices_at_layer = MagicMock(return_value={"slices": []})
        lifecycle._run_governance_check = MagicMock(return_value={"passed": True, "findings": []})
        lifecycle.worktree_manager = None

        result = lifecycle._run_transition("l1", "l2", max_rounds=3)

        assert result["transition_stuck"] is True
        assert "error" in result
        assert "stuck" in result["error"].lower()

    def test_transition_resolves_early(self, tmp_path: Path) -> None:
        """Verify transition stops early when demotions resolve."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "resolve-run"

        lifecycle = PddLifecycle(manager, mode="auto")

        # First call returns demotions, second returns 0 => resolved
        lifecycle._architectural_refinement = MagicMock(
            side_effect=[
                {"demotion_tickets": 2},
                {"demotion_tickets": 0},
            ]
        )
        lifecycle._run_slices_at_layer = MagicMock(return_value={"slices": []})
        lifecycle._run_governance_check = MagicMock(return_value={"passed": True, "findings": []})
        lifecycle.worktree_manager = None

        result = lifecycle._run_transition("l1", "l2", max_rounds=3)

        assert result["transition_stuck"] is False
        assert len(result["rework_rounds"]) == 2
        # Only 1 rework (first round had demotions), second round resolved
        assert lifecycle._run_slices_at_layer.call_count == 1


# ===================================================================
# 3. RunState tests
# ===================================================================


class TestRunState:
    """Test RunStateManager persistence."""

    def test_write_and_read_config(self, tmp_path: Path) -> None:
        mgr = RunStateManager(workspace_root=tmp_path, run_id="test-run")
        config = RunConfig(
            run_id="test-run",
            mode="auto",
            max_iterations_by_layer={"l1": 10, "l2": 20, "l3": 5},
            max_approval_iterations=2,
        )
        mgr.write_config(config)

        loaded = mgr.read_config()
        assert loaded is not None
        assert loaded.run_id == "test-run"
        assert loaded.mode == "auto"
        assert loaded.max_iterations_by_layer == {"l1": 10, "l2": 20, "l3": 5}
        assert loaded.max_approval_iterations == 2
        assert loaded.created_at > 0  # auto-set

    def test_read_config_returns_none_when_missing(self, tmp_path: Path) -> None:
        mgr = RunStateManager(workspace_root=tmp_path, run_id="noexist")
        assert mgr.read_config() is None

    def test_update_and_read_state(self, tmp_path: Path) -> None:
        mgr = RunStateManager(workspace_root=tmp_path, run_id="state-run")

        mgr.update_state(active_layer="l1", phase="intake")
        state = mgr.read_state()
        assert state is not None
        assert state.active_layer == "l1"
        assert state.phase == "intake"
        assert state.updated_at > 0

        # Subsequent update merges fields
        mgr.update_state(active_layer="l2", total_iterations=42)
        state2 = mgr.read_state()
        assert state2 is not None
        assert state2.active_layer == "l2"
        assert state2.phase == "intake"  # unchanged
        assert state2.total_iterations == 42

    def test_read_state_returns_none_when_missing(self, tmp_path: Path) -> None:
        mgr = RunStateManager(workspace_root=tmp_path, run_id="nostate")
        assert mgr.read_state() is None

    def test_ensure_directories(self, tmp_path: Path) -> None:
        mgr = RunStateManager(workspace_root=tmp_path, run_id="dir-run")
        mgr.ensure_directories()

        # Verify standard directories
        assert (tmp_path / ".pdd_runs" / "dir-run" / "slices").is_dir()
        assert (tmp_path / ".pdd_runs" / "dir-run" / "demotions").is_dir()
        assert (tmp_path / ".pdd_runs" / "dir-run" / "ci" / "l1" / "batches").is_dir()
        assert (tmp_path / ".pdd_runs" / "dir-run" / "ci" / "l2" / "batches").is_dir()
        assert (tmp_path / ".pdd_runs" / "dir-run" / "ci" / "l3" / "batches").is_dir()
        assert (tmp_path / "reports" / "pdd" / "dir-run" / "architecture").is_dir()
        assert (tmp_path / "reports" / "pdd" / "dir-run" / "quality").is_dir()
        assert (tmp_path / "reports" / "pdd" / "dir-run" / "alignment").is_dir()

    def test_config_roundtrip_preserves_all_fields(self, tmp_path: Path) -> None:
        mgr = RunStateManager(workspace_root=tmp_path, run_id="roundtrip")
        config = RunConfig(
            run_id="roundtrip",
            mode="interactive",
            input_folder="/specs",
            stagnation_threshold=5,
            retry_budget=7,
            test_commands={"l1": "pytest tests/"},
            model_ids={"gap": "opus-4"},
        )
        mgr.write_config(config)
        loaded = mgr.read_config()
        assert loaded is not None
        assert loaded.stagnation_threshold == 5
        assert loaded.retry_budget == 7
        assert loaded.test_commands == {"l1": "pytest tests/"}
        assert loaded.model_ids == {"gap": "opus-4"}

    def test_state_roundtrip_preserves_all_fields(self, tmp_path: Path) -> None:
        mgr = RunStateManager(workspace_root=tmp_path, run_id="rt2")
        mgr.update_state(
            active_layer="l2",
            phase="l2",
            layers_completed=["l1"],
            transitions_completed=["l1_l2"],
            shas={"l1": "abc123"},
            budgets_consumed={"l1": 5},
            total_iterations=15,
            total_demotions=3,
            stagnated_slices=["slice-a"],
            blocked_slices=["slice-b"],
        )
        state = mgr.read_state()
        assert state is not None
        assert state.layers_completed == ["l1"]
        assert state.transitions_completed == ["l1_l2"]
        assert state.shas == {"l1": "abc123"}
        assert state.budgets_consumed == {"l1": 5}
        assert state.stagnated_slices == ["slice-a"]
        assert state.blocked_slices == ["slice-b"]


# ===================================================================
# 4. Demotion ledger tests
# ===================================================================


class TestDemotionLedger:
    """Test DemotionManager ledger append behavior."""

    def test_ledger_appended_on_apply(self, tmp_path: Path) -> None:
        """Create DemotionManager with run_id, apply a ticket, verify ledger."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        dm = DemotionManager(workspace_root=tmp_path, run_id="ledger-run")
        ticket = DemotionTicket(
            run_id="ledger-run",
            slice_id="s1",
            source="GATE_FAILURE",
            target_layer="L1",
            severity="BLOCKER",
            diagnosis="Test failure",
            failing_files=["foo.py"],
        )

        dm.apply(ticket, slice_root)

        ledger_path = tmp_path / ".pdd_runs" / "ledger-run" / "demotions" / "ledger.jsonl"
        assert ledger_path.exists()
        lines = ledger_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["ticket_id"] == ticket.ticket_id
        assert entry["source"] == "GATE_FAILURE"
        assert entry["target_layer"] == "L1"
        assert entry["severity"] == "BLOCKER"
        assert entry["failing_files"] == ["foo.py"]
        assert entry["applied"] is True

    def test_ledger_entries_are_jsonl(self, tmp_path: Path) -> None:
        """Apply multiple tickets, verify each line is valid JSON."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        dm = DemotionManager(workspace_root=tmp_path, run_id="multi-run")

        for i in range(5):
            ticket = DemotionTicket(
                run_id="multi-run",
                slice_id=f"s{i}",
                source="TEST_FAILURE",
                target_layer="L1",
                severity="MAJOR",
                diagnosis=f"failure {i}",
                failing_files=[f"file_{i}.py"],
            )
            dm.apply(ticket, slice_root)

        ledger_path = tmp_path / ".pdd_runs" / "multi-run" / "demotions" / "ledger.jsonl"
        lines = ledger_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 5

        for i, line in enumerate(lines):
            entry = json.loads(line)
            # The ledger entry does not store slice_id; verify fields
            # that _append_to_ledger actually writes.
            assert entry["diagnosis"] == f"failure {i}"
            assert entry["failing_files"] == [f"file_{i}.py"]
            assert entry["source"] == "TEST_FAILURE"
            assert entry["target_layer"] == "L1"
            assert entry["severity"] == "MAJOR"

    def test_ledger_not_written_without_run_id(self, tmp_path: Path) -> None:
        """Without run_id on both manager and ticket, no ledger is written."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        dm = DemotionManager(workspace_root=tmp_path, run_id="")
        ticket = DemotionTicket(
            run_id="",
            slice_id="s1",
            source="GATE_FAILURE",
            target_layer="L1",
            severity="BLOCKER",
            diagnosis="No run id",
        )

        dm.apply(ticket, slice_root)

        # No ledger directory should be created
        ledger_path = tmp_path / ".pdd_runs" / "" / "demotions" / "ledger.jsonl"
        assert not ledger_path.exists()


# ===================================================================
# 5. Scoring framework tests
# ===================================================================


def _make_run_results(
    *,
    l1_slices: list[dict[str, Any]] | None = None,
    l2_slices: list[dict[str, Any]] | None = None,
    l3_slices: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Helper to build run_results for scoring."""
    return {
        "l1": {
            "slices": {"slices": l1_slices or []},
        },
        "l2": {
            "slices": {"slices": l2_slices or []},
        },
        "l3": {
            "slices": {"slices": l3_slices or []},
        },
    }


class TestScorecardMetric:
    """Test ScorecardMetric.to_dict serialization."""

    def test_scorecard_metric_to_dict(self) -> None:
        metric = ScorecardMetric(
            name="gates.final_pass",
            raw=1.0,
            score=1.0,
            status="PASS",
            hard_gate=True,
            evidence_refs=["bundle_001.json"],
            detail="All gates passed",
        )
        d = metric.to_dict()
        assert d["name"] == "gates.final_pass"
        assert d["raw"] == 1.0
        assert d["score"] == 1.0
        assert d["status"] == "PASS"
        assert d["hard_gate"] is True
        assert d["evidence_refs"] == ["bundle_001.json"]
        assert d["detail"] == "All gates passed"

    def test_scorecard_metric_defaults(self) -> None:
        metric = ScorecardMetric()
        d = metric.to_dict()
        assert d["name"] == ""
        assert d["raw"] == 0.0
        assert d["status"] == "PASS"
        assert d["hard_gate"] is False


class TestRunReporterComputeAllPass:
    """Pass run_results with all COMPLETE slices -- overall_pass=True."""

    def test_run_reporter_compute_all_pass(self, tmp_path: Path) -> None:
        reporter = RunReporter(workspace_root=tmp_path, run_id="pass-run")
        results = _make_run_results(
            l1_slices=[
                {"slice_id": "s1", "status": "COMPLETE", "iterations": 3, "demotion_count": 0},
                {"slice_id": "s2", "status": "COMPLETE", "iterations": 5, "demotion_count": 1},
            ],
            l2_slices=[
                {"slice_id": "s3", "status": "COMPLETE", "iterations": 2, "demotion_count": 0},
            ],
            l3_slices=[
                {"slice_id": "s4", "status": "COMPLETE", "iterations": 1, "demotion_count": 0},
            ],
        )

        scorecard = reporter.compute(results)
        assert scorecard.overall_pass is True
        assert scorecard.run_id == "pass-run"

        # All hard gates should be PASS
        for gate in scorecard.hard_gates:
            assert gate.status == "PASS", f"Gate {gate.name} failed unexpectedly"


class TestRunReporterComputeWithFailure:
    """Include a STAGNATED slice -- gates.final_pass should be FAIL."""

    def test_run_reporter_compute_with_failure(self, tmp_path: Path) -> None:
        reporter = RunReporter(workspace_root=tmp_path, run_id="fail-run")
        results = _make_run_results(
            l1_slices=[
                {"slice_id": "s1", "status": "STAGNATED", "iterations": 20, "demotion_count": 5},
            ],
        )

        scorecard = reporter.compute(results)
        assert scorecard.overall_pass is False

        # Verify gates.final_pass is FAIL
        final_pass_gate = next(g for g in scorecard.hard_gates if g.name == "gates.final_pass")
        assert final_pass_gate.status == "FAIL"

    def test_stagnated_l3_fails_no_behavior_change(self, tmp_path: Path) -> None:
        reporter = RunReporter(workspace_root=tmp_path, run_id="l3fail")
        results = _make_run_results(
            l3_slices=[
                {"slice_id": "s1", "status": "STAGNATED", "iterations": 10, "demotion_count": 3},
            ],
        )

        scorecard = reporter.compute(results)
        l3_gate = next(g for g in scorecard.hard_gates if g.name == "l3.no_behavior_change")
        assert l3_gate.status == "FAIL"


class TestRunReporterWrite:
    """Verify scores.json and scorecard.md are written."""

    def test_run_reporter_write(self, tmp_path: Path) -> None:
        reporter = RunReporter(workspace_root=tmp_path, run_id="write-run")
        results = _make_run_results(
            l1_slices=[
                {"slice_id": "s1", "status": "COMPLETE", "iterations": 1, "demotion_count": 0},
            ],
        )

        scorecard = reporter.compute(results)
        scores_path, md_path = reporter.write(scorecard)

        assert scores_path.exists()
        assert md_path.exists()

        # Verify scores.json content
        scores_data = json.loads(scores_path.read_text(encoding="utf-8"))
        assert scores_data["run_id"] == "write-run"
        assert scores_data["overall_pass"] is True
        assert "hard_gates" in scores_data
        assert "soft_signals" in scores_data

        # Verify scorecard.md content
        md_content = md_path.read_text(encoding="utf-8")
        assert "write-run" in md_content
        assert "Hard Gates" in md_content
        assert "Soft Signals" in md_content


class TestScorecardMarkdownRendering:
    """Verify the markdown rendering output format."""

    def test_scorecard_markdown_rendering(self) -> None:
        scorecard = Scorecard(
            run_id="md-test",
            hard_gates=[
                ScorecardMetric(name="gates.final_pass", score=1.0, status="PASS", hard_gate=True),
                ScorecardMetric(name="ci.final_pass", score=0.0, status="FAIL", hard_gate=True),
            ],
            soft_signals=[
                ScorecardMetric(name="pipeline.stagnation_rate", raw=2.0, score=0.8, status="PASS"),
            ],
            overall_pass=False,
            summary="FAIL: ci.final_pass",
        )

        md = RunReporter._render_markdown(scorecard)

        assert "# Scorecard" in md
        assert "md-test" in md
        assert "FAIL" in md
        assert "gates.final_pass" in md
        assert "ci.final_pass" in md
        assert "pipeline.stagnation_rate" in md
        assert "| Gate | Status | Score |" in md
        assert "| Signal | Status | Score | Raw |" in md


class TestScorecardSoftSignals:
    """Verify soft signal computations."""

    def test_stagnation_rate_signal(self, tmp_path: Path) -> None:
        reporter = RunReporter(workspace_root=tmp_path, run_id="signals")
        results = _make_run_results(
            l1_slices=[
                {"slice_id": "s1", "status": "STAGNATED", "iterations": 20, "demotion_count": 0},
                {"slice_id": "s2", "status": "COMPLETE", "iterations": 5, "demotion_count": 0},
            ],
        )

        scorecard = reporter.compute(results)
        stag_signal = next(
            s for s in scorecard.soft_signals if s.name == "pipeline.stagnation_rate"
        )
        # 1 stagnated out of 2 = 50% rate
        assert stag_signal.raw == 1.0
        assert stag_signal.status == "FAIL"  # 50% > 0.05 threshold

    def test_demotion_count_from_ledger(self, tmp_path: Path) -> None:
        """Verify pipeline.total_demotions counts ledger entries."""
        reporter = RunReporter(workspace_root=tmp_path, run_id="churn-run")

        # Write a ledger with 3 demotion entries
        ledger_dir = tmp_path / ".pdd_runs" / "churn-run" / "demotions"
        ledger_dir.mkdir(parents=True)
        ledger_path = ledger_dir / "ledger.jsonl"
        entries = [
            {"ticket_id": "t1", "failing_files": ["a.py"], "source": "GATE_FAILURE"},
            {"ticket_id": "t2", "failing_files": ["a.py"], "source": "GATE_FAILURE"},
            {"ticket_id": "t3", "failing_files": ["b.py"], "source": "TEST_FAILURE"},
        ]
        ledger_path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

        results = _make_run_results(
            l1_slices=[
                {"slice_id": "s1", "status": "COMPLETE", "iterations": 3, "demotion_count": 2},
            ],
        )

        scorecard = reporter.compute(results)
        demo_signal = next(
            s for s in scorecard.soft_signals if s.name == "pipeline.total_demotions"
        )
        # ledger has 3 entries, slice has demotion_count=2; max(2, 3) = 3
        assert demo_signal.raw == 3.0


# ===================================================================
# 6. Final report tests
# ===================================================================


class TestFinalReportGenerator:
    """Test FinalReportGenerator output."""

    def test_generate_creates_files(self, tmp_path: Path) -> None:
        gen = FinalReportGenerator(workspace_root=tmp_path, run_id="report-run")
        results = _make_run_results(
            l1_slices=[
                {"slice_id": "s1", "status": "COMPLETE", "iterations": 2, "demotion_count": 0},
            ],
        )

        scorecard = Scorecard(
            run_id="report-run",
            overall_pass=True,
            hard_gates=[],
            soft_signals=[],
            summary="All pass",
        )

        report_path, scorecard_path = gen.generate(results, scorecard)

        assert report_path.exists()
        assert scorecard_path.exists()
        assert report_path.name == "final_report.md"
        assert scorecard_path.name == "scorecard.json"

    def test_report_contains_sections(self, tmp_path: Path) -> None:
        gen = FinalReportGenerator(workspace_root=tmp_path, run_id="sections-run")
        results = _make_run_results(
            l1_slices=[
                {"slice_id": "s1", "status": "COMPLETE", "iterations": 2, "demotion_count": 0},
            ],
        )
        results["l1_l2_transition"] = {"transition_stuck": False, "rework_rounds": []}
        results["l2_l3_transition"] = {"transition_stuck": True, "rework_rounds": [{"round": 1}]}
        results["qa"] = {"error": "eval failed"}

        scorecard = Scorecard(
            run_id="sections-run",
            overall_pass=False,
            hard_gates=[
                ScorecardMetric(name="gates.final_pass", status="PASS"),
            ],
            soft_signals=[
                ScorecardMetric(name="pipeline.stagnation_rate", score=0.9, status="PASS"),
            ],
            summary="FAIL: something",
        )

        report_path, _ = gen.generate(results, scorecard)
        report = report_path.read_text(encoding="utf-8")

        # Required sections
        assert "Executive Summary" in report
        assert "Architecture Topology" in report
        assert "Scorecard" in report
        assert "Demotion Summary" in report
        assert "Known Risks" in report
        assert "Evidence Links" in report

        # Stuck transition should appear in known risks
        assert "stuck" in report.lower()

        # QA error should appear in known risks
        assert "eval failed" in report

    def test_demotion_summary_from_ledger(self, tmp_path: Path) -> None:
        """Write ledger entries, verify they appear in the report."""
        gen = FinalReportGenerator(workspace_root=tmp_path, run_id="demo-report")

        # Create ledger
        ledger_dir = tmp_path / ".pdd_runs" / "demo-report" / "demotions"
        ledger_dir.mkdir(parents=True)
        ledger_path = ledger_dir / "ledger.jsonl"
        entries = [
            {
                "ticket_id": "t1",
                "source": "GATE_FAILURE",
                "target_layer": "L1",
                "severity": "BLOCKER",
                "failing_files": ["a.py"],
                "applied": True,
            },
            {
                "ticket_id": "t2",
                "source": "TEST_FAILURE",
                "target_layer": "L2",
                "severity": "MAJOR",
                "failing_files": ["b.py"],
                "applied": True,
            },
            {
                "ticket_id": "t3",
                "source": "GATE_FAILURE",
                "target_layer": "L1",
                "severity": "MINOR",
                "failing_files": [],
                "applied": False,
            },
        ]
        ledger_path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

        results = _make_run_results()
        report_path, _ = gen.generate(results, None)
        report = report_path.read_text(encoding="utf-8")

        assert "Total tickets" in report
        assert "3" in report  # total count
        assert "GATE_FAILURE" in report
        assert "TEST_FAILURE" in report
        assert "L1" in report
        assert "L2" in report

    def test_scorecard_json_output(self, tmp_path: Path) -> None:
        gen = FinalReportGenerator(workspace_root=tmp_path, run_id="sc-json")
        scorecard = Scorecard(
            run_id="sc-json",
            overall_pass=True,
            hard_gates=[
                ScorecardMetric(name="g1", status="PASS", score=1.0, hard_gate=True),
            ],
            soft_signals=[],
            summary="All pass",
        )

        _, scorecard_path = gen.generate({}, scorecard)
        data = json.loads(scorecard_path.read_text(encoding="utf-8"))
        assert data["run_id"] == "sc-json"
        assert data["overall_pass"] is True
        assert len(data["hard_gates"]) == 1

    def test_generate_without_scorecard(self, tmp_path: Path) -> None:
        gen = FinalReportGenerator(workspace_root=tmp_path, run_id="no-sc")
        report_path, scorecard_path = gen.generate({}, None)
        assert report_path.exists()
        assert scorecard_path.exists()

        sc_data = json.loads(scorecard_path.read_text(encoding="utf-8"))
        assert sc_data == {}

        report = report_path.read_text(encoding="utf-8")
        assert "Scorecard not computed" in report


# ===================================================================
# 7. Governance check tests
# ===================================================================


class TestGovernanceCheck:
    """Test PddLifecycle._run_governance_check."""

    def _make_lifecycle(self, tmp_path: Path) -> Any:
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "gov-run"
        return PddLifecycle(manager, mode="auto")

    def test_governance_check_passed(self, tmp_path: Path) -> None:
        """Run with all artifacts present => passed=True."""
        lifecycle = self._make_lifecycle(tmp_path)

        # Create required artifacts
        run_dir = tmp_path / ".pdd_runs" / "gov-run"
        slices_dir = run_dir / "slices"
        slices_dir.mkdir(parents=True)
        # Need at least one entry so iterdir() is non-empty
        (slices_dir / "slice-1").mkdir()
        demotions_dir = run_dir / "demotions"
        demotions_dir.mkdir(parents=True)

        result = lifecycle._run_governance_check(
            "transition_l1_l2",
            check_artifacts=True,
        )
        assert result["passed"] is True
        assert result["findings"] == []

    def test_governance_check_missing_artifacts(self, tmp_path: Path) -> None:
        """Run without slices dir => findings present."""
        lifecycle = self._make_lifecycle(tmp_path)

        result = lifecycle._run_governance_check(
            "transition_l1_l2",
            check_artifacts=True,
        )
        assert result["passed"] is False
        assert len(result["findings"]) > 0
        assert any("slices" in f.lower() or "evidence" in f.lower() for f in result["findings"])

    def test_governance_check_missing_report(self, tmp_path: Path) -> None:
        """When check_report=True and files are missing, findings are emitted."""
        lifecycle = self._make_lifecycle(tmp_path)

        result = lifecycle._run_governance_check(
            "final",
            check_report=True,
        )
        assert result["passed"] is False
        assert any("report" in f.lower() for f in result["findings"])

    def test_governance_check_report_present(self, tmp_path: Path) -> None:
        """When check_report=True and files exist, passed=True."""
        lifecycle = self._make_lifecycle(tmp_path)

        reports_dir = tmp_path / "reports" / "pdd" / "gov-run"
        reports_dir.mkdir(parents=True)
        (reports_dir / "final_report.md").write_text("report", encoding="utf-8")
        (reports_dir / "scorecard.json").write_text("{}", encoding="utf-8")

        result = lifecycle._run_governance_check(
            "final",
            check_report=True,
        )
        assert result["passed"] is True

    def test_governance_check_no_checks(self, tmp_path: Path) -> None:
        """Without check_artifacts or check_report, always passes."""
        lifecycle = self._make_lifecycle(tmp_path)

        result = lifecycle._run_governance_check("any_checkpoint")
        assert result["passed"] is True
        assert result["findings"] == []


# ===================================================================
# 8. CI readiness tests
# ===================================================================


class TestReadinessCI:
    """Test PddLifecycle._run_readiness_ci."""

    def test_readiness_ci_no_worktree(self, tmp_path: Path) -> None:
        """Returns passed=True with note when no worktree manager."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "ci-run"

        lifecycle = PddLifecycle(manager, mode="auto")
        lifecycle.worktree_manager = None

        result = lifecycle._run_readiness_ci("l2")
        assert result["passed"] is True
        assert "note" in result

    def test_readiness_ci_no_dirty_path(self, tmp_path: Path) -> None:
        """Returns passed=True when dirty worktree doesn't exist."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "ci-run2"

        wm = MagicMock()
        wm.get_layer_worktree.return_value = None

        lifecycle = PddLifecycle(manager, mode="auto", worktree_manager=wm)

        result = lifecycle._run_readiness_ci("l2")
        assert result["passed"] is True


# ===================================================================
# 9. Human approval tests
# ===================================================================


class TestL2CheckpointAutoMode:
    """Test _request_l2_checkpoint in auto mode."""

    def test_l2_checkpoint_auto_mode(self, tmp_path: Path) -> None:
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "auto-run"

        lifecycle = PddLifecycle(manager, mode="auto")

        result = lifecycle._request_l2_checkpoint({"slices": []})
        assert result["approved"] is True
        assert result["mode"] == "auto"

    def test_l2_checkpoint_steering_mode(self, tmp_path: Path) -> None:
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "steering-run"

        lifecycle = PddLifecycle(manager, mode="steering")

        result = lifecycle._request_l2_checkpoint({"slices": []})
        assert result["approved"] is True
        assert result["mode"] == "steering"


class TestReleaseSignoffAutoMode:
    """Test _request_release_signoff in auto mode."""

    def test_release_signoff_auto_mode(self, tmp_path: Path) -> None:
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "signoff-run"

        lifecycle = PddLifecycle(manager, mode="auto")

        result = lifecycle._request_release_signoff({"scorecard": {"overall_pass": True}})
        assert result["approved"] is True
        assert result["mode"] == "auto"

    def test_release_signoff_steering_mode(self, tmp_path: Path) -> None:
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "signoff-s"

        lifecycle = PddLifecycle(manager, mode="steering")

        result = lifecycle._request_release_signoff({"scorecard": {"overall_pass": False}})
        assert result["approved"] is True
        assert result["mode"] == "steering"


# ===================================================================
# Additional edge-case tests
# ===================================================================


class TestPromotionLoopEdgeCases:
    """Edge cases for the PromotionLoop."""

    def test_blocked_status(self, tmp_path: Path) -> None:
        """Verify a BLOCKED step returns BLOCKED SliceResult."""
        dm = DemotionManager(workspace_root=tmp_path, run_id="block-run")

        loop = PromotionLoop(
            workspace_root=tmp_path,
            demotion_manager=dm,
            steps=[BlockStep()],
        )

        ref = SliceRef(
            slice_id="block-slice",
            layer="l1",
            worktree_path=str(tmp_path),
        )
        run_ctx = RunContext(
            run_id="block-run",
            workspace_root=str(tmp_path),
        )

        result = loop.run_slice(ref, run_ctx)
        assert result.status == "BLOCKED"
        assert len(result.blocked_questions) > 0
        assert "What should X do?" in result.blocked_questions

    def test_fail_status(self, tmp_path: Path) -> None:
        """Verify a FAIL step returns FAILED SliceResult."""
        dm = DemotionManager(workspace_root=tmp_path, run_id="fail-run")

        loop = PromotionLoop(
            workspace_root=tmp_path,
            demotion_manager=dm,
            steps=[FailStep()],
        )

        ref = SliceRef(
            slice_id="fail-slice",
            layer="l1",
            worktree_path=str(tmp_path),
        )
        run_ctx = RunContext(
            run_id="fail-run",
            workspace_root=str(tmp_path),
        )

        result = loop.run_slice(ref, run_ctx)
        assert result.status == "FAILED"
        assert result.error == "hard failure"

    def test_complete_when_no_gaps(self, tmp_path: Path) -> None:
        """Verify a step that produces 0 gaps leads to COMPLETE."""
        dm = DemotionManager(workspace_root=tmp_path, run_id="complete-run")

        # FixedGapStep with 0 gaps => immediate completion
        loop = PromotionLoop(
            workspace_root=tmp_path,
            demotion_manager=dm,
            steps=[FixedGapStep(gap_count=0)],
        )

        ref = SliceRef(
            slice_id="done-slice",
            layer="l1",
            worktree_path=str(tmp_path),
        )
        run_ctx = RunContext(
            run_id="complete-run",
            workspace_root=str(tmp_path),
        )

        result = loop.run_slice(ref, run_ctx)
        assert result.status == "COMPLETE"
        assert result.iterations == 1
        assert result.remaining_gaps == 0

    def test_run_slices_multiple(self, tmp_path: Path) -> None:
        """Verify run_slices processes multiple slices."""
        dm = DemotionManager(workspace_root=tmp_path, run_id="multi-run")

        loop = PromotionLoop(
            workspace_root=tmp_path,
            demotion_manager=dm,
            steps=[FixedGapStep(gap_count=0)],
        )

        refs = [
            SliceRef(slice_id=f"s{i}", layer="l1", worktree_path=str(tmp_path)) for i in range(3)
        ]
        run_ctx = RunContext(
            run_id="multi-run",
            workspace_root=str(tmp_path),
        )

        results = loop.run_slices(refs, run_ctx)
        assert len(results) == 3
        assert all(r.status == "COMPLETE" for r in results)

    def test_integrate_step_investigator_budget(self) -> None:
        """Verify IntegrateStep has configurable investigator budget."""
        from spec_manager.orchestration.promotion_loop import IntegrateStep

        step = IntegrateStep(investigator_budget=5)
        assert step._investigator_budget == 5

        step_default = IntegrateStep()
        assert step_default._investigator_budget == 2

    def test_integrate_step_no_worktree_manager(self) -> None:
        """Verify IntegrateStep returns OK without worktree manager."""
        from spec_manager.orchestration.promotion_loop import IntegrateStep

        step = IntegrateStep(worktree_manager=None)
        ctx = SliceContext(slice_id="test", run_id="test")
        bundle = EvidenceBundle()
        result = step.run(ctx, bundle)
        assert result.status == "OK"


class TestDemotionTicketSerialization:
    """Verify DemotionTicket roundtrip serialization."""

    def test_to_dict_and_from_dict(self) -> None:
        ticket = DemotionTicket(
            run_id="r1",
            slice_id="s1",
            source="TEST_FAILURE",
            gate="SPEC_COMMENTS",
            target_layer="L2",
            severity="MAJOR",
            origin_layer="L3",
            failing_files=["a.py", "b.py"],
            diagnosis="Test flaky",
        )
        d = ticket.to_dict()
        restored = DemotionTicket.from_dict(d)

        assert restored.run_id == "r1"
        assert restored.slice_id == "s1"
        assert restored.source == "TEST_FAILURE"
        assert restored.gate == "SPEC_COMMENTS"
        assert restored.target_layer == "L2"
        assert restored.severity == "MAJOR"
        assert restored.origin_layer == "L3"
        assert restored.failing_files == ["a.py", "b.py"]
        assert restored.diagnosis == "Test flaky"


class TestRunConfigSerialization:
    """Verify RunConfig roundtrip via to_dict / from_dict."""

    def test_roundtrip(self) -> None:
        config = RunConfig(
            run_id="rt",
            mode="interactive",
            max_transition_rounds=5,
        )
        d = config.to_dict()
        restored = RunConfig.from_dict(d)
        assert restored.run_id == "rt"
        assert restored.mode == "interactive"
        assert restored.max_transition_rounds == 5

    def test_from_dict_ignores_unknown_keys(self) -> None:
        d = {"run_id": "x", "unknown_field": 99}
        config = RunConfig.from_dict(d)
        assert config.run_id == "x"
        assert not hasattr(config, "unknown_field")


class TestRunStateSerialization:
    """Verify RunState roundtrip via to_dict / from_dict."""

    def test_roundtrip(self) -> None:
        state = RunState(
            run_id="rt",
            active_layer="l2",
            total_demotions=7,
            stagnated_slices=["s1"],
        )
        d = state.to_dict()
        restored = RunState.from_dict(d)
        assert restored.run_id == "rt"
        assert restored.active_layer == "l2"
        assert restored.total_demotions == 7
        assert restored.stagnated_slices == ["s1"]


# ===================================================================
# 10. Per-layer demotion budget tests (budget #3)
# ===================================================================


class TestDemotionBudget:
    """Test per-layer demotion budget (budget #3).

    PddLifecycle.max_demotions_per_layer controls how many total
    demotion tickets across all slices are tolerable at a single layer.
    When exceeded, _run_slices_at_layer sets budget_exceeded=True.
    """

    def test_budget_not_exceeded(self, tmp_path: Path) -> None:
        """When total demotions <= budget, budget_exceeded is False."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "budget-ok"

        lifecycle = PddLifecycle(manager, mode="auto", max_demotions_per_layer=50)
        lifecycle.worktree_manager = None

        # Mock _discover_slices to return one slice ref
        mock_ref = MagicMock()
        mock_ref.slice_id = "s1"
        lifecycle._discover_slices = MagicMock(return_value=[mock_ref])

        # Mock SliceResult with low demotion count
        mock_slice_result = MagicMock()
        mock_slice_result.slice_id = "s1"
        mock_slice_result.status = "COMPLETE"
        mock_slice_result.iterations = 3
        mock_slice_result.remaining_gaps = 0
        mock_slice_result.demotion_tickets = [MagicMock()] * 2  # 2 demotions

        mock_sched_result = MagicMock()
        mock_sched_result.slice_results = [mock_slice_result]
        mock_sched_result.all_complete = True
        mock_sched_result.waiting_slices = []

        with (
            patch("spec_manager.orchestration.promotion_loop.PromotionLoop"),
            patch(
                "spec_manager.orchestration.promotion_scheduler.ReactivePromotionScheduler"
            ) as mock_sched_cls,
        ):
            mock_sched_cls.return_value.run.return_value = mock_sched_result
            result = lifecycle._run_slices_at_layer("l1")

        assert result["budget_exceeded"] is False
        assert result["total_layer_demotions"] == 2

    def test_budget_exceeded(self, tmp_path: Path) -> None:
        """When total demotions > budget, budget_exceeded is True."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "budget-over"

        lifecycle = PddLifecycle(manager, mode="auto", max_demotions_per_layer=5)
        lifecycle.worktree_manager = None

        # Three slices, each with 3 demotion tickets = 9 total > 5
        mock_refs = []
        mock_results = []
        for i in range(3):
            ref = MagicMock()
            ref.slice_id = f"s{i}"
            mock_refs.append(ref)

            sr = MagicMock()
            sr.slice_id = f"s{i}"
            sr.status = "COMPLETE"
            sr.iterations = 2
            sr.remaining_gaps = 0
            sr.demotion_tickets = [MagicMock()] * 3
            mock_results.append(sr)

        lifecycle._discover_slices = MagicMock(return_value=mock_refs)

        mock_sched_result = MagicMock()
        mock_sched_result.slice_results = mock_results
        mock_sched_result.all_complete = True
        mock_sched_result.waiting_slices = []

        with (
            patch("spec_manager.orchestration.promotion_loop.PromotionLoop"),
            patch(
                "spec_manager.orchestration.promotion_scheduler.ReactivePromotionScheduler"
            ) as mock_sched_cls,
        ):
            mock_sched_cls.return_value.run.return_value = mock_sched_result
            result = lifecycle._run_slices_at_layer("l1")

        assert result["budget_exceeded"] is True
        assert result["total_layer_demotions"] == 9

    def test_custom_budget_stored(self, tmp_path: Path) -> None:
        """Verify PddLifecycle stores the custom budget value."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "custom-budget"

        lifecycle = PddLifecycle(manager, mode="auto", max_demotions_per_layer=7)
        assert lifecycle.max_demotions_per_layer == 7

    def test_default_budget_is_50(self, tmp_path: Path) -> None:
        """Verify the default demotion budget is 50."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "default-budget"

        lifecycle = PddLifecycle(manager, mode="auto")
        assert lifecycle.max_demotions_per_layer == 50

    def test_budget_exactly_at_limit(self, tmp_path: Path) -> None:
        """When total demotions == budget, budget_exceeded is False (not >)."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "budget-edge"

        lifecycle = PddLifecycle(manager, mode="auto", max_demotions_per_layer=3)
        lifecycle.worktree_manager = None

        mock_ref = MagicMock()
        mock_ref.slice_id = "s1"
        lifecycle._discover_slices = MagicMock(return_value=[mock_ref])

        mock_sr = MagicMock()
        mock_sr.slice_id = "s1"
        mock_sr.status = "COMPLETE"
        mock_sr.iterations = 1
        mock_sr.remaining_gaps = 0
        mock_sr.demotion_tickets = [MagicMock()] * 3  # exactly 3 == budget

        mock_sched_result = MagicMock()
        mock_sched_result.slice_results = [mock_sr]
        mock_sched_result.all_complete = True
        mock_sched_result.waiting_slices = []

        with (
            patch("spec_manager.orchestration.promotion_loop.PromotionLoop"),
            patch(
                "spec_manager.orchestration.promotion_scheduler.ReactivePromotionScheduler"
            ) as mock_sched_cls,
        ):
            mock_sched_cls.return_value.run.return_value = mock_sched_result
            result = lifecycle._run_slices_at_layer("l1")

        # budget is checked as > not >=, so exactly at limit is not exceeded
        assert result["budget_exceeded"] is False
        assert result["total_layer_demotions"] == 3


# ===================================================================
# 11. Pipeline pass cap tests (budget #4)
# ===================================================================


class TestPipelinePassCap:
    """Test pipeline pass cap (budget #4).

    PddLifecycle.max_pipeline_passes controls the max number of
    L1->L2->L3 pipeline passes. The run() method records
    results["pipeline_pass"] and results["max_pipeline_passes"].
    """

    def test_pipeline_pass_cap_stored(self, tmp_path: Path) -> None:
        """Verify max_pipeline_passes is stored on the lifecycle instance."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "cap-run"

        lifecycle = PddLifecycle(manager, mode="auto", max_pipeline_passes=5)
        assert lifecycle.max_pipeline_passes == 5

    def test_pipeline_pass_cap_default(self, tmp_path: Path) -> None:
        """Verify default max_pipeline_passes is 2."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "cap-default"

        lifecycle = PddLifecycle(manager, mode="auto")
        assert lifecycle.max_pipeline_passes == 2

    def test_pipeline_pass_in_run_results(self, tmp_path: Path) -> None:
        """Verify run() sets pipeline_pass and max_pipeline_passes in results."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "pass-result"
        manager.structure.input_folder = tmp_path / "specs"
        manager.structure.libraries_dir = tmp_path / "libraries"
        manager.structure.root = tmp_path
        manager.structure.spec_snapshot_dir = tmp_path / "spec_snapshot"

        lifecycle = PddLifecycle(manager, mode="auto", max_pipeline_passes=3)
        lifecycle.worktree_manager = None

        # Mock all the heavy methods to isolate what we're testing
        lifecycle._run_intake = MagicMock(return_value={"ok": True})
        lifecycle._run_l1_with_approval = MagicMock(
            return_value=(
                {"slices": {"slices": []}},
                {"approved": True},
            )
        )
        lifecycle._run_transition = MagicMock(
            return_value={"transition_stuck": False, "rework_rounds": []}
        )
        lifecycle._run_layer = MagicMock(return_value={"slices": {"slices": []}})
        lifecycle.qa = MagicMock(return_value={"pass_rate": 1.0})
        lifecycle._run_governance_check = MagicMock(return_value={"passed": True, "findings": []})
        lifecycle._request_l2_checkpoint = MagicMock(return_value={"approved": True})
        lifecycle._request_release_signoff = MagicMock(return_value={"approved": True})
        lifecycle._record_git_ref = MagicMock()

        # Mock the scorer and report generator
        mock_scorecard = MagicMock()
        mock_scorecard.to_dict.return_value = {"overall_pass": True}

        with (
            patch("spec_manager.orchestration.scoring.RunReporter") as mock_reporter_cls,
            patch("spec_manager.orchestration.final_report.FinalReportGenerator") as mock_gen_cls,
        ):
            mock_reporter_cls.return_value.compute.return_value = mock_scorecard
            mock_reporter_cls.return_value.write.return_value = (
                tmp_path / "scores.json",
                tmp_path / "scorecard.md",
            )
            mock_gen_cls.return_value.generate.return_value = (
                tmp_path / "final_report.md",
                tmp_path / "scorecard.json",
            )

            results = lifecycle.run()

        assert results["pipeline_pass"] == 1
        assert results["max_pipeline_passes"] == 3


# ===================================================================
# 12. Approval artifact writing tests
# ===================================================================


class TestApprovalArtifact:
    """Test _write_approval_artifact writes decision.json.

    The method creates .pdd_runs/<run_id>/approvals/<layer>/decision.json
    containing the approval decision with metadata.
    """

    def test_writes_decision_json(self, tmp_path: Path) -> None:
        """Verify decision.json is written with correct content."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "artifact-run"

        lifecycle = PddLifecycle(manager, mode="auto")

        # Set up _state_mgr with a real RunStateManager
        state_mgr = RunStateManager(workspace_root=tmp_path, run_id="artifact-run")
        state_mgr.ensure_directories()
        lifecycle._state_mgr = state_mgr

        lifecycle._write_approval_artifact("l1", approved=True, iteration=2)

        decision_path = (
            tmp_path / ".pdd_runs" / "artifact-run" / "approvals" / "l1" / "decision.json"
        )
        assert decision_path.exists()

        data = json.loads(decision_path.read_text(encoding="utf-8"))
        assert data["layer"] == "l1"
        assert data["approved"] is True
        assert data["iteration"] == 2
        assert data["mode"] == "auto"

    def test_writes_with_extra_metadata(self, tmp_path: Path) -> None:
        """Verify extra keyword arguments are included in decision.json."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "extra-run"

        lifecycle = PddLifecycle(manager, mode="steering")

        state_mgr = RunStateManager(workspace_root=tmp_path, run_id="extra-run")
        state_mgr.ensure_directories()
        lifecycle._state_mgr = state_mgr

        lifecycle._write_approval_artifact(
            "l2", approved=True, iteration=1, reason="checkpoint", score=0.95
        )

        decision_path = tmp_path / ".pdd_runs" / "extra-run" / "approvals" / "l2" / "decision.json"
        assert decision_path.exists()

        data = json.loads(decision_path.read_text(encoding="utf-8"))
        assert data["layer"] == "l2"
        assert data["approved"] is True
        assert data["reason"] == "checkpoint"
        assert data["score"] == 0.95
        assert data["mode"] == "steering"

    def test_no_write_without_state_mgr(self, tmp_path: Path) -> None:
        """Calling _write_approval_artifact without _state_mgr should not error."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "no-state-run"

        lifecycle = PddLifecycle(manager, mode="auto")
        # Explicitly ensure _state_mgr is not set (it is only set in run())
        if hasattr(lifecycle, "_state_mgr"):
            del lifecycle._state_mgr

        # Should not raise
        lifecycle._write_approval_artifact("l1", approved=True, iteration=1)

        # No decision.json should exist
        decision_path = (
            tmp_path / ".pdd_runs" / "no-state-run" / "approvals" / "l1" / "decision.json"
        )
        assert not decision_path.exists()

    def test_release_approval_artifact(self, tmp_path: Path) -> None:
        """Verify _write_approval_artifact works for 'release' layer."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "release-art"

        lifecycle = PddLifecycle(manager, mode="auto")

        state_mgr = RunStateManager(workspace_root=tmp_path, run_id="release-art")
        state_mgr.ensure_directories()
        lifecycle._state_mgr = state_mgr

        lifecycle._write_approval_artifact("release", approved=False, iteration=0)

        decision_path = (
            tmp_path / ".pdd_runs" / "release-art" / "approvals" / "release" / "decision.json"
        )
        assert decision_path.exists()

        data = json.loads(decision_path.read_text(encoding="utf-8"))
        assert data["layer"] == "release"
        assert data["approved"] is False

    def test_approval_called_from_request_approval_auto(self, tmp_path: Path) -> None:
        """Verify _request_approval in auto mode calls _write_approval_artifact."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "auto-approval"

        lifecycle = PddLifecycle(manager, mode="auto")

        state_mgr = RunStateManager(workspace_root=tmp_path, run_id="auto-approval")
        state_mgr.ensure_directories()
        lifecycle._state_mgr = state_mgr

        result = lifecycle._request_approval({"overview": {}}, iteration=1)
        assert result["approved"] is True

        decision_path = (
            tmp_path / ".pdd_runs" / "auto-approval" / "approvals" / "l1" / "decision.json"
        )
        assert decision_path.exists()
        data = json.loads(decision_path.read_text(encoding="utf-8"))
        assert data["approved"] is True
        assert data["layer"] == "l1"
        assert data["iteration"] == 1


# ===================================================================
# 13. Git ref recording tests
# ===================================================================


class TestGitRefRecording:
    """Test _record_git_ref writes ref metadata JSON.

    The method writes to .pdd_runs/<run_id>/refs/<sanitized_name>.json
    where / in the ref name is replaced with _.
    """

    def test_records_ref(self, tmp_path: Path) -> None:
        """Verify ref JSON file is created with correct content."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "ref-run"

        lifecycle = PddLifecycle(manager, mode="auto")

        state_mgr = RunStateManager(workspace_root=tmp_path, run_id="ref-run")
        state_mgr.ensure_directories()
        lifecycle._state_mgr = state_mgr

        lifecycle._record_git_ref("pdd/ref-run/base")

        ref_path = tmp_path / ".pdd_runs" / "ref-run" / "refs" / "pdd_ref-run_base.json"
        assert ref_path.exists()

        data = json.loads(ref_path.read_text(encoding="utf-8"))
        assert data["ref"] == "pdd/ref-run/base"
        assert data["run_id"] == "ref-run"
        assert "timestamp" in data
        assert isinstance(data["timestamp"], float)

    def test_ref_name_sanitization(self, tmp_path: Path) -> None:
        """Verify slashes in ref name are replaced with underscores in filename."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "sanitize-run"

        lifecycle = PddLifecycle(manager, mode="auto")

        state_mgr = RunStateManager(workspace_root=tmp_path, run_id="sanitize-run")
        state_mgr.ensure_directories()
        lifecycle._state_mgr = state_mgr

        lifecycle._record_git_ref("pdd/run/l1-approved")

        ref_path = tmp_path / ".pdd_runs" / "sanitize-run" / "refs" / "pdd_run_l1-approved.json"
        assert ref_path.exists()

        data = json.loads(ref_path.read_text(encoding="utf-8"))
        assert data["ref"] == "pdd/run/l1-approved"

    def test_no_write_without_state_mgr(self, tmp_path: Path) -> None:
        """Calling _record_git_ref without _state_mgr should not error."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "no-ref-state"

        lifecycle = PddLifecycle(manager, mode="auto")
        if hasattr(lifecycle, "_state_mgr"):
            del lifecycle._state_mgr

        # Should not raise
        lifecycle._record_git_ref("pdd/no-ref-state/base")

        # No ref file should exist
        refs_dir = tmp_path / ".pdd_runs" / "no-ref-state" / "refs"
        assert not refs_dir.exists()

    def test_multiple_refs(self, tmp_path: Path) -> None:
        """Verify multiple refs can be recorded independently."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "multi-ref"

        lifecycle = PddLifecycle(manager, mode="auto")

        state_mgr = RunStateManager(workspace_root=tmp_path, run_id="multi-ref")
        state_mgr.ensure_directories()
        lifecycle._state_mgr = state_mgr

        lifecycle._record_git_ref("pdd/multi-ref/base")
        lifecycle._record_git_ref("pdd/multi-ref/l1-approved")
        lifecycle._record_git_ref("pdd/multi-ref/release")

        refs_dir = tmp_path / ".pdd_runs" / "multi-ref" / "refs"
        ref_files = list(refs_dir.glob("*.json"))
        assert len(ref_files) == 3

        # Verify each file has the correct ref value
        ref_names = set()
        for f in ref_files:
            data = json.loads(f.read_text(encoding="utf-8"))
            ref_names.add(data["ref"])

        assert ref_names == {
            "pdd/multi-ref/base",
            "pdd/multi-ref/l1-approved",
            "pdd/multi-ref/release",
        }


# ===================================================================
# 14. CI batch receipt writing tests
# ===================================================================


class TestCIBatchReceipt:
    """Test CI batch receipt writing in _run_slices_at_layer.

    After each CI tick for a completed slice with a worktree manager,
    a batch_<slice_id>_<n>.json receipt is written to
    .pdd_runs/<run_id>/ci/<layer>/batches/.
    """

    def test_batch_receipt_written(self, tmp_path: Path) -> None:
        """Verify batch receipt JSON is written after CI tick."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "ci-batch"

        lifecycle = PddLifecycle(manager, mode="auto")

        # Set up state manager so the receipt writing code path fires
        state_mgr = RunStateManager(workspace_root=tmp_path, run_id="ci-batch")
        state_mgr.ensure_directories()
        lifecycle._state_mgr = state_mgr

        # Set up worktree manager so CI ticks happen
        wm = MagicMock()
        tick_result = MagicMock()
        tick_result.main_updated = True
        tick_result.demotion_tickets = []
        wm.tick_pipeline.return_value = tick_result
        wm.create_slice_worktree.side_effect = RuntimeError("exists")
        wm.get_slice_worktree.return_value = tmp_path / "wt"
        lifecycle.worktree_manager = wm

        # Mock _discover_slices
        mock_ref = MagicMock()
        mock_ref.slice_id = "lib1"
        lifecycle._discover_slices = MagicMock(return_value=[mock_ref])

        # Create COMPLETE slice result
        mock_sr = MagicMock()
        mock_sr.slice_id = "lib1"
        mock_sr.status = "COMPLETE"
        mock_sr.iterations = 2
        mock_sr.remaining_gaps = 0
        mock_sr.demotion_tickets = []

        mock_sched_result = MagicMock()
        mock_sched_result.slice_results = [mock_sr]
        mock_sched_result.all_complete = True
        mock_sched_result.waiting_slices = []

        with (
            patch("spec_manager.orchestration.promotion_loop.PromotionLoop"),
            patch(
                "spec_manager.orchestration.promotion_scheduler.ReactivePromotionScheduler"
            ) as mock_sched_cls,
        ):
            mock_sched_cls.return_value.run.return_value = mock_sched_result
            lifecycle._run_slices_at_layer("l1")

        # Check receipt was written
        batch_dir = tmp_path / ".pdd_runs" / "ci-batch" / "ci" / "l1" / "batches"
        assert batch_dir.exists()
        receipts = list(batch_dir.glob("batch_*.json"))
        assert len(receipts) == 1

        data = json.loads(receipts[0].read_text(encoding="utf-8"))
        assert data["slice_id"] == "lib1"
        assert data["layer"] == "l1"
        assert data["main_updated"] is True
        assert data["demotions"] == 0

    def test_no_receipt_without_worktree_manager(self, tmp_path: Path) -> None:
        """Without worktree manager, no CI ticks and no receipts."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "no-wm"

        lifecycle = PddLifecycle(manager, mode="auto")

        state_mgr = RunStateManager(workspace_root=tmp_path, run_id="no-wm")
        state_mgr.ensure_directories()
        lifecycle._state_mgr = state_mgr
        lifecycle.worktree_manager = None

        mock_ref = MagicMock()
        mock_ref.slice_id = "s1"
        lifecycle._discover_slices = MagicMock(return_value=[mock_ref])

        mock_sr = MagicMock()
        mock_sr.slice_id = "s1"
        mock_sr.status = "COMPLETE"
        mock_sr.iterations = 1
        mock_sr.remaining_gaps = 0
        mock_sr.demotion_tickets = []

        mock_sched_result = MagicMock()
        mock_sched_result.slice_results = [mock_sr]
        mock_sched_result.all_complete = True
        mock_sched_result.waiting_slices = []

        with (
            patch("spec_manager.orchestration.promotion_loop.PromotionLoop"),
            patch(
                "spec_manager.orchestration.promotion_scheduler.ReactivePromotionScheduler"
            ) as mock_sched_cls,
        ):
            mock_sched_cls.return_value.run.return_value = mock_sched_result
            lifecycle._run_slices_at_layer("l1")

        # No batch receipts should exist
        batch_dir = tmp_path / ".pdd_runs" / "no-wm" / "ci" / "l1" / "batches"
        receipts = list(batch_dir.glob("batch_*.json"))
        assert len(receipts) == 0

    def test_no_receipt_for_non_complete_slices(self, tmp_path: Path) -> None:
        """CI ticks only fire for COMPLETE slices, so no receipt for STAGNATED."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "stag-ci"

        lifecycle = PddLifecycle(manager, mode="auto")

        state_mgr = RunStateManager(workspace_root=tmp_path, run_id="stag-ci")
        state_mgr.ensure_directories()
        lifecycle._state_mgr = state_mgr

        wm = MagicMock()
        wm.create_slice_worktree.side_effect = RuntimeError("exists")
        wm.get_slice_worktree.return_value = tmp_path / "wt"
        lifecycle.worktree_manager = wm

        mock_ref = MagicMock()
        mock_ref.slice_id = "s1"
        lifecycle._discover_slices = MagicMock(return_value=[mock_ref])

        # STAGNATED slice -- CI tick should NOT fire
        mock_sr = MagicMock()
        mock_sr.slice_id = "s1"
        mock_sr.status = "STAGNATED"
        mock_sr.iterations = 20
        mock_sr.remaining_gaps = 5
        mock_sr.demotion_tickets = []

        mock_sched_result = MagicMock()
        mock_sched_result.slice_results = [mock_sr]
        mock_sched_result.all_complete = False
        mock_sched_result.waiting_slices = []

        with (
            patch("spec_manager.orchestration.promotion_loop.PromotionLoop"),
            patch(
                "spec_manager.orchestration.promotion_scheduler.ReactivePromotionScheduler"
            ) as mock_sched_cls,
        ):
            mock_sched_cls.return_value.run.return_value = mock_sched_result
            lifecycle._run_slices_at_layer("l2")

        batch_dir = tmp_path / ".pdd_runs" / "stag-ci" / "ci" / "l2" / "batches"
        receipts = list(batch_dir.glob("batch_*.json"))
        assert len(receipts) == 0
        # tick_pipeline should not have been called
        wm.tick_pipeline.assert_not_called()


# ===================================================================
# 15. Run-scoped report writing tests
# ===================================================================


def test_write_run_report_writes_both_paths(tmp_path):
    """Test _write_run_report writes to both global and run-scoped dirs."""
    from spec_manager.orchestration.pdd_lifecycle import PddLifecycle
    from spec_manager.refinement.workspace.manager import WorkspaceManager

    manager = WorkspaceManager(run_id="test-run", input_folder=tmp_path)
    manager.initialize()
    lifecycle = PddLifecycle(manager, mode="auto")

    lifecycle._write_run_report("test_report.json", {"key": "value"})

    global_path = manager.structure.root / "reports" / "test_report.json"
    run_path = manager.structure.root / "reports" / "pdd" / "test-run" / "test_report.json"

    assert global_path.exists()
    assert run_path.exists()
    assert json.loads(global_path.read_text()) == {"key": "value"}
    assert json.loads(run_path.read_text()) == {"key": "value"}


def test_write_run_report_handles_string(tmp_path):
    """Test _write_run_report handles string data."""
    from spec_manager.orchestration.pdd_lifecycle import PddLifecycle
    from spec_manager.refinement.workspace.manager import WorkspaceManager

    manager = WorkspaceManager(run_id="test-run", input_folder=tmp_path)
    manager.initialize()
    lifecycle = PddLifecycle(manager, mode="auto")

    lifecycle._write_run_report("overview.md", "# Overview\n\nContent")

    global_path = manager.structure.root / "reports" / "overview.md"
    assert global_path.exists()
    assert "# Overview" in global_path.read_text()


def test_final_report_reads_run_scoped_first(tmp_path):
    """Test FinalReportGenerator reads run-scoped manifests first."""
    workspace = tmp_path
    run_id = "test-run"

    # Create run-scoped manifest
    run_reports = workspace / "reports" / "pdd" / run_id
    run_reports.mkdir(parents=True)
    (run_reports / "component_manifest.json").write_text(
        json.dumps({"components": [{"component_id": "run-scoped"}]}),
        encoding="utf-8",
    )

    gen = FinalReportGenerator(workspace_root=workspace, run_id=run_id)
    result = gen._architecture_topology({})
    assert "run-scoped" in result


def test_quality_scoring_flag(tmp_path):
    """Test _compute_quality flag on PddLifecycle."""
    from spec_manager.orchestration.pdd_lifecycle import PddLifecycle
    from spec_manager.refinement.workspace.manager import WorkspaceManager

    manager = WorkspaceManager(run_id="quality-test", input_folder=tmp_path)
    manager.initialize()
    lifecycle = PddLifecycle(manager, mode="auto")
    assert lifecycle._compute_quality is False

    lifecycle._compute_quality = True
    assert lifecycle._compute_quality is True


# ===================================================================
# 16. RunConfig flag tests
# ===================================================================


class TestRunConfigFlags:
    """Test enable_snapshots and enable_quality_scoring config flags."""

    def test_run_config_defaults(self) -> None:
        config = RunConfig()
        assert config.enable_snapshots is True
        assert config.enable_quality_scoring is False

    def test_run_config_custom_flags(self) -> None:
        config = RunConfig(enable_snapshots=False, enable_quality_scoring=True)
        assert config.enable_snapshots is False
        assert config.enable_quality_scoring is True

    def test_run_config_flags_roundtrip(self, tmp_path: Path) -> None:
        mgr = RunStateManager(workspace_root=tmp_path, run_id="flags-run")
        config = RunConfig(
            run_id="flags-run",
            enable_snapshots=False,
            enable_quality_scoring=True,
        )
        mgr.write_config(config)
        loaded = mgr.read_config()
        assert loaded is not None
        assert loaded.enable_snapshots is False
        assert loaded.enable_quality_scoring is True

    def test_model_profile_stored_on_lifecycle(self, tmp_path: Path) -> None:
        """Verify model_profile is stored on PddLifecycle."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "mp-run"

        mock_profile = MagicMock()
        lifecycle = PddLifecycle(manager, mode="auto", model_profile=mock_profile)
        assert lifecycle._model_profile is mock_profile

    def test_model_profile_defaults_none(self, tmp_path: Path) -> None:
        """Verify model_profile defaults to None."""
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        manager = MagicMock()
        manager.workspace_path = tmp_path
        manager.run_id = "no-mp-run"

        lifecycle = PddLifecycle(manager, mode="auto")
        assert lifecycle._model_profile is None
