"""Tests for scripts/planner/state.py - DesignState."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.planner.state import (
    Branch,
    DesignState,
    DomainHypothesis,
    ExploredPath,
    PatternHypothesis,
    TestPlan,
    Unit,
)


class TestCreateUnitFromSpec:
    """Tests for DesignState._create_unit_from_spec validation."""

    def test_valid_spec_creates_unit(self) -> None:
        """Test that a valid spec creates a Unit correctly."""
        spec = {
            "id": "unit-1",
            "description": "A test unit",
            "operation": "CREATE",
        }

        unit = DesignState._create_unit_from_spec(
            spec,
            parent_id="parent-1",
            path_id="path-1",
            confidence=0.9,
        )

        assert unit.id == "unit-1"
        assert unit.description == "A test unit"
        assert unit.operation == "CREATE"
        assert unit.parent == "parent-1"
        assert unit.path_id == "path-1"
        assert unit.confidence == 0.9

    def test_missing_id_raises_type_error(self) -> None:
        """Test that missing 'id' raises TypeError with helpful message."""
        spec = {
            "description": "A test unit",
            "operation": "CREATE",
        }

        with pytest.raises(TypeError) as exc_info:
            DesignState._create_unit_from_spec(
                spec,
                parent_id="parent-1",
                path_id="path-1",
                confidence=0.9,
            )

        error_message = str(exc_info.value)
        assert "id" in error_message
        assert "Missing or invalid" in error_message
        assert "NoneType" in error_message

    def test_invalid_id_type_raises_type_error(self) -> None:
        """Test that non-string 'id' raises TypeError with helpful message."""
        spec = {
            "id": 123,
            "description": "A test unit",
        }

        with pytest.raises(TypeError) as exc_info:
            DesignState._create_unit_from_spec(
                spec,
                parent_id="parent-1",
                path_id="path-1",
                confidence=0.9,
            )

        error_message = str(exc_info.value)
        assert "id" in error_message
        assert "int" in error_message

    def test_missing_description_raises_type_error(self) -> None:
        """Test that missing 'description' raises TypeError with helpful message."""
        spec = {
            "id": "unit-1",
            "operation": "CREATE",
        }

        with pytest.raises(TypeError) as exc_info:
            DesignState._create_unit_from_spec(
                spec,
                parent_id="parent-1",
                path_id="path-1",
                confidence=0.9,
            )

        error_message = str(exc_info.value)
        assert "description" in error_message
        assert "unit-1" in error_message  # Should include the id for context
        assert "Missing or invalid" in error_message

    def test_invalid_description_type_raises_type_error(self) -> None:
        """Test that non-string 'description' raises TypeError."""
        spec = {
            "id": "unit-1",
            "description": ["not", "a", "string"],
        }

        with pytest.raises(TypeError) as exc_info:
            DesignState._create_unit_from_spec(
                spec,
                parent_id="parent-1",
                path_id="path-1",
                confidence=0.9,
            )

        error_message = str(exc_info.value)
        assert "description" in error_message
        assert "list" in error_message

    def test_default_operation_is_create(self) -> None:
        """Test that missing operation defaults to CREATE."""
        spec = {
            "id": "unit-1",
            "description": "A test unit",
        }

        unit = DesignState._create_unit_from_spec(
            spec,
            parent_id="parent-1",
            path_id="path-1",
            confidence=None,
        )

        assert unit.operation == "CREATE"

    def test_valid_operation_modify(self) -> None:
        """Test that MODIFY operation is accepted."""
        spec = {
            "id": "unit-1",
            "description": "A test unit",
            "operation": "MODIFY",
        }

        unit = DesignState._create_unit_from_spec(
            spec,
            parent_id="parent-1",
            path_id="path-1",
            confidence=None,
        )

        assert unit.operation == "MODIFY"

    def test_valid_operation_delete(self) -> None:
        """Test that DELETE operation is accepted."""
        spec = {
            "id": "unit-1",
            "description": "A test unit",
            "operation": "DELETE",
        }

        unit = DesignState._create_unit_from_spec(
            spec,
            parent_id="parent-1",
            path_id="path-1",
            confidence=None,
        )

        assert unit.operation == "DELETE"

    def test_invalid_operation_raises_value_error(self) -> None:
        """Test that invalid operation raises ValueError with helpful message."""
        spec = {
            "id": "unit-1",
            "description": "A test unit",
            "operation": "INVALID",
        }

        with pytest.raises(ValueError) as exc_info:
            DesignState._create_unit_from_spec(
                spec,
                parent_id="parent-1",
                path_id="path-1",
                confidence=0.9,
            )

        error_message = str(exc_info.value)
        assert "operation" in error_message
        assert "unit-1" in error_message
        assert "INVALID" in error_message
        assert "CREATE" in error_message
        assert "MODIFY" in error_message
        assert "DELETE" in error_message

    def test_lowercase_operation_raises_value_error(self) -> None:
        """Test that lowercase operation (e.g., 'create') raises ValueError."""
        spec = {
            "id": "unit-1",
            "description": "A test unit",
            "operation": "create",
        }

        with pytest.raises(ValueError) as exc_info:
            DesignState._create_unit_from_spec(
                spec,
                parent_id="parent-1",
                path_id="path-1",
                confidence=0.9,
            )

        error_message = str(exc_info.value)
        assert "create" in error_message
        assert "unit-1" in error_message

    def test_spec_preview_in_error_message(self) -> None:
        """Test that error message includes spec preview for debugging."""
        spec = {
            "id": "unit-1",
            "extra_field": "some value",
            # description missing
        }

        with pytest.raises(TypeError) as exc_info:
            DesignState._create_unit_from_spec(
                spec,
                parent_id="parent-1",
                path_id="path-1",
                confidence=0.9,
            )

        error_message = str(exc_info.value)
        assert "unit-1" in error_message

    def test_domain_hypotheses_extracted_from_spec(self) -> None:
        """Test that domain_hypotheses are extracted from spec."""
        spec = {
            "id": "unit-1",
            "description": "A test unit",
            "operation": "CREATE",
            "domain_hypotheses": [
                {"domain": "auth", "subdomains": ["login"], "confidence": 0.8, "rationale": "Auth domain"},
                {"domain": "user", "confidence": 0.6, "rationale": "User domain"},
            ],
        }

        unit = DesignState._create_unit_from_spec(
            spec,
            parent_id="parent-1",
            path_id="path-1",
            confidence=0.9,
        )

        assert len(unit.domain_hypotheses) == 2
        assert unit.domain_hypotheses[0].domain == "auth"
        assert unit.domain_hypotheses[0].subdomains == ["login"]
        assert unit.domain_hypotheses[0].confidence == 0.8
        assert unit.domain_hypotheses[1].domain == "user"
        assert unit.domain_hypotheses[1].confidence == 0.6

    def test_pattern_hypotheses_extracted_from_spec(self) -> None:
        """Test that pattern_hypotheses are extracted from spec."""
        spec = {
            "id": "unit-1",
            "description": "A test unit",
            "operation": "CREATE",
            "pattern_hypotheses": [
                {"pattern": "builder", "category": "creational", "confidence": 0.9, "rationale": "Builder pattern"},
                {"pattern": "factory", "category": "creational", "confidence": 0.7, "rationale": "Factory pattern"},
            ],
        }

        unit = DesignState._create_unit_from_spec(
            spec,
            parent_id="parent-1",
            path_id="path-1",
            confidence=0.9,
        )

        assert len(unit.pattern_hypotheses) == 2
        assert unit.pattern_hypotheses[0].pattern == "builder"
        assert unit.pattern_hypotheses[0].category == "creational"
        assert unit.pattern_hypotheses[0].confidence == 0.9
        assert unit.pattern_hypotheses[1].pattern == "factory"
        assert unit.pattern_hypotheses[1].confidence == 0.7

    def test_hypotheses_skip_non_dict_items(self) -> None:
        """Test that non-dict items in hypotheses lists are skipped."""
        spec = {
            "id": "unit-1",
            "description": "A test unit",
            "operation": "CREATE",
            "domain_hypotheses": [
                {"domain": "auth", "confidence": 0.8, "rationale": "Valid"},
                "not-a-dict",
                123,
                None,
            ],
            "pattern_hypotheses": [
                {"pattern": "builder", "category": "creational", "confidence": 0.9, "rationale": "Valid"},
                ["not", "a", "dict"],
            ],
        }

        unit = DesignState._create_unit_from_spec(
            spec,
            parent_id="parent-1",
            path_id="path-1",
            confidence=0.9,
        )

        # Only valid dict items should be parsed
        assert len(unit.domain_hypotheses) == 1
        assert unit.domain_hypotheses[0].domain == "auth"
        assert len(unit.pattern_hypotheses) == 1
        assert unit.pattern_hypotheses[0].pattern == "builder"

    def test_empty_hypotheses_default_to_empty_lists(self) -> None:
        """Test that missing hypotheses default to empty lists."""
        spec = {
            "id": "unit-1",
            "description": "A test unit",
            "operation": "CREATE",
        }

        unit = DesignState._create_unit_from_spec(
            spec,
            parent_id="parent-1",
            path_id="path-1",
            confidence=0.9,
        )

        assert unit.domain_hypotheses == []
        assert unit.pattern_hypotheses == []


class TestDomainHypothesisConfidenceValidation:
    """Tests for DomainHypothesis confidence validation."""

    def test_valid_confidence_zero(self) -> None:
        """Test that confidence of 0.0 is valid."""
        hypothesis = DomainHypothesis(domain="test", confidence=0.0)
        assert hypothesis.confidence == 0.0

    def test_valid_confidence_one(self) -> None:
        """Test that confidence of 1.0 is valid."""
        hypothesis = DomainHypothesis(domain="test", confidence=1.0)
        assert hypothesis.confidence == 1.0

    def test_valid_confidence_mid_range(self) -> None:
        """Test that confidence in the middle of range is valid."""
        hypothesis = DomainHypothesis(domain="test", confidence=0.5)
        assert hypothesis.confidence == 0.5

    def test_valid_confidence_integer_one(self) -> None:
        """Test that integer 1 is valid and coerced to float."""
        hypothesis = DomainHypothesis(domain="test", confidence=1)
        assert hypothesis.confidence == 1.0
        assert isinstance(hypothesis.confidence, float)

    def test_valid_confidence_integer_zero(self) -> None:
        """Test that integer 0 is valid and coerced to float."""
        hypothesis = DomainHypothesis(domain="test", confidence=0)
        assert hypothesis.confidence == 0.0
        assert isinstance(hypothesis.confidence, float)

    def test_invalid_confidence_negative(self) -> None:
        """Test that negative confidence raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            DomainHypothesis(domain="test", confidence=-0.1)
        assert "DomainHypothesis" in str(exc_info.value)
        assert "-0.1" in str(exc_info.value)

    def test_invalid_confidence_above_one(self) -> None:
        """Test that confidence above 1.0 raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            DomainHypothesis(domain="test", confidence=1.5)
        assert "DomainHypothesis" in str(exc_info.value)
        assert "1.5" in str(exc_info.value)

    def test_invalid_confidence_string(self) -> None:
        """Test that string confidence raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            DomainHypothesis(domain="test", confidence="0.5")  # type: ignore[arg-type]
        assert "DomainHypothesis" in str(exc_info.value)

    def test_from_dict_validates_confidence(self) -> None:
        """Test that from_dict also validates confidence via __post_init__."""
        with pytest.raises(ValueError) as exc_info:
            DomainHypothesis.from_dict({"domain": "test", "confidence": 2.0})
        assert "DomainHypothesis" in str(exc_info.value)


