"""
Tests for coverage database operations.
"""

import json
import sqlite3
import tempfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from scripts.dev.test_runner.coverage_db import (
    clear_custom_tables,
    get_functions_below_threshold,
    get_missing_lines,
    get_test_failures,
    get_tier_config,
    get_tier_summary,
    get_usecase_coverage,
    init_custom_tables,
    write_function_coverage,
    write_missing_lines,
    write_run_metadata,
    write_test_result,
    write_tier_config,
    write_tier_summary,
    write_usecase_coverage,
    write_usecase_registry,
)
from scripts.dev.test_runner.test_coverage import (
    FunctionCoverage,
    MissingLineDetail,
    TestTierConfig,
    UseCase,
)


@pytest.fixture
def temp_db() -> Iterator[Path]:
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    try:
        yield db_path
    finally:
        if db_path.exists():
            db_path.unlink()


@pytest.fixture
def initialized_db(temp_db: Path) -> Iterator[Path]:
    """Create and initialize a temporary database."""
    init_custom_tables(temp_db)
    return temp_db  # type: ignore[return-value]


class TestTableCreation:
    """Tests for table creation and initialization."""

    def test_init_custom_tables_creates_all_tables(self, temp_db: Path) -> None:
        """Test that init_custom_tables creates all required tables."""
        init_custom_tables(temp_db)

        # Verify tables exist
        conn = sqlite3.connect(str(temp_db))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'cc_%'"
        )
        table_names = {row[0] for row in cursor.fetchall()}
        conn.close()

        expected_tables = {
            "cc_run_metadata",
            "cc_tier_config",
            "cc_function_coverage",
            "cc_missing_line",
            "cc_usecase",
            "cc_usecase_coverage",
            "cc_test_result",
            "cc_tier_summary",
        }
        assert table_names == expected_tables

    def test_init_custom_tables_idempotent(self, temp_db: Path) -> None:
        """Test that calling init_custom_tables multiple times is safe."""
        init_custom_tables(temp_db)
        init_custom_tables(temp_db)  # Should not raise

        # Verify tables still exist
        conn = sqlite3.connect(str(temp_db))
        cursor = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'cc_%'"
        )
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 8

    def test_clear_custom_tables(self, initialized_db: Path) -> None:
        """Test that clear_custom_tables removes all data."""
        # Add some data
        write_run_metadata(initialized_db, Path("/test/repo"))

        tier_config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            coverage_type="line_branch",
        )
        write_tier_config(initialized_db, "unit", tier_config)

        # Clear tables
        clear_custom_tables(initialized_db)

        # Verify data is gone
        conn = sqlite3.connect(str(initialized_db))

        cursor = conn.execute("SELECT COUNT(*) FROM cc_run_metadata")
        assert cursor.fetchone()[0] == 0

        cursor = conn.execute("SELECT COUNT(*) FROM cc_tier_config")
        assert cursor.fetchone()[0] == 0

        conn.close()

    def test_clear_custom_tables_with_missing_tables(self, temp_db: Path) -> None:
        """Test that clear_custom_tables handles missing tables gracefully."""
        # Don't initialize tables
        clear_custom_tables(temp_db)  # Should not raise


class TestRunMetadata:
    """Tests for run metadata operations."""

    def test_write_run_metadata(self, initialized_db: Path) -> None:
        """Test writing run metadata."""
        repo_root = Path("/test/repo")
        write_run_metadata(initialized_db, repo_root)

        # Verify data
        conn = sqlite3.connect(str(initialized_db))
        cursor = conn.execute("SELECT * FROM cc_run_metadata")
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 1  # id
        assert row[2] == str(repo_root)  # repo_root

        # Verify generated_at is a valid ISO timestamp
        generated_at = datetime.fromisoformat(row[1])
        assert generated_at.tzinfo is not None

    def test_write_run_metadata_replaces_existing(self, initialized_db: Path) -> None:
        """Test that writing run metadata replaces existing data."""
        write_run_metadata(initialized_db, Path("/old/repo"))
        write_run_metadata(initialized_db, Path("/new/repo"))

        # Verify only one row exists
        conn = sqlite3.connect(str(initialized_db))
        cursor = conn.execute("SELECT COUNT(*) FROM cc_run_metadata")
        count = cursor.fetchone()[0]
        assert count == 1

        cursor = conn.execute("SELECT repo_root FROM cc_run_metadata")
        repo_root = cursor.fetchone()[0]
        conn.close()

        assert repo_root == "/new/repo"


