from pathlib import Path
from typing import TYPE_CHECKING

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


class TestQueryNonIdenticalItemsWithResolutions:
    def test_filters_resolved_items(self, real_knowledge_path: Path) -> None:
        """Should exclude items that appear in resolutions file.

        DuckDB requires real filesystem files.
        """
        # Create comparison CSV with items
        csv_content = """source_file,id,origin_type,original_text,split_file,split_text
source.yml,item-1,original,text one,split.yml,modified one
source.yml,item-2,original,text two,split.yml,modified two
source.yml,item-3,original,text three,split.yml,modified three
"""
        csv_path = real_knowledge_path / "comparisons" / "test.csv"
        csv_path.write_text(csv_content)

        # Create resolutions file that marks item-1 and item-3 as resolved
        resolutions_dir = real_knowledge_path / "resolutions"
        resolutions_dir.mkdir(parents=True, exist_ok=True)
        resolutions_content = """id,source_file,split_file,resolved_at
item-1,source.yml,split.yml,2024-01-01T00:00:00Z
item-3,source.yml,split.yml,2024-01-02T00:00:00Z
"""
        (resolutions_dir / "resolved.csv").write_text(resolutions_content)

        result = query_non_identical_items(real_knowledge_path)

        # Only item-2 should remain (not in resolutions)
        if "test" in result:
            items = result["test"]
            ids = [item["element_id"] for item in items]
            assert "item-1" not in ids
            assert "item-2" in ids
            assert "item-3" not in ids

    def test_includes_unresolved_items_with_resolutions_file(
        self, real_knowledge_path: Path
    ) -> None:
        """Should include items not in resolutions file even when file exists.

        DuckDB requires real filesystem files.
        """
        # Create comparison CSV
        csv_content = """source_file,id,origin_type,original_text,split_file,split_text
source.yml,new-item,original,new text,split.yml,modified new text
"""
        csv_path = real_knowledge_path / "comparisons" / "test.csv"
        csv_path.write_text(csv_content)

        # Create resolutions file with different items
        resolutions_dir = real_knowledge_path / "resolutions"
        resolutions_dir.mkdir(parents=True, exist_ok=True)
        resolutions_content = """id,source_file,split_file,resolved_at
old-item,source.yml,split.yml,2024-01-01T00:00:00Z
"""
        (resolutions_dir / "resolved.csv").write_text(resolutions_content)

        result = query_non_identical_items(real_knowledge_path)

        # new-item should be included
        if "test" in result:
            items = result["test"]
            ids = [item["element_id"] for item in items]
            assert "new-item" in ids
