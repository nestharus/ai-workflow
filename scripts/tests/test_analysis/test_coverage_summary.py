"""Tests for coverage summary tool."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.dev.test_analysis.coverage_summary import (
    aggregate_files_by_coverage,
    generate_summary,
    get_filtered_functions,
    get_filtered_missing_lines,
    main,
    print_summary,
)
from scripts.dev.test_runner.coverage_db import (
    init_custom_tables,
    write_function_coverage,
    write_missing_lines,
    write_run_metadata,
    write_tier_summary,
)
from scripts.dev.test_runner.test_coverage import (
    FunctionCoverage,
    MissingLineDetail,
)


@pytest.fixture
def temp_db() -> Iterator[Path]:
    """Create a temporary database with test data."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    # Initialize database
    init_custom_tables(db_path)

    # Add test data
    write_run_metadata(db_path, Path("/test/repo"))

    # Add tier summary
    write_tier_summary(
        db_path,
        "unit",
        {
            "coverage_type": "line_branch",
            "total_functions": 10,
            "passing_functions": 8,
            "failing_functions": 2,
            "overall_line_pct": 85.5,
            "overall_branch_pct": 80.0,
            "total_tests": 20,
            "tests_passed": 18,
            "tests_failed": 2,
            "tier_pass": 0,
        },
    )

    # Add function coverage
    functions = [
        FunctionCoverage(
            file_path="app/services/test.py",
            name="test_function",
            start_line=10,
            end_line=20,
            total_lines=10,
            covered_lines=7,
            line_coverage_pct=70.0,
            total_branches=4,
            covered_branches=2,
            branch_coverage_pct=50.0,
            missing_lines=[12, 15, 18],
            missing_branches=[(11, 12), (14, 15)],
        ),
    ]
    write_function_coverage(db_path, "unit", functions, 80.0, 80.0)

    # Add missing lines
    missing_lines = [
        MissingLineDetail(
            file="app/services/test.py",
            line_number=12,
            content="    return None",
            context_before=[{"line_number": 11, "content": "if x:"}],
            context_after=[{"line_number": 13, "content": "else:"}],
            missing_branch_exits=[13],
        ),
    ]
    write_missing_lines(db_path, missing_lines)

    yield db_path

    # Cleanup
    db_path.unlink()


def test_get_filtered_functions(temp_db: Path) -> None:
    """Test filtering functions by exclusion."""
    included, excluded = get_filtered_functions(temp_db)

    # All functions should be included (no excluded paths)
    assert len(included) == 1
    assert len(excluded) == 0
    assert included[0]["file_path"] == "app/services/test.py"


def test_get_filtered_missing_lines(temp_db: Path) -> None:
    """Test filtering missing lines by exclusion."""
    included, excluded_count = get_filtered_missing_lines(temp_db)

    # All lines should be included
    assert len(included) == 1
    assert excluded_count == 0
    assert included[0]["file_path"] == "app/services/test.py"


def test_aggregate_files_by_coverage(temp_db: Path) -> None:
    """Test aggregating missing lines by file."""
    included_lines, _ = get_filtered_missing_lines(temp_db)
    files = aggregate_files_by_coverage(included_lines)

    assert "app/services/test.py" in files
    assert files["app/services/test.py"]["missing_lines"] == 1
    assert files["app/services/test.py"]["missing_branches"] == 1


def test_generate_summary(temp_db: Path) -> None:
    """Test generating complete summary."""
    summary = generate_summary(temp_db)

    # Check structure
    assert "generated_at" in summary
    assert "raw_totals" in summary
    assert "filtered_totals" in summary
    assert "tier_summaries" in summary
    assert "use_case_coverage" in summary
    assert "top_files_by_missing_lines" in summary

    # Check raw totals
    assert summary["raw_totals"]["percent_covered"] == 85.5
    assert summary["raw_totals"]["total_functions_below_threshold"] == 2

    # Check filtered totals
    assert summary["filtered_totals"]["functions_below_threshold"] == 1
    assert summary["filtered_totals"]["excluded_functions"] == 0

    # Check tier summaries
    assert "unit" in summary["tier_summaries"]
    assert summary["tier_summaries"]["unit"]["overall_line_pct"] == 85.5


