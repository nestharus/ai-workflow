# TODO(single-layer): RESTRUCTURE — Triage classification logic survives but targets
#   change. Layer = Literal["L1","L2","L3"] becomes Phase = Literal["libraries",
#   "architecture","quality"] (3 phases, forward-only, no cycling back).
#   required_change_type mapping is already correct (behavior_change, wiring_only,
#   refactor_only, spec_change) — used for: routing within current phase's work queues,
#   detecting illegal changes for the phase, deciding block vs proceed.
#   Category routing (LOGIC→libraries, ARCH→architecture, STYLE→quality) maps
#   naturally. Remove failing_pins field, add shape_id field. The triage algorithm
#   itself (priority cascade) is a good pattern that KEEPS (Section 11.1).
#   No cross-phase demotion (Section 9.2): if a phase encounters something outside
#   its authority, it BLOCKS (not re-triages to an earlier phase). Architecture can
#   do in-phase remediation of algorithms; Quality blocks on behavior change.
#   Gate cleanup (Section 10.2): merge TESTS_PASS into ALL_TESTS_PASS — single gate
#   in the single-layer model. Remove redundant _GATE_RULES entries for defunct gates.
# ALGORITHM(single-layer):
#   References: response3 Sections 9.2, 10.2, 11.1; evaluation modification #2.
#   Data structures:
#     - PhaseId = Literal['libraries', 'architecture', 'quality'] imported from run_state.py.
#     - DemotionContext -> EscalationContext: {active_phase: PhaseId, source: str, gate: str|None, category: str, dimension: str, tags: list[str], required_change_type: Literal['behavior_change','wiring_only','refactor_only','spec_change']|str, failing_files: list[str], shape_id: ShapeId|None, evidence_paths: list[str]}.
#     - DemotionRouting -> EscalationRouting: {action: Literal['queue_work_item','fix_in_phase','block'], reason: str, confidence: float, diagnostics: list[str]}.
#   Interface contracts:
#     - def triage(ctx: EscalationContext) -> EscalationRouting
#     - def triage_finding(finding_dict: dict[str, Any], active_phase: PhaseId) -> EscalationRouting
#   Control flow:
#     1. Priority cascade: required_change_type mapping first, then gate mapping, then category/tag fallback.
#     2. Classification determines: route within current phase work queue, or block.
#     3. Authority classification is phase-context-dependent (not a rigid category→phase map):
#        - Libraries phase: behavior_change, spec_change, wiring_only, refactor_only → all within authority.
#        - Architecture phase: wiring_only → within authority; behavior_change within existing
#          library boundaries → within authority (in-place algorithm remediation); behavior_change
#          requiring new library or ownership change → block; refactor_only → block.
#        - Quality phase: refactor_only → within authority; behavior_change → block.
#     4. If finding is within current phase authority: queue_work_item or fix_in_phase.
#     5. If finding is outside current phase authority: block (no demotion to earlier phase).
#     6. Merge TESTS_PASS into ALL_TESTS_PASS and remove dead gate IDs from routing tables.
#   Error handling:
#     - Unknown category/gate returns block action with explicit diagnostics.
#     - Missing shape_id keeps routing result but marks needs_owner_resolution diagnostic.
#   Integration points:
#     - Called by demotion router, findings converter, lifecycle hooks.
#   Test requirements:
#     - Required_change_type precedence over category fallback.
#     - Out-of-authority findings produce block (not cross-phase re-route) across all three phases.
#     - Architecture phase can remediate algorithm findings in-place (not blocked).
#     - Quality phase blocks on behavior_change (cannot handle).
#     - Legacy gate IDs rejected or mapped deterministically.

