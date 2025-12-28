import json
import sqlite3
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from scripts.dev.test_runner.batch_coverage_gaps import (
    FailingFunction,
    create_batches,
    get_test_file_path,
    group_by_test_file,
    main,
    query_failing_functions,
    write_batch_file,
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
def initialized_db(temp_db: Path) -> Path:
    """Create and initialize a temporary database with required schema."""
    conn = sqlite3.connect(temp_db)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cc_function_coverage (
            file_path TEXT,
            function_name TEXT,
            tier TEXT,
            line_coverage_pct REAL,
            branch_coverage_pct REAL,
            threshold_line REAL,
            threshold_branch REAL,
            missing_lines TEXT,
            missing_branches TEXT,
            line_pass INTEGER,
            branch_pass INTEGER
        )
    """)
    conn.commit()
    conn.close()
    return temp_db


class TestFailingFunctionDataclass:
    def test_test_file_path_property_for_scripts_tier(self) -> None:
        """Test that test_file_path property correctly maps scripts tier."""
        func = FailingFunction(
            file_path="scripts/dev/test_runner/coverage.py",
            function_name="test_func",
            tier="scripts",
            line_coverage_pct=50.0,
            branch_coverage_pct=50.0,
            threshold_line=80.0,
            threshold_branch=70.0,
            missing_lines="[1, 2]",
            missing_branches="[[1, 2]]",
        )
        assert func.test_file_path == "scripts/tests/test_runner/test_coverage.py"

    def test_test_file_path_property_for_unit_tier(self) -> None:
        """Test that test_file_path property correctly maps unit tier."""
        func = FailingFunction(
            file_path="app/core/factory.py",
            function_name="test_func",
            tier="unit",
            line_coverage_pct=50.0,
            branch_coverage_pct=50.0,
            threshold_line=80.0,
            threshold_branch=70.0,
            missing_lines="[]",
            missing_branches="[]",
        )
        assert func.test_file_path == "tests/unit/test_factory.py"


class TestGetTestFilePath:
    def test_unit_tier_simple_path(self) -> None:
        """Test mapping for unit tier with simple path."""
        result = get_test_file_path("app/core/factory.py", "unit")
        assert result == "tests/unit/test_factory.py"

    def test_unit_tier_infrastructure_path(self) -> None:
        """Test mapping for unit tier with infrastructure path."""
        result = get_test_file_path("app/infrastructure/duckdb/client.py", "unit")
        assert result == "tests/unit/test_duckdb_client.py"

    def test_unit_tier_infrastructure_no_subdir(self) -> None:
        """Test mapping for unit tier with infrastructure but no subdirectory."""
        result = get_test_file_path("app/infrastructure/client.py", "unit")
        assert result == "tests/unit/test_client.py"

    def test_component_tier_simple_path(self) -> None:
        """Test mapping for component tier (same as unit)."""
        result = get_test_file_path("app/services/auth.py", "component")
        assert result == "tests/unit/test_auth.py"

    def test_scripts_tier_dev_path(self) -> None:
        """Test mapping for scripts tier with dev path."""
        result = get_test_file_path("scripts/dev/test_runner/coverage.py", "scripts")
        assert result == "scripts/tests/test_runner/test_coverage.py"

    def test_scripts_tier_without_dev(self) -> None:
        """Test mapping for scripts tier without dev subdirectory."""
        result = get_test_file_path("scripts/knowledge/fact_store.py", "scripts")
        assert result == "scripts/tests/knowledge/test_fact_store.py"

    def test_scripts_tier_flat_path(self) -> None:
        """Test mapping for scripts tier with flat path."""
        result = get_test_file_path("scripts/some_script.py", "scripts")
        assert result == "scripts/tests/test_some_script.py"

    def test_scripts_tier_non_scripts_path(self) -> None:
        """Test mapping for scripts tier with non-scripts path."""
        result = get_test_file_path("other/module.py", "scripts")
        assert result == "scripts/tests/test_module.py"

    def test_unknown_tier(self) -> None:
        """Test mapping for unknown tier."""
        result = get_test_file_path("app/core/factory.py", "unknown")
        assert result == "tests/test_factory.py"

    def test_scripts_tier_deep_dev_path(self) -> None:
        """Test mapping for scripts tier with deep dev path."""
        result = get_test_file_path("scripts/dev/linter/base.py", "scripts")
        assert result == "scripts/tests/linter/test_base.py"

    def test_scripts_tier_empty_remaining(self) -> None:
        """Test mapping for scripts tier with only 'scripts' directory."""
        # When path is just "scripts" with no subdirectories
        result = get_test_file_path("scripts/main.py", "scripts")
        assert result == "scripts/tests/test_main.py"

    def test_component_tier_infrastructure_path(self) -> None:
        """Test mapping for component tier with infrastructure path."""
        result = get_test_file_path("app/infrastructure/redis/cache.py", "component")
        assert result == "tests/unit/test_redis_cache.py"


class TestQueryFailingFunctions:
    def test_query_with_no_failing_functions(self, initialized_db: Path) -> None:
        """Test query when all functions pass."""
        # Add a passing function
        conn = sqlite3.connect(initialized_db)
        conn.execute(
            """
            INSERT INTO cc_function_coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "app/main.py",
                "good_func",
                "unit",
                100.0,
                100.0,
                80.0,
                70.0,
                "[]",
                "[]",
                1,
                1,
            ),
        )
        conn.commit()
        conn.close()

        result = query_failing_functions(initialized_db)
        assert result == []

    def test_query_with_failing_functions(self, initialized_db: Path) -> None:
        """Test query when there are failing functions."""
        conn = sqlite3.connect(initialized_db)
        conn.execute(
            """
            INSERT INTO cc_function_coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "app/main.py",
                "bad_func",
                "unit",
                50.0,
                60.0,
                80.0,
                70.0,
                "[1, 2, 3]",
                "[[1, 2]]",
                0,
                0,
            ),
        )
        conn.commit()
        conn.close()

        result = query_failing_functions(initialized_db)
        assert len(result) == 1
        assert result[0].file_path == "app/main.py"
        assert result[0].function_name == "bad_func"
        assert result[0].tier == "unit"
        assert result[0].line_coverage_pct == 50.0
        assert result[0].branch_coverage_pct == 60.0
        assert result[0].missing_lines == "[1, 2, 3]"
        assert result[0].missing_branches == "[[1, 2]]"

    def test_query_with_tier_filter(self, initialized_db: Path) -> None:
        """Test query with tier filter."""
        conn = sqlite3.connect(initialized_db)
        # Insert failing functions in different tiers
        conn.execute(
            """
            INSERT INTO cc_function_coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("app/main.py", "func1", "unit", 50.0, 50.0, 80.0, 70.0, "[]", "[]", 0, 0),
        )
        conn.execute(
            """
            INSERT INTO cc_function_coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "scripts/test.py",
                "func2",
                "scripts",
                50.0,
                50.0,
                80.0,
                70.0,
                "[]",
                "[]",
                0,
                0,
            ),
        )
        conn.commit()
        conn.close()

        result = query_failing_functions(initialized_db, tier="unit")
        assert len(result) == 1
        assert result[0].tier == "unit"

    def test_query_handles_null_missing_lines(self, initialized_db: Path) -> None:
        """Test query handles NULL missing_lines gracefully."""
        conn = sqlite3.connect(initialized_db)
        conn.execute(
            """
            INSERT INTO cc_function_coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "app/main.py",
                "bad_func",
                "unit",
                50.0,
                60.0,
                80.0,
                70.0,
                None,  # NULL missing_lines
                None,  # NULL missing_branches
                0,
                0,
            ),
        )
        conn.commit()
        conn.close()

        result = query_failing_functions(initialized_db)
        assert len(result) == 1
        assert result[0].missing_lines == "[]"
        assert result[0].missing_branches == "[]"


