"""Tests for CON-0011: Contract-Validated Outputs.

CON-0011 specifies that all agent outputs must be validated against their
contract schemas, and invalid outputs must be quarantined rather than
written to authority.

This module contains:
- xfail tests for features not yet implemented (quarantine, routing)
- passing tests for current validation functionality
"""

from __future__ import annotations

from typing import Any

import pytest
from spec_manager.compliance import (
    ContractValidationResult,
    SchemaRegistry,
    validate_artifact_contract,
)


class TestContractValidationResult:
    """Tests for the ContractValidationResult data structure (DS-COMP-0001)."""

    def test_valid_result_structure(self) -> None:
        """ContractValidationResult should have all required fields."""
        result = ContractValidationResult(
            artifact_id="test_001",
            schema_id="derived_elements",
            valid=True,
            errors=[],
            warnings=[],
        )

        assert result.artifact_id == "test_001"
        assert result.schema_id == "derived_elements"
        assert result.valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_invalid_result_with_errors(self) -> None:
        """ContractValidationResult should capture validation errors."""
        result = ContractValidationResult(
            artifact_id="test_002",
            schema_id="atoms",
            valid=False,
            errors=["Missing required field: atoms", "Invalid type for file_uid"],
            warnings=["Deprecated field used"],
        )

        assert result.valid is False
        assert len(result.errors) == 2
        assert "Missing required field: atoms" in result.errors
        assert len(result.warnings) == 1

    def test_to_dict_serialization(self) -> None:
        """ContractValidationResult.to_dict() should produce valid JSON structure."""
        result = ContractValidationResult(
            artifact_id="test_003",
            schema_id="task_plan",
            valid=True,
            errors=[],
            warnings=["jsonschema not installed"],
        )

        data = result.to_dict()

        assert data["artifact_id"] == "test_003"
        assert data["schema_id"] == "task_plan"
        assert data["valid"] is True
        assert data["errors"] == []
        assert data["warnings"] == ["jsonschema not installed"]

    def test_from_dict_deserialization(self) -> None:
        """ContractValidationResult.from_dict() should reconstruct from dict."""
        data = {
            "artifact_id": "test_004",
            "schema_id": "atoms",
            "valid": False,
            "errors": ["Error 1"],
            "warnings": [],
        }

        result = ContractValidationResult.from_dict(data)

        assert result.artifact_id == "test_004"
        assert result.schema_id == "atoms"
        assert result.valid is False
        assert result.errors == ["Error 1"]


class TestSchemaValidation:
    """Tests for schema-based contract validation."""

    def test_validate_valid_atoms_manifest(
        self,
        schema_registry: SchemaRegistry,
        valid_atoms_manifest: dict[str, Any],
    ) -> None:
        """Valid atoms manifest should pass validation."""
        result = validate_artifact_contract(
            artifact=valid_atoms_manifest,
            schema_id="atoms",
            artifact_id="valid_atoms",
            registry=schema_registry,
        )

        assert result.valid is True
        assert result.errors == []

    def test_validate_invalid_atoms_missing_required(
        self,
        schema_registry: SchemaRegistry,
        invalid_atoms_manifest_missing_required: dict[str, Any],
    ) -> None:
        """Atoms manifest missing required fields should fail validation."""
        result = validate_artifact_contract(
            artifact=invalid_atoms_manifest_missing_required,
            schema_id="atoms",
            artifact_id="invalid_atoms",
            registry=schema_registry,
        )

        assert result.valid is False
        assert len(result.errors) > 0
        # Should mention missing required fields
        error_text = " ".join(result.errors)
        assert "required" in error_text.lower() or "rev_id" in error_text or "atoms" in error_text

    def test_validate_invalid_atoms_bad_atom(
        self,
        schema_registry: SchemaRegistry,
        invalid_atoms_manifest_bad_atom: dict[str, Any],
    ) -> None:
        """Atoms manifest with invalid atom entry should fail validation."""
        result = validate_artifact_contract(
            artifact=invalid_atoms_manifest_bad_atom,
            schema_id="atoms",
            artifact_id="bad_atom",
            registry=schema_registry,
        )

        assert result.valid is False
        assert len(result.errors) > 0

    def test_validate_valid_derived_elements(
        self,
        schema_registry: SchemaRegistry,
        valid_derived_elements: dict[str, Any],
    ) -> None:
        """Valid derived elements should pass validation."""
        result = validate_artifact_contract(
            artifact=valid_derived_elements,
            schema_id="derived_elements",
            artifact_id="valid_derived",
            registry=schema_registry,
        )

        assert result.valid is True
        assert result.errors == []

    def test_validate_invalid_derived_elements(
        self,
        schema_registry: SchemaRegistry,
        invalid_derived_elements_missing_fields: dict[str, Any],
    ) -> None:
        """Derived elements with missing fields should fail validation."""
        result = validate_artifact_contract(
            artifact=invalid_derived_elements_missing_fields,
            schema_id="derived_elements",
            artifact_id="invalid_derived",
            registry=schema_registry,
        )

        assert result.valid is False
        assert len(result.errors) > 0

    def test_validate_unknown_schema_fails(
        self,
        schema_registry: SchemaRegistry,
    ) -> None:
        """Validation with unknown schema ID should fail gracefully."""
        result = validate_artifact_contract(
            artifact={"test": "data"},
            schema_id="nonexistent_schema",
            artifact_id="test",
            registry=schema_registry,
        )

        assert result.valid is False
        assert any("Unknown schema ID" in e for e in result.errors)


