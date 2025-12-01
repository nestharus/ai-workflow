"""Tests for scripts.grep_yml_ids module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import yaml

from scripts import grep_yml_ids
from scripts.grep_yml_ids import (
    TEXT_FIELDS,
    MatchResult,
    _extract_text_content,
    _search_structure,
    _validate_yaml_result,
    format_json,
    format_table,
    main,
    parse_args,
    parse_yaml_file,
    search_yaml_files,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestTextFields:
    """Tests for TEXT_FIELDS constant."""

    def test_has_required_fields(self) -> None:
        """Should have all expected text fields."""
        assert "text" in TEXT_FIELDS
        assert "description" in TEXT_FIELDS
        assert "summary" in TEXT_FIELDS
        assert "title" in TEXT_FIELDS


class TestParseArgs:
    """Tests for parse_args function."""

    def test_requires_id_argument(self) -> None:
        """Should require --id argument."""
        with pytest.raises(SystemExit):
            parse_args([])

    def test_parses_id_argument(self) -> None:
        """Should parse --id argument."""
        args = parse_args(["--id", "test.id"])
        assert args.id == "test.id"

    def test_default_path(self) -> None:
        """Should use default development directory."""
        args = parse_args(["--id", "test"])
        assert "development" in str(args.path)

    def test_custom_path(self) -> None:
        """Should accept custom path."""
        args = parse_args(["--id", "test", "--path", "/custom/path"])
        assert args.path == Path("/custom/path")

    def test_exact_flag_default_false(self) -> None:
        """Should default exact to False."""
        args = parse_args(["--id", "test"])
        assert args.exact is False

    def test_exact_flag_when_set(self) -> None:
        """Should set exact to True when flag is provided."""
        args = parse_args(["--id", "test", "--exact"])
        assert args.exact is True

    def test_output_default_table(self) -> None:
        """Should default output to table."""
        args = parse_args(["--id", "test"])
        assert args.output == "table"

    def test_output_json(self) -> None:
        """Should accept json output format."""
        args = parse_args(["--id", "test", "--output", "json"])
        assert args.output == "json"

    def test_invalid_output_rejected(self) -> None:
        """Should reject invalid output format."""
        with pytest.raises(SystemExit):
            parse_args(["--id", "test", "--output", "xml"])


class TestValidateYamlResult:
    """Tests for _validate_yaml_result function."""

    def test_accepts_dict(self) -> None:
        """Should accept dictionary result."""
        result = _validate_yaml_result({"key": "value"}, Path("/test.yml"))
        assert result == {"key": "value"}

    def test_accepts_list(self) -> None:
        """Should accept list result."""
        result = _validate_yaml_result([1, 2, 3], Path("/test.yml"))
        assert result == [1, 2, 3]

    def test_raises_for_string(self, fs: FakeFilesystem) -> None:
        """Should raise TypeError for string result."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            with pytest.raises(TypeError) as exc_info:
                _validate_yaml_result("string", Path("/fake/test.yml"))
            assert "expected dict or list" in str(exc_info.value)

    def test_raises_for_none(self, fs: FakeFilesystem) -> None:
        """Should raise TypeError for None result."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            with pytest.raises(TypeError):
                _validate_yaml_result(None, Path("/fake/test.yml"))

    def test_raises_for_int(self, fs: FakeFilesystem) -> None:
        """Should raise TypeError for integer result."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            with pytest.raises(TypeError):
                _validate_yaml_result(42, Path("/fake/test.yml"))


