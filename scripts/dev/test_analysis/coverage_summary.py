"""Coverage summary tool - get totals across tiers with exclusions.

Provides a high-level summary of coverage data from the SQLite database,
filtering out excluded paths (infrastructure, HTTP handling).

Usage:
    uv run coverage-summary
    uv run coverage-summary --json
    uv run coverage-summary --db .coverage/coverage.db
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
    get_db_connection,
    get_functions_below_threshold,
    get_missing_lines,
    get_tier_summary,
    get_usecase_coverage,
    is_excluded_path,
)


def get_filtered_functions(
    db_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Get functions below threshold, split into included and excluded.

    Args:
        db_path: Path to the coverage database.

    Returns:
        Tuple of (included_functions, excluded_functions).
    """
    functions = get_functions_below_threshold(db_path)
    included = []
    excluded = []

    for func in functions:
        file_path = func.get("file_path", "")

        if is_excluded_path(file_path):
            excluded.append(func)
        else:
            included.append(func)

    return included, excluded


def get_filtered_missing_lines(
    db_path: Path,
) -> tuple[list[dict[str, Any]], int]:
    """Get missing lines, filtering out excluded paths.

    Args:
        db_path: Path to the coverage database.

    Returns:
        Tuple of (included_lines, excluded_count).
    """
    missing_lines = get_missing_lines(db_path)
    included = []
    excluded_count = 0

    for line in missing_lines:
        file_path = line.get("file_path", "")
        if is_excluded_path(file_path):
            excluded_count += 1
        else:
            included.append(line)

    return included, excluded_count


def aggregate_files_by_coverage(
    missing_lines: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Aggregate missing lines by file with coverage stats.

    Args:
        missing_lines: List of missing line records.

    Returns:
        Dict mapping file paths to their coverage info.
    """
    files: dict[str, dict[str, Any]] = {}

    for line in missing_lines:
        file_path = line.get("file_path", "")
        if file_path not in files:
            files[file_path] = {"missing_lines": 0, "missing_branches": 0}

        files[file_path]["missing_lines"] += 1
        files[file_path]["missing_branches"] += len(line.get("missing_branch_exits", []))

    return files


def generate_summary(db_path: Path) -> dict[str, Any]:
    """Generate a filtered coverage summary.

    Args:
        db_path: Path to the coverage database.

    Returns:
        Summary dict with filtered statistics.
    """
    # Get tier summaries
    tier_summaries = get_tier_summary(db_path)

    # Calculate raw totals from tier summaries
    total_functions_below = 0
    overall_line_pct = 0.0

    if tier_summaries:
        # Use the first tier's overall percentages (all tiers should have same overall)
        first_tier: dict[str, Any] = next(iter(tier_summaries.values()), {})
        overall_line_pct = first_tier.get("overall_line_pct", 0.0) or 0.0

        # Sum up functions below threshold across all tiers
        for tier_data in tier_summaries.values():
            total_functions_below += tier_data.get("failing_functions", 0)

    # Filter functions
    included_funcs, excluded_funcs = get_filtered_functions(db_path)

    # Filter missing lines
    included_lines, excluded_line_count = get_filtered_missing_lines(db_path)

    # Count total missing lines and branches from included lines
    total_missing_lines = len(included_lines)
    total_missing_branches = sum(
        len(line.get("missing_branch_exits", [])) for line in included_lines
    )

    # Get files with issues
    files_with_issues = aggregate_files_by_coverage(included_lines)

    # Get use case coverage
    use_case_coverage = get_usecase_coverage(db_path)

    # Get run metadata
    try:
        conn = get_db_connection(db_path)
        cursor = conn.execute("SELECT generated_at FROM cc_run_metadata WHERE id = 1")
        row = cursor.fetchone()
        generated_at = row["generated_at"] if row else "Unknown"
        conn.close()
    except Exception:
        generated_at = "Unknown"

    # Build summary
    return {
        "generated_at": generated_at,
        "raw_totals": {
            "percent_covered": overall_line_pct,
            "missing_lines": total_missing_lines,
            "missing_branches": total_missing_branches,
            "total_functions_below_threshold": total_functions_below,
        },
        "filtered_totals": {
            "functions_below_threshold": len(included_funcs),
            "excluded_functions": len(excluded_funcs),
            "missing_lines": len(included_lines),
            "excluded_lines": excluded_line_count,
            "files_with_issues": len(files_with_issues),
        },
        "tier_summaries": {
            tier: {
                "coverage_type": data.get("coverage_type", "line_branch"),
                "overall_line_pct": data.get("overall_line_pct", 0.0) or 0.0,
                "overall_branch_pct": data.get("overall_branch_pct", 0.0) or 0.0,
                "total_functions": data.get("total_functions", 0),
                "passing_functions": data.get("passing_functions", 0),
                "failing_functions": data.get("failing_functions", 0),
                "tier_pass": bool(data.get("tier_pass", 0)),
            }
            for tier, data in tier_summaries.items()
        },
        "use_case_coverage": {
            "total": use_case_coverage.get("total", 0),
            "covered": use_case_coverage.get("covered", 0),
            "uncovered": len(use_case_coverage.get("uncovered", [])),
        },
        "top_files_by_missing_lines": sorted(
            [
                {"file": f, "missing_lines": info["missing_lines"]}
                for f, info in files_with_issues.items()
            ],
            key=lambda x: x["missing_lines"],
            reverse=True,
        )[:10],
    }


def print_summary(summary: dict[str, Any]) -> None:
    """Print a human-readable summary.

    Args:
        summary: The summary dict from generate_summary.
    """
    print("=" * 60)
    print("COVERAGE SUMMARY (with exclusions applied)")
    print("=" * 60)
    print(f"Generated: {summary['generated_at']}")
    print()

    print("RAW TOTALS (before exclusions):")
    raw = summary["raw_totals"]
    print(f"  Line coverage: {format_percentage(raw['percent_covered'])}")
    print(f"  Missing lines: {raw['missing_lines']}")
    print(f"  Missing branches: {raw['missing_branches']}")
    print(f"  Functions below threshold: {raw['total_functions_below_threshold']}")
    print()

    print("FILTERED TOTALS (after exclusions):")
    filtered = summary["filtered_totals"]
    print(f"  Functions below threshold: {filtered['functions_below_threshold']}")
    print(f"  Excluded functions: {filtered['excluded_functions']}")
    print(f"  Missing lines: {filtered['missing_lines']}")
    print(f"  Excluded lines: {filtered['excluded_lines']}")
    print(f"  Files with issues: {filtered['files_with_issues']}")
    print()

    print("USE CASE COVERAGE:")
    uc = summary["use_case_coverage"]
    print(f"  Total: {uc['total']}")
    print(f"  Covered: {uc['covered']}")
    print(f"  Uncovered: {uc['uncovered']}")
    print()

    print("TOP 10 FILES BY MISSING LINES:")
    for item in summary["top_files_by_missing_lines"]:
        print(f"  {item['missing_lines']:4d} lines  {item['file']}")

    print()
    print("=" * 60)


def main() -> int:
    """Run the coverage summary tool.

    Returns:
        Exit code (0 for success).
    """
    parser = argparse.ArgumentParser(description="Get coverage summary with exclusions applied")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of human-readable format",
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
        summary = generate_summary(db_path)
    except Exception as e:
        print(f"Error generating summary: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print_summary(summary)

    return 0


if __name__ == "__main__":
    sys.exit(main())