class TestPatternHypothesisConfidenceValidation:
    """Tests for PatternHypothesis confidence validation."""

    def test_valid_confidence_zero(self) -> None:
        """Test that confidence of 0.0 is valid."""
        hypothesis = PatternHypothesis(pattern="test", category="cat", confidence=0.0)
        assert hypothesis.confidence == 0.0

    def test_valid_confidence_one(self) -> None:
        """Test that confidence of 1.0 is valid."""
        hypothesis = PatternHypothesis(pattern="test", category="cat", confidence=1.0)
        assert hypothesis.confidence == 1.0

    def test_valid_confidence_mid_range(self) -> None:
        """Test that confidence in the middle of range is valid."""
        hypothesis = PatternHypothesis(pattern="test", category="cat", confidence=0.5)
        assert hypothesis.confidence == 0.5

    def test_valid_confidence_integer_one(self) -> None:
        """Test that integer 1 is valid and coerced to float."""
        hypothesis = PatternHypothesis(pattern="test", category="cat", confidence=1)
        assert hypothesis.confidence == 1.0
        assert isinstance(hypothesis.confidence, float)

    def test_valid_confidence_integer_zero(self) -> None:
        """Test that integer 0 is valid and coerced to float."""
        hypothesis = PatternHypothesis(pattern="test", category="cat", confidence=0)
        assert hypothesis.confidence == 0.0
        assert isinstance(hypothesis.confidence, float)

    def test_invalid_confidence_negative(self) -> None:
        """Test that negative confidence raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            PatternHypothesis(pattern="test", category="cat", confidence=-0.1)
        assert "PatternHypothesis" in str(exc_info.value)
        assert "-0.1" in str(exc_info.value)

    def test_invalid_confidence_above_one(self) -> None:
        """Test that confidence above 1.0 raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            PatternHypothesis(pattern="test", category="cat", confidence=1.5)
        assert "PatternHypothesis" in str(exc_info.value)
        assert "1.5" in str(exc_info.value)

    def test_invalid_confidence_string(self) -> None:
        """Test that string confidence raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            PatternHypothesis(pattern="test", category="cat", confidence="0.5")  # type: ignore[arg-type]
        assert "PatternHypothesis" in str(exc_info.value)

    def test_from_dict_validates_confidence(self) -> None:
        """Test that from_dict also validates confidence via __post_init__."""
        with pytest.raises(ValueError) as exc_info:
            PatternHypothesis.from_dict({"pattern": "test", "category": "cat", "confidence": 2.0})
        assert "PatternHypothesis" in str(exc_info.value)


class TestCommitToPath:
    """Tests for DesignState.commit_to_path exception handling."""

    def _create_state_with_path(
        self,
        parent_id: str,
        path_id: str,
        sub_unit_specs: list[dict],
    ) -> DesignState:
        """Create a DesignState with an explored path."""
        parent_unit = Unit(
            id=parent_id,
            description="Parent unit",
            operation="CREATE",
            status="pending",
            children=[],
            parent=None,
        )
        explored_path = ExploredPath(
            confidence=0.9,
            rationale="Test path",
            status="exploring",
            sub_unit_specs=sub_unit_specs,
            sub_units=[],
        )
        state = DesignState(
            workspace=Path("/tmp/test"),
            ticket_id="TEST-1",
            title="Test commit_to_path",
            units={parent_id: parent_unit},
            explored_paths={parent_id: {path_id: explored_path}},
        )
        return state

    def test_malformed_spec_aborts_without_partial_mutation(self) -> None:
        """Test that a malformed spec aborts the entire operation atomically.

        When any spec fails validation in _create_unit_from_spec, the entire
        operation should abort and no units should be added to state.
        """
        specs = [
            {"id": "good-1", "description": "Valid unit 1"},
            {"id": "bad-1"},  # Missing description - should abort entire operation
            {"id": "good-2", "description": "Valid unit 2"},
        ]
        state = self._create_state_with_path("parent-1", "path-1", specs)

        # The malformed spec should raise TypeError and abort the entire operation
        with pytest.raises(TypeError):
            state.commit_to_path("parent-1", "path-1", layer_manager=None)

        # No units should have been added (atomic behavior)
        assert "good-1" not in state.units
        assert "good-2" not in state.units
        assert "bad-1" not in state.units

        # Parent children should be unchanged
        parent = state.units["parent-1"]
        assert parent.children == []

    def test_non_dict_spec_skipped(self) -> None:
        """Test that non-dict specs are skipped."""
        specs = [
            {"id": "good-1", "description": "Valid unit"},
            "not-a-dict",
            123,
            None,
        ]
        state = self._create_state_with_path("parent-1", "path-1", specs)

        new_unit_ids = state.commit_to_path("parent-1", "path-1", layer_manager=None)

        assert new_unit_ids == ["good-1"]
        assert len(state.units) == 2  # parent + good-1

    def test_spec_without_string_id_skipped(self) -> None:
        """Test that specs with non-string id are skipped."""
        specs = [
            {"id": "good-1", "description": "Valid unit"},
            {"id": 123, "description": "Invalid id type"},
            {"description": "Missing id"},
        ]
        state = self._create_state_with_path("parent-1", "path-1", specs)

        new_unit_ids = state.commit_to_path("parent-1", "path-1", layer_manager=None)

        assert new_unit_ids == ["good-1"]
        assert len(state.units) == 2  # parent + good-1

    def test_all_filterable_specs_returns_empty(self) -> None:
        """Test that specs filtered before validation return empty list."""
        # These specs are filtered early (non-dict or missing string id)
        # so they don't trigger the atomic abort behavior
        specs = [
            {"description": "Missing id"},  # No string id - filtered early
            "not-a-dict",  # Not a dict - filtered early
        ]
        state = self._create_state_with_path("parent-1", "path-1", specs)

        new_unit_ids = state.commit_to_path("parent-1", "path-1", layer_manager=None)

        assert new_unit_ids == []
        assert len(state.units) == 1  # Only parent
        assert state.units["parent-1"].children == []

    def test_malformed_dict_spec_with_id_aborts(self) -> None:
        """Test that a dict spec with id but invalid content aborts atomically."""
        specs = [
            {"id": "bad-1"},  # Has string id but missing description
        ]
        state = self._create_state_with_path("parent-1", "path-1", specs)

        with pytest.raises(TypeError):
            state.commit_to_path("parent-1", "path-1", layer_manager=None)

        assert "bad-1" not in state.units
        assert state.units["parent-1"].children == []

    def test_malformed_spec_does_not_mutate_path_status(self) -> None:
        """Test that path status remains unchanged when spec validation fails."""
        specs = [
            {"id": "good-1", "description": "Valid unit"},
            {"id": "bad-1"},  # Missing description - will fail
        ]
        state = self._create_state_with_path("parent-1", "path-1", specs)
        # Verify initial status
        assert state.explored_paths["parent-1"]["path-1"].status == "exploring"

        with pytest.raises(TypeError):
            state.commit_to_path("parent-1", "path-1", layer_manager=None)

        # Path status should remain unchanged (not set to "selected")
        assert state.explored_paths["parent-1"]["path-1"].status == "exploring"

    def test_already_selected_path_returns_early(self) -> None:
        """Test that committing to an already-selected path returns early with no changes."""
        specs = [
            {"id": "child-1", "description": "Child unit 1"},
        ]
        state = self._create_state_with_path("parent-1", "path-1", specs)

        # First commit should create the child unit
        new_unit_ids = state.commit_to_path("parent-1", "path-1", layer_manager=None)
        assert new_unit_ids == ["child-1"]
        assert "child-1" in state.units
        assert state.explored_paths["parent-1"]["path-1"].status == "selected"

        # Second commit to the same already-selected path should return empty list
        repeated_unit_ids = state.commit_to_path("parent-1", "path-1", layer_manager=None)
        assert repeated_unit_ids == []
        # State should remain unchanged
        assert len(state.units) == 2  # parent + child-1
        assert state.explored_paths["parent-1"]["path-1"].status == "selected"

    def test_rollback_on_layer_manager_failure(self) -> None:
        """Test that state is rolled back if layer_manager raises an exception."""
        # Create parent unit with an existing selected path and child units
        parent_unit = Unit(
            id="parent-1",
            description="Parent unit",
            operation="CREATE",
            status="decomposed",
            children=["child-1", "child-2"],
            parent=None,
        )
        child_1 = Unit(
            id="child-1",
            description="Child unit 1",
            operation="CREATE",
            status="pending",
            children=[],
            parent="parent-1",
        )
        child_2 = Unit(
            id="child-2",
            description="Child unit 2",
            operation="CREATE",
            status="pending",
            children=[],
            parent="parent-1",
        )

        # Create two paths: path-1 is selected, path-2 is exploring
        path_1 = ExploredPath(
            confidence=0.8,
            rationale="Old path",
            status="selected",
            sub_unit_specs=[],
            sub_units=["child-1", "child-2"],
        )
        path_2 = ExploredPath(
            confidence=0.9,
            rationale="New path",
            status="exploring",
            sub_unit_specs=[{"id": "child-3", "description": "New child"}],
            sub_units=[],
        )

        state = DesignState(
            workspace=Path("/tmp/test"),
            ticket_id="TEST-1",
            title="Test rollback",
            units={"parent-1": parent_unit, "child-1": child_1, "child-2": child_2},
            explored_paths={"parent-1": {"path-1": path_1, "path-2": path_2}},
            branches={"main": Branch(branch_id="main")},
        )

        # Mock layer_manager that raises an exception
        class FailingLayerManager:
            def remove_unit_from_layer(self, unit_id: str, branch_id: str = "main") -> None:
                raise RuntimeError("Simulated layer_manager failure")

            def add_units_to_layer(self, unit_ids: list[str], branch_id: str = "main") -> None:
                pass

        failing_manager = FailingLayerManager()

        # Attempt to commit to path-2, which should fail and rollback
        with pytest.raises(RuntimeError, match="Simulated layer_manager failure"):
            state.commit_to_path("parent-1", "path-2", layer_manager=failing_manager)

        # Verify rollback: old path status should be restored to "selected"
        assert state.explored_paths["parent-1"]["path-1"].status == "selected"

        # Verify rollback: children should still be attached to parent
        assert "child-1" in state.units["parent-1"].children
        assert "child-2" in state.units["parent-1"].children

        # Verify rollback: child units should still exist
        assert "child-1" in state.units
        assert "child-2" in state.units

    def test_rollback_restores_partially_removed_children(self) -> None:
        """Test rollback when failure occurs after partial child removal."""
        parent_unit = Unit(
            id="parent-1",
            description="Parent unit",
            operation="CREATE",
            status="decomposed",
            children=["child-1"],
            parent=None,
        )
        child_1 = Unit(
            id="child-1",
            description="Child unit 1",
            operation="CREATE",
            status="pending",
            children=[],
            parent="parent-1",
        )

        path_1 = ExploredPath(
            confidence=0.8,
            rationale="Old path",
            status="selected",
            sub_unit_specs=[],
            sub_units=["child-1"],
        )
        path_2 = ExploredPath(
            confidence=0.9,
            rationale="New path",
            status="exploring",
            sub_unit_specs=[],
            sub_units=[],
        )

        state = DesignState(
            workspace=Path("/tmp/test"),
            ticket_id="TEST-1",
            title="Test partial rollback",
            units={"parent-1": parent_unit, "child-1": child_1},
            explored_paths={"parent-1": {"path-1": path_1, "path-2": path_2}},
            branches={"main": Branch(branch_id="main")},
        )

        # Layer manager that tracks calls and fails on specific unit
        class TrackingFailingLayerManager:
            def __init__(self) -> None:
                self.removed_units: list[str] = []

            def remove_unit_from_layer(self, unit_id: str, branch_id: str = "main") -> None:
                self.removed_units.append(unit_id)
                raise RuntimeError(f"Failed removing {unit_id}")

            def add_units_to_layer(self, unit_ids: list[str], branch_id: str = "main") -> None:
                pass

        failing_manager = TrackingFailingLayerManager()

        with pytest.raises(RuntimeError):
            state.commit_to_path("parent-1", "path-2", layer_manager=failing_manager)

        # Verify child is restored to parent.children
        assert "child-1" in state.units["parent-1"].children

        # Verify child unit is restored
        assert "child-1" in state.units

        # Verify old path status is restored
        assert state.explored_paths["parent-1"]["path-1"].status == "selected"


class TestPruneOldPath:
    """Tests for DesignState._prune_old_path helper method."""

    def test_marks_path_as_pruned(self) -> None:
        """Test that _prune_old_path marks the old path status as pruned."""
        parent_unit = Unit(
            id="parent-1",
            description="Parent",
            operation="CREATE",
            status="decomposed",
            children=["child-1"],
        )
        child_unit = Unit(
            id="child-1",
            description="Child",
            operation="CREATE",
            status="pending",
            children=[],
            parent="parent-1",
        )
        old_path = ExploredPath(
            confidence=0.8,
            rationale="Old path",
            status="selected",
            sub_unit_specs=[],
            sub_units=["child-1"],
        )
        state = DesignState(
            workspace=Path("/tmp/test"),
            ticket_id="TEST-1",
            title="Test prune",
            units={"parent-1": parent_unit, "child-1": child_unit},
            explored_paths={"parent-1": {"path-1": old_path}},
        )

        descendant_ids = {"child-1"}
        parent_children_to_remove = {"parent-1": ["child-1"]}

        state._prune_old_path(
            old_path, descendant_ids, parent_children_to_remove, layer_manager=None
        )

        assert old_path.status == "pruned"

    def test_removes_children_from_parent(self) -> None:
        """Test that _prune_old_path detaches children from parent units."""
        parent_unit = Unit(
            id="parent-1",
            description="Parent",
            operation="CREATE",
            status="decomposed",
            children=["child-1", "child-2"],
        )
        child_1 = Unit(
            id="child-1",
            description="Child 1",
            operation="CREATE",
            status="pending",
            children=[],
            parent="parent-1",
        )
        child_2 = Unit(
            id="child-2",
            description="Child 2",
            operation="CREATE",
            status="pending",
            children=[],
            parent="parent-1",
        )
        old_path = ExploredPath(
            confidence=0.8,
            rationale="Old path",
            status="selected",
            sub_unit_specs=[],
            sub_units=["child-1", "child-2"],
        )
        state = DesignState(
            workspace=Path("/tmp/test"),
            ticket_id="TEST-1",
            title="Test prune",
            units={"parent-1": parent_unit, "child-1": child_1, "child-2": child_2},
            explored_paths={"parent-1": {"path-1": old_path}},
        )

        descendant_ids = {"child-1", "child-2"}
        parent_children_to_remove = {"parent-1": ["child-1", "child-2"]}

        state._prune_old_path(
            old_path, descendant_ids, parent_children_to_remove, layer_manager=None
        )

        assert state.units["parent-1"].children == []

    def test_removes_units_from_state(self) -> None:
        """Test that _prune_old_path removes descendant units from self.units."""
        parent_unit = Unit(
            id="parent-1",
            description="Parent",
            operation="CREATE",
            status="decomposed",
            children=["child-1"],
        )
        child_unit = Unit(
            id="child-1",
            description="Child",
            operation="CREATE",
            status="pending",
            children=[],
            parent="parent-1",
        )
        old_path = ExploredPath(
            confidence=0.8,
            rationale="Old path",
            status="selected",
            sub_unit_specs=[],
            sub_units=["child-1"],
        )
        state = DesignState(
            workspace=Path("/tmp/test"),
            ticket_id="TEST-1",
            title="Test prune",
            units={"parent-1": parent_unit, "child-1": child_unit},
            explored_paths={"parent-1": {"path-1": old_path}},
        )

        descendant_ids = {"child-1"}
        parent_children_to_remove = {"parent-1": ["child-1"]}

        state._prune_old_path(
            old_path, descendant_ids, parent_children_to_remove, layer_manager=None
        )

        assert "child-1" not in state.units
        assert "parent-1" in state.units


class TestRollbackPathPruning:
    """Tests for DesignState._rollback_path_pruning helper method."""

    def test_restores_path_status_to_selected(self) -> None:
        """Test that _rollback_path_pruning restores old_path status."""
        old_path = ExploredPath(
            confidence=0.8,
            rationale="Old path",
            status="pruned",  # Simulate pruned state
            sub_unit_specs=[],
            sub_units=["child-1"],
        )
        state = DesignState(
            workspace=Path("/tmp/test"),
            ticket_id="TEST-1",
            title="Test rollback",
            units={
                "parent-1": Unit(
                    id="parent-1",
                    description="Parent",
                    operation="CREATE",
                    children=[],
                )
            },
            explored_paths={"parent-1": {"path-1": old_path}},
        )

        removed_units = {
            "child-1": Unit(
                id="child-1",
                description="Child",
                operation="CREATE",
                children=[],
                parent="parent-1",
            )
        }

        state._rollback_path_pruning(
            old_path,
            descendant_ids={"child-1"},
            parent_children_to_remove={"parent-1": ["child-1"]},
            removed_units=removed_units,
            layer_manager=None,
        )

        assert old_path.status == "selected"

    def test_reattaches_children_to_parent(self) -> None:
        """Test that _rollback_path_pruning re-attaches children to parents."""
        parent_unit = Unit(
            id="parent-1",
            description="Parent",
            operation="CREATE",
            children=[],  # Children were removed
        )
        old_path = ExploredPath(
            confidence=0.8,
            rationale="Old path",
            status="pruned",
            sub_unit_specs=[],
            sub_units=["child-1"],
        )
        state = DesignState(
            workspace=Path("/tmp/test"),
            ticket_id="TEST-1",
            title="Test rollback",
            units={"parent-1": parent_unit},
            explored_paths={"parent-1": {"path-1": old_path}},
        )

        removed_units = {
            "child-1": Unit(
                id="child-1",
                description="Child",
                operation="CREATE",
                children=[],
                parent="parent-1",
            )
        }

        state._rollback_path_pruning(
            old_path,
            descendant_ids={"child-1"},
            parent_children_to_remove={"parent-1": ["child-1"]},
            removed_units=removed_units,
            layer_manager=None,
        )

        assert "child-1" in state.units["parent-1"].children

    def test_restores_removed_units(self) -> None:
        """Test that _rollback_path_pruning restores removed units."""
        parent_unit = Unit(
            id="parent-1",
            description="Parent",
            operation="CREATE",
            children=[],
        )
        old_path = ExploredPath(
            confidence=0.8,
            rationale="Old path",
            status="pruned",
            sub_unit_specs=[],
            sub_units=["child-1"],
        )
        state = DesignState(
            workspace=Path("/tmp/test"),
            ticket_id="TEST-1",
            title="Test rollback",
            units={"parent-1": parent_unit},  # child-1 was removed
            explored_paths={"parent-1": {"path-1": old_path}},
        )

        child_unit = Unit(
            id="child-1",
            description="Child",
            operation="CREATE",
            children=[],
            parent="parent-1",
        )
        removed_units = {"child-1": child_unit}

        state._rollback_path_pruning(
            old_path,
            descendant_ids={"child-1"},
            parent_children_to_remove={"parent-1": ["child-1"]},
            removed_units=removed_units,
            layer_manager=None,
        )

        assert "child-1" in state.units
        assert state.units["child-1"] is child_unit


class TestMaterializePathUnits:
    """Tests for DesignState._materialize_path_units helper method."""

    def test_creates_new_units_from_specs(self) -> None:
        """Test that _materialize_path_units creates units from valid specs."""
        parent_unit = Unit(
            id="parent-1",
            description="Parent",
            operation="CREATE",
            children=[],
        )
        new_path = ExploredPath(
            confidence=0.9,
            rationale="New path",
            status="exploring",
            sub_unit_specs=[
                {"id": "child-1", "description": "Child 1"},
                {"id": "child-2", "description": "Child 2"},
            ],
            sub_units=[],
        )
        state = DesignState(
            workspace=Path("/tmp/test"),
            ticket_id="TEST-1",
            title="Test materialize",
            units={"parent-1": parent_unit},
            explored_paths={"parent-1": {"path-1": new_path}},
        )

        units_to_create, existing_to_update, new_ids = state._materialize_path_units(
            new_path, parent_unit_id="parent-1", path_id="path-1"
        )

        assert len(units_to_create) == 2
        assert "child-1" in units_to_create
        assert "child-2" in units_to_create
        assert new_ids == ["child-1", "child-2"]
        assert existing_to_update == []

    def test_identifies_existing_units_for_update(self) -> None:
        """Test that _materialize_path_units identifies existing units for path_id update."""
        parent_unit = Unit(
            id="parent-1",
            description="Parent",
            operation="CREATE",
            children=["child-1"],
        )
        existing_child = Unit(
            id="child-1",
            description="Existing child",
            operation="CREATE",
            parent="parent-1",
            path_id="old-path",
        )
        new_path = ExploredPath(
            confidence=0.9,
            rationale="New path",
            status="exploring",
            sub_unit_specs=[
                {"id": "child-1", "description": "Existing child"},
                {"id": "child-2", "description": "New child"},
            ],
            sub_units=[],
        )
        state = DesignState(
            workspace=Path("/tmp/test"),
            ticket_id="TEST-1",
            title="Test materialize",
            units={"parent-1": parent_unit, "child-1": existing_child},
            explored_paths={"parent-1": {"path-1": new_path}},
        )

        units_to_create, existing_to_update, new_ids = state._materialize_path_units(
            new_path, parent_unit_id="parent-1", path_id="path-1"
        )

        assert len(units_to_create) == 1
        assert "child-2" in units_to_create
        assert existing_to_update == ["child-1"]
        assert new_ids == ["child-2"]

    def test_skips_non_dict_specs(self) -> None:
        """Test that _materialize_path_units skips non-dict specs."""
        parent_unit = Unit(
            id="parent-1",
            description="Parent",
            operation="CREATE",
            children=[],
        )
        new_path = ExploredPath(
            confidence=0.9,
            rationale="New path",
            status="exploring",
            sub_unit_specs=[
                {"id": "child-1", "description": "Valid"},
                "not-a-dict",
                123,
                None,
            ],
            sub_units=[],
        )
        state = DesignState(
            workspace=Path("/tmp/test"),
            ticket_id="TEST-1",
            title="Test materialize",
            units={"parent-1": parent_unit},
            explored_paths={"parent-1": {"path-1": new_path}},
        )

        units_to_create, existing_to_update, new_ids = state._materialize_path_units(
            new_path, parent_unit_id="parent-1", path_id="path-1"
        )

        assert len(units_to_create) == 1
        assert new_ids == ["child-1"]

    def test_raises_on_invalid_spec(self) -> None:
        """Test that _materialize_path_units raises on invalid spec with string id."""
        parent_unit = Unit(
            id="parent-1",
            description="Parent",
            operation="CREATE",
            children=[],
        )
        new_path = ExploredPath(
            confidence=0.9,
            rationale="New path",
            status="exploring",
            sub_unit_specs=[
                {"id": "bad-1"},  # Missing description - should raise
            ],
            sub_units=[],
        )
        state = DesignState(
            workspace=Path("/tmp/test"),
            ticket_id="TEST-1",
            title="Test materialize",
            units={"parent-1": parent_unit},
            explored_paths={"parent-1": {"path-1": new_path}},
        )

        with pytest.raises(TypeError):
            state._materialize_path_units(
                new_path, parent_unit_id="parent-1", path_id="path-1"
            )

    def test_does_not_mutate_state(self) -> None:
        """Test that _materialize_path_units does not mutate self.units."""
        parent_unit = Unit(
            id="parent-1",
            description="Parent",
            operation="CREATE",
            children=[],
        )
        new_path = ExploredPath(
            confidence=0.9,
            rationale="New path",
            status="exploring",
            sub_unit_specs=[
                {"id": "child-1", "description": "Child"},
            ],
            sub_units=[],
        )
        state = DesignState(
            workspace=Path("/tmp/test"),
            ticket_id="TEST-1",
            title="Test materialize",
            units={"parent-1": parent_unit},
            explored_paths={"parent-1": {"path-1": new_path}},
        )

        initial_unit_count = len(state.units)

        state._materialize_path_units(
            new_path, parent_unit_id="parent-1", path_id="path-1"
        )

        # State should not be mutated
        assert len(state.units) == initial_unit_count
        assert "child-1" not in state.units


class TestTestPlanFromDict:
    """Tests for TestPlan.from_dict suite field extraction."""

    def test_extracts_suite_fields_from_nested_dict(self) -> None:
        """Test that suite fields are extracted from nested 'suite' dict."""
        data = {
            "id": "test-1",
            "capability_id": "cap-1",
            "use_case": "Test use case",
            "type": "unit",
            "suite": {
                "file": "tests/test_example.py",
                "type": "unit",
                "coverage_type": "line_branch",
            },
        }

        plan = TestPlan.from_dict(data)

        assert plan.suite_file == "tests/test_example.py"
        assert plan.suite_type == "unit"
        assert plan.coverage_type == "line_branch"

    def test_top_level_fields_take_precedence(self) -> None:
        """Test that top-level suite fields take precedence over nested."""
        data = {
            "id": "test-1",
            "capability_id": "cap-1",
            "use_case": "Test use case",
            "type": "unit",
            "suite_file": "top_level.py",
            "suite_type": "component",
            "coverage_type": "usecase",
            "suite": {
                "file": "nested.py",
                "type": "unit",
                "coverage_type": "line_branch",
            },
        }

        plan = TestPlan.from_dict(data)

        # Top-level values should be used
        assert plan.suite_file == "top_level.py"
        assert plan.suite_type == "component"
        assert plan.coverage_type == "usecase"

    def test_handles_non_dict_suite(self) -> None:
        """Test that non-dict suite values are ignored."""
        data = {
            "id": "test-1",
            "capability_id": "cap-1",
            "use_case": "Test use case",
            "type": "unit",
            "suite": "not-a-dict",
        }

        plan = TestPlan.from_dict(data)

        assert plan.suite_file is None
        assert plan.suite_type is None
        assert plan.coverage_type is None

    def test_handles_missing_suite(self) -> None:
        """Test that missing suite is handled gracefully."""
        data = {
            "id": "test-1",
            "capability_id": "cap-1",
            "use_case": "Test use case",
            "type": "unit",
        }

        plan = TestPlan.from_dict(data)

        assert plan.suite_file is None
        assert plan.suite_type is None
        assert plan.coverage_type is None


class TestUnitDiscoveredFrom:
    """Tests for Unit.discovered_from field."""

    def test_discovered_from_included_in_to_dict(self) -> None:
        """Test that discovered_from is serialized when set."""
        unit = Unit(
            id="unit-1",
            description="Test unit",
            operation="CREATE",
            discovered_from="folder_scan",
        )

        result = unit.to_dict()

        assert result["discovered_from"] == "folder_scan"

    def test_discovered_from_omitted_when_none(self) -> None:
        """Test that discovered_from is omitted when None."""
        unit = Unit(
            id="unit-1",
            description="Test unit",
            operation="CREATE",
        )

        result = unit.to_dict()

        assert "discovered_from" not in result

    def test_discovered_from_parsed_from_dict(self) -> None:
        """Test that discovered_from is deserialized correctly."""
        data = {
            "id": "unit-1",
            "description": "Test unit",
            "operation": "CREATE",
            "discovered_from": "entry_point_analysis",
        }

        unit = Unit.from_dict(data)

        assert unit.discovered_from == "entry_point_analysis"

    def test_discovered_from_defaults_to_none(self) -> None:
        """Test that missing discovered_from defaults to None."""
        data = {
            "id": "unit-1",
            "description": "Test unit",
            "operation": "CREATE",
        }

        unit = Unit.from_dict(data)

        assert unit.discovered_from is None
