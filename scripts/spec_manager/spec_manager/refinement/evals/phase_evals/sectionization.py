"""Sectionization phase evaluator.

Evaluates the sectionization phase by comparing detected sections
against ground truth expectations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from spec_manager.refinement.evals.inputs.ground_truth import PhaseGroundTruth
from spec_manager.refinement.evals.loop_detector import LoopDetector, LoopStatus
from spec_manager.refinement.evals.metrics import (
    PhaseMetrics,
    score_detail_capture,
)
from spec_manager.refinement.workspace import WorkspaceManager


@dataclass
class SectionizationResult:
    """Result of sectionization evaluation.

    Attributes:
        sections_detected: List of detected section labels.
        atoms_emitted: Number of atoms emitted.
        terms_extracted: Number of terms extracted.
        file_count: Number of files processed.
    """

    sections_detected: list[str]
    atoms_emitted: int = 0
    terms_extracted: int = 0
    file_count: int = 0
    parse_failures: list[str] = field(default_factory=list)


def extract_sectionization_outputs(manager: WorkspaceManager) -> SectionizationResult:
    """Extract sectionization outputs from workspace.

    Args:
        manager: WorkspaceManager for the run.

    Returns:
        SectionizationResult with detected sections and counts.
    """
    sections_dir = manager.structure.manifest_sections_dir
    atoms_dir = manager.structure.manifest_atoms_dir
    terms_dir = manager.structure.manifest_terms_dir

    sections_detected: set[str] = set()
    atoms_emitted = 0
    terms_extracted = 0
    file_count = 0
    parse_failures: list[str] = []

    # Read sections from manifest
    if sections_dir.exists():
        for sections_file in sections_dir.glob("*.sections.json"):
            file_count += 1
            try:
                data = json.loads(sections_file.read_text(encoding="utf-8"))
                for section in data.get("sections", []):
                    label = section.get("label") or section.get("section_id")
                    if label:
                        sections_detected.add(label)
            except json.JSONDecodeError as exc:
                parse_failures.append(f"invalid_json:{sections_file}:{exc}")
                continue
            except OSError as exc:
                parse_failures.append(f"unreadable:{sections_file}:{exc}")
                continue

    # Count atoms
    if atoms_dir.exists():
        for atoms_file in atoms_dir.glob("*.atoms.jsonl"):
            try:
                content = atoms_file.read_text(encoding="utf-8")
                atoms_emitted += sum(1 for line in content.splitlines() if line.strip())
            except OSError as exc:
                parse_failures.append(f"unreadable:{atoms_file}:{exc}")
                continue

    # Count terms
    if terms_dir.exists():
        for terms_file in terms_dir.glob("*.terms.json"):
            try:
                data = json.loads(terms_file.read_text(encoding="utf-8"))
                terms_extracted += len(data.get("terms", []))
            except json.JSONDecodeError as exc:
                parse_failures.append(f"invalid_json:{terms_file}:{exc}")
                continue
            except OSError as exc:
                parse_failures.append(f"unreadable:{terms_file}:{exc}")
                continue

    return SectionizationResult(
        sections_detected=sorted(sections_detected),
        atoms_emitted=atoms_emitted,
        terms_extracted=terms_extracted,
        file_count=file_count,
        parse_failures=parse_failures,
    )


def compute_section_state_hash(result: SectionizationResult) -> str:
    """Compute hash of sectionization state for loop detection.

    Args:
        result: SectionizationResult to hash.

    Returns:
        16-character hex digest.
    """
    content = "|".join(sorted(result.sections_detected))
    return LoopDetector.compute_hash(content)


def eval_sectionization(
    manager: WorkspaceManager,
    ground_truth: PhaseGroundTruth,
    loop_detector: LoopDetector,
    fuzzy_threshold: float = 0.8,
    max_iterations: int = 5,
) -> PhaseMetrics:
    """Evaluate sectionization phase against ground truth.

    Args:
        manager: WorkspaceManager for the run.
        ground_truth: Expected outputs for this phase.
        loop_detector: Loop detector for stagnation detection.
        fuzzy_threshold: Threshold for fuzzy string matching.
        max_iterations: Maximum iterations to attempt.

    Returns:
        PhaseMetrics for the sectionization phase.
    """
    import time

    start_time = time.perf_counter()
    iterations = 0
    converged = False
    trajectory: list[float] = []

    expected_sections = ground_truth.expected_sections

    for iteration in range(1, max_iterations + 1):
        iterations = iteration

        # Extract current outputs
        result = extract_sectionization_outputs(manager)

        # Score against ground truth
        score = score_detail_capture(
            expected_sections,
            result.sections_detected,
            fuzzy_threshold=fuzzy_threshold,
        )

        trajectory.append(score.recall)

        # Check for loop conditions
        state_hash = compute_section_state_hash(result)
        loop_status = loop_detector.update(state_hash)

        if loop_status in {LoopStatus.STAGNANT, LoopStatus.CYCLING, LoopStatus.MAX_ITERATIONS}:
            break

        # Check for convergence
        if score.recall >= 0.95:
            converged = True
            break

    # Final scoring
    final_result = extract_sectionization_outputs(manager)
    final_score = score_detail_capture(
        expected_sections,
        final_result.sections_detected,
        fuzzy_threshold=fuzzy_threshold,
    )

    duration_ms = (time.perf_counter() - start_time) * 1000

    return PhaseMetrics(
        phase_name="sectionization",
        detail_score=final_score,
        iterations=iterations,
        converged=converged,
        duration_ms=duration_ms,
        gaps_open=final_score.expected_count - final_score.matched_count,
        gaps_closed=final_score.matched_count,
        errors=final_result.parse_failures,
    )
