"""Branch lifecycle workflow for spec refinement.

Provides four phase functions that wire the branches/ module
into the refinement workflow:

- run_branch_init: Initialize branch layout + collapse codebase
- run_branch_gaps: Scan algorithmic branch for gaps
- run_branch_promote: Compliance gate + promote to architectural
- run_branch_analyze: Regenerate analysis branch
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from spec_manager.refinement.workspace.state import Phase, PhaseStatus

logger = logging.getLogger(__name__)


def _get_manager(run_id: str) -> Any:
    """Instantiate a WorkspaceManager for the given run_id.

    Uses a late import to avoid circular dependencies.
    """
    from spec_manager.refinement.workspace import WorkspaceManager

    return WorkspaceManager(run_id=run_id, input_folder=Path("."))


def run_branch_init(
    run_id: str,
    source_dir: Path | None = None,
) -> dict[str, Any]:
    """Initialize branch layout and optionally collapse a codebase.

    Args:
        run_id: The run identifier.
        source_dir: If provided, collapse this directory into Layer 1.

    Returns:
        Dict with ``success`` flag and ``outputs`` dict.
    """
    manager = _get_manager(run_id)
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized. Run init before branch operations.")

    manager.start_phase(Phase.BRANCH_INIT)

    try:
        # Initialize branch directory structure
        issues = manager.branches.initialize()
        if issues:
            logger.warning("Branch init issues: %s", issues)

        outputs: dict[str, Any] = {
            "branch_initialized": True,
            "init_issues": issues,
            "atom_count": 0,
            "atom_count_by_kind": {},
            "collapse_warnings": [],
        }

        # Collapse codebase if source_dir provided
        if source_dir is not None and source_dir.exists():
            collapse_result = manager.branches.collapse_codebase(source_dir)

            # Register all extracted atoms
            all_atoms = (
                collapse_result.extracted_atoms
                + collapse_result.extracted_stores
                + collapse_result.extracted_shapes
            )
            for atom in all_atoms:
                manager.branches.register_atom(atom)

            outputs["atom_count"] = len(all_atoms)
            outputs["atom_count_by_kind"] = {
                "algorithm": len(collapse_result.extracted_atoms),
                "store": len(collapse_result.extracted_stores),
                "shape": len(collapse_result.extracted_shapes),
            }
            outputs["architectural_remnants"] = len(collapse_result.architectural_remnants)
            outputs["collapse_warnings"] = collapse_result.warnings

        # Persist registries
        manager.branches.save()

        manager.complete_phase(Phase.BRANCH_INIT, outputs=outputs)
        return {"success": True, "outputs": outputs}

    except Exception as exc:
        manager.fail_phase(Phase.BRANCH_INIT, error=str(exc))
        return {"success": False, "error": str(exc)}


def run_branch_gaps(run_id: str) -> dict[str, Any]:
    """Scan the algorithmic branch for gaps.

    Args:
        run_id: The run identifier.

    Returns:
        Dict with ``success`` flag and ``outputs`` dict.
    """
    from spec_manager.branches.gap_detection import GapDetector

    manager = _get_manager(run_id)
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized.")

    # Check prerequisite: BRANCH_INIT completed
    init_status = manager.state.phases[Phase.BRANCH_INIT.value].status
    if init_status != PhaseStatus.COMPLETED:
        raise RuntimeError("BRANCH_INIT must be completed before running BRANCH_GAPS.")

    manager.start_phase(Phase.BRANCH_GAPS)

    try:
        detector = GapDetector()
        algorithmic_dir = manager.branches.layout.algorithmic_dir()
        gap_items = detector.scan_branch(algorithmic_dir)

        # Write gap report to analysis directory
        analysis_dir = manager.branches.layout.analysis_dir()
        analysis_dir.mkdir(parents=True, exist_ok=True)
        gap_report_path = analysis_dir / "gap_report.json"
        gap_report_path.write_text(
            json.dumps([g.to_dict() for g in gap_items], indent=2),
            encoding="utf-8",
        )

        # Summarize by type
        gaps_by_type: dict[str, int] = {}
        for gap in gap_items:
            gaps_by_type[gap.gap_type] = gaps_by_type.get(gap.gap_type, 0) + 1

        outputs: dict[str, Any] = {
            "total_gaps": len(gap_items),
            "gaps_by_type": gaps_by_type,
            "gap_report_path": str(gap_report_path),
        }

        manager.complete_phase(Phase.BRANCH_GAPS, outputs=outputs)
        return {"success": True, "outputs": outputs}

    except Exception as exc:
        manager.fail_phase(Phase.BRANCH_GAPS, error=str(exc))
        return {"success": False, "error": str(exc)}


def run_branch_promote(
    run_id: str,
    skip_compliance: bool = False,
    atom_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Run compliance gate and promote atoms to architectural branch.

    Args:
        run_id: The run identifier.
        skip_compliance: Skip compliance gate.
        atom_ids: Specific atoms to promote (None = all changed).

    Returns:
        Dict with ``success`` flag and ``outputs`` dict.
    """
    manager = _get_manager(run_id)
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized.")

    # Check prerequisite: BRANCH_INIT completed
    init_status = manager.state.phases[Phase.BRANCH_INIT.value].status
    if init_status != PhaseStatus.COMPLETED:
        raise RuntimeError("BRANCH_INIT must be completed before running BRANCH_PROMOTE.")

    manager.start_phase(Phase.BRANCH_PROMOTE)

    try:
        result = manager.branches.promote(
            atom_ids=atom_ids,
            skip_compliance=skip_compliance,
        )

        # Persist pin registry updates
        manager.branches.save()

        outputs: dict[str, Any] = {
            "promoted_count": len(result.promoted_atoms),
            "skipped_count": len(result.skipped_atoms),
            "compliance_passed": result.compliance_result.passed
            if result.compliance_result
            else None,
            "new_pin_ids": result.pin_ids_created,
            "skip_compliance": skip_compliance,
        }

        manager.complete_phase(Phase.BRANCH_PROMOTE, outputs=outputs)
        return {"success": True, "outputs": outputs}

    except Exception as exc:
        manager.fail_phase(Phase.BRANCH_PROMOTE, error=str(exc))
        return {"success": False, "error": str(exc)}