class TestTierConfigOps:
    """Tests for tier configuration operations."""

    def test_write_tier_config(self, initialized_db: Path) -> None:
        """Test writing tier configuration."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app", "scripts"],
            coverage_type="line_branch",
            min_line_overall=80.0,
            min_branch_overall=70.0,
            min_line_per_function=75.0,
            min_branch_per_function=65.0,
            skip_private_functions=True,
            service_layer_only=False,
        )
        write_tier_config(initialized_db, "unit", config)

        # Verify data
        conn = sqlite3.connect(str(initialized_db))
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM cc_tier_config WHERE tier = ?", ("unit",))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row["tier"] == "unit"
        assert row["coverage_type"] == "line_branch"
        assert row["test_path"] == "tests/unit"
        assert json.loads(row["source_paths"]) == ["app", "scripts"]
        assert row["min_line_overall"] == 80.0
        assert row["min_branch_overall"] == 70.0
        assert row["min_line_per_function"] == 75.0
        assert row["min_branch_per_function"] == 65.0
        assert row["skip_private_functions"] == 1
        assert row["service_layer_only"] == 0

    def test_get_tier_config(self, initialized_db: Path) -> None:
        """Test retrieving tier configuration."""
        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            coverage_type="usecase",
            min_usecase=90.0,
        )
        write_tier_config(initialized_db, "integration", config)

        result = get_tier_config(initialized_db, "integration")

        assert result["tier"] == "integration"
        assert result["coverage_type"] == "usecase"
        assert result["test_path"] == "tests/integration"
        assert result["source_paths"] == ["app"]
        assert result["min_usecase"] == 90.0
        assert result["skip_private_functions"] is False
        assert result["service_layer_only"] is False

    def test_get_tier_config_not_found(self, initialized_db: Path) -> None:
        """Test retrieving non-existent tier configuration."""
        result = get_tier_config(initialized_db, "nonexistent")
        assert result == {}

    def test_get_tier_config_missing_table(self, temp_db: Path) -> None:
        """Test retrieving tier config when table doesn't exist."""
        result = get_tier_config(temp_db, "unit")
        assert result == {}


