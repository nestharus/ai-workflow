"""Tests for scripts.knowledge.compare_yaml_docs module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import yaml

from scripts.knowledge import compare_yaml_docs
from scripts.knowledge.compare_yaml_docs import (
    CSV_COLUMNS,
    ComparisonEntry,
    SplitEntry,
    _extract_text_content,
    _flatten_entry_to_rows,
    _strip_timestamp_prefix,
    _validate_yaml_result,
    aggregate_split_texts,
    compare_original_to_splits,
    extract_ids_and_text,
    find_all_yml,
    find_mapped_splits,
    find_originals,
    get_ids_text,
    main,
    parse_args,
    parse_yaml_file,
    pattern_from_path,
    write_compare_files,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_path(self) -> None:
        """Should use default development directory."""
        args = parse_args([])
        assert "development" in str(args.path)

    def test_custom_path(self) -> None:
        """Should accept custom path."""
        args = parse_args(["--path", "/custom/path"])
        assert args.path == Path("/custom/path")

    def test_original_files(self) -> None:
        """Should accept original-files argument."""
        args = parse_args(["--original-files", "/file1.yml", "/file2.yml"])
        assert len(args.original_files) == 2


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
        with patch.object(compare_yaml_docs, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            with pytest.raises(TypeError) as exc_info:
                _validate_yaml_result("string", Path("/fake/test.yml"))
            assert "expected dict or list" in str(exc_info.value)

    def test_raises_for_none(self, fs: FakeFilesystem) -> None:
        """Should raise TypeError for None result."""
        with patch.object(compare_yaml_docs, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            with pytest.raises(TypeError):
                _validate_yaml_result(None, Path("/fake/test.yml"))


class TestParseYamlFile:
    """Tests for parse_yaml_file function."""

    def test_parses_valid_yaml(self, fs: FakeFilesystem) -> None:
        """Should parse valid YAML file."""
        with patch.object(compare_yaml_docs, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            fs.create_file("/fake/test.yml", contents="key: value\n")

            result = parse_yaml_file(Path("/fake/test.yml"))

            assert result == {"key": "value"}

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
        element = {"text": "Some text"}
        result = _extract_text_content(element)  # type: ignore[arg-type]
        assert result == "Some text"

    def test_extracts_multiple_fields(self) -> None:
        """Should concatenate multiple text fields."""
        element = {"text": "Text", "description": "Description"}
        result = _extract_text_content(element)  # type: ignore[arg-type]
        assert "Text" in result
        assert "Description" in result
        assert " | " in result

    def test_ignores_empty_fields(self) -> None:
        """Should ignore empty or whitespace-only fields."""
        element = {"text": "Valid", "description": "   "}
        result = _extract_text_content(element)  # type: ignore[arg-type]
        assert result == "Valid"

    def test_returns_empty_for_no_text_fields(self) -> None:
        """Should return empty string when no text fields present."""
        element = {"id": "test", "other": "value"}
        result = _extract_text_content(element)  # type: ignore[arg-type]
        assert result == ""


class TestExtractIdsAndText:
    """Tests for extract_ids_and_text function."""

    def test_extracts_from_dict(self) -> None:
        """Should extract IDs from dictionary structure."""
        data = {
            "id": "item-1",
            "text": "Item text",
        }
        result = extract_ids_and_text(data)  # type: ignore[arg-type]
        assert "item-1" in result
        assert result["item-1"] == "Item text"

    def test_extracts_from_nested_dict(self) -> None:
        """Should extract IDs from nested dictionaries."""
        data = {
            "sections": {
                "id": "section-1",
                "text": "Section text",
            }
        }
        result = extract_ids_and_text(data)  # type: ignore[arg-type]
        assert "section-1" in result

    def test_extracts_from_list(self) -> None:
        """Should extract IDs from list items."""
        data = [
            {"id": "item-1", "text": "Text 1"},
            {"id": "item-2", "text": "Text 2"},
        ]
        result = extract_ids_and_text(data)  # type: ignore[arg-type]
        assert "item-1" in result
        assert "item-2" in result

    def test_ignores_non_string_ids(self) -> None:
        """Should ignore non-string ID values."""
        data = {"id": 123, "text": "Text"}
        result = extract_ids_and_text(data)  # type: ignore[arg-type]
        assert len(result) == 0


class TestStripTimestampPrefix:
    """Tests for _strip_timestamp_prefix function."""

    def test_strips_timestamp(self) -> None:
        """Should strip ISO 8601 timestamp prefix."""
        result = _strip_timestamp_prefix("20251201T134735Z-api-patterns")
        assert result == "api-patterns"

    def test_returns_original_without_timestamp(self) -> None:
        """Should return original if no timestamp prefix."""
        result = _strip_timestamp_prefix("api-patterns")
        assert result == "api-patterns"


class TestPatternFromPath:
    """Tests for pattern_from_path function."""

    def test_extracts_from_original_file(self) -> None:
        """Should extract pattern from original.*.yml file."""
        result = pattern_from_path(Path("/docs/original.api-patterns.yml"))
        assert result == "api-patterns"

    def test_extracts_from_split_file(self) -> None:
        """Should extract pattern from split file."""
        result = pattern_from_path(Path("/docs/python/python.api-patterns.yml"))
        assert result == "api-patterns"

    def test_extracts_from_timestamped_file(self) -> None:
        """Should extract pattern from timestamped file."""
        result = pattern_from_path(Path("/docs/20251201T134735Z-api-patterns.yml"))
        assert result == "api-patterns"


class TestFindOriginals:
    """Tests for find_originals function."""

    def test_finds_original_files(self, fs: FakeFilesystem) -> None:
        """Should find original.*.yml files."""
        fs.create_dir("/docs")
        fs.create_file("/docs/original.api-patterns.yml", contents="")
        fs.create_file("/docs/original.other-patterns.yml", contents="")

        result = find_originals(Path("/docs"))

        assert len(result) == 2

    def test_uses_provided_original_files(self, fs: FakeFilesystem) -> None:
        """Should use provided original files instead of globbing."""
        fs.create_dir("/docs")
        fs.create_file("/docs/custom.yml", contents="")

        result = find_originals(Path("/docs"), [Path("/docs/custom.yml")])

        assert len(result) == 1
        assert result[0].name == "custom.yml"

    def test_filters_nonexistent_original_files(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should filter out non-existent provided files with warning."""
        fs.create_dir("/docs")
        fs.create_file("/docs/exists.yml", contents="")

        result = find_originals(
            Path("/docs"), [Path("/docs/exists.yml"), Path("/docs/missing.yml")]
        )

        assert len(result) == 1
        captured = capsys.readouterr()
        assert "does not exist" in captured.err