class TestSchemaRegistry:
    """Tests for SchemaRegistry functionality."""

    def test_get_available_schemas(self, schema_registry: SchemaRegistry) -> None:
        """SchemaRegistry should list all available schema IDs."""
        schemas = schema_registry.get_available_schemas()

        assert "atoms" in schemas
        assert "derived_elements" in schemas
        assert "section_map" in schemas
        assert "task_plan" in schemas
        assert len(schemas) == 8  # All 8 design schemas

    def test_get_schema_loads_valid_json(self, schema_registry: SchemaRegistry) -> None:
        """SchemaRegistry.get_schema() should load valid JSON schema."""
        schema = schema_registry.get_schema("atoms")

        assert "$schema" in schema
        assert schema["type"] == "object"
        assert "properties" in schema

    def test_get_schema_caches_loaded_schemas(self, schema_registry: SchemaRegistry) -> None:
        """SchemaRegistry should cache loaded schemas."""
        schema1 = schema_registry.get_schema("atoms")
        schema2 = schema_registry.get_schema("atoms")

        # Should be the exact same object (cached)
        assert schema1 is schema2

    def test_is_schema_available(self, schema_registry: SchemaRegistry) -> None:
        """is_schema_available should check if schema file exists."""
        assert schema_registry.is_schema_available("atoms") is True
        assert schema_registry.is_schema_available("nonexistent") is False

    def test_clear_cache(self, schema_registry: SchemaRegistry) -> None:
        """clear_cache should remove all cached schemas."""
        _ = schema_registry.get_schema("atoms")
        assert len(schema_registry._loaded) > 0

        schema_registry.clear_cache()
        assert len(schema_registry._loaded) == 0


class TestQuarantineBehavior:
    """Tests for quarantine behavior (CON-0011).

    These tests verify that invalid outputs are quarantined and not written
    to authority. Currently marked as xfail because the quarantine routing
    infrastructure is not yet implemented.
    """

    @pytest.mark.xfail(reason="Quarantine routing not yet implemented - Phase 1 foundation only")
    def test_invalid_output_quarantined(
        self,
        sample_invalid_artifact_for_quarantine: dict[str, Any],
    ) -> None:
        """Invalid agent output must be quarantined, not written to authority.

        CON-0011 requirement: Invalid outputs should be routed to quarantine
        directory and not written to the authority workspace.
        """
        # This test requires validate_and_route() function which is not yet implemented
        # The function would:
        # 1. Validate the artifact against schema
        # 2. If invalid, write to quarantine directory
        # 3. Return result indicating quarantine status
        from spec_manager.compliance import validate_and_route  # type: ignore[attr-defined]

        result = validate_and_route(
            sample_invalid_artifact_for_quarantine,
            schema_id="derived_elements",
        )

        assert result.quarantined is True
        assert result.written_to_authority is False

    @pytest.mark.xfail(reason="Quarantine routing not yet implemented - Phase 1 foundation only")
    def test_valid_output_not_quarantined(
        self,
        sample_valid_artifact_for_quarantine: dict[str, Any],
    ) -> None:
        """Valid agent output should pass through to authority, not quarantined.

        CON-0011 requirement: Valid outputs should be written to authority
        workspace, not quarantined.
        """
        from spec_manager.compliance import validate_and_route  # type: ignore[attr-defined]

        result = validate_and_route(
            sample_valid_artifact_for_quarantine,
            schema_id="derived_elements",
        )

        assert result.quarantined is False
        assert result.written_to_authority is True

    @pytest.mark.xfail(reason="Quarantine routing not yet implemented - Phase 1 foundation only")
    def test_quarantine_preserves_original_artifact(
        self,
        sample_invalid_artifact_for_quarantine: dict[str, Any],
    ) -> None:
        """Quarantined artifacts should preserve the original content for debugging.

        When an artifact is quarantined, the original content should be saved
        along with the validation errors for debugging purposes.
        """
        from spec_manager.compliance import validate_and_route  # type: ignore[attr-defined]

        result = validate_and_route(
            sample_invalid_artifact_for_quarantine,
            schema_id="derived_elements",
        )

        assert result.quarantined is True
        assert result.original_artifact == sample_invalid_artifact_for_quarantine
        assert len(result.validation_errors) > 0
