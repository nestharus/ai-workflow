"""QA evaluation workflow for running quality assurance checks.

Evaluates specs against the approved overview for completeness and correctness.
"""

from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path
from typing import Any

from spec_manager.core.agent_utils import run_agent
from spec_manager.refinement.formats import _extract_json_payload, _strip_code_fences
from spec_manager.refinement.progress import ProgressTracker
from spec_manager.refinement.workspace import Phase, PhaseStatus, WorkspaceManager

logger = logging.getLogger(__name__)


def _build_qa_prompt(
    spec_content: str,
    overview_content: str,
    lib_id: str,
) -> str:
    """Build prompt for QA evaluation."""
    lines = [
        "## TASK",
        "",
        "Evaluate the library spec against the approved overview.",
        "Identify any QA failures: missing requirements, inconsistencies,",
        "or gaps between the overview and the spec.",
        "",
        "Return JSON with keys: findings, total_findings.",
        "",
        "## SCHEMA",
        "",
        '{"findings": [{"type": "missing|inconsistent|incomplete", "description": "str",',
        ' "severity": "high|medium|low", "location": "str"}], "total_findings": int}',
        "",
        f"Library ID: {lib_id}",
        "",
        "Approved Overview:",
        overview_content.strip(),
        "",
        "Current Spec:",
        spec_content.strip(),
        "",
    ]
    return "\n".join(lines).strip() + "\n"


def _build_root_cause_prompt(findings: list[dict[str, Any]], lib_id: str) -> str:
    """Build prompt for root cause analysis of QA findings."""
    findings_text = json.dumps(findings, indent=2)
    lines = [
        "## TASK",
        "",
        "Analyze the root causes of these QA findings.",
        "For each finding, determine what went wrong and suggest a fix.",
        "",
        "Return JSON with keys: analyses.",
        "",
        '{"analyses": [{"finding_index": int, "root_cause": "str", "suggested_fix": "str"}]}',
        "",
        f"Library ID: {lib_id}",
        "",
        "Findings:",
        findings_text,
        "",
    ]
    return "\n".join(lines).strip() + "\n"


def parse_qa_evaluation_output(output: str) -> dict[str, Any]:
    """Parse QA evaluation agent output."""
    cleaned = _strip_code_fences(output)
    extracted = _extract_json_payload(cleaned)
    data = json.loads(extracted)
    if not isinstance(data, dict):
        raise TypeError("Expected JSON object for QA evaluation output.")
    return data


def evaluate_qa(run_id: str, max_iterations: int = 3) -> dict[str, Any]:
    """Run QA evaluation against approved overview.

    Args:
        run_id: Run identifier.
        max_iterations: Maximum QA evaluation iterations.

    Returns:
        Result payload with QA findings.
    """
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized.")

    overview_status = manager.state.phases[Phase.OVERVIEW_GENERATION.value].status
    if overview_status != PhaseStatus.COMPLETED:
        raise RuntimeError("Overview generation must be completed before QA evaluation.")

    # Check for overview approval marker
    reports_dir = manager.structure.root / "reports"
    marker_path = reports_dir / "overview_approved.marker"
    if not marker_path.exists():
        raise RuntimeError(
            "Overview must be approved before QA evaluation. Run 'approve-overview' first."
        )

    manager.start_phase(Phase.QA_EVALUATION)

    overview_path = reports_dir / "overview.md"
    overview_content = overview_path.read_text(encoding="utf-8") if overview_path.exists() else ""

    libraries_dir = manager.structure.libraries_dir
    lib_dirs = [d for d in sorted(libraries_dir.iterdir()) if d.is_dir()]

    tracker = ProgressTracker(
        total=len(lib_dirs),
        description="Running QA evaluation",
        manager=manager,
    )

    errors: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    total_findings = 0
    libraries_evaluated = 0

    for lib_dir in lib_dirs:
        lib_id = lib_dir.name
        spec_path = lib_dir / "spec.md"

        if not spec_path.exists():
            errors.append({"lib_id": lib_id, "error": "Missing spec.md"})
            tracker.update(status=lib_id)
            continue

        spec_content = spec_path.read_text(encoding="utf-8")

        for iteration in range(max_iterations):
            prompt = _build_qa_prompt(spec_content, overview_content, lib_id)

            try:
                output = run_agent(
                    agent_name="chatgpt-qa-evaluator",
                    prompt=prompt,
                    workspace=manager.workspace_path,
                )
            except RuntimeError as exc:
                errors.append({"lib_id": lib_id, "error": f"QA agent failed: {exc}"})
                break

            try:
                data = parse_qa_evaluation_output(output)
            except Exception as exc:
                errors.append({"lib_id": lib_id, "error": f"Parse failed: {exc}"})
                break

            findings = data.get("findings", [])
            total_findings += len(findings)

            if not findings:
                break

            # Run root cause analysis on high-severity findings
            high_severity = [f for f in findings if f.get("severity") == "high"]
            if high_severity:
                rca_prompt = _build_root_cause_prompt(high_severity, lib_id)
                with contextlib.suppress(RuntimeError):
                    run_agent(
                        agent_name="chatgpt-root-cause-analyzer",
                        prompt=rca_prompt,
                        workspace=manager.workspace_path,
                    )  # Root cause analysis is best-effort

            if iteration + 1 >= max_iterations:
                break

        libraries_evaluated += 1
        tracker.update(status=lib_id)

    tracker.finish()

    # Write QA report
    report_lines = [
        "# QA Evaluation Report",
        "",
        f"Libraries evaluated: {libraries_evaluated}",
        f"Total findings: {total_findings}",
        "",
    ]
    (reports_dir / "qa_evaluation.md").write_text("\n".join(report_lines), encoding="utf-8")

    outputs = {
        "libraries_evaluated": libraries_evaluated,
        "total_findings": total_findings,
    }

    phase_result = manager.state.phases[Phase.QA_EVALUATION.value]
    phase_result.issues = errors + issues
    manager.complete_phase(Phase.QA_EVALUATION, outputs=outputs)

    return {
        "success": not errors,
        "libraries_evaluated": libraries_evaluated,
        "total_findings": total_findings,
        "errors": errors,
        "issues": issues,
        "outputs": outputs,
    }
