"""Demotion triage: classifies failures into target layers/actions.

Given failure evidence (gate violations, test failures, review findings),
determine which layer is responsible for remediation, or whether progress
must be blocked in-place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, cast

Layer = Literal["L1", "L2", "L3"]
RoutingAction = Literal["demote", "fix_in_layer", "block"]

_LAYER_ORDER: dict[Layer, int] = {"L1": 0, "L2": 1, "L3": 2}


@dataclass
class DemotionContext:
    """Context for triaging a failure into a demotion target."""

    active_layer: Layer = "L1"
    source_layer: Layer = "L1"
    source: str = ""  # TEST_FAILURE, REVIEW, ARCH_GATE, ALGORITHMIC_GATE, VERIFY, etc.
    gate: str | None = None
    category: str = ""  # style | maintainability | architecture | logic | drift | governance
    dimension: str = ""  # ARCH_BOUNDARY | PIN_COVERAGE | CLARITY | CORRECTNESS | DRIFT | GOVERNANCE
    tags: list[str] = field(default_factory=list)
    required_change_type: str = ""  # refactor_only, wiring_only, behavior_change, spec_change
    failing_files: list[str] = field(default_factory=list)
    failing_pins: list[str] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)


@dataclass
class DemotionRouting:
    """Result of triaging a failure."""

    target_layer: Layer = "L1"
    action: RoutingAction = "demote"
    reason: str = ""
    confidence: float = 1.0


# required_change_type → target layer (highest priority)
_CHANGE_TYPE_ROUTING: dict[str, Layer | None] = {
    "behavior_change": "L1",
    "spec_change": "L1",
    "wiring_only": "L2",
    "refactor_only": None,  # fix-in-layer, no demotion
}

# Canonical category defaults from SEC-027.
_CATEGORY_ROUTING: dict[str, Layer | None] = {
    "style": None,
    "maintainability": None,
    "architecture": "L2",
    "logic": "L1",
    "drift": None,  # scope-sensitive; handled separately
    "governance": None,  # block in current layer
}
_CATEGORY_ALIASES: dict[str, str] = {
    "arch": "architecture",
    "spec": "logic",
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

_L1_GATES = {
    "NO_REMAINING_COMMENTS",
    "NO_STUB_FUNCTIONS",
    "ALL_TESTS_PASS",
    "CALL_GRAPH_CONNECTED",
    "STORE_MONOGAMY",
}

_L2_GATES = {
    "NO_INLINED_ATOM_LOGIC",
    "FUNCTION_RECOMPOSITION",
    "PIN_CONSUMPTION_COVERAGE",
    "PIN_COVERAGE",
    "EDGE_REALIZATION",
    "NO_ORPHAN_COMPONENTS",
    "EVENT_HANDLER_COVERAGE",
    "CONFIG_EXTERNALIZATION",
    "ARCH_DRIFT_PASS",
    "INTRODUCED_ALGORITHM_SPECS",
}

_L3_GATES = {
    "ALL_QUALITY_REVIEWERS_PASS",
    "NO_LOGIC_CHANGE",
    "NO_ARCH_BOUNDARY_VIOLATIONS",
    "DRIFT_PASS",
    "TESTS_PASS",
}

# Source → target layer fallback
_SOURCE_ROUTING: dict[str, Layer | None] = {
    "ALGORITHMIC_GATE": "L1",
    "ARCH_GATE": "L2",
    "TEST_FAILURE": None,
    "LINEAGE": "L2",
    "REVIEW": "L3",
    "GATE_FAILURE": None,
    "VERIFY": None,
}

_ARCH_TO_L1_TAGS = {"INLINE_LOGIC_AT_ARCH"}
_LOGIC_TO_L1_TAGS = {"CORRECTNESS", "LOGIC_BUG", "SPEC_UNDER_SPEC"}
_LOGIC_TO_L2_TAGS = {
    "WIRING_ONLY",
    "PROJECTION",
    "ARCH_BOUNDARY",
    "PIN_COVERAGE",
    "ARCH_DRIFT",
    "CROSS_COMPONENT",
    "TOPOLOGY",
}
_DRIFT_TO_L2_TAGS = {
    "ARCH_DRIFT",
    "ARCH_BOUNDARY",
    "TOPOLOGY",
    "CROSS_COMPONENT",
    "PROJECTION",
    "WIRING_ONLY",
    "PIN_COVERAGE",
}
_DRIFT_TO_L1_TAGS = {
    "BEHAVIOR_DRIFT",
    "CORRECTNESS",
    "LOGIC_BUG",
    "SPEC_DRIFT",
    "SPEC_UNDER_SPEC",
    "BEHAVIOR_CHANGE",
    "SPEC_CHANGE",
}
_DRIFT_DIMENSION_TO_L2 = {"ARCH_BOUNDARY", "PIN_COVERAGE"}
_DRIFT_DIMENSION_TO_L1 = {"CORRECTNESS", "DRIFT", "CLARITY"}


def triage(ctx: DemotionContext) -> DemotionRouting:
    """Classify a failure and determine the target demotion layer.

    Priority: governance block > required_change_type > category > gate >
    source > fix-in-place.

    If the determined target layer is above the active layer, route down
    to the active layer instead (because higher layers aren't editable
    when lower layers are active).
    """
    active_layer = _normalize_layer(ctx.active_layer, "L1")
    source_layer = _normalize_layer(ctx.source_layer, active_layer)
    category = _normalize_category(ctx.category)
    dimension = (ctx.dimension or "").strip().upper()
    tags = _normalize_tags(ctx.tags)
    required_change_type = (ctx.required_change_type or "").strip().lower()

    # Governance findings block progress in-place; this is not a demotion.
    if category == "governance" or dimension == "GOVERNANCE":
        return DemotionRouting(
            target_layer=active_layer,
            action="block",
            reason="Governance finding requires same-layer remediation before continuing",
            confidence=0.95,
        )

    # 0. Try required_change_type routing (most precise, from Finding schema)
    if required_change_type:
        target = _CHANGE_TYPE_ROUTING.get(required_change_type)
        if target is None and required_change_type in _CHANGE_TYPE_ROUTING:
            return DemotionRouting(
                target_layer=active_layer,
                action="fix_in_layer",
                reason=f"Change type '{required_change_type}' fixes in current layer",
                confidence=0.95,
            )
        if target is None:
            return DemotionRouting(
                target_layer=active_layer,
                action="fix_in_layer",
                reason=f"Unknown change type '{required_change_type}' — fix in current layer",
                confidence=0.5,
            )
        return _constrain_to_active(
            DemotionRouting(
                target_layer=target,
                action="demote",
                reason=f"Change type '{required_change_type}' routes to {target}",
                confidence=0.95,
            ),
            active_layer,
        )

    # 1. Try category-based routing
    if category:
        if category == "drift":
            drift_target, drift_reason = _route_drift(tags=tags, dimension=dimension)
            return _constrain_to_active(
                DemotionRouting(
                    target_layer=drift_target,
                    action="demote",
                    reason=drift_reason,
                    confidence=0.85,
                ),
                active_layer,
            )

        target = _CATEGORY_ROUTING.get(category)
        if target is None and category in _CATEGORY_ROUTING:
            return DemotionRouting(
                target_layer=active_layer,
                action="fix_in_layer",
                reason=f"Category '{category}' fixes in current layer",
                confidence=0.9,
            )
        if target is None:
            return DemotionRouting(
                target_layer=active_layer,
                action="fix_in_layer",
                reason=f"Unknown category '{category}' — fix in current layer",
                confidence=0.5,
            )

        override = _tag_override_target(category=category, tags=tags)
        if override:
            return _constrain_to_active(
                DemotionRouting(
                    target_layer=override,
                    action="demote",
                    reason=f"Category '{category}' with tags {sorted(tags)} routes to {override}",
                    confidence=0.9,
                ),
                active_layer,
            )

        return _constrain_to_active(
            DemotionRouting(
                target_layer=target,
                action="demote",
                reason=f"Category '{category}' routes to {target}",
                confidence=0.9,
            ),
            active_layer,
        )

    # 2. Try gate-based routing
    if ctx.gate:
        target = _GATE_ROUTING.get(ctx.gate)
        if target is None and ctx.gate in _GATE_ROUTING:
            return DemotionRouting(
                target_layer=active_layer,
                action="fix_in_layer",
                reason=f"Gate '{ctx.gate}' fixes in current layer",
                confidence=0.85,
            )
        if target:
            return _constrain_to_active(
                DemotionRouting(
                    target_layer=target,
                    action="demote",
                    reason=f"Gate '{ctx.gate}' routes to {target}",
                    confidence=0.85,
                ),
                active_layer,
            )

    # 3. Try source-based routing
    if ctx.source:
        # Higher-layer failures cannot be fixed at that higher layer while a lower
        # layer is active; source-layer context narrows source-based fallback.
        if _is_layer_above(source_layer, active_layer):
            return DemotionRouting(
                target_layer=active_layer,
                action="fix_in_layer",
                reason=(
                    f"Source '{ctx.source}' originated at {source_layer} while active layer is "
                    f"{active_layer}; routing is constrained to current editable layer"
                ),
                confidence=0.75,
            )
        if ctx.source == "TEST_FAILURE":
            return DemotionRouting(
                target_layer=active_layer,
                action="fix_in_layer",
                reason=(
                    "Source 'TEST_FAILURE' defaults to current layer; "
                    "demote lower only when stronger diagnosis signals exist"
                ),
                confidence=0.7,
            )
        target = _SOURCE_ROUTING.get(ctx.source)
        if target is None and ctx.source in _SOURCE_ROUTING:
            return DemotionRouting(
                target_layer=active_layer,
                action="fix_in_layer",
                reason=f"Source '{ctx.source}' fixes in current layer",
                confidence=0.6,
            )
        if target:
            return _constrain_to_active(
                DemotionRouting(
                    target_layer=target,
                    action="demote",
                    reason=f"Source '{ctx.source}' routes to {target}",
                    confidence=0.7,
                ),
                active_layer,
            )

    # 4. Default: fix in current layer (don't guess target at low confidence)
    return DemotionRouting(
        target_layer=active_layer,
        action="fix_in_layer",
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
            dimension=finding_dict.get("dimension", ""),
            tags=list(finding_dict.get("tags", []) or []),
            required_change_type=finding_dict.get("required_change_type", ""),
            failing_files=[loc["file"]] if loc.get("file") else [],
        )
    )


def _constrain_to_active(routing: DemotionRouting, active_layer: Layer) -> DemotionRouting:
    """Ensure the target layer is not above the active layer.

    If active_layer is L1, target cannot be L2 or L3 (they don't exist yet).
    """
    target_idx = _LAYER_ORDER.get(routing.target_layer, 0)
    active_idx = _LAYER_ORDER.get(active_layer, 0)

    if target_idx > active_idx:
        routing.target_layer = active_layer
        routing.reason += f" (constrained to active layer {active_layer})"
        routing.confidence *= 0.8

    return routing


def _normalize_tags(tags: list[str]) -> set[str]:
    """Normalize tag strings for stable routing comparisons."""
    return {t.strip().upper() for t in tags if isinstance(t, str) and t.strip()}


def _normalize_category(category: str | None) -> str:
    raw = str(category or "").strip().lower()
    if not raw:
        return ""
    return _CATEGORY_ALIASES.get(raw, raw)


def _tag_override_target(category: str, tags: set[str]) -> Layer | None:
    """Return a stronger target implied by category+tag combinations."""
    if category == "architecture" and tags.intersection(_ARCH_TO_L1_TAGS):
        return "L1"
    if category == "logic":
        if tags.intersection(_LOGIC_TO_L1_TAGS):
            return "L1"
        if tags.intersection(_LOGIC_TO_L2_TAGS):
            return "L2"
    return None


def _route_drift(*, tags: set[str], dimension: str) -> tuple[Layer, str]:
    """Classify drift scope as architectural (L2) or behavioral (L1)."""
    if tags.intersection(_DRIFT_TO_L2_TAGS):
        return "L2", f"Drift finding tagged architectural scope {sorted(tags)} routes to L2"
    if tags.intersection(_DRIFT_TO_L1_TAGS):
        return "L1", f"Drift finding tagged behavioral scope {sorted(tags)} routes to L1"
    if dimension in _DRIFT_DIMENSION_TO_L2:
        return "L2", f"Drift finding with dimension '{dimension}' routes to L2"
    if dimension in _DRIFT_DIMENSION_TO_L1:
        return "L1", f"Drift finding with dimension '{dimension}' routes to L1"
    return "L1", "Drift finding missing explicit scope signal; conservatively routes to L1"


def infer_gate_source_layer(gate_id: str | None) -> Layer | None:
    """Infer the originating layer for a gate identifier."""
    normalized = str(gate_id or "").strip().upper()
    if not normalized:
        return None

    if normalized.startswith("L1_"):
        return "L1"
    if normalized.startswith("L2_"):
        return "L2"
    if normalized.startswith("L3_"):
        return "L3"

    if normalized in _L1_GATES:
        return "L1"
    if normalized in _L2_GATES:
        return "L2"
    if normalized in _L3_GATES:
        return "L3"
    return None


def _normalize_layer(layer: str | None, default: Layer) -> Layer:
    normalized = str(layer or "").strip().upper()
    if normalized in _LAYER_ORDER:
        return cast("Layer", normalized)
    return default


def _is_layer_above(source_layer: Layer, active_layer: Layer) -> bool:
    return _LAYER_ORDER[source_layer] > _LAYER_ORDER[active_layer]
