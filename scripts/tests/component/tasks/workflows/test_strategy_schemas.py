"""Tests for test-strategy schema validation and structured output parsing.

This test module validates:
1. JSON Schema files are valid and loadable
2. Input schema validation with valid/invalid payloads
3. Output schema validation with agent-like outputs
4. Review schema validation
5. Graceful fallback behavior for unstructured output
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from scripts.tasks.workflows.test_automation import (
    parse_strategy_output_structured,
    parse_strategy_review_output_structured,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
SCHEMAS_DIR = PROJECT_ROOT / "docs" / "schemas"


# =============================================================================
# Schema Loading and Validation Tests
# =============================================================================


class TestSchemaLoading:
    """Tests for loading and validating JSON Schema files."""

    def test_input_schema_loads_and_is_valid(self) -> None:
        """Should load input schema and validate it as a valid JSON Schema."""
        schema_path = SCHEMAS_DIR / "test-strategy-input.schema.json"
        assert schema_path.exists(), f"Input schema not found at {schema_path}"

        with schema_path.open() as f:
            schema = json.load(f)

        # Validate that it's a valid JSON Schema Draft-07
        jsonschema.validators.Draft7Validator.check_schema(schema)

        # Check required top-level properties
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "mode" in schema["properties"]
        assert "target_files" in schema["properties"]

    def test_output_schema_loads_and_is_valid(self) -> None:
        """Should load output schema and validate it as a valid JSON Schema."""
        schema_path = SCHEMAS_DIR / "test-strategy-output.schema.json"
        assert schema_path.exists(), f"Output schema not found at {schema_path}"

        with schema_path.open() as f:
            schema = json.load(f)

        # Validate that it's a valid JSON Schema Draft-07
        jsonschema.validators.Draft7Validator.check_schema(schema)

        # Check required top-level properties
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "summary" in schema["properties"]
        assert "tier_assignments" in schema["properties"]
        assert "test_file_mapping" in schema["properties"]

    def test_review_schema_loads_and_is_valid(self) -> None:
        """Should load review schema and validate it as a valid JSON Schema."""
        schema_path = SCHEMAS_DIR / "test-strategy-review.schema.json"
        assert schema_path.exists(), f"Review schema not found at {schema_path}"

        with schema_path.open() as f:
            schema = json.load(f)

        # Validate that it's a valid JSON Schema Draft-07
        jsonschema.validators.Draft7Validator.check_schema(schema)

        # Check required top-level properties
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "status" in schema["properties"]


# =============================================================================
# Input Schema Validation Tests
# =============================================================================


class TestInputSchemaValidation:
    """Tests for validating input payloads against the input schema."""

    @pytest.fixture
    def input_schema(self) -> dict[str, Any]:
        """Load the input schema."""
        schema_path = SCHEMAS_DIR / "test-strategy-input.schema.json"
        with schema_path.open() as f:
            result: dict[str, Any] = json.load(f)
            return result

    def test_valid_generate_mode_input(self, input_schema: dict[str, Any]) -> None:
        """Should validate a valid generate mode input."""
        payload = {
            "mode": "generate",
            "target_files": [
                {
                    "path": "app/services/user.py",
                    "change_type": "MODIFY",
                    "functions_changed": ["create_user", "delete_user"],
                }
            ],
            "context": {
                "analysis_description": "Added email verification",
                "git_diff": "@@ -45,6 +45,10 @@ def create_user...",
                "existing_tests": ["tests/unit/test_user.py"],
            },
        }

        # Should not raise validation error
        jsonschema.validate(instance=payload, schema=input_schema)

    def test_valid_review_mode_input(self, input_schema: dict[str, Any]) -> None:
        """Should validate a valid review mode input."""
        payload = {
            "mode": "review",
            "target_files": [{"path": "app/services/user.py"}],
            "strategy_document": "## Strategy\nTier: unit\n...",
            "proposed_plan": "## Test Plan\n1. test_create_user\n...",
        }

        # Should not raise validation error
        jsonschema.validate(instance=payload, schema=input_schema)

    def test_valid_revise_mode_input(self, input_schema: dict[str, Any]) -> None:
        """Should validate a valid revise mode input."""
        payload = {
            "mode": "revise",
            "target_files": [{"path": "app/services/user.py"}],
            "coverage_gaps": [
                {
                    "function": "create_user",
                    "file": "app/services/user.py",
                    "line_coverage": 45.0,
                    "branch_coverage": 30.0,
                }
            ],
        }

        # Should not raise validation error
        jsonschema.validate(instance=payload, schema=input_schema)

    def test_invalid_input_missing_required_fields(self, input_schema: dict[str, Any]) -> None:
        """Should reject input missing required fields."""
        payload = {
            "mode": "generate",
            # Missing target_files
        }

        with pytest.raises(jsonschema.ValidationError, match="'target_files' is a required"):
            jsonschema.validate(instance=payload, schema=input_schema)

    def test_invalid_mode_value(self, input_schema: dict[str, Any]) -> None:
        """Should reject input with invalid mode value."""
        payload = {
            "mode": "invalid_mode",
            "target_files": [{"path": "app/services/user.py"}],
        }

        with pytest.raises(jsonschema.ValidationError, match="'invalid_mode' is not one of"):
            jsonschema.validate(instance=payload, schema=input_schema)

    def test_review_mode_requires_strategy_and_plan(self, input_schema: dict[str, Any]) -> None:
        """Should reject review mode input without strategy_document and proposed_plan."""
        payload = {
            "mode": "review",
            "target_files": [{"path": "app/services/user.py"}],
            # Missing strategy_document and proposed_plan
        }

        with pytest.raises(jsonschema.ValidationError, match="'strategy_document' is a required"):
            jsonschema.validate(instance=payload, schema=input_schema)

    def test_revise_mode_requires_coverage_gaps(self, input_schema: dict[str, Any]) -> None:
        """Should reject revise mode input without coverage_gaps."""
        payload = {
            "mode": "revise",
            "target_files": [{"path": "app/services/user.py"}],
            # Missing coverage_gaps
        }

        with pytest.raises(jsonschema.ValidationError, match="'coverage_gaps' is a required"):
            jsonschema.validate(instance=payload, schema=input_schema)


# =============================================================================
# Output Schema Validation Tests
# =============================================================================


class TestOutputSchemaValidation:
    """Tests for validating output payloads against the output schema."""

    @pytest.fixture
    def output_schema(self) -> dict[str, Any]:
        """Load the output schema."""
        schema_path = SCHEMAS_DIR / "test-strategy-output.schema.json"
        with schema_path.open() as f:
            result: dict[str, Any] = json.load(f)
            return result

    def test_valid_full_output_with_all_fields(self, output_schema: dict[str, Any]) -> None:
        """Should validate a complete output with all fields."""
        payload = {
            "summary": "Comprehensive testing strategy for user service",
            "tier_assignments": [
                {
                    "file": "app/services/user.py",
                    "tier": "unit",
                    "coverage_type": "line_branch",
                    "coverage_target": 80,
                    "rationale": "Service layer with complex business logic",
                    "functions": [
                        {
                            "name": "create_user",
                            "test_type": "line_branch",
                            "priority": "high",
                            "notes": "Complex branching requires parametrized tests",
                        }
                    ],
                }
            ],
            "testing_patterns": {
                "fixtures_required": [
                    {"name": "user_factory", "exists": True, "path": "tests/conftest.py"}
                ],
                "mocking_strategies": [
                    {
                        "target": "app.infrastructure.email.EmailClient",
                        "approach": "dependency_injection",
                        "notes": "Inject mock via constructor",
                    }
                ],
                "assertion_patterns": [
                    {
                        "pattern": "response_schema_validation",
                        "description": "Use pydantic model_validate",
                    }
                ],
            },
            "use_cases": {
                "new": [
                    {
                        "id": "UC-USER-001",
                        "endpoint": "/api/v1/users",
                        "method": "POST",
                        "description": "Create user succeeds",
                        "test_tier": "integration",
                    }
                ],
                "existing_applicable": [
                    {"id": "UC-AUTH-003", "notes": "Existing auth flow covers token validation"}
                ],
            },
            "edge_cases": [
                {
                    "scenario": "Duplicate email registration",
                    "severity": "high",
                    "test_approach": "Expect 409 Conflict response",
                }
            ],
            "test_file_mapping": [
                {
                    "source": "app/services/user.py",
                    "tests": [
                        {
                            "path": "tests/unit/test_user.py",
                            "operation": "MODIFY",
                            "tier": "unit",
                        }
                    ],
                }
            ],
            "guidance_for_planner": [
                "Use parametrized tests for validation edge cases",
                "Mock EmailClient at service layer, not repository",
            ],
        }

        # Should not raise validation error
        jsonschema.validate(instance=payload, schema=output_schema)

    def test_valid_minimal_output_summary_only(self, output_schema: dict[str, Any]) -> None:
        """Should validate minimal output with only required fields."""
        payload = {
            "summary": "Basic testing strategy",
            "tier_assignments": [
                {
                    "file": "app/services/user.py",
                    "tier": "unit",
                    "coverage_type": "line_branch",
                    "coverage_target": 80,
                    "rationale": "Standard service layer testing",
                }
            ],
            "test_file_mapping": [
                {
                    "source": "app/services/user.py",
                    "tests": [
                        {
                            "path": "tests/unit/test_user.py",
                            "operation": "NEW",
                            "tier": "unit",
                        }
                    ],
                }
            ],
        }

        # Should not raise validation error
        jsonschema.validate(instance=payload, schema=output_schema)

    def test_invalid_output_wrong_tier_value(self, output_schema: dict[str, Any]) -> None:
        """Should reject output with invalid tier value."""
        payload = {
            "summary": "Testing strategy",
            "tier_assignments": [
                {
                    "file": "app/services/user.py",
                    "tier": "invalid_tier",  # Invalid tier
                    "coverage_type": "line_branch",
                    "coverage_target": 80,
                    "rationale": "Test",
                }
            ],
            "test_file_mapping": [
                {
                    "source": "app/services/user.py",
                    "tests": [
                        {"path": "tests/unit/test_user.py", "operation": "NEW", "tier": "unit"}
                    ],
                }
            ],
        }

        with pytest.raises(jsonschema.ValidationError, match="'invalid_tier' is not one of"):
            jsonschema.validate(instance=payload, schema=output_schema)

    def test_output_matches_parse_strategy_output_structured_returns(
        self, output_schema: dict[str, Any]
    ) -> None:
        """Should validate that parse_strategy_output_structured returns valid output."""
        # Test with a full YAML output
        agent_output = """STRATEGY:
```yaml
summary: "Comprehensive testing strategy for user service"
tier_assignments:
  - file: "app/services/user.py"
    tier: "unit"
    coverage_type: "line_branch"
    coverage_target: 80
    rationale: "Service layer with complex logic"
test_file_mapping:
  - source: "app/services/user.py"
    tests:
      - path: "tests/unit/test_user.py"
        operation: "NEW"
        tier: "unit"
```"""

        parsed = parse_strategy_output_structured(agent_output)

        # Convert TypedDict to regular dict for validation
        payload = dict(parsed)

        # Should not raise validation error
        jsonschema.validate(instance=payload, schema=output_schema)


# =============================================================================
# Review Schema Validation Tests
# =============================================================================


class TestReviewSchemaValidation:
    """Tests for validating review output payloads against the review schema."""

    @pytest.fixture
    def review_schema(self) -> dict[str, Any]:
        """Load the review schema."""
        schema_path = SCHEMAS_DIR / "test-strategy-review.schema.json"
        with schema_path.open() as f:
            result: dict[str, Any] = json.load(f)
            return result

    def test_approved_status(self, review_schema: dict[str, Any]) -> None:
        """Should validate APPROVED status."""
        payload = {"status": "APPROVED"}

        # Should not raise validation error
        jsonschema.validate(instance=payload, schema=review_schema)

    def test_feedback_status_with_issues(self, review_schema: dict[str, Any]) -> None:
        """Should validate FEEDBACK status with issues."""
        payload = {
            "status": "FEEDBACK",
            "issues": [
                {
                    "category": "missing_tier",
                    "description": "Integration tests missing for user deletion",
                    "strategy_reference": "tier_assignments[0].functions[1]",
                    "severity": "high",
                },
                {
                    "category": "missing_edge_case",
                    "description": "No tests for duplicate email scenario",
                    "severity": "medium",
                },
            ],
        }

        # Should not raise validation error
        jsonschema.validate(instance=payload, schema=review_schema)

    def test_blocked_status_with_reason(self, review_schema: dict[str, Any]) -> None:
        """Should validate BLOCKED status with reason."""
        payload = {
            "status": "BLOCKED",
            "reason": "Cannot review - strategy document is missing or malformed",
        }

        # Should not raise validation error
        jsonschema.validate(instance=payload, schema=review_schema)

    def test_invalid_status_value(self, review_schema: dict[str, Any]) -> None:
        """Should reject invalid status value."""
        payload = {"status": "INVALID_STATUS"}

        with pytest.raises(jsonschema.ValidationError, match="'INVALID_STATUS' is not one of"):
            jsonschema.validate(instance=payload, schema=review_schema)

    def test_feedback_requires_issues(self, review_schema: dict[str, Any]) -> None:
        """Should reject FEEDBACK status without issues."""
        payload = {
            "status": "FEEDBACK",
            # Missing issues
        }

        with pytest.raises(jsonschema.ValidationError, match="'issues' is a required"):
            jsonschema.validate(instance=payload, schema=review_schema)

    def test_blocked_requires_reason(self, review_schema: dict[str, Any]) -> None:
        """Should reject BLOCKED status without reason."""
        payload = {
            "status": "BLOCKED",
            # Missing reason
        }

        with pytest.raises(jsonschema.ValidationError, match="'reason' is a required"):
            jsonschema.validate(instance=payload, schema=review_schema)


# =============================================================================
# Graceful Fallback Tests
# =============================================================================


class TestGracefulFallback:
    """Tests for graceful fallback behavior when parsing unstructured output."""

    def test_parse_strategy_output_structured_handles_unstructured_output(self) -> None:
        """Should handle unstructured output gracefully by returning summary field."""
        output = "This is just plain text without any YAML structure."

        result = parse_strategy_output_structured(output)

        assert "summary" in result
        assert "plain text" in result["summary"]
        # Should not have other structured fields
        assert "tier_assignments" not in result
        assert "test_file_mapping" not in result

    def test_parse_strategy_output_structured_returns_summary_on_yaml_parse_failure(
        self,
    ) -> None:
        """Should return dict with summary field when YAML parsing fails."""
        output = """STRATEGY:
