"""Tests for coverage summary tool."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from scripts.dev.test_analysis.coverage_summary import (
    aggregate_files_by_coverage,
    generate_summary,
    get_filtered_functions,
    get_filtered_missing_lines,
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