class TestParseYamlFile:
    """Tests for parse_yaml_file function."""

    def test_parses_valid_yaml_dict(self, fs: FakeFilesystem) -> None:
        """Should parse valid YAML file with dict content."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            fs.create_file("/fake/test.yml", contents="key: value\n")

            result = parse_yaml_file(Path("/fake/test.yml"))

            assert result == {"key": "value"}

    def test_parses_valid_yaml_list(self, fs: FakeFilesystem) -> None:
        """Should parse valid YAML file with list content."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            fs.create_file("/fake/test.yml", contents="- item1\n- item2\n")

            result = parse_yaml_file(Path("/fake/test.yml"))

            assert result == ["item1", "item2"]

    def test_raises_for_invalid_yaml(self, fs: FakeFilesystem) -> None:
        """Should raise YAMLError for invalid YAML."""
        fs.create_file("/test.yml", contents="invalid: yaml: content:")

        with pytest.raises(yaml.YAMLError):
            parse_yaml_file(Path("/test.yml"))

    def test_raises_for_missing_file(self) -> None:
        """Should raise FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            parse_yaml_file(Path("/nonexistent.yml"))


class TestExtractTextContent:
    """Tests for _extract_text_content function."""

    def test_extracts_text_field(self) -> None:
        """Should extract text field."""
        element = {"id": "test", "text": "Some text"}
        result = _extract_text_content(element)
        assert result == "Some text"

    def test_extracts_description_field(self) -> None:
        """Should extract description field."""
        element = {"id": "test", "description": "A description"}
        result = _extract_text_content(element)
        assert result == "A description"

    def test_extracts_summary_field(self) -> None:
        """Should extract summary field."""
        element = {"id": "test", "summary": "A summary"}
        result = _extract_text_content(element)
        assert result == "A summary"

    def test_extracts_title_field(self) -> None:
        """Should extract title field."""
        element = {"id": "test", "title": "A title"}
        result = _extract_text_content(element)
        assert result == "A title"

    def test_concatenates_multiple_fields(self) -> None:
        """Should concatenate multiple text fields with separator."""
        element = {"text": "Text", "description": "Description"}
        result = _extract_text_content(element)
        assert "Text" in result
        assert "Description" in result
        assert " | " in result

    def test_ignores_empty_fields(self) -> None:
        """Should ignore empty or whitespace-only fields."""
        element = {"text": "Valid", "description": "   "}
        result = _extract_text_content(element)
        assert result == "Valid"

    def test_returns_empty_for_no_text_fields(self) -> None:
        """Should return empty string when no text fields present."""
        element = {"id": "test", "type": "rule"}
        result = _extract_text_content(element)
        assert result == ""

    def test_ignores_non_string_values(self) -> None:
        """Should ignore non-string text field values."""
        element = {"text": ["list", "items"]}
        result = _extract_text_content(element)
        assert result == ""


class TestSearchStructure:
    """Tests for _search_structure function."""

    def test_finds_exact_match(self, fs: FakeFilesystem) -> None:
        """Should find exact ID match."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            data = {"id": "test.item", "text": "Test text"}

            results = _search_structure(
                data, "test.item", exact=True, file_path=Path("/fake/test.yml")
            )

            assert len(results) == 1
            assert results[0]["element_id"] == "test.item"

    def test_finds_partial_match(self, fs: FakeFilesystem) -> None:
        """Should find partial ID match."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            data = {"id": "url.prefix", "text": "Test text"}

            results = _search_structure(data, "url", exact=False, file_path=Path("/fake/test.yml"))

            assert len(results) == 1
            assert results[0]["element_id"] == "url.prefix"

    def test_exact_match_rejects_partial(self, fs: FakeFilesystem) -> None:
        """Should reject partial match when exact=True."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            data = {"id": "url.prefix", "text": "Test text"}

            results = _search_structure(data, "url", exact=True, file_path=Path("/fake/test.yml"))

            assert len(results) == 0

    def test_searches_nested_dict(self, fs: FakeFilesystem) -> None:
        """Should search nested dictionaries."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            data = {
                "sections": {
                    "id": "section-1",
                    "items": {"id": "nested.item", "text": "Nested text"},
                }
            }

            results = _search_structure(
                data, "nested.item", exact=True, file_path=Path("/fake/test.yml")
            )

            assert len(results) == 1

    def test_searches_list_items(self, fs: FakeFilesystem) -> None:
        """Should search list items."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            data = [
                {"id": "item-1", "text": "First"},
                {"id": "item-2", "text": "Second"},
            ]

            results = _search_structure(data, "item", exact=False, file_path=Path("/fake/test.yml"))

            assert len(results) == 2

    def test_tracks_section_context(self, fs: FakeFilesystem) -> None:
        """Should track section context for nested items."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            data = {
                "id": "parent-section",
                "items": [{"id": "child.item", "text": "Child text"}],
            }

            results = _search_structure(
                data, "child.item", exact=True, file_path=Path("/fake/test.yml")
            )

            assert len(results) == 1
            assert results[0]["section_id"] == "parent-section"

    def test_extracts_item_type(self, fs: FakeFilesystem) -> None:
        """Should extract item type if present."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            data = {"id": "test.rule", "type": "rule", "text": "Rule text"}

            results = _search_structure(
                data, "test.rule", exact=True, file_path=Path("/fake/test.yml")
            )

            assert len(results) == 1
            assert results[0]["item_type"] == "rule"

    def test_ignores_non_string_ids(self, fs: FakeFilesystem) -> None:
        """Should ignore non-string ID values."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            data = {"id": 123, "text": "Text"}

            results = _search_structure(data, "123", exact=True, file_path=Path("/fake/test.yml"))

            assert len(results) == 0


class TestSearchYamlFiles:
    """Tests for search_yaml_files function."""

    def test_searches_yml_files(self, fs: FakeFilesystem) -> None:
        """Should search .yml files in directory."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            content = "id: test.id\ntext: Test text\n"
            fs.create_file("/fake/docs/test.yml", contents=content)

            results = search_yaml_files("test.id", Path("/fake/docs"), exact=True)

            assert len(results) == 1
            assert results[0]["element_id"] == "test.id"

    def test_searches_yaml_files(self, fs: FakeFilesystem) -> None:
        """Should search .yaml files in directory."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            content = "id: test.id\ntext: Test text\n"
            fs.create_file("/fake/docs/test.yaml", contents=content)

            results = search_yaml_files("test.id", Path("/fake/docs"), exact=True)

            assert len(results) == 1

    def test_searches_subdirectories(self, fs: FakeFilesystem) -> None:
        """Should search recursively in subdirectories."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs/subdir")
            content = "id: nested.id\ntext: Nested text\n"
            fs.create_file("/fake/docs/subdir/test.yml", contents=content)

            results = search_yaml_files("nested.id", Path("/fake/docs"), exact=True)

            assert len(results) == 1

    def test_aggregates_results_from_multiple_files(self, fs: FakeFilesystem) -> None:
        """Should aggregate results from multiple files."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file("/fake/docs/file1.yml", contents="id: url.prefix\ntext: One\n")
            fs.create_file("/fake/docs/file2.yml", contents="id: url.suffix\ntext: Two\n")

            results = search_yaml_files("url", Path("/fake/docs"), exact=False)

            assert len(results) == 2

    def test_handles_invalid_yaml_gracefully(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should warn and continue when YAML parsing fails."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file("/fake/docs/valid.yml", contents="id: test\ntext: Valid\n")
            fs.create_file("/fake/docs/invalid.yml", contents="bad: yaml: content:")

            results = search_yaml_files("test", Path("/fake/docs"), exact=True)

            assert len(results) == 1
            captured = capsys.readouterr()
            assert "Warning" in captured.err

    def test_returns_empty_for_no_matches(self, fs: FakeFilesystem) -> None:
        """Should return empty list when no matches found."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file("/fake/docs/test.yml", contents="id: other.id\ntext: Text\n")

            results = search_yaml_files("nonexistent", Path("/fake/docs"), exact=True)

            assert len(results) == 0