```yaml
summary: "Unclosed quote
invalid: yaml: structure:
```"""

        result = parse_strategy_output_structured(output)

        assert "summary" in result
        assert isinstance(result["summary"], str)
        # Summary should contain the original content or error message
        assert "YAML parsing failed" in result["summary"] or "Unclosed quote" in result["summary"]

    def test_parse_strategy_output_structured_handles_blocked_output(self) -> None:
        """Should handle BLOCKED output gracefully."""
        output = "BLOCKED: Cannot analyze - missing dependencies"

        result = parse_strategy_output_structured(output)

        assert "summary" in result
        assert "BLOCKED:" in result["summary"]
        assert "missing dependencies" in result["summary"]

    def test_parse_strategy_output_structured_handles_missing_strategy_marker(
        self,
    ) -> None:
        """Should handle output without STRATEGY marker."""
        output = "Some random output without the STRATEGY marker"

        result = parse_strategy_output_structured(output)

        assert "summary" in result
        assert "random output" in result["summary"]

    def test_parse_strategy_review_output_structured_handles_unstructured(self) -> None:
        """Should handle unstructured review output gracefully."""
        output = "Some random review output"

        result = parse_strategy_review_output_structured(output)

        assert result["status"] == "BLOCKED"
        assert "reason" in result
        assert "Unrecognized" in result["reason"]

    def test_parse_strategy_output_structured_adds_default_summary_when_missing(
        self,
    ) -> None:
        """Should add default summary when YAML has other fields but no summary."""
        output = """STRATEGY:
```yaml
tier_assignments:
  - file: "test.py"
    tier: "unit"
    coverage_type: "line_branch"
    coverage_target: 80
    rationale: "Test"
test_file_mapping:
  - source: "test.py"
    tests:
      - path: "tests/test.py"
        operation: "NEW"
        tier: "unit"
```"""

        result = parse_strategy_output_structured(output)

        assert "summary" in result
        assert "tier_assignments" in result
        # Should have a default summary since it was missing
        assert "Structured strategy output" in result["summary"] or result["summary"]


# =============================================================================
# Schema Validation Fallback Tests
# =============================================================================


class TestSchemaValidationFallback:
    """Tests for schema validation fallback behavior in structured parsers."""

    def test_parse_strategy_output_structured_validates_and_fallbacks_on_invalid(
        self,
    ) -> None:
        """Should fall back to summary-only when schema validation fails."""
        # Invalid tier value should trigger validation error
        output = """STRATEGY:
```yaml
summary: "Test strategy"
tier_assignments:
  - file: "test.py"
    tier: "invalid_tier_value"
    coverage_type: "line_branch"
    coverage_target: 80
    rationale: "Test"
test_file_mapping:
  - source: "test.py"
    tests:
      - path: "tests/test.py"
        operation: "NEW"
        tier: "unit"
```"""
        result = parse_strategy_output_structured(output)

        # Should fall back to summary with validation error message
        assert "summary" in result
        assert "Validation error" in result["summary"]
        # Should not have structured fields since validation failed
        assert "tier_assignments" not in result

    def test_parse_strategy_output_structured_accepts_valid_data(self) -> None:
        """Should accept valid structured data and return all fields."""
        output = """STRATEGY:
