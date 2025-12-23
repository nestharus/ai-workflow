"""Tests for scripts.knowledge.validate_artifact_kinds module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from scripts.knowledge import validate_artifact_kinds
from scripts.knowledge.validate_artifact_kinds import (
    ValidationResult,
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
            exit_code = main(
                [
                    "--knowledge-path",
                    "/fake/.knowledge",
                    "--json-report",
                    "/fake/output/report.json",
                ]
            )

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

    def test_json_report_write_error(self, fs: FakeFilesystem, capsys) -> None:
        """Should handle OSError when writing JSON report (lines 819-820)."""
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
        # Create output directory
        fs.create_dir("/fake/output")

        def failing_write_text(self, data, encoding=None):
            if "report.json" in str(self):
                raise OSError("Permission denied")
            # Fall through to real pyfakefs write
            path_str = str(self)
            fs.create_file(path_str, contents=data)

        # Patch at the module level
        with (
            patch.object(validate_artifact_kinds, "REPO_ROOT", Path("/fake")),
            patch("pathlib.Path.write_text", failing_write_text),
        ):
            exit_code = main(
                [
                    "--knowledge-path",
                    "/fake/.knowledge",
                    "--json-report",
                    "/fake/output/report.json",
                ]
            )

        captured = capsys.readouterr()
        assert "Error writing JSON report" in captured.err
        # Should still return 0 since registry is valid
        assert exit_code == 0

    def test_main_with_no_warnings(self, fs: FakeFilesystem) -> None:
        """Should pass when there are no warnings (branch 829->835)."""
        fs.create_dir("/fake/.knowledge/artifacts")
        # Create a valid registry with examples that exist
        registry_content = """
kinds:
  - kind_id: test/kind
    content_form: text
    structure_pattern:
      root_path: sections[*].text
    extraction_contract:
      contributors: []
    rendering_contract: {}
    examples:
      - source_file: docs/test.yml
        element_id: test-element
