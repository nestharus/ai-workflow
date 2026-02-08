"""Library synthesis phase evaluator.

Evaluates the library synthesis phase by comparing synthesized libraries
against ground truth expectations.
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
class SynthesisResult:
    """Result of library synthesis extraction.

    Attributes:
        libraries_synthesized: List of synthesized library names.
        functions_defined: Number of functions defined.
        types_defined: Number of types defined.
        dependencies_resolved: Number of dependencies resolved.
        file_count: Number of files processed.
    """

    libraries_synthesized: list[str]
    functions_defined: int = 0
    types_defined: int = 0
    dependencies_resolved: int = 0
    file_count: int = 0


def extract_synthesis_outputs(manager: WorkspaceManager) -> SynthesisResult:
    """Extract library synthesis outputs from workspace.

    Args:
        manager: WorkspaceManager for the run.

    Returns:
        SynthesisResult with synthesized libraries and counts.
    """
    libraries_dir = manager.structure.manifest_dir / "libraries"

    libraries_synthesized: set[str] = set()
    functions_defined = 0
    types_defined = 0
    dependencies_resolved = 0
    file_count = 0

    # Read libraries from manifest
    if libraries_dir.exists():
        for lib_file in libraries_dir.glob("*.library.json"):
            file_count += 1
            try:
                data = json.loads(lib_file.read_text(encoding="utf-8"))

                # Extract library name
                lib_name = data.get("library_name") or data.get("name")
                if lib_name:
                    libraries_synthesized.add(lib_name)

                # Count functions
                functions = data.get("functions", [])
                functions_defined += len(functions)

                # Count types
                types = data.get("types", [])
                types_defined += len(types)

                # Count resolved dependencies
                deps = data.get("dependencies", [])
                dependencies_resolved += sum(
                    1 for d in deps if isinstance(d, dict) and d.get("resolved", False)
                )

            except (json.JSONDecodeError, OSError):
                continue

    # Also check for synthesis output files
    synthesis_dir = manager.structure.manifest_dir / "synthesis"
    if synthesis_dir.exists():
        for synth_file in synthesis_dir.glob("*.synthesis.json"):
            file_count += 1
            try:
                data = json.loads(synth_file.read_text(encoding="utf-8"))

                for lib in data.get("libraries", []):
                    lib_name = lib.get("name") or lib.get("library_name")
                    if lib_name:
                        libraries_synthesized.add(lib_name)

            except (json.JSONDecodeError, OSError):
                continue

    return SynthesisResult(
        libraries_synthesized=sorted(libraries_synthesized),
        functions_defined=functions_defined,
        types_defined=types_defined,
        dependencies_resolved=dependencies_resolved,
        file_count=file_count,
    )


def compute_synthesis_state_hash(result: SynthesisResult) -> str:
    """Compute hash of synthesis state for loop detection.

    Args:
        result: SynthesisResult to hash.

    Returns:
        16-character hex digest.
    """
    content = "|".join(
        [
            ",".join(sorted(result.libraries_synthesized)),
            str(result.functions_defined),
            str(result.types_defined),
        ]
    )
    return LoopDetector.compute_hash(content)


def eval_library_synthesis(
    manager: WorkspaceManager,
    ground_truth: PhaseGroundTruth,
    loop_detector: LoopDetector,
    fuzzy_threshold: float = 0.8,
    max_iterations: int = 5,
) -> PhaseMetrics:
    """Evaluate library synthesis phase against ground truth.

    Args:
        manager: WorkspaceManager for the run.
        ground_truth: Expected outputs for this phase.
        loop_detector: Loop detector for stagnation detection.
        fuzzy_threshold: Threshold for fuzzy string matching.
        max_iterations: Maximum iterations to attempt.

    Returns:
        PhaseMetrics for the library synthesis phase.
    """
    start_time = time.perf_counter()
    iterations = 0
    converged = False
    trajectory: list[float] = []

    expected_libraries = ground_truth.expected_libraries

    for iteration in range(1, max_iterations + 1):
        iterations = iteration

        # Extract current outputs
        result = extract_synthesis_outputs(manager)

        # Score against ground truth
        score = score_detail_capture(
            expected_libraries,
            result.libraries_synthesized,
            fuzzy_threshold=fuzzy_threshold,
        )

        trajectory.append(score.recall)

        # Check for loop conditions
        state_hash = compute_synthesis_state_hash(result)
        loop_status = loop_detector.update(state_hash)

        if loop_status in {LoopStatus.STAGNANT, LoopStatus.CYCLING, LoopStatus.MAX_ITERATIONS}:
            break

        # Check for convergence
        if score.recall >= 0.95:
            converged = True
            break

    # Final scoring
    final_result = extract_synthesis_outputs(manager)
    final_score = score_detail_capture(
        expected_libraries,
        final_result.libraries_synthesized,
        fuzzy_threshold=fuzzy_threshold,
    )

    duration_ms = (time.perf_counter() - start_time) * 1000

    return PhaseMetrics(
        phase_name="library_synthesis",
        detail_score=final_score,
        iterations=iterations,
        converged=converged,
        duration_ms=duration_ms,
        gaps_open=final_score.expected_count - final_score.matched_count,
        gaps_closed=final_score.matched_count,
    )
