"""Tests for scripts.knowledge.validate_artifact_kinds module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts.knowledge import validate_artifact_kinds
from scripts.knowledge.validate_artifact_kinds import (
    ValidationError,
    ValidationResult,
    ValidationWarning,
    _compute_jaccard_similarity,
    compute_pattern_signature,
    load_registry,
    main,
    parse_args,
    validate_duplicates,
    validate_registry,
    validate_samples,
    validate_schema,
    validate_structure_pattern_determinism,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_knowledge_path(self) -> None:
        """Should use default knowledge directory."""
        args = parse_args([])
        assert ".knowledge" in str(args.knowledge_path)

    def test_custom_knowledge_path(self) -> None:
        """Should accept custom knowledge path."""
        args = parse_args(["--knowledge-path", "/custom/path"])
        assert args.knowledge_path == Path("/custom/path")

    def test_strict_flag(self) -> None:
        """Should accept strict flag."""
        args = parse_args(["--strict"])
        assert args.strict is True

    def test_json_report_flag(self) -> None:
        """Should accept json-report path."""
        args = parse_args(["--json-report", "/output/report.json"])
        assert args.json_report == Path("/output/report.json")


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_initial_state(self) -> None:
        """Should initialize with passed=True and empty lists."""
        result = ValidationResult()
        assert result.passed is True
        assert result.errors == []
        assert result.warnings == []

    def test_add_error(self) -> None:
        """Should add error and set passed=False."""
        result = ValidationResult()
        result.add_error("kind-1", "field_name", "Error message")
        assert result.passed is False
        assert len(result.errors) == 1
        assert result.errors[0].kind_id == "kind-1"
        assert result.errors[0].field == "field_name"
        assert result.errors[0].message == "Error message"

    def test_add_warning(self) -> None:
        """Should add warning without changing passed status."""
        result = ValidationResult()
        result.add_warning("kind-1", "field_name", "Warning message")
        assert result.passed is True
        assert len(result.warnings) == 1

    def test_to_dict(self) -> None:
        """Should convert to dictionary for JSON output."""
        result = ValidationResult()
        result.add_error("kind-1", "field", "error")
        result.add_warning("kind-2", "field", "warning")
        d = result.to_dict()
        assert d["passed"] is False
        assert len(d["errors"]) == 1
        assert len(d["warnings"]) == 1


class TestLoadRegistry:
    """Tests for load_registry function."""

    def test_missing_file(self, fs: FakeFilesystem) -> None:
        """Should return error message when file doesn't exist."""
        fs.create_dir("/fake/.knowledge/artifacts")
        kinds, error = load_registry(Path("/fake/.knowledge"))
        assert kinds == []
        assert "not found" in error

    def test_valid_registry(self, fs: FakeFilesystem) -> None:
        """Should load valid registry."""
        fs.create_dir("/fake/.knowledge/artifacts")
        registry_content = """
kinds:
  - kind_id: test/kind
    content_form: text
    structure_pattern:
      root_path: sections[*].text
    extraction_contract:
      contributors: []
    rendering_contract:
      render_plan_id: test.v1
"""
        fs.create_file(
            "/fake/.knowledge/artifacts/kinds.yml",
            contents=registry_content,
        )
        kinds, error = load_registry(Path("/fake/.knowledge"))
        assert error is None
        assert len(kinds) == 1
        assert kinds[0]["kind_id"] == "test/kind"

    def test_invalid_yaml(self, fs: FakeFilesystem) -> None:
        """Should return error for invalid YAML."""
        fs.create_dir("/fake/.knowledge/artifacts")
        fs.create_file(
            "/fake/.knowledge/artifacts/kinds.yml",
            contents="invalid: yaml: content: [",
        )
        kinds, error = load_registry(Path("/fake/.knowledge"))
        assert kinds == []
        assert "parse" in error.lower()

    def test_not_dict(self, fs: FakeFilesystem) -> None:
        """Should return error when root is not a dict."""
        fs.create_dir("/fake/.knowledge/artifacts")
        fs.create_file(
            "/fake/.knowledge/artifacts/kinds.yml",
            contents="- item1\n- item2\n",
        )
        kinds, error = load_registry(Path("/fake/.knowledge"))
        assert kinds == []
        assert "mapping" in error


