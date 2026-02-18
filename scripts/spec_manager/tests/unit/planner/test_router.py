"""Tests for ``spec_manager.planner.router`` contracts."""

from __future__ import annotations

from typing import Any

import pytest
from spec_manager.planner.api import PlanningContext, PlanningRequest
from spec_manager.planner.jit.actions import ActionType
from spec_manager.planner.router import CapabilityRouter, LayerRouter


class _FakePlanner:
    """Minimal per-phase planner used by router tests."""

    def __init__(self, phase: str = "libraries") -> None:
        self.phase = phase
        self.discovery_router = object()
        self.skeleton_planner = object()
        self.layer_research_adapter = object()

    def bind_trace(self, trace: Any | None) -> None:
        self.trace = trace

    def discover(self, ctx: Any) -> dict[str, Any]:
        return {"phase": self.phase, "ctx_phase": str(getattr(ctx, "phase", ""))}

    def extract_skeleton(self, ctx: Any, discovery: dict[str, Any]) -> dict[str, Any]:
        return {"nodes": [{"id": "n1"}], "phase": self.phase}

    def build_plan(
        self, ctx: Any, gaps: list[dict[str, Any]], discovery: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "intentions": [{"phase": self.phase, "gap_count": len(gaps)}],
            "decision_requirements": [{"decision_id": "D-1"}],
        }

    def resolve_under_spec(
        self, ctx: Any, events: list[dict[str, Any]], discovery: dict[str, Any]
    ) -> dict[str, Any]:
        blocked = bool(events)
        return {"blocked": blocked, "questions": ["why?"] if blocked else []}

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        if signal is None:
            return None
        return {"resolved": True, "signal": signal}

    def triage_signal(self, ctx: Any, signal: dict[str, Any]) -> dict[str, Any]:
        return {"action": signal.get("action_hint", "NOOP"), "monitors": []}


def _make_request(capability: str, inputs: dict[str, Any] | None = None) -> PlanningRequest:
    return PlanningRequest(
        capability=capability,
        context=PlanningContext(phase="libraries"),
        inputs=inputs or {},
    )


def _run_actions(router: CapabilityRouter, planner: _FakePlanner, req: PlanningRequest) -> dict[str, Any]:
    interim: dict[str, Any] = {}
    for action in router.plan_actions(req):
        if action.action == ActionType.RUN_TOOL:
            router.run_tool(
                planner=planner,
                req=req,
                tool_name=str(action.tool),
                action_inputs=action.inputs,
                interim=interim,
            )
        elif action.action == ActionType.CALL_AGENT:
            router.run_agent(
                planner=planner,
                req=req,
                agent_name=str(action.agent),
                action_inputs=action.inputs,
                interim=interim,
            )
    return interim


class TestLayerRouter:
    def test_select_registered_phases_and_any_default(self) -> None:
        router = LayerRouter()
        libraries = _FakePlanner("libraries")
        architecture = _FakePlanner("architecture")
        quality = _FakePlanner("quality")

        router.register("libraries", libraries)
        router.register("architecture", architecture)
        router.register("quality", quality)

        assert router.select("libraries") is libraries
        assert router.select("architecture") is architecture
        assert router.select("quality") is quality
        assert router.select("any") is libraries

    def test_missing_registration_raises_value_error(self) -> None:
        router = LayerRouter()
        with pytest.raises(ValueError, match="No planner registered"):
            router.select("libraries")


class TestCapabilityRouter:
    def test_resolve_signal_with_none_yields_noop(self) -> None:
        router = CapabilityRouter()
        planner = _FakePlanner()
        req = _make_request("RESOLVE_SIGNAL", {"signal": None})

        interim = _run_actions(router, planner, req)
        result = router.finalize(req, interim)

        assert result.status == "NOOP"
        assert result.outputs == {}

    def test_gap_flow_builds_prioritized_outputs(self) -> None:
        router = CapabilityRouter()
        planner = _FakePlanner()
        req = _make_request(
            "GAP",
            {
                "raw_gaps": [
                    {"severity": "MINOR", "file": "z.py", "description": "later"},
                    {"severity": "BLOCKER", "file": "a.py", "description": "first"},
                    {"severity": "BLOCKER", "file": "a.py", "description": "first"},
                ]
            },
        )

        interim = _run_actions(router, planner, req)
        result = router.finalize(req, interim)

        assert result.status == "OK"
        assert len(result.outputs["gaps"]) == 2
        assert result.outputs["gaps"][0]["severity"] == "BLOCKER"

    def test_plan_flow_includes_layer_skeleton(self) -> None:
        router = CapabilityRouter()
        planner = _FakePlanner()
        req = _make_request("PLAN", {"gaps": [{"gap_id": "g-1"}]})

        interim = _run_actions(router, planner, req)
        result = router.finalize(req, interim)

        assert result.status == "OK"
        assert result.outputs["intentions"][0]["gap_count"] == 1
        assert "layer_skeleton" in result.outputs
        assert result.outputs["layer_skeleton"]["phase"] == "libraries"

    def test_triage_non_noop_yields_waiting(self) -> None:
        router = CapabilityRouter()
        planner = _FakePlanner()
        req = _make_request("TRIAGE_SIGNAL", {"signal": {"action_hint": "WAIT_ON_WORK_ITEM"}})

        interim = _run_actions(router, planner, req)
        result = router.finalize(req, interim)

        assert result.status == "WAITING"
        assert result.outputs["action"] == "WAIT_ON_WORK_ITEM"

    def test_unknown_capability_returns_error_action(self) -> None:
        router = CapabilityRouter()
        req = _make_request("NOT_A_CAPABILITY")

        actions = router.plan_actions(req)

        assert len(actions) == 1
        assert actions[0].action == ActionType.ERROR

    def test_resolve_signal_actions_include_research_when_needed(self) -> None:
        router = CapabilityRouter()
        req = _make_request("RESOLVE_SIGNAL")

        actions = router.plan_actions(req, requires_external_facts=True)

        assert actions[0].action == ActionType.RUN_TOOL
        assert actions[0].tool == "web_research"
