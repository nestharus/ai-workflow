"""Overview generation workflow for producing human-readable overviews.

Generates a consolidated overview document from all library specs.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from spec_manager.refinement.agent_utils import run_agent
from spec_manager.refinement.progress import ProgressTracker
from spec_manager.refinement.workspace import Phase, PhaseStatus, WorkspaceManager

logger = logging.getLogger(__name__)


def _build_overview_prompt(
    lib_id: str,
    spec_content: str,
    charter_content: str,
) -> str:
    """Build prompt for overview generation."""
    lines = [
        "## TASK",
        "",
        "Generate a human-readable overview document for this library.",
        "The overview should explain what the library does, how its components",
        "fit together, and key design decisions in clear prose.",
        "",
        "Return the overview as markdown (no JSON wrapper).",
        "",
        f"Library ID: {lib_id}",
        "",
        "Charter:",
        charter_content.strip(),
        "",
        "Spec:",
        spec_content.strip(),
        "",
    ]
    return "\n".join(lines).strip() + "\n"


def generate_overview(run_id: str) -> dict[str, Any]:
    """Generate human-readable overview document.

    Args:
        run_id: Run identifier.

    Returns:
        Result payload with generation status.
    """
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized.")

    alignment_status = manager.state.phases[Phase.ALIGNMENT_CHECK.value].status
    if alignment_status != PhaseStatus.COMPLETED:
        raise RuntimeError("Alignment check must be completed before overview generation.")

    manager.start_phase(Phase.OVERVIEW_GENERATION)

    libraries_dir = manager.structure.libraries_dir
    lib_dirs = [d for d in sorted(libraries_dir.iterdir()) if d.is_dir()]

    tracker = ProgressTracker(
        total=len(lib_dirs),
        description="Generating overviews",
        manager=manager,
    )

    errors: list[dict[str, Any]] = []
    libraries_processed = 0
    overview_parts: list[str] = []

    for lib_dir in lib_dirs:
        lib_id = lib_dir.name
        spec_path = lib_dir / "spec.md"
        charter_path = lib_dir / "charter.md"

        if not spec_path.exists():
            errors.append({"lib_id": lib_id, "error": "Missing spec.md"})
            tracker.update(status=lib_id)
            continue

        spec_content = spec_path.read_text(encoding="utf-8")
        charter_content = charter_path.read_text(encoding="utf-8") if charter_path.exists() else ""

        prompt = _build_overview_prompt(lib_id, spec_content, charter_content)

        try:
            output = run_agent(
                agent_name="opus-overview-writer",
                prompt=prompt,
                workspace=manager.workspace_path,
            )
        except RuntimeError as exc:
            errors.append({"lib_id": lib_id, "error": f"Agent failed: {exc}"})
            tracker.update(status=lib_id)
            continue

        overview_parts.append(f"## {lib_id}\n\n{output.strip()}\n")
        libraries_processed += 1
        tracker.update(status=lib_id)

    tracker.finish()

    # Write consolidated overview
    reports_dir = manager.structure.root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    overview_content = "# Project Overview\n\n" + "\n---\n\n".join(overview_parts)
    (reports_dir / "overview.md").write_text(overview_content, encoding="utf-8")

    outputs = {
        "libraries_processed": libraries_processed,
        "overview_path": "reports/overview.md",
    }

    phase_result = manager.state.phases[Phase.OVERVIEW_GENERATION.value]
    phase_result.issues = errors
    manager.complete_phase(Phase.OVERVIEW_GENERATION, outputs=outputs)

    return {
        "success": not errors,
        "libraries_processed": libraries_processed,
        "errors": errors,
        "outputs": outputs,
    }
