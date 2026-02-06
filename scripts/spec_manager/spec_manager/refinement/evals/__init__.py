"""Deterministic evaluation framework for spec refinement.

This module provides:
- Sequence spec fixtures with verifiable ground truth
- Metrics for detail capture (precision/recall), convergence, and loop detection
- Evaluation runner with checkpoint/resume support
- Per-phase evaluators for each refinement phase
"""

from spec_manager.refinement.evals.checkpoint import (
    CheckpointManager,
    EvalCheckpoint,
    PhaseCheckpoint,
)
from spec_manager.refinement.evals.inputs.ground_truth import GroundTruth, PhaseGroundTruth
from spec_manager.refinement.evals.inputs.sequence_spec import (
    SequenceRule,
    SequenceSpec,
    load_sequence_spec,
)
from spec_manager.refinement.evals.logger import EvalLogger, EvalLogEntry
from spec_manager.refinement.evals.loop_detector import LoopDetector, LoopStatus
from spec_manager.refinement.evals.metrics import (
    ConvergenceAnalysis,
    DetailCaptureMetrics,
    DetailScore,
    PhaseMetrics,
    analyze_convergence,
    score_detail_capture,
)
from spec_manager.refinement.evals.report import (
    EvalReport,
    EvalResult,
    generate_markdown_report,
    load_report,
    save_report,
)
from spec_manager.refinement.evals.runner import EvalConfig, EvalRunner, EvalState
from spec_manager.refinement.evals.workflow_integration import (
    WorkspaceIntegration,
    run_real_phase_evaluation,
)

__all__ = [
    "CheckpointManager",
    "ConvergenceAnalysis",
    "DetailCaptureMetrics",
    "DetailScore",
    "EvalCheckpoint",
    "EvalConfig",
    "EvalLogEntry",
    "EvalLogger",
    "EvalReport",
    "EvalResult",
    "EvalRunner",
    "EvalState",
    "GroundTruth",
    "LoopDetector",
    "LoopStatus",
    "PhaseCheckpoint",
    "PhaseGroundTruth",
    "PhaseMetrics",
    "SequenceRule",
    "SequenceSpec",
    "WorkspaceIntegration",
    "analyze_convergence",
    "generate_markdown_report",
    "load_report",
    "load_sequence_spec",
    "run_real_phase_evaluation",
    "save_report",
    "score_detail_capture",
]
