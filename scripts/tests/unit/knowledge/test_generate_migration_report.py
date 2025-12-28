from pathlib import Path
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


class TestMain:
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

    def test_handles_absolute_knowledge_path(
        self, real_knowledge_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle absolute knowledge path correctly.

        DuckDB requires real filesystem files.
        """
        csv_content = """source_file,id,origin_type,original_text,split_file,split_text
source.yml,item-1,original,different text,split.yml,modified text
"""
        csv_path = real_knowledge_path / "comparisons" / "test.csv"
        csv_path.write_text(csv_content)

        # Use absolute path
        absolute_path = real_knowledge_path.resolve()
        with patch("sys.argv", ["script", "--knowledge-path", str(absolute_path)]):
            result = main()

        assert result == 0

    def test_handles_duckdb_error(
        self, real_knowledge_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 and print error when duckdb.Error occurs."""
        # Create an invalid CSV that will cause DuckDB to fail
        csv_content = """malformed csv without proper headers
this is not valid"""
        csv_path = real_knowledge_path / "comparisons" / "test.csv"
        csv_path.write_text(csv_content)

        import duckdb

        # Mock query_non_identical_items to raise a DuckDB error
        with (
            patch("sys.argv", ["script", "--knowledge-path", str(real_knowledge_path)]),
            patch(
                "scripts.knowledge.generate_migration_report.query_non_identical_items",
                side_effect=duckdb.Error("Invalid CSV format"),
            ),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error executing query" in captured.err
