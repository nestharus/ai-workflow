"""Coverage database module for managing .coverage SQLite database operations.

This module handles all custom table operations (cc_* tables) in the .coverage
SQLite database, providing write and query functions for coverage analysis.
"""

import contextlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.dev.test_runner.test_coverage import (
    FunctionCoverage,
    MissingLineDetail,
    TestTierConfig,
    UseCase,
)

# SQL schema for custom tables
SCHEMA_SQL = """
-- Run metadata
CREATE TABLE IF NOT EXISTS cc_run_metadata (
    id INTEGER PRIMARY KEY,
    generated_at TEXT NOT NULL,
    repo_root TEXT NOT NULL
);

-- Tier configuration (from pyproject.toml)
CREATE TABLE IF NOT EXISTS cc_tier_config (
    tier TEXT PRIMARY KEY,
    coverage_type TEXT NOT NULL,
    test_path TEXT NOT NULL,
    source_paths TEXT NOT NULL,
    min_line_overall REAL,
    min_branch_overall REAL,
    min_line_per_function REAL,
    min_branch_per_function REAL,
    min_usecase REAL,
    skip_private_functions INTEGER DEFAULT 0,
    service_layer_only INTEGER DEFAULT 0
);

-- Per-function coverage with pass/fail flags
CREATE TABLE IF NOT EXISTS cc_function_coverage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    function_name TEXT NOT NULL,
    tier TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    total_lines INTEGER NOT NULL,
    covered_lines INTEGER NOT NULL,
    line_coverage_pct REAL NOT NULL,
    total_branches INTEGER NOT NULL,
    covered_branches INTEGER NOT NULL,
    branch_coverage_pct REAL NOT NULL,
    missing_lines TEXT,
    missing_branches TEXT,
    threshold_line REAL NOT NULL,
    threshold_branch REAL NOT NULL,
    line_pass INTEGER NOT NULL,
    branch_pass INTEGER NOT NULL,
    UNIQUE(file_path, function_name, tier)
);

-- Missing lines with source context (for detailed viewing)
CREATE TABLE IF NOT EXISTS cc_missing_line (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    line_number INTEGER NOT NULL,
    content TEXT,
    context_before TEXT,
    context_after TEXT,
    missing_branch_exits TEXT,
    UNIQUE(file_path, line_number)
);

-- Use case registry (from tests/docs/use_cases.yaml)
CREATE TABLE IF NOT EXISTS cc_usecase (
    usecase_id TEXT PRIMARY KEY,
    endpoint TEXT,
    method TEXT,
    description TEXT,
    test_tier TEXT NOT NULL
);

-- Use case coverage tracking
CREATE TABLE IF NOT EXISTS cc_usecase_coverage (
    usecase_id TEXT PRIMARY KEY,
    covered INTEGER NOT NULL DEFAULT 0,
    test_file TEXT,
    test_function TEXT,
    FOREIGN KEY (usecase_id) REFERENCES cc_usecase(usecase_id)
);

-- Test results (pass/fail/error with details)
CREATE TABLE IF NOT EXISTS cc_test_result (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tier TEXT NOT NULL,
    test_name TEXT NOT NULL,
    status TEXT NOT NULL,
    duration REAL,
    message TEXT,
    traceback TEXT,
    UNIQUE(tier, test_name)
);

-- Tier summary with overall pass/fail
CREATE TABLE IF NOT EXISTS cc_tier_summary (
    tier TEXT PRIMARY KEY,
    coverage_type TEXT NOT NULL,
    total_functions INTEGER DEFAULT 0,
    passing_functions INTEGER DEFAULT 0,
    failing_functions INTEGER DEFAULT 0,
    overall_line_pct REAL,
    overall_branch_pct REAL,
    total_usecases INTEGER DEFAULT 0,
    usecases_covered INTEGER DEFAULT 0,
    total_tests INTEGER DEFAULT 0,
    tests_passed INTEGER DEFAULT 0,
    tests_failed INTEGER DEFAULT 0,
    tier_pass INTEGER NOT NULL
);
"""