class TestFunctionCoverage:
    """Tests for function coverage operations."""

    def test_write_function_coverage(self, initialized_db: Path) -> None:
        """Test writing function coverage data."""
        functions = [
            FunctionCoverage(
                name="test_func",
                file_path="app/main.py",
                start_line=10,
                end_line=20,
                total_lines=10,
                covered_lines=8,
                missing_lines=[12, 15],
                line_coverage_pct=80.0,
                total_branches=4,
                covered_branches=3,
                missing_branches=[(12, 13)],
                branch_coverage_pct=75.0,
            ),
            FunctionCoverage(
                name="another_func",
                file_path="app/utils.py",
                start_line=5,
                end_line=15,
                total_lines=10,
                covered_lines=10,
                missing_lines=[],
                line_coverage_pct=100.0,
                total_branches=2,
                covered_branches=2,
                missing_branches=[],
                branch_coverage_pct=100.0,
            ),
        ]

        write_function_coverage(
            initialized_db,
            tier="unit",
            functions=functions,
            threshold_line=85.0,
            threshold_branch=80.0,
        )

        # Verify data
        conn = sqlite3.connect(str(initialized_db))
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM cc_function_coverage ORDER BY function_name")
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) == 2

        # Check first function (another_func)
        assert rows[0]["function_name"] == "another_func"
        assert rows[0]["file_path"] == "app/utils.py"
        assert rows[0]["tier"] == "unit"
        assert rows[0]["line_coverage_pct"] == 100.0
        assert rows[0]["branch_coverage_pct"] == 100.0
        assert rows[0]["threshold_line"] == 85.0
        assert rows[0]["threshold_branch"] == 80.0
        assert rows[0]["line_pass"] == 1  # 100.0 >= 85.0
        assert rows[0]["branch_pass"] == 1  # 100.0 >= 80.0
        assert json.loads(rows[0]["missing_lines"]) == []
        assert json.loads(rows[0]["missing_branches"]) == []

        # Check second function (test_func)
        assert rows[1]["function_name"] == "test_func"
        assert rows[1]["file_path"] == "app/main.py"
        assert rows[1]["line_pass"] == 0  # 80.0 < 85.0
        assert rows[1]["branch_pass"] == 0  # 75.0 < 80.0
        assert json.loads(rows[1]["missing_lines"]) == [12, 15]
        assert json.loads(rows[1]["missing_branches"]) == [[12, 13]]

    def test_write_function_coverage_replaces_existing(self, initialized_db: Path) -> None:
        """Test that writing function coverage replaces existing data."""
        func1 = FunctionCoverage(
            name="test_func",
            file_path="app/main.py",
            start_line=10,
            end_line=20,
            total_lines=10,
            covered_lines=5,
            missing_lines=[11, 12, 13, 14, 15],
            line_coverage_pct=50.0,
            total_branches=0,
            covered_branches=0,
            missing_branches=[],
            branch_coverage_pct=0.0,
        )

        write_function_coverage(
            initialized_db,
            tier="unit",
            functions=[func1],
            threshold_line=70.0,
            threshold_branch=70.0,
        )

        # Update with better coverage
        func2 = FunctionCoverage(
            name="test_func",
            file_path="app/main.py",
            start_line=10,
            end_line=20,
            total_lines=10,
            covered_lines=9,
            missing_lines=[15],
            line_coverage_pct=90.0,
            total_branches=0,
            covered_branches=0,
            missing_branches=[],
            branch_coverage_pct=0.0,
        )

        write_function_coverage(
            initialized_db,
            tier="unit",
            functions=[func2],
            threshold_line=70.0,
            threshold_branch=70.0,
        )

        # Verify only one row exists with updated data
        conn = sqlite3.connect(str(initialized_db))
        cursor = conn.execute(
            """
            SELECT COUNT(*) FROM cc_function_coverage
            WHERE file_path = ? AND function_name = ? AND tier = ?
            """,
            ("app/main.py", "test_func", "unit"),
        )
        count = cursor.fetchone()[0]
        assert count == 1

        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT * FROM cc_function_coverage
            WHERE file_path = ? AND function_name = ? AND tier = ?
            """,
            ("app/main.py", "test_func", "unit"),
        )
        row = cursor.fetchone()
        conn.close()

        assert row["line_coverage_pct"] == 90.0
        assert json.loads(row["missing_lines"]) == [15]

    def test_get_functions_below_threshold(self, initialized_db: Path) -> None:
        """Test querying functions below threshold."""
        functions = [
            FunctionCoverage(
                name="good_func",
                file_path="app/good.py",
                start_line=1,
                end_line=10,
                total_lines=10,
                covered_lines=10,
                missing_lines=[],
                line_coverage_pct=100.0,
                total_branches=2,
                covered_branches=2,
                missing_branches=[],
                branch_coverage_pct=100.0,
            ),
            FunctionCoverage(
                name="bad_line_func",
                file_path="app/bad.py",
                start_line=1,
                end_line=10,
                total_lines=10,
                covered_lines=6,
                missing_lines=[5, 6, 7, 8],
                line_coverage_pct=60.0,
                total_branches=2,
                covered_branches=2,
                missing_branches=[],
                branch_coverage_pct=100.0,
            ),
            FunctionCoverage(
                name="bad_branch_func",
                file_path="app/bad.py",
                start_line=20,
                end_line=30,
                total_lines=10,
                covered_lines=10,
                missing_lines=[],
                line_coverage_pct=100.0,
                total_branches=4,
                covered_branches=2,
                missing_branches=[(22, 23), (25, 26)],
                branch_coverage_pct=50.0,
            ),
        ]

        write_function_coverage(
            initialized_db,
            tier="unit",
            functions=functions,
            threshold_line=80.0,
            threshold_branch=80.0,
        )

        # Query all functions below threshold
        results = get_functions_below_threshold(initialized_db)
        assert len(results) == 2

        # Verify bad_line_func
        bad_line = next(f for f in results if f["function_name"] == "bad_line_func")
        assert bad_line["line_pass"] == 0
        assert bad_line["branch_pass"] == 1
        assert bad_line["line_coverage_pct"] == 60.0
        assert bad_line["missing_lines"] == [5, 6, 7, 8]

        # Verify bad_branch_func
        bad_branch = next(f for f in results if f["function_name"] == "bad_branch_func")
        assert bad_branch["line_pass"] == 1
        assert bad_branch["branch_pass"] == 0
        assert bad_branch["branch_coverage_pct"] == 50.0
        assert bad_branch["missing_branches"] == [[22, 23], [25, 26]]

    def test_get_functions_below_threshold_with_tier_filter(self, initialized_db: Path) -> None:
        """Test filtering functions by tier."""
        func = FunctionCoverage(
            name="test_func",
            file_path="app/main.py",
            start_line=1,
            end_line=10,
            total_lines=10,
            covered_lines=5,
            missing_lines=[6, 7, 8, 9, 10],
            line_coverage_pct=50.0,
            total_branches=0,
            covered_branches=0,
            missing_branches=[],
            branch_coverage_pct=0.0,
        )

        write_function_coverage(
            initialized_db,
            tier="unit",
            functions=[func],
            threshold_line=80.0,
            threshold_branch=80.0,
        )
        write_function_coverage(
            initialized_db,
            tier="integration",
            functions=[func],
            threshold_line=80.0,
            threshold_branch=80.0,
        )

        # Query only unit tier
        results = get_functions_below_threshold(initialized_db, tier="unit")
        assert len(results) == 1
        assert results[0]["tier"] == "unit"

    def test_get_functions_below_threshold_with_file_filter(self, initialized_db: Path) -> None:
        """Test filtering functions by file path."""
        functions = [
            FunctionCoverage(
                name="func1",
                file_path="app/services/user.py",
                start_line=1,
                end_line=10,
                total_lines=10,
                covered_lines=5,
                missing_lines=[6, 7, 8, 9, 10],
                line_coverage_pct=50.0,
                total_branches=0,
                covered_branches=0,
                missing_branches=[],
                branch_coverage_pct=0.0,
            ),
            FunctionCoverage(
                name="func2",
                file_path="app/utils/helpers.py",
                start_line=1,
                end_line=10,
                total_lines=10,
                covered_lines=5,
                missing_lines=[6, 7, 8, 9, 10],
                line_coverage_pct=50.0,
                total_branches=0,
                covered_branches=0,
                missing_branches=[],
                branch_coverage_pct=0.0,
            ),
        ]

        write_function_coverage(
            initialized_db,
            tier="unit",
            functions=functions,
            threshold_line=80.0,
            threshold_branch=80.0,
        )

        # Query only services
        results = get_functions_below_threshold(initialized_db, file_filter="services")
        assert len(results) == 1
        assert "services" in results[0]["file_path"]

    def test_get_functions_below_threshold_missing_table(self, temp_db: Path) -> None:
        """Test querying when table doesn't exist."""
        results = get_functions_below_threshold(temp_db)
        assert results == []


