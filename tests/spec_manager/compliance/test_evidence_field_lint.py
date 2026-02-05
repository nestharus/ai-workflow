"""Tests for evidence field linting (CON-0021, ALG-COMP-0005).

Tests:
- test_validate_evid_value: Validate EVID format strings
- test_is_evidence_field: Identify evidence field names
- test_scan_evidence_fields_valid: Valid EVID-only artifacts pass
- test_scan_evidence_fields_legacy: Legacy pointers in evidence fail
- test_scan_evidence_fields_spec_snapshot: spec_snapshot in evidence fail
- test_scan_evidence_fields_derived_warning: Derived paths in free text warn
- test_scan_evidence_fields_allowlist: Allowlist suppression works
- test_lint_l1_artifact: Full artifact linting
"""

import json
import tempfile
from pathlib import Path

import pytest

from spec_manager.compliance.evidence_field_lint import (
    LintResult,
    is_evidence_field,
    lint_l1_artifact,
    scan_evidence_fields,
    scan_for_forbidden_output_signatures,
    validate_evid_value,
)


class TestValidateEvidValue:
    """Test EVID value validation."""

    def test_valid_evid_values(self) -> None:
        """Test valid EVID format strings."""
        valid_values = [
            "EVID-F0001-R0001-L1-L1",
            "EVID-F0001-R0001-L1-L25",
            "EVID-F9999-R9999-L100-L200",
        ]
        for value in valid_values:
            assert validate_evid_value(value) is True, f"Expected valid: {value}"

    def test_invalid_evid_values(self) -> None:
        """Test invalid EVID format strings."""
        invalid_values = [
            "",
            "not-an-evid",
            "F0001-R0001-L1-L25",  # Missing EVID prefix
            "EVID-F001-R0001-L1-L25",  # Wrong file_uid
            "[EVID-F0001-R0001-L1-L25]",  # With brackets
            "[F0001::INTRO]",  # Legacy format
        ]
        for value in invalid_values:
            assert validate_evid_value(value) is False, f"Expected invalid: {value}"


class TestIsEvidenceField:
    """Test evidence field name detection."""

    def test_known_evidence_fields(self) -> None:
        """Test known evidence field names."""
        known_fields = [
            "evidence",
            "evidence_id",
            "evidence_ids",
            "evidence_sources",
            "citations",
            "source_evidence",
            "supporting_evidence",
        ]
        for field in known_fields:
            assert is_evidence_field(field) is True, f"Expected evidence field: {field}"

    def test_non_evidence_fields(self) -> None:
        """Test non-evidence field names."""
        non_evidence_fields = [
            "description",
            "rationale",
            "file_id",
            "section_id",
            "content",
        ]
        for field in non_evidence_fields:
            assert is_evidence_field(field) is False, f"Expected non-evidence: {field}"

    def test_case_insensitive(self) -> None:
        """Test case-insensitive matching."""
        assert is_evidence_field("EVIDENCE") is True
        assert is_evidence_field("Evidence") is True
        assert is_evidence_field("  evidence  ") is True


class TestScanEvidenceFields:
    """Test artifact scanning for evidence field violations."""

    def test_valid_evid_only_artifact(self) -> None:
        """Test that valid EVID-only artifacts pass."""
        artifact = {
            "file_id": "F0001",
            "evidence": ["EVID-F0001-R0001-L1-L10", "EVID-F0001-R0001-L15-L20"],
            "description": "Test artifact",
        }
        errors, warnings = scan_evidence_fields(artifact)
        assert len(errors) == 0
        assert len(warnings) == 0

    def test_legacy_pointer_in_evidence_fails(self) -> None:
        """Test that legacy pointers in evidence fields cause errors."""
        artifact = {
            "file_id": "F0001",
            "evidence": ["[F0001::INTRO]"],
        }
        errors, warnings = scan_evidence_fields(artifact)
        assert len(errors) == 1
        assert "Legacy citation" in errors[0]

    def test_spec_snapshot_in_evidence_fails(self) -> None:
        """Test that spec_snapshot pointers in evidence fields cause errors."""
        artifact = {
            "file_id": "F0001",
            "evidence": ["[spec_snapshot/file.md::SEC-F0001-0001]"],
        }
        errors, warnings = scan_evidence_fields(artifact)
        assert len(errors) == 1
        assert "Legacy citation" in errors[0]

    def test_lib_pointer_in_evidence_fails(self) -> None:
        """Test that LIB pointers in evidence fields cause errors."""
        artifact = {
            "file_id": "F0001",
            "evidence_sources": ["[LIB-0001::spec.md::SEC-F0001-0001]"],
        }
        errors, warnings = scan_evidence_fields(artifact)
        assert len(errors) == 1

    def test_derived_path_in_freetext_warns(self) -> None:
        """Test that derived artifact paths in free text cause warnings."""
        artifact = {
            "file_id": "F0001",
            "description": "See runs/001/artifacts/file.json for details",
        }
        errors, warnings = scan_evidence_fields(artifact)
        assert len(errors) == 0
        assert len(warnings) == 1
        assert "Derived artifact" in warnings[0]

    def test_nested_evidence_fields(self) -> None:
        """Test scanning nested evidence fields."""
        artifact = {
            "elements": [
                {
                    "id": "elem-1",
                    "evidence": ["[F0001::SECTION]"],  # Should error
                },
                {
                    "id": "elem-2",
                    "evidence": ["EVID-F0001-R0001-L1-L5"],  # Should pass
                },
            ]
        }
        errors, warnings = scan_evidence_fields(artifact)
        assert len(errors) == 1
        assert "elem-1" in errors[0] or "[0]" in errors[0]

    def test_allowlist_suppression(self) -> None:
        """Test that allowlist suppresses specific errors."""
        artifact = {
            "file_id": "F0001",
            "evidence": ["SPECIAL_VALUE"],
        }
        # Without allowlist
        errors, warnings = scan_evidence_fields(artifact)
        assert len(errors) == 1

        # With allowlist
        errors, warnings = scan_evidence_fields(
            artifact, allowlist={"evidence": ["SPECIAL_VALUE"]}
        )
        assert len(errors) == 0

    def test_empty_evidence_values_ignored(self) -> None:
        """Test that empty evidence values are ignored."""
        artifact = {
            "evidence": ["", "  ", "EVID-F0001-R0001-L1-L5"],
        }
        errors, warnings = scan_evidence_fields(artifact)
        assert len(errors) == 0

    def test_multiple_patterns_in_description(self) -> None:
        """Test detection of multiple derived patterns."""
        artifact = {
            "description": "Check views/summary.md and runs/001/output.yaml",
        }
        errors, warnings = scan_evidence_fields(artifact)
        # Should only warn once per field
        assert len(warnings) == 1


