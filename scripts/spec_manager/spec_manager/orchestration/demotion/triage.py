"""Demotion triage: classifies failures into target layers.

Given failure evidence (gate violations, test failures, review findings),
determines which layer is responsible for the fix.

Classification policy:
- STYLE / QUALITY issues → L3 (clean code)
- ARCH / PROJECTION issues → L2 (architecture)
- LOGIC / SPEC / UNDER_SPEC issues → L1 (code-as-spec)
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
    source: str = ""  # TEST_FAILURE, REVIEW, ARCH_GATE, ALGORITHMIC_GATE, etc.
    gate: str | None = None
    category: str = ""  # STYLE, QUALITY, LOGIC, ARCH, SPEC, UNDER_SPEC
    failing_files: list[str] = field(default_factory=list)
    failing_pins: list[str] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)


@dataclass
class DemotionRouting:
    """Result of triaging a failure."""

    target_layer: Layer = "L1"
    reason: str = ""
    confidence: float = 1.0


# Category → target layer mapping
_CATEGORY_ROUTING: dict[str, Layer] = {
    "STYLE": "L3",
    "QUALITY": "L3",
    "LOGIC": "L1",
    "SPEC": "L1",
    "UNDER_SPEC": "L1",
    "ARCH": "L2",
    "PROJECTION": "L2",
}

# Gate → target layer mapping (for gate failures without category)
_GATE_ROUTING: dict[str, Layer] = {
    "NO_REMAINING_COMMENTS": "L1",
    "NO_STUB_FUNCTIONS": "L1",
    "ALL_TESTS_PASS": "L1",
    "CALL_GRAPH_CONNECTED": "L1",
    "STORE_MONOGAMY": "L1",
    "NO_INLINED_ATOM_LOGIC": "L1",
    "FUNCTION_RECOMPOSITION": "L2",
    "PIN_COVERAGE": "L2",
    "INTRODUCED_ALGORITHM_SPECS": "L2",
}

# Source → target layer fallback (when no category or gate info)
_SOURCE_ROUTING: dict[str, Layer] = {
    "ALGORITHMIC_GATE": "L1",
    "ARCH_GATE": "L2",
    "TEST_FAILURE": "L1",
    "LINEAGE": "L2",
    "REVIEW": "L3",
    "GATE_FAILURE": "L1",
}


def triage(ctx: DemotionContext) -> DemotionRouting:
    """Classify a failure and determine the target demotion layer.

    Priority: category > gate > source > default (L1).

    If the determined target layer is above the active layer, route down
    to the active layer instead (because higher layers aren't editable
    when lower layers are active).
    """
    # 1. Try category-based routing
    if ctx.category:
        target = _CATEGORY_ROUTING.get(ctx.category.upper())
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
        if target:
            return _constrain_to_active(
                DemotionRouting(
                    target_layer=target,
                    reason=f"Source '{ctx.source}' routes to {target}",
                    confidence=0.7,
                ),
                ctx.active_layer,
            )

    # 4. Default to L1
    return DemotionRouting(
        target_layer="L1",
        reason="Default routing to L1",
        confidence=0.5,
    )


def _constrain_to_active(
    routing: DemotionRouting, active_layer: Layer
) -> DemotionRouting:
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