def test_generate_summary_with_empty_db() -> None:
    """Test generating summary with empty database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        init_custom_tables(db_path)
        summary = generate_summary(db_path)

        # Should return default values
        assert summary["raw_totals"]["total_functions_below_threshold"] == 0
        assert summary["filtered_totals"]["functions_below_threshold"] == 0
    finally:
        db_path.unlink()


def test_get_filtered_functions_with_excluded_paths(temp_db: Path) -> None:
    """Test filtering functions when is_excluded_path returns True for some."""
    # Mock is_excluded_path to exclude app/services paths
    with patch(
        "scripts.dev.test_analysis.coverage_summary.is_excluded_path",
        side_effect=lambda p: "app/services" in p,
    ):
        included, excluded = get_filtered_functions(temp_db)

    # Function in app/services/test.py should be excluded
    assert len(included) == 0
    assert len(excluded) == 1
    assert excluded[0]["file_path"] == "app/services/test.py"


def test_get_filtered_missing_lines_with_excluded_paths(temp_db: Path) -> None:
    """Test filtering missing lines when is_excluded_path returns True."""
    # Mock is_excluded_path to exclude app/services paths
    with patch(
        "scripts.dev.test_analysis.coverage_summary.is_excluded_path",
        side_effect=lambda p: "app/services" in p,
    ):
        included, excluded_count = get_filtered_missing_lines(temp_db)

    # Line in app/services/test.py should be excluded
    assert len(included) == 0
    assert excluded_count == 1


def test_aggregate_files_by_coverage_multiple_lines_same_file() -> None:
    """Test aggregating when multiple missing lines belong to the same file."""
    # Create multiple missing lines for the same file
    missing_lines = [
        {
            "file_path": "app/test.py",
            "line_number": 10,
            "missing_branch_exits": [11, 12],
        },
        {
            "file_path": "app/test.py",
            "line_number": 20,
            "missing_branch_exits": [21],
        },
        {
            "file_path": "app/other.py",
            "line_number": 5,
            "missing_branch_exits": [],
        },
    ]

    files = aggregate_files_by_coverage(missing_lines)

    # Check aggregation for app/test.py
    assert "app/test.py" in files
    assert files["app/test.py"]["missing_lines"] == 2
    assert files["app/test.py"]["missing_branches"] == 3  # 2 + 1

    # Check app/other.py
    assert "app/other.py" in files
    assert files["app/other.py"]["missing_lines"] == 1
    assert files["app/other.py"]["missing_branches"] == 0


def test_print_summary(temp_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test print_summary outputs human-readable format."""
    summary = generate_summary(temp_db)
    print_summary(summary)

    captured = capsys.readouterr()
    output = captured.out

    # Check header
    assert "COVERAGE SUMMARY" in output
    assert "with exclusions applied" in output

    # Check raw totals section
    assert "RAW TOTALS" in output
    assert "Line coverage:" in output
    assert "85.5%" in output
    assert "Functions below threshold:" in output

    # Check filtered totals section
    assert "FILTERED TOTALS" in output
    assert "Excluded functions:" in output
    assert "Files with issues:" in output

    # Check use case coverage section
    assert "USE CASE COVERAGE:" in output
    assert "Total:" in output
    assert "Covered:" in output
    assert "Uncovered:" in output

    # Check top files section
    assert "TOP 10 FILES BY MISSING LINES:" in output


