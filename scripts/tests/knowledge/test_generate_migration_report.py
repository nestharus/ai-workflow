"""Tests for scripts.knowledge.generate_migration_report module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts.knowledge.generate_migration_report import (
    ReviewItem,
    compute_text_similarity,
    generate_yaml_report,
    get_comparison_csv_paths,
    main,
    parse_args,
    query_non_identical_items,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestComputeTextSimilarity:
    """Tests for compute_text_similarity function."""

    def test_identical_texts_return_one(self) -> None:
        """Should return 1.0 for identical texts."""
        result = compute_text_similarity("same text", "same text")
        assert result == 1.0

    def test_completely_different_texts_return_low_score(self) -> None:
        """Should return low score for completely different texts."""
        result = compute_text_similarity("abc", "xyz")
        assert result < 0.5

    def test_similar_texts_return_high_score(self) -> None:
        """Should return high score for similar texts."""
        result = compute_text_similarity("hello world", "hello world!")
        assert result > 0.8

    def test_strips_whitespace(self) -> None:
        """Should strip whitespace before comparing."""
        result = compute_text_similarity("  text  ", "text")
        assert result == 1.0

    def test_empty_texts(self) -> None:
        """Should handle empty texts."""
        result = compute_text_similarity("", "")
        assert result == 1.0


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

    def test_returns_empty_for_missing_directory(self, fs: FakeFilesystem) -> None:
        """Should return empty list when comparisons directory doesn't exist."""
        fs.create_dir("/knowledge")

        result = get_comparison_csv_paths(Path("/knowledge"))

        assert len(result) == 0


class TestQueryNonIdenticalItems:
    """Tests for query_non_identical_items function."""

    def test_raises_for_no_csv_files(self, fs: FakeFilesystem) -> None:
        """Should raise FileNotFoundError when no CSV files exist."""
        fs.create_dir("/knowledge")

        with pytest.raises(FileNotFoundError):
            query_non_identical_items(Path("/knowledge"))

    def test_filters_identical_items(self, real_knowledge_path: Path) -> None:
        """Should filter out items with identical text.

        DuckDB requires real filesystem files.
        """
        csv_content = """source_file,id,origin_type,original_text,split_file,split_text
source.yml,item-1,original,identical text,split.yml,identical text
source.yml,item-2,original,different text,split.yml,modified text
"""
        csv_path = real_knowledge_path / "comparisons" / "test.csv"
        csv_path.write_text(csv_content)

        result = query_non_identical_items(real_knowledge_path)

        # Only item-2 should be included (different text)
        if "test" in result:
            items = result["test"]
            ids = [item["element_id"] for item in items]
            assert "item-1" not in ids

    def test_excludes_split_only_and_orphan(self, real_knowledge_path: Path) -> None:
        """Should exclude split_only and orphan origin types.

        DuckDB requires real filesystem files.
        """
        csv_content = """source_file,id,origin_type,original_text,split_file,split_text
source.yml,item-1,split_only,text1,,
source.yml,item-2,orphan,text2,,
source.yml,item-3,original,text3,split.yml,modified
"""
        csv_path = real_knowledge_path / "comparisons" / "test.csv"
        csv_path.write_text(csv_content)

        result = query_non_identical_items(real_knowledge_path)

        if "test" in result:
            items = result["test"]
            ids = [item["element_id"] for item in items]
            assert "item-1" not in ids
            assert "item-2" not in ids


class TestGenerateYamlReport:
    """Tests for generate_yaml_report function."""

    def test_creates_yaml_file(self, fs: FakeFilesystem) -> None:
        """Should create YAML report file."""
        output_path = Path("/knowledge/reports/test-review.yml")

        items = [
            ReviewItem(
                element_id="item-1",
                source_file="source.yml",
                source_text="Source text",
                split_file="split.yml",
                target_text="Target text",
                text_similarity_score=0.85,
                requires_review=True,
                origin_type="original",
            )
        ]

        generate_yaml_report(items, "test", output_path)

        assert output_path.exists()
        content = output_path.read_text()
        assert "pattern: test" in content
        assert "item-1" in content

    def test_includes_all_fields(self, fs: FakeFilesystem) -> None:
        """Should include all review item fields."""
        output_path = Path("/knowledge/reports/test-review.yml")

        items = [
            ReviewItem(
                element_id="item-1",
                source_file="source.yml",
                source_text="Source text",
                split_file="split.yml",
                target_text="Target text",
                text_similarity_score=0.85,
                requires_review=True,
                origin_type="original",
            )
        ]

        generate_yaml_report(items, "test", output_path)

        content = output_path.read_text()
        assert "element_id" in content
        assert "source_file" in content
        assert "source_text" in content
        assert "split_file" in content
        assert "target_text" in content
        assert "text_similarity_score" in content


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_values(self) -> None:
        """Should have default values."""
        args = parse_args([])

        assert args.pattern is None
        assert args.knowledge_path == Path(".knowledge")

    def test_parses_pattern(self) -> None:
        """Should parse --pattern argument."""
        args = parse_args(["--pattern", "api-patterns"])
        assert args.pattern == "api-patterns"

    def test_parses_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_args(["--knowledge-path", "/custom/path"])
        assert args.knowledge_path == Path("/custom/path")


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

    def test_returns_zero_when_no_items_need_review(
        self, real_knowledge_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 with message when no items need review.

        DuckDB requires real filesystem files.
        """
        # Create CSV with identical items only
        csv_content = """source_file,id,origin_type,original_text,split_file,split_text
source.yml,item-1,original,same text,split.yml,same text
"""
        csv_path = real_knowledge_path / "comparisons" / "test.csv"
        csv_path.write_text(csv_content)

        with patch("sys.argv", ["script", "--knowledge-path", str(real_knowledge_path)]):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "No items requiring review" in captured.out

    def test_returns_zero_and_generates_reports(
        self, real_knowledge_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 and generate reports on success.

        DuckDB requires real filesystem files.
        """
        csv_content = """source_file,id,origin_type,original_text,split_file,split_text
source.yml,item-1,original,different text,split.yml,modified text
"""
        csv_path = real_knowledge_path / "comparisons" / "test.csv"
        csv_path.write_text(csv_content)

        with patch("sys.argv", ["script", "--knowledge-path", str(real_knowledge_path)]):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Generated" in captured.out
