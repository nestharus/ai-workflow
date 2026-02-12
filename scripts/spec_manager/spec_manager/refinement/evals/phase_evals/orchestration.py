"""Orchestration-level eval paths for PromotionLoop and PddLifecycle.

Provides functions that set up a workspace from PDD fixtures, install
Phase 0 output, and run the orchestration layer with REAL LLM calls.
No mocks, no test doubles, no patches.

The eval functions use the actual production classes:
- PromotionLoop.run_slice() for per-slice evaluation
- PddLifecycle._run_layer() for full layer evaluation
- PddLifecycle._run_transition() for cross-layer transitions
- RunReporter for scoring
- FinalReportGenerator for final reports
- PddLifecycle.run() for full end-to-end pipeline

Usage (step-by-step QA)::

    manager, ws = setup_orchestration_workspace()
    slices = discover_eval_slices(manager, "l1")
    result = run_promotion_loop_slice(manager, "l1", slices[0]["slice_id"])
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from spec_manager.core.project_root import resolve_from_root
from spec_manager.orchestration.pdd_orchestrator import PddOrchestrator
from spec_manager.refinement.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)

_FIXTURES = resolve_from_root(
    "scripts", "spec_manager", "spec_manager", "refinement", "evals", "inputs", "fixtures"
)
_PDD_DIR = _FIXTURES / "chaotic_treasury_expanded_pdd"
_P0_OUTPUT = _FIXTURES / "chaotic_treasury_expanded_phase0_output"


def setup_orchestration_workspace(
    run_id: str = "orchestration-qa",
) -> tuple[WorkspaceManager, Path]:
    """Create workspace from PDD fixtures and install Phase 0 output.

    Returns:
        Tuple of (WorkspaceManager, workspace_path).
    """
    manager = WorkspaceManager(run_id=run_id, input_folder=_PDD_DIR)
    manager.initialize(force=True)

    orchestrator = PddOrchestrator(manager)
    orchestrator._install_phase0_output(_P0_OUTPUT)

    return manager, manager.workspace_path


def discover_eval_slices(
    manager: WorkspaceManager,
    layer: str,
) -> list[dict[str, Any]]:
    """Discover available slices for evaluation at a given layer.

    Uses PddLifecycle._discover_slices() — the actual production code path.

    For L1: slices = libraries (concern boundaries).
    For L2: slices = architectural components from manifest or libraries.
    For L3: slices = individual Python files.
    """
    from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

    lifecycle = PddLifecycle(manager, mode="auto")
    slice_refs = lifecycle._discover_slices(layer)

    return [
        {
            "slice_id": ref.slice_id,
            "layer": ref.layer,
            "library_id": ref.library_id,
            "worktree_path": ref.worktree_path,
        }
        for ref in slice_refs
    ]


def run_promotion_loop_slice(
    manager: WorkspaceManager,
    layer: str,
    slice_id: str,
    worktree_path: str | None = None,
) -> dict[str, Any]:
    """Run PromotionLoop.run_slice() on a single slice with real LLM calls.

    Uses the actual PromotionLoop state machine (10 steps: COLLECT through ALIGN).

    Args:
        manager: Initialized workspace manager.
        layer: Layer to run at (l1, l2, l3).
        slice_id: Slice identifier.
        worktree_path: Override worktree path (defaults to spec_snapshot_dir).

    Returns:
        Dict with slice_id, status, iterations, remaining_gaps, demotion_count, error.
    """
    from spec_manager.orchestration.promotion_loop import (
        PromotionLoop,
        RunContext,
        SliceRef,
    )

    effective_worktree = worktree_path or str(manager.structure.spec_snapshot_dir)

    slice_ref = SliceRef(
        slice_id=slice_id,
        layer=layer,
        library_id=slice_id if layer == "l1" else "",
        worktree_path=effective_worktree,
    )

    run_context = RunContext(
        run_id=manager.run_id,
        mode="auto",
        workspace_root=str(manager.workspace_path),
    )

    loop = PromotionLoop(workspace_root=manager.workspace_path)

    start = time.perf_counter()
    result = loop.run_slice(slice_ref, run_context)
    duration_ms = (time.perf_counter() - start) * 1000

    return {
        "slice_id": result.slice_id,
        "status": result.status,
        "iterations": result.iterations,
        "remaining_gaps": result.remaining_gaps,
        "demotion_count": len(result.demotion_tickets),
        "blocked_questions": result.blocked_questions,
        "error": result.error,
        "duration_ms": duration_ms,
    }


def run_lifecycle_layer(
    manager: WorkspaceManager,
    layer: str,
) -> dict[str, Any]:
    """Run PddLifecycle._run_layer() for a single layer with real LLM calls.

    Runs: entry refinement -> per-slice PromotionLoop -> exit refinement.

    Returns:
        Dict from _run_layer() with entry_refinement, slices, exit_refinement,
        plus duration_ms.
    """
    from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

    lifecycle = PddLifecycle(manager, mode="auto")

    start = time.perf_counter()
    result = lifecycle._run_layer(layer)
    duration_ms = (time.perf_counter() - start) * 1000

    result["duration_ms"] = duration_ms
    return result


def run_lifecycle_transition(
    manager: WorkspaceManager,
    from_layer: str,
    to_layer: str,
) -> dict[str, Any]:
    """Run PddLifecycle._run_transition() between layers with real LLM calls.

    Runs the next layer's typed refinement as a gate. If demotion tickets
    are emitted, re-runs previous layer slices (up to 3 rounds).

    Returns:
        Dict from _run_transition() with refinement, rework_rounds,
        transition_stuck, plus duration_ms.
    """
    from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

    lifecycle = PddLifecycle(manager, mode="auto")

    start = time.perf_counter()
    result = lifecycle._run_transition(from_layer, to_layer)
    duration_ms = (time.perf_counter() - start) * 1000

    result["duration_ms"] = duration_ms
    return result


def run_scoring(
    manager: WorkspaceManager,
    run_results: dict[str, Any],
) -> dict[str, Any]:
    """Compute scorecard using RunReporter (5 hard gates, 11 soft signals).

    Returns:
        Dict with scorecard, paths, overall_pass, and summary.
    """
    from spec_manager.evaluation.scoring import RunReporter

    reporter = RunReporter(
        workspace_root=manager.workspace_path,
        run_id=manager.run_id,
    )

    scorecard = reporter.compute(run_results)
    scores_path, md_path = reporter.write(scorecard)

    return {
        "scorecard": scorecard.to_dict(),
        "scores_path": str(scores_path),
        "scorecard_md_path": str(md_path),
        "overall_pass": scorecard.overall_pass,
        "hard_gates_passed": sum(1 for g in scorecard.hard_gates if g.status != "FAIL"),
        "hard_gates_total": len(scorecard.hard_gates),
        "summary": scorecard.summary,
    }


def run_final_report(
    manager: WorkspaceManager,
    run_results: dict[str, Any],
) -> dict[str, Any]:
    """Generate final report using FinalReportGenerator.

    Computes scorecard internally and generates final_report.md + scorecard.json.

    Returns:
        Dict with report_path and scorecard_json_path.
    """
    from spec_manager.evaluation.report import FinalReportGenerator
    from spec_manager.evaluation.scoring import RunReporter

    reporter = RunReporter(
        workspace_root=manager.workspace_path,
        run_id=manager.run_id,
    )
    scorecard = reporter.compute(run_results)

    gen = FinalReportGenerator(
        workspace_root=manager.workspace_path,
        run_id=manager.run_id,
    )

    report_path, scorecard_json_path = gen.generate(run_results, scorecard)

    return {
        "report_path": str(report_path),
        "scorecard_json_path": str(scorecard_json_path),
    }


def run_full_pipeline(
    manager: WorkspaceManager,
) -> dict[str, Any]:
    """Run PddLifecycle.run() — the full L1 -> L2 -> L3 pipeline.

    This runs intake, L1 with approval, transitions, L2, L3, QA,
    scoring, final report, governance, and release signoff.

    Returns:
        Full results dict from PddLifecycle.run() plus duration_ms.
    """
    from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

    lifecycle = PddLifecycle(manager, mode="auto")

    start = time.perf_counter()
    result = lifecycle.run()
    duration_ms = (time.perf_counter() - start) * 1000

    result["duration_ms"] = duration_ms
    return result
