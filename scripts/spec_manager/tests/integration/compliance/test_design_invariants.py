"""Tests for design invariants that must always pass.

This module contains invariant tests for the design-alignment harness.
These tests verify fundamental properties of the compliance infrastructure
that must hold at all times.

Invariants tested:
- Schema registry loads all 8 design schemas
- ContractValidationResult structure matches DS-COMP-0001
- Coverage tracking maintains 100% coverage through transformations
"""

from __future__ import annotations

import pytest
from spec_manager.compliance import (
    ContractValidationResult,
    SchemaRegistry,
    validate_artifact_contract,
)
from spec_manager.core.coverage import CoverageTracker, FragmentStatus


class TestSchemaRegistryInvariants:
    """Invariants for the SchemaRegistry class."""

    def test_schema_registry_loads_all_design_schemas(self) -> None:
        """Schema registry must be able to load all 8 design schemas.

        This is a fundamental invariant: the registry must have access to
        all design schemas defined in the plan.
        """
        registry = SchemaRegistry()
        expected_schemas = [
            "atoms",
            "section_map",
            "decomposition_output",
            "library_labels",
            "gap_element",
            "task_plan",
            "derived_elements",
            "tag_index_delta",
        ]

        available = registry.get_available_schemas()

        for schema_id in expected_schemas:
            assert schema_id in available, f"Missing schema: {schema_id}"

        assert len(available) == 8, f"Expected 8 schemas, got {len(available)}"

    def test_each_schema_file_exists_and_loads(self) -> None:
        """Each schema file must exist and be valid JSON.

        Invariant: All schema files in SCHEMA_MAP must be loadable.
        """
        registry = SchemaRegistry()

        for schema_id in registry.get_available_schemas():
            # Should not raise
            schema = registry.get_schema(schema_id)

            # Basic JSON Schema structure validation
            assert isinstance(schema, dict), f"Schema {schema_id} is not a dict"
            assert "$schema" in schema, f"Schema {schema_id} missing $schema"
            assert "type" in schema or "properties" in schema, (
                f"Schema {schema_id} missing type/properties"
            )


class TestContractValidationResultInvariants:
    """Invariants for ContractValidationResult (DS-COMP-0001)."""

    def test_contract_validation_result_has_required_fields(self) -> None:
        """ContractValidationResult must have all fields from DS-COMP-0001."""
        result = ContractValidationResult(
            artifact_id="test",
            schema_id="atoms",
            valid=True,
            errors=[],
            warnings=[],
        )

        # Required fields from DS-COMP-0001
        assert hasattr(result, "artifact_id")
        assert hasattr(result, "schema_id")
        assert hasattr(result, "valid")
        assert hasattr(result, "errors")
        assert hasattr(result, "warnings")

    def test_to_dict_roundtrip(self) -> None:
        """ContractValidationResult must serialize and deserialize correctly."""
        original = ContractValidationResult(
            artifact_id="test_roundtrip",
            schema_id="derived_elements",
            valid=False,
            errors=["Error 1", "Error 2"],
            warnings=["Warning 1"],
        )

        data = original.to_dict()
        restored = ContractValidationResult.from_dict(data)

        assert restored.artifact_id == original.artifact_id
        assert restored.schema_id == original.schema_id
        assert restored.valid == original.valid
        assert restored.errors == original.errors
        assert restored.warnings == original.warnings

    def test_valid_result_has_no_errors(self) -> None:
        """A valid ContractValidationResult should typically have no errors."""
        result = validate_artifact_contract(
            artifact={
                "file_uid": "F0001",
                "rev_id": "rev_001",
                "atoms": [],
            },
            schema_id="atoms",
            artifact_id="valid_test",
        )

        # Valid results should not have errors
        if result.valid:
            assert result.errors == []


