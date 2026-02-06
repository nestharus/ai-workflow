"""Overview generation phase evaluator.

Evaluates the overview generation phase by comparing generated overview
content against ground truth expectations.
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
class OverviewGenerationResult:
    """Result of overview generation extraction.

    Attributes:
        overview_elements: List of overview element descriptions.
        prose_sections: List of prose section headings or summaries.
    """

    overview_elements: list[str]
    prose_sections: list[str] = None

    def __post_init__(self) -> None:
        if self.prose_sections is None:
            self.prose_sections = []


def extract_overview_generation_outputs(
    manager: WorkspaceManager,
) -> OverviewGenerationResult:
    """Extract overview generation outputs from workspace.

    Args:
        manager: WorkspaceManager for the run.

    Returns:
        OverviewGenerationResult with overview elements and prose sections.
    """
    reports_dir = manager.structure.reports_dir
    overview_path = reports_dir / "overview.md"

    overview_elements: list[str] = []
    prose_sections: list[str] = []

    if overview_path.exists():
        content = overview_path.read_text(encoding="utf-8")
        current_section: str | None = None

        for line in content.splitlines():
            stripped = line.strip()

            # Track section headings
            if stripped.startswith("## "):
                current_section = stripped[3:].strip()
                prose_sections.append(current_section)
                continue

            # Extract bullet items as overview elements
            if stripped.startswith("- "):
                overview_elements.append(stripped[2:])

    return OverviewGenerationResult(
        overview_elements=overview_elements,
        prose_sections=prose_sections,
    )


def compute_overview_generation_state_hash(
    result: OverviewGenerationResult,
) -> str:
    """Compute hash of overview generation state for loop detection.

    Args:
        result: OverviewGenerationResult to hash.

    Returns:
        16-character hex digest.
    """
    content = "|".join([
        ",".join(sorted(result.overview_elements)),
        ",".join(sorted(result.prose_sections)),
    ])
    return LoopDetector.compute_hash(content)


def eval_overview_generation(
    manager: WorkspaceManager,
    ground_truth: PhaseGroundTruth,
    loop_detector: LoopDetector,
    fuzzy_threshold: float = 0.5,
    max_iterations: int = 5,
) -> PhaseMetrics:
    """Evaluate overview generation phase against ground truth.

    Uses a lower fuzzy_threshold (0.5) since prose matching requires
    more tolerance for variation in natural language expression.

    Args:
        manager: WorkspaceManager for the run.
        ground_truth: Expected outputs for this phase.
        loop_detector: Loop detector for stagnation detection.
        fuzzy_threshold: Threshold for fuzzy string matching (default 0.5).
        max_iterations: Maximum iterations to attempt.

    Returns:
        PhaseMetrics for the overview generation phase.
    """
    start_time = time.perf_counter()
    iterations = 0
    converged = False
    trajectory: list[float] = []

    expected_items = ground_truth.custom_expectations.get(
        "expected_overview_elements", []
    )

    for iteration in range(1, max_iterations + 1):
        iterations = iteration

        # Extract current outputs
        result = extract_overview_generation_outputs(manager)
        actual_items = result.overview_elements + result.prose_sections

        # Score against ground truth
        score = score_detail_capture(
            expected_items,
            actual_items,
            fuzzy_threshold=fuzzy_threshold,
        )

        trajectory.append(score.recall)

        # Check for loop conditions
        state_hash = compute_overview_generation_state_hash(result)
        loop_status = loop_detector.update(state_hash)

        if loop_status in {LoopStatus.STAGNANT, LoopStatus.CYCLING, LoopStatus.MAX_ITERATIONS}:
            break

        # Check for convergence
        if score.recall >= 0.95:
            converged = True
            break

    # Final scoring
    final_result = extract_overview_generation_outputs(manager)
    final_actual = final_result.overview_elements + final_result.prose_sections
    final_score = score_detail_capture(
        expected_items,
        final_actual,
        fuzzy_threshold=fuzzy_threshold,
    )

    duration_ms = (time.perf_counter() - start_time) * 1000

    return PhaseMetrics(
        phase_name="overview_generation",
        detail_score=final_score,
        iterations=iterations,
        converged=converged,
        duration_ms=duration_ms,
        gaps_open=final_score.expected_count - final_score.matched_count,
        gaps_closed=final_score.matched_count,
    )
