"""Quality gates phase evaluator.

Evaluates the quality gates phase by comparing dimension scores and
element IDs against ground truth expectations using exact matching.
"""

from __future__ import annotations

import json
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
class QualityGatesResult:
    """Result of quality gates extraction.

    Attributes:
        dimension_scores: Mapping of dimension names to their scores.
        element_ids_found: List of element IDs found in quality gate output.
    """

    dimension_scores: dict[str, float]
    element_ids_found: list[str] = None

    def __post_init__(self) -> None:
        if self.element_ids_found is None:
            self.element_ids_found = []


def extract_quality_gates_outputs(
    manager: WorkspaceManager,
) -> QualityGatesResult:
    """Extract quality gates outputs from workspace.

    Reads from reports/quality_gates.json which contains structured
    quality gate evaluation data.

    Args:
        manager: WorkspaceManager for the run.

    Returns:
        QualityGatesResult with dimension scores and element IDs.
    """
    reports_dir = manager.structure.reports_dir
    report_path = reports_dir / "quality_gates.json"

    dimension_scores: dict[str, float] = {}
    element_ids_found: list[str] = []

    if report_path.exists():
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))

            # Extract dimension scores
            for dimension in data.get("dimensions", []):
                if isinstance(dimension, dict):
                    name = dimension.get("name") or dimension.get("dimension")
                    score = dimension.get("score") or dimension.get("value")
                    if name and score is not None:
                        dimension_scores[name] = float(score)
                elif isinstance(dimension, str):
                    dimension_scores[dimension] = 0.0

            # Extract top-level scores if dimensions not nested
            if not dimension_scores:
                scores = data.get("scores", {})
                if isinstance(scores, dict):
                    for name, value in scores.items():
                        if isinstance(value, (int, float)):
                            dimension_scores[name] = float(value)

            # Extract element IDs
            for element_id in data.get("element_ids", []):
                if isinstance(element_id, str):
                    element_ids_found.append(element_id)

            # Also check elements list
            for element in data.get("elements", []):
                if isinstance(element, str):
                    element_ids_found.append(element)
                elif isinstance(element, dict):
                    eid = element.get("id") or element.get("element_id")
                    if eid:
                        element_ids_found.append(eid)

        except (json.JSONDecodeError, OSError):
            pass

    return QualityGatesResult(
        dimension_scores=dimension_scores,
        element_ids_found=sorted(set(element_ids_found)),
    )


def compute_quality_gates_state_hash(result: QualityGatesResult) -> str:
    """Compute hash of quality gates state for loop detection.

    Args:
        result: QualityGatesResult to hash.

    Returns:
        16-character hex digest.
    """
    scores_str = ",".join(f"{k}={v}" for k, v in sorted(result.dimension_scores.items()))
    content = "|".join(
        [
            scores_str,
            ",".join(sorted(result.element_ids_found)),
        ]
    )
    return LoopDetector.compute_hash(content)


def eval_quality_gates(
    manager: WorkspaceManager,
    ground_truth: PhaseGroundTruth,
    loop_detector: LoopDetector,
    fuzzy_threshold: float = 1.0,
    max_iterations: int = 5,
) -> PhaseMetrics:
    """Evaluate quality gates phase against ground truth.

    Uses exact matching (fuzzy_threshold=1.0) for element IDs since
    they must match precisely.

    Args:
        manager: WorkspaceManager for the run.
        ground_truth: Expected outputs for this phase.
        loop_detector: Loop detector for stagnation detection.
        fuzzy_threshold: Threshold for matching (default 1.0 for exact).
        max_iterations: Maximum iterations to attempt.

    Returns:
        PhaseMetrics for the quality gates phase.
    """
    start_time = time.perf_counter()
    iterations = 0
    converged = False
    trajectory: list[float] = []

    expected_items = ground_truth.expected_elements

    for iteration in range(1, max_iterations + 1):
        iterations = iteration

        # Extract current outputs
        result = extract_quality_gates_outputs(manager)
        actual_items = result.element_ids_found

        # Score against ground truth with exact matching
        score = score_detail_capture(
            expected_items,
            actual_items,
            fuzzy_threshold=fuzzy_threshold,
        )

        trajectory.append(score.recall)

        # Check for loop conditions
        state_hash = compute_quality_gates_state_hash(result)
        loop_status = loop_detector.update(state_hash)

        if loop_status in {LoopStatus.STAGNANT, LoopStatus.CYCLING, LoopStatus.MAX_ITERATIONS}:
            break

        # Check for convergence
        if score.recall >= 0.95:
            converged = True
            break

    # Final scoring
    final_result = extract_quality_gates_outputs(manager)
    final_actual = final_result.element_ids_found
    final_score = score_detail_capture(
        expected_items,
        final_actual,
        fuzzy_threshold=fuzzy_threshold,
    )

    duration_ms = (time.perf_counter() - start_time) * 1000

    return PhaseMetrics(
        phase_name="quality_gates",
        detail_score=final_score,
        iterations=iterations,
        converged=converged,
        duration_ms=duration_ms,
        gaps_open=final_score.expected_count - final_score.matched_count,
        gaps_closed=final_score.matched_count,
    )