def test_print_summary_with_top_files(capsys: pytest.CaptureFixture[str]) -> None:
    """Test print_summary displays top files correctly."""
    summary = {
        "generated_at": "2024-01-01T00:00:00",
        "raw_totals": {
            "percent_covered": 75.0,
            "missing_lines": 100,
            "missing_branches": 50,
            "total_functions_below_threshold": 10,
        },
        "filtered_totals": {
            "functions_below_threshold": 8,
            "excluded_functions": 2,
            "missing_lines": 90,
            "excluded_lines": 10,
            "files_with_issues": 5,
        },
        "tier_summaries": {},
        "use_case_coverage": {
            "total": 20,
            "covered": 15,
            "uncovered": 5,
        },
        "top_files_by_missing_lines": [
            {"file": "app/test.py", "missing_lines": 50},
            {"file": "app/other.py", "missing_lines": 30},
        ],
    }

    print_summary(summary)

    captured = capsys.readouterr()
    output = captured.out

    # Check that top files are printed
    assert "50 lines  app/test.py" in output
    assert "30 lines  app/other.py" in output


def test_print_summary_with_empty_top_files(capsys: pytest.CaptureFixture[str]) -> None:
    """Test print_summary handles empty top files list."""
    summary = {
        "generated_at": "2024-01-01T00:00:00",
        "raw_totals": {
            "percent_covered": 100.0,
            "missing_lines": 0,
            "missing_branches": 0,
            "total_functions_below_threshold": 0,
        },
        "filtered_totals": {
            "functions_below_threshold": 0,
            "excluded_functions": 0,
            "missing_lines": 0,
            "excluded_lines": 0,
            "files_with_issues": 0,
        },
        "tier_summaries": {},
        "use_case_coverage": {
            "total": 10,
            "covered": 10,
            "uncovered": 0,
        },
        "top_files_by_missing_lines": [],
    }

    print_summary(summary)

    captured = capsys.readouterr()
    output = captured.out

    # Should still have the header
    assert "TOP 10 FILES BY MISSING LINES:" in output


class TestMain:
    """Tests for the main() function."""

    def test_main_returns_zero_on_success(self, temp_db: Path) -> None:
        """Test main returns 0 on successful execution."""
        with patch("sys.argv", ["coverage-summary", "--db", str(temp_db)]):
            result = main()
        assert result == 0

    def test_main_with_json_output(self, temp_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main outputs JSON when --json flag is provided."""
        with patch("sys.argv", ["coverage-summary", "--db", str(temp_db), "--json"]):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        # JSON output should be parseable
        import json

        data = json.loads(captured.out)
        assert "generated_at" in data
        assert "raw_totals" in data

    def test_main_returns_one_for_missing_database(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main returns 1 when database does not exist."""
        nonexistent_db = tmp_path / "nonexistent.db"
        with patch("sys.argv", ["coverage-summary", "--db", str(nonexistent_db)]):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Coverage database not found" in captured.err

    def test_main_with_default_db_path(self) -> None:
        """Test main uses default db path when --db not provided."""
        with (
            patch("sys.argv", ["coverage-summary"]),
            patch(
                "scripts.dev.test_analysis.coverage_summary.DEFAULT_COVERAGE_DB_PATH",
                Path("/nonexistent/path.db"),
            ),
        ):
            result = main()
        # Should return 1 because default db doesn't exist
        assert result == 1

    def test_main_returns_one_on_exception(
        self, temp_db: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main returns 1 when generate_summary raises an exception."""
        with (
            patch("sys.argv", ["coverage-summary", "--db", str(temp_db)]),
            patch(
                "scripts.dev.test_analysis.coverage_summary.generate_summary",
                side_effect=Exception("Test error"),
            ),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error generating summary" in captured.err
        assert "Test error" in captured.err

    def test_main_prints_human_readable_by_default(
        self, temp_db: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main prints human-readable output by default (not JSON)."""
        with patch("sys.argv", ["coverage-summary", "--db", str(temp_db)]):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        # Human-readable output should have the header
        assert "COVERAGE SUMMARY" in captured.out
        # And should not be valid JSON (no leading brace)
        assert not captured.out.strip().startswith("{")