```yaml
summary: "Valid testing strategy"
tier_assignments:
  - file: "app/services/user.py"
    tier: "unit"
    coverage_type: "line_branch"
    coverage_target: 80
    rationale: "Standard service testing"
test_file_mapping:
  - source: "app/services/user.py"
    tests:
      - path: "tests/unit/test_user.py"
        operation: "NEW"
        tier: "unit"
```"""
        result = parse_strategy_output_structured(output)

        assert "summary" in result
        assert result["summary"] == "Valid testing strategy"
        assert "tier_assignments" in result
        assert "test_file_mapping" in result
        # No validation error in summary
        assert "Validation error" not in result["summary"]

    def test_parse_strategy_review_output_structured_validates_and_fallbacks(
        self,
    ) -> None:
        """Should fall back when review schema validation fails."""
        # Invalid issue category should trigger validation error
        output = """FEEDBACK:
```yaml
issues:
  - category: "invalid_category_value"
    description: "Some issue"
    severity: "high"
```"""
        result = parse_strategy_review_output_structured(output)

        # Should still have FEEDBACK status
        assert result["status"] == "FEEDBACK"
        assert "issues" in result
        # Validation error should be in the issue description
        issue_desc = result["issues"][0]["description"]
        assert "Validation error" in issue_desc

    def test_parse_strategy_review_output_structured_accepts_valid_feedback(
        self,
    ) -> None:
        """Should accept valid FEEDBACK with properly structured issues."""
        output = """FEEDBACK:
```yaml
issues:
  - category: "missing_tier"
    description: "Integration tests missing for user deletion"
    severity: "high"
```"""
        result = parse_strategy_review_output_structured(output)

        assert result["status"] == "FEEDBACK"
        assert "issues" in result
        assert len(result["issues"]) == 1
        assert result["issues"][0]["category"] == "missing_tier"
        # No validation error in description
        assert "Validation error" not in result["issues"][0]["description"]

    def test_parse_strategy_review_output_structured_blocked_validates(self) -> None:
        """Should validate BLOCKED status with reason."""
        output = """BLOCKED:
```yaml
reason: "Cannot review - strategy document is malformed"
```"""
        result = parse_strategy_review_output_structured(output)

        assert result["status"] == "BLOCKED"
        assert "reason" in result
        assert "malformed" in result["reason"]
        # No validation error
        assert "Validation error" not in result["reason"]
