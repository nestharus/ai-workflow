# TODO(single-layer): RESTRUCTURE — Public API renames: LayerPromotionGate →
#   AspectPromotionGate (or just PromotionGate). GateId loses PIN_* entries, gains
#   SHAPE_* entries. "Layer promotion" → "phase gate" in docstrings. PromotionReport
#   and GateCheckResult structures are layer-independent and KEEP.
# ALGORITHM(single-layer):
#   References: response3 Sections 10 and 12.
#   Data structures:
#     - PhaseId = Literal['libraries', 'architecture', 'quality'] — three-phase forward-only pipeline.
#     - Public API renames only; no behavioral structures.
#   Interface contracts:
#     - Export AspectPromotionGate (or PromotionGate) instead of LayerPromotionGate.
#     - Export updated GateId enum and unchanged result structures.
#     - Keep call graph exports as advisory tooling only.
# IMPL(single-layer): Keep this package as the single external import surface for
# promotion gates/config/results so symbol renames land in one API boundary.
#   Control flow:
#     1. Replace layer terminology in module docstring/public names with phase/aspect terminology.
#     2. Three phases (Libraries -> Architecture -> Quality), forward-only; no cycling back.
#     3. Each phase edits code via its own PromotionLoop with IMPLEMENT step — all phases do work.
#     4. Preserve import paths for current package exports only (no compatibility shim aliases).
# IMPL(single-layer): Remove `LayerPromotionGate` in the same change that adds
# `AspectPromotionGate`/`PromotionGate`; do not keep alias shims.
#   Error handling:
#     - Import mismatch should raise immediately during package import tests.
#   Integration points:
#     - Consumed by promotion loop and lifecycle.
#     - Phase-local remediation if within authority; block if outside authority (no backtracking).
#   Test requirements:
#     - API smoke test for renamed symbols.
#     - Ensure removed symbols are absent.

"""Compliance gating for layer promotion.

This sub-package implements quality gates that must pass before promoting
code through the current layer pipeline.

Public API:
    LayerPromotionGate: Orchestrator for all promotion gate checks
    PromotionGateConfig: Full configuration for promotion gating
    PromotionReport: Aggregate report from all promotion gate checks
    GateCheckResult: Result of a single gate check
    GateId: Identifiers for each promotion gate check
    GateMode: How a gate failure is treated
    GateSpec: Configuration for a single gate check
    StrategyRegistry: Injectable registry for call-graph strategies
    CallGraphBuildResult: Aggregated call graph extraction results
    CallGraphEdge: One extracted call edge with provenance
"""

# IMPL(single-layer): Call graph exports stay advisory routing signals (Section 10.2),
# not deterministic gate authority.
from spec_manager.compliance.promotion.call_graph import (
    CallGraphBuildResult,
    CallGraphEdge,
    StrategyRegistry,
)

# IMPL(single-layer): Gate config exports track the Section 10.2 collapse from
# pin/layer gates to shape/verifier-oriented gates.
from spec_manager.compliance.promotion.config import (
    GateId,
    GateMode,
    GateSpec,
    PhaseId,
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
    "PhaseId",
    "PromotionGateConfig",
    "PromotionReport",
    "StrategyRegistry",
]
