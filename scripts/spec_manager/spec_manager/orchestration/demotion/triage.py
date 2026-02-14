"""Demotion triage: classifies failures into target layers.

Given failure evidence (gate violations, test failures, review findings),
determines which layer is responsible for the fix.

Classification policy follows SEC-026 two-stage routing:
1. behavior_change (or forced logic-affecting tags) → L1
2. architecture/cross-component/topology scope → L2
3. otherwise fix in current layer (no demotion)

Forced demotions:
- INLINE_LOGIC_AT_ARCH → L1
- Diff-impact logic-affecting → L1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Layer = Literal["L1", "L2", "L3"]


@dataclass
class DemotionContext:
    """Context for triaging a failure into a demotion target."""

    active_layer: Layer = "L1"
    source_layer: Layer = "L1"
    source: str = ""  # TEST_FAILURE, REVIEW, ARCH_GATE, ALGORITHMIC_GATE, VERIFY, etc.
    gate: str | None = None
    category: str = (
        ""  # STYLE, MAINTAINABILITY, LOGIC, ARCH, SPEC, UNDER_SPEC, DRIFT, GOVERNANCE, etc.
    )
    required_change_type: str = ""  # refactor_only, wiring_only, behavior_change, spec_change
    failing_files: list[str] = field(default_factory=list)
    failing_pins: list[str] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)


@dataclass
class DemotionRouting:
    """Result of triaging a failure."""

    target_layer: Layer = "L1"
    reason: str = ""
    confidence: float = 1.0


# required_change_type → target layer (highest priority)
_CHANGE_TYPE_ROUTING: dict[str, Layer | None] = {
    "behavior_change": "L1",
    "spec_change": "L1",
    "wiring_only": "L2",
    "refactor_only": None,  # fix-in-layer, no demotion
}

# Category → target layer mapping (minimal SEC-026 triage)
_CATEGORY_ROUTING: dict[str, Layer | None] = {
    "LOGIC_AFFECTING": "L1",
    "INLINE_LOGIC_AT_ARCH": "L1",
    "ARCH": "L2",
    "ARCHITECTURE": "L2",
    "CROSS_COMPONENT": "L2",
    "TOPOLOGY": "L2",
    "PROJECTION": "L2",
    "DRIFT": None,
    "GOVERNANCE": None,  # block in current layer, no demotion
}

# Gate → target layer mapping
_GATE_ROUTING: dict[str, Layer | None] = {
    # L1 gates
    "NO_REMAINING_COMMENTS": "L1",
    "NO_STUB_FUNCTIONS": "L1",
    "ALL_TESTS_PASS": "L1",
    "CALL_GRAPH_CONNECTED": "L1",
    "STORE_MONOGAMY": "L1",
    # L2 gates
    "NO_INLINED_ATOM_LOGIC": "L1",
    "FUNCTION_RECOMPOSITION": "L2",
    "PIN_CONSUMPTION_COVERAGE": "L2",
    "PIN_COVERAGE": "L2",
    "EDGE_REALIZATION": "L2",
    "NO_ORPHAN_COMPONENTS": "L2",
    "EVENT_HANDLER_COVERAGE": "L2",
    "CONFIG_EXTERNALIZATION": "L2",
    "ARCH_DRIFT_PASS": "L2",
    "INTRODUCED_ALGORITHM_SPECS": "L2",
    # L3 gates
    "ALL_QUALITY_REVIEWERS_PASS": None,
    "NO_LOGIC_CHANGE": "L1",
    "NO_ARCH_BOUNDARY_VIOLATIONS": "L2",
    "DRIFT_PASS": None,
    "TESTS_PASS": "L1",
}

# Source → target layer fallback
_SOURCE_ROUTING: dict[str, Layer | None] = {
    "ALGORITHMIC_GATE": "L1",
    "ARCH_GATE": "L2",
    "TEST_FAILURE": "L1",
    "LINEAGE": "L2",
    "REVIEW": "L3",
    "GATE_FAILURE": None,
    "VERIFY": None,
}


def triage(ctx: DemotionContext) -> DemotionRouting:
    """Classify a failure and determine the target demotion layer.

    Priority: required_change_type > category > gate > source > fix-in-place.

    If the determined target layer is above the active layer, route down
    to the active layer instead (because higher layers aren't editable
    when lower layers are active).
    """
    # 0. Try required_change_type routing (most precise, from Finding schema)
    if ctx.required_change_type:
        target = _CHANGE_TYPE_ROUTING.get(ctx.required_change_type)
        if target is None:
            # refactor_only or governance → fix-in-layer, no demotion needed
            return DemotionRouting(
                target_layer=ctx.active_layer,
                reason=f"Change type '{ctx.required_change_type}' fixes in current layer",
                confidence=0.95,
            )
        return _constrain_to_active(
            DemotionRouting(
                target_layer=target,
                reason=f"Change type '{ctx.required_change_type}' routes to {target}",
                confidence=0.95,
            ),
            ctx.active_layer,
        )

    # 1. Try category-based routing
    if ctx.category:
        target = _CATEGORY_ROUTING.get(ctx.category.upper())
        if target is None:
            # GOVERNANCE → fix in current layer
            return DemotionRouting(
                target_layer=ctx.active_layer,
                reason=f"Category '{ctx.category}' fixes in current layer",
                confidence=0.9,
            )
        if target:
            return _constrain_to_active(
                DemotionRouting(
                    target_layer=target,
                    reason=f"Category '{ctx.category}' routes to {target}",
                    confidence=0.9,
                ),
                ctx.active_layer,
            )

    # 2. Try gate-based routing
    if ctx.gate:
        target = _GATE_ROUTING.get(ctx.gate)
        if target is None and ctx.gate in _GATE_ROUTING:
            return DemotionRouting(
                target_layer=ctx.active_layer,
                reason=f"Gate '{ctx.gate}' fixes in current layer",
                confidence=0.85,
            )
        if target:
            return _constrain_to_active(
                DemotionRouting(
                    target_layer=target,
                    reason=f"Gate '{ctx.gate}' routes to {target}",
                    confidence=0.85,
                ),
                ctx.active_layer,
            )

    # 3. Try source-based routing
    if ctx.source:
        target = _SOURCE_ROUTING.get(ctx.source)
        if target is None and ctx.source in _SOURCE_ROUTING:
            return DemotionRouting(
                target_layer=ctx.active_layer,
                reason=f"Source '{ctx.source}' fixes in current layer",
                confidence=0.6,
            )
        if target:
            return _constrain_to_active(
                DemotionRouting(
                    target_layer=target,
                    reason=f"Source '{ctx.source}' routes to {target}",
                    confidence=0.7,
                ),
                ctx.active_layer,
            )

    # 4. Default: fix in current layer (don't guess target at low confidence)
    return DemotionRouting(
        target_layer=ctx.active_layer,
        reason="Unclassifiable failure — fix in current layer (needs manual triage)",
        confidence=0.3,
    )


def triage_finding(finding_dict: dict, active_layer: Layer, source_layer: Layer) -> DemotionRouting:
    """Convenience: triage a Finding dict directly.

    Constructs a DemotionContext from the finding's fields and delegates
    to :func:`triage`.
    """
    loc = finding_dict.get("location", {})
    return triage(
        DemotionContext(
            active_layer=active_layer,
            source_layer=source_layer,
            source="VERIFY",
            category=finding_dict.get("category", ""),
            required_change_type=finding_dict.get("required_change_type", ""),
            failing_files=[loc["file"]] if loc.get("file") else [],
        )
    )


def _constrain_to_active(routing: DemotionRouting, active_layer: Layer) -> DemotionRouting:
    """Ensure the target layer is not above the active layer.

    If active_layer is L1, target cannot be L2 or L3 (they don't exist yet).
    """
    layer_order = {"L1": 0, "L2": 1, "L3": 2}
    target_idx = layer_order.get(routing.target_layer, 0)
    active_idx = layer_order.get(active_layer, 0)

    if target_idx > active_idx:
        routing.target_layer = active_layer
        routing.reason += f" (constrained to active layer {active_layer})"
        routing.confidence *= 0.8

    return routing
