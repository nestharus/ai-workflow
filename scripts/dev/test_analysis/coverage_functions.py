"""Coverage functions tool - list functions below threshold.

Lists all functions that are below the coverage threshold from coverage_llm.json,
filtering out excluded paths and providing sorting/filtering options.

Usage:
    uv run coverage-functions
    uv run coverage-functions --filter app/services
    uv run coverage-functions --limit 20
    uv run coverage-functions --sort line_coverage
    uv run coverage-functions --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.dev.test_analysis.common import (
    format_percentage,
    is_excluded_path,
    load_coverage_llm,
)


def get_functions_below_threshold(
    data: dict[str, Any],
    path_filter: str | None = None,
    limit: int | None = None,
    sort_by: str = "line_coverage",
) -> list[dict[str, Any]]:
    """Get list of functions below coverage threshold.

    Args:
        data: The coverage_llm.json data.
        path_filter: Optional path prefix to filter by.
        limit: Optional limit on number of results.
        sort_by: Field to sort by (line_coverage, branch_coverage, file, function).

    Returns:
        List of function entries sorted by the specified field.
    """
    all_functions = data.get("function_coverage", {}).get("functions_below_threshold", [])

    # Filter excluded paths
    functions = []
    for func in all_functions:
        file_path = func.get("file", "")

        if is_excluded_path(file_path):
            continue

        func_name = func.get("function", "")
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

    # Sort
    reverse = sort_by not in ("file", "function")
    if sort_by in ("line_coverage", "branch_coverage"):
        # For coverage, lower is worse, so don't reverse (show worst first)
        reverse = False
    functions.sort(key=lambda x: x.get(sort_by, 0), reverse=reverse)

    # Apply limit
    if limit:
        functions = functions[:limit]

    return functions


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
        "--path",
        type=Path,
        default=None,
        help="Path to coverage_llm.json",
    )
    args = parser.parse_args()

    try:
        data = load_coverage_llm(args.path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    functions = get_functions_below_threshold(
        data,
        path_filter=args.filter,
        limit=args.limit,
        sort_by=args.sort,
    )

    if args.json:
        print(json.dumps(functions, indent=2))
    else:
        threshold = data.get("config", {}).get("min_line_coverage", 80.0)
        print_functions(functions, threshold)

    return 0


if __name__ == "__main__":
    sys.exit(main())
