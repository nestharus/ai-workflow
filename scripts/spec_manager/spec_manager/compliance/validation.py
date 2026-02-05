"""Contract validation for agent outputs.

This module provides the ContractValidationResult dataclass (DS-COMP-0001)
and validation functions for checking agent outputs against JSON schemas.

Public API:
    ContractValidationResult: Result of validating an artifact against its contract schema
    validate_artifact_contract: Validate an artifact against its schema (ALG-COMP-0001)

Usage:
    from spec_manager.compliance.validation import (
        ContractValidationResult,
        validate_artifact_contract,
    )

    result = validate_artifact_contract(
        artifact={"elements": [...]},
        schema_id="derived_elements",
        artifact_id="output_001",
    )
    if result.valid:
        print("Artifact is valid")
    else:
        print(f"Errors: {result.errors}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .schema_registry import SchemaRegistry, get_default_registry

_logger = logging.getLogger(__name__)

# Try to import jsonschema for validation
try:
    import jsonschema
    from jsonschema import Draft202012Validator, ValidationError

    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False
    Draft202012Validator = None  # type: ignore[assignment, misc]
    ValidationError = Exception  # type: ignore[assignment, misc]


@dataclass
class ContractValidationResult:
    """Result of validating an artifact against its contract schema.

    This is the DS-COMP-0001 data structure from the design specification.
    It captures the outcome of schema validation including any errors or warnings.

    Attributes:
        artifact_id: Identifier for the artifact being validated.
        schema_id: The schema used for validation.
        valid: Whether the artifact passed validation.
        errors: List of validation error messages.
        warnings: List of validation warning messages.
    """

    artifact_id: str
    schema_id: str
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON output."""
        return {
            "artifact_id": self.artifact_id,
            "schema_id": self.schema_id,
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContractValidationResult:
        """Deserialize from dictionary.

        Args:
            data: Dictionary with validation result data.

        Returns:
            ContractValidationResult instance.
        """
        return cls(
            artifact_id=data["artifact_id"],
            schema_id=data["schema_id"],
            valid=data["valid"],
            errors=data.get("errors", []),
            warnings=data.get("warnings", []),
        )


def validate_artifact_contract(
    artifact: dict[str, Any],
    schema_id: str,
    artifact_id: str = "unknown",
    registry: SchemaRegistry | None = None,
) -> ContractValidationResult:
    """Validate an artifact against its contract schema.

    This implements ALG-COMP-0001 from the design specification.
    It validates the artifact structure against the JSON schema and
    collects all validation errors.

    Args:
        artifact: The artifact dictionary to validate.
        schema_id: The schema ID to validate against (e.g., "derived_elements").
        artifact_id: Optional identifier for the artifact (for error reporting).
        registry: Optional SchemaRegistry instance. Uses default if not provided.

    Returns:
        ContractValidationResult with validation outcome and any errors.

    Note:
        If jsonschema library is not installed, validation always passes
        with a warning. Install jsonschema for full validation support.
    """
    if registry is None:
        registry = get_default_registry()

    warnings: list[str] = []
    errors: list[str] = []

    # Check if jsonschema is available
    if not _HAS_JSONSCHEMA:
        _logger.warning("jsonschema library not installed; skipping schema validation")
        return ContractValidationResult(
            artifact_id=artifact_id,
            schema_id=schema_id,
            valid=True,
            errors=[],
            warnings=["jsonschema library not installed; validation skipped"],
        )

    # Load the schema
    try:
        schema = registry.get_schema(schema_id)
    except KeyError as e:
        _logger.error(f"Unknown schema ID: {schema_id}")
        return ContractValidationResult(
            artifact_id=artifact_id,
            schema_id=schema_id,
            valid=False,
            errors=[f"Unknown schema ID: {schema_id}. {e}"],
            warnings=[],
        )
    except FileNotFoundError as e:
        _logger.error(f"Schema file not found: {e}")
        return ContractValidationResult(
            artifact_id=artifact_id,
            schema_id=schema_id,
            valid=False,
            errors=[f"Schema file not found: {e}"],
            warnings=[],
        )

    # Perform JSON Schema validation
    try:
        validator = Draft202012Validator(schema)
        validation_errors = list(validator.iter_errors(artifact))

        if validation_errors:
            for error in validation_errors:
                # Format the error path and message
                path = ".".join(str(p) for p in error.absolute_path) if error.absolute_path else "root"
                errors.append(f"[{path}] {error.message}")

            return ContractValidationResult(
                artifact_id=artifact_id,
                schema_id=schema_id,
                valid=False,
                errors=errors,
                warnings=warnings,
            )

        return ContractValidationResult(
            artifact_id=artifact_id,
            schema_id=schema_id,
            valid=True,
            errors=[],
            warnings=warnings,
        )

    except Exception as e:
        _logger.exception(f"Unexpected error during validation: {e}")
        return ContractValidationResult(
            artifact_id=artifact_id,
            schema_id=schema_id,
            valid=False,
            errors=[f"Validation error: {e}"],
            warnings=warnings,
        )
