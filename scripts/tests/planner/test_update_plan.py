"""Tests for scripts/planner/update_plan.py - UpdatePlanStateMachine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from scripts.planner.update_plan import UpdatePlanStateMachine


class TestComputeUpdateSummary:
    """Tests for UpdatePlanStateMachine._compute_update_summary."""

    def _create_mock_state(
        self,
        history: list[dict] | None = None,
        comments: list | None = None,
        update_source: str | None = None,
        update_prompt_text: str | None = None,
        latest_test_replanning_count: int = 0,
        latest_replanned_tests: list[dict] | None = None,
    ) -> MagicMock:
        """Create a mock DesignState with specified attributes.

        Note: latest_test_replanning_count defaults to 0 to match the real
        DesignState behavior where this field is always populated upstream.
        """
        state = MagicMock()
        state.history = history or []
        state.comments = comments or []
        state.update_source = update_source
        state.update_prompt_text = update_prompt_text
        state.latest_test_replanning_count = latest_test_replanning_count
        state.latest_replanned_tests = latest_replanned_tests or []
        state.workspace = Path("/tmp/test")
        return state

    def test_uses_latest_test_replanning_count_from_state(self) -> None:
        """Test that test_plans_updated uses latest_test_replanning_count from state."""
        state = self._create_mock_state(
            latest_test_replanning_count=7,
            latest_replanned_tests=[{"id": "test-1"}],
        )
        machine = UpdatePlanStateMachine(state)

        result = machine._compute_update_summary()

        assert result["test_plans_updated"] == 7
        assert result["replanned_tests"] == [{"id": "test-1"}]

    def test_returns_zero_when_latest_test_replanning_count_is_zero(self) -> None:
        """Test that test_plans_updated is 0 when latest_test_replanning_count is 0."""
        state = self._create_mock_state(latest_test_replanning_count=0)
        machine = UpdatePlanStateMachine(state)

        result = machine._compute_update_summary()

        assert result["test_plans_updated"] == 0

    def test_uses_direct_access_for_latest_test_replanning_count(self) -> None:
        """Test that latest_test_replanning_count is accessed directly from state.

        Since latest_test_replanning_count is a declared DesignState field with
        default=0, no defensive getattr/isinstance handling is needed.
        The field is always an int at runtime due to DesignState._from_dict
        providing integer defaults during YAML loading.
        """
        state = self._create_mock_state(latest_test_replanning_count=5)
        machine = UpdatePlanStateMachine(state)

        result = machine._compute_update_summary()

        assert result["test_plans_updated"] == 5