class TestFindAllYml:
    """Tests for find_all_yml function."""

    def test_finds_yml_in_subdirs(self, fs: FakeFilesystem) -> None:
        """Should find .yml files in configured subdirectories."""
        fs.create_dir("/docs/python")
        fs.create_dir("/docs/fastapi")
        fs.create_file("/docs/python/python.api-patterns.yml", contents="")
        fs.create_file("/docs/fastapi/fastapi.api-patterns.yml", contents="")

        result = find_all_yml(Path("/docs"))

        assert len(result) == 2


class TestFindMappedSplits:
    """Tests for find_mapped_splits function."""

    def test_finds_matching_splits(self, fs: FakeFilesystem) -> None:
        """Should find split files matching pattern."""
        fs.create_dir("/docs/python")
        fs.create_file("/docs/python/python.api-patterns.yml", contents="")

        result = find_mapped_splits("api-patterns", Path("/docs"))

        assert "python" in result
        assert result["python"].name == "python.api-patterns.yml"


class TestGetIdsText:
    """Tests for get_ids_text function."""

    def test_extracts_ids_and_text(self, fs: FakeFilesystem) -> None:
        """Should extract IDs and text from YAML file."""
        with patch.object(compare_yaml_docs, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            content = """
id: root
items:
  - id: item-1
    text: Item 1 text
"""
            fs.create_file("/fake/test.yml", contents=content)

            result = get_ids_text(Path("/fake/test.yml"))

            assert "item-1" in result


class TestAggregateSplitTexts:
    """Tests for aggregate_split_texts function."""

    def test_aggregates_text_by_id(self, fs: FakeFilesystem) -> None:
        """Should aggregate text content by ID across files."""
        with patch.object(compare_yaml_docs, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/python")
            content = """
items:
  - id: item-1
    text: Python item text
"""
            fs.create_file("/fake/python/python.test.yml", contents=content)

            split_map = {"python": Path("/fake/python/python.test.yml")}
            result = aggregate_split_texts(split_map)

            assert "item-1" in result


class TestCompareOriginalToSplits:
    """Tests for compare_original_to_splits function."""

    def test_finds_differences(self, fs: FakeFilesystem) -> None:
        """Should find text differences between original and splits."""
        with patch.object(compare_yaml_docs, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/python")

            orig_content = """
items:
  - id: item-1
    text: Original text
"""
            split_content = """
items:
  - id: item-1
    text: Modified text
"""
            fs.create_file("/fake/original.yml", contents=orig_content)
            fs.create_file("/fake/python/python.test.yml", contents=split_content)

            split_map = {"python": Path("/fake/python/python.test.yml")}
            result = compare_original_to_splits(Path("/fake/original.yml"), split_map)

            assert len(result) > 0


class TestFlattenEntryToRows:
    """Tests for _flatten_entry_to_rows function."""

    def test_flattens_entry_with_splits(self) -> None:
        """Should create one row per split."""
        entry = ComparisonEntry(
            source_file="source.yml",
            id="item-1",
            source_text="Original",
            splits=[
                SplitEntry(split_text="Split 1", source_file="split1.yml"),
                SplitEntry(split_text="Split 2", source_file="split2.yml"),
            ],
            origin_type="original",
        )

        rows = _flatten_entry_to_rows(entry)

        assert len(rows) == 2

    def test_flattens_entry_without_splits(self) -> None:
        """Should create one row with empty split columns."""
        entry = ComparisonEntry(
            source_file="source.yml",
            id="item-1",
            source_text="Original",
            splits=[],
            origin_type="split_only",
        )

        rows = _flatten_entry_to_rows(entry)

        assert len(rows) == 1
        assert rows[0]["split_file"] == ""
        assert rows[0]["split_text"] == ""


class TestWriteCompareFiles:
    """Tests for write_compare_files function."""

    def test_writes_csv_files(self, tmp_path: Path) -> None:
        """Should write CSV files with comparison results.

        DuckDB requires real filesystem.
        """
        (tmp_path / ".knowledge" / "comparisons").mkdir(parents=True)

        with patch.object(compare_yaml_docs, "REPO_ROOT", tmp_path):
            results = {
                "docs/original.api-patterns.yml": {
                    "original_file": "docs/original.api-patterns.yml",
                    "entries": [
                        ComparisonEntry(
                            source_file="docs/original.api-patterns.yml",
                            id="item-1",
                            source_text="Text",
                            splits=[],
                            origin_type="original",
                        )
                    ],
                }
            }

            count = write_compare_files(results)  # type: ignore[arg-type]

            assert count == 1


class TestCsvColumns:
    """Tests for CSV_COLUMNS constant."""

    def test_has_required_columns(self) -> None:
        """Should have all required columns."""
        assert "source_file" in CSV_COLUMNS
        assert "id" in CSV_COLUMNS
        assert "origin_type" in CSV_COLUMNS
        assert "original_text" in CSV_COLUMNS
        assert "split_file" in CSV_COLUMNS
        assert "split_text" in CSV_COLUMNS


class TestMain:
    """Tests for main function."""

    def test_returns_one_for_invalid_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 for non-existent path."""
        nonexistent = tmp_path / "nonexistent"
        with patch("sys.argv", ["script", "--path", str(nonexistent)]):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "does not exist" in captured.err

    def test_returns_zero_when_no_differences(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 when no differences found."""
        # Create docs structure
        docs_dir = tmp_path / "docs"
        python_dir = docs_dir / "python"
        knowledge_dir = tmp_path / ".knowledge"

        docs_dir.mkdir()
        python_dir.mkdir()
        (knowledge_dir / "comparisons").mkdir(parents=True)

        # Create matching original and split
        content = """
items:
  - id: item-1
    text: Same text
"""
        (docs_dir / "original.test.yml").write_text(content)
        (python_dir / "python.test.yml").write_text(content)

        with (
            patch.object(compare_yaml_docs, "REPO_ROOT", tmp_path),
            patch.object(compare_yaml_docs, "DEVELOPMENT_DIR", docs_dir),
            patch("sys.argv", ["script", "--path", str(docs_dir)]),
        ):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "No differences found" in captured.out