class TestValidateSchema:
    """Tests for validate_schema function."""

    def test_valid_entry_passes(self) -> None:
        """Should pass for valid entry with all required fields."""
        kinds = [
            {
                "kind_id": "test/kind",
                "content_form": "text",
                "structure_pattern": {"root_path": "sections[*].text"},
                "extraction_contract": {"contributors": []},
                "rendering_contract": {"render_plan_id": "test.v1"},
            }
        ]
        result = ValidationResult()
        validate_schema(kinds, result)
        # Only render_plan warning expected
        assert result.passed is True

    def test_missing_required_field_fails(self) -> None:
        """Should fail when required field is missing."""
        kinds = [
            {
                "kind_id": "test/kind",
                "content_form": "text",
                # Missing: structure_pattern, extraction_contract, rendering_contract
            }
        ]
        result = ValidationResult()
        validate_schema(kinds, result)
        assert result.passed is False
        missing_fields = [e.field for e in result.errors]
        assert "structure_pattern" in missing_fields
        assert "extraction_contract" in missing_fields
        assert "rendering_contract" in missing_fields

    def test_duplicate_kind_id_fails(self) -> None:
        """Should fail when kind_id is duplicated."""
        kinds = [
            {
                "kind_id": "test/kind",
                "content_form": "text",
                "structure_pattern": {},
                "extraction_contract": {},
                "rendering_contract": {},
            },
            {
                "kind_id": "test/kind",  # Duplicate
                "content_form": "text2",
                "structure_pattern": {},
                "extraction_contract": {},
                "rendering_contract": {},
            },
        ]
        result = ValidationResult()
        validate_schema(kinds, result)
        assert result.passed is False
        assert any("Duplicate" in e.message for e in result.errors)

    def test_invalid_alias_target_fails(self) -> None:
        """Should fail when alias target doesn't exist."""
        kinds = [
            {
                "kind_id": "test/kind",
                "content_form": "text",
                "structure_pattern": {},
                "extraction_contract": {},
                "rendering_contract": {},
                "aliases": ["nonexistent/kind"],
            }
        ]
        result = ValidationResult()
        validate_schema(kinds, result)
        assert result.passed is False
        assert any("Alias target" in e.message for e in result.errors)


class TestValidateStructurePatternDeterminism:
    """Tests for validate_structure_pattern_determinism function."""

    def test_valid_root_path_passes(self) -> None:
        """Should pass for valid root_path syntax."""
        kinds = [
            {
                "kind_id": "test/kind",
                "structure_pattern": {
                    "root_path": "sections[*].items[*].text",
                },
            }
        ]
        result = ValidationResult()
        validate_structure_pattern_determinism(kinds, result)
        assert result.passed is True

    def test_invalid_root_path_fails(self) -> None:
        """Should fail for invalid root_path syntax."""
        kinds = [
            {
                "kind_id": "test/kind",
                "structure_pattern": {
                    "root_path": "sections[*].items[*].text!@#$",
                },
            }
        ]
        result = ValidationResult()
        validate_structure_pattern_determinism(kinds, result)
        assert result.passed is False

    def test_valid_sibling_constraint_passes(self) -> None:
        """Should pass for valid sibling constraints."""
        kinds = [
            {
                "kind_id": "test/kind",
                "structure_pattern": {
                    "sibling_constraints": [
                        {"key": "type", "equals": "code"},
                    ],
                },
            }
        ]
        result = ValidationResult()
        validate_structure_pattern_determinism(kinds, result)
        assert result.passed is True

    def test_missing_constraint_operator_fails(self) -> None:
        """Should fail when sibling constraint lacks operator."""
        kinds = [
            {
                "kind_id": "test/kind",
                "structure_pattern": {
                    "sibling_constraints": [
                        {"key": "type"},  # Missing operator
                    ],
                },
            }
        ]
        result = ValidationResult()
        validate_structure_pattern_determinism(kinds, result)
        assert result.passed is False

    def test_invalid_content_sniff_regex_fails(self) -> None:
        """Should fail for invalid regex in content_sniff."""
        kinds = [
            {
                "kind_id": "test/kind",
                "structure_pattern": {
                    "content_sniff": {
                        "matches": "[invalid(regex",
                    },
                },
            }
        ]
        result = ValidationResult()
        validate_structure_pattern_determinism(kinds, result)
        assert result.passed is False


