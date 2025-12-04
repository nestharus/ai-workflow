"""Tests for coverage functions tool."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from scripts.dev.test_analysis.coverage_functions import (
    filter_and_sort_functions,
    get_threshold,
)
from scripts.dev.test_runner.coverage_db import (
    init_custom_tables,
    write_function_coverage,
)
from scripts.dev.test_runner.test_coverage import FunctionCoverage


@pytest.fixture
def temp_db():
    """Create a temporary database with test data."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    # Initialize database
    init_custom_tables(db_path)

    # Add function coverage with varying coverage levels
    functions = [
        FunctionCoverage(
            file_path="app/services/service_a.py",
            name="function_low",
            start_line=10,
            end_line=20,
            total_lines=10,
            covered_lines=5,
            line_coverage_pct=50.0,
            total_branches=4,
            covered_branches=1,
            branch_coverage_pct=25.0,
            missing_lines=[12, 15, 17, 18, 19],
            missing_branches=[[11, 12]],
        ),
        FunctionCoverage(
            file_path="app/services/service_a.py",
            name="function_medium",
            start_line=30,
            end_line=40,
            total_lines=10,
            covered_lines=7,
            line_coverage_pct=70.0,
            total_branches=2,
            covered_branches=1,
            branch_coverage_pct=50.0,
            missing_lines=[32, 35, 38],
            missing_branches=[],
        ),
        FunctionCoverage(
            file_path="app/services/service_b.py",
            name="function_high",
            start_line=50,
            end_line=60,
            total_lines=10,
            covered_lines=8,
            line_coverage_pct=75.0,
            total_branches=2,
            covered_branches=1,
            branch_coverage_pct=50.0,
            missing_lines=[52, 55],
            missing_branches=[],
        ),
    ]
    write_function_coverage(db_path, "unit", functions, 80.0, 80.0)

    yield db_path

    # Cleanup
    db_path.unlink()


def test_filter_and_sort_functions_default(temp_db):
    """Test getting functions with default sorting (by line coverage, worst first)."""
    functions = filter_and_sort_functions(temp_db)

    # Should return all 3 functions
    assert len(functions) == 3

    # Should be sorted by line coverage (lowest first)
    assert functions[0]["line_coverage"] == 50.0
    assert functions[1]["line_coverage"] == 70.0
    assert functions[2]["line_coverage"] == 75.0


def test_filter_and_sort_functions_by_branch(temp_db):
    """Test sorting by branch coverage."""
    functions = filter_and_sort_functions(temp_db, sort_by="branch_coverage")

    # Should be sorted by branch coverage (lowest first)
    assert functions[0]["branch_coverage"] == 25.0
    assert functions[1]["branch_coverage"] >= functions[0]["branch_coverage"]


def test_filter_and_sort_functions_by_file(temp_db):
    """Test sorting by file path."""
    functions = filter_and_sort_functions(temp_db, sort_by="file")

    # Should be sorted alphabetically by file path
    assert functions[0]["file"] == "app/services/service_a.py"
    assert functions[2]["file"] == "app/services/service_b.py"


def test_filter_and_sort_functions_with_path_filter(temp_db):
    """Test filtering by path prefix."""
    functions = filter_and_sort_functions(temp_db, path_filter="app/services/service_a")

    # Should return only functions from service_a
    assert len(functions) == 2
    assert all(f["file"] == "app/services/service_a.py" for f in functions)


def test_filter_and_sort_functions_with_limit(temp_db):
    """Test limiting number of results."""
    functions = filter_and_sort_functions(temp_db, limit=2)

    # Should return only 2 functions
    assert len(functions) == 2

    # Should be the worst 2 (lowest coverage)
    assert functions[0]["line_coverage"] == 50.0
    assert functions[1]["line_coverage"] == 70.0


def test_filter_and_sort_functions_by_missing_lines(temp_db):
    """Test sorting by missing lines count."""
    functions = filter_and_sort_functions(temp_db, sort_by="missing_lines_count")

    # Should be sorted by missing lines count (most first)
    assert functions[0]["missing_lines_count"] == 5
    assert functions[1]["missing_lines_count"] == 3
    assert functions[2]["missing_lines_count"] == 2


def test_get_threshold(temp_db):
    """Test getting coverage threshold."""
    threshold = get_threshold(temp_db)

    # Should return default threshold
    assert threshold == 80.0


def test_get_threshold_empty_db():
    """Test getting threshold from empty database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        init_custom_tables(db_path)
        threshold = get_threshold(db_path)

        # Should return default
        assert threshold == 80.0
    finally:
        db_path.unlink()


def test_filter_and_sort_functions_combined_filters(temp_db):
    """Test combining path filter, limit, and sorting."""
    functions = filter_and_sort_functions(
        temp_db,
        path_filter="app/services/service_a",
        limit=1,
        sort_by="line_coverage",
    )

    # Should return only 1 function from service_a with lowest coverage
    assert len(functions) == 1
    assert functions[0]["file"] == "app/services/service_a.py"
    assert functions[0]["line_coverage"] == 50.0
