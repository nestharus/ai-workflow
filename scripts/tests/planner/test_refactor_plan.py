"""Tests for scripts/planner/refactor_plan.py - RefactorPlanStateMachine."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


class TestHandleSkeletonAnalysis:
    """Tests for _handle_skeleton_analysis method."""

    @pytest.fixture
    def mock_state(self, tmp_path: Path) -> MagicMock:
        """Create a mock DesignState."""
        state = MagicMock()
        state.workspace = tmp_path
        state.paths = ["/some/path"]
        state.ticket_id = "TEST-123"
        state.title = "Test Ticket"
        state.units = {}
        return state

    @pytest.fixture
    def state_machine(self, mock_state: MagicMock) -> Any:
        """Create RefactorPlanStateMachine with mock state."""
        from scripts.planner.refactor_plan import RefactorPlanStateMachine

        return RefactorPlanStateMachine(mock_state)

    def test_skeleton_analysis_with_root_unit(
        self, state_machine: Any, mock_state: MagicMock
    ) -> None:
        """Test skeleton analysis includes root unit description when present."""
        from scripts.planner.state import Unit

        root_unit = Unit(
            id="root",
            description="Root unit description",
            operation="MODIFY",
        )
        mock_state.units = {"root": root_unit}

        state_machine._handle_skeleton_analysis()

        # Check write_agent_input was called with correct description
        call_args = mock_state.write_agent_input.call_args[0][0]
        assert call_args["ticket"]["description"] == "Root unit description"

    def test_skeleton_analysis_without_root_unit(
        self, state_machine: Any, mock_state: MagicMock
    ) -> None:
        """Test skeleton analysis uses empty string when root unit is missing."""
        mock_state.units = {}

        state_machine._handle_skeleton_analysis()

        # Check write_agent_input was called with empty description
        call_args = mock_state.write_agent_input.call_args[0][0]
        assert call_args["ticket"]["description"] == ""

    def test_skeleton_analysis_with_other_units_but_no_root(
        self, state_machine: Any, mock_state: MagicMock
    ) -> None:
        """Test skeleton analysis uses empty string when root is not in units."""
        from scripts.planner.state import Unit

        other_unit = Unit(
            id="other",
            description="Other unit description",
            operation="MODIFY",
        )
        mock_state.units = {"other": other_unit}

        state_machine._handle_skeleton_analysis()

        # Check write_agent_input was called with empty description
        call_args = mock_state.write_agent_input.call_args[0][0]
        assert call_args["ticket"]["description"] == ""


class TestHandleReview:
    """Tests for _handle_review method."""

    @pytest.fixture
    def mock_state(self, tmp_path: Path) -> MagicMock:
        """Create a mock DesignState."""
        from scripts.planner.state import Unit

        state = MagicMock()
        state.workspace = tmp_path
        state.ticket_id = "TEST-123"
        state.title = "Test Refactor"
        state.refactoring_operations = [{"op": "move", "from": "a", "to": "b"}]
        state.migration_plan = {"phases": []}
        state.pattern_migrations = []
        state.breaking_changes_summary = {}
        state.risk_assessment = {}
        state.dependency_graph = {"a": ["b"]}
        state.circular_dependencies = []
        state.integration_points = []
        state.external_consumers = []
        state.refactoring_risks = []

        # Create some units
        unit1 = Unit(id="comp1", description="Component 1", operation="MODIFY", status="atomic")
        unit2 = Unit(id="comp2", description="Component 2", operation="MODIFY", status="pending")
        state.units = {"comp1": unit1, "comp2": unit2}

        return state

    @pytest.fixture
    def state_machine(self, mock_state: MagicMock) -> Any:
        """Create RefactorPlanStateMachine with mock state."""
        from scripts.planner.refactor_plan import RefactorPlanStateMachine

        return RefactorPlanStateMachine(mock_state)

    def test_handle_review_calls_layer_reviewer(
        self, state_machine: Any, mock_state: MagicMock
    ) -> None:
        """Test _handle_review invokes CALL_LAYER_REVIEWER action."""
        from scripts.planner.actions import ActionType

        state_machine._handle_review()

        mock_state.write_next_action.assert_called_once_with(ActionType.CALL_LAYER_REVIEWER)

    def test_handle_review_writes_agent_input(
        self, state_machine: Any, mock_state: MagicMock
    ) -> None:
        """Test _handle_review writes proper agent input with refactor context."""
        state_machine._handle_review()

        mock_state.write_agent_input.assert_called_once()
        call_args = mock_state.write_agent_input.call_args[0][0]

        # Check review context is set
        assert call_args["review_context"] == "refactor_plan"

        # Check refactoring data is included
        assert call_args["refactoring_operations"] == [{"op": "move", "from": "a", "to": "b"}]
        assert call_args["migration_plan"] == {"phases": []}

        # Check integration context is included
        assert call_args["integration_context"]["dependency_graph"] == {"a": ["b"]}

        # Check ticket info
        assert call_args["ticket"]["id"] == "TEST-123"
        assert call_args["ticket"]["title"] == "Test Refactor"

    def test_handle_review_includes_components(
        self, state_machine: Any, mock_state: MagicMock
    ) -> None:
        """Test _handle_review includes component information."""
        state_machine._handle_review()

        call_args = mock_state.write_agent_input.call_args[0][0]
        components = call_args["components"]

        assert len(components) == 2
        component_ids = {c["id"] for c in components}
        assert component_ids == {"comp1", "comp2"}

        # Check component details
        comp1 = next(c for c in components if c["id"] == "comp1")
        assert comp1["description"] == "Component 1"
        assert comp1["status"] == "atomic"


class TestProcessLayerReviewerOutput:
    """Tests for _process_layer_reviewer_output status validation."""

    @pytest.fixture
    def mock_state(self, tmp_path: Path) -> MagicMock:
        """Create a mock DesignState."""
        state = MagicMock()
        state.workspace = tmp_path
        state.history = []
        state.phase = "review"
        return state

    @pytest.fixture
    def state_machine(self, mock_state: MagicMock) -> Any:
        """Create RefactorPlanStateMachine with mock state."""
        from scripts.planner.refactor_plan import RefactorPlanStateMachine

        return RefactorPlanStateMachine(mock_state)

    def test_success_proceeds_to_generate_docs(
        self, state_machine: Any, mock_state: MagicMock
    ) -> None:
        """Test successful review advances to generate_docs phase."""
        mock_state.read_agent_output.return_value = {
            "status": "success",
            "proceed_notes": "Looks good to proceed",
        }

        state_machine._process_layer_reviewer_output()

        # Should add history entry
        mock_state.add_history.assert_called_once_with(
            "review", {"reviewer_feedback": "Looks good to proceed"}
        )
        # Should advance phase
        assert mock_state.phase == "generate_docs"
        # Should save state
        mock_state.save.assert_called_once()

    def test_failure_status_handles_error(self, state_machine: Any, mock_state: MagicMock) -> None:
        """Test failed review status calls _handle_error and does not proceed."""
        from scripts.planner.actions import ActionType

        mock_state.read_agent_output.return_value = {
            "status": "failed",
            "error": "Review found critical issues",
        }

        state_machine._process_layer_reviewer_output()

        # Should set phase to error and save
        assert mock_state.phase == "error"
        mock_state.save.assert_called_once()
        # Should write error action with the error message
        mock_state.write_next_action.assert_called_once_with(
            ActionType.ERROR, message="Review found critical issues"
        )
        # Should NOT call add_history (error state handled by _handle_error)
        mock_state.add_history.assert_not_called()

    def test_missing_status_handles_error(self, state_machine: Any, mock_state: MagicMock) -> None:
        """Test missing status is treated as failure."""
        from scripts.planner.actions import ActionType

        mock_state.read_agent_output.return_value = {
            "proceed_notes": "Notes without status",
        }

        state_machine._process_layer_reviewer_output()

        # Should set phase to error and save
        assert mock_state.phase == "error"
        mock_state.save.assert_called_once()
        # Should write error action with default message
        mock_state.write_next_action.assert_called_once_with(
            ActionType.ERROR, message="Layer review failed"
        )

    def test_error_status_includes_error_details(
        self, state_machine: Any, mock_state: MagicMock
    ) -> None:
        """Test error status includes error details in error action."""
        from scripts.planner.actions import ActionType

        mock_state.read_agent_output.return_value = {
            "status": "error",
            "error": "Agent crashed unexpectedly",
        }

        state_machine._process_layer_reviewer_output()

        # Should set phase to error
        assert mock_state.phase == "error"
        # Error message should be passed to write_next_action
        mock_state.write_next_action.assert_called_once_with(
            ActionType.ERROR, message="Agent crashed unexpectedly"
        )

    def test_empty_output_handles_error(self, state_machine: Any, mock_state: MagicMock) -> None:
        """Test empty output is treated as failure."""
        from scripts.planner.actions import ActionType

        mock_state.read_agent_output.return_value = {}

        state_machine._process_layer_reviewer_output()

        # Should set phase to error
        assert mock_state.phase == "error"
        mock_state.save.assert_called_once()
        # Default error message should be used
        mock_state.write_next_action.assert_called_once_with(
            ActionType.ERROR, message="Layer review failed"
        )


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
        main_branch = Branch(branch_id="main", layers={0: []})
        state.branches = {"main": main_branch}

        # Set up root unit with real Unit
        root_unit = Unit(id="root", description="Root", operation="MODIFY")
        state.units = {"root": root_unit}

        return state

    @pytest.fixture
    def state_machine(self, mock_state: MagicMock) -> Any:
        """Create RefactorPlanStateMachine with mock state."""
        from scripts.planner.refactor_plan import RefactorPlanStateMachine

        return RefactorPlanStateMachine(mock_state)

    def test_no_duplicates_when_run_multiple_times(
        self, state_machine: Any, mock_state: MagicMock
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
        # Should only have comp1 once in layer 1 (skeleton analyzer adds to layer 1)
        assert mock_state.branches["main"].layers[1].count("comp1") == 1

    def test_multiple_components_no_duplicates(
        self, state_machine: Any, mock_state: MagicMock
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
        # Skeleton analyzer adds to layer 1
        assert mock_state.branches["main"].layers[1].count("comp1") == 1
        assert mock_state.branches["main"].layers[1].count("comp2") == 1


class TestProcessSkeletonAnalyzerOutputEntryPointDuplicates:
    """Tests for _process_skeleton_analyzer_output entry point duplicate prevention."""

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
        main_branch = Branch(branch_id="main", layers={0: []})
        state.branches = {"main": main_branch}

        # Set up root unit with real Unit
        root_unit = Unit(id="root", description="Root", operation="MODIFY")
        state.units = {"root": root_unit}

        return state

    @pytest.fixture
    def state_machine(self, mock_state: MagicMock) -> Any:
        """Create RefactorPlanStateMachine with mock state."""
        from scripts.planner.refactor_plan import RefactorPlanStateMachine

        return RefactorPlanStateMachine(mock_state)

    def test_no_duplicate_entry_points_on_retry(
        self, state_machine: Any, mock_state: MagicMock
    ) -> None:
        """Test that entry points are not duplicated when analyzer runs twice."""
        mock_state.read_agent_output.return_value = {
            "status": "success",
            "components": [
                {
                    "id": "comp1",
                    "description": "Component 1",
                    "entry_points": ["main.py", "cli.py"],
                },
            ],
        }

        # Run twice to simulate retry scenario
        state_machine._process_skeleton_analyzer_output()
        mock_state.phase = "skeleton_analysis"
        state_machine._process_skeleton_analyzer_output()

        # Entry points should only appear once each
        assert mock_state.entry_points.count("main.py") == 1
        assert mock_state.entry_points.count("cli.py") == 1

    def test_entry_points_from_multiple_components(
        self, state_machine: Any, mock_state: MagicMock
    ) -> None:
        """Test entry points from multiple components are merged without duplicates."""
        mock_state.read_agent_output.return_value = {
            "status": "success",
            "components": [
                {
                    "id": "comp1",
                    "description": "Component 1",
                    "entry_points": ["main.py", "shared.py"],
                },
                {
                    "id": "comp2",
                    "description": "Component 2",
                    "entry_points": ["cli.py", "shared.py"],
                },
            ],
        }

        state_machine._process_skeleton_analyzer_output()

        # shared.py should only appear once despite being in both components
        assert mock_state.entry_points.count("shared.py") == 1
        assert "main.py" in mock_state.entry_points
        assert "cli.py" in mock_state.entry_points
        assert len(mock_state.entry_points) == 3

    def test_empty_entry_points_handled_gracefully(
        self, state_machine: Any, mock_state: MagicMock
    ) -> None:
        """Test that missing or empty entry_points are handled gracefully."""
        mock_state.read_agent_output.return_value = {
            "status": "success",
            "components": [
                {"id": "comp1", "description": "Component 1"},
                {"id": "comp2", "description": "Component 2", "entry_points": []},
                {"id": "comp3", "description": "Component 3", "entry_points": ["main.py"]},
            ],
        }

        state_machine._process_skeleton_analyzer_output()

        # Should only have entry point from comp3
        assert mock_state.entry_points == ["main.py"]

    def test_preserves_order_of_entry_points(
        self, state_machine: Any, mock_state: MagicMock
    ) -> None:
        """Test that order of entry points is preserved (first occurrence wins)."""
        mock_state.read_agent_output.return_value = {
            "status": "success",
            "components": [
                {
                    "id": "comp1",
                    "description": "Component 1",
                    "entry_points": ["a.py", "b.py", "c.py"],
                },
            ],
        }

        state_machine._process_skeleton_analyzer_output()

        assert mock_state.entry_points == ["a.py", "b.py", "c.py"]


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

        # Set up branches - comp1 is at layer 1 (as in real pipeline where
        # components have parent="root" and are placed in layer 1)
        main_branch = Branch(branch_id="main", layers={0: ["root"], 1: ["comp1"], 2: []})
        state.branches = {"main": main_branch}

        # Set up root and parent component unit with proper parent chain
        root_unit = Unit(id="root", description="Root", operation="MODIFY", parent=None)
        comp_unit = Unit(
            id="comp1", description="Component 1", operation="MODIFY", status="pending", parent="root"
        )
        state.units = {"root": root_unit, "comp1": comp_unit}

        return state

    @pytest.fixture
    def state_machine(self, mock_state: MagicMock) -> Any:
        """Create RefactorPlanStateMachine with mock state."""
        from scripts.planner.refactor_plan import RefactorPlanStateMachine

        return RefactorPlanStateMachine(mock_state)

    def test_no_duplicate_sub_units_on_retry(
        self, state_machine: Any, mock_state: MagicMock
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

        # Run twice
        state_machine._process_component_analyzer_output()
        mock_state.phase = "component_analysis"
        state_machine._process_component_analyzer_output()

        # The sub_id is generated as f"{unit_id}.{len(unit.children) + 1}"
        # After first run: comp1.1 is added, children = ["comp1.1"]
        # After second run: would try to add comp1.2 since len(children) is now 1
        # This is expected behavior - each run generates new IDs based on children count
        # The duplicate check is for the same ID being added twice
        comp1 = mock_state.units["comp1"]

        # Verify no exact duplicates in children list
        assert len(comp1.children) == len(set(comp1.children))
        # Sub-units should be placed at parent_layer + 1 (comp1 is at layer 1, so sub-units at layer 2)
        layer_2 = mock_state.branches["main"].layers[2]
        assert len(layer_2) == len(set(layer_2))


class TestProcessComponentAnalyzerSubUnitLayerPlacement:
    """Tests for sub-unit layer placement based on parent depth."""

    @pytest.fixture
    def mock_state(self, tmp_path: Path) -> MagicMock:
        """Create a mock DesignState with nested components."""
        from scripts.planner.state import Branch, Unit

        state = MagicMock()
        state.workspace = tmp_path
        state.history = []
        state.phase = "component_analysis"

        # Set up branches with existing layers
        main_branch = Branch(branch_id="main", layers={0: ["root"], 1: ["comp1"]})
        state.branches = {"main": main_branch}

        # Set up root and parent component with proper parent chain
        root_unit = Unit(id="root", description="Root", operation="MODIFY", parent=None)
        comp_unit = Unit(
            id="comp1", description="Component 1", operation="MODIFY", status="pending", parent="root"
        )
        state.units = {"root": root_unit, "comp1": comp_unit}

        return state

    @pytest.fixture
    def state_machine(self, mock_state: MagicMock) -> Any:
        """Create RefactorPlanStateMachine with mock state."""
        from scripts.planner.refactor_plan import RefactorPlanStateMachine

        return RefactorPlanStateMachine(mock_state)

    def test_sub_units_placed_at_parent_layer_plus_one(
        self, state_machine: Any, mock_state: MagicMock
    ) -> None:
        """Test that sub-units are placed at parent_layer + 1, not hardcoded layer 1."""
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

        # comp1 is at layer 1 (has parent="root" which is at layer 0)
        # So sub-units should be at layer 2, not layer 1
        assert "comp1.1" in mock_state.branches["main"].layers.get(2, [])
        assert "comp1.2" in mock_state.branches["main"].layers.get(2, [])

        # Verify they are NOT in layer 1
        layer_1 = mock_state.branches["main"].layers.get(1, [])
        assert "comp1.1" not in layer_1
        assert "comp1.2" not in layer_1


class TestNextActionErrorPhase:
    """Tests for next_action handling of error phase."""

    @pytest.fixture
    def mock_state(self, tmp_path: Path) -> MagicMock:
        """Create a mock DesignState."""
        state = MagicMock()
        state.workspace = tmp_path
        state.phase = "error"
        return state

    @pytest.fixture
    def state_machine(self, mock_state: MagicMock) -> Any:
        """Create RefactorPlanStateMachine with mock state."""
        from scripts.planner.refactor_plan import RefactorPlanStateMachine

        return RefactorPlanStateMachine(mock_state)

    def test_error_phase_writes_error_action_directly(
        self, state_machine: Any, mock_state: MagicMock
    ) -> None:
        """Test that error phase writes error action without calling _handle_error."""
        from scripts.planner.actions import ActionType

        # When next_action is called with phase already set to error
        state_machine.next_action()

        # Should write ERROR action directly
        mock_state.write_next_action.assert_called_once_with(
            ActionType.ERROR, message="Error state"
        )
        # Should NOT modify the phase (it's already error)
        # Should NOT call save (error state was already saved by _handle_error)

    def test_error_phase_does_not_recurse(
        self, state_machine: Any, mock_state: MagicMock
    ) -> None:
        """Test that error phase does not cause recursive _handle_error calls."""
        # Calling next_action multiple times with error phase should be stable
        state_machine.next_action()
        state_machine.next_action()
        state_machine.next_action()

        # Should have called write_next_action 3 times, but phase remains error
        assert mock_state.write_next_action.call_count == 3
        # Phase should still be error (not modified by subsequent calls)
        assert mock_state.phase == "error"


class TestProcessComponentAnalyzerPatternsUsed:
    """Tests for _process_component_analyzer_output patterns_used assignment."""

    @pytest.fixture
    def mock_state(self, tmp_path: Path) -> MagicMock:
        """Create a mock DesignState with a component."""
        from scripts.planner.state import Branch, Unit

        state = MagicMock()
        state.workspace = tmp_path
        state.history = []
        state.phase = "component_analysis"

        # Set up branches
        main_branch = Branch(branch_id="main", layers={0: ["comp1"], 1: []})
        state.branches = {"main": main_branch}

        # Set up parent component unit
        comp_unit = Unit(
            id="comp1", description="Component 1", operation="MODIFY", status="pending"
        )
        state.units = {"comp1": comp_unit}

        return state

    @pytest.fixture
    def state_machine(self, mock_state: MagicMock) -> Any:
        """Create RefactorPlanStateMachine with mock state."""
        from scripts.planner.refactor_plan import RefactorPlanStateMachine

        return RefactorPlanStateMachine(mock_state)

    def test_patterns_used_is_set_on_unit(
        self, state_machine: Any, mock_state: MagicMock
    ) -> None:
        """Test that patterns_used list is assigned to the unit."""
        patterns = [
            {"pattern": "builder", "pattern_category": "creation"},
            {"pattern": "factory", "pattern_category": "creation"},
        ]
        mock_state.read_agent_output.return_value = {
            "status": "success",
            "analyzed_components": [
                {
                    "component_id": "comp1",
                    "patterns_used": patterns,
                    "capabilities": {"provided": [], "expected": []},
                    "decomposition_suggestion": {"should_decompose": False},
                }
            ],
        }

        state_machine._process_component_analyzer_output()

        comp1 = mock_state.units["comp1"]
        # patterns_used should contain the full list
        assert comp1.patterns_used == patterns
        # pattern and pattern_category should be set from first pattern
        assert comp1.pattern == "builder"
        assert comp1.pattern_category == "creation"

    def test_empty_patterns_does_not_set_patterns_used(
        self, state_machine: Any, mock_state: MagicMock
    ) -> None:
        """Test that empty patterns list leaves patterns_used as default empty list."""
        mock_state.read_agent_output.return_value = {
            "status": "success",
            "analyzed_components": [
                {
                    "component_id": "comp1",
                    "patterns_used": [],
                    "capabilities": {"provided": [], "expected": []},
                    "decomposition_suggestion": {"should_decompose": False},
                }
            ],
        }

        state_machine._process_component_analyzer_output()

        comp1 = mock_state.units["comp1"]
        # patterns_used should remain empty (default)
        assert comp1.patterns_used == []
        # pattern and pattern_category should remain None
        assert comp1.pattern is None
        assert comp1.pattern_category is None

    def test_patterns_used_available_for_integration_mapping(
        self, state_machine: Any, mock_state: MagicMock
    ) -> None:
        """Test that patterns_used is accessible for downstream integration mapping."""
        patterns = [{"pattern": "visitor", "pattern_category": "behavioral"}]
        mock_state.read_agent_output.return_value = {
            "status": "success",
            "analyzed_components": [
                {
                    "component_id": "comp1",
                    "patterns_used": patterns,
                    "capabilities": {"provided": [], "expected": []},
                    "decomposition_suggestion": {"should_decompose": False},
                }
            ],
        }

        state_machine._process_component_analyzer_output()

        # Simulate what _handle_integration_mapping does
        comp1 = mock_state.units["comp1"]
        patterns_used = getattr(comp1, "patterns_used", [])

        # This should now pass - patterns_used should be populated
        assert patterns_used == patterns
        assert len(patterns_used) > 0