"""Demotion triage: classifies failures into target layers/actions.

Given failure evidence (gate violations, test failures, review findings),
determine which layer is responsible for remediation, or whether progress
must be blocked in-place.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from spec_manager.compliance.promotion.config import PhaseId
from spec_manager.routing.shapes import ShapeId

# IMPL(single-layer): Replace layer identifiers with `PhaseId`
# (`libraries`/`architecture`/`quality`) and drop layer-order demotion math.
Layer = Literal["L1", "L2", "L3"]
RoutingAction = Literal["queue_work_item", "fix_in_phase", "block"]

_PHASE_ORDER: dict[PhaseId, int] = {"libraries": 0, "architecture": 1, "quality": 2}
_PHASE_TO_LAYER: dict[PhaseId, Layer] = {
    "libraries": "L1",
    "architecture": "L2",
    "quality": "L3",
}
_LAYER_TO_PHASE: dict[Layer, PhaseId] = {v: k for k, v in _PHASE_TO_LAYER.items()}
logger = logging.getLogger(__name__)
_OWNER_DIAGNOSTIC = "NEEDS_OWNER_RESOLUTION"


@dataclass
class DemotionContext:
    """Context for triaging a failure into a demotion target."""

    # IMPL(single-layer): Migrate to `EscalationContext` with `active_phase`,
    # remove `failing_pins`, and add `shape_id` owner context for phase-local work.
    active_phase: PhaseId = "libraries"
    source: str = ""  # TEST_FAILURE, REVIEW, ARCH_GATE, ALGORITHMIC_GATE, LINEAGE
    gate: str | None = None
    category: str = ""  # style | maintainability | architecture | logic | drift | governance
    dimension: str = ""  # ARCH_BOUNDARY | PIN_COVERAGE | CLARITY | CORRECTNESS | DRIFT | GOVERNANCE
    tags: list[str] = field(default_factory=list)
    required_change_type: str = ""  # refactor_only, wiring_only, behavior_change, spec_change
    failing_files: list[str] = field(default_factory=list)
    shape_id: ShapeId | None = None
    evidence_paths: list[str] = field(default_factory=list)
    # Legacy compatibility for existing callers.
    active_layer: Layer = "L1"
    source_layer: Layer = "L1"
    failing_pins: list[str] = field(default_factory=list)


@dataclass
class DemotionRouting:
    """Result of triaging a failure."""

    # IMPL(single-layer): Migrate to action-only `EscalationRouting`
    # (`queue_work_item`/`fix_in_phase`/`block`) without `target_layer`.
    target_layer: Layer = "L1"
    action: RoutingAction = "block"
    reason: str = ""
    confidence: float = 1.0
    diagnostics: list[str] = field(default_factory=list)


EscalationContext = DemotionContext
EscalationRouting = DemotionRouting


# required_change_type → target phase (highest priority)
# IMPL(single-layer): Keep required_change_type precedence (Section 11), but evaluate
# legality against the active phase authority instead of routing to earlier layers.
_CHANGE_TYPE_ROUTING: dict[str, PhaseId] = {
    "behavior_change": "libraries",
    "spec_change": "libraries",
    "wiring_only": "architecture",
    "refactor_only": "quality",
}
_KNOWN_CHANGE_TYPES = frozenset(_CHANGE_TYPE_ROUTING)

# Canonical category defaults from SEC-027.
_CATEGORY_ROUTING: dict[str, PhaseId | None] = {
    "style": "quality",
    "maintainability": "quality",
    "architecture": "architecture",
    "logic": "libraries",
    "drift": None,  # scope-sensitive; handled separately
    "governance": None,  # block in current layer
}
_CATEGORY_ALIASES: dict[str, str] = {
    "arch": "architecture",
    "spec": "logic",
}

# Gate routing is authoritative in one table:
# gate_id -> tuple[phase...]
# IMPL(single-layer): Apply Section 10.2 gate collapse here (`TESTS_PASS` merged into
# `ALL_TESTS_PASS`; pin-era gate IDs removed) and block on retired/unknown gate IDs.
_GATE_RULES: dict[str, tuple[PhaseId, ...]] = {
    "NO_REMAINING_COMMENTS": ("quality",),
    "NO_STUB_FUNCTIONS": ("libraries", "architecture", "quality"),
    "ALL_TESTS_PASS": ("libraries", "architecture", "quality"),
    "CALL_GRAPH_CONNECTED": ("libraries", "architecture"),
    "STORE_MONOGAMY": ("libraries", "architecture", "quality"),
    "FUNCTION_RECOMPOSITION": ("architecture", "quality"),
    "NO_ORPHAN_COMPONENTS": ("architecture", "quality"),
    "EVENT_HANDLER_COVERAGE": ("architecture", "quality"),
    "CONFIG_EXTERNALIZATION": ("architecture", "quality"),
    "INTRODUCED_ALGORITHM_SPECS": ("libraries",),
    "SHAPE_VERIFIERS_PASS": ("libraries", "architecture", "quality"),
    "IMPORT_BOUNDARY_CHECK": ("libraries", "architecture", "quality"),
    "SHAPE_DRIFT_RESOLVED": ("libraries", "architecture"),
    "PROVENANCE_COMPLETE": ("architecture", "quality"),
    "ENTITY_COVERAGE": ("quality",),
}
_DEPRECATED_GATES = {
    "TESTS_PASS",
    "PIN_COVERAGE",
    "PIN_CONSUMPTION_COVERAGE",
    "NO_INLINED_ATOM_LOGIC",
    "ARCH_DRIFT_PASS",
    "TEST_PIN_ALIGNMENT",
    "EDGE_REALIZATION",
}
_GATE_ROUTING: dict[str, tuple[PhaseId, ...]] = {
    gate: tuple(phase_ids) for gate, phase_ids in _GATE_RULES.items()
}

# Source → target phase fallback
# IMPL(single-layer): Keep source fallback lowest-priority only; it cannot authorize
# cross-phase backtracking once phase authority boundaries are enforced.
_SOURCE_ROUTING: dict[str, PhaseId] = {
    "ALGORITHMIC_GATE": "libraries",
    "ARCH_GATE": "architecture",
    "TEST_FAILURE": "libraries",
    "LINEAGE": "architecture",
    "REVIEW": "quality",
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
_ARCH_BOUNDARY_TAGS = {
    "ARCH_BOUNDARY",
    "CROSS_COMPONENT",
    "TOPOLOGY",
    "OWNERSHIP_CHANGE",
    "NEW_LIBRARY",
    "PROJECTION",
}
_ARCH_BOUNDARY_DIMENSIONS = {"ARCH_BOUNDARY", "TOPOLOGY"}


def triage(ctx: DemotionContext) -> DemotionRouting:
    """Classify a failure and determine a phase-local routing action."""
    # IMPL(single-layer): `triage` becomes phase-local classification:
    # within-authority -> queue/fix in phase, out-of-authority -> block.
    layer_phase = _normalize_phase(ctx.active_layer, fallback="libraries")
    active_phase = _normalize_phase(ctx.active_phase, fallback=layer_phase)
    if active_phase == "libraries" and _normalize_layer(ctx.active_layer, "L1") in {"L2", "L3"}:
        active_phase = layer_phase
    source_layer = _normalize_layer(ctx.source_layer, _PHASE_TO_LAYER[active_phase])
    source = _normalize_source(ctx.source)
    gate = normalize_gate_id(ctx.gate)
    category = _normalize_category(ctx.category)
    dimension = (ctx.dimension or "").strip().upper()
    tags = _normalize_tags(ctx.tags)
    required_change_type = _normalize_change_type(ctx.required_change_type)

    ctx.shape_id = _normalize_shape_id(getattr(ctx, "shape_id", None))

    # Governance findings block progress in-place; this is not a demotion.
    if category == "governance" or dimension == "GOVERNANCE":
        return _with_shape_diagnostics(
            _route_authority(
                active_phase=active_phase,
                target_phase=active_phase,
                action="block",
                reason="Governance finding requires same-phase remediation before continuing",
                confidence=0.95,
                ctx=ctx,
            ),
            ctx,
        )

    # 0. Try required_change_type routing (most precise, from Finding schema)
    if required_change_type:
        return _triage_required_change(
            ctx=ctx,
            active_phase=active_phase,
            required_change_type=required_change_type,
            dimension=dimension,
            tags=tags,
        )

    # 1. Try category-based routing
    if category:
        if category == "drift":
            drift_target, drift_reason = _route_drift(tags=tags, dimension=dimension)
            return _route_authority(
                active_phase=active_phase,
                target_phase=drift_target,
                action="queue_work_item",
                reason=drift_reason,
                confidence=0.85,
                ctx=ctx,
            )

        target = _CATEGORY_ROUTING.get(category)
        if target is None and category in _CATEGORY_ROUTING:
            return _route_authority(
                active_phase=active_phase,
                target_phase=_LAYER_TO_PHASE[source_layer],
                action="fix_in_phase",
                reason=f"Category '{category}' fixes in current phase {active_phase}",
                confidence=0.9,
                ctx=ctx,
            )
        if target is None:
            return _diagnostic_block(
                active_phase=active_phase,
                target_phase=active_phase,
                reason=f"Unknown category '{category}' — blocked",
                confidence=0.5,
                diagnostic_code=f"UNKNOWN_CATEGORY:{category}",
                ctx=ctx,
            )

        override = _tag_override_target(category=category, tags=tags)
        if override is not None:
            target = override

        return _route_authority(
            active_phase=active_phase,
            target_phase=target,
            action="queue_work_item",
            reason=f"Category '{category}' routes to {target}",
            confidence=0.9,
            ctx=ctx,
        )

    # 2. Try gate-based routing
    if gate:
        # IMPL(single-layer): Unknown/retired gate IDs should return `block`
        # with diagnostics rather than silently falling through to source heuristics.
        if gate in _DEPRECATED_GATES:
            return _diagnostic_block(
                active_phase=active_phase,
                target_phase=active_phase,
                reason=f"Gate '{gate}' is retired in single-layer routing policy",
                confidence=0.6,
                diagnostic_code=f"DEPRECATED_GATE:{gate}",
                ctx=ctx,
            )

        target_phases = _GATE_ROUTING.get(gate)
        if target_phases is None:
            return _diagnostic_block(
                active_phase=active_phase,
                target_phase=active_phase,
                reason=f"Unknown gate '{gate}' — blocked",
                confidence=0.4,
                diagnostic_code=f"UNKNOWN_GATE:{gate}",
                ctx=ctx,
            )
        if active_phase in target_phases:
            return _route_authority(
                active_phase=active_phase,
                target_phase=active_phase,
                action="queue_work_item",
                reason=f"Gate '{gate}' is in-scope for active phase {active_phase}",
                confidence=0.85,
                ctx=ctx,
            )

        return _diagnostic_block(
            active_phase=active_phase,
            target_phase=active_phase,
            reason=(
                f"Gate '{gate}' is handled in {', '.join(target_phases)}; "
                f"active phase is {active_phase}"
            ),
            confidence=0.7,
            diagnostic_code=f"GATE_OUT_OF_PHASE:{gate}",
            ctx=ctx,
        )

    # 3. Try source-based routing
    if source:
        target = _SOURCE_ROUTING.get(source)
        if target is None:
            return _diagnostic_block(
                active_phase=active_phase,
                target_phase=active_phase,
                reason=f"Unknown source '{source}' — blocked",
                confidence=0.5,
                diagnostic_code=f"UNKNOWN_SOURCE:{source}",
                ctx=ctx,
            )
        return _route_authority(
            active_phase=active_phase,
            target_phase=target,
            action="queue_work_item",
            reason=f"Source '{source}' maps to {target}",
            confidence=0.7,
            ctx=ctx,
        )

    # 4. Default: block until manual triage is possible.
    return _diagnostic_block(
        active_phase=active_phase,
        target_phase=active_phase,
        reason="Unclassifiable failure — blocked (needs manual triage)",
        confidence=0.3,
        diagnostic_code="UNCLASSIFIABLE_FAILURE",
        ctx=ctx,
    )


def triage_finding(
    finding_dict: dict[str, Any],
    active_phase: PhaseId,
    source_layer: Layer | None = None,
) -> DemotionRouting:
    """Convenience: triage a Finding dict directly.

    Constructs a DemotionContext from the finding's fields and delegates
    to :func:`triage`.
    """
    # IMPL(single-layer): Signature migrates to phase terminology and should
    # forward `shape_id` owner context from finding conversion.
    loc = finding_dict.get("location", {})
    return triage(
        DemotionContext(
            active_phase=active_phase,
            active_layer=source_layer or "L1",
            source="LINEAGE",
            category=finding_dict.get("category", ""),
            dimension=finding_dict.get("dimension", ""),
            tags=list(finding_dict.get("tags", []) or []),
            required_change_type=finding_dict.get("required_change_type", ""),
            shape_id=_normalize_shape_id(finding_dict.get("shape_id")),
            failing_files=[loc["file"]] if loc.get("file") else [],
        )
    )


def _triage_required_change(
    *,
    ctx: DemotionContext,
    active_phase: PhaseId,
    required_change_type: str,
    dimension: str,
    tags: set[str],
) -> DemotionRouting:
    if required_change_type not in _KNOWN_CHANGE_TYPES:
        return _diagnostic_block(
            active_phase=active_phase,
            target_phase=active_phase,
            reason=f"Unknown change type '{required_change_type}' — blocked",
            confidence=0.35,
            diagnostic_code=f"UNKNOWN_CHANGE_TYPE:{required_change_type}",
            ctx=ctx,
        )

    target_phase = _CHANGE_TYPE_ROUTING[required_change_type]
    action = _default_action(
        active_phase=active_phase,
        required_change_type=required_change_type,
    )

    # Architecture can only remediate algorithm behavior changes in-scope.
    if required_change_type == "behavior_change":
        if active_phase == "architecture" and _requires_library_or_ownership_change(
            tags=tags,
            dimension=dimension,
        ):
            return _diagnostic_block(
                active_phase=active_phase,
                target_phase=target_phase,
                reason=(
                    "Architecture behavior change requires ownership/library transition; "
                    "out of active-phase authority"
                ),
                confidence=0.9,
                diagnostic_code="ARCHITECTURE_SCOPE_CHANGE",
                ctx=ctx,
            )
        if active_phase == "quality":
            return _diagnostic_block(
                active_phase=active_phase,
                target_phase=target_phase,
                reason="Quality phase blocks behavior-change findings",
                confidence=0.95,
                diagnostic_code="QUALITY_BLOCKS_BEHAVIOR_CHANGE",
                ctx=ctx,
            )

    if required_change_type == "refactor_only" and active_phase == "architecture":
        return _diagnostic_block(
            active_phase=active_phase,
            target_phase=target_phase,
            reason="Architecture phase blocks refactor-only findings",
            confidence=0.95,
            diagnostic_code="ARCHITECTURE_REFACTOR_OUT_OF_AUTHORITY",
            ctx=ctx,
        )

    return _route_authority(
        active_phase=active_phase,
        target_phase=target_phase,
        action=action,
        reason=f"Change type '{required_change_type}' routes to {target_phase}",
        confidence=0.95,
        ctx=ctx,
    )


def _route_authority(
    *,
    active_phase: PhaseId,
    target_phase: PhaseId,
    action: RoutingAction,
    reason: str,
    confidence: float,
    ctx: DemotionContext,
) -> DemotionRouting:
    if _phase_authority(active_phase, target_phase):
        return _with_shape_diagnostics(
            DemotionRouting(
                target_layer=_PHASE_TO_LAYER[target_phase],
                action=action,
                reason=reason,
                confidence=confidence,
            ),
            ctx=ctx,
        )
    return _diagnostic_block(
        active_phase=active_phase,
        target_phase=target_phase,
        reason=(
            f"{reason}: active_phase={active_phase} "
            f"target_phase={target_phase} is out of phase authority"
        ),
        confidence=min(0.7, confidence),
        diagnostic_code=f"OUT_OF_AUTHORITY:{active_phase}->{target_phase}",
        ctx=ctx,
    )


def _diagnostic_block(
    *,
    active_phase: PhaseId,
    target_phase: PhaseId,
    reason: str,
    confidence: float,
    diagnostic_code: str,
    ctx: DemotionContext,
) -> DemotionRouting:
    # IMPL(single-layer): Unknown/retired gate and category inputs should return block
    # with explicit diagnostic evidence.
    logger.warning("Demotion triage blocked: %s [%s]", reason, diagnostic_code)
    return _with_shape_diagnostics(
        DemotionRouting(
            target_layer=_PHASE_TO_LAYER.get(
                target_phase,
                _PHASE_TO_LAYER[active_phase],
            ),
            action="block",
            reason=reason,
            confidence=confidence,
            diagnostics=[diagnostic_code],
        ),
        ctx=ctx,
    )


def _with_shape_diagnostics(routing: DemotionRouting, ctx: DemotionContext) -> DemotionRouting:
    if getattr(ctx, "shape_id", None) is None and _OWNER_DIAGNOSTIC not in routing.diagnostics:
        routing.diagnostics.append(_OWNER_DIAGNOSTIC)
    return routing


def _default_action(active_phase: PhaseId, required_change_type: str) -> RoutingAction:
    if required_change_type == "refactor_only" and active_phase in {"libraries", "quality"}:
        return "fix_in_phase"
    return "queue_work_item"


def _phase_authority(active_phase: PhaseId, target_phase: PhaseId) -> bool:
    if active_phase == "libraries":
        return True
    if active_phase == "architecture":
        return target_phase in {"libraries", "architecture"}
    if active_phase == "quality":
        return target_phase == "quality"
    return False


def _normalize_tags(tags: list[str]) -> set[str]:
    """Normalize tag strings for stable routing comparisons."""
    return {t.strip().upper() for t in tags if isinstance(t, str) and t.strip()}


def _normalize_category(category: str | None) -> str:
    raw = str(category or "").strip().lower()
    if not raw:
        return ""
    return _CATEGORY_ALIASES.get(raw, raw)


def _tag_override_target(category: str, tags: set[str]) -> PhaseId | None:
    """Return a stronger target implied by category+tag combinations."""
    if category == "architecture" and tags.intersection(_ARCH_TO_L1_TAGS):
        return "libraries"
    if category == "logic":
        if tags.intersection(_LOGIC_TO_L1_TAGS):
            return "libraries"
        if tags.intersection(_LOGIC_TO_L2_TAGS):
            return "architecture"
    return None


def _route_drift(*, tags: set[str], dimension: str) -> tuple[PhaseId, str]:
    """Classify drift scope as architectural (architecture) or behavioral (libraries)."""
    if tags.intersection(_DRIFT_TO_L2_TAGS):
        return (
            "architecture",
            f"Drift finding tagged architectural scope {sorted(tags)} routes to architecture",
        )
    if tags.intersection(_DRIFT_TO_L1_TAGS):
        return (
            "libraries",
            f"Drift finding tagged behavioral scope {sorted(tags)} routes to libraries",
        )
    if dimension in _DRIFT_DIMENSION_TO_L2:
        return "architecture", f"Drift finding with dimension '{dimension}' routes to architecture"
    if dimension in _DRIFT_DIMENSION_TO_L1:
        return "libraries", f"Drift finding with dimension '{dimension}' routes to libraries"
    return "libraries", "Drift finding missing explicit scope signal; conservatively routes to libraries"


def infer_gate_source_layer(gate_id: str | None) -> Layer | None:
    """Infer the originating layer for a gate identifier."""
    # IMPL(single-layer): Replace with phase vocabulary and map legacy callers
    # to deterministic source-layer hints.
    normalized = normalize_gate_id(gate_id)
    if not normalized:
        return None

    if normalized.startswith("L1_"):
        return "L1"
    if normalized.startswith("L2_"):
        return "L2"
    if normalized.startswith("L3_"):
        return "L3"

    phases = _GATE_ROUTING.get(normalized)
    if not phases:
        return None
    if "libraries" in phases:
        return "L1"
    if "architecture" in phases:
        return "L2"
    if "quality" in phases:
        return "L3"
    return None


def normalize_gate_id(gate_id: str | None) -> str | None:
    """Canonical gate identifier format used across triage decisions."""
    normalized = str(gate_id or "").strip().upper().replace("-", "_")
    if normalized == "TESTS_PASS":
        normalized = "ALL_TESTS_PASS"
    return normalized or None


def _normalize_layer(layer: str | None, default: Layer) -> Layer:
    normalized = str(layer or "").strip().upper()
    if normalized in _PHASE_TO_LAYER.values():
        return cast("Layer", normalized)
    if normalized in _LAYER_TO_PHASE:
        return cast("Layer", normalized)
    return default


def _normalize_phase(phase: str | None, *, fallback: PhaseId) -> PhaseId:
    normalized = str(phase or "").strip().lower()
    if normalized in _PHASE_ORDER:
        return cast("PhaseId", normalized)
    upper = normalized.upper()
    if upper in _LAYER_TO_PHASE:
        return _LAYER_TO_PHASE[cast("Layer", upper)]
    return fallback


def _normalize_change_type(value: str | None) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _normalize_shape_id(shape_id: ShapeId | str | None) -> ShapeId | None:
    if isinstance(shape_id, ShapeId):
        return shape_id
    if isinstance(shape_id, str):
        normalized = shape_id.strip()
        return normalized if normalized else None
    return None


def _normalize_source(source: str | None) -> str:
    return str(source or "").strip().upper()


def _requires_library_or_ownership_change(
    *,
    tags: set[str],
    dimension: str,
) -> bool:
    return bool(tags.intersection(_ARCH_BOUNDARY_TAGS) or dimension in _ARCH_BOUNDARY_DIMENSIONS)