class TestGroupByTestFile:
    def test_group_single_function(self) -> None:
        """Test grouping a single function."""
        functions = [
            FailingFunction(
                file_path="app/main.py",
                function_name="func1",
                tier="unit",
                line_coverage_pct=50.0,
                branch_coverage_pct=50.0,
                threshold_line=80.0,
                threshold_branch=70.0,
                missing_lines="[]",
                missing_branches="[]",
            )
        ]
        result = group_by_test_file(functions)
        assert len(result) == 1
        assert "tests/unit/test_main.py" in result
        assert len(result["tests/unit/test_main.py"]) == 1

    def test_group_multiple_functions_same_file(self) -> None:
        """Test grouping multiple functions mapping to same test file."""
        functions = [
            FailingFunction(
                file_path="app/main.py",
                function_name="func1",
                tier="unit",
                line_coverage_pct=50.0,
                branch_coverage_pct=50.0,
                threshold_line=80.0,
                threshold_branch=70.0,
                missing_lines="[]",
                missing_branches="[]",
            ),
            FailingFunction(
                file_path="app/main.py",
                function_name="func2",
                tier="unit",
                line_coverage_pct=60.0,
                branch_coverage_pct=60.0,
                threshold_line=80.0,
                threshold_branch=70.0,
                missing_lines="[]",
                missing_branches="[]",
            ),
        ]
        result = group_by_test_file(functions)
        assert len(result) == 1
        assert len(result["tests/unit/test_main.py"]) == 2

    def test_group_multiple_functions_different_files(self) -> None:
        """Test grouping functions mapping to different test files."""
        functions = [
            FailingFunction(
                file_path="app/main.py",
                function_name="func1",
                tier="unit",
                line_coverage_pct=50.0,
                branch_coverage_pct=50.0,
                threshold_line=80.0,
                threshold_branch=70.0,
                missing_lines="[]",
                missing_branches="[]",
            ),
            FailingFunction(
                file_path="app/other.py",
                function_name="func2",
                tier="unit",
                line_coverage_pct=60.0,
                branch_coverage_pct=60.0,
                threshold_line=80.0,
                threshold_branch=70.0,
                missing_lines="[]",
                missing_branches="[]",
            ),
        ]
        result = group_by_test_file(functions)
        assert len(result) == 2
        assert "tests/unit/test_main.py" in result
        assert "tests/unit/test_other.py" in result


