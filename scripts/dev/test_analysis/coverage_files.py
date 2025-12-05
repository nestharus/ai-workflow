"""Coverage files tool - list files with coverage problems.

Lists all files that have coverage issues from the SQLite database,
filtering out excluded paths and providing filtering options.

Usage:
    uv run coverage-files
    uv run coverage-files --filter app/services
    uv run coverage-files --limit 20
    uv run coverage-files --json
    uv run coverage-files --db .coverage/coverage.db
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from scripts.dev.test_analysis.common import (
    DEFAULT_COVERAGE_DB_PATH,
    get_functions_below_threshold,
    get_missing_lines,
    is_excluded_path,
)


def aggregate_files(
    functions: list[dict[str, Any]],
    missing_lines: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Aggregate coverage issues by file.

    Args:
        functions: List of function coverage records.
        missing_lines: List of missing line records.

    Returns:
        Dict mapping file paths to their coverage info.
    """
    files: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "missing_lines": [],
            "missing_branches": [],
            "functions_below_threshold": [],
        }
    )

    # Collect missing lines
    for line in missing_lines:
        file_path = line.get("file_path", "")
        if not is_excluded_path(file_path):
            files[file_path]["missing_lines"].append(line.get("line_number"))
            for branch in line.get("missing_branch_exits", []):
                files[file_path]["missing_branches"].append(branch)

    # Collect functions below threshold
    for func in functions:
        file_path = func.get("file_path", "")
        if not is_excluded_path(file_path):
            files[file_path]["functions_below_threshold"].append(
                {
                    "name": func.get("function_name", ""),
                    "line_coverage": func.get("line_coverage_pct", 0),
                    "branch_coverage": func.get("branch_coverage_pct", 0),
                }
            )

    return dict(files)


def format_file_entry(file_path: str, info: dict[str, Any]) -> dict[str, Any]:
    """Format a file entry for output.

    Args:
        file_path: The file path.
        info: The file's coverage info.

    Returns:
        Formatted dict for output.
    """
    return {
        "file": file_path,
        "missing_lines_count": len(info["missing_lines"]),
        "missing_branches_count": len(info["missing_branches"]),
        "functions_below_threshold": len(info["functions_below_threshold"]),
        "total_issues": (
            len(info["missing_lines"])
            + len(info["missing_branches"])
            + len(info["functions_below_threshold"])
        ),
    }


def get_files_with_issues(
    db_path: Path,
    path_filter: str | None = None,
    limit: int | None = None,
    sort_by: str = "total_issues",
) -> list[dict[str, Any]]:
    """Get list of files with coverage issues.

    Args:
        db_path: Path to the coverage database.
        path_filter: Optional path prefix to filter by.
        limit: Optional limit on number of results.
        sort_by: Field to sort by (total_issues, missing_lines_count, file).

    Returns:
        List of file entries sorted by the specified field.
    """
    # Get data from database
    functions = get_functions_below_threshold(db_path)
    missing_lines = get_missing_lines(db_path)

    # Aggregate by file
    files = aggregate_files(functions, missing_lines)

    # Format entries
    entries = [format_file_entry(f, info) for f, info in files.items()]

    # Apply path filter
    if path_filter:
        entries = [e for e in entries if e["file"].startswith(path_filter)]

    # Sort
    reverse = sort_by != "file"
    entries.sort(key=lambda x: x.get(sort_by, 0), reverse=reverse)

    # Apply limit
    if limit:
        entries = entries[:limit]

    return entries


def print_files(entries: list[dict[str, Any]]) -> None:
    """Print files in human-readable format.

    Args:
        entries: List of file entries.
    """
    if not entries:
        print("No files with coverage issues found (after applying exclusions).")
        return

    print(f"{'FILE':<60} {'LINES':>6} {'BRANCH':>6} {'FUNCS':>5} {'TOTAL':>5}")
    print("-" * 88)

    for entry in entries:
        print(
            f"{entry['file']:<60} "
            f"{entry['missing_lines_count']:>6} "
            f"{entry['missing_branches_count']:>6} "
            f"{entry['functions_below_threshold']:>5} "
            f"{entry['total_issues']:>5}"
        )

    print("-" * 88)
    print(f"Total files: {len(entries)}")


def main() -> int:
    """Run the coverage files tool.

    Returns:
        Exit code (0 for success).
    """
    parser = argparse.ArgumentParser(description="List files with coverage problems")
    parser.add_argument(
        "--filter",
        type=str,
        default=None,
        help="Filter files by path prefix (e.g., 'app/services')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of results",
    )
    parser.add_argument(
        "--sort",
        choices=["total_issues", "missing_lines_count", "file"],
        default="total_issues",
        help="Sort by field (default: total_issues)",
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
        entries = get_files_with_issues(
            db_path,
            path_filter=args.filter,
            limit=args.limit,
            sort_by=args.sort,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(entries, indent=2))
    else:
        print_files(entries)

    return 0


if __name__ == "__main__":
    sys.exit(main())
