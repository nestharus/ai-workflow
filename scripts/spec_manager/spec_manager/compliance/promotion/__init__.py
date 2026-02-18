"""Compliance gating for layer promotion.

This sub-package implements quality gates that must pass before promoting
code from the algorithmic branch to the architectural branch.

Public API:
    LayerPromotionGate: Orchestrator for all promotion gate checks
    PromotionGateConfig: Full configuration for layer promotion gating
    PromotionReport: Aggregate report from all promotion gate checks
    GateCheckResult: Result of a single gate check
    GateId: Identifiers for each promotion gate check
    GateMode: How a gate failure is treated
    GateSpec: Configuration for a single gate check
    StrategyRegistry: Injectable registry for call-graph strategies
    CallGraphBuildResult: Aggregated call graph extraction results
    CallGraphEdge: One extracted call edge with provenance
"""

from spec_manager.compliance.promotion.call_graph import (
    CallGraphBuildResult,
    CallGraphEdge,
    StrategyRegistry,
)
from spec_manager.compliance.promotion.config import (
    GateId,
    GateMode,
    GateSpec,
    PromotionGateConfig,
)
from spec_manager.compliance.promotion.orchestrator import LayerPromotionGate
from spec_manager.compliance.promotion.result import (
    GateCheckResult,
    PromotionReport,
)

__all__ = [
    "CallGraphBuildResult",
    "CallGraphEdge",
    "GateCheckResult",
    "GateId",
    "GateMode",
    "GateSpec",
    "LayerPromotionGate",
    "PromotionGateConfig",
    "PromotionReport",
    "StrategyRegistry",
]