class TestValidateSamples:
    """Tests for validate_samples function."""

    def test_missing_examples_warns(self) -> None:
        """Should warn when no examples are declared."""
        kinds = [
            {
                "kind_id": "test/kind",
                "structure_pattern": {},
            }
        ]
        result = ValidationResult()
        validate_samples(kinds, result)
        assert result.passed is True
        assert len(result.warnings) == 1
        assert "No sample" in result.warnings[0].message

    def test_missing_source_file_fails(self) -> None:
        """Should fail when example lacks source_file."""
        kinds = [
            {
                "kind_id": "test/kind",
                "examples": [
                    {"element_id": "test-element"},  # Missing source_file
                ],
            }
        ]
        result = ValidationResult()
        validate_samples(kinds, result)
        assert result.passed is False

    def test_missing_source_file_path_warns(self, fs: FakeFilesystem) -> None:
        """Should warn when source file doesn't exist."""
        with patch.object(validate_artifact_kinds, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            kinds = [
                {
                    "kind_id": "test/kind",
                    "examples": [
                        {
                            "source_file": "docs/nonexistent.yml",
                            "element_id": "test-element",
                        },
                    ],
                }
            ]
            result = ValidationResult()
            validate_samples(kinds, result)
            assert result.passed is True
            assert any("not found" in w.message for w in result.warnings)


class TestValidateDuplicates:
    """Tests for validate_duplicates function."""

    def test_different_patterns_pass(self) -> None:
        """Should pass for different structure patterns."""
        kinds = [
            {
                "kind_id": "kind/one",
                "structure_pattern": {
                    "root_path": "sections[*].items",
                },
            },
            {
                "kind_id": "kind/two",
                "structure_pattern": {
                    "root_path": "sections[*].text",
                },
            },
        ]
        result = ValidationResult()
        validate_duplicates(kinds, result)
        assert result.passed is True

    def test_identical_patterns_fail(self) -> None:
        """Should fail for identical structure patterns."""
        kinds = [
            {
                "kind_id": "kind/one",
                "structure_pattern": {
                    "root_path": "sections[*].text",
                },
            },
            {
                "kind_id": "kind/two",
                "structure_pattern": {
                    "root_path": "sections[*].text",  # Same pattern
                },
            },
        ]
        result = ValidationResult()
        validate_duplicates(kinds, result)
        assert result.passed is False
        assert any("Identical structure pattern" in e.message for e in result.errors)

    def test_near_duplicate_warns(self) -> None:
        """Should warn for near-duplicate patterns above threshold."""
        kinds = [
            {
                "kind_id": "kind/one",
                "structure_pattern": {
                    "root_path": "sections[*].text",
                    "sibling_constraints": [{"key": "type", "equals": "code"}],
                },
            },
            {
                "kind_id": "kind/two",
                "structure_pattern": {
                    "root_path": "sections[*].text",
                    "sibling_constraints": [{"key": "type", "equals": "prose"}],
                },
            },
        ]
        result = ValidationResult()
        validate_duplicates(kinds, result, similarity_threshold=0.3)
        assert result.passed is True
        assert any("Near-duplicate" in w.message for w in result.warnings)

    def test_dissimilar_patterns_no_warning(self) -> None:
        """Should not warn for dissimilar patterns below threshold."""
        kinds = [
            {
                "kind_id": "kind/one",
                "structure_pattern": {
                    "root_path": "sections[*].text",
                },
            },
            {
                "kind_id": "kind/two",
                "structure_pattern": {
                    "root_path": "items[*].content",
                    "sibling_constraints": [{"key": "type", "equals": "code"}],
                },
            },
        ]
        result = ValidationResult()
        validate_duplicates(kinds, result, similarity_threshold=0.9)
        assert result.passed is True
        assert not any("Near-duplicate" in w.message for w in result.warnings)


class TestComputeJaccardSimilarity:
    """Tests for _compute_jaccard_similarity function."""

    def test_identical_signatures(self) -> None:
        """Should return 1.0 for identical signatures."""
        sig = "root=sections[*].text|sibling.type.equals=code"
        assert _compute_jaccard_similarity(sig, sig) == 1.0

    def test_empty_signatures(self) -> None:
        """Should return 0.0 for empty signatures."""
        assert _compute_jaccard_similarity("", "") == 0.0
        assert _compute_jaccard_similarity("", "root=foo") == 0.0
        assert _compute_jaccard_similarity("root=foo", "") == 0.0

    def test_partial_overlap(self) -> None:
        """Should return correct similarity for partial overlap."""
        sig1 = "root=sections[*].text|sibling.type.equals=code"
        sig2 = "root=sections[*].text|sibling.type.equals=prose"
        # Tokens: {root=sections[*].text, sibling.type.equals=code}
        #         {root=sections[*].text, sibling.type.equals=prose}
        # Intersection: {root=sections[*].text} = 1
        # Union: {root=sections[*].text, sibling.type.equals=code, sibling.type.equals=prose} = 3
        # Jaccard = 1/3 = 0.333...
        similarity = _compute_jaccard_similarity(sig1, sig2)
        assert 0.33 <= similarity <= 0.34

    def test_no_overlap(self) -> None:
        """Should return 0.0 for signatures with no overlap."""
        sig1 = "root=sections[*].text"
        sig2 = "sibling.type.equals=code"
        assert _compute_jaccard_similarity(sig1, sig2) == 0.0


class TestComputePatternSignature:
    """Tests for compute_pattern_signature function."""

    def test_root_path_signature(self) -> None:
        """Should include normalized root path in signature."""
        kind = {
            "structure_pattern": {
                "root_path": "sections[0].items[1].text",
            }
        }
        sig = compute_pattern_signature(kind)
        # Indices should be normalized to [*]
        assert "root=sections[*].items[*].text" in sig

    def test_sibling_constraint_signature(self) -> None:
        """Should include sibling constraints in signature."""
        kind = {
            "structure_pattern": {
                "sibling_constraints": [
                    {"key": "type", "equals": "code"},
                ],
            }
        }
        sig = compute_pattern_signature(kind)
        assert "sibling.type.equals=code" in sig


class TestValidateRegistry:
    """Tests for validate_registry function."""

    def test_empty_registry_warns(self, fs: FakeFilesystem) -> None:
        """Should warn for empty registry."""
        fs.create_dir("/fake/.knowledge/artifacts")
        fs.create_file(
            "/fake/.knowledge/artifacts/kinds.yml",
            contents="kinds: []\n",
        )
        result = validate_registry(Path("/fake/.knowledge"))
        assert result.passed is True
        assert any("empty" in w.message for w in result.warnings)

    def test_strict_mode_upgrades_warnings(self, fs: FakeFilesystem) -> None:
        """Should upgrade warnings to errors in strict mode."""
        fs.create_dir("/fake/.knowledge/artifacts")
        fs.create_file(
            "/fake/.knowledge/artifacts/kinds.yml",
            contents="kinds: []\n",
        )
        result = validate_registry(Path("/fake/.knowledge"), strict=True)
        assert result.passed is False


class TestCLIIntegration:
    """Tests for main function (CLI integration)."""

    def test_success_exit_code(self, fs: FakeFilesystem) -> None:
        """Should return 0 for valid registry."""
        fs.create_dir("/fake/.knowledge/artifacts")
        registry_content = """
kinds:
  - kind_id: test/kind
    content_form: text
    structure_pattern:
      root_path: sections[*].text
    extraction_contract:
      contributors: []
    rendering_contract:
      render_plan_id: test.v1
    examples:
      - source_file: docs/test.yml
        element_id: test-element
"""
        fs.create_file(
            "/fake/.knowledge/artifacts/kinds.yml",
            contents=registry_content,
        )
        # Create the source file for sample validation
        fs.create_dir("/fake/docs")
        fs.create_file("/fake/docs/test.yml", contents="")

        with patch.object(validate_artifact_kinds, "REPO_ROOT", Path("/fake")):
            exit_code = main(["--knowledge-path", "/fake/.knowledge"])
        assert exit_code == 0

    def test_error_exit_code(self, fs: FakeFilesystem) -> None:
        """Should return 1 for invalid registry."""
        fs.create_dir("/fake/.knowledge/artifacts")
        # Missing required fields
        registry_content = """
kinds:
  - kind_id: test/kind
"""
        fs.create_file(
            "/fake/.knowledge/artifacts/kinds.yml",
            contents=registry_content,
        )
        exit_code = main(["--knowledge-path", "/fake/.knowledge"])
        assert exit_code == 1

    def test_json_report_output(self, fs: FakeFilesystem) -> None:
        """Should write JSON report when requested."""
        fs.create_dir("/fake/.knowledge/artifacts")
        fs.create_dir("/fake/output")
        registry_content = """
kinds:
  - kind_id: test/kind
    content_form: text
    structure_pattern:
      root_path: sections[*].text
    extraction_contract:
      contributors: []
    rendering_contract:
      render_plan_id: test.v1
"""
        fs.create_file(
            "/fake/.knowledge/artifacts/kinds.yml",
            contents=registry_content,
        )
        with patch.object(validate_artifact_kinds, "REPO_ROOT", Path("/fake")):
            exit_code = main([
                "--knowledge-path", "/fake/.knowledge",
                "--json-report", "/fake/output/report.json",
            ])

        assert exit_code == 0
        assert fs.exists("/fake/output/report.json")
        report = json.loads(Path("/fake/output/report.json").read_text())
        assert "passed" in report
        assert "errors" in report
        assert "warnings" in report

    def test_strict_flag(self, fs: FakeFilesystem) -> None:
        """Should upgrade warnings to errors with strict flag."""
        fs.create_dir("/fake/.knowledge/artifacts")
        fs.create_file(
            "/fake/.knowledge/artifacts/kinds.yml",
            contents="kinds: []\n",
        )
        exit_code = main(["--knowledge-path", "/fake/.knowledge", "--strict"])
        assert exit_code == 1