"""
        fs.create_file(
            "/fake/.knowledge/artifacts/kinds.yml",
            contents=registry_content,
        )
        fs.create_dir("/fake/docs")
        fs.create_file("/fake/docs/test.yml", contents="test: value\n")

        with patch.object(validate_artifact_kinds, "REPO_ROOT", Path("/fake")):
            exit_code = main(["--knowledge-path", "/fake/.knowledge"])

        # Should pass with warnings only
        assert exit_code == 0


class TestLoadRegistryAdditional:
    """Additional tests for load_registry function."""

    def test_os_error_reading_file(self, fs: FakeFilesystem) -> None:
        """Should return error message on OSError (lines 168-169)."""
        fs.create_dir("/fake/.knowledge/artifacts")
        fs.create_file(
            "/fake/.knowledge/artifacts/kinds.yml",
            contents="kinds: []\n",
        )

        def mock_read_text(self, encoding=None):
            """Mock that raises OSError."""
            raise OSError("Disk read error")

        # Patch at the module level using pathlib.Path.read_text
        with patch("pathlib.Path.read_text", mock_read_text):
            kinds, error = load_registry(Path("/fake/.knowledge"))

        assert kinds == []
        assert "Failed to read registry file" in error

    def test_kinds_not_a_list(self, fs: FakeFilesystem) -> None:
        """Should return error when kinds is not a list (line 176)."""
        fs.create_dir("/fake/.knowledge/artifacts")
        fs.create_file(
            "/fake/.knowledge/artifacts/kinds.yml",
            contents="kinds: {invalid: mapping}\n",
        )
        kinds, error = load_registry(Path("/fake/.knowledge"))
        assert kinds == []
        assert "'kinds' must be a list" in error


class TestValidateSchemaAdditional:
    """Additional tests for validate_schema function."""

    def test_entry_not_dict(self) -> None:
        """Should error when entry is not a dict (lines 199-200)."""
        kinds = [
            "not_a_dict",  # type: ignore[list-item]
            123,  # type: ignore[list-item]
        ]
        result = ValidationResult()
        validate_schema(kinds, result)  # type: ignore[arg-type]
        assert result.passed is False
        assert any("Entry must be a mapping/dict" in e.message for e in result.errors)

    def test_missing_kind_id(self) -> None:
        """Should error when kind_id is missing (lines 204-205)."""
        kinds = [
            {
                # No kind_id
                "content_form": "text",
                "structure_pattern": {},
                "extraction_contract": {},
                "rendering_contract": {},
            }
        ]
        result = ValidationResult()
        validate_schema(kinds, result)
        assert result.passed is False
        assert any("Missing required field 'kind_id'" in e.message for e in result.errors)

    def test_aliases_not_a_list(self) -> None:
        """Should handle aliases that are not a list (branch 222->232)."""
        kinds = [
            {
                "kind_id": "test/kind",
                "content_form": "text",
                "structure_pattern": {},
                "extraction_contract": {},
                "rendering_contract": {},
                "aliases": "not_a_list",  # Invalid aliases type
            }
        ]
        result = ValidationResult()
        validate_schema(kinds, result)
        # Should not add alias errors since aliases is not a list
        assert all("Alias target" not in e.message for e in result.errors)

    def test_rendering_contract_not_dict(self) -> None:
        """Should handle rendering_contract not being a dict (branch 233->197)."""
        kinds = [
            {
                "kind_id": "test/kind",
                "content_form": "text",
                "structure_pattern": {},
                "extraction_contract": {},
                "rendering_contract": "not_a_dict",  # Not a dict
            }
        ]
        result = ValidationResult()
        validate_schema(kinds, result)
        # Should just pass without render_plan warning
        assert result.passed is True


class TestValidateStructurePatternDeterminismAdditional:
    """Additional tests for validate_structure_pattern_determinism function."""

    def test_non_dict_kind_skipped(self) -> None:
        """Should skip non-dict kinds (line 262)."""
        kinds = [
            "not_a_dict",  # type: ignore[list-item]
            {"kind_id": "valid/kind", "structure_pattern": {}},
        ]
        result = ValidationResult()
        validate_structure_pattern_determinism(kinds, result)  # type: ignore[arg-type]
        assert result.passed is True

    def test_structure_pattern_not_dict(self) -> None:
        """Should error when structure_pattern is not a dict (lines 268-269)."""
        kinds = [
            {
                "kind_id": "test/kind",
                "structure_pattern": "not_a_dict",
            }
        ]
        result = ValidationResult()
        validate_structure_pattern_determinism(kinds, result)
        assert result.passed is False
        assert any("Must be a mapping/dict" in e.message for e in result.errors)

    def test_sibling_constraint_not_dict(self) -> None:
        """Should error when sibling_constraint is not a dict (lines 285, 290)."""
        kinds = [
            {
                "kind_id": "test/kind",
                "structure_pattern": {
                    "sibling_constraints": [
                        "not_a_dict",  # type: ignore[list-item]
                    ],
                },
            }
        ]
        result = ValidationResult()
        validate_structure_pattern_determinism(kinds, result)
        assert result.passed is False
        assert any("Constraint must be a mapping/dict" in e.message for e in result.errors)

    def test_sibling_constraint_missing_key(self) -> None:
        """Should error when sibling constraint is missing key (lines 293)."""
        kinds = [
            {
                "kind_id": "test/kind",
                "structure_pattern": {
                    "sibling_constraints": [
                        {"equals": "value"},  # Missing 'key' field
                    ],
                },
            }
        ]
        result = ValidationResult()
        validate_structure_pattern_determinism(kinds, result)
        assert result.passed is False
        assert any("Missing required 'key' field" in e.message for e in result.errors)

    def test_starts_with_any_not_a_list(self) -> None:
        """Should error when starts_with_any is not a list (lines 329)."""
        kinds = [
            {
                "kind_id": "test/kind",
                "structure_pattern": {
                    "content_sniff": {
                        "starts_with_any": "not_a_list",
                    },
                },
            }
        ]
        result = ValidationResult()
        validate_structure_pattern_determinism(kinds, result)
        assert result.passed is False
        assert any("Must be a list of strings" in e.message for e in result.errors)

    def test_starts_with_any_non_string_item(self) -> None:
        """Should error when starts_with_any contains non-strings (lines 335-337)."""
        kinds = [
            {
                "kind_id": "test/kind",
                "structure_pattern": {
                    "content_sniff": {
                        "starts_with_any": ["valid", 123, None],  # type: ignore[list-item]
                    },
                },
            }
        ]
        result = ValidationResult()
        validate_structure_pattern_determinism(kinds, result)
        assert result.passed is False
        assert any("Must be a string" in e.message for e in result.errors)

    def test_sibling_constraints_not_a_list(self) -> None:
        """Should handle sibling_constraints not being a list (branch 282->312)."""
        kinds = [
            {
                "kind_id": "test/kind",
                "structure_pattern": {
                    "sibling_constraints": "not_a_list",
                },
            }
        ]
        result = ValidationResult()
        validate_structure_pattern_determinism(kinds, result)
        # Should not crash, just skip validation
        assert result.passed is True

    def test_content_sniff_not_a_dict(self) -> None:
        """Should handle content_sniff not being a dict (branch 313->260)."""
        kinds = [
            {
                "kind_id": "test/kind",
                "structure_pattern": {
                    "content_sniff": "not_a_dict",
                },
            }
        ]
        result = ValidationResult()
        validate_structure_pattern_determinism(kinds, result)
        # Should not crash, just skip validation
        assert result.passed is True


class TestComputePatternSignatureAdditional:
    """Additional tests for compute_pattern_signature function."""

    def test_pattern_not_dict(self) -> None:
        """Should return empty string when pattern is not a dict (line 594)."""
        kind = {"structure_pattern": "not_a_dict"}
        sig = compute_pattern_signature(kind)
        assert sig == ""

    def test_content_sniff_starts_with_any_list(self) -> None:
        """Should handle content_sniff.starts_with_any as list (lines 617-620)."""
        kind = {
            "structure_pattern": {
                "content_sniff": {
                    "starts_with_any": ["prefix1", "prefix2"],
                }
            }
        }
        sig = compute_pattern_signature(kind)
        assert "sniff.starts_with_any=" in sig
        assert "prefix1" in sig
        assert "prefix2" in sig

    def test_content_sniff_matches_string(self) -> None:
        """Should handle content_sniff.matches as string (lines 617-620, val not list)."""
        kind = {
            "structure_pattern": {
                "content_sniff": {
                    "matches": "^test.*",
                }
            }
        }
        sig = compute_pattern_signature(kind)
        assert "sniff.matches=^test.*" in sig

    def test_empty_sibling_constraints(self) -> None:
        """Should handle empty sibling_constraints (branch 605->613)."""
        kind = {
            "structure_pattern": {
                "sibling_constraints": [],
            }
        }
        sig = compute_pattern_signature(kind)
        assert sig == ""

    def test_sibling_constraints_non_dict_item(self) -> None:
        """Should skip non-dict items in sibling_constraints (branch 607->606)."""
        kind = {
            "structure_pattern": {
                "sibling_constraints": [
                    "not_a_dict",  # type: ignore[list-item]
                    {"key": "type", "equals": "code"},
                ],
            }
        }
        sig = compute_pattern_signature(kind)
        # Should still include the valid constraint
        assert "sibling.type.equals=code" in sig

    def test_empty_content_sniff(self) -> None:
        """Should handle empty content_sniff (branch 614->622)."""
        kind = {
            "structure_pattern": {
                "content_sniff": {},
            }
        }
        sig = compute_pattern_signature(kind)
        assert sig == ""


class TestValidateDuplicatesAdditional:
    """Additional tests for validate_duplicates function."""

    def test_non_dict_kind_skipped(self) -> None:
        """Should skip non-dict kinds (line 673)."""
        kinds = [
            "not_a_dict",  # type: ignore[list-item]
            {
                "kind_id": "valid/kind",
                "structure_pattern": {"root_path": "sections[*].text"},
            },
        ]
        result = ValidationResult()
        validate_duplicates(kinds, result)  # type: ignore[arg-type]
        # Should not crash, still works with valid kind
        assert result.passed is True

    def test_duplicate_pair_check_skipped(self) -> None:
        """Should skip already-checked pairs (line 710)."""
        # Create kinds that would generate multiple pair checks
        kinds = [
            {
                "kind_id": "kind/a",
                "structure_pattern": {"root_path": "path.a"},
            },
            {
                "kind_id": "kind/b",
                "structure_pattern": {"root_path": "path.b"},
            },
            {
                "kind_id": "kind/c",
                "structure_pattern": {"root_path": "path.c"},
            },
        ]
        result = ValidationResult()
        validate_duplicates(kinds, result)
        # All different, should pass without duplicates
        assert result.passed is True


class TestValidateRegistryAdditional:
    """Additional tests for validate_registry function."""

    def test_load_error_returns_early(self, fs: FakeFilesystem) -> None:
        """Should return early with error when load fails (lines 742-743)."""
        fs.create_dir("/fake/.knowledge/artifacts")
        # No kinds.yml file - will trigger error
        result = validate_registry(Path("/fake/.knowledge"))
        assert result.passed is False
        assert any("not found" in e.message for e in result.errors)

    def test_strict_mode_upgrades_warnings_to_errors(self, fs: FakeFilesystem) -> None:
        """Should upgrade warnings to errors in strict mode (lines 759-761)."""
        fs.create_dir("/fake/.knowledge/artifacts")
        # Create registry with a valid kind that has a render_plan_id (generates warning)
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
            result = validate_registry(Path("/fake/.knowledge"), strict=True)

        # In strict mode, warnings become errors
        assert result.passed is False
        # Warnings list should be empty after being converted to errors
        assert len(result.warnings) == 0
        # Check that warnings were converted to errors with [strict] prefix
        assert any("[strict]" in e.message for e in result.errors)


class TestValidateSamplesAdditional:
    """Additional tests for validate_samples function."""

    def test_non_dict_kind_skipped(self) -> None:
        """Should skip non-dict kinds (line 474)."""
        kinds = [
            "not_a_dict",  # type: ignore[list-item]
            {
                "kind_id": "valid/kind",
                "examples": [],
            },
        ]
        result = ValidationResult()
        validate_samples(kinds, result)  # type: ignore[arg-type]
        # Should not crash, should warn about no samples
        assert result.passed is True

    def test_examples_not_a_list(self) -> None:
        """Should error when examples is not a list (lines 488-489)."""
        kinds = [
            {
                "kind_id": "test/kind",
                "examples": "not_a_list",
            }
        ]
        result = ValidationResult()
        validate_samples(kinds, result)
        assert result.passed is False
        assert any("Must be a list" in e.message for e in result.errors)

    def test_example_not_a_dict(self) -> None:
        """Should error when example is not a dict (lines 493, 498)."""
        kinds = [
            {
                "kind_id": "test/kind",
                "examples": [
                    "not_a_dict",  # type: ignore[list-item]
                ],
            }
        ]
        result = ValidationResult()
        validate_samples(kinds, result)
        assert result.passed is False
        assert any("Sample must be a mapping/dict" in e.message for e in result.errors)

    def test_strict_source_file_not_found(self, fs: FakeFilesystem) -> None:
        """Should error in strict mode when source file not found (line 513)."""
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
            validate_samples(kinds, result, strict=True)
            assert result.passed is False
            assert any("Sample source file not found" in e.message for e in result.errors)

    def test_missing_element_id_warns(self, fs: FakeFilesystem) -> None:
        """Should warn when element_id is missing (lines 528, 533)."""
        with patch.object(validate_artifact_kinds, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file("/fake/docs/test.yml", contents="test: value\n")
            kinds = [
                {
                    "kind_id": "test/kind",
                    "examples": [
                        {
                            "source_file": "docs/test.yml",
                            # Missing element_id
                        },
                    ],
                }
            ]
            result = ValidationResult()
            validate_samples(kinds, result)
            assert result.passed is True
            assert any("No element_id specified" in w.message for w in result.warnings)

    def test_yaml_parse_error_warns(self, fs: FakeFilesystem) -> None:
        """Should warn when YAML parsing fails (lines 541-543, 549)."""
        with patch.object(validate_artifact_kinds, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file("/fake/docs/test.yml", contents="invalid: yaml: [")
            kinds = [
                {
                    "kind_id": "test/kind",
                    "examples": [
                        {
                            "source_file": "docs/test.yml",
                            "element_id": "test-element",
                        },
                    ],
                }
            ]
            result = ValidationResult()
            validate_samples(kinds, result)
            assert result.passed is True
            assert any("Failed to parse sample file" in w.message for w in result.warnings)

    def test_yaml_parse_error_strict_errors(self, fs: FakeFilesystem) -> None:
        """Should error in strict mode when YAML parsing fails (lines 542-543)."""
        with patch.object(validate_artifact_kinds, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file("/fake/docs/test.yml", contents="invalid: yaml: [")
            kinds = [
                {
                    "kind_id": "test/kind",
                    "examples": [
                        {
                            "source_file": "docs/test.yml",
                            "element_id": "test-element",
                        },
                    ],
                }
            ]
            result = ValidationResult()
            validate_samples(kinds, result, strict=True)
            assert result.passed is False
            assert any("Failed to parse sample file" in e.message for e in result.errors)

    def test_element_not_found_warns(self, fs: FakeFilesystem) -> None:
        """Should warn when element_id not found (lines 561, 563-574)."""
        with patch.object(validate_artifact_kinds, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file(
                "/fake/docs/test.yml",
                contents="kinds:\n  - kind_id: other-kind\n    value: test\n",
            )
            kinds = [
                {
                    "kind_id": "test/kind",
                    "examples": [
                        {
                            "source_file": "docs/test.yml",
                            "element_id": "nonexistent-element",
                        },
                    ],
                }
            ]
            result = ValidationResult()
            validate_samples(kinds, result)
            assert result.passed is True
            # Should warn about element not found
            assert any("not found" in w.message.lower() for w in result.warnings)

    def test_element_not_found_strict_errors(self, fs: FakeFilesystem) -> None:
        """Should error in strict mode when element_id not found (lines 562-563)."""
        with patch.object(validate_artifact_kinds, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file(
                "/fake/docs/test.yml",
                contents="kinds:\n  - kind_id: other-kind\n    value: test\n",
            )
            kinds = [
                {
                    "kind_id": "test/kind",
                    "examples": [
                        {
                            "source_file": "docs/test.yml",
                            "element_id": "nonexistent-element",
                        },
                    ],
                }
            ]
            result = ValidationResult()
            validate_samples(kinds, result, strict=True)
            assert result.passed is False

    def test_valid_sample_with_element_facts(self, fs: FakeFilesystem) -> None:
        """Should validate sample extraction when element facts exist (lines 577-578)."""
        with patch.object(validate_artifact_kinds, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            # Create a valid YAML file with an element that can be extracted
            # The 'id' field is required for extract_ids_and_objects to find it
            yaml_content = """
