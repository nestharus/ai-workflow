"""Core types and Planner API for the planning module.

Defines the public data types (PlanningContext, PlanningRequest,
PlanningResult) and the Planner class that serves as the single
auto-mode decision authority.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from spec_manager.planner.router import CapabilityRouter, LayerRouter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Layer = Literal["l1", "l2", "l3", "any"]
Capability = Literal[
    "RESOLVE_SIGNAL",  # interactive refinement + under-spec questions
    "GAP",  # gap understanding / clustering / prioritization
    "PLAN",  # plan synthesis (intentions / wiring / refactor)
    "UNDER_SPEC",  # resolve or block; produce constraints or questions
    "INTEGRATION_ANALYSIS",
]


# ---------------------------------------------------------------------------
# Core data types
# ---------------------------------------------------------------------------


@dataclass
class PlanningContext:
    """Per-request context passed through all planner operations."""

    run_id: str = ""
    slice_id: str = ""
    iteration: int = 0
    layer: Layer = "any"
    mode: Literal["auto", "interactive"] = "auto"
    workspace_root: str = ""
    slice_root: str = ""
    bundle_ref: Any = None  # EvidenceBundle or lightweight view
    signal_ref: Any = None  # InputSignal or Ambiguity
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanningRequest:
    """A typed request dispatched to the planner."""

    capability: Capability
    context: PlanningContext
    inputs: dict[str, Any] = field(default_factory=dict)
    constraints_hint: dict[str, Any] | None = None


@dataclass
class PlanningResult:
    """Outcome of a planner invocation."""

    status: Literal["OK", "BLOCKED", "NEEDS_INPUT", "NOOP", "ERROR"]
    outputs: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class Planner:
    """Single auto-mode decision authority across the spec manager lifecycle.

    Routes each ``PlanningRequest`` to the appropriate layer planner
    (L1/L2/L3) via a ``LayerRouter``, then dispatches by capability
    through a ``CapabilityRouter``.  Every invocation is tagged with a
    trace id for observability.

    If *register_defaults* is True (the default), real L1/L2/L3 planners
    are registered automatically.  Pass False and call
    ``register_layer_planner`` manually for testing.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        mode: str = "auto",
        *,
        register_defaults: bool = True,
        research_tool: Any = None,
        integration_tool: Any = None,
        evidence_tool: Any = None,
    ) -> None:
        self._workspace_root = Path(workspace_root)
        self._mode = mode
        self._layer_router = LayerRouter()
        self._capability_router = CapabilityRouter()

        if register_defaults:
            self._register_default_planners(
                research_tool=research_tool,
                integration_tool=integration_tool,
                evidence_tool=evidence_tool,
            )

    def _register_default_planners(
        self,
        research_tool: Any = None,
        integration_tool: Any = None,
        evidence_tool: Any = None,
    ) -> None:
        """Register real L1/L2/L3 planners with injected tools."""
        from spec_manager.planner.layers.l1 import L1Planner
        from spec_manager.planner.layers.l2 import L2Planner
        from spec_manager.planner.layers.l3 import L3Planner

        self._layer_router.register(
            "l1",
            L1Planner(
                research_tool=research_tool,
                integration_tool=integration_tool,
                evidence_tool=evidence_tool,
            ),
        )
        self._layer_router.register(
            "l2",
            L2Planner(
                research_tool=research_tool,
                integration_tool=integration_tool,
                evidence_tool=evidence_tool,
            ),
        )
        self._layer_router.register(
            "l3",
            L3Planner(
                research_tool=research_tool,
                integration_tool=integration_tool,
                evidence_tool=evidence_tool,
            ),
        )

    def register_layer_planner(self, layer: str, planner: Any) -> None:
        """Register a custom planner for a layer (useful for testing)."""
        self._layer_router.register(layer, planner)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def plan(self, req: PlanningRequest) -> PlanningResult:
        """Route *req* to the correct layer planner and capability handler.

        Returns a ``PlanningResult`` with a unique ``trace_id`` for
        every invocation regardless of outcome.
        """
        trace_id = _new_trace_id()
        layer = req.context.layer

        logger.debug(
            "planner.plan  trace=%s  capability=%s  layer=%s  slice=%s",
            trace_id,
            req.capability,
            layer,
            req.context.slice_id,
        )

        try:
            planner = self._layer_router.select(layer)
            result = self._capability_router.route(planner, req)
            result.trace_id = trace_id
            return result
        except Exception as exc:
            logger.exception("planner.plan failed  trace=%s", trace_id)
            return PlanningResult(
                status="ERROR",
                trace_id=trace_id,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Convenience adapters for existing call sites
    # ------------------------------------------------------------------

    def resolve_signal(self, signal: Any, context: PlanningContext) -> Any:
        """Resolve an ambiguity signal.

        Returns the layer planner's response (typically a dict or None).
        """
        context.signal_ref = signal
        req = PlanningRequest(
            capability="RESOLVE_SIGNAL",
            context=context,
            inputs={"signal": signal},
        )
        result = self.plan(req)
        return result.outputs.get("response")

    def plan_from_gaps(
        self, context: PlanningContext, gaps: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Generate plan intentions from a gap list.

        Returns a list of intention dicts (may be empty on NOOP).
        """
        req = PlanningRequest(
            capability="PLAN",
            context=context,
            inputs={"gaps": gaps},
        )
        result = self.plan(req)
        return result.outputs.get("intentions", [])

    def resolve_under_spec(
        self, context: PlanningContext, events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Resolve or block under-spec events.

        Returns a dict with ``blocked`` (bool) and ``constraints`` keys.
        """
        req = PlanningRequest(
            capability="UNDER_SPEC",
            context=context,
            inputs={"events": events},
        )
        result = self.plan(req)
        return result.outputs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_trace_id() -> str:
    """Return a short unique trace identifier."""
    return uuid.uuid4().hex[:12]
