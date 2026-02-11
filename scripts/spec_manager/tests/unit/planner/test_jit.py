"""Tests for spec_manager.planner.jit — state machine and actions."""

from __future__ import annotations

from typing import Any

import pytest
from spec_manager.planner.jit.actions import ActionType, NextAction
from spec_manager.planner.jit.state_machine import (
    PlannerStateMachine,
    PlanPhase,
    PlanStatus,
)

# ---------------------------------------------------------------------------
# PlannerStateMachine
# ---------------------------------------------------------------------------


class TestPlannerStateMachine:
    def test_state_machine_initial_state(self) -> None:
        sm = PlannerStateMachine()
        assert sm.phase == PlanPhase.INIT
        assert sm.status == PlanStatus.RUNNING
        assert sm.history == []

    def test_state_machine_advance(self) -> None:
        sm = PlannerStateMachine()
        sm.advance(PlanPhase.DISCOVER)
        assert sm.phase == PlanPhase.DISCOVER
        assert sm.status == PlanStatus.RUNNING
        assert len(sm.history) == 1
        assert sm.history[0]["from_phase"] == "init"
        assert sm.history[0]["to_phase"] == "discover"

        sm.advance(PlanPhase.GAP_UNDERSTANDING)
        assert sm.phase == PlanPhase.GAP_UNDERSTANDING
        assert len(sm.history) == 2

        sm.advance(PlanPhase.RESEARCH)
        assert sm.phase == PlanPhase.RESEARCH
        assert len(sm.history) == 3

    def test_state_machine_block(self) -> None:
        sm = PlannerStateMachine()
        sm.advance(PlanPhase.DISCOVER)
        sm.block("missing arch files")
        assert sm.phase == PlanPhase.BLOCKED
        assert sm.status == PlanStatus.PAUSED
        assert len(sm.history) == 2
        assert sm.history[-1]["reason"] == "missing arch files"

    def test_state_machine_complete(self) -> None:
        sm = PlannerStateMachine()
        sm.advance(PlanPhase.VALIDATE)
        sm.complete()
        assert sm.phase == PlanPhase.COMPLETE
        assert sm.status == PlanStatus.COMPLETED
        assert len(sm.history) == 2
        assert sm.history[-1]["to_phase"] == "complete"

    def test_state_machine_error(self) -> None:
        sm = PlannerStateMachine()
        sm.error("something broke")
        assert sm.status == PlanStatus.ERROR
        # Phase stays at INIT since error doesn't change phase
        assert sm.phase == PlanPhase.INIT
        assert len(sm.history) == 1
        assert sm.history[0]["error"] == "something broke"

    def test_state_machine_to_dict(self) -> None:
        sm = PlannerStateMachine()
        sm.advance(PlanPhase.DISCOVER)
        sm.advance(PlanPhase.DESIGN)

        d = sm.to_dict()
        assert d["phase"] == "design"
        assert d["status"] == "running"
        assert isinstance(d["history"], list)
        assert len(d["history"]) == 2

    def test_state_machine_history_has_timestamps(self) -> None:
        sm = PlannerStateMachine()
        sm.advance(PlanPhase.DISCOVER)
        assert "timestamp" in sm.history[0]

    def test_state_machine_full_lifecycle(self) -> None:
        """Walk through a complete lifecycle: INIT -> DISCOVER -> GAP -> DESIGN -> VALIDATE -> COMPLETE."""
        sm = PlannerStateMachine()
        sm.advance(PlanPhase.DISCOVER)
        sm.advance(PlanPhase.GAP_UNDERSTANDING)
        sm.advance(PlanPhase.DESIGN)
        sm.advance(PlanPhase.VALIDATE)
        sm.complete()

        assert sm.phase == PlanPhase.COMPLETE
        assert sm.status == PlanStatus.COMPLETED
        assert len(sm.history) == 5


# ---------------------------------------------------------------------------
# PlanPhase and PlanStatus enums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_all_plan_phases(self) -> None:
        expected = {
            "INIT",
            "DISCOVER",
            "INTEGRATION_ANALYSIS",
            "GAP_UNDERSTANDING",
            "RESEARCH",
            "DESIGN",
            "VALIDATE",
            "COMPLETE",
            "BLOCKED",
        }
        actual = {p.name for p in PlanPhase}
        assert actual == expected

    def test_all_plan_statuses(self) -> None:
        expected = {"RUNNING", "PAUSED", "WAITING_INPUT", "COMPLETED", "ERROR"}
        actual = {s.name for s in PlanStatus}
        assert actual == expected


# ---------------------------------------------------------------------------
# ActionType and NextAction
# ---------------------------------------------------------------------------


class TestActionType:
    def test_next_action_types(self) -> None:
        """All ActionType values should construct without error."""
        for at in ActionType:
            action = NextAction(action=at)
            assert action.action is at

    def test_all_action_type_values(self) -> None:
        expected = {"CALL_AGENT", "RUN_TOOL", "USER_INPUT", "COMPLETE", "ERROR"}
        actual = {a.name for a in ActionType}
        assert actual == expected


class TestNextAction:
    def test_next_action_defaults(self) -> None:
        action = NextAction(action=ActionType.COMPLETE)
        assert action.agent == ""
        assert action.tool == ""
        assert action.inputs == {}
        assert action.prompt == ""

    def test_next_action_call_agent(self) -> None:
        action = NextAction(
            action=ActionType.CALL_AGENT,
            agent="gap_agent",
            inputs={"slice_id": "s1"},
        )
        assert action.action == ActionType.CALL_AGENT
        assert action.agent == "gap_agent"
        assert action.inputs["slice_id"] == "s1"

    def test_next_action_run_tool(self) -> None:
        action = NextAction(
            action=ActionType.RUN_TOOL,
            tool="evidence_search",
            inputs={"query": "netting"},
        )
        assert action.tool == "evidence_search"

    def test_next_action_user_input(self) -> None:
        action = NextAction(
            action=ActionType.USER_INPUT,
            prompt="What is the settlement frequency?",
        )
        assert action.prompt == "What is the settlement frequency?"

    def test_next_action_error(self) -> None:
        action = NextAction(
            action=ActionType.ERROR,
            prompt="Internal failure: timeout",
        )
        assert action.action == ActionType.ERROR

    def test_next_action_to_dict(self) -> None:
        action = NextAction(
            action=ActionType.CALL_AGENT,
            agent="plan_agent",
            inputs={"gaps": [1, 2]},
        )
        d = action.to_dict()
        assert d["action"] == "call_agent"
        assert d["agent"] == "plan_agent"
        assert d["tool"] == ""
        assert d["inputs"] == {"gaps": [1, 2]}
        assert d["prompt"] == ""

    def test_next_action_to_dict_complete(self) -> None:
        action = NextAction(action=ActionType.COMPLETE)
        d = action.to_dict()
        assert d["action"] == "complete"
        assert d["inputs"] == {}