class TestFormatTable:
    """Tests for format_table function."""

    def test_formats_no_matches(self) -> None:
        """Should return no matches message for empty results."""
        result = format_table([])
        assert "No matches found" in result

    def test_formats_single_match(self) -> None:
        """Should format single match."""
        results: list[MatchResult] = [
            MatchResult(
                file_path="docs/test.yml",
                element_id="test.id",
                text="Test text",
                section_id=None,
                item_type=None,
            )
        ]

        output = format_table(results)

        assert "1 match" in output
        assert "test.id" in output
        assert "docs/test.yml" in output
        assert "Test text" in output

    def test_formats_multiple_matches(self) -> None:
        """Should format multiple matches."""
        results: list[MatchResult] = [
            MatchResult(
                file_path="docs/test1.yml",
                element_id="id-1",
                text="Text 1",
                section_id=None,
                item_type=None,
            ),
            MatchResult(
                file_path="docs/test2.yml",
                element_id="id-2",
                text="Text 2",
                section_id=None,
                item_type=None,
            ),
        ]

        output = format_table(results)

        assert "2 match" in output
        assert "[1]" in output
        assert "[2]" in output

    def test_includes_section_id(self) -> None:
        """Should include section ID when present."""
        results: list[MatchResult] = [
            MatchResult(
                file_path="docs/test.yml",
                element_id="test.id",
                text="Test text",
                section_id="parent-section",
                item_type=None,
            )
        ]

        output = format_table(results)

        assert "Section: parent-section" in output

    def test_includes_item_type(self) -> None:
        """Should include item type when present."""
        results: list[MatchResult] = [
            MatchResult(
                file_path="docs/test.yml",
                element_id="test.id",
                text="Test text",
                section_id=None,
                item_type="rule",
            )
        ]

        output = format_table(results)

        assert "Type: rule" in output

    def test_truncates_long_text(self) -> None:
        """Should truncate text longer than 200 characters."""
        long_text = "x" * 250
        results: list[MatchResult] = [
            MatchResult(
                file_path="docs/test.yml",
                element_id="test.id",
                text=long_text,
                section_id=None,
                item_type=None,
            )
        ]

        output = format_table(results)

        assert "..." in output
        assert len(long_text) > 200