class TestMissingLines:
    """Tests for missing lines operations."""

    def test_write_missing_lines(self, initialized_db: Path) -> None:
        """Test writing missing line details."""
        missing_lines = [
            MissingLineDetail(
                file="app/main.py",
                line_number=15,
                content="    return None",
                context_before=[
                    {"line_number": 13, "content": "def test():"},
                    {"line_number": 14, "content": "    if False:"},
                ],
                context_after=[
                    {"line_number": 16, "content": "    else:"},
                    {"line_number": 17, "content": "        return True"},
                ],
                missing_branch_exits=[16],
            ),
            MissingLineDetail(
                file="app/utils.py",
                line_number=42,
                content="    raise Exception()",
                context_before=[{"line_number": 41, "content": "    if error:"}],
                context_after=[{"line_number": 43, "content": ""}],
                missing_branch_exits=[],
            ),
        ]

        write_missing_lines(initialized_db, missing_lines)

        # Verify data
        results = get_missing_lines(initialized_db)
        assert len(results) == 2

        # Check first missing line
        line1 = results[0]
        assert line1["file_path"] == "app/main.py"
        assert line1["line_number"] == 15
        assert line1["content"] == "    return None"
        assert len(line1["context_before"]) == 2
        assert line1["context_before"][0]["line_number"] == 13
        assert len(line1["context_after"]) == 2
        assert line1["missing_branch_exits"] == [16]

        # Check second missing line
        line2 = results[1]
        assert line2["file_path"] == "app/utils.py"
        assert line2["line_number"] == 42
        assert line2["missing_branch_exits"] == []

    def test_get_missing_lines_with_file_filter(self, initialized_db: Path) -> None:
        """Test filtering missing lines by file path."""
        missing_lines = [
            MissingLineDetail(
                file="app/main.py",
                line_number=15,
                content="return None",
                context_before=[],
                context_after=[],
                missing_branch_exits=[],
            ),
            MissingLineDetail(
                file="app/utils.py",
                line_number=42,
                content="raise Exception()",
                context_before=[],
                context_after=[],
                missing_branch_exits=[],
            ),
        ]

        write_missing_lines(initialized_db, missing_lines)

        # Query only main.py
        results = get_missing_lines(initialized_db, file_path="app/main.py")
        assert len(results) == 1
        assert results[0]["file_path"] == "app/main.py"

    def test_get_missing_lines_missing_table(self, temp_db: Path) -> None:
        """Test querying when table doesn't exist."""
        results = get_missing_lines(temp_db)
        assert results == []


