"""Common utilities for test analysis tools.

This module contains shared helper functions used by all test analysis tools.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from scripts.dev.test_runner.coverage_db import (
    get_functions_below_threshold as _get_functions_below_threshold,
)
from scripts.dev.test_runner.coverage_db import (
    get_missing_lines as _get_missing_lines,
)
from scripts.dev.test_runner.coverage_db import (
    get_tier_summary as _get_tier_summary,
)
from scripts.dev.test_runner.coverage_db import (
    get_usecase_coverage as _get_usecase_coverage,
)
from scripts.dev.test_runner.test_coverage import (
    is_excluded_path as _is_excluded_path,
)

# Default coverage database path
DEFAULT_COVERAGE_DB_PATH = Path(".coverage/coverage.db")


def is_excluded_path(file_path: str) -> bool:
    """Check if a file path is excluded from coverage validation.

    Note: Currently no path exclusions - unit tests cover all of app/.
    This function always returns False but is kept for API compatibility.

    Args:
        file_path: The file path to check.

    Returns:
        Always False (no path exclusions).
    """
    return _is_excluded_path(file_path)


def get_db_connection(path: Path | None = None) -> sqlite3.Connection:
    """Get a connection to the coverage database.

    Args:
        path: Optional path to coverage.db. Defaults to .coverage/coverage.db.

    Returns:
        SQLite connection with row factory enabled.

    Raises:
        FileNotFoundError: If coverage.db doesn't exist.
    """
    db_path = path or DEFAULT_COVERAGE_DB_PATH
    if not db_path.exists():
        msg = (
            f"Coverage database not found at {db_path}. Run 'uv run test-coverage' to generate it."
        )
        raise FileNotFoundError(msg)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def get_functions_below_threshold(
    db_path: Path | None = None,
    tier: str | None = None,
    file_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Query functions that are below coverage thresholds.

    Args:
        db_path: Optional path to coverage.db.
        tier: Optional tier name to filter by.
        file_filter: Optional file path pattern to filter by.

    Returns:
        List of dictionaries with function coverage details.
    """
    path = db_path or DEFAULT_COVERAGE_DB_PATH
    if not path.exists():
        return []
    return _get_functions_below_threshold(path, tier=tier, file_filter=file_filter)


def get_missing_lines(
    db_path: Path | None = None,
    file_path: str | None = None,
) -> list[dict[str, Any]]:
    """Query missing lines with source context.

    Args:
        db_path: Optional path to coverage.db.
        file_path: Optional file path to filter by.

    Returns:
        List of dictionaries with missing line details.
    """
    path = db_path or DEFAULT_COVERAGE_DB_PATH
    if not path.exists():
        return []
    return _get_missing_lines(path, file_path=file_path)


def get_tier_summary(
    db_path: Path | None = None,
    tier: str | None = None,
) -> dict[str, Any]:
    """Query tier summary statistics.

    Args:
        db_path: Optional path to coverage.db.
        tier: Optional tier name to filter by.

    Returns:
        Dictionary with tier summary data.
    """
    path = db_path or DEFAULT_COVERAGE_DB_PATH
    if not path.exists():
        return {}
    return _get_tier_summary(path, tier=tier)


def get_usecase_coverage(db_path: Path | None = None) -> dict[str, Any]:
    """Query use case coverage statistics.

    Args:
        db_path: Optional path to coverage.db.

    Returns:
        Dictionary with use case coverage details.
    """
    path = db_path or DEFAULT_COVERAGE_DB_PATH
    if not path.exists():
        return {
            "total": 0,
            "covered": 0,
            "coverage_pct": 0.0,
            "by_tier": {},
            "uncovered": [],
        }
    return _get_usecase_coverage(path)


def format_percentage(value: float) -> str:
    """Format a percentage value for display.

    Args:
        value: The percentage value (0-100).

    Returns:
        Formatted string like "85.5%".
    """
    return f"{value:.1f}%"
