"""
Workflow module - orchestrates the full ingest workflow.

This module provides:
- WorkflowOrchestrator: Main coordinator with phase methods
- WorkflowConfig: Configuration for compliance gates and limits
- WorkflowState: Workflow state tracking
- WorkflowPhase: Enum for workflow phases
- PatchDependencyGraph: Tracks patch dependencies
- ContextIndex: Entity resolution across strata
- TrackedUnit: Content units with provenance tracking
- ingest: Entry point function for the workflow
"""

from spec_manager.workflow.config import (
    TrackedUnit,
    UnitLabels,
    UnitStatus,
    UnitType,
    WorkflowConfig,
    WorkflowPhase,
    WorkflowState,
)
from spec_manager.workflow.context import (
    ContextIndex,
    PatchDependency,
    PatchDependencyGraph,
)
from spec_manager.workflow.orchestrator import (
    IntermediateManager,
    ProvenanceTracker,
    Severity,
    WorkflowEvidence,
    WorkflowOrchestrator,
)


def ingest(
    spec_folder: str,
    max_cleaning_passes: int = 10,
    max_discovery_iterations: int = 10,
    save_intermediates: bool = True,
    verbose: bool = False,
    compliance_threshold: float = 0.90,
    compliance_gate_mode: str = "block",
) -> dict:
    """
    Run the full ingest workflow on a spec folder.

    Args:
        spec_folder: Path to spec folder containing patches/
        max_cleaning_passes: Max iterations for cleaning phase
        max_discovery_iterations: Max iterations for library discovery
        save_intermediates: Whether to save intermediate states
        verbose: Enable verbose logging
        compliance_threshold: Format compliance score threshold (0-1)
        compliance_gate_mode: "block" or "warn" for compliance gate

    Returns:
        Dict with workflow results
    """
    from pathlib import Path

    config = WorkflowConfig(
        max_cleaning_passes=max_cleaning_passes,
        max_discovery_iterations=max_discovery_iterations,
        save_intermediates=save_intermediates,
        verbose=verbose,
        compliance_threshold=compliance_threshold,
        compliance_gate_mode=compliance_gate_mode,
    )

    orchestrator = WorkflowOrchestrator(
        spec_folder=Path(spec_folder),
        config=config
    )

    state = orchestrator.run()

    return {
        'phase': state.phase.value,
        'cleaning_passes': state.cleaning_pass,
        'discovery_iterations': state.discovery_iteration,
        'total_units': len(state.units),
        'libraries': list(state.library_shapes.keys()),
        'compliance_score': state.compliance_score,
        'compliance_passed': state.compliance_passed,
        'errors': state.errors
    }


__all__ = [
    # Configuration
    "WorkflowConfig",
    "WorkflowPhase",
    "WorkflowState",
    # Units
    "TrackedUnit",
    "UnitLabels",
    "UnitStatus",
    "UnitType",
    # Context
    "ContextIndex",
    "PatchDependency",
    "PatchDependencyGraph",
    # Orchestration
    "WorkflowEvidence",
    "IntermediateManager",
    "ProvenanceTracker",
    "Severity",
    "WorkflowOrchestrator",
    # Entry point
    "ingest",
]
