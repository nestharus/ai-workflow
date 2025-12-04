"""Tests for common analysis utilities."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from scripts.dev.test_analysis.common import (
    format_percentage,
    get_db_connection,
    get_functions_below_threshold,
    get_missing_lines,
    get_tier_summary,
    get_usecase_coverage,
)


def test_format_percentage():
    """Test percentage formatting."""
    assert format_percentage(85.5) == "85.5%"
    assert format_percentage(100.0) == "100.0%"
    assert format_percentage(0.0) == "0.0%"
    assert format_percentage(33.333) == "33.3%"


def test_get_db_connection_missing_file():
    """Test that get_db_connection raises error for missing file."""
    with pytest.raises(FileNotFoundError, match="Coverage database not found"):
        get_db_connection(Path("/nonexistent/path/coverage.db"))


def test_get_db_connection_valid_file():
    """Test that get_db_connection works with valid database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        # Create a minimal database
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.close()

        # Test connection
        conn = get_db_connection(db_path)
        assert conn is not None
        assert conn.row_factory == sqlite3.Row
        conn.close()
    finally:
        db_path.unlink()


def test_get_functions_below_threshold_missing_db():
    """Test that get_functions_below_threshold returns empty list for missing db."""
    result = get_functions_below_threshold(Path("/nonexistent/coverage.db"))
    assert result == []


def test_get_missing_lines_missing_db():
    """Test that get_missing_lines returns empty list for missing db."""
    result = get_missing_lines(Path("/nonexistent/coverage.db"))
    assert result == []


def test_get_tier_summary_missing_db():
    """Test that get_tier_summary returns empty dict for missing db."""
    result = get_tier_summary(Path("/nonexistent/coverage.db"))
    assert result == {}


def test_get_usecase_coverage_missing_db():
    """Test that get_usecase_coverage returns default dict for missing db."""
    result = get_usecase_coverage(Path("/nonexistent/coverage.db"))
    assert result == {
        "total": 0,
        "covered": 0,
        "coverage_pct": 0.0,
        "by_tier": {},
        "uncovered": [],
    }