class TestUseCases:
    """Tests for use case operations."""

    def test_write_usecase_registry(self, initialized_db: Path) -> None:
        """Test writing use case definitions."""
        usecases = [
            UseCase(
                id="UC-API-001",
                endpoint="/api/users",
                method="GET",
                description="List all users",
                test_tier="integration",
            ),
            UseCase(
                id="UC-API-002",
                endpoint="/api/users/{id}",
                method="GET",
                description="Get user by ID",
                test_tier="integration",
            ),
        ]

        write_usecase_registry(initialized_db, usecases)

        # Verify data
        conn = sqlite3.connect(str(initialized_db))
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM cc_usecase ORDER BY usecase_id")
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) == 2
        assert rows[0]["usecase_id"] == "UC-API-001"
        assert rows[0]["endpoint"] == "/api/users"
        assert rows[0]["method"] == "GET"
        assert rows[0]["test_tier"] == "integration"

    def test_write_usecase_coverage(self, initialized_db: Path) -> None:
        """Test writing use case coverage status."""
        # First register use cases
        usecases = [
            UseCase(
                id="UC-API-001",
                endpoint="/api/users",
                method="GET",
                description="List all users",
                test_tier="integration",
            ),
        ]
        write_usecase_registry(initialized_db, usecases)

        # Write coverage
        write_usecase_coverage(
            initialized_db,
            usecase_id="UC-API-001",
            covered=True,
            test_file="tests/integration/test_users.py",
            test_function="test_list_users",
        )

        # Verify data
        conn = sqlite3.connect(str(initialized_db))
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT * FROM cc_usecase_coverage WHERE usecase_id = ?", ("UC-API-001",)
        )
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row["covered"] == 1
        assert row["test_file"] == "tests/integration/test_users.py"
        assert row["test_function"] == "test_list_users"

    def test_get_usecase_coverage(self, initialized_db: Path) -> None:
        """Test querying use case coverage statistics."""
        # Register use cases
        usecases = [
            UseCase(
                id="UC-API-001",
                endpoint="/api/users",
                method="GET",
                description="List users",
                test_tier="integration",
            ),
            UseCase(
                id="UC-API-002",
                endpoint="/api/users/{id}",
                method="GET",
                description="Get user",
                test_tier="integration",
            ),
            UseCase(
                id="UC-API-003",
                endpoint="/api/users",
                method="POST",
                description="Create user",
                test_tier="e2e",
            ),
        ]
        write_usecase_registry(initialized_db, usecases)

        # Mark some as covered
        write_usecase_coverage(
            initialized_db,
            usecase_id="UC-API-001",
            covered=True,
            test_file="tests/integration/test_users.py",
            test_function="test_list",
        )
        write_usecase_coverage(
            initialized_db,
            usecase_id="UC-API-002",
            covered=False,
        )
        write_usecase_coverage(
            initialized_db,
            usecase_id="UC-API-003",
            covered=True,
            test_file="tests/e2e/test_users.py",
            test_function="test_create",
        )

        # Query coverage
        result = get_usecase_coverage(initialized_db)

        assert result["total"] == 3
        assert result["covered"] == 2
        assert result["coverage_pct"] == pytest.approx(66.67, rel=0.01)
        assert "UC-API-002" in result["uncovered"]
        assert len(result["uncovered"]) == 1

    def test_get_usecase_coverage_missing_table(self, temp_db: Path) -> None:
        """Test querying when table doesn't exist."""
        result = get_usecase_coverage(temp_db)
        assert result["total"] == 0
        assert result["covered"] == 0
        assert result["coverage_pct"] == 0.0
        assert result["by_tier"] == {}
        assert result["uncovered"] == []


