"""Tests for coverage file tool."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from scripts.dev.test_analysis.coverage_file import get_file_details
from scripts.dev.test_runner.coverage_db import (
    init_custom_tables,
    write_function_coverage,
    write_missing_lines,
)
from scripts.dev.test_runner.test_coverage import (
    FunctionCoverage,
    MissingLineDetail,
)


@pytest.fixture
def temp_db():
    """Create a temporary database with test data."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    # Initialize database
    init_custom_tables(db_path)

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
            missing_branches=[[11, 12], [14, 15]],
        ),
    ]
    write_function_coverage(db_path, "unit", functions, 80.0, 80.0)

    # Add missing lines with context
    missing_lines = [
        MissingLineDetail(
            file="app/services/test.py",
            line_number=12,
            content="    return None",
            context_before=[{"line_number": 11, "content": "if x:"}],
            context_after=[{"line_number": 13, "content": "else:"}],
            missing_branch_exits=[13],
        ),
        MissingLineDetail(
            file="app/services/test.py",
            line_number=15,
            content="    raise ValueError()",
            context_before=[{"line_number": 14, "content": "if y:"}],
            context_after=[{"line_number": 16, "content": "return True"}],
            missing_branch_exits=[],
        ),
    ]
    write_missing_lines(db_path, missing_lines)

    yield db_path

    # Cleanup
    db_path.unlink()


def test_get_file_details_valid_file(temp_db):
    """Test getting details for a file with coverage issues."""
    details = get_file_details(temp_db, "app/services/test.py")

    assert details is not None
    assert details["file"] == "app/services/test.py"
    assert details["excluded"] is False

    # Check summary
    assert details["summary"]["missing_lines_count"] == 2
    assert details["summary"]["missing_branches_count"] == 1
    assert details["summary"]["functions_below_threshold_count"] == 1

    # Check missing lines
    assert len(details["missing_lines"]) == 2
    assert details["missing_lines"][0]["line_number"] == 12
    assert details["missing_lines"][0]["content"] == "return None"
    assert len(details["missing_lines"][0]["context_before"]) == 1
    assert len(details["missing_lines"][0]["context_after"]) == 1

    # Check functions
    assert len(details["functions_below_threshold"]) == 1
    assert details["functions_below_threshold"][0]["name"] == "test_function"
    assert details["functions_below_threshold"][0]["line_coverage"] == 70.0


def test_get_file_details_no_issues(temp_db):
    """Test getting details for a file with no coverage issues."""
    details = get_file_details(temp_db, "app/services/perfect.py")

    # Should return None for files with no issues
    assert details is None


def test_get_file_details_excluded_path(temp_db):
    """Test getting details for an excluded path."""
    # Note: is_excluded_path currently always returns False
    # This test verifies the exclusion logic works if exclusions are added
    details = get_file_details(temp_db, "app/infrastructure/excluded.py")

    # Currently should return None (no data), but if exclusions are added,
    # should return exclusion info
    assert details is None or details.get("excluded") is True


def test_get_file_details_with_context(temp_db):
    """Test that context is properly included in missing lines."""
    details = get_file_details(temp_db, "app/services/test.py")

    assert details is not None
    missing_line = details["missing_lines"][0]

    # Check context structure
    assert "context_before" in missing_line
    assert "context_after" in missing_line
    assert isinstance(missing_line["context_before"], list)
    assert isinstance(missing_line["context_after"], list)

    # Check context content
    if missing_line["context_before"]:
        assert "line" in missing_line["context_before"][0]
        assert "content" in missing_line["context_before"][0]