class TestFormatJson:
    """Tests for format_json function."""

    def test_formats_empty_results(self) -> None:
        """Should return empty JSON array for no results."""
        result = format_json([])
        assert result == "[]"

    def test_formats_results_as_json(self) -> None:
        """Should format results as valid JSON."""
        import json

        results: list[MatchResult] = [
            MatchResult(
                file_path="docs/test.yml",
                element_id="test.id",
                text="Test text",
                section_id="section-1",
                item_type="rule",
            )
        ]

        output = format_json(results)
        parsed = json.loads(output)

        assert len(parsed) == 1
        assert parsed[0]["file_path"] == "docs/test.yml"
        assert parsed[0]["element_id"] == "test.id"
        assert parsed[0]["text"] == "Test text"
        assert parsed[0]["section_id"] == "section-1"
        assert parsed[0]["item_type"] == "rule"

    def test_includes_null_for_none_values(self) -> None:
        """Should include null for None values in JSON."""
        import json

        results: list[MatchResult] = [
            MatchResult(
                file_path="docs/test.yml",
                element_id="test.id",
                text="Test text",
                section_id=None,
                item_type=None,
            )
        ]

        output = format_json(results)
        parsed = json.loads(output)

        assert parsed[0]["section_id"] is None
        assert parsed[0]["item_type"] is None


class TestMain:
    """Tests for main function."""

    def test_returns_one_for_invalid_path(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 for non-existent path."""
        with patch("sys.argv", ["script", "--id", "test", "--path", "/nonexistent"]):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "does not exist" in captured.err

    def test_returns_one_for_file_path(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when path is a file, not directory."""
        fs.create_file("/test.yml", contents="id: test\n")

        with patch("sys.argv", ["script", "--id", "test", "--path", "/test.yml"]):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "not a directory" in captured.err

    def test_returns_one_for_no_matches(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when no matches found."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file("/fake/docs/test.yml", contents="id: other.id\ntext: Text\n")

            with patch("sys.argv", ["script", "--id", "nonexistent", "--path", "/fake/docs"]):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "No matches found" in captured.out

    def test_returns_zero_for_matches(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 when matches found."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file("/fake/docs/test.yml", contents="id: test.id\ntext: Found\n")

            with patch("sys.argv", ["script", "--id", "test.id", "--path", "/fake/docs"]):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "1 match" in captured.out

    def test_outputs_table_by_default(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should output table format by default."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file("/fake/docs/test.yml", contents="id: test.id\ntext: Text\n")

            with patch("sys.argv", ["script", "--id", "test.id", "--path", "/fake/docs"]):
                main()

        captured = capsys.readouterr()
        assert "File:" in captured.out
        assert "Text:" in captured.out

    def test_outputs_json_when_requested(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should output JSON format when requested."""
        import json

        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file("/fake/docs/test.yml", contents="id: test.id\ntext: Text\n")

            with patch(
                "sys.argv",
                ["script", "--id", "test.id", "--path", "/fake/docs", "--output", "json"],
            ):
                main()

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert len(parsed) == 1
        assert parsed[0]["element_id"] == "test.id"

    def test_exact_match_mode(self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]) -> None:
        """Should respect exact match mode."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file("/fake/docs/test.yml", contents="id: url.prefix\ntext: Text\n")

            # Partial match without --exact should find it
            with patch("sys.argv", ["script", "--id", "url", "--path", "/fake/docs"]):
                result_partial = main()

            # Exact match should not find it
            with patch("sys.argv", ["script", "--id", "url", "--path", "/fake/docs", "--exact"]):
                result_exact = main()

        assert result_partial == 0
        assert result_exact == 1