class TestTestResults:
    """Tests for test result operations."""

    def test_write_test_result(self, initialized_db: Path) -> None:
        """Test writing test execution results."""
        write_test_result(
            initialized_db,
            tier="unit",
            test_name="tests/unit/test_main.py::test_success",
            status="passed",
            duration=0.123,
        )

        write_test_result(
            initialized_db,
            tier="unit",
            test_name="tests/unit/test_main.py::test_failure",
            status="failed",
            duration=0.456,
            message="AssertionError: expected True",
            traceback="Traceback...",
        )

        # Verify data
        conn = sqlite3.connect(str(initialized_db))
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM cc_test_result ORDER BY test_name")
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) == 2

        # Check failure
        assert rows[0]["status"] == "failed"
        assert rows[0]["message"] == "AssertionError: expected True"
        assert rows[0]["traceback"] == "Traceback..."
        assert rows[0]["duration"] == 0.456

        # Check success
        assert rows[1]["status"] == "passed"
        assert rows[1]["message"] is None
        assert rows[1]["duration"] == 0.123

    def test_get_test_failures(self, initialized_db: Path) -> None:
        """Test querying test failures."""
        write_test_result(
            initialized_db,
            tier="unit",
            test_name="test_pass",
            status="passed",
            duration=0.1,
        )

        write_test_result(
            initialized_db,
            tier="unit",
            test_name="test_fail",
            status="failed",
            duration=0.2,
            message="Failed",
        )

        write_test_result(
            initialized_db,
            tier="integration",
            test_name="test_error",
            status="error",
            duration=0.3,
            message="Error occurred",
            traceback="Traceback...",
        )

        # Query all failures
        results = get_test_failures(initialized_db)
        assert len(results) == 2

        # Query by tier
        unit_failures = get_test_failures(initialized_db, tier="unit")
        assert len(unit_failures) == 1
        assert unit_failures[0]["test_name"] == "test_fail"

    def test_get_test_failures_missing_table(self, temp_db: Path) -> None:
        """Test querying when table doesn't exist."""
        results = get_test_failures(temp_db)
        assert results == []


class TestTierSummary:
    """Tests for tier summary operations."""

    def test_write_tier_summary(self, initialized_db: Path) -> None:
        """Test writing tier summary statistics."""
        summary = {
            "coverage_type": "line_branch",
            "total_functions": 100,
            "passing_functions": 85,
            "failing_functions": 15,
            "overall_line_pct": 87.5,
            "overall_branch_pct": 82.3,
            "total_tests": 50,
            "tests_passed": 48,
            "tests_failed": 2,
            "tier_pass": 0,  # Has failures
        }

        write_tier_summary(initialized_db, "unit", summary)

        # Verify data
        result = get_tier_summary(initialized_db, tier="unit")

        assert result["tier"] == "unit"
        assert result["coverage_type"] == "line_branch"
        assert result["total_functions"] == 100
        assert result["passing_functions"] == 85
        assert result["failing_functions"] == 15
        assert result["overall_line_pct"] == 87.5
        assert result["overall_branch_pct"] == 82.3
        assert result["total_tests"] == 50
        assert result["tests_passed"] == 48
        assert result["tests_failed"] == 2
        assert result["tier_pass"] == 0

    def test_get_tier_summary_all_tiers(self, initialized_db: Path) -> None:
        """Test getting all tier summaries."""
        unit_summary = {
            "coverage_type": "line_branch",
            "total_functions": 50,
            "passing_functions": 50,
            "failing_functions": 0,
            "tier_pass": 1,
        }
        integration_summary = {
            "coverage_type": "usecase",
            "total_usecases": 20,
            "usecases_covered": 18,
            "tier_pass": 0,
        }

        write_tier_summary(initialized_db, "unit", unit_summary)
        write_tier_summary(initialized_db, "integration", integration_summary)

        # Get all tiers
        results = get_tier_summary(initialized_db)

        assert len(results) == 2
        assert "unit" in results
        assert "integration" in results
        assert results["unit"]["tier_pass"] == 1
        assert results["integration"]["tier_pass"] == 0

    def test_get_tier_summary_missing_table(self, temp_db: Path) -> None:
        """Test querying when table doesn't exist."""
        result = get_tier_summary(temp_db, tier="unit")
        assert result == {}


