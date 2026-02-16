"""Finalize workflow for Phase 11 reporting and traceability."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from spec_manager.refinement.workflows.reports import (
    generate_compliance_report,
    generate_coverage_report,
    generate_drift_report,
    generate_run_audit,
)
from spec_manager.refinement.workflows.trace_indexes import (
    build_trace_indexes,
    validate_trace_indexes,
)
from spec_manager.refinement.workspace.manager import WorkspaceManager
from spec_manager.refinement.workspace.state import Phase, PhaseStatus

logger = logging.getLogger(__name__)


def finalize_run(run_id: str) -> dict[str, Any]:
    """Finalize run by building trace indexes and generating reports."""
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    try:
        if not manager.is_initialized:
            raise RuntimeError("Workspace not initialized. Run init before finalization.")

        implementation_status = manager.state.phases[Phase.IMPLEMENTATION.value].status
        if implementation_status != PhaseStatus.COMPLETED:
            status_label = (
                implementation_status.value
                if hasattr(implementation_status, "value")
                else str(implementation_status)
            )
            logger.warning(
                "Implementation phase status is %s; finalize-run is recommended after completion.",
                status_label,
            )

        manifest_files_path = manager.structure.files_json
        manifest_sections_path = manager.structure.sections_json
        if not manifest_files_path.exists() or not manifest_sections_path.exists():
            raise RuntimeError("Manifest files missing. Run Phase 1 sectionization first.")

        libraries_dir = manager.structure.libraries_dir
        if not libraries_dir.exists():
            raise RuntimeError("No libraries found. Run Phase 2-6 to create libraries.")

        libraries = [lib_dir for lib_dir in libraries_dir.iterdir() if lib_dir.is_dir()]
        if not libraries:
            raise RuntimeError("No libraries found. Run Phase 2-6 to create libraries.")

        spec_index_paths = [lib_dir / "spec_index.json" for lib_dir in libraries]
        if not any(path.exists() for path in spec_index_paths):
            raise RuntimeError("No stabilized specs found. Run Phase 6 stabilization first.")

        tasks_dir = manager.structure.tasks_dir
        if not tasks_dir.exists():
            logger.warning("Tasks directory missing: %s", tasks_dir)
        else:
            task_index_path = tasks_dir / "task_index.json"
            if not task_index_path.exists():
                logger.warning("Task index missing: %s", task_index_path)

        edge_list_path = manager.structure.indexes_dir / "edge_list.json"
        interface_index_path = manager.structure.indexes_dir / "interface_index.json"
        if not edge_list_path.exists():
            logger.warning("Interface edge list missing: %s", edge_list_path)
        if not interface_index_path.exists():
            logger.warning("Interface index missing: %s", interface_index_path)

        manager.start_phase(Phase.AUDIT)

        trace_stats = build_trace_indexes(run_id)
        logger.info(
            "Trace indexes built (atoms=%d, sections=%d, elements=%d, tasks=%d).",
            trace_stats.get("atoms", 0),
            trace_stats.get("sections", 0),
            trace_stats.get("elements", 0),
            trace_stats.get("tasks", 0),
        )

        validation_errors = validate_trace_indexes(manager)
        if validation_errors:
            logger.warning("Trace index validation found %d issue(s).", len(validation_errors))
            for error in validation_errors:
                logger.warning("Trace index validation: %s", error)
            raise RuntimeError(
                "Trace index validation failed; finalization blocked. "
                f"Issues: {'; '.join(validation_errors)}"
            )

        generate_coverage_report(manager)
        generate_compliance_report(manager, run_qa=True)
        generate_drift_report(manager)
        generate_run_audit(manager)

        outputs = {
            "trace_index_path": "workspace/indexes/trace_index.json",
            "trace_stats": trace_stats,
            "validation_errors": validation_errors,
            "reports": {
                "coverage": "reports/coverage.md",
                "compliance": "reports/compliance.md",
                "drift": "reports/drift.md",
                "run_audit": "audits/run_audit.md",
            },
        }

        logger.debug("Finalize outputs: %s", json.dumps(outputs, indent=2))

        manager.complete_phase(Phase.AUDIT, outputs=outputs)

        return {
            "success": True,
            "trace_stats": trace_stats,
            "validation_errors": validation_errors,
            "reports_generated": 4,
        }
    except Exception as exc:
        if manager.is_initialized:
            manager.fail_phase(Phase.AUDIT, error=str(exc))
        logger.exception("Finalize run failed.")
        raise RuntimeError(f"Finalize run failed: {exc}") from exc


__all__ = ["finalize_run"]