class TestCreateBatches:
    def _make_func(self, path: str, name: str) -> FailingFunction:
        """Helper to create a FailingFunction."""
        return FailingFunction(
            file_path=path,
            function_name=name,
            tier="unit",
            line_coverage_pct=50.0,
            branch_coverage_pct=50.0,
            threshold_line=80.0,
            threshold_branch=70.0,
            missing_lines="[]",
            missing_branches="[]",
        )

    def test_single_group_below_target_size(self) -> None:
        """Test with single group below target size."""
        groups = {
            "tests/unit/test_main.py": [
                self._make_func("app/main.py", "func1"),
                self._make_func("app/main.py", "func2"),
            ]
        }
        batches = create_batches(groups, target_size=10)
        assert len(batches) == 1
        assert len(batches[0]) == 2

    def test_group_exceeds_target_size(self) -> None:
        """Test that groups exceeding target size become their own batch."""
        groups = {
            "tests/unit/test_main.py": [
                self._make_func("app/main.py", f"func{i}") for i in range(15)
            ]
        }
        batches = create_batches(groups, target_size=10)
        assert len(batches) == 1
        assert len(batches[0]) == 15  # All in one batch

    def test_multiple_groups_combined_into_batch(self) -> None:
        """Test multiple groups combined into single batch under target size."""
        groups = {
            "tests/unit/test_a.py": [self._make_func("app/a.py", "func1")],
            "tests/unit/test_b.py": [self._make_func("app/b.py", "func2")],
        }
        batches = create_batches(groups, target_size=10)
        assert len(batches) == 1
        assert len(batches[0]) == 2

    def test_groups_split_into_multiple_batches(self) -> None:
        """Test groups split into multiple batches when exceeding target."""
        groups = {
            "tests/unit/test_a.py": [self._make_func("app/a.py", f"func{i}") for i in range(5)],
            "tests/unit/test_b.py": [self._make_func("app/b.py", f"func{i}") for i in range(5)],
            "tests/unit/test_c.py": [self._make_func("app/c.py", f"func{i}") for i in range(5)],
        }
        batches = create_batches(groups, target_size=10)
        # Should split into 2 batches: first has 10 (5+5), second has 5
        assert len(batches) >= 2

    def test_large_group_flushes_current_batch(self) -> None:
        """Test that a large group flushes the current batch first."""
        groups = {
            "tests/unit/test_a.py": [
                self._make_func("app/a.py", "func1"),
                self._make_func("app/a.py", "func2"),
            ],
            "tests/unit/test_big.py": [
                self._make_func("app/big.py", f"func{i}") for i in range(15)
            ],
        }
        batches = create_batches(groups, target_size=10)
        # The small group goes into one batch, the large group into another
        assert len(batches) == 2

    def test_empty_groups(self) -> None:
        """Test with empty groups."""
        groups: dict[str, list[FailingFunction]] = {}
        batches = create_batches(groups, target_size=10)
        assert len(batches) == 0

    def test_large_group_with_existing_batch_content(self) -> None:
        """Test large group is processed first due to sorting by size (descending)."""
        # Groups are sorted by size descending, so large group is processed first
        groups = {
            # First group: small
            "tests/unit/test_a.py": [self._make_func("app/a.py", f"func{i}") for i in range(3)],
            # Second group: large (exceeds target)
            "tests/unit/test_big.py": [
                self._make_func("app/big.py", f"func{i}") for i in range(12)
            ],
            # Third group: small
            "tests/unit/test_c.py": [self._make_func("app/c.py", f"func{i}") for i in range(2)],
        }
        batches = create_batches(groups, target_size=10)
        # Large group (12) goes into its own batch first
        # Small groups (3+2=5) fit together in another batch
        assert len(batches) == 2
        # First batch is the large one (sorted by size descending)
        assert len(batches[0]) == 12
        # Second batch has the combined small groups
        assert len(batches[1]) == 5

    def test_batch_size_exactly_at_target(self) -> None:
        """Test when batch size exactly matches target."""
        groups = {
            "tests/unit/test_a.py": [self._make_func("app/a.py", f"func{i}") for i in range(5)],
            "tests/unit/test_b.py": [self._make_func("app/b.py", f"func{i}") for i in range(5)],
        }
        batches = create_batches(groups, target_size=10)
        # Both groups fit exactly in one batch
        assert len(batches) == 1
        assert len(batches[0]) == 10

    def test_batch_overflow_triggers_new_batch(self) -> None:
        """Test that exceeding target size starts new batch."""
        groups = {
            "tests/unit/test_a.py": [self._make_func("app/a.py", f"func{i}") for i in range(6)],
            "tests/unit/test_b.py": [self._make_func("app/b.py", f"func{i}") for i in range(6)],
        }
        batches = create_batches(groups, target_size=10)
        # First group (6) fits, second group would make 12, so it goes to new batch
        assert len(batches) == 2
        assert len(batches[0]) == 6
        assert len(batches[1]) == 6


