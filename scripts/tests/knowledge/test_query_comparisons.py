"""Tests for scripts.knowledge.query_comparisons module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts.knowledge.query_comparisons import (
    build_query,
    format_results,
    get_comparison_csv_paths,
    main,
    parse_args,
)
from scripts.knowledge.query_comparisons import (
    query_comparisons as query_comparisons_func,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestGetComparisonCsvPaths:
    """Tests for get_comparison_csv_paths function."""

    def test_finds_all_csvs(self, fs: FakeFilesystem) -> None:
        """Should find all CSV files in comparisons directory."""
        fs.create_dir("/knowledge/comparisons")
        fs.create_file("/knowledge/comparisons/api-patterns.csv", contents="")
        fs.create_file("/knowledge/comparisons/other-patterns.csv", contents="")

        result = get_comparison_csv_paths(Path("/knowledge"))

        assert len(result) == 2

    def test_filters_by_pattern(self, fs: FakeFilesystem) -> None:
        """Should filter by pattern name."""
        fs.create_dir("/knowledge/comparisons")
        fs.create_file("/knowledge/comparisons/api-patterns.csv", contents="")
        fs.create_file("/knowledge/comparisons/other-patterns.csv", contents="")

        result = get_comparison_csv_paths(Path("/knowledge"), "api-patterns")

        assert len(result) == 1
        assert result[0].name == "api-patterns.csv"

    def test_returns_empty_for_missing_pattern(self, fs: FakeFilesystem) -> None:
        """Should return empty list when pattern not found."""
        fs.create_dir("/knowledge/comparisons")
        fs.create_file("/knowledge/comparisons/api-patterns.csv", contents="")

        result = get_comparison_csv_paths(Path("/knowledge"), "nonexistent")

        assert len(result) == 0

    def test_returns_empty_for_missing_directory(self, fs: FakeFilesystem) -> None:
        """Should return empty list when comparisons directory doesn't exist."""
        fs.create_dir("/knowledge")

        result = get_comparison_csv_paths(Path("/knowledge"))

        assert len(result) == 0


class TestBuildQuery:
    """Tests for build_query function."""

    def test_basic_query(self, fs: FakeFilesystem) -> None:
        """Should build basic query without filters."""
        fs.create_file("/knowledge/comparisons/test.csv", contents="")

        query, params = build_query([Path("/knowledge/comparisons/test.csv")])

        assert "SELECT" in query
        assert "FROM" in query
        assert len(params) >= 1

    def test_query_with_element_id_filter(self, fs: FakeFilesystem) -> None:
        """Should include element_id filter in query."""
        fs.create_file("/knowledge/comparisons/test.csv", contents="")

        query, params = build_query([Path("/knowledge/comparisons/test.csv")], element_id="item-1")

        assert "id = ?" in query
        assert "item-1" in params

    def test_query_with_origin_type_filter(self, fs: FakeFilesystem) -> None:
        """Should include origin_type filter in query."""
        fs.create_file("/knowledge/comparisons/test.csv", contents="")

        query, params = build_query(
            [Path("/knowledge/comparisons/test.csv")], origin_type="original"
        )

        assert "origin_type = ?" in query
        assert "original" in params

    def test_query_with_exclude_resolved(self, fs: FakeFilesystem) -> None:
        """Should add resolution join when exclude_resolved is True."""
        fs.create_file("/knowledge/comparisons/test.csv", contents="")
        fs.create_file("/knowledge/resolutions/resolved.csv", contents="")

        query, _ = build_query(
            [Path("/knowledge/comparisons/test.csv")],
            exclude_resolved=True,
            resolutions_path=Path("/knowledge/resolutions/resolved.csv"),
        )

        assert "LEFT JOIN" in query
        assert "r.id IS NULL" in query

    def test_query_with_multiple_csv_files(self, fs: FakeFilesystem) -> None:
        """Should union multiple CSV files."""
        fs.create_file("/knowledge/comparisons/test1.csv", contents="")
        fs.create_file("/knowledge/comparisons/test2.csv", contents="")

        query, _ = build_query(
            [
                Path("/knowledge/comparisons/test1.csv"),
                Path("/knowledge/comparisons/test2.csv"),
            ]
        )

        assert "UNION ALL" in query