def run_branch_analyze(run_id: str) -> dict[str, Any]:
    """Regenerate the analysis branch from current state.

    Args:
        run_id: The run identifier.

    Returns:
        Dict with ``success`` flag and ``outputs`` dict.
    """
    manager = _get_manager(run_id)
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized.")

    # Check prerequisite: BRANCH_INIT completed
    init_status = manager.state.phases[Phase.BRANCH_INIT.value].status
    if init_status != PhaseStatus.COMPLETED:
        raise RuntimeError("BRANCH_INIT must be completed before running BRANCH_ANALYZE.")

    manager.start_phase(Phase.BRANCH_ANALYZE)

    try:
        report = manager.branches.regenerate_analysis()

        analysis_dir = manager.branches.layout.analysis_dir()
        outputs: dict[str, Any] = {
            "atom_count": len(report.atoms),
            "orphaned_count": len(report.orphaned_architectural),
            "subgraph_count": len(report.disconnected_subgraphs),
            "artifact_paths": {
                "lineage_table": str(analysis_dir / "lineage_table.json"),
                "adjacency_graph": str(analysis_dir / "adjacency_graph.json"),
                "drift_report": str(analysis_dir / "drift_report.md"),
            },
        }

        manager.complete_phase(Phase.BRANCH_ANALYZE, outputs=outputs)
        return {"success": True, "outputs": outputs}

    except Exception as exc:
        manager.fail_phase(Phase.BRANCH_ANALYZE, error=str(exc))
        return {"success": False, "error": str(exc)}


def run_branch_init_from_edit_in_place(
    run_id: str,
    source_dir: Path,
) -> dict[str, Any]:
    """Initialize branches using edit-in-place analysis output.

    Calls ``run_branch_init`` for collapse, then cross-references
    collapsed atoms with TrackedUnits from the edit-in-place bridge
    and writes a lineage mapping to the analysis directory.

    Args:
        run_id: The run identifier.
        source_dir: Root directory of the source codebase.

    Returns:
        Dict with ``success`` flag and ``outputs`` dict.
    """
    from spec_manager.core.edit_in_place import analyze_project
    from spec_manager.core.edit_in_place_bridge import (
        function_info_to_tracked_unit,
        project_state_to_gap_queue,
    )

    # Run branch init with collapse
    init_result = run_branch_init(run_id, source_dir=source_dir)
    if not init_result.get("success"):
        return init_result

    manager = _get_manager(run_id)

    try:
        # Analyze source for edit-in-place data
        project_state = analyze_project(str(source_dir))

        # Convert functions to TrackedUnits and build lineage mapping
        lineage: dict[str, str] = {}
        all_atoms = manager.branches.list_atoms()

        for file_state in project_state.files.values():
            for func in file_state.functions:
                tracked = function_info_to_tracked_unit(func)
                # Cross-reference by qualified name
                for atom in all_atoms:
                    if atom.function_name == func.qualified_name or (
                        atom.atom_id.endswith(f":{func.qualified_name}")
                    ):
                        lineage[atom.atom_id] = tracked.id
                        break

        # Write lineage mapping
        analysis_dir = manager.branches.layout.analysis_dir()
        analysis_dir.mkdir(parents=True, exist_ok=True)
        lineage_path = analysis_dir / "eip_lineage.json"
        lineage_path.write_text(json.dumps(lineage, indent=2), encoding="utf-8")

        # Get gap queue from edit-in-place
        gap_queue = project_state_to_gap_queue(project_state)

        combined_outputs = dict(init_result.get("outputs", {}))
        combined_outputs["eip_lineage_path"] = str(lineage_path)
        combined_outputs["eip_lineage_count"] = len(lineage)
        combined_outputs["eip_gap_count"] = len(gap_queue.gaps)

        return {"success": True, "outputs": combined_outputs}

    except Exception as exc:
        logger.exception("Edit-in-place integration failed")
        return {"success": False, "error": str(exc)}
