"""Quality gates workflow for multi-dimensional quality review.

Runs completeness, consistency, clarity, and correctness reviews.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from spec_manager.core.agent_utils import run_agent
from spec_manager.refinement.formats import _extract_json_payload, _strip_code_fences
from spec_manager.refinement.progress import ProgressTracker
from spec_manager.refinement.workspace import Phase, PhaseStatus, WorkspaceManager

logger = logging.getLogger(__name__)

QUALITY_DIMENSIONS = ["completeness", "consistency", "clarity", "correctness"]
DIMENSION_WEIGHTS = {
    "completeness": 0.3,
    "consistency": 0.25,
    "clarity": 0.2,
    "correctness": 0.25,
}


def _build_quality_prompt(
    dimension: str,
    spec_content: str,
    lib_id: str,
) -> str:
    """Build prompt for a quality dimension review."""
    dimension_descriptions = {
        "completeness": "Check if all requirements from the charter are covered in the spec.",
        "consistency": "Check if there are contradictions or conflicting statements in the spec.",
        "clarity": "Check if the spec is clear, unambiguous, and well-structured.",
        "correctness": "Check if the spec accurately reflects the intended behavior.",
    }
    description = dimension_descriptions.get(dimension, "")
    lines = [
        f"## TASK: {dimension.upper()} REVIEW",
        "",
        description,
        "",
        "Return JSON with keys: score (0.0-1.0), findings.",
        "",
        '{"score": float, "findings": [{"description": "str", "severity": "high|medium|low"}]}',
        "",
        f"Library ID: {lib_id}",
        "",
        "Spec:",
        spec_content.strip(),
        "",
    ]
    return "\n".join(lines).strip() + "\n"


def parse_quality_gate_output(output: str) -> dict[str, Any]:
    """Parse quality gate agent output."""
    cleaned = _strip_code_fences(output)
    extracted = _extract_json_payload(cleaned)
    data = json.loads(extracted)
    if not isinstance(data, dict):
        raise TypeError("Expected JSON object for quality gate output.")
    return data


def run_quality_gates(run_id: str, threshold: float = 0.8) -> dict[str, Any]:
    """Run multi-dimensional quality review.

    Args:
        run_id: Run identifier.
        threshold: Minimum weighted average score to pass.

    Returns:
        Result payload with quality scores and pass/fail status.
    """
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized.")

    interfaces_status = manager.state.phases[Phase.INTERFACES.value].status
    if interfaces_status != PhaseStatus.COMPLETED:
        raise RuntimeError("Interfaces must be completed before quality gates.")

    manager.start_phase(Phase.QUALITY_GATES)

    libraries_dir = manager.structure.libraries_dir
    lib_dirs = [d for d in sorted(libraries_dir.iterdir()) if d.is_dir()]

    tracker = ProgressTracker(
        total=len(lib_dirs) * len(QUALITY_DIMENSIONS),
        description="Running quality gates",
        manager=manager,
    )

    errors: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    library_scores: dict[str, dict[str, float]] = {}
    libraries_reviewed = 0

    for lib_dir in lib_dirs:
        lib_id = lib_dir.name
        spec_path = lib_dir / "spec.md"

        if not spec_path.exists():
            errors.append({"lib_id": lib_id, "error": "Missing spec.md"})
            for _ in QUALITY_DIMENSIONS:
                tracker.update(status=lib_id)
            continue

        spec_content = spec_path.read_text(encoding="utf-8")
        dimension_scores: dict[str, float] = {}

        for dimension in QUALITY_DIMENSIONS:
            agent_name = f"chatgpt-{dimension}-reviewer"
            prompt = _build_quality_prompt(dimension, spec_content, lib_id)

            try:
                output = run_agent(
                    agent_name=agent_name,
                    prompt=prompt,
                    workspace=manager.workspace_path,
                )
            except RuntimeError as exc:
                errors.append(
                    {
                        "lib_id": lib_id,
                        "dimension": dimension,
                        "error": f"Agent failed: {exc}",
                    }
                )
                dimension_scores[dimension] = 0.0
                tracker.update(status=f"{lib_id}/{dimension}")
                continue

            try:
                data = parse_quality_gate_output(output)
                score = float(data.get("score", 0.0))
                dimension_scores[dimension] = min(max(score, 0.0), 1.0)
            except Exception as exc:
                errors.append(
                    {
                        "lib_id": lib_id,
                        "dimension": dimension,
                        "error": f"Parse failed: {exc}",
                    }
                )
                dimension_scores[dimension] = 0.0

            tracker.update(status=f"{lib_id}/{dimension}")

        library_scores[lib_id] = dimension_scores
        libraries_reviewed += 1

    tracker.finish()

    # Calculate weighted averages
    overall_scores: dict[str, float] = {}
    for lib_id, scores in library_scores.items():
        weighted = sum(scores.get(dim, 0.0) * DIMENSION_WEIGHTS[dim] for dim in QUALITY_DIMENSIONS)
        overall_scores[lib_id] = round(weighted, 4)

    avg_score = sum(overall_scores.values()) / len(overall_scores) if overall_scores else 0.0
    passed = avg_score >= threshold

    # Write quality gates report
    reports_dir = manager.structure.root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    report_lines = [
        "# Quality Gates Report",
        "",
        f"Threshold: {threshold}",
        f"Average Score: {avg_score:.4f}",
        f"Status: {'PASSED' if passed else 'FAILED'}",
        "",
        "## Library Scores",
        "",
    ]
    for lib_id, score in sorted(overall_scores.items()):
        dims = library_scores.get(lib_id, {})
        dim_str = ", ".join(f"{d}: {dims.get(d, 0.0):.2f}" for d in QUALITY_DIMENSIONS)
        report_lines.append(f"- {lib_id}: {score:.4f} ({dim_str})")
    report_lines.append("")

    (reports_dir / "quality_gates.md").write_text("\n".join(report_lines), encoding="utf-8")
    (reports_dir / "quality_gates.json").write_text(
        json.dumps(
            {
                "threshold": threshold,
                "average_score": avg_score,
                "passed": passed,
                "library_scores": library_scores,
                "overall_scores": overall_scores,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    outputs = {
        "libraries_reviewed": libraries_reviewed,
        "average_score": round(avg_score, 4),
        "passed": passed,
        "threshold": threshold,
    }

    phase_result = manager.state.phases[Phase.QUALITY_GATES.value]
    phase_result.issues = errors + issues

    if passed:
        manager.complete_phase(Phase.QUALITY_GATES, outputs=outputs)
    else:
        manager.fail_phase(
            Phase.QUALITY_GATES, error=f"Quality score {avg_score:.4f} below threshold {threshold}"
        )

    return {
        "success": passed,
        "libraries_reviewed": libraries_reviewed,
        "average_score": round(avg_score, 4),
        "passed": passed,
        "library_scores": library_scores,
        "errors": errors,
        "issues": issues,
        "outputs": outputs,
    }
