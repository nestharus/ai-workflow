"""Alignment check phase evaluator.

Evaluates the alignment check phase by verifying drift detection
and intent preservation against ground truth.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spec_manager.refinement.evals.inputs.ground_truth import PhaseGroundTruth
from spec_manager.refinement.evals.loop_detector import LoopDetector, LoopStatus
from spec_manager.refinement.evals.metrics import (
    PhaseMetrics,
    score_detail_capture,
)
from spec_manager.refinement.workspace import WorkspaceManager


@dataclass
class AlignmentCheckResult:
    """Result of alignment check extraction.

    Attributes:
        analysis_items: List of analysis items extracted.
        drift_findings: List of drift findings detected.
        patches_applied: Number of patches applied.
    """

    analysis_items: list[str]
    drift_findings: list[str] = None
    patches_applied: int = 0

    def __post_init__(self) -> None:
        if self.drift_findings is None:
            self.drift_findings = []


def extract_alignment_check_outputs(manager: WorkspaceManager) -> AlignmentCheckResult:
    """Extract alignment check outputs from workspace.

    Args:
        manager: WorkspaceManager for the run.

    Returns:
        AlignmentCheckResult with analysis items and drift findings.
    """
    reports_dir = manager.structure.reports_dir
    report_path = reports_dir / "alignment_report.md"

    analysis_items: list[str] = []
    drift_findings: list[str] = []
    patches_applied = 0

    if report_path.exists():
        content = report_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- ") and "drift" in stripped.lower():
                drift_findings.append(stripped[2:])
            elif stripped.startswith("- "):
                analysis_items.append(stripped[2:])

    # Check library specs for Analysis section items
    libraries_dir = manager.structure.libraries_dir
    if libraries_dir.exists():
        for lib_dir in sorted(libraries_dir.iterdir()):
            if not lib_dir.is_dir():
                continue
            spec_path = lib_dir / "spec.md"
            if spec_path.exists():
                spec_content = spec_path.read_text(encoding="utf-8")
                in_analysis = False
                for line in spec_content.splitlines():
                    if line.strip() == "## Analysis":
                        in_analysis = True
                        continue
                    if line.startswith("## ") and in_analysis:
                        in_analysis = False
                        continue
                    if in_analysis and line.strip().startswith("- "):
                        analysis_items.append(line.strip()[2:])

    return AlignmentCheckResult(
        analysis_items=analysis_items,
        drift_findings=drift_findings,
        patches_applied=patches_applied,
    )


def compute_alignment_check_state_hash(result: AlignmentCheckResult) -> str:
    """Compute hash of alignment check state for loop detection.

    Args:
        result: AlignmentCheckResult to hash.

    Returns:
        16-character hex digest.
    """
    content = "|".join([
        ",".join(sorted(result.analysis_items)),
        ",".join(sorted(result.drift_findings)),
    ])
    return LoopDetector.compute_hash(content)


def eval_alignment_check(
    manager: WorkspaceManager,
    ground_truth: PhaseGroundTruth,
    loop_detector: LoopDetector,
    fuzzy_threshold: float = 0.8,
    max_iterations: int = 5,
) -> PhaseMetrics:
    """Evaluate alignment check phase against ground truth.

    Args:
        manager: WorkspaceManager for the run.
        ground_truth: Expected outputs for this phase.
        loop_detector: Loop detector for stagnation detection.
        fuzzy_threshold: Threshold for fuzzy string matching.
        max_iterations: Maximum iterations to attempt.

    Returns:
        PhaseMetrics for the alignment check phase.
    """
    start_time = time.perf_counter()
    iterations = 0
    converged = False
    trajectory: list[float] = []

    expected_items = (
        ground_truth.custom_expectations.get("expected_analysis_items", []) +
        ground_truth.expected_requirements
    )

    for iteration in range(1, max_iterations + 1):
        iterations = iteration

        # Extract current outputs
        result = extract_alignment_check_outputs(manager)
        actual_items = result.analysis_items + result.drift_findings

        # Score against ground truth
        score = score_detail_capture(
            expected_items, actual_items, fuzzy_threshold=fuzzy_threshold
        )

        trajectory.append(score.recall)

        # Check for loop conditions
        state_hash = compute_alignment_check_state_hash(result)
        loop_status = loop_detector.update(state_hash)

        if loop_status in {LoopStatus.STAGNANT, LoopStatus.CYCLING, LoopStatus.MAX_ITERATIONS}:
            break

        # Check for convergence
        if score.recall >= 0.95:
            converged = True
            break

    # Final scoring
    final_result = extract_alignment_check_outputs(manager)
    final_actual = final_result.analysis_items + final_result.drift_findings
    final_score = score_detail_capture(
        expected_items, final_actual, fuzzy_threshold=fuzzy_threshold
    )

    duration_ms = (time.perf_counter() - start_time) * 1000

    return PhaseMetrics(
        phase_name="alignment_check",
        detail_score=final_score,
        iterations=iterations,
        converged=converged,
        duration_ms=duration_ms,
        gaps_open=final_score.expected_count - final_score.matched_count,
        gaps_closed=final_score.matched_count,
    )