class TestWriteBatchFile:
    def test_write_batch_file_creates_file(self, tmp_path: Path) -> None:
        """Test that write_batch_file creates a JSON file."""
        batch = [
            FailingFunction(
                file_path="app/main.py",
                function_name="func1",
                tier="unit",
                line_coverage_pct=50.0,
                branch_coverage_pct=60.0,
                threshold_line=80.0,
                threshold_branch=70.0,
                missing_lines="[1, 2, 3]",
                missing_branches="[[1, 2]]",
            )
        ]
        result_path = write_batch_file(batch, 1, tmp_path)

        assert result_path.exists()
        assert result_path.name == "batch_001.json"

    def test_write_batch_file_content(self, tmp_path: Path) -> None:
        """Test that write_batch_file writes correct content."""
        batch = [
            FailingFunction(
                file_path="app/main.py",
                function_name="func1",
                tier="unit",
                line_coverage_pct=50.0,
                branch_coverage_pct=60.0,
                threshold_line=80.0,
                threshold_branch=70.0,
                missing_lines="[1, 2, 3]",
                missing_branches="[[1, 2]]",
            )
        ]
        result_path = write_batch_file(batch, 1, tmp_path)

        with open(result_path) as f:
            data = json.load(f)

        assert data["batch_number"] == 1
        assert data["total_functions"] == 1
        assert "tests/unit/test_main.py" in data["test_files"]
        assert "tests/unit/test_main.py" in data["functions_by_test_file"]

        func_data = data["functions_by_test_file"]["tests/unit/test_main.py"][0]
        assert func_data["source_file"] == "app/main.py"
        assert func_data["function_name"] == "func1"
        assert func_data["missing_lines"] == [1, 2, 3]
        assert func_data["missing_branches"] == [[1, 2]]

    def test_write_batch_file_multiple_functions(self, tmp_path: Path) -> None:
        """Test write_batch_file with multiple functions."""
        batch = [
            FailingFunction(
                file_path="app/main.py",
                function_name="func1",
                tier="unit",
                line_coverage_pct=50.0,
                branch_coverage_pct=60.0,
                threshold_line=80.0,
                threshold_branch=70.0,
                missing_lines="[]",
                missing_branches="[]",
            ),
            FailingFunction(
                file_path="app/other.py",
                function_name="func2",
                tier="unit",
                line_coverage_pct=40.0,
                branch_coverage_pct=50.0,
                threshold_line=80.0,
                threshold_branch=70.0,
                missing_lines="[5, 6]",
                missing_branches="[]",
            ),
        ]
        result_path = write_batch_file(batch, 5, tmp_path)

        with open(result_path) as f:
            data = json.load(f)

        assert data["batch_number"] == 5
        assert data["total_functions"] == 2
        assert len(data["test_files"]) == 2

    def test_write_batch_file_handles_empty_missing_data(self, tmp_path: Path) -> None:
        """Test write_batch_file handles empty missing lines/branches."""
        batch = [
            FailingFunction(
                file_path="app/main.py",
                function_name="func1",
                tier="unit",
                line_coverage_pct=50.0,
                branch_coverage_pct=60.0,
                threshold_line=80.0,
                threshold_branch=70.0,
                missing_lines="",  # Empty string
                missing_branches="",  # Empty string
            )
        ]
        result_path = write_batch_file(batch, 1, tmp_path)

        with open(result_path) as f:
            data = json.load(f)

        func_data = data["functions_by_test_file"]["tests/unit/test_main.py"][0]
        assert func_data["missing_lines"] == []
        assert func_data["missing_branches"] == []
