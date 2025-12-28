"""Tests for scripts/planner/analyze.py - AnalyzeStateMachine."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from scripts.planner.analyze import AnalyzeStateMachine


class TestProcessSkeletonAnalyzerOutputDuplicates:
    """Tests for _process_skeleton_analyzer_output duplicate prevention."""

    @pytest.fixture
    def mock_state(self, tmp_path: Path) -> MagicMock:
        """Create a mock DesignState with branches."""
        from scripts.planner.state import Branch, Unit

        state = MagicMock()
        state.workspace = tmp_path
        state.history = []
        state.phase = "skeleton_analysis"
        state.entry_points = []

        # Set up branches with a real Branch object
        main_branch = Branch(branch_id="main", layers={0: [], 1: []})
        state.branches = {"main": main_branch}

        # Set up root unit with real Unit
        root_unit = Unit(id="root", description="Root", operation="MODIFY")
        state.units = {"root": root_unit}

        return state

    @pytest.fixture
    def state_machine(self, mock_state: MagicMock) -> AnalyzeStateMachine:
        """Create AnalyzeStateMachine with mock state."""
        from scripts.planner.analyze import AnalyzeStateMachine

        return AnalyzeStateMachine(mock_state)

    def test_no_duplicates_when_run_multiple_times(
        self, state_machine: AnalyzeStateMachine, mock_state: MagicMock
    ) -> None:
        """Test that running skeleton analyzer twice doesn't create duplicates."""
        mock_state.read_agent_output.return_value = {
            "status": "success",
            "components": [
                {"id": "comp1", "description": "Component 1"},
            ],
        }

        # Run twice to simulate retry scenario
        state_machine._process_skeleton_analyzer_output()
        mock_state.phase = "skeleton_analysis"
        state_machine._process_skeleton_analyzer_output()

        # Should only have comp1 once in root.children
        assert mock_state.units["root"].children.count("comp1") == 1
        # Should only have comp1 once in layer 1
        assert mock_state.branches["main"].layers[1].count("comp1") == 1

    def test_multiple_components_no_duplicates(
        self, state_machine: AnalyzeStateMachine, mock_state: MagicMock
    ) -> None:
        """Test multiple components don't create duplicates on retry."""
        mock_state.read_agent_output.return_value = {
            "status": "success",
            "components": [
                {"id": "comp1", "description": "Component 1"},
                {"id": "comp2", "description": "Component 2"},
            ],
        }

        # Run twice
        state_machine._process_skeleton_analyzer_output()
        mock_state.phase = "skeleton_analysis"
        state_machine._process_skeleton_analyzer_output()

        # Each component should appear exactly once
        assert mock_state.units["root"].children.count("comp1") == 1
        assert mock_state.units["root"].children.count("comp2") == 1
        assert mock_state.branches["main"].layers[1].count("comp1") == 1
        assert mock_state.branches["main"].layers[1].count("comp2") == 1

    def test_entry_points_no_duplicates_across_components(
        self, state_machine: AnalyzeStateMachine, mock_state: MagicMock
    ) -> None:
        """Test that entry_points are deduplicated across components."""
        mock_state.read_agent_output.return_value = {
            "status": "success",
            "components": [
                {
                    "id": "comp1",
                    "description": "Component 1",
                    "entry_points": ["main.py", "utils.py"],
                },
                {
                    "id": "comp2",
                    "description": "Component 2",
                    "entry_points": ["main.py", "config.py"],  # main.py is duplicate
                },
            ],
        }

        state_machine._process_skeleton_analyzer_output()

        # Each entry point should appear exactly once
        assert mock_state.entry_points.count("main.py") == 1
        assert mock_state.entry_points.count("utils.py") == 1
        assert mock_state.entry_points.count("config.py") == 1
        assert len(mock_state.entry_points) == 3

    def test_entry_points_no_duplicates_on_retry(
        self, state_machine: AnalyzeStateMachine, mock_state: MagicMock
    ) -> None:
        """Test that entry_points aren't duplicated when analyzer runs twice."""
        mock_state.read_agent_output.return_value = {
            "status": "success",
            "components": [
                {
                    "id": "comp1",
                    "description": "Component 1",
                    "entry_points": ["main.py", "utils.py"],
                },
            ],
        }

        # Run twice
        state_machine._process_skeleton_analyzer_output()
        mock_state.phase = "skeleton_analysis"
        state_machine._process_skeleton_analyzer_output()

        # Entry points should not be duplicated
        assert mock_state.entry_points.count("main.py") == 1
        assert mock_state.entry_points.count("utils.py") == 1
        assert len(mock_state.entry_points) == 2