class TestFormatResults:
    """Tests for format_results function."""

    def test_formats_empty_results(self) -> None:
        """Should return 'No results' message for empty results."""
        result = format_results([], ["col1", "col2"])
        assert "No results found" in result

    def test_formats_results_as_table(self) -> None:
        """Should format results as table."""
        rows = [("value1", "value2"), ("value3", "value4")]
        columns = ["col1", "col2"]

        result = format_results(rows, columns)  # type: ignore[arg-type]

        assert "col1" in result
        assert "col2" in result
        assert "value1" in result
        assert "2 row(s) returned" in result

    def test_truncates_long_values(self) -> None:
        """Should truncate values longer than 50 characters."""
        long_value = "x" * 100
        rows = [(long_value, "short")]
        columns = ["col1", "col2"]

        result = format_results(rows, columns)  # type: ignore[arg-type]

        # Should be truncated
        assert len(result.split("\n")[2].split("|")[1].strip()) <= 50

    def test_handles_none_values(self) -> None:
        """Should handle None values gracefully."""
        rows = [(None, "value")]
        columns = ["col1", "col2"]

        result = format_results(rows, columns)  # type: ignore[arg-type]

        assert "value" in result


class TestQueryComparisonsFunc:
    """Tests for query_comparisons function."""

    def test_raises_for_no_csv_files(self, fs: FakeFilesystem) -> None:
        """Should raise FileNotFoundError when no CSV files exist."""
        fs.create_dir("/knowledge")

        with pytest.raises(FileNotFoundError):
            query_comparisons_func(Path("/knowledge"))

    def test_queries_csv_files(self, real_knowledge_path: Path) -> None:
        """Should query CSV files and return results.

        DuckDB requires real filesystem files, so we use tmp_path fixture.
        """
        csv_content = """source_file,id,origin_type,original_text,split_file,split_text
source.yml,item-1,original,text1,split.yml,text2
"""
        csv_path = real_knowledge_path / "comparisons" / "test.csv"
        csv_path.write_text(csv_content)

        rows, columns = query_comparisons_func(real_knowledge_path)

        assert len(rows) > 0
        assert "id" in columns


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_values(self) -> None:
        """Should have default values."""
        args = parse_args([])

        assert args.element_id is None
        assert args.origin_type is None
        assert args.exclude_resolved is False
        assert args.knowledge_path == Path(".knowledge")

    def test_parses_element_id(self) -> None:
        """Should parse --id argument."""
        args = parse_args(["--id", "item-1"])
        assert args.element_id == "item-1"

    def test_parses_origin_type(self) -> None:
        """Should parse --origin-type argument."""
        args = parse_args(["--origin-type", "original"])
        assert args.origin_type == "original"

    def test_parses_exclude_resolved(self) -> None:
        """Should parse --exclude-resolved flag."""
        args = parse_args(["--exclude-resolved"])
        assert args.exclude_resolved is True

    def test_validates_origin_type_choices(self) -> None:
        """Should validate origin_type choices."""
        with pytest.raises(SystemExit):
            parse_args(["--origin-type", "invalid"])


class TestMain:
    """Tests for main function."""

    def test_returns_one_for_missing_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when knowledge directory doesn't exist."""
        nonexistent = tmp_path / "nonexistent"
        with patch("sys.argv", ["script", "--knowledge-path", str(nonexistent)]):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_one_for_no_csv_files(
        self, real_knowledge_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when no CSV files found."""
        with patch("sys.argv", ["script", "--knowledge-path", str(real_knowledge_path)]):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "No comparison CSV files" in captured.err

    def test_returns_zero_on_success(
        self, real_knowledge_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 and print results on success.

        DuckDB requires real filesystem files.
        """
        csv_content = """source_file,id,origin_type,original_text,split_file,split_text
source.yml,item-1,original,text1,split.yml,text2
"""
        csv_path = real_knowledge_path / "comparisons" / "test.csv"
        csv_path.write_text(csv_content)

        with patch("sys.argv", ["script", "--knowledge-path", str(real_knowledge_path)]):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "row(s) returned" in captured.out