class TestPassFailCalculation:
    """Tests for pass/fail flag calculation logic."""

    def test_function_line_pass_calculation(self, initialized_db: Path) -> None:
        """Test that line_pass is calculated correctly."""
        functions = [
            FunctionCoverage(
                name="at_threshold",
                file_path="app/test.py",
                start_line=1,
                end_line=10,
                total_lines=10,
                covered_lines=8,
                missing_lines=[9, 10],
                line_coverage_pct=80.0,
                total_branches=0,
                covered_branches=0,
                missing_branches=[],
                branch_coverage_pct=0.0,
            ),
            FunctionCoverage(
                name="above_threshold",
                file_path="app/test.py",
                start_line=20,
                end_line=30,
                total_lines=10,
                covered_lines=9,
                missing_lines=[30],
                line_coverage_pct=90.0,
                total_branches=0,
                covered_branches=0,
                missing_branches=[],
                branch_coverage_pct=0.0,
            ),
            FunctionCoverage(
                name="below_threshold",
                file_path="app/test.py",
                start_line=40,
                end_line=50,
                total_lines=10,
                covered_lines=7,
                missing_lines=[48, 49, 50],
                line_coverage_pct=70.0,
                total_branches=0,
                covered_branches=0,
                missing_branches=[],
                branch_coverage_pct=0.0,
            ),
        ]

        write_function_coverage(
            initialized_db,
            tier="unit",
            functions=functions,
            threshold_line=80.0,
            threshold_branch=0.0,
        )

        # Query results
        conn = sqlite3.connect(str(initialized_db))
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT function_name, line_coverage_pct, line_pass
            FROM cc_function_coverage ORDER BY function_name
            """
        )
        rows = cursor.fetchall()
        conn.close()

        # Results are ordered alphabetically by function_name
        # above_threshold: 90.0 >= 80.0 -> pass
        assert rows[0]["function_name"] == "above_threshold"
        assert rows[0]["line_pass"] == 1

        # at_threshold: 80.0 >= 80.0 -> pass
        assert rows[1]["function_name"] == "at_threshold"
        assert rows[1]["line_pass"] == 1

        # below_threshold: 70.0 < 80.0 -> fail
        assert rows[2]["function_name"] == "below_threshold"
        assert rows[2]["line_pass"] == 0

    def test_function_branch_pass_calculation(self, initialized_db: Path) -> None:
        """Test that branch_pass is calculated correctly."""
        functions = [
            FunctionCoverage(
                name="good_branches",
                file_path="app/test.py",
                start_line=1,
                end_line=10,
                total_lines=10,
                covered_lines=10,
                missing_lines=[],
                line_coverage_pct=100.0,
                total_branches=4,
                covered_branches=4,
                missing_branches=[],
                branch_coverage_pct=100.0,
            ),
            FunctionCoverage(
                name="bad_branches",
                file_path="app/test.py",
                start_line=20,
                end_line=30,
                total_lines=10,
                covered_lines=10,
                missing_lines=[],
                line_coverage_pct=100.0,
                total_branches=4,
                covered_branches=2,
                missing_branches=[(22, 23), (25, 26)],
                branch_coverage_pct=50.0,
            ),
        ]

        write_function_coverage(
            initialized_db,
            tier="unit",
            functions=functions,
            threshold_line=0.0,
            threshold_branch=75.0,
        )

        # Query results
        conn = sqlite3.connect(str(initialized_db))
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT function_name, branch_coverage_pct, branch_pass
            FROM cc_function_coverage ORDER BY function_name
            """
        )
        rows = cursor.fetchall()
        conn.close()

        # bad_branches: 50.0 < 75.0 -> fail
        assert rows[0]["function_name"] == "bad_branches"
        assert rows[0]["branch_pass"] == 0

        # good_branches: 100.0 >= 75.0 -> pass
        assert rows[1]["function_name"] == "good_branches"
        assert rows[1]["branch_pass"] == 1
