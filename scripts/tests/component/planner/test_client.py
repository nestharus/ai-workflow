"""Tests for scripts/planner/client.py - _get_state_machine helper."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from scripts.planner.client import _get_state_machine
from scripts.planner.state import DesignState


class TestGetStateMachine:
    """Tests for _get_state_machine helper function."""

    def _create_state_with_workflow(self, workflow: str) -> DesignState:
        """Create a minimal DesignState with the given workflow."""
        state = MagicMock(spec=DesignState)
        state.workflow = workflow
        return state

    def test_create_plan_workflow_returns_create_plan_state_machine(self) -> None:
        """Test that 'create-plan' workflow returns CreatePlanStateMachine."""
        from scripts.planner.create_plan import CreatePlanStateMachine

        state = self._create_state_with_workflow("create-plan")
        machine = _get_state_machine(state)
        assert isinstance(machine, CreatePlanStateMachine)

    def test_update_plan_workflow_returns_update_plan_state_machine(self) -> None:
        """Test that 'update-plan' workflow returns UpdatePlanStateMachine."""
        from scripts.planner.update_plan import UpdatePlanStateMachine

        state = self._create_state_with_workflow("update-plan")
        machine = _get_state_machine(state)
        assert isinstance(machine, UpdatePlanStateMachine)

    def test_analyze_workflow_returns_analyze_state_machine(self) -> None:
        """Test that 'analyze' workflow returns AnalyzeStateMachine."""
        from scripts.planner.analyze import AnalyzeStateMachine

        state = self._create_state_with_workflow("analyze")
        machine = _get_state_machine(state)
        assert isinstance(machine, AnalyzeStateMachine)

    def test_refactor_plan_workflow_returns_refactor_plan_state_machine(self) -> None:
        """Test that 'refactor-plan' workflow returns RefactorPlanStateMachine."""
        from scripts.planner.refactor_plan import RefactorPlanStateMachine

        state = self._create_state_with_workflow("refactor-plan")
        machine = _get_state_machine(state)
        assert isinstance(machine, RefactorPlanStateMachine)

    def test_unknown_workflow_raises_value_error(self) -> None:
        """Test that unknown workflow raises ValueError with helpful message."""
        state = self._create_state_with_workflow("unknown-workflow")

        with pytest.raises(ValueError) as exc_info:
            _get_state_machine(state)

        error_message = str(exc_info.value)
        assert "Unknown workflow" in error_message
        assert "unknown-workflow" in error_message

    def test_empty_workflow_raises_value_error(self) -> None:
        """Test that empty workflow raises ValueError."""
        state = self._create_state_with_workflow("")

        with pytest.raises(ValueError) as exc_info:
            _get_state_machine(state)

        assert "Unknown workflow" in str(exc_info.value)