class TestLintL1Artifact:
    """Test full L1 artifact linting."""

    def test_lint_json_artifact(self) -> None:
        """Test linting a JSON artifact file."""
        artifact = {
            "file_id": "F0001",
            "evidence": ["EVID-F0001-R0001-L1-L10"],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(artifact, f)
            f.flush()
            result = lint_l1_artifact(Path(f.name))

        assert result.passed

    def test_lint_json_with_violations(self) -> None:
        """Test linting a JSON artifact with violations."""
        artifact = {
            "file_id": "F0001",
            "evidence": ["[F0001::INTRO]"],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(artifact, f)
            f.flush()
            result = lint_l1_artifact(Path(f.name))

        assert not result.passed
        assert len(result.errors) >= 1

    def test_lint_nonexistent_file(self) -> None:
        """Test linting a nonexistent file."""
        result = lint_l1_artifact(Path("/nonexistent/file.json"))
        assert not result.passed
        assert "not found" in result.errors[0]

    def test_lint_invalid_json(self) -> None:
        """Test linting invalid JSON."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            f.write("not valid json {")
            f.flush()
            result = lint_l1_artifact(Path(f.name))

        assert not result.passed
        assert "Invalid JSON" in result.errors[0]

    def test_lint_markdown_artifact(self) -> None:
        """Test linting a markdown artifact file."""
        content = """
# Test Document

**Evidence:** [EVID-F0001-R0001-L1-L10]

Some description text.
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write(content)
            f.flush()
            result = lint_l1_artifact(Path(f.name))

        assert result.passed

    def test_lint_markdown_with_legacy_citation(self) -> None:
        """Test linting markdown with legacy citation in evidence."""
        content = """
# Test Document

**Evidence:** [F0001::INTRO]

See runs/001/output.json for details.
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write(content)
            f.flush()
            result = lint_l1_artifact(Path(f.name))

        assert not result.passed
        assert len(result.errors) >= 1
        assert len(result.warnings) >= 1  # For runs/ reference


class TestScanForForbiddenOutputSignatures:
    """Test convenience function for scanning arbitrary text."""

    def test_scan_text_with_legacy_citations(self) -> None:
        """Test scanning text with legacy citations."""
        text = "Reference: [F0001::INTRO] and [LIB-0001::spec.md::SEC]"
        errors, warnings = scan_for_forbidden_output_signatures(text, "test")
        assert len(errors) >= 2

    def test_scan_text_with_derived_refs(self) -> None:
        """Test scanning text with derived artifact references."""
        text = "See runs/001/artifacts/file.json and views/summary.md"
        errors, warnings = scan_for_forbidden_output_signatures(text, "test")
        assert len(warnings) >= 2

    def test_scan_clean_text(self) -> None:
        """Test scanning clean text."""
        text = "This is clean text with [EVID-F0001-R0001-L1-L10] citations."
        errors, warnings = scan_for_forbidden_output_signatures(text, "test")
        assert len(errors) == 0
        # Note: warnings for .json extension might still fire


class TestLintResult:
    """Test LintResult dataclass."""

    def test_passed_with_no_errors(self) -> None:
        """Test that passed is True with no errors."""
        result = LintResult(errors=[], warnings=["warning 1"])
        assert result.passed is True

    def test_not_passed_with_errors(self) -> None:
        """Test that passed is False with errors."""
        result = LintResult(errors=["error 1"], warnings=[])
        assert result.passed is False

    def test_default_empty_lists(self) -> None:
        """Test default empty lists."""
        result = LintResult()
        assert result.errors == []
        assert result.warnings == []
        assert result.passed is True