def _get_connection(db_path: Path) -> sqlite3.Connection:
    """Get a connection to the coverage database.

    Args:
        db_path: Path to the .coverage database file

    Returns:
        SQLite connection with row factory enabled
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_custom_tables(db_path: Path) -> None:
    """Create custom cc_* tables if they don't exist.

    Args:
        db_path: Path to the .coverage database file
    """
    conn = _get_connection(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def clear_custom_tables(db_path: Path) -> None:
    """Clear all custom cc_* tables for a fresh run.

    Args:
        db_path: Path to the .coverage database file
    """
    conn = _get_connection(db_path)
    try:
        tables = [
            "cc_run_metadata",
            "cc_tier_config",
            "cc_function_coverage",
            "cc_missing_line",
            "cc_usecase",
            "cc_usecase_coverage",
            "cc_test_result",
            "cc_tier_summary",
        ]
        for table in tables:
            with contextlib.suppress(sqlite3.OperationalError):
                # Table might not exist yet, suppress the error
                conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()


def write_run_metadata(db_path: Path, repo_root: Path) -> None:
    """Write run metadata to the database.

    Args:
        db_path: Path to the .coverage database file
        repo_root: Path to the repository root directory
    """
    conn = _get_connection(db_path)
    try:
        # Clear existing metadata
        conn.execute("DELETE FROM cc_run_metadata")

        # Insert new metadata
        conn.execute(
            "INSERT INTO cc_run_metadata (id, generated_at, repo_root) VALUES (?, ?, ?)",
            (1, datetime.now(UTC).isoformat(), str(repo_root)),
        )
        conn.commit()
    finally:
        conn.close()


def write_tier_config(db_path: Path, tier: str, config: TestTierConfig) -> None:
    """Write tier configuration to the database.

    Args:
        db_path: Path to the .coverage database file
        tier: Tier name (e.g., 'unit', 'integration')
        config: Test tier configuration object
    """
    conn = _get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO cc_tier_config (
                tier, coverage_type, test_path, source_paths,
                min_line_overall, min_branch_overall,
                min_line_per_function, min_branch_per_function,
                min_usecase, skip_private_functions, service_layer_only
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tier,
                config.coverage_type,
                config.test_path,
                json.dumps(config.source_paths),
                config.min_line_overall,
                config.min_branch_overall,
                config.min_line_per_function,
                config.min_branch_per_function,
                config.min_usecase,
                1 if config.skip_private_functions else 0,
                1 if config.service_layer_only else 0,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def write_function_coverage(
    db_path: Path,
    tier: str,
    functions: list[FunctionCoverage],
    threshold_line: float,
    threshold_branch: float,
) -> None:
    """Write per-function coverage data with pass/fail flags.

    Args:
        db_path: Path to the .coverage database file
        tier: Tier name (e.g., 'unit', 'integration')
        functions: List of function coverage objects
        threshold_line: Line coverage threshold for this tier
        threshold_branch: Branch coverage threshold for this tier
    """
    conn = _get_connection(db_path)
    try:
        for func in functions:
            # Calculate pass/fail flags
            line_pass = 1 if func.line_coverage_pct >= threshold_line else 0
            branch_pass = 1 if func.branch_coverage_pct >= threshold_branch else 0

            conn.execute(
                """
                INSERT OR REPLACE INTO cc_function_coverage (
                    file_path, function_name, tier, start_line, end_line,
                    total_lines, covered_lines, line_coverage_pct,
                    total_branches, covered_branches, branch_coverage_pct,
                    missing_lines, missing_branches,
                    threshold_line, threshold_branch,
                    line_pass, branch_pass
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    func.file_path,
                    func.name,
                    tier,
                    func.start_line,
                    func.end_line,
                    func.total_lines,
                    func.covered_lines,
                    func.line_coverage_pct,
                    func.total_branches,
                    func.covered_branches,
                    func.branch_coverage_pct,
                    json.dumps(func.missing_lines),
                    json.dumps(func.missing_branches),
                    threshold_line,
                    threshold_branch,
                    line_pass,
                    branch_pass,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def write_missing_lines(db_path: Path, missing_lines: list[MissingLineDetail]) -> None:
    """Write missing lines with source context.

    Args:
        db_path: Path to the .coverage database file
        missing_lines: List of missing line detail objects
    """
    conn = _get_connection(db_path)
    try:
        for line in missing_lines:
            conn.execute(
                """
                INSERT OR REPLACE INTO cc_missing_line (
                    file_path, line_number, content,
                    context_before, context_after, missing_branch_exits
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    line.file,
                    line.line_number,
                    line.content,
                    json.dumps(line.context_before),
                    json.dumps(line.context_after),
                    json.dumps(line.missing_branch_exits),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def write_usecase_registry(db_path: Path, usecases: list[UseCase]) -> None:
    """Write use case definitions to the database.

    Args:
        db_path: Path to the .coverage database file
        usecases: List of use case objects
    """
    conn = _get_connection(db_path)
    try:
        for usecase in usecases:
            conn.execute(
                """
                INSERT OR REPLACE INTO cc_usecase (
                    usecase_id, endpoint, method, description, test_tier
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    usecase.id,
                    usecase.endpoint,
                    usecase.method,
                    usecase.description,
                    usecase.test_tier,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def write_usecase_coverage(
    db_path: Path,
    usecase_id: str,
    covered: bool,
    test_file: str | None = None,
    test_function: str | None = None,
) -> None:
    """Write use case coverage status.

    Args:
        db_path: Path to the .coverage database file
        usecase_id: Use case identifier (e.g., 'UC-API-001')
        covered: Whether the use case is covered by tests
        test_file: Path to the test file that covers this use case
        test_function: Name of the test function that covers this use case
    """
    conn = _get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO cc_usecase_coverage (
                usecase_id, covered, test_file, test_function
            ) VALUES (?, ?, ?, ?)
            """,
            (usecase_id, 1 if covered else 0, test_file, test_function),
        )
        conn.commit()
    finally:
        conn.close()


def write_test_result(
    db_path: Path,
    tier: str,
    test_name: str,
    status: str,
    duration: float | None = None,
    message: str | None = None,
    traceback: str | None = None,
) -> None:
    """Write test execution result.

    Args:
        db_path: Path to the .coverage database file
        tier: Tier name (e.g., 'unit', 'integration')
        test_name: Full test name (e.g., 'tests/unit/test_foo.py::test_bar')
        status: Test status ('passed', 'failed', 'error', 'skipped')
        duration: Test execution duration in seconds
        message: Failure/error message
        traceback: Full traceback for failures/errors
    """
    conn = _get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO cc_test_result (
                tier, test_name, status, duration, message, traceback
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (tier, test_name, status, duration, message, traceback),
        )
        conn.commit()
    finally:
        conn.close()


def write_tier_summary(db_path: Path, tier: str, summary: dict[str, Any]) -> None:
    """Write tier summary with overall statistics.

    Args:
        db_path: Path to the .coverage database file
        tier: Tier name (e.g., 'unit', 'integration')
        summary: Summary dictionary with keys:
            - coverage_type: 'line_branch' or 'usecase'
            - total_functions: Total number of functions analyzed
            - passing_functions: Number of functions meeting thresholds
            - failing_functions: Number of functions below thresholds
            - overall_line_pct: Overall line coverage percentage
            - overall_branch_pct: Overall branch coverage percentage
            - total_usecases: Total number of use cases
            - usecases_covered: Number of covered use cases
            - total_tests: Total number of tests
            - tests_passed: Number of passed tests
            - tests_failed: Number of failed tests
            - tier_pass: 1 if tier meets all requirements, 0 otherwise
    """
    conn = _get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO cc_tier_summary (
                tier, coverage_type,
                total_functions, passing_functions, failing_functions,
                overall_line_pct, overall_branch_pct,
                total_usecases, usecases_covered,
                total_tests, tests_passed, tests_failed,
                tier_pass
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tier,
                summary.get("coverage_type", "line_branch"),
                summary.get("total_functions", 0),
                summary.get("passing_functions", 0),
                summary.get("failing_functions", 0),
                summary.get("overall_line_pct"),
                summary.get("overall_branch_pct"),
                summary.get("total_usecases", 0),
                summary.get("usecases_covered", 0),
                summary.get("total_tests", 0),
                summary.get("tests_passed", 0),
                summary.get("tests_failed", 0),
                summary.get("tier_pass", 0),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_functions_below_threshold(
    db_path: Path,
    tier: str | None = None,
    file_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Query functions that are below coverage thresholds.

    Args:
        db_path: Path to the .coverage database file
        tier: Optional tier name to filter by
        file_filter: Optional file path pattern to filter by

    Returns:
        List of dictionaries with function coverage details
    """
    conn = _get_connection(db_path)
    try:
        query = """
            SELECT
                file_path, function_name, tier, start_line, end_line,
                total_lines, covered_lines, line_coverage_pct,
                total_branches, covered_branches, branch_coverage_pct,
                missing_lines, missing_branches,
                threshold_line, threshold_branch,
                line_pass, branch_pass
            FROM cc_function_coverage
            WHERE (line_pass = 0 OR branch_pass = 0)
        """
        params = []

        if tier is not None:
            query += " AND tier = ?"
            params.append(tier)

        if file_filter is not None:
            query += " AND file_path LIKE ?"
            params.append(f"%{file_filter}%")

        query += " ORDER BY file_path, function_name"

        cursor = conn.execute(query, params)
        results = []
        for row in cursor:
            result = dict(row)
            # Parse JSON fields
            result["missing_lines"] = (
                json.loads(result["missing_lines"]) if result["missing_lines"] else []
            )
            result["missing_branches"] = (
                json.loads(result["missing_branches"]) if result["missing_branches"] else []
            )
            results.append(result)
    except sqlite3.OperationalError:
        # Table doesn't exist
        results = []
    finally:
        conn.close()
    return results


def get_missing_lines(
    db_path: Path,
    file_path: str | None = None,
) -> list[dict[str, Any]]:
    """Query missing lines with source context.

    Args:
        db_path: Path to the .coverage database file
        file_path: Optional file path to filter by

    Returns:
        List of dictionaries with missing line details
    """
    conn = _get_connection(db_path)
    try:
        query = """
            SELECT
                file_path, line_number, content,
                context_before, context_after, missing_branch_exits
            FROM cc_missing_line
        """
        params = []

        if file_path is not None:
            query += " WHERE file_path = ?"
            params.append(file_path)

        query += " ORDER BY file_path, line_number"

        cursor = conn.execute(query, params)
        results = []
        for row in cursor:
            result = dict(row)
            # Parse JSON fields
            result["context_before"] = (
                json.loads(result["context_before"]) if result["context_before"] else []
            )
            result["context_after"] = (
                json.loads(result["context_after"]) if result["context_after"] else []
            )
            result["missing_branch_exits"] = (
                json.loads(result["missing_branch_exits"]) if result["missing_branch_exits"] else []
            )
            results.append(result)
    except sqlite3.OperationalError:
        # Table doesn't exist
        results = []
    finally:
        conn.close()
    return results


def get_usecase_coverage(db_path: Path) -> dict[str, Any]:
    """Query use case coverage statistics.

    Args:
        db_path: Path to the .coverage database file

    Returns:
        Dictionary with use case coverage details:
            - total: Total number of use cases
            - covered: Number of covered use cases
            - coverage_pct: Coverage percentage
            - by_tier: Dictionary of coverage by tier
            - uncovered: List of uncovered use case IDs
    """
    conn = _get_connection(db_path)
    try:
        # Get overall statistics
        cursor = conn.execute("""
            SELECT
                COUNT(*) as total,
                COALESCE(SUM(CASE WHEN cuc.covered = 1 THEN 1 ELSE 0 END), 0) as covered
            FROM cc_usecase cu
            LEFT JOIN cc_usecase_coverage cuc ON cu.usecase_id = cuc.usecase_id
        """)
        row = cursor.fetchone()
        total = row["total"] if row else 0
        covered = row["covered"] if row else 0
        coverage_pct = (covered / total * 100) if total > 0 else 0.0

        # Get coverage by tier
        cursor = conn.execute("""
            SELECT
                cu.test_tier,
                COUNT(*) as total,
                COALESCE(SUM(CASE WHEN cuc.covered = 1 THEN 1 ELSE 0 END), 0) as covered
            FROM cc_usecase cu
            LEFT JOIN cc_usecase_coverage cuc ON cu.usecase_id = cuc.usecase_id
            GROUP BY cu.test_tier
        """)
        by_tier = {}
        for row in cursor:
            tier = row["test_tier"]
            tier_total = row["total"]
            tier_covered = row["covered"]
            tier_pct = (tier_covered / tier_total * 100) if tier_total > 0 else 0.0
            by_tier[tier] = {
                "total": tier_total,
                "covered": tier_covered,
                "coverage_pct": tier_pct,
            }

        # Get uncovered use cases
        cursor = conn.execute("""
            SELECT cu.usecase_id
            FROM cc_usecase cu
            LEFT JOIN cc_usecase_coverage cuc ON cu.usecase_id = cuc.usecase_id
            WHERE cuc.covered IS NULL OR cuc.covered = 0
            ORDER BY cu.usecase_id
        """)
        uncovered = [row["usecase_id"] for row in cursor]
    except sqlite3.OperationalError:
        # Table doesn't exist
        return {
            "total": 0,
            "covered": 0,
            "coverage_pct": 0.0,
            "by_tier": {},
            "uncovered": [],
        }
    else:
        return {
            "total": total,
            "covered": covered,
            "coverage_pct": coverage_pct,
            "by_tier": by_tier,
            "uncovered": uncovered,
        }
    finally:
        conn.close()


def get_test_failures(
    db_path: Path,
    tier: str | None = None,
) -> list[dict[str, Any]]:
    """Query test failures and errors.

    Args:
        db_path: Path to the .coverage database file
        tier: Optional tier name to filter by

    Returns:
        List of dictionaries with test failure details
    """
    conn = _get_connection(db_path)
    try:
        query = """
            SELECT
                tier, test_name, status, duration, message, traceback
            FROM cc_test_result
            WHERE status IN ('failed', 'error')
        """
        params = []

        if tier is not None:
            query += " AND tier = ?"
            params.append(tier)

        query += " ORDER BY tier, test_name"

        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor]
    except sqlite3.OperationalError:
        # Table doesn't exist
        return []
    finally:
        conn.close()


def get_tier_summary(
    db_path: Path,
    tier: str | None = None,
) -> dict[str, Any]:
    """Query tier summary statistics.

    Args:
        db_path: Path to the .coverage database file
        tier: Optional tier name to filter by (returns specific tier or all tiers)

    Returns:
        Dictionary with tier summary data. If tier is specified, returns that tier's data.
        If tier is None, returns dictionary mapping tier names to their summaries.
    """
    conn = _get_connection(db_path)
    try:
        if tier is not None:
            # Get specific tier
            cursor = conn.execute(
                """
                SELECT
                    tier, coverage_type,
                    total_functions, passing_functions, failing_functions,
                    overall_line_pct, overall_branch_pct,
                    total_usecases, usecases_covered,
                    total_tests, tests_passed, tests_failed,
                    tier_pass
                FROM cc_tier_summary
                WHERE tier = ?
                """,
                (tier,),
            )
            row = cursor.fetchone()
            return dict(row) if row else {}
        else:
            # Get all tiers
            cursor = conn.execute("""
                SELECT
                    tier, coverage_type,
                    total_functions, passing_functions, failing_functions,
                    overall_line_pct, overall_branch_pct,
                    total_usecases, usecases_covered,
                    total_tests, tests_passed, tests_failed,
                    tier_pass
                FROM cc_tier_summary
                ORDER BY tier
            """)
            return {row["tier"]: dict(row) for row in cursor}
    except sqlite3.OperationalError:
        # Table doesn't exist
        return {}
    finally:
        conn.close()


def get_tier_config(db_path: Path, tier: str) -> dict[str, Any]:
    """Query tier configuration.

    Args:
        db_path: Path to the .coverage database file
        tier: Tier name (e.g., 'unit', 'integration')

    Returns:
        Dictionary with tier configuration details
    """
    conn = _get_connection(db_path)
    result: dict[str, Any] = {}
    try:
        cursor = conn.execute(
            """
            SELECT
                tier, coverage_type, test_path, source_paths,
                min_line_overall, min_branch_overall,
                min_line_per_function, min_branch_per_function,
                min_usecase, skip_private_functions, service_layer_only
            FROM cc_tier_config
            WHERE tier = ?
            """,
            (tier,),
        )
        row = cursor.fetchone()
        if row:
            result = dict(row)
            # Parse JSON field
            result["source_paths"] = (
                json.loads(result["source_paths"]) if result["source_paths"] else []
            )
            # Convert integers to booleans
            result["skip_private_functions"] = bool(result["skip_private_functions"])
            result["service_layer_only"] = bool(result["service_layer_only"])
    except sqlite3.OperationalError:
        # Table doesn't exist
        pass
    finally:
        conn.close()
    return result
