"""Tests for spec_manager.planner.api — core types and Planner class."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from spec_manager.planner.api import (
    Capability,
    Layer,
    Planner,
    PlanningContext,
    PlanningRequest,
    PlanningResult,
)
from spec_manager.planner.router import LayerPlanner

# ---------------------------------------------------------------------------
# Helpers — tiny mock planner that satisfies the LayerPlanner protocol
# ---------------------------------------------------------------------------


class _MockLayerPlanner:
    """Minimal LayerPlanner for routing tests."""

    def __init__(self, layer: str) -> None:
        self.layer = layer
        self.last_ctx: Any = None

    def discover(self, ctx: Any) -> dict[str, Any]:
        self.last_ctx = ctx
        return {"nodes": [], "edges": []}

    def build_plan(
        self, ctx: Any, gaps: list[dict[str, Any]], discovery: dict[str, Any]
    ) -> dict[str, Any]:
        self.last_ctx = ctx
        return {"intentions": [{"from": self.layer}]}

    def resolve_under_spec(
        self, ctx: Any, events: list[dict[str, Any]], discovery: dict[str, Any]
    ) -> dict[str, Any]:
        self.last_ctx = ctx
        return {"blocked": False, "constraints": {}}

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        self.last_ctx = ctx
        if signal is None:
            return None
        return {"resolved": True, "target": str(signal)}


# ---------------------------------------------------------------------------
# PlanningContext
# ---------------------------------------------------------------------------


class TestPlanningContext:
    def test_planning_context_defaults(self) -> None:
        ctx = PlanningContext()
        assert ctx.run_id == ""
        assert ctx.slice_id == ""
        assert ctx.iteration == 0
        assert ctx.layer == "any"
        assert ctx.mode == "auto"
        assert ctx.workspace_root == ""
        assert ctx.slice_root == ""
        assert ctx.bundle_ref is None
        assert ctx.signal_ref is None
        assert ctx.metadata == {}


# ---------------------------------------------------------------------------
# PlanningRequest
# ---------------------------------------------------------------------------


class TestPlanningRequest:
    def test_planning_request_creation(self) -> None:
        ctx = PlanningContext(layer="l1", run_id="run-1")
        req = PlanningRequest(
            capability="GAP",
            context=ctx,
            inputs={"foo": "bar"},
        )
        assert req.capability == "GAP"
        assert req.context is ctx
        assert req.inputs == {"foo": "bar"}
        assert req.constraints_hint is None


# ---------------------------------------------------------------------------
# PlanningResult
# ---------------------------------------------------------------------------


class TestPlanningResult:
    def test_planning_result_statuses(self) -> None:
        for status in ("OK", "BLOCKED", "NEEDS_INPUT", "NOOP", "ERROR"):
            result = PlanningResult(status=status)
            assert result.status == status
            assert result.outputs == {}
            assert result.trace_id == ""
            assert result.error == ""


# ---------------------------------------------------------------------------
# Planner routing
# ---------------------------------------------------------------------------


class TestPlannerRouting:
    def _make_planner(self, tmp_path: Any) -> tuple[Planner, dict[str, _MockLayerPlanner]]:
        """Build a Planner with mock layer planners for each layer."""
        planner = Planner(workspace_root=tmp_path, register_defaults=False)
        mocks: dict[str, _MockLayerPlanner] = {}
        for layer in ("l1", "l2", "l3"):
            mock = _MockLayerPlanner(layer)
            planner.register_layer_planner(layer, mock)
            mocks[layer] = mock
        return planner, mocks

    def test_planner_routes_to_correct_layer(self, tmp_path: Any) -> None:
        planner, mocks = self._make_planner(tmp_path)

        for layer in ("l1", "l2", "l3"):
            ctx = PlanningContext(layer=layer, slice_id=f"slice-{layer}")
            req = PlanningRequest(capability="GAP", context=ctx)
            result = planner.plan(req)
            assert result.status == "OK"
            assert mocks[layer].last_ctx is ctx

    def test_planner_routes_any_to_l1(self, tmp_path: Any) -> None:
        planner, mocks = self._make_planner(tmp_path)
        ctx = PlanningContext(layer="any", slice_id="slice-any")
        req = PlanningRequest(capability="GAP", context=ctx)
        result = planner.plan(req)
        assert result.status == "OK"
        assert mocks["l1"].last_ctx is ctx

    def test_planner_plan_returns_trace_id(self, tmp_path: Any) -> None:
        planner, _ = self._make_planner(tmp_path)
        ctx = PlanningContext(layer="l1")
        req = PlanningRequest(capability="GAP", context=ctx)
        result = planner.plan(req)
        assert result.trace_id != ""
        assert len(result.trace_id) == 12  # uuid hex[:12]

    def test_planner_error_handling(self, tmp_path: Any) -> None:
        planner = Planner(workspace_root=tmp_path, register_defaults=False)

        class _RaisingPlanner(_MockLayerPlanner):
            def discover(self, ctx: Any) -> dict[str, Any]:
                raise RuntimeError("boom")

        planner.register_layer_planner("l1", _RaisingPlanner("l1"))
        ctx = PlanningContext(layer="l1")
        req = PlanningRequest(capability="GAP", context=ctx)
        result = planner.plan(req)
        assert result.status == "ERROR"
        assert "boom" in result.error
        assert result.trace_id != ""


# ---------------------------------------------------------------------------
# Planner convenience methods
# ---------------------------------------------------------------------------


class TestPlannerConvenience:
    def _make_planner(self, tmp_path: Any) -> Planner:
        planner = Planner(workspace_root=tmp_path, register_defaults=False)
        planner.register_layer_planner("l1", _MockLayerPlanner("l1"))
        planner.register_layer_planner("l2", _MockLayerPlanner("l2"))
        planner.register_layer_planner("l3", _MockLayerPlanner("l3"))
        return planner

    def test_planner_resolve_signal(self, tmp_path: Any) -> None:
        planner = self._make_planner(tmp_path)
        ctx = PlanningContext(layer="l1")
        response = planner.resolve_signal({"target": "foo"}, ctx)
        assert response is not None
        assert response["resolved"] is True

    def test_planner_resolve_signal_none(self, tmp_path: Any) -> None:
        planner = self._make_planner(tmp_path)
        ctx = PlanningContext(layer="l1")
        response = planner.resolve_signal(None, ctx)
        assert response is None

    def test_planner_plan_from_gaps(self, tmp_path: Any) -> None:
        planner = self._make_planner(tmp_path)
        ctx = PlanningContext(layer="l1")
        gaps = [{"target": "f1", "description": "missing impl"}]
        intentions = planner.plan_from_gaps(ctx, gaps)
        assert isinstance(intentions, list)
        # The mock build_plan returns [{"from": "l1"}]
        assert len(intentions) == 1
        assert intentions[0]["from"] == "l1"

    def test_planner_resolve_under_spec(self, tmp_path: Any) -> None:
        planner = self._make_planner(tmp_path)
        ctx = PlanningContext(layer="l2")
        events = [{"target": "comp-A", "question": "what scope?"}]
        result = planner.resolve_under_spec(ctx, events)
        assert isinstance(result, dict)
        assert result["blocked"] is False


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestPlannerRegistration:
    def test_planner_register_custom_planner(self, tmp_path: Any) -> None:
        planner = Planner(workspace_root=tmp_path, register_defaults=False)
        custom = _MockLayerPlanner("l2")
        planner.register_layer_planner("l2", custom)
        ctx = PlanningContext(layer="l2")
        req = PlanningRequest(capability="GAP", context=ctx)
        result = planner.plan(req)
        assert result.status == "OK"
        assert custom.last_ctx is ctx

    def test_planner_register_defaults(self, tmp_path: Any) -> None:
        planner = Planner(workspace_root=tmp_path, register_defaults=True)
        # Verify that L1/L2/L3 planners are registered by routing to each
        for layer in ("l1", "l2", "l3"):
            ctx = PlanningContext(layer=layer)
            req = PlanningRequest(capability="GAP", context=ctx)
            result = planner.plan(req)
            assert result.status == "OK"
