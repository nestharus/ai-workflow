"""Coverage summary tool - get totals across tiers with exclusions.

Provides a high-level summary of coverage data from coverage_llm.json,
filtering out excluded paths (infrastructure, HTTP handling).

Usage:
    uv run coverage-summary
    uv run coverage-summary --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from scripts.dev.test_analysis.common import (
    format_percentage,
    is_excluded_path,
    load_coverage_llm,
)


def get_filtered_functions(
    data: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Get functions below threshold, split into included and excluded.

    Args:
        data: The coverage_llm.json data.

    Returns:
        Tuple of (included_functions, excluded_functions).
    """
    functions = data.get("function_coverage", {}).get("functions_below_threshold", [])
    included = []
    excluded = []

    for func in functions:
        file_path = func.get("file", "")

        if is_excluded_path(file_path):
            excluded.append(func)
        else:
            included.append(func)

    return included, excluded


def get_filtered_missing_lines(
    data: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    """Get missing lines, filtering out excluded paths.

    Args:
        data: The coverage_llm.json data.

    Returns:
        Tuple of (included_lines, excluded_count).
    """
    missing_lines = data.get("code_coverage", {}).get("missing_lines", [])
    included = []
    excluded_count = 0

    for line in missing_lines:
        file_path = line.get("file", "")
        if is_excluded_path(file_path):
            excluded_count += 1
        else:
            included.append(line)

    return included, excluded_count


def get_files_by_coverage(
    data: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Aggregate missing lines by file with coverage stats.

    Args:
        data: The coverage_llm.json data.

    Returns:
        Dict mapping file paths to their coverage info.
    """
    missing_lines, _ = get_filtered_missing_lines(data)
    files: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"missing_lines": 0, "missing_branches": 0}
    )

    for line in missing_lines:
        file_path = line.get("file", "")
        files[file_path]["missing_lines"] += 1
        files[file_path]["missing_branches"] += len(line.get("missing_branch_exits", []))

    return dict(files)


def generate_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Generate a filtered coverage summary.

    Args:
        data: The coverage_llm.json data.

    Returns:
        Summary dict with filtered statistics.
    """
    # Get raw totals
    code_coverage = data.get("code_coverage", {})
    totals = code_coverage.get("coverage_totals", {})
    function_coverage = data.get("function_coverage", {})
    use_case_coverage = data.get("use_case_coverage", {})

    # Filter functions
    included_funcs, excluded_funcs = get_filtered_functions(data)

    # Filter missing lines
    included_lines, excluded_line_count = get_filtered_missing_lines(data)

    # Get files with issues
    files_with_issues = get_files_by_coverage(data)

    # Build summary
    return {
        "generated_at": data.get("generated_at"),
        "raw_totals": {
            "percent_covered": totals.get("percent_covered", 0),
            "missing_lines": totals.get("missing_lines", 0),
            "missing_branches": totals.get("missing_branches", 0),
            "total_functions_below_threshold": function_coverage.get(
                "total_functions_below_threshold", 0
            ),
        },
        "filtered_totals": {
            "functions_below_threshold": len(included_funcs),
            "excluded_functions": len(excluded_funcs),
            "missing_lines": len(included_lines),
            "excluded_lines": excluded_line_count,
            "files_with_issues": len(files_with_issues),
        },
        "tier_summaries": function_coverage.get("tier_summaries", {}),
        "use_case_coverage": {
            "total": use_case_coverage.get("totals", {}).get("total", 0),
            "covered": use_case_coverage.get("totals", {}).get("covered", 0),
            "uncovered": len(use_case_coverage.get("uncovered_use_cases", [])),
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
        "--path",
        type=Path,
        default=None,
        help="Path to coverage_llm.json (default: coverage_llm.json)",
    )
    args = parser.parse_args()

    try:
        data = load_coverage_llm(args.path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    summary = generate_summary(data)

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print_summary(summary)

    return 0


if __name__ == "__main__":
    sys.exit(main())