class TestProcessComponentAnalyzerOutputDuplicates:
    """Tests for _process_component_analyzer_output duplicate prevention."""

    @pytest.fixture
    def mock_state(self, tmp_path: Path) -> MagicMock:
        """Create a mock DesignState with branches and a component."""
        from scripts.planner.state import Branch, Unit

        state = MagicMock()
        state.workspace = tmp_path
        state.history = []
        state.phase = "component_analysis"

        # Set up branches with root at layer 0 and comp1 at layer 1
        main_branch = Branch(branch_id="main", layers={0: ["root"], 1: ["comp1"]})
        state.branches = {"main": main_branch}

        # Set up root unit and parent component unit with parent relationship
        root_unit = Unit(id="root", description="Root", operation="MODIFY", status="pending")
        comp_unit = Unit(
            id="comp1",
            description="Component 1",
            operation="MODIFY",
            status="pending",
            parent="root",
        )
        state.units = {"root": root_unit, "comp1": comp_unit}

        return state

    @pytest.fixture
    def state_machine(self, mock_state: MagicMock) -> AnalyzeStateMachine:
        """Create AnalyzeStateMachine with mock state."""
        from scripts.planner.analyze import AnalyzeStateMachine

        return AnalyzeStateMachine(mock_state)

    def test_no_duplicate_sub_units_on_retry(
        self, state_machine: AnalyzeStateMachine, mock_state: MagicMock
    ) -> None:
        """Test that sub-units aren't duplicated when analyzer runs twice."""
        mock_state.read_agent_output.return_value = {
            "status": "success",
            "analyzed_components": [
                {
                    "component_id": "comp1",
                    "patterns_used": [{"pattern": "builder", "pattern_category": "creation"}],
                    "capabilities": {"provided": [], "expected": []},
                    "decomposition_suggestion": {
                        "should_decompose": True,
                        "suggested_sub_units": [
                            {"description": "Sub unit 1"},
                        ],
                    },
                }
            ],
        }

        # Run the first time
        state_machine._process_component_analyzer_output()

        # Record state after first call
        comp1 = mock_state.units["comp1"]
        children_after_first = list(comp1.children)
        layer_2_after_first = list(mock_state.branches["main"].layers.get(2, []))

        # Run again to simulate retry scenario
        mock_state.phase = "component_analysis"
        state_machine._process_component_analyzer_output()

        # Verify the children list is unchanged (retry is a no-op)
        assert comp1.children == children_after_first
        # Verify layer 2 is unchanged
        layer_2_after_second = mock_state.branches["main"].layers.get(2, [])
        assert layer_2_after_second == layer_2_after_first

    def test_sub_units_placed_in_correct_layer(
        self, state_machine: AnalyzeStateMachine, mock_state: MagicMock
    ) -> None:
        """Test that sub-units are placed in parent_layer + 1, not always layer 1."""
        mock_state.read_agent_output.return_value = {
            "status": "success",
            "analyzed_components": [
                {
                    "component_id": "comp1",
                    "patterns_used": [{"pattern": "builder", "pattern_category": "creation"}],
                    "capabilities": {"provided": [], "expected": []},
                    "decomposition_suggestion": {
                        "should_decompose": True,
                        "suggested_sub_units": [
                            {"description": "Sub unit 1"},
                            {"description": "Sub unit 2"},
                        ],
                    },
                }
            ],
        }

        state_machine._process_component_analyzer_output()

        # comp1 is in layer 1 (parent is root at layer 0)
        # Sub-units should be in layer 2 (parent_layer + 1)
        layer_2 = mock_state.branches["main"].layers.get(2, [])
        assert "comp1.1" in layer_2
        assert "comp1.2" in layer_2

        # Layer 1 should still only contain comp1, not the sub-units
        layer_1 = mock_state.branches["main"].layers.get(1, [])
        assert "comp1.1" not in layer_1
        assert "comp1.2" not in layer_1

    def test_sub_unit_id_collision_avoidance(
        self, state_machine: AnalyzeStateMachine, mock_state: MagicMock
    ) -> None:
        """Test that sub-unit ID generation skips IDs that already exist."""
        from scripts.planner.state import Unit

        # Pre-populate comp1.1 as if a partial run happened
        existing_sub = Unit(
            id="comp1.1",
            description="Existing sub unit",
            operation="MODIFY",
            status="pending",
            parent="comp1",
        )
        mock_state.units["comp1.1"] = existing_sub
        mock_state.units["comp1"].children.append("comp1.1")

        mock_state.read_agent_output.return_value = {
            "status": "success",
            "analyzed_components": [
                {
                    "component_id": "comp1",
                    "patterns_used": [],
                    "capabilities": {"provided": [], "expected": []},
                    "decomposition_suggestion": {
                        "should_decompose": True,
                        "suggested_sub_units": [
                            {"description": "New sub unit A"},
                            {"description": "New sub unit B"},
                        ],
                    },
                }
            ],
        }

        state_machine._process_component_analyzer_output()

        # The new sub-units should get IDs .2 and .3, skipping .1
        assert "comp1.2" in mock_state.units
        assert "comp1.3" in mock_state.units
        assert mock_state.units["comp1.2"].description == "New sub unit A"
        assert mock_state.units["comp1.3"].description == "New sub unit B"
        # Original .1 should remain
        assert mock_state.units["comp1.1"].description == "Existing sub unit"

    def test_add_units_to_layer_called_once(
        self, state_machine: AnalyzeStateMachine, mock_state: MagicMock
    ) -> None:
        """Test that add_units_to_layer is called once with all new sub-IDs."""
        mock_state.read_agent_output.return_value = {
            "status": "success",
            "analyzed_components": [
                {
                    "component_id": "comp1",
                    "patterns_used": [],
                    "capabilities": {"provided": [], "expected": []},
                    "decomposition_suggestion": {
                        "should_decompose": True,
                        "suggested_sub_units": [
                            {"description": "Sub A"},
                            {"description": "Sub B"},
                            {"description": "Sub C"},
                        ],
                    },
                }
            ],
        }

        # Track calls to add_units_to_layer
        original_add = state_machine.layer_manager.add_units_to_layer
        add_calls: list[list[str]] = []

        def tracking_add(unit_ids: list[str], branch_id: str = "main") -> None:
            add_calls.append(unit_ids)
            original_add(unit_ids, branch_id)

        state_machine.layer_manager.add_units_to_layer = tracking_add

        state_machine._process_component_analyzer_output()

        # Should be called exactly once with all 3 sub-unit IDs
        assert len(add_calls) == 1
        assert len(add_calls[0]) == 3
        assert set(add_calls[0]) == {"comp1.1", "comp1.2", "comp1.3"}


