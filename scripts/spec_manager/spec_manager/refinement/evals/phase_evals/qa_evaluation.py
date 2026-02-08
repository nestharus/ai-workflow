"""QA evaluation phase evaluator.

Evaluates the QA evaluation phase by comparing findings and detail items
against ground truth expectations.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from spec_manager.refinement.evals.inputs.ground_truth import PhaseGroundTruth
from spec_manager.refinement.evals.loop_detector import LoopDetector, LoopStatus
from spec_manager.refinement.evals.metrics import (
    PhaseMetrics,
    score_detail_capture,
)
from spec_manager.refinement.workspace import WorkspaceManager


@dataclass
class QAEvaluationResult:
    """Result of QA evaluation extraction.

    Attributes:
        findings: List of QA findings detected.
        detail_items: List of detailed evaluation items.
    """

    findings: list[str]
    detail_items: list[str] = None

    def __post_init__(self) -> None:
        if self.detail_items is None:
            self.detail_items = []


def extract_qa_evaluation_outputs(manager: WorkspaceManager) -> QAEvaluationResult:
    """Extract QA evaluation outputs from workspace.

    Args:
        manager: WorkspaceManager for the run.

    Returns:
        QAEvaluationResult with findings and detail items.
    """
    reports_dir = manager.structure.reports_dir
    report_path = reports_dir / "qa_evaluation.md"

    findings: list[str] = []
    detail_items: list[str] = []

    if report_path.exists():
        content = report_path.read_text(encoding="utf-8")
        in_findings = False
        in_details = False

        for line in content.splitlines():
            stripped = line.strip()

            # Track section context
            if stripped.startswith("## "):
                heading = stripped[3:].strip().lower()
                in_findings = "finding" in heading
                in_details = "detail" in heading or "item" in heading
                continue

            # Extract bullet items based on section
            if stripped.startswith("- "):
                item_text = stripped[2:]
                if in_findings:
                    findings.append(item_text)
                elif in_details:
                    detail_items.append(item_text)
                else:
                    # Default to findings for items outside known sections
                    findings.append(item_text)

    return QAEvaluationResult(
        findings=findings,
        detail_items=detail_items,
    )


def compute_qa_evaluation_state_hash(result: QAEvaluationResult) -> str:
    """Compute hash of QA evaluation state for loop detection.

    Args:
        result: QAEvaluationResult to hash.

    Returns:
        16-character hex digest.
    """
    content = "|".join(
        [
            ",".join(sorted(result.findings)),
            ",".join(sorted(result.detail_items)),
        ]
    )
    return LoopDetector.compute_hash(content)


def eval_qa_evaluation(
    manager: WorkspaceManager,
    ground_truth: PhaseGroundTruth,
    loop_detector: LoopDetector,
    fuzzy_threshold: float = 0.8,
    max_iterations: int = 5,
) -> PhaseMetrics:
    """Evaluate QA evaluation phase against ground truth.

    Args:
        manager: WorkspaceManager for the run.
        ground_truth: Expected outputs for this phase.
        loop_detector: Loop detector for stagnation detection.
        fuzzy_threshold: Threshold for fuzzy string matching.
        max_iterations: Maximum iterations to attempt.

    Returns:
        PhaseMetrics for the QA evaluation phase.
    """
    start_time = time.perf_counter()
    iterations = 0
    converged = False
    trajectory: list[float] = []

    expected_items = ground_truth.custom_expectations.get("expected_detail_items", [])

    for iteration in range(1, max_iterations + 1):
        iterations = iteration

        # Extract current outputs
        result = extract_qa_evaluation_outputs(manager)
        actual_items = result.findings + result.detail_items

        # Score against ground truth
        score = score_detail_capture(
            expected_items,
            actual_items,
            fuzzy_threshold=fuzzy_threshold,
        )

        trajectory.append(score.recall)

        # Check for loop conditions
        state_hash = compute_qa_evaluation_state_hash(result)
        loop_status = loop_detector.update(state_hash)

        if loop_status in {LoopStatus.STAGNANT, LoopStatus.CYCLING, LoopStatus.MAX_ITERATIONS}:
            break

        # Check for convergence
        if score.recall >= 0.95:
            converged = True
            break

    # Final scoring
    final_result = extract_qa_evaluation_outputs(manager)
    final_actual = final_result.findings + final_result.detail_items
    final_score = score_detail_capture(
        expected_items,
        final_actual,
        fuzzy_threshold=fuzzy_threshold,
    )

    duration_ms = (time.perf_counter() - start_time) * 1000

    return PhaseMetrics(
        phase_name="qa_evaluation",
        detail_score=final_score,
        iterations=iterations,
        converged=converged,
        duration_ms=duration_ms,
        gaps_open=final_score.expected_count - final_score.matched_count,
        gaps_closed=final_score.matched_count,
    )
