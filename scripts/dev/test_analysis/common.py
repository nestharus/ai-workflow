"""Common utilities for test analysis tools.

This module contains shared helper functions used by all test analysis tools.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.dev.test_runner.test_coverage import (
    is_excluded_path as _is_excluded_path,
)

# Default coverage_llm.json path
DEFAULT_COVERAGE_LLM_PATH = Path("coverage_llm.json")


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


def load_coverage_llm(path: Path | None = None) -> dict[str, Any]:
    """Load coverage_llm.json data.

    Args:
        path: Optional path to coverage_llm.json. Defaults to repo root.

    Returns:
        The parsed JSON data.

    Raises:
        FileNotFoundError: If coverage_llm.json doesn't exist.
        json.JSONDecodeError: If the file contains invalid JSON.
    """
    coverage_path = path or DEFAULT_COVERAGE_LLM_PATH
    if not coverage_path.exists():
        msg = (
            f"coverage_llm.json not found at {coverage_path}. "
            "Run 'uv run llm-coverage-report' to generate it."
        )
        raise FileNotFoundError(msg)
    with coverage_path.open() as f:
        return json.load(f)


def format_percentage(value: float) -> str:
    """Format a percentage value for display.

    Args:
        value: The percentage value (0-100).

    Returns:
        Formatted string like "85.5%".
    """
    return f"{value:.1f}%"
