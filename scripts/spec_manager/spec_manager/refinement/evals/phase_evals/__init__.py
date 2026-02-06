"""Per-phase evaluators for spec refinement.

Each evaluator:
1. Extracts actual outputs from workspace
2. Compares against ground truth using fuzzy matching
3. Computes precision/recall/F1
4. Tracks convergence trajectory
"""

from spec_manager.refinement.evals.phase_evals.alignment_check import eval_alignment_check
from spec_manager.refinement.evals.phase_evals.overview_generation import eval_overview_generation
from spec_manager.refinement.evals.phase_evals.qa_evaluation import eval_qa_evaluation
from spec_manager.refinement.evals.phase_evals.quality_gates import eval_quality_gates
from spec_manager.refinement.evals.phase_evals.sectionization import eval_sectionization
from spec_manager.refinement.evals.phase_evals.spec_building import eval_spec_building
from spec_manager.refinement.evals.phase_evals.summarization import eval_summarization
from spec_manager.refinement.evals.phase_evals.synthesis import eval_library_synthesis
from spec_manager.refinement.evals.phase_evals.tasks import eval_tasks

__all__ = [
    "eval_alignment_check",
    "eval_library_synthesis",
    "eval_overview_generation",
    "eval_qa_evaluation",
    "eval_quality_gates",
    "eval_sectionization",
    "eval_spec_building",
    "eval_summarization",
    "eval_tasks",
]
