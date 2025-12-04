"""Tests for scripts.dev.lint_yaml_docs module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts.dev import lint_yaml_docs
from scripts.dev.lint_yaml_docs import (
    LintError,
    LintResult,
    _generate_id_from_title,
    find_yaml_files,
    format_errors,
    is_documentation_file,
    lint_directory,
    lint_yaml_file,
    main,
    parse_args,
    validate_document_root,
    validate_sections,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_path(self) -> None:
        """Should use default docs directory."""
        args = parse_args([])
        assert "docs" in str(args.path)

    def test_custom_path(self) -> None:
        """Should accept custom path."""
        args = parse_args(["--path", "/custom/path"])
        assert args.path == Path("/custom/path")

    def test_fix_flag(self) -> None:
        """Should accept fix flag."""
        args = parse_args(["--fix"])
        assert args.fix is True


class TestIsDocumentationFile:
    """Tests for is_documentation_file function."""

    def test_returns_true_when_doc_id_present(self) -> None:
        """Should return True when doc_id is present at root."""
        data = {"doc_id": "test-doc", "title": "Test", "sections": []}
        assert is_documentation_file(data) is True

    def test_returns_false_when_doc_id_missing(self) -> None:
        """Should return False when doc_id is missing."""
        data = {"title": "Test", "sections": []}
        assert is_documentation_file(data) is False


class TestGenerateIdFromTitle:
    """Tests for _generate_id_from_title function."""

    def test_converts_to_kebab_case(self) -> None:
        """Should convert title to kebab-case."""
        assert _generate_id_from_title("My Test Title") == "my-test-title"

    def test_handles_special_characters(self) -> None:
        """Should replace special characters with hyphens."""
        assert _generate_id_from_title("Test (with) Special!") == "test-with-special"

    def test_collapses_multiple_hyphens(self) -> None:
        """Should collapse multiple hyphens."""
        assert _generate_id_from_title("Test   Multiple   Spaces") == "test-multiple-spaces"

    def test_returns_section_for_empty(self) -> None:
        """Should return 'section' for empty or invalid titles."""
        assert _generate_id_from_title("!!!") == "section"


class TestValidateDocumentRoot:
    """Tests for validate_document_root function."""

    def test_returns_empty_when_all_required_present(self) -> None:
        """Should return empty list when all required fields present."""
        data = {"doc_id": "test", "title": "Test", "sections": []}
        errors = validate_document_root(data, "test.yml")
        assert errors == []

    def test_reports_missing_doc_id(self) -> None:
        """Should report missing doc_id."""
        data = {"title": "Test", "sections": []}
        errors = validate_document_root(data, "test.yml")
        assert len(errors) == 1
        assert errors[0]["error_type"] == "missing_required_field"
        assert "doc_id" in errors[0]["message"]

    def test_reports_missing_title(self) -> None:
        """Should report missing title."""
        data = {"doc_id": "test", "sections": []}
        errors = validate_document_root(data, "test.yml")
        assert len(errors) == 1
        assert "title" in errors[0]["message"]

    def test_reports_missing_sections(self) -> None:
        """Should report missing sections."""
        data = {"doc_id": "test", "title": "Test"}
        errors = validate_document_root(data, "test.yml")
        assert len(errors) == 1
        assert "sections" in errors[0]["message"]

    def test_reports_multiple_missing_fields(self) -> None:
        """Should report all missing required fields."""
        data = {}
        errors = validate_document_root(data, "test.yml")
        assert len(errors) == 3

    def test_reports_invalid_sections_type(self) -> None:
        """Should report when sections is not a list."""
        data = {"doc_id": "test", "title": "Test", "sections": "not a list"}
        errors = validate_document_root(data, "test.yml")
        assert len(errors) == 1
        assert errors[0]["error_type"] == "invalid_type"

    def test_accepts_valid_list_type_fields(self) -> None:
        """Should accept valid list-type optional fields."""
        data = {
            "doc_id": "test",
            "title": "Test",
            "sections": [],
            "domain": ["yaml", "documentation"],
            "primary_runtime_references": [{"path": "app/main.py"}],
            "related_docs": [{"doc_id": "other-doc"}],
            "external_references": [{"url": "https://example.com"}],
        }
        errors = validate_document_root(data, "test.yml")
        assert errors == []

    def test_reports_invalid_domain_type(self) -> None:
        """Should report when domain is not a list."""
        data = {"doc_id": "test", "title": "Test", "sections": [], "domain": "yaml"}
        errors = validate_document_root(data, "test.yml")
        assert len(errors) == 1
        assert errors[0]["error_type"] == "invalid_type"
        assert "domain" in errors[0]["message"]
        assert "str" in errors[0]["message"]

    def test_reports_invalid_primary_runtime_references_type(self) -> None:
        """Should report when primary_runtime_references is not a list."""
        data = {
            "doc_id": "test",
            "title": "Test",
            "sections": [],
            "primary_runtime_references": "app/main.py",
        }
        errors = validate_document_root(data, "test.yml")
        assert len(errors) == 1
        assert errors[0]["error_type"] == "invalid_type"
        assert "primary_runtime_references" in errors[0]["message"]

    def test_reports_invalid_related_docs_type(self) -> None:
        """Should report when related_docs is not a list."""
        data = {
            "doc_id": "test",
            "title": "Test",
            "sections": [],
            "related_docs": "other-doc",
        }
        errors = validate_document_root(data, "test.yml")
        assert len(errors) == 1
        assert errors[0]["error_type"] == "invalid_type"
        assert "related_docs" in errors[0]["message"]

    def test_reports_invalid_external_references_type(self) -> None:
        """Should report when external_references is not a list."""
        data = {
            "doc_id": "test",
            "title": "Test",
            "sections": [],
            "external_references": "https://example.com",
        }
        errors = validate_document_root(data, "test.yml")
        assert len(errors) == 1
        assert errors[0]["error_type"] == "invalid_type"
        assert "external_references" in errors[0]["message"]

    def test_reports_multiple_invalid_list_type_fields(self) -> None:
        """Should report all invalid list-type fields."""
        data = {
            "doc_id": "test",
            "title": "Test",
            "sections": [],
            "domain": "yaml",
            "related_docs": "other-doc",
        }
        errors = validate_document_root(data, "test.yml")
        assert len(errors) == 2
        error_fields = {e["message"].split("'")[1] for e in errors}
        assert "domain" in error_fields
        assert "related_docs" in error_fields

    def test_omitted_list_type_fields_pass(self) -> None:
        """Should pass when optional list-type fields are omitted."""
        data = {"doc_id": "test", "title": "Test", "sections": []}
        errors = validate_document_root(data, "test.yml")
        assert errors == []


class TestValidateSections:
    """Tests for validate_sections function."""

    def test_returns_empty_when_all_sections_have_ids(self) -> None:
        """Should return empty list when all sections have IDs."""
        sections = [
            {"id": "section-1", "title": "First"},
            {"id": "section-2", "title": "Second"},
        ]
        errors = validate_sections(sections, "test.yml")
        assert errors == []

    def test_reports_missing_section_id(self) -> None:
        """Should report section missing ID."""
        sections = [{"title": "No ID Section"}]
        errors = validate_sections(sections, "test.yml")
        assert len(errors) == 1
        assert errors[0]["error_type"] == "missing_section_id"
        assert "index 0" in errors[0]["message"]

    def test_includes_title_hint_in_error(self) -> None:
        """Should include section title in error message as hint."""
        sections = [{"title": "Missing ID"}]
        errors = validate_sections(sections, "test.yml")
        assert "Missing ID" in errors[0]["message"]

    def test_reports_invalid_section_type(self) -> None:
        """Should report when section is not a dict."""
        sections = ["not a dict", {"id": "valid"}]
        errors = validate_sections(sections, "test.yml")
        assert len(errors) == 1
        assert errors[0]["error_type"] == "invalid_section_type"

    def test_reports_multiple_missing_ids(self) -> None:
        """Should report all sections missing IDs."""
        sections = [
            {"title": "First"},
            {"id": "valid"},
            {"title": "Third"},
        ]
        errors = validate_sections(sections, "test.yml")
        assert len(errors) == 2


class TestLintYamlFile:
    """Tests for lint_yaml_file function."""

    def test_skips_non_doc_files(self, fs: FakeFilesystem) -> None:
        """Should return is_doc_file=False for non-documentation files."""
        with patch.object(lint_yaml_docs, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            fs.create_file("/fake/config.yml", contents="key: value")

            result = lint_yaml_file(Path("/fake/config.yml"))

            assert result["is_doc_file"] is False
            assert result["errors"] == []

    def test_validates_documentation_files(self, fs: FakeFilesystem) -> None:
        """Should validate documentation files and return errors."""
        with patch.object(lint_yaml_docs, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            # Missing title
            fs.create_file(
                "/fake/doc.yml",
                contents="doc_id: test\nsections:\n  - id: section-1",
            )

            result = lint_yaml_file(Path("/fake/doc.yml"))

            assert result["is_doc_file"] is True
            assert len(result["errors"]) == 1
            assert "title" in result["errors"][0]["message"]

    def test_handles_yaml_parse_errors(self, fs: FakeFilesystem) -> None:
        """Should handle YAML parse errors gracefully."""
        with patch.object(lint_yaml_docs, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            fs.create_file("/fake/bad.yml", contents="invalid: yaml: content:")

            result = lint_yaml_file(Path("/fake/bad.yml"))

            assert len(result["errors"]) == 1
            assert result["errors"][0]["error_type"] == "yaml_parse_error"

    def test_skips_non_dict_yaml(self, fs: FakeFilesystem) -> None:
        """Should skip YAML files that parse to non-dict."""
        with patch.object(lint_yaml_docs, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            fs.create_file("/fake/list.yml", contents="- item1\n- item2")

            result = lint_yaml_file(Path("/fake/list.yml"))

            assert result["is_doc_file"] is False


class TestFindYamlFiles:
    """Tests for find_yaml_files function."""

    def test_finds_yml_files(self, fs: FakeFilesystem) -> None:
        """Should find .yml files."""
        fs.create_dir("/search")
        fs.create_file("/search/file1.yml", contents="")
        fs.create_file("/search/file2.yml", contents="")

        result = find_yaml_files(Path("/search"))

        assert len(result) == 2

    def test_finds_yaml_files(self, fs: FakeFilesystem) -> None:
        """Should find .yaml files."""
        fs.create_dir("/search")
        fs.create_file("/search/file1.yaml", contents="")

        result = find_yaml_files(Path("/search"))

        assert len(result) == 1

    def test_searches_recursively(self, fs: FakeFilesystem) -> None:
        """Should search subdirectories recursively."""
        fs.create_dir("/search/sub")
        fs.create_file("/search/root.yml", contents="")
        fs.create_file("/search/sub/nested.yml", contents="")

        result = find_yaml_files(Path("/search"))

        assert len(result) == 2


class TestLintDirectory:
    """Tests for lint_directory function."""

    def test_counts_doc_files_and_errors(self, fs: FakeFilesystem) -> None:
        """Should count documentation files and errors."""
        with patch.object(lint_yaml_docs, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file(
                "/fake/docs/valid.yml",
                contents="doc_id: valid\ntitle: Valid\nsections:\n  - id: sec-1",
            )
            fs.create_file(
                "/fake/docs/invalid.yml",
                contents="doc_id: invalid\nsections:\n  - id: sec-1",  # missing title
            )
            fs.create_file("/fake/docs/config.yml", contents="key: value")  # not a doc

            results, doc_count, error_count = lint_directory(Path("/fake/docs"))

            assert doc_count == 2  # two doc files
            assert error_count == 1  # one error in invalid.yml


class TestFormatErrors:
    """Tests for format_errors function."""

    def test_formats_errors(self) -> None:
        """Should format errors for display."""
        results = [
            LintResult(
                file_path="test.yml",
                is_doc_file=True,
                errors=[
                    LintError(
                        file_path="test.yml",
                        line=None,
                        error_type="missing_required_field",
                        message="Missing 'title'",
                    )
                ],
            )
        ]

        output = format_errors(results)

        assert "test.yml" in output
        assert "missing_required_field" in output
        assert "Missing 'title'" in output

    def test_skips_results_without_errors(self) -> None:
        """Should skip results with no errors."""
        results = [LintResult(file_path="clean.yml", is_doc_file=True, errors=[])]

        output = format_errors(results)

        assert output == ""


class TestMain:
    """Tests for main function."""

    def test_returns_one_for_invalid_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 for non-existent path."""
        nonexistent = tmp_path / "nonexistent"
        result = main(["--path", str(nonexistent)])

        assert result == 1
        captured = capsys.readouterr()
        assert "does not exist" in captured.err

    def test_returns_zero_when_no_errors(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 when no errors found."""
        with patch.object(lint_yaml_docs, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file(
                "/fake/docs/valid.yml",
                contents="doc_id: test\ntitle: Test\nsections:\n  - id: sec-1",
            )

            result = main(["--path", "/fake/docs"])

            assert result == 0
            captured = capsys.readouterr()
            assert "No errors found" in captured.out

    def test_returns_one_when_errors_found(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when errors found."""
        with patch.object(lint_yaml_docs, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file(
                "/fake/docs/invalid.yml",
                contents="doc_id: test\nsections:\n  - id: sec-1",  # missing title
            )

            result = main(["--path", "/fake/docs"])

            assert result == 1
            captured = capsys.readouterr()
            assert "error" in captured.out
