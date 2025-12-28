from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.knowledge.query_comparisons import (
    build_query,
    format_results,
    get_comparison_csv_paths,
    main,
    parse_args,
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

    def test_handles_absolute_knowledge_path(
        self, real_knowledge_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle absolute knowledge path correctly.

        This covers line 284-285 (then branch) where path.is_absolute() is True.
        """
        csv_content = """source_file,id,origin_type,original_text,split_file,split_text
source.yml,item-1,original,text1,split.yml,text2
"""
        csv_path = real_knowledge_path / "comparisons" / "test.csv"
        csv_path.write_text(csv_content)

        # Use an absolute path
        absolute_path = real_knowledge_path.resolve()
        assert absolute_path.is_absolute()

        with patch("sys.argv", ["script", "--knowledge-path", str(absolute_path)]):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "row(s) returned" in captured.out

    def test_returns_one_on_duckdb_error(
        self, real_knowledge_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when DuckDB query fails.

        This covers lines 306-308 where duckdb.Error is caught.
        """
        import duckdb

        # Create a valid CSV file so query_comparisons finds it
        csv_path = real_knowledge_path / "comparisons" / "test.csv"
        csv_path.write_text("source_file,id,origin_type,original_text,split_file,split_text\n")

        # Mock duckdb.execute to raise a DuckDB error
        with (
            patch("sys.argv", ["script", "--knowledge-path", str(real_knowledge_path)]),
            patch(
                "scripts.knowledge.query_comparisons.duckdb.execute",
                side_effect=duckdb.Error("Simulated DuckDB error"),
            ),
        ):
            result = main()

        # Should fail due to query error
        assert result == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err
