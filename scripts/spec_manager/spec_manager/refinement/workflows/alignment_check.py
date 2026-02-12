"""Alignment check workflow for verifying specs against original requirements.

Detects requirement drift and reward hacking after spec stabilization.
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

from .spec_building import _extract_sections
from .spec_patches import (
    VALID_SPEC_SECTIONS,
    SpecDocument,
    apply_patch,
    parse_patch_json,
    render_spec,
    validate_patch_operation,
)

logger = logging.getLogger(__name__)


def _build_alignment_prompt(
    lib_id: str,
    spec_content: str,
    original_sections: dict[str, str],
    charter_content: str,
) -> str:
    """Build prompt for alignment checking."""
    lines = [
        "## TASK",
        "",
        "Check the library spec against the original charter and requirements.",
        "Detect any requirement drift (spec diverged from charter intent) or",
        "reward hacking (spec optimizes for metrics rather than actual goals).",
        "",
        "Return JSON with keys: drift_findings, reward_hacking_findings, patches.",
        "",
        "## SCHEMA",
        "",
        '{"drift_findings": [{"element": "str", "description": "str", '
        '"severity": "high|medium|low"}],',
        ' "reward_hacking_findings": [{"element": "str", "description": "str", '
        '"severity": "high|medium|low"}],',
        ' "patches": [{"op": "edit", "section": "str", "bullet_index": int, '
        '"content": "str", "citations": []}]}',
        "",
        f"Library ID: {lib_id}",
        "",
        "Charter:",
        charter_content.strip(),
        "",
        "Current Spec:",
        spec_content.strip(),
        "",
    ]
    return "\n".join(lines).strip() + "\n"


def parse_alignment_check_output(output: str) -> dict[str, Any]:
    """Parse alignment check agent output."""
    cleaned = _strip_code_fences(output)
    extracted = _extract_json_payload(cleaned)
    data = json.loads(extracted)
    if not isinstance(data, dict):
        raise TypeError("Expected JSON object for alignment check output.")
    return data


def _generate_alignment_patches(drift_findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate patches from drift findings."""
    patches: list[dict[str, Any]] = []
    for finding in drift_findings:
        if finding.get("severity") == "high":
            patches.append(
                {
                    "op": "edit",
                    "section": "Details",
                    "bullet_index": None,
                    "content": f"[DRIFT] {finding.get('description', '')}",
                    "citations": [],
                }
            )
    return patches


def check_alignment(run_id: str, max_iterations: int = 3) -> dict[str, Any]:
    """Check specs against original requirements for drift and reward hacking.

    Args:
        run_id: Run identifier.
        max_iterations: Maximum alignment correction iterations.

    Returns:
        Result payload with findings and corrections applied.
    """
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized.")

    stabilization_status = manager.state.phases[Phase.SPEC_STABILIZATION.value].status
    if stabilization_status != PhaseStatus.COMPLETED:
        raise RuntimeError("Spec stabilization must be completed before alignment check.")

    manager.start_phase(Phase.ALIGNMENT_CHECK)

    libraries_dir = manager.structure.libraries_dir
    lib_dirs = [d for d in sorted(libraries_dir.iterdir()) if d.is_dir()]

    tracker = ProgressTracker(
        total=len(lib_dirs),
        description="Checking alignment",
        manager=manager,
    )

    errors: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    total_drift = 0
    total_reward_hacking = 0
    libraries_checked = 0

    for lib_dir in lib_dirs:
        lib_id = lib_dir.name
        spec_path = lib_dir / "spec.md"
        charter_path = lib_dir / "charter.md"

        if not spec_path.exists() or not charter_path.exists():
            errors.append({"lib_id": lib_id, "error": "Missing spec.md or charter.md"})
            tracker.update(status=lib_id)
            continue

        spec_content = spec_path.read_text(encoding="utf-8")
        charter_content = charter_path.read_text(encoding="utf-8")
        original_sections = _extract_sections(spec_content, level=2)

        for _iteration in range(max_iterations):
            prompt = _build_alignment_prompt(
                lib_id, spec_content, original_sections, charter_content
            )

            try:
                output = run_agent(
                    agent_name="opus-alignment-checker",
                    prompt=prompt,
                    workspace=manager.workspace_path,
                )
            except RuntimeError as exc:
                errors.append({"lib_id": lib_id, "error": f"Agent failed: {exc}"})
                break

            try:
                data = parse_alignment_check_output(output)
            except Exception as exc:
                errors.append({"lib_id": lib_id, "error": f"Parse failed: {exc}"})
                break

            drift_findings = data.get("drift_findings", [])
            reward_findings = data.get("reward_hacking_findings", [])
            total_drift += len(drift_findings)
            total_reward_hacking += len(reward_findings)

            patches = data.get("patches", [])
            if not patches and not drift_findings:
                break

            # Apply patches if provided
            if patches:
                try:
                    patch_json = json.dumps(
                        {"operations": patches, "lib_id": lib_id, "file_id": "alignment"}
                    )
                    patch_set = parse_patch_json(patch_json)
                    spec_doc = SpecDocument(spec_content)
                    for op in patch_set.operations:
                        op_errors = validate_patch_operation(op, VALID_SPEC_SECTIONS)
                        if not op_errors:
                            try:
                                apply_patch(spec_doc, op)
                            except Exception:
                                logger.debug("Alignment check parsing failed", exc_info=True)
                    spec_content = render_spec(spec_doc, lib_id)
                    spec_path.write_text(spec_content, encoding="utf-8")
                except Exception as exc:
                    issues.append({"lib_id": lib_id, "type": "patch_failed", "message": str(exc)})

            if not drift_findings:
                break

        libraries_checked += 1
        tracker.update(status=lib_id)

    tracker.finish()

    # Write alignment report
    reports_dir = manager.structure.root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_lines = [
        "# Alignment Check Report",
        "",
        f"Libraries checked: {libraries_checked}",
        f"Drift findings: {total_drift}",
        f"Reward hacking findings: {total_reward_hacking}",
        "",
    ]
    (reports_dir / "alignment_report.md").write_text("\n".join(report_lines), encoding="utf-8")

    outputs = {
        "libraries_checked": libraries_checked,
        "drift_findings": total_drift,
        "reward_hacking_findings": total_reward_hacking,
    }

    phase_result = manager.state.phases[Phase.ALIGNMENT_CHECK.value]
    phase_result.issues = errors + issues
    manager.complete_phase(Phase.ALIGNMENT_CHECK, outputs=outputs)

    return {
        "success": not errors,
        "libraries_checked": libraries_checked,
        "drift_findings": total_drift,
        "reward_hacking_findings": total_reward_hacking,
        "errors": errors,
        "issues": issues,
        "outputs": outputs,
    }