kinds:
  - id: test-element
    value: test
    description: Test description
"""
            fs.create_file(
                "/fake/docs/test.yml",
                contents=yaml_content,
            )
            kinds = [
                {
                    "kind_id": "test/kind",
                    "structure_pattern": {
                        "required_fields": ["value"],
                    },
                    "extraction_contract": {
                        "contributors": [
                            {"field_path": "value"},
                        ],
                    },
                    "examples": [
                        {
                            "source_file": "docs/test.yml",
                            "element_id": "test-element",
                        },
                    ],
                }
            ]
            result = ValidationResult()
            validate_samples(kinds, result)
            # Should not add errors for the element (may add warnings for no samples elsewhere)
            assert result.passed is True

    def test_sample_with_empty_element_facts(self, fs: FakeFilesystem) -> None:
        """Should skip validation when element_facts is empty (branch 577->491)."""
        with patch.object(validate_artifact_kinds, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            # Create YAML file but return empty facts by using a format that doesn't produce facts
            yaml_content = """
data:
  items:
    - name: test-element
      value: test
"""
            fs.create_file(
                "/fake/docs/test.yml",
                contents=yaml_content,
            )
            # Mock _resolve_element_and_field to return empty facts
            original_resolve = validate_artifact_kinds._resolve_element_and_field

            def mock_resolve(data, source_file, element_id, field_path):
                return {"id": element_id}, [], None  # Empty facts list

            kinds = [
                {
                    "kind_id": "test/kind",
                    "structure_pattern": {},
                    "extraction_contract": {},
                    "examples": [
                        {
                            "source_file": "docs/test.yml",
                            "element_id": "test-element",
                        },
                    ],
                }
            ]
            result = ValidationResult()
            with patch.object(validate_artifact_kinds, "_resolve_element_and_field", mock_resolve):
                validate_samples(kinds, result)
            # Should pass since no errors were added
            assert result.passed is True
