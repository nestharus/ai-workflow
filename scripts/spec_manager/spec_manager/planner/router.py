"""Layer and capability routing for the planner module.

LayerRouter selects the correct per-layer planner (L1/L2/L3) based on
the request's layer field.  CapabilityRouter dispatches within a layer
planner to the appropriate method based on the request's capability.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Re-use the type aliases from the api module at runtime; we define the
# same literals here to avoid a circular import (api imports router).
Layer = Literal["l1", "l2", "l3", "any"]


# ---------------------------------------------------------------------------
# LayerPlanner protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LayerPlanner(Protocol):
    """Protocol that every per-layer planner must satisfy."""

    layer: Layer

    def discover(self, ctx: Any) -> dict[str, Any]:
        """Gather layer-specific discovery data for the slice."""
        ...

    def build_plan(
        self, ctx: Any, gaps: list[dict[str, Any]], discovery: dict[str, Any]
    ) -> dict[str, Any]:
        """Synthesize plan intentions from gaps + discovery."""
        ...

    def resolve_under_spec(
        self, ctx: Any, events: list[dict[str, Any]], discovery: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve or block under-spec events."""
        ...

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        """Resolve an ambiguity signal.  May return None for no-op."""
        ...

    def triage_signal(self, ctx: Any, signal: dict[str, Any]) -> dict[str, Any]:
        """Triage a coordination signal — search work items, classify, route."""
        ...


# ---------------------------------------------------------------------------
# Stub layer planners (NOOP — filled in by layer modules later)
# ---------------------------------------------------------------------------


class _StubPlanner:
    """Placeholder layer planner that returns NOOP for every operation."""

    def __init__(self, layer: Layer) -> None:
        self.layer: Layer = layer

    def discover(self, ctx: Any) -> dict[str, Any]:
        return {}

    def build_plan(
        self, ctx: Any, gaps: list[dict[str, Any]], discovery: dict[str, Any]
    ) -> dict[str, Any]:
        return {"intentions": []}

    def resolve_under_spec(
        self, ctx: Any, events: list[dict[str, Any]], discovery: dict[str, Any]
    ) -> dict[str, Any]:
        return {"blocked": False, "constraints": {}}

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        return None

    def triage_signal(self, ctx: Any, signal: dict[str, Any]) -> dict[str, Any]:
        return {"action": "NOOP", "monitors": []}


# ---------------------------------------------------------------------------
# LayerRouter
# ---------------------------------------------------------------------------


class LayerRouter:
    """Routes planning requests to the appropriate layer planner.

    Each layer (l1/l2/l3) has a registered ``LayerPlanner``.  Requesting
    ``"any"`` returns the L1 planner as the default.
    """

    def __init__(self) -> None:
        self._planners: dict[Layer, LayerPlanner] = {
            "l1": _StubPlanner("l1"),
            "l2": _StubPlanner("l2"),
            "l3": _StubPlanner("l3"),
        }

    def register(self, layer: Layer, planner: LayerPlanner) -> None:
        """Replace the stub planner for *layer* with a real implementation."""
        if layer == "any":
            raise ValueError("Cannot register a planner for 'any'; use a concrete layer.")
        self._planners[layer] = planner

    def select(self, layer: Layer) -> LayerPlanner:
        """Return the planner for *layer*.  ``"any"`` resolves to L1."""
        if layer == "any":
            return self._planners["l1"]
        planner = self._planners.get(layer)
        if planner is None:
            raise ValueError(f"No planner registered for layer {layer!r}")
        return planner


# ---------------------------------------------------------------------------
# CapabilityRouter
# ---------------------------------------------------------------------------


class CapabilityRouter:
    """Routes within a layer planner based on capability."""

    def route(self, planner: LayerPlanner, req: Any) -> Any:
        """Dispatch *req* to the correct method on *planner*.

        Returns a ``PlanningResult`` (imported lazily to avoid circular deps).
        """
        # Lazy import to avoid circular reference (api -> router -> api).
        from spec_manager.planner.api import PlanningResult

        capability = req.capability
        ctx = req.context
        inputs = req.inputs

        if capability == "RESOLVE_SIGNAL":
            signal = inputs.get("signal")
            response = planner.resolve_signal(ctx, signal)
            if response is None:
                return PlanningResult(status="NOOP", outputs={})
            return PlanningResult(status="OK", outputs={"response": response})

        if capability == "GAP":
            discovery = planner.discover(ctx)
            return PlanningResult(status="OK", outputs={"discovery": discovery})

        if capability == "PLAN":
            gaps = inputs.get("gaps", [])
            discovery = planner.discover(ctx)
            plan = planner.build_plan(ctx, gaps, discovery)
            outputs: dict[str, Any] = {"intentions": plan.get("intentions", [])}
            # Forward strategy pipeline outputs when present
            for key in (
                "decision_requirements",
                "new_constraints",
                "under_spec_events",
                "decision_outcomes",
            ):
                if key in plan:
                    outputs[key] = plan[key]
            return PlanningResult(status="OK", outputs=outputs)

        if capability == "UNDER_SPEC":
            events = inputs.get("events", [])
            discovery = planner.discover(ctx)
            result = planner.resolve_under_spec(ctx, events, discovery)
            blocked = result.get("blocked", False)
            status = "BLOCKED" if blocked else "OK"
            return PlanningResult(status=status, outputs=result)

        if capability == "INTEGRATION_ANALYSIS":
            discovery = planner.discover(ctx)
            return PlanningResult(status="OK", outputs={"discovery": discovery})

        if capability == "TRIAGE_SIGNAL":
            signal = inputs.get("signal", {})
            triage_result = planner.triage_signal(ctx, signal)
            action = triage_result.get("action", "NOOP")
            status = "WAITING" if action != "NOOP" else "NOOP"
            return PlanningResult(status=status, outputs=triage_result)

        return PlanningResult(
            status="ERROR",
            error=f"Unknown capability: {capability!r}",
        )
