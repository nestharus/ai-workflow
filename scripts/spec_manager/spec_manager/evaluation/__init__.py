"""Evaluation and quality assessment system."""

from __future__ import annotations

from spec_manager.evaluation.comparison import ComparisonRunner
from spec_manager.evaluation.cost_ledger import CostLedger, LLMCallRecord
from spec_manager.evaluation.digests import build_architecture_digest, build_code_digest
from spec_manager.evaluation.model_profile import ModelProfile
from spec_manager.evaluation.multi_model import MultiModelRunner
from spec_manager.evaluation.quality import QualityReporter, QualityScorecard
from spec_manager.evaluation.report import FinalReportGenerator
from spec_manager.evaluation.scoring import RunReporter, Scorecard
from spec_manager.evaluation.snapshot import snapshot_run

__all__ = [
    "ComparisonRunner",
    "CostLedger",
    "FinalReportGenerator",
    "LLMCallRecord",
    "ModelProfile",
    "MultiModelRunner",
    "QualityReporter",
    "QualityScorecard",
    "RunReporter",
    "Scorecard",
    "build_architecture_digest",
    "build_code_digest",
    "snapshot_run",
]
