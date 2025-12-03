"""Redundant test detector using coverage contexts.

This module analyzes per-test coverage data to identify tests that add no unique
coverage - meaning all lines/branches they cover are also covered by other tests.

Usage:
    1. Run tests with coverage contexts enabled:
       pytest --cov=app --cov-context=test --cov-branch

    2. Analyze the .coverage database:
       from scripts.dev.test_runner.redundant_test_detector import detect_redundant_tests
       result = detect_redundant_tests(Path(".coverage"))

The detector uses coverage.py's SQLite database schema to query per-test coverage.
See: https://coverage.readthedocs.io/en/latest/dbschema.html
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TestCoverage:
    """Coverage data for a single test."""

    test_name: str
    covered_lines: set[tuple[str, int]]  # (file_path, line_number)
    covered_arcs: set[tuple[str, int, int]]  # (file_path, from_line, to_line)


@dataclass
class RedundantTestResult:
    """Result of redundant test detection."""

    redundant_tests: list[dict[str, Any]]
    total_tests: int
    tests_with_unique_coverage: int
    summary: dict[str, Any] = field(default_factory=dict)


def _register_numbits_functions(conn: sqlite3.Connection) -> None:
    """Register coverage.py numbits functions for SQLite.

    Uses coverage.py's built-in functions if available, otherwise provides
    a fallback implementation.
    """
    try:
        from coverage.numbits import register_sqlite_functions

        register_sqlite_functions(conn)
    except ImportError:
        # Fallback: implement numbits_to_nums ourselves
        # numbits is a compressed binary format for storing sets of integers
        def numbits_to_nums(numbits: bytes | None) -> str:
            """Convert numbits blob to JSON array of line numbers."""
            import json

            if numbits is None:
                return "[]"

            nums = []
            for byte_index, byte_val in enumerate(numbits):
                for bit_index in range(8):
                    if byte_val & (1 << bit_index):
                        nums.append(byte_index * 8 + bit_index)
            return json.dumps(nums)

        conn.create_function("numbits_to_nums", 1, numbits_to_nums)


def _load_test_coverage_from_db(coverage_db_path: Path) -> dict[str, TestCoverage]:
    """Load per-test coverage data from coverage.py SQLite database.

    Args:
        coverage_db_path: Path to the .coverage SQLite database

    Returns:
        Dictionary mapping test names to their coverage data
    """
    import json

    if not coverage_db_path.exists():
        return {}

    conn = sqlite3.connect(str(coverage_db_path))
    _register_numbits_functions(conn)

    test_coverage: dict[str, TestCoverage] = {}

    try:
        # Check if contexts were recorded
        cursor = conn.execute("SELECT COUNT(*) FROM context WHERE context != ''")
        context_count = cursor.fetchone()[0]

        if context_count == 0:
            # No test contexts recorded - coverage was not run with --cov-context=test
            return {}

        # Get all test contexts (excluding empty context which is setup/teardown code)
        cursor = conn.execute(
            "SELECT id, context FROM context WHERE context != '' AND context IS NOT NULL"
        )
        contexts = {row[0]: row[1] for row in cursor.fetchall()}

        # Get file paths
        cursor = conn.execute("SELECT id, path FROM file")
        files = {row[0]: row[1] for row in cursor.fetchall()}

        # Check if we have line_bits table (line coverage)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='line_bits'"
        )
        has_line_bits = cursor.fetchone() is not None

        # Check if we have arc table (branch coverage)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='arc'"
        )
        has_arcs = cursor.fetchone() is not None

        # Load line coverage per context
        if has_line_bits:
            cursor = conn.execute(
                """
                SELECT context_id, file_id, numbits_to_nums(numbits) as lines
                FROM line_bits
                WHERE context_id IN (SELECT id FROM context WHERE context != '')
                """
            )

            for context_id, file_id, lines_json in cursor.fetchall():
                if context_id not in contexts or file_id not in files:
                    continue

                test_name = contexts[context_id]
                file_path = files[file_id]
                line_nums = json.loads(lines_json) if lines_json else []

                if test_name not in test_coverage:
                    test_coverage[test_name] = TestCoverage(
                        test_name=test_name,
                        covered_lines=set(),
                        covered_arcs=set(),
                    )

                for line_num in line_nums:
                    test_coverage[test_name].covered_lines.add((file_path, line_num))

        # Load arc (branch) coverage per context
        if has_arcs:
            cursor = conn.execute(
                """
                SELECT context_id, file_id, fromno, tono
                FROM arc
                WHERE context_id IN (SELECT id FROM context WHERE context != '')
                """
            )

            for context_id, file_id, from_line, to_line in cursor.fetchall():
                if context_id not in contexts or file_id not in files:
                    continue

                test_name = contexts[context_id]
                file_path = files[file_id]

                if test_name not in test_coverage:
                    test_coverage[test_name] = TestCoverage(
                        test_name=test_name,
                        covered_lines=set(),
                        covered_arcs=set(),
                    )

                test_coverage[test_name].covered_arcs.add((file_path, from_line, to_line))

    finally:
        conn.close()

    return test_coverage


def _compute_unique_coverage(
    test_name: str,
    test_coverage: dict[str, TestCoverage],
) -> tuple[set[tuple[str, int]], set[tuple[str, int, int]]]:
    """Compute lines/arcs that are uniquely covered by a specific test.

    Args:
        test_name: Name of the test to analyze
        test_coverage: All test coverage data

    Returns:
        Tuple of (unique_lines, unique_arcs) that only this test covers
    """
    if test_name not in test_coverage:
        return set(), set()

    this_test = test_coverage[test_name]

    # Compute coverage from all OTHER tests
    other_lines: set[tuple[str, int]] = set()
    other_arcs: set[tuple[str, int, int]] = set()

    for name, cov in test_coverage.items():
        if name != test_name:
            other_lines.update(cov.covered_lines)
            other_arcs.update(cov.covered_arcs)

    # Unique coverage = this test's coverage - all other tests' coverage
    unique_lines = this_test.covered_lines - other_lines
    unique_arcs = this_test.covered_arcs - other_arcs

    return unique_lines, unique_arcs


def detect_redundant_tests(
    coverage_db_path: Path,
    include_partial: bool = False,
) -> RedundantTestResult:
    """Detect tests that add no unique coverage.

    A test is considered redundant if every line and branch it covers is also
    covered by at least one other test. Removing such tests would not reduce
    overall coverage.

    Args:
        coverage_db_path: Path to the .coverage SQLite database
        include_partial: If True, also report tests with very low unique coverage

    Returns:
        RedundantTestResult with list of redundant tests and statistics
    """
    test_coverage = _load_test_coverage_from_db(coverage_db_path)

    if not test_coverage:
        return RedundantTestResult(
            redundant_tests=[],
            total_tests=0,
            tests_with_unique_coverage=0,
            summary={
                "error": "No test coverage contexts found. "
                "Run tests with --cov-context=test to enable per-test tracking."
            },
        )

    redundant_tests: list[dict[str, Any]] = []
    tests_with_unique: int = 0

    for test_name, coverage in test_coverage.items():
        unique_lines, unique_arcs = _compute_unique_coverage(test_name, test_coverage)

        total_lines = len(coverage.covered_lines)
        total_arcs = len(coverage.covered_arcs)
        unique_line_count = len(unique_lines)
        unique_arc_count = len(unique_arcs)

        # A test is redundant if it has zero unique coverage
        is_redundant = unique_line_count == 0 and unique_arc_count == 0

        # Calculate unique coverage percentage
        total_coverage_points = total_lines + total_arcs
        unique_coverage_points = unique_line_count + unique_arc_count

        if total_coverage_points > 0:
            unique_pct = (unique_coverage_points / total_coverage_points) * 100
        else:
            unique_pct = 0.0

        if is_redundant:
            redundant_tests.append(
                {
                    "test_name": test_name,
                    "total_lines_covered": total_lines,
                    "total_arcs_covered": total_arcs,
                    "unique_lines": unique_line_count,
                    "unique_arcs": unique_arc_count,
                    "unique_coverage_pct": round(unique_pct, 1),
                    "reason": "All coverage duplicated by other tests",
                }
            )
        elif include_partial and unique_pct < 5.0 and total_coverage_points > 0:
            # Optionally report tests with very low unique coverage
            redundant_tests.append(
                {
                    "test_name": test_name,
                    "total_lines_covered": total_lines,
                    "total_arcs_covered": total_arcs,
                    "unique_lines": unique_line_count,
                    "unique_arcs": unique_arc_count,
                    "unique_coverage_pct": round(unique_pct, 1),
                    "reason": f"Only {unique_pct:.1f}% unique coverage",
                }
            )
        else:
            tests_with_unique += 1

    # Sort by total coverage (tests covering more are more likely worth keeping)
    redundant_tests.sort(
        key=lambda t: t["total_lines_covered"] + t["total_arcs_covered"],
    )

    return RedundantTestResult(
        redundant_tests=redundant_tests,
        total_tests=len(test_coverage),
        tests_with_unique_coverage=tests_with_unique,
        summary={
            "total_tests_analyzed": len(test_coverage),
            "redundant_test_count": len(redundant_tests),
            "tests_with_unique_coverage": tests_with_unique,
            "redundancy_rate_pct": round(
                (len(redundant_tests) / len(test_coverage)) * 100, 1
            )
            if test_coverage
            else 0.0,
        },
    )


def format_redundant_test_report(result: RedundantTestResult) -> str:
    """Format redundant test detection results as a human-readable report.

    Args:
        result: RedundantTestResult from detect_redundant_tests

    Returns:
        Formatted string report
    """
    lines = [
        "=" * 70,
        "REDUNDANT TEST DETECTION REPORT",
        "=" * 70,
        "",
    ]

    if "error" in result.summary:
        lines.append(f"ERROR: {result.summary['error']}")
        return "\n".join(lines)

    lines.extend(
        [
            f"Total tests analyzed:      {result.total_tests:>6}",
            f"Tests with unique coverage:{result.tests_with_unique_coverage:>6}",
            f"Redundant tests:           {len(result.redundant_tests):>6}",
            f"Redundancy rate:           {result.summary.get('redundancy_rate_pct', 0):>5.1f}%",
            "",
        ]
    )

    if result.redundant_tests:
        lines.append("Redundant tests (can be removed without reducing coverage):")
        lines.append("-" * 70)

        for test in result.redundant_tests:
            lines.append(f"  {test['test_name']}")
            lines.append(
                f"    Lines: {test['total_lines_covered']}, "
                f"Arcs: {test['total_arcs_covered']}, "
                f"Unique: {test['unique_coverage_pct']}%"
            )
            lines.append(f"    Reason: {test['reason']}")
            lines.append("")
    else:
        lines.append("No redundant tests found - all tests contribute unique coverage.")

    return "\n".join(lines)


def main() -> int:
    """CLI entry point for redundant test detection."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect tests that add no unique coverage.",
    )
    parser.add_argument(
        "--coverage-file",
        "-c",
        type=Path,
        default=Path(".coverage"),
        help="Path to coverage database (default: .coverage)",
    )
    parser.add_argument(
        "--include-partial",
        action="store_true",
        help="Include tests with <5%% unique coverage",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of formatted report",
    )

    args = parser.parse_args()

    result = detect_redundant_tests(
        args.coverage_file,
        include_partial=args.include_partial,
    )

    if args.json:
        import json

        output = {
            "redundant_tests": result.redundant_tests,
            "summary": result.summary,
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_redundant_test_report(result))

    # Return non-zero if redundant tests found
    return 1 if result.redundant_tests else 0


if __name__ == "__main__":
    raise SystemExit(main())