class TestErrorPhaseHandling:
    """Tests for explicit error phase handling."""

    @pytest.fixture
    def mock_state(self, tmp_path: Path) -> MagicMock:
        """Create a mock DesignState in error phase."""
        from scripts.planner.state import Branch

        state = MagicMock()
        state.workspace = tmp_path
        state.history = []
        state.phase = "error"

        # Set up branches with a real Branch object
        main_branch = Branch(branch_id="main", layers={0: []})
        state.branches = {"main": main_branch}

        return state

    @pytest.fixture
    def state_machine(self, mock_state: MagicMock) -> AnalyzeStateMachine:
        """Create AnalyzeStateMachine with mock state."""
        from scripts.planner.analyze import AnalyzeStateMachine

        return AnalyzeStateMachine(mock_state)

    def test_error_phase_does_not_recurse(
        self, state_machine: AnalyzeStateMachine, mock_state: MagicMock
    ) -> None:
        """Test that error phase is handled explicitly and doesn't call _handle_error."""
        from scripts.planner.actions import ActionType

        # Call next_action when phase is already "error"
        state_machine.next_action()

        # Should write ERROR action, not "Unknown phase: error"
        mock_state.write_next_action.assert_called_once()
        call_args = mock_state.write_next_action.call_args
        assert call_args[0][0] == ActionType.ERROR
        # Message should indicate we're in error state, not "Unknown phase"
        assert "In error state" in call_args[1].get("message", "")

    def test_error_phase_does_not_change_phase(
        self, state_machine: AnalyzeStateMachine, mock_state: MagicMock
    ) -> None:
        """Test that error phase handling doesn't modify the phase."""
        initial_phase = mock_state.phase

        state_machine.next_action()

        # Phase should remain "error"
        assert mock_state.phase == initial_phase
        # save() should not have been called (no phase change)
        mock_state.save.assert_not_called()
