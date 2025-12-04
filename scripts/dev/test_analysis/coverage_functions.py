"""Coverage functions tool - list functions below threshold.

Lists all functions that are below the coverage threshold from the SQLite database,
filtering out excluded paths and providing sorting/filtering options.

Usage:
    uv run coverage-functions
    uv run coverage-functions --filter app/services
    uv run coverage-functions --limit 20
    uv run coverage-functions --sort line_coverage
    uv run coverage-functions --json
    uv run coverage-functions --db .coverage/coverage.db
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.dev.test_analysis.common import (
    DEFAULT_COVERAGE_DB_PATH,
    format_percentage,
    get_functions_below_threshold,
    is_excluded_path,
)


def filter_and_sort_functions(
    db_path: Path,
    path_filter: str | None = None,
    limit: int | None = None,
    sort_by: str = "line_coverage",
) -> list[dict[str, Any]]:
    """Get list of functions below coverage threshold.

    Args:
        db_path: Path to the coverage database.
        path_filter: Optional path prefix to filter by.
        limit: Optional limit on number of results.
        sort_by: Field to sort by (line_coverage, branch_coverage, file_path, function_name).

    Returns:
        List of function entries sorted by the specified field.
    """
    all_functions = get_functions_below_threshold(db_path)

    # Filter excluded paths
    functions = []
    for func in all_functions:
        file_path = func.get("file_path", "")

        if is_excluded_path(file_path):
            continue

        func_name = func.get("function_name", "")
        functions.append(
            {
                "file": file_path,
                "function": func_name,
                "line_coverage": func.get("line_coverage_pct", 0),
                "branch_coverage": func.get("branch_coverage_pct", 0),
                "missing_lines": func.get("missing_lines", []),
                "missing_lines_count": len(func.get("missing_lines", [])),
            }
        )

    # Apply path filter
    if path_filter:
        functions = [f for f in functions if f["file"].startswith(path_filter)]

    # Map sort_by to actual keys
    sort_key_map = {
        "line_coverage": "line_coverage",
        "branch_coverage": "branch_coverage",
        "file": "file",
        "function": "function",
        "missing_lines_count": "missing_lines_count",
    }
    actual_sort_key = sort_key_map.get(sort_by, "line_coverage")

    # Sort
    reverse = actual_sort_key not in ("file", "function")
    if actual_sort_key in ("line_coverage", "branch_coverage"):
        # For coverage, lower is worse, so don't reverse (show worst first)
        reverse = False
    functions.sort(key=lambda x: x.get(actual_sort_key, 0), reverse=reverse)

    # Apply limit
    if limit:
        functions = functions[:limit]

    return functions


def get_threshold(db_path: Path) -> float:
    """Get the coverage threshold from tier config.

    Args:
        db_path: Path to the coverage database.

    Returns:
        The minimum line coverage threshold (defaults to 80.0 if not found).
    """
    # Threshold is stored in function coverage records, not tier summary
    # Default to 80.0 for now
    # TODO: Consider querying cc_tier_config table for actual threshold
    return 80.0


def print_functions(functions: list[dict[str, Any]], threshold: float) -> None:
    """Print functions in human-readable format.

    Args:
        functions: List of function entries.
        threshold: The coverage threshold used.
    """
    if not functions:
        print("No functions below threshold (after applying exclusions).")
        return

    print(f"Functions below {format_percentage(threshold)} line coverage threshold:")
    print()
    print(f"{'FILE':<45} {'FUNCTION':<25} {'LINE':>6} {'BRANCH':>6} {'MISS':>5}")
    print("-" * 93)

    for func in functions:
        file_short = func["file"]
        if len(file_short) > 44:
            file_short = "..." + file_short[-41:]

        func_name = func["function"]
        if len(func_name) > 24:
            func_name = func_name[:21] + "..."

        print(
            f"{file_short:<45} "
            f"{func_name:<25} "
            f"{format_percentage(func['line_coverage']):>6} "
            f"{format_percentage(func['branch_coverage']):>6} "
            f"{func['missing_lines_count']:>5}"
        )

    print("-" * 93)
    print(f"Total functions below threshold: {len(functions)}")


def main() -> int:
    """Run the coverage functions tool.

    Returns:
        Exit code (0 for success).
    """
    parser = argparse.ArgumentParser(description="List functions below coverage threshold")
    parser.add_argument(
        "--filter",
        type=str,
        default=None,
        help="Filter by file path prefix (e.g., 'app/services')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of results",
    )
    parser.add_argument(
        "--sort",
        choices=["line_coverage", "branch_coverage", "file", "function", "missing_lines_count"],
        default="line_coverage",
        help="Sort by field (default: line_coverage, worst first)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help=f"Path to coverage database (default: {DEFAULT_COVERAGE_DB_PATH})",
    )
    args = parser.parse_args()

    db_path = args.db or DEFAULT_COVERAGE_DB_PATH

    if not db_path.exists():
        print(
            f"Error: Coverage database not found at {db_path}. "
            "Run 'uv run test-coverage' to generate it.",
            file=sys.stderr,
        )
        return 1

    try:
        functions = filter_and_sort_functions(
            db_path,
            path_filter=args.filter,
            limit=args.limit,
            sort_by=args.sort,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(functions, indent=2))
    else:
        threshold = get_threshold(db_path)
        print_functions(functions, threshold)

    return 0


if __name__ == "__main__":
    sys.exit(main())
