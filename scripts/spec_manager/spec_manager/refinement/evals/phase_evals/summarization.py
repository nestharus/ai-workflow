"""Summarization phase evaluator.

Evaluates the summarization phase by comparing generated summaries
against ground truth expectations.
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
class SummarizationResult:
    """Result of summarization extraction.

    Attributes:
        summaries_generated: List of summary identifiers.
        key_points_extracted: Number of key points extracted.
        topics_identified: List of identified topics.
        file_count: Number of files processed.
    """

    summaries_generated: list[str]
    key_points_extracted: int = 0
    topics_identified: list[str] = None
    file_count: int = 0

    def __post_init__(self) -> None:
        if self.topics_identified is None:
            self.topics_identified = []


def extract_summarization_outputs(manager: WorkspaceManager) -> SummarizationResult:
    """Extract summarization outputs from workspace.

    Args:
        manager: WorkspaceManager for the run.

    Returns:
        SummarizationResult with extracted summaries and counts.
    """
    summaries_dir = manager.structure.manifest_dir / "summaries"

    summaries_generated: list[str] = []
    key_points_extracted = 0
    topics_identified: set[str] = set()
    file_count = 0

    # Read summaries from manifest
    if summaries_dir.exists():
        for summary_file in summaries_dir.glob("*.summary.json"):
            file_count += 1
            try:
                data = json.loads(summary_file.read_text(encoding="utf-8"))

                # Extract summary identifier
                summary_id = data.get("summary_id") or summary_file.stem.replace(".summary", "")
                summaries_generated.append(summary_id)

                # Count key points
                key_points = data.get("key_points", [])
                key_points_extracted += len(key_points)

                # Extract topics
                for topic in data.get("topics", []):
                    if isinstance(topic, str):
                        topics_identified.add(topic)
                    elif isinstance(topic, dict):
                        topic_name = topic.get("name") or topic.get("topic")
                        if topic_name:
                            topics_identified.add(topic_name)

            except (json.JSONDecodeError, OSError):
                continue

    return SummarizationResult(
        summaries_generated=sorted(summaries_generated),
        key_points_extracted=key_points_extracted,
        topics_identified=sorted(topics_identified),
        file_count=file_count,
    )


def compute_summarization_state_hash(result: SummarizationResult) -> str:
    """Compute hash of summarization state for loop detection.

    Args:
        result: SummarizationResult to hash.

    Returns:
        16-character hex digest.
    """
    content = "|".join([
        ",".join(sorted(result.summaries_generated)),
        str(result.key_points_extracted),
        ",".join(sorted(result.topics_identified)),
    ])
    return LoopDetector.compute_hash(content)


def eval_summarization(
    manager: WorkspaceManager,
    ground_truth: PhaseGroundTruth,
    loop_detector: LoopDetector,
    fuzzy_threshold: float = 0.8,
    max_iterations: int = 5,
) -> PhaseMetrics:
    """Evaluate summarization phase against ground truth.

    Args:
        manager: WorkspaceManager for the run.
        ground_truth: Expected outputs for this phase.
        loop_detector: Loop detector for stagnation detection.
        fuzzy_threshold: Threshold for fuzzy string matching.
        max_iterations: Maximum iterations to attempt.

    Returns:
        PhaseMetrics for the summarization phase.
    """
    start_time = time.perf_counter()
    iterations = 0
    converged = False
    trajectory: list[float] = []

    # Combine expected elements for comparison
    expected_items = (
        ground_truth.expected_elements +
        ground_truth.expected_requirements
    )

    for iteration in range(1, max_iterations + 1):
        iterations = iteration

        # Extract current outputs
        result = extract_summarization_outputs(manager)

        # Combine actual items for scoring
        actual_items = result.summaries_generated + result.topics_identified

        # Score against ground truth
        score = score_detail_capture(
            expected_items,
            actual_items,
            fuzzy_threshold=fuzzy_threshold,
        )

        trajectory.append(score.recall)

        # Check for loop conditions
        state_hash = compute_summarization_state_hash(result)
        loop_status = loop_detector.update(state_hash)

        if loop_status in {LoopStatus.STAGNANT, LoopStatus.CYCLING, LoopStatus.MAX_ITERATIONS}:
            break

        # Check for convergence
        if score.recall >= 0.95:
            converged = True
            break

    # Final scoring
    final_result = extract_summarization_outputs(manager)
    final_actual = final_result.summaries_generated + final_result.topics_identified
    final_score = score_detail_capture(
        expected_items,
        final_actual,
        fuzzy_threshold=fuzzy_threshold,
    )

    duration_ms = (time.perf_counter() - start_time) * 1000

    return PhaseMetrics(
        phase_name="summarization",
        detail_score=final_score,
        iterations=iterations,
        converged=converged,
        duration_ms=duration_ms,
        gaps_open=final_score.expected_count - final_score.matched_count,
        gaps_closed=final_score.matched_count,
    )
