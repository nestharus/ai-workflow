"""Spec building phase evaluator.

Evaluates the spec building phase by comparing built specifications
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
class SpecBuildingResult:
    """Result of spec building extraction.

    Attributes:
        requirements_captured: List of captured requirement IDs/descriptions.
        citations_found: List of citation references.
        decisions_made: List of design decisions.
        constraints_identified: List of identified constraints.
        file_count: Number of files processed.
    """

    requirements_captured: list[str]
    citations_found: list[str] = None
    decisions_made: list[str] = None
    constraints_identified: list[str] = None
    file_count: int = 0

    def __post_init__(self) -> None:
        if self.citations_found is None:
            self.citations_found = []
        if self.decisions_made is None:
            self.decisions_made = []
        if self.constraints_identified is None:
            self.constraints_identified = []


def extract_spec_building_outputs(manager: WorkspaceManager) -> SpecBuildingResult:
    """Extract spec building outputs from workspace.

    Args:
        manager: WorkspaceManager for the run.

    Returns:
        SpecBuildingResult with captured requirements and related data.
    """
    specs_dir = manager.structure.manifest_dir / "specs"

    requirements_captured: set[str] = set()
    citations_found: set[str] = set()
    decisions_made: set[str] = set()
    constraints_identified: set[str] = set()
    file_count = 0

    # Read specs from manifest
    if specs_dir.exists():
        for spec_file in specs_dir.glob("*.spec.json"):
            file_count += 1
            try:
                data = json.loads(spec_file.read_text(encoding="utf-8"))

                # Extract requirements
                for req in data.get("requirements", []):
                    if isinstance(req, str):
                        requirements_captured.add(req)
                    elif isinstance(req, dict):
                        req_text = req.get("description") or req.get("text") or req.get("id")
                        if req_text:
                            requirements_captured.add(req_text)

                # Extract citations
                for citation in data.get("citations", []):
                    if isinstance(citation, str):
                        citations_found.add(citation)
                    elif isinstance(citation, dict):
                        cite_ref = citation.get("reference") or citation.get("source")
                        if cite_ref:
                            citations_found.add(cite_ref)

                # Extract decisions
                for decision in data.get("decisions", []):
                    if isinstance(decision, str):
                        decisions_made.add(decision)
                    elif isinstance(decision, dict):
                        decision_text = decision.get("description") or decision.get("decision")
                        if decision_text:
                            decisions_made.add(decision_text)

                # Extract constraints
                for constraint in data.get("constraints", []):
                    if isinstance(constraint, str):
                        constraints_identified.add(constraint)
                    elif isinstance(constraint, dict):
                        constraint_text = constraint.get("description") or constraint.get("constraint")
                        if constraint_text:
                            constraints_identified.add(constraint_text)

            except (json.JSONDecodeError, OSError):
                continue

    # Also check for requirement files directly
    reqs_dir = manager.structure.manifest_dir / "requirements"
    if reqs_dir.exists():
        for req_file in reqs_dir.glob("*.requirements.json"):
            file_count += 1
            try:
                data = json.loads(req_file.read_text(encoding="utf-8"))

                for req in data.get("requirements", []):
                    if isinstance(req, str):
                        requirements_captured.add(req)
                    elif isinstance(req, dict):
                        req_text = req.get("description") or req.get("text") or req.get("id")
                        if req_text:
                            requirements_captured.add(req_text)

            except (json.JSONDecodeError, OSError):
                continue

    return SpecBuildingResult(
        requirements_captured=sorted(requirements_captured),
        citations_found=sorted(citations_found),
        decisions_made=sorted(decisions_made),
        constraints_identified=sorted(constraints_identified),
        file_count=file_count,
    )


def compute_spec_building_state_hash(result: SpecBuildingResult) -> str:
    """Compute hash of spec building state for loop detection.

    Args:
        result: SpecBuildingResult to hash.

    Returns:
        16-character hex digest.
    """
    content = "|".join([
        ",".join(sorted(result.requirements_captured)),
        ",".join(sorted(result.citations_found)),
        ",".join(sorted(result.decisions_made)),
    ])
    return LoopDetector.compute_hash(content)


def eval_spec_building(
    manager: WorkspaceManager,
    ground_truth: PhaseGroundTruth,
    loop_detector: LoopDetector,
    fuzzy_threshold: float = 0.8,
    max_iterations: int = 5,
) -> PhaseMetrics:
    """Evaluate spec building phase against ground truth.

    Args:
        manager: WorkspaceManager for the run.
        ground_truth: Expected outputs for this phase.
        loop_detector: Loop detector for stagnation detection.
        fuzzy_threshold: Threshold for fuzzy string matching.
        max_iterations: Maximum iterations to attempt.

    Returns:
        PhaseMetrics for the spec building phase.
    """
    start_time = time.perf_counter()
    iterations = 0
    converged = False
    trajectory: list[float] = []

    # Combine expected items for comprehensive scoring
    expected_items = (
        ground_truth.expected_requirements +
        ground_truth.expected_citations +
        ground_truth.expected_decisions
    )

    for iteration in range(1, max_iterations + 1):
        iterations = iteration

        # Extract current outputs
        result = extract_spec_building_outputs(manager)

        # Combine actual items for scoring
        actual_items = (
            result.requirements_captured +
            result.citations_found +
            result.decisions_made
        )

        # Score against ground truth
        score = score_detail_capture(
            expected_items,
            actual_items,
            fuzzy_threshold=fuzzy_threshold,
        )

        trajectory.append(score.recall)

        # Check for loop conditions
        state_hash = compute_spec_building_state_hash(result)
        loop_status = loop_detector.update(state_hash)

        if loop_status in {LoopStatus.STAGNANT, LoopStatus.CYCLING, LoopStatus.MAX_ITERATIONS}:
            break

        # Check for convergence
        if score.recall >= 0.95:
            converged = True
            break

    # Final scoring
    final_result = extract_spec_building_outputs(manager)
    final_actual = (
        final_result.requirements_captured +
        final_result.citations_found +
        final_result.decisions_made
    )
    final_score = score_detail_capture(
        expected_items,
        final_actual,
        fuzzy_threshold=fuzzy_threshold,
    )

    duration_ms = (time.perf_counter() - start_time) * 1000

    return PhaseMetrics(
        phase_name="spec_building",
        detail_score=final_score,
        iterations=iterations,
        converged=converged,
        duration_ms=duration_ms,
        gaps_open=final_score.expected_count - final_score.matched_count,
        gaps_closed=final_score.matched_count,
    )
