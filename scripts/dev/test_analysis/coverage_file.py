"""Coverage file tool - get detailed problems for a specific file.

Shows all coverage issues for a specific file including missing lines
with context and functions below threshold.

Usage:
    uv run coverage-file app/services/example_service.py
    uv run coverage-file app/core/factory.py --json
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


def get_file_details(data: dict[str, Any], file_path: str) -> dict[str, Any] | None:
    """Get detailed coverage info for a specific file.

    Args:
        data: The coverage_llm.json data.
        file_path: The file path to look up.

    Returns:
        Dict with file coverage details, or None if file not found.
    """
    # Check if file is excluded
    if is_excluded_path(file_path):
        return {
            "file": file_path,
            "excluded": True,
            "exclusion_reason": "Path matches excluded patterns (infrastructure/HTTP handling)",
            "missing_lines": [],
            "missing_branches": [],
            "functions_below_threshold": [],
        }

    # Collect missing lines for this file
    missing_lines = []
    missing_branches = []
    all_missing = data.get("code_coverage", {}).get("missing_lines", [])

    for line in all_missing:
        if line.get("file") == file_path:
            missing_lines.append(
                {
                    "line_number": line.get("line_number"),
                    "content": line.get("content", "").strip(),
                    "context_before": [
                        {
                            "line": c.get("line_number"),
                            "content": c.get("content", "").strip(),
                        }
                        for c in line.get("context_before", [])
                    ],
                    "context_after": [
                        {
                            "line": c.get("line_number"),
                            "content": c.get("content", "").strip(),
                        }
                        for c in line.get("context_after", [])
                    ],
                }
            )
            for branch in line.get("missing_branch_exits", []):
                missing_branches.append(
                    {
                        "from_line": line.get("line_number"),
                        "to_line": branch,
                    }
                )

    # Collect functions below threshold for this file
    functions_below = []
    all_functions = data.get("function_coverage", {}).get("functions_below_threshold", [])

    for func in all_functions:
        if func.get("file") == file_path:
            functions_below.append(
                {
                    "name": func.get("function", ""),
                    "line_coverage": func.get("line_coverage_pct", 0),
                    "branch_coverage": func.get("branch_coverage_pct", 0),
                    "missing_lines": func.get("missing_lines", []),
                    "missing_branches": func.get("missing_branches", []),
                }
            )

    if not missing_lines and not missing_branches and not functions_below:
        return None

    return {
        "file": file_path,
        "excluded": False,
        "missing_lines": missing_lines,
        "missing_branches": missing_branches,
        "functions_below_threshold": functions_below,
        "summary": {
            "missing_lines_count": len(missing_lines),
            "missing_branches_count": len(missing_branches),
            "functions_below_threshold_count": len(functions_below),
        },
    }


def print_file_details(details: dict[str, Any]) -> None:
    """Print file details in human-readable format.

    Args:
        details: The file details dict.
    """
    print("=" * 70)
    print(f"FILE: {details['file']}")
    print("=" * 70)

    if details.get("excluded"):
        print(f"\nEXCLUDED: {details.get('exclusion_reason')}")
        print("This file is tested via integration/e2e tests, not unit tests.")
        return

    summary = details.get("summary", {})
    print(f"\nMissing lines: {summary.get('missing_lines_count', 0)}")
    print(f"Missing branches: {summary.get('missing_branches_count', 0)}")
    print(f"Functions below threshold: {summary.get('functions_below_threshold_count', 0)}")

    # Print functions below threshold
    functions = details.get("functions_below_threshold", [])
    if functions:
        print("\n" + "-" * 70)
        print("FUNCTIONS BELOW THRESHOLD:")
        print("-" * 70)
        for func in functions:
            print(f"\n  {func['name']}:")
            print(f"    Line coverage: {format_percentage(func['line_coverage'])}")
            print(f"    Branch coverage: {format_percentage(func['branch_coverage'])}")
            if func.get("missing_lines"):
                lines_str = ", ".join(str(ln) for ln in func["missing_lines"][:10])
                if len(func["missing_lines"]) > 10:
                    lines_str += f" ... (+{len(func['missing_lines']) - 10} more)"
                print(f"    Missing lines: {lines_str}")

    # Print missing lines with context
    missing_lines = details.get("missing_lines", [])
    if missing_lines:
        print("\n" + "-" * 70)
        print("MISSING LINES (with context):")
        print("-" * 70)
        # Group consecutive lines
        shown = 0
        for line in missing_lines[:20]:  # Limit to first 20
            print(f"\n  Line {line['line_number']}:")
            for ctx in line.get("context_before", []):
                print(f"    {ctx['line']:4d} | {ctx['content']}")
            print(f"  > {line['line_number']:4d} | {line['content']}")
            for ctx in line.get("context_after", []):
                print(f"    {ctx['line']:4d} | {ctx['content']}")
            shown += 1

        if len(missing_lines) > 20:
            print(f"\n  ... and {len(missing_lines) - 20} more missing lines")

    print("\n" + "=" * 70)


def main() -> int:
    """Run the coverage file tool.

    Returns:
        Exit code (0 for success, 1 for errors).
    """
    parser = argparse.ArgumentParser(
        description="Get detailed coverage problems for a specific file"
    )
    parser.add_argument(
        "file",
        type=str,
        help="File path to get coverage details for",
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

    details = get_file_details(data, args.file)

    if details is None:
        print(f"No coverage issues found for: {args.file}")
        print("(File may have full coverage or may not be in the coverage report)")
        return 0

    if args.json:
        print(json.dumps(details, indent=2))
    else:
        print_file_details(details)

    return 0


if __name__ == "__main__":
    sys.exit(main())
