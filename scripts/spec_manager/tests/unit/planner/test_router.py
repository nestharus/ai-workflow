"""Tests for spec_manager.planner.router — LayerRouter and CapabilityRouter."""

from __future__ import annotations

from typing import Any

import pytest
from spec_manager.planner.api import PlanningContext, PlanningRequest, PlanningResult
from spec_manager.planner.router import (
    CapabilityRouter,
    LayerPlanner,
    LayerRouter,
    _StubPlanner,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakePlanner:
    """Minimal LayerPlanner for testing."""

    def __init__(self, layer: str) -> None:
        self.layer = layer

    def discover(self, ctx: Any) -> dict[str, Any]:
        return {"source": self.layer}

    def build_plan(
        self, ctx: Any, gaps: list[dict[str, Any]], discovery: dict[str, Any]
    ) -> dict[str, Any]:
        return {"intentions": [{"layer": self.layer, "gap_count": len(gaps)}]}

    def resolve_under_spec(
        self, ctx: Any, events: list[dict[str, Any]], discovery: dict[str, Any]
    ) -> dict[str, Any]:
        if events:
            return {"blocked": True, "constraints": {}, "questions": ["why?"]}
        return {"blocked": False, "constraints": {}}

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        if signal is None:
            return None
        return {"resolved": True}


# ---------------------------------------------------------------------------
# LayerRouter
# ---------------------------------------------------------------------------


class TestLayerRouter:
    def test_layer_router_select_l1_l2_l3(self) -> None:
        router = LayerRouter()
        for layer in ("l1", "l2", "l3"):
            fake = _FakePlanner(layer)
            router.register(layer, fake)
            selected = router.select(layer)
            assert selected is fake

    def test_layer_router_select_any_returns_l1(self) -> None:
        router = LayerRouter()
        fake_l1 = _FakePlanner("l1")
        router.register("l1", fake_l1)
        selected = router.select("any")
        assert selected is fake_l1

    def test_layer_router_register_replaces_stub(self) -> None:
        router = LayerRouter()
        # Initially has stubs
        stub = router.select("l2")
        assert isinstance(stub, _StubPlanner)

        # Register a real planner
        real = _FakePlanner("l2")
        router.register("l2", real)
        selected = router.select("l2")
        assert selected is real
        assert not isinstance(selected, _StubPlanner)

    def test_layer_router_register_any_raises(self) -> None:
        router = LayerRouter()
        with pytest.raises(ValueError, match="Cannot register.*'any'"):
            router.register("any", _FakePlanner("any"))


# ---------------------------------------------------------------------------
# CapabilityRouter
# ---------------------------------------------------------------------------


class TestCapabilityRouter:
    def _make_request(
        self,
        capability: str,
        inputs: dict[str, Any] | None = None,
    ) -> PlanningRequest:
        ctx = PlanningContext(layer="l1")
        return PlanningRequest(
            capability=capability,
            context=ctx,
            inputs=inputs or {},
        )

    def test_capability_router_resolve_signal(self) -> None:
        router = CapabilityRouter()
        planner = _FakePlanner("l1")
        req = self._make_request("RESOLVE_SIGNAL", {"signal": {"target": "x"}})
        result = router.route(planner, req)
        assert isinstance(result, PlanningResult)
        assert result.status == "OK"
        assert result.outputs["response"]["resolved"] is True

    def test_capability_router_resolve_signal_noop(self) -> None:
        router = CapabilityRouter()
        planner = _FakePlanner("l1")
        req = self._make_request("RESOLVE_SIGNAL", {"signal": None})
        result = router.route(planner, req)
        assert result.status == "NOOP"
        assert result.outputs == {}

    def test_capability_router_gap(self) -> None:
        router = CapabilityRouter()
        planner = _FakePlanner("l1")
        req = self._make_request("GAP")
        result = router.route(planner, req)
        assert result.status == "OK"
        assert "discovery" in result.outputs
        assert result.outputs["discovery"]["source"] == "l1"

    def test_capability_router_plan(self) -> None:
        router = CapabilityRouter()
        planner = _FakePlanner("l1")
        req = self._make_request("PLAN", {"gaps": [{"id": "g1"}, {"id": "g2"}]})
        result = router.route(planner, req)
        assert result.status == "OK"
        assert "intentions" in result.outputs
        intentions = result.outputs["intentions"]
        assert len(intentions) == 1
        assert intentions[0]["gap_count"] == 2

    def test_capability_router_under_spec_blocked(self) -> None:
        router = CapabilityRouter()
        planner = _FakePlanner("l1")
        req = self._make_request("UNDER_SPEC", {"events": [{"target": "x"}]})
        result = router.route(planner, req)
        assert result.status == "BLOCKED"
        assert result.outputs["blocked"] is True

    def test_capability_router_under_spec_ok(self) -> None:
        router = CapabilityRouter()
        planner = _FakePlanner("l1")
        req = self._make_request("UNDER_SPEC", {"events": []})
        result = router.route(planner, req)
        assert result.status == "OK"
        assert result.outputs["blocked"] is False

    def test_capability_router_integration_analysis(self) -> None:
        router = CapabilityRouter()
        planner = _FakePlanner("l1")
        req = self._make_request("INTEGRATION_ANALYSIS")
        result = router.route(planner, req)
        assert result.status == "OK"
        assert "discovery" in result.outputs

    def test_capability_router_unknown_capability(self) -> None:
        router = CapabilityRouter()
        planner = _FakePlanner("l1")
        req = self._make_request("NONEXISTENT_CAPABILITY")
        result = router.route(planner, req)
        assert result.status == "ERROR"
        assert "Unknown capability" in result.error