class TestCoverageTrackerInvariants:
    """Invariants for the CoverageTracker class (foundation for CON-0002)."""

    def test_coverage_invariant_split_preserves_coverage(self) -> None:
        """Splitting a fragment must preserve 100% coverage.

        Key invariant: At any point, leaf fragments must cover 100% of original.
        """
        tracker = CoverageTracker()
        content = "ABCDEFGHIJ"  # 10 characters
        root = tracker.initialize("test.md", content)

        # Verify initial coverage
        is_complete, gaps = tracker.verify_coverage("test.md")
        assert is_complete is True
        assert gaps == []

        # Split the fragment
        children = tracker.split(root.id, [3, 7])

        # Coverage must still be complete after split
        is_complete_after, gaps_after = tracker.verify_coverage("test.md")
        assert is_complete_after is True, f"Coverage broken after split, gaps: {gaps_after}"
        assert gaps_after == []

        # Children should cover the full content
        assert len(children) == 3
        total_length = sum(len(c.content) for c in children)
        assert total_length == 10

    def test_coverage_invariant_projection_preserves_coverage(self) -> None:
        """Projecting a fragment must preserve coverage tracking.

        Projected fragments still trace back to original content.
        """
        tracker = CoverageTracker()
        content = "Original prose content here."
        root = tracker.initialize("test.md", content)

        # Project the fragment
        tracker.project(root.id, "requirement", "Structured: requirement")

        # Coverage must still be complete
        is_complete, gaps = tracker.verify_coverage("test.md")
        assert is_complete is True
        assert gaps == []

        # Fragment should be marked as projected
        assert tracker.fragments[root.id].status == FragmentStatus.PROJECTED

    def test_coverage_report_structure(self) -> None:
        """Coverage report must contain required fields."""
        tracker = CoverageTracker()
        content = "Test content for coverage report."
        tracker.initialize("test.md", content)

        report = tracker.get_coverage_report("test.md")

        # Required fields in coverage report
        assert "file" in report
        assert "original_length" in report
        assert "leaf_count" in report
        assert "complete" in report
        assert "gaps" in report
        assert "by_status" in report

    def test_fragment_status_transitions_valid(self) -> None:
        """Fragment status transitions must follow valid paths.

        Valid transitions:
        - PROSE -> PROJECTED (successful projection)
        - PROSE -> NOISE (marked as noise)
        - PROSE -> SPLIT (when split into children)
        """
        tracker = CoverageTracker()
        content = "Content A|Content B|Content C"
        root = tracker.initialize("test.md", content)

        # Initial status is PROSE
        assert tracker.fragments[root.id].status == FragmentStatus.PROSE

        # Split -> status becomes SPLIT
        children = tracker.split(root.id, [10, 20])
        assert tracker.fragments[root.id].status == FragmentStatus.SPLIT

        # Project child -> status becomes PROJECTED
        tracker.project(children[0].id, "spec", "Projected content")
        assert tracker.fragments[children[0].id].status == FragmentStatus.PROJECTED

        # Mark child as noise -> status becomes NOISE
        tracker.mark_as_noise(children[1].id, "Circular justification")
        assert tracker.fragments[children[1].id].status == FragmentStatus.NOISE


class TestValidationFunctionInvariants:
    """Invariants for the validate_artifact_contract function (ALG-COMP-0001)."""

    def test_validation_always_returns_result(self) -> None:
        """validate_artifact_contract must always return a ContractValidationResult.

        It should never raise an exception for normal validation scenarios.
        """
        registry = SchemaRegistry()

        # Valid artifact
        result1 = validate_artifact_contract(
            artifact={"file_uid": "F0001", "rev_id": "rev_001", "atoms": []},
            schema_id="atoms",
            registry=registry,
        )
        assert isinstance(result1, ContractValidationResult)

        # Invalid artifact
        result2 = validate_artifact_contract(
            artifact={"invalid": "data"},
            schema_id="atoms",
            registry=registry,
        )
        assert isinstance(result2, ContractValidationResult)

        # Unknown schema
        result3 = validate_artifact_contract(
            artifact={"test": "data"},
            schema_id="nonexistent",
            registry=registry,
        )
        assert isinstance(result3, ContractValidationResult)
        assert result3.valid is False

    def test_validation_errors_are_descriptive(self) -> None:
        """Validation errors must be descriptive enough for debugging."""
        result = validate_artifact_contract(
            artifact={"missing_everything": True},
            schema_id="atoms",
            artifact_id="test_descriptive",
        )

        assert result.valid is False
        assert len(result.errors) > 0
        # Errors should mention what's wrong
        error_text = " ".join(result.errors).lower()
        assert "required" in error_text or "missing" in error_text or "file_uid" in error_text


class TestAtomAccountingInvariants:
    """Invariants for atom accounting (CON-0002 foundation)."""

    @pytest.mark.parametrize(
        "scenario",
        ["all_projected", "some_remainder", "some_excluded"],
    )
    def test_every_fragment_has_valid_status(self, scenario: str) -> None:
        """Every fragment must have a valid FragmentStatus.

        Invariant: No fragment should have an undefined or invalid status.
        """
        tracker = CoverageTracker()
        content = "Line 1|Line 2|Line 3"
        root = tracker.initialize("test.md", content)
        children = tracker.split(root.id, [7, 14])

        if scenario == "all_projected":
            for child in children:
                tracker.project(child.id, "spec", f"Projected: {child.content}")
        elif scenario == "some_remainder":
            tracker.project(children[0].id, "spec", "Projected")
            # children[1] and children[2] remain as PROSE
        elif scenario == "some_excluded":
            tracker.project(children[0].id, "spec", "Projected")
            tracker.project(children[1].id, "spec", "Projected")
            tracker.mark_as_noise(children[2].id, "Noise")

        # Verify all fragments have valid status
        for frag_id, fragment in tracker.fragments.items():
            assert isinstance(fragment.status, FragmentStatus), (
                f"Fragment {frag_id} has invalid status"
            )

    def test_leaf_fragments_cover_original(self) -> None:
        """Leaf fragments must cover 100% of original content.

        This is the fundamental coverage invariant that enables CON-0002.
        """
        tracker = CoverageTracker()
        content = "0123456789"  # 10 characters
        root = tracker.initialize("test.md", content)

        # Perform some operations
        children = tracker.split(root.id, [5])
        tracker.project(children[0].id, "spec", "Projected first half")

        # Verify coverage
        is_complete, gaps = tracker.verify_coverage("test.md")
        assert is_complete is True, f"Coverage incomplete, gaps: {gaps}"

        # Verify leaf content length
        leaves = tracker.get_leaves("test.md")
        total_span = sum(f.total_span_length for f in leaves)
        assert total_span == 10, f"Total span {total_span} != original length 10"
