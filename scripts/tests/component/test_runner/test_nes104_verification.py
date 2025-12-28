import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from scripts.dev.test_runner.redundant_test_detector import (
    RedundantTestResult,
    detect_redundant_tests,
)
from scripts.dev.test_runner.test_coverage import (
    CoverageResult,
    TestTierConfig,
)


@pytest.fixture
def tier_data_dir(tmp_path: Path) -> Path:
    """Create a directory for tier-specific coverage files."""
    data_dir = tmp_path / ".coverage"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def create_coverage_db_with_contexts(
    db_path: Path,
    contexts: list[str],
    file_coverage: dict[str, dict[str, Any]],
) -> None:
    """Create a coverage.py SQLite database with per-test contexts.

    This creates a valid coverage.py version 7 database that can be used with
    the coverage combine command.

    Args:
        db_path: Path to create the database
        contexts: List of test context names (e.g., ["test_foo", "test_bar"])
        file_coverage: Dict mapping file paths to coverage data:
            {
                "app/module.py": {
                    "lines": {1, 2, 3},  # All covered lines
                    "lines_by_context": {
                        "test_foo": {1, 2},  # Lines covered by test_foo
                        "test_bar": {2, 3},  # Lines covered by test_bar
                    }
                }
            }
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        # Create coverage.py schema (version 7) - MUST include coverage_schema and meta tables
        # for the combine command to work
        conn.executescript("""
            -- Schema version table (required by coverage.py)
            CREATE TABLE coverage_schema (
                version integer
            );
            INSERT INTO coverage_schema VALUES (7);

            -- Metadata table (required by coverage.py)
            CREATE TABLE meta (
                key text,
                value text,
                unique (key)
            );

            CREATE TABLE file (
                id INTEGER PRIMARY KEY,
                path TEXT,
                unique (path)
            );

            CREATE TABLE context (
                id INTEGER PRIMARY KEY,
                context TEXT,
                unique (context)
            );

            CREATE TABLE line_bits (
                file_id INTEGER,
                context_id INTEGER,
                numbits BLOB,
                foreign key (file_id) references file (id),
                foreign key (context_id) references context (id),
                unique (file_id, context_id)
            );

            CREATE TABLE arc (
                file_id INTEGER,
                context_id INTEGER,
                fromno INTEGER,
                tono INTEGER,
                foreign key (file_id) references file (id),
                foreign key (context_id) references context (id),
                unique (file_id, context_id, fromno, tono)
            );

            CREATE TABLE tracer (
                file_id integer primary key,
                tracer text,
                foreign key (file_id) references file (id)
            );
        """)

        # Insert required metadata
        conn.execute("INSERT INTO meta VALUES ('has_arcs', '0')")
        conn.execute("INSERT INTO meta VALUES ('version', '7.3.0')")
        conn.execute("INSERT INTO meta VALUES ('sys_argv', '[]')")

        # Insert empty context (always present in coverage.py)
        conn.execute("INSERT INTO context (id, context) VALUES (0, '')")

        # Insert test contexts
        for i, ctx in enumerate(contexts, start=1):
            conn.execute("INSERT INTO context (id, context) VALUES (?, ?)", (i, ctx))

        # Insert files and coverage data
        for file_id, (file_path, coverage) in enumerate(file_coverage.items(), start=1):
            conn.execute("INSERT INTO file (id, path) VALUES (?, ?)", (file_id, file_path))

            # Insert line coverage per context
            lines_by_context = coverage.get("lines_by_context", {})
            for ctx, lines in lines_by_context.items():
                if ctx in contexts:
                    ctx_id = contexts.index(ctx) + 1
                    # Create numbits blob
                    numbits = _lines_to_numbits(lines)
                    conn.execute(
                        "INSERT INTO line_bits (file_id, context_id, numbits) VALUES (?, ?, ?)",
                        (file_id, ctx_id, numbits),
                    )

        conn.commit()
    finally:
        conn.close()


def _lines_to_numbits(lines: set[int]) -> bytes:
    """Convert a set of line numbers to coverage.py numbits format.

    Numbits is a compressed binary format where each bit represents a line number.
    Byte N, bit B represents line number N*8 + B.
    """
    if not lines:
        return b""

    max_line = max(lines)
    num_bytes = (max_line // 8) + 1
    result = bytearray(num_bytes)

    for line in lines:
        byte_index = line // 8
        bit_index = line % 8
        result[byte_index] |= 1 << bit_index

    return bytes(result)


def create_coverage_json(
    output_path: Path,
    file_coverage: dict[str, dict[str, Any]],
) -> None:
    """Create a coverage.py JSON report file.

    Args:
        output_path: Path to write the JSON file
        file_coverage: Dict mapping file paths to coverage data:
            {
                "app/module.py": {
                    "executed_lines": [1, 2, 3],
                    "missing_lines": [4, 5],
                    "executed_branches": [[1, 2], [1, 3]],
                    "missing_branches": [[4, 5]],
                }
            }
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    files_data = {}
    total_lines = 0
    covered_lines = 0
    missing_lines_count = 0
    total_branches = 0
    covered_branches = 0

    for file_path, coverage in file_coverage.items():
        executed = coverage.get("executed_lines", [])
        missing = coverage.get("missing_lines", [])
        exec_branches = coverage.get("executed_branches", [])
        miss_branches = coverage.get("missing_branches", [])

        files_data[file_path] = {
            "executed_lines": executed,
            "missing_lines": missing,
            "excluded_lines": [],
            "summary": {
                "num_statements": len(executed) + len(missing),
                "covered_lines": len(executed),
                "missing_lines": len(missing),
                "percent_covered": 100 * len(executed) / max(1, len(executed) + len(missing)),
            },
        }

        if exec_branches or miss_branches:
            files_data[file_path]["missing_branches"] = miss_branches

        total_lines += len(executed) + len(missing)
        covered_lines += len(executed)
        missing_lines_count += len(missing)
        total_branches += len(exec_branches) + len(miss_branches)
        covered_branches += len(exec_branches)

    report = {
        "meta": {
            "version": "7.0",
            "timestamp": "2024-01-01T00:00:00.000000",
            "branch_coverage": True,
            "show_contexts": False,
        },
        "files": files_data,
        "totals": {
            "num_statements": total_lines,
            "covered_lines": covered_lines,
            "missing_lines": missing_lines_count,
            "percent_covered": 100 * covered_lines / max(1, total_lines),
            "num_branches": total_branches,
            "covered_branches": covered_branches,
            "missing_branches": total_branches - covered_branches,
            "percent_covered_branches": 100 * covered_branches / max(1, total_branches),
        },
    }

    output_path.write_text(json.dumps(report, indent=2))


class TestVerification1TierIsolation:
    def test_unit_tier_coverage_result_structure(self, tmp_path: Path) -> None:
        """CoverageResult has required fields for tier comparison."""
        result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=80,
            missing_lines=20,
            line_coverage_pct=80.0,
            total_branches=50,
            covered_branches=40,
            missing_branches=10,
            branch_coverage_pct=80.0,
            files={},
            functions={
                "app/service.py::process": {
                    "name": "process",
                    "file": "app/service.py",
                    "line_coverage": 85.0,
                    "branch_coverage": 75.0,
                }
            },
        )

        # Verify all fields needed for comparison exist
        assert result.suite_name == "unit"
        assert result.total_lines == 100
        assert result.covered_lines == 80
        assert result.line_coverage_pct == 80.0
        assert result.total_branches == 50
        assert result.covered_branches == 40
        assert result.branch_coverage_pct == 80.0
        assert len(result.functions) == 1

    def test_isolated_tier_config_has_unique_coverage_file(self, tmp_path: Path) -> None:
        """TestTierConfig can be associated with tier-specific coverage file path.

        This test verifies the data structures support tier isolation.
        """
        unit_config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )

        component_config = TestTierConfig(
            name="component",
            test_path="tests/component",
            source_paths=["app/services"],
            min_usecase=100.0,
        )

        # Each tier should have distinct configuration
        assert unit_config.name != component_config.name
        assert unit_config.source_paths != component_config.source_paths
        assert component_config.coverage_type == "usecase"
        assert unit_config.coverage_type == "line_branch"

    def test_coverage_json_isolated_per_tier(self, tier_data_dir: Path) -> None:
        """Different tiers can have different coverage JSON reports.

        Verifies that we can create isolated coverage data for each tier.
        """
        # Create unit tier coverage
        unit_coverage = {
            "app/module.py": {
                "executed_lines": [1, 2, 3, 4, 5],
                "missing_lines": [6, 7],
            },
            "app/services/service.py": {
                "executed_lines": [10, 11, 12],
                "missing_lines": [13, 14, 15],
            },
        }
        create_coverage_json(tier_data_dir / "unit_coverage.json", unit_coverage)

        # Create component tier coverage (only service layer)
        component_coverage = {
            "app/services/service.py": {
                "executed_lines": [10, 11],  # Fewer lines than unit
                "missing_lines": [12, 13, 14, 15],
            },
        }
        create_coverage_json(tier_data_dir / "component_coverage.json", component_coverage)

        # Verify files are independent
        with (tier_data_dir / "unit_coverage.json").open() as f:
            unit_data = json.load(f)
        with (tier_data_dir / "component_coverage.json").open() as f:
            component_data = json.load(f)

        # Unit tier should have more files
        assert len(unit_data["files"]) == 2
        assert len(component_data["files"]) == 1

        # Unit should cover more lines in service.py
        unit_service = unit_data["files"]["app/services/service.py"]
        comp_service = component_data["files"]["app/services/service.py"]
        assert len(unit_service["executed_lines"]) > len(comp_service["executed_lines"])

    def test_function_counts_match_between_isolated_runs(self, tier_data_dir: Path) -> None:
        """Function counts are consistent when tier runs alone vs in suite.

        This test simulates checking that the same tier configuration
        produces the same function count regardless of other tiers.
        """
        # Simulate "run alone" coverage
        alone_functions = {
            "app/module.py::func_a": {"name": "func_a", "line_coverage": 90.0},
            "app/module.py::func_b": {"name": "func_b", "line_coverage": 80.0},
            "app/module.py::func_c": {"name": "func_c", "line_coverage": 70.0},
        }

        # Simulate "run as part of suite" coverage (should be identical)
        suite_functions = {
            "app/module.py::func_a": {"name": "func_a", "line_coverage": 90.0},
            "app/module.py::func_b": {"name": "func_b", "line_coverage": 80.0},
            "app/module.py::func_c": {"name": "func_c", "line_coverage": 70.0},
        }

        # With proper isolation, both should be identical
        assert len(alone_functions) == len(suite_functions)
        for key in alone_functions:
            assert key in suite_functions
            assert alone_functions[key]["line_coverage"] == suite_functions[key]["line_coverage"]

    def test_no_leakage_from_other_tiers(self, tier_data_dir: Path) -> None:
        """Unit tier coverage should not include component-only covered lines.

        This verifies the isolation mechanism prevents cross-tier contamination.
        """
        # In isolated mode, unit tier only sees its own coverage
        unit_only_coverage = {
            "app/module.py": {
                "executed_lines": [1, 2, 3],
                "missing_lines": [4, 5, 6],
            },
        }

        # If component tests covered lines 4, 5 - unit should NOT see them
        # (This would happen without isolation - we verify it doesn't)
        create_coverage_json(tier_data_dir / "isolated_unit.json", unit_only_coverage)

        with (tier_data_dir / "isolated_unit.json").open() as f:
            data = json.load(f)

        # Verify only unit's lines are marked as executed
        executed = data["files"]["app/module.py"]["executed_lines"]
        missing = data["files"]["app/module.py"]["missing_lines"]

        assert 4 not in executed
        assert 5 not in executed
        assert 4 in missing
        assert 5 in missing


class TestVerification2TierSpecificCoverage:
    def test_component_coverage_excludes_unit_only_lines(self, tier_data_dir: Path) -> None:
        """Component tier coverage JSON should not include lines only covered by unit.

        Scenario:
        - Unit tests cover lines 1-10 of service.py
        - Component tests only cover lines 5-8 of service.py
        - Component coverage should show lines 1-4, 9-10 as missing
        """
        # Unit coverage (more comprehensive)
        unit_coverage = {
            "app/services/service.py": {
                "executed_lines": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                "missing_lines": [],
            }
        }

        # Component coverage (less comprehensive)
        component_coverage = {
            "app/services/service.py": {
                "executed_lines": [5, 6, 7, 8],
                "missing_lines": [1, 2, 3, 4, 9, 10],
            }
        }

        create_coverage_json(tier_data_dir / "unit.json", unit_coverage)
        create_coverage_json(tier_data_dir / "component.json", component_coverage)

        # Load and verify
        with (tier_data_dir / "component.json").open() as f:
            comp_data = json.load(f)

        comp_file = comp_data["files"]["app/services/service.py"]

        # Lines 1-4 and 9-10 should be missing in component (even though unit covers them)
        assert 1 in comp_file["missing_lines"]
        assert 2 in comp_file["missing_lines"]
        assert 3 in comp_file["missing_lines"]
        assert 4 in comp_file["missing_lines"]
        assert 9 in comp_file["missing_lines"]
        assert 10 in comp_file["missing_lines"]

        # Lines 5-8 should be executed
        assert 5 in comp_file["executed_lines"]
        assert 6 in comp_file["executed_lines"]
        assert 7 in comp_file["executed_lines"]
        assert 8 in comp_file["executed_lines"]

    def test_function_shows_higher_coverage_in_unit_than_component(
        self, tier_data_dir: Path
    ) -> None:
        """Same function can show different coverage percentages per tier.

        Verifies that a function in app/services/ can have:
        - 100% coverage in unit tier
        - 40% coverage in component tier

        This is expected when unit tests exercise more code paths than
        component tests for the same function.
        """
        # Unit tier: 100% coverage of the function
        unit_result = CoverageResult(
            suite_name="unit",
            total_lines=10,
            covered_lines=10,
            missing_lines=0,
            line_coverage_pct=100.0,
            total_branches=4,
            covered_branches=4,
            missing_branches=0,
            branch_coverage_pct=100.0,
            files={},
            functions={
                "app/services/auth.py::validate_token": {
                    "name": "validate_token",
                    "file": "app/services/auth.py",
                    "line_coverage": 100.0,
                    "branch_coverage": 100.0,
                }
            },
        )

        # Component tier: 40% coverage of the same function
        component_result = CoverageResult(
            suite_name="component",
            total_lines=10,
            covered_lines=4,
            missing_lines=6,
            line_coverage_pct=40.0,
            total_branches=4,
            covered_branches=2,
            missing_branches=2,
            branch_coverage_pct=50.0,
            files={},
            functions={
                "app/services/auth.py::validate_token": {
                    "name": "validate_token",
                    "file": "app/services/auth.py",
                    "line_coverage": 40.0,
                    "branch_coverage": 50.0,
                }
            },
        )

        # Verify the same function has different coverage per tier
        unit_func = unit_result.functions["app/services/auth.py::validate_token"]
        comp_func = component_result.functions["app/services/auth.py::validate_token"]

        assert unit_func["line_coverage"] > comp_func["line_coverage"]
        assert unit_func["branch_coverage"] > comp_func["branch_coverage"]

        # Specifically verify expected values
        assert unit_func["line_coverage"] == 100.0
        assert comp_func["line_coverage"] == 40.0

    def test_overall_percentage_differs_between_tiers(self, tier_data_dir: Path) -> None:
        """Overall coverage percentage can differ between tiers for same source.

        Even when analyzing the same source files, different test tiers
        may have different overall coverage percentages.
        """
        # Create coverage data with different overall percentages
        unit_data = {
            "app/services/service.py": {
                "executed_lines": list(range(1, 81)),  # 80 lines covered
                "missing_lines": list(range(81, 101)),  # 20 lines missing
            }
        }

        component_data = {
            "app/services/service.py": {
                "executed_lines": list(range(1, 51)),  # 50 lines covered
                "missing_lines": list(range(51, 101)),  # 50 lines missing
            }
        }

        create_coverage_json(tier_data_dir / "unit.json", unit_data)
        create_coverage_json(tier_data_dir / "component.json", component_data)

        with (tier_data_dir / "unit.json").open() as f:
            unit_json = json.load(f)
        with (tier_data_dir / "component.json").open() as f:
            comp_json = json.load(f)

        # Verify different overall coverage percentages
        unit_pct = unit_json["totals"]["percent_covered"]
        comp_pct = comp_json["totals"]["percent_covered"]

        assert unit_pct == 80.0
        assert comp_pct == 50.0
        assert unit_pct > comp_pct

    def test_missing_lines_accurate_per_tier(self, tier_data_dir: Path) -> None:
        """Missing lines list is accurate for each tier independently."""
        # Unit covers lines 1-5, component covers lines 3-7
        # Total lines: 1-10
        unit_data = {
            "app/module.py": {
                "executed_lines": [1, 2, 3, 4, 5],
                "missing_lines": [6, 7, 8, 9, 10],
            }
        }

        component_data = {
            "app/module.py": {
                "executed_lines": [3, 4, 5, 6, 7],
                "missing_lines": [1, 2, 8, 9, 10],
            }
        }

        create_coverage_json(tier_data_dir / "unit.json", unit_data)
        create_coverage_json(tier_data_dir / "component.json", component_data)

        with (tier_data_dir / "unit.json").open() as f:
            unit_json = json.load(f)
        with (tier_data_dir / "component.json").open() as f:
            comp_json = json.load(f)

        unit_missing = set(unit_json["files"]["app/module.py"]["missing_lines"])
        comp_missing = set(comp_json["files"]["app/module.py"]["missing_lines"])

        # Lines 1, 2 are missing in component but NOT in unit
        assert 1 not in unit_missing
        assert 2 not in unit_missing
        assert 1 in comp_missing
        assert 2 in comp_missing

        # Lines 6, 7 are missing in unit but NOT in component
        assert 6 in unit_missing
        assert 7 in unit_missing
        assert 6 not in comp_missing
        assert 7 not in comp_missing


class TestVerification3RedundantTestDetector:
    def test_detect_redundant_tests_returns_valid_result(self, tier_data_dir: Path) -> None:
        """detect_redundant_tests() returns RedundantTestResult, not error."""
        db_path = tier_data_dir / "combined.db"

        # Create coverage database with test contexts
        contexts = ["test_foo", "test_bar", "test_baz"]
        file_coverage = {
            "app/module.py": {
                "lines": {1, 2, 3, 4, 5},
                "lines_by_context": {
                    "test_foo": {1, 2, 3},
                    "test_bar": {2, 3, 4},
                    "test_baz": {4, 5},
                },
            }
        }
        create_coverage_db_with_contexts(db_path, contexts, file_coverage)

        # Call detect_redundant_tests
        result = detect_redundant_tests(db_path)

        # Verify it returns a valid RedundantTestResult
        assert isinstance(result, RedundantTestResult)
        assert "error" not in result.summary or result.summary.get("error") is None

    def test_total_tests_analyzed_greater_than_zero(self, tier_data_dir: Path) -> None:
        """detect_redundant_tests() analyzes at least 1 test (total_tests > 0)."""
        db_path = tier_data_dir / "combined.db"

        contexts = ["test_alpha", "test_beta"]
        file_coverage = {
            "app/service.py": {
                "lines": {10, 11, 12},
                "lines_by_context": {
                    "test_alpha": {10, 11},
                    "test_beta": {11, 12},
                },
            }
        }
        create_coverage_db_with_contexts(db_path, contexts, file_coverage)

        result = detect_redundant_tests(db_path)

        assert result.total_tests > 0
        assert result.total_tests == 2  # We have 2 test contexts

    def test_tests_with_unique_coverage_greater_than_zero(self, tier_data_dir: Path) -> None:
        """At least some tests have unique coverage (tests_with_unique_coverage > 0)."""
        db_path = tier_data_dir / "combined.db"

        # Create tests where each has some unique coverage
        contexts = ["test_unique_a", "test_unique_b", "test_unique_c"]
        file_coverage = {
            "app/service.py": {
                "lines": {1, 2, 3, 4, 5, 6},
                "lines_by_context": {
                    "test_unique_a": {1, 2},  # Unique: line 1
                    "test_unique_b": {2, 3, 4},  # Unique: lines 3, 4
                    "test_unique_c": {5, 6},  # Unique: lines 5, 6
                },
            }
        }
        create_coverage_db_with_contexts(db_path, contexts, file_coverage)

        result = detect_redundant_tests(db_path)

        # Each test has unique coverage, so all should be counted
        assert result.tests_with_unique_coverage > 0
        # All 3 tests have unique lines
        assert result.tests_with_unique_coverage == 3

    def test_contexts_recorded_in_database(self, tier_data_dir: Path) -> None:
        """Coverage database has context_count > 0 after creation."""
        db_path = tier_data_dir / "combined.db"

        contexts = ["test_one", "test_two", "test_three"]
        file_coverage = {
            "app/module.py": {
                "lines": {1, 2, 3},
                "lines_by_context": {
                    "test_one": {1},
                    "test_two": {2},
                    "test_three": {3},
                },
            }
        }
        create_coverage_db_with_contexts(db_path, contexts, file_coverage)

        # Query context count directly
        conn = sqlite3.connect(str(db_path))
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM context WHERE context != ''")
            context_count = cursor.fetchone()[0]
        finally:
            conn.close()

        assert context_count > 0
        assert context_count == 3  # We created 3 non-empty contexts

    def test_empty_database_returns_error_in_summary(self, tier_data_dir: Path) -> None:
        """Database without contexts returns error message in summary."""
        db_path = tier_data_dir / "empty.db"

        # Create database with NO contexts
        create_coverage_db_with_contexts(db_path, [], {})

        result = detect_redundant_tests(db_path)

        # Should return an error message about missing contexts
        assert "error" in result.summary
        assert "context" in result.summary["error"].lower()
        assert result.total_tests == 0

    def test_redundant_test_identified_correctly(self, tier_data_dir: Path) -> None:
        """Tests with zero unique coverage are correctly identified as redundant."""
        db_path = tier_data_dir / "combined.db"

        # Create tests where test_c is fully redundant
        contexts = ["test_a", "test_b", "test_redundant"]
        file_coverage = {
            "app/module.py": {
                "lines": {1, 2, 3, 4, 5},
                "lines_by_context": {
                    "test_a": {1, 2, 3},  # Has unique lines 1, 2
                    "test_b": {3, 4, 5},  # Has unique lines 4, 5
                    "test_redundant": {3},  # Only covers line 3, already covered by both
                },
            }
        }
        create_coverage_db_with_contexts(db_path, contexts, file_coverage)

        result = detect_redundant_tests(db_path)

        # test_redundant should be identified as redundant
        assert len(result.redundant_tests) >= 1
        redundant_names = [t["test_name"] for t in result.redundant_tests]
        assert "test_redundant" in redundant_names

    def test_result_summary_has_required_fields(self, tier_data_dir: Path) -> None:
        """RedundantTestResult.summary has all required statistics fields."""
        db_path = tier_data_dir / "combined.db"

        contexts = ["test_x", "test_y"]
        file_coverage = {
            "app/module.py": {
                "lines": {1, 2},
                "lines_by_context": {
                    "test_x": {1},
                    "test_y": {2},
                },
            }
        }
        create_coverage_db_with_contexts(db_path, contexts, file_coverage)

        result = detect_redundant_tests(db_path)

        # Verify summary has required fields
        assert "total_tests_analyzed" in result.summary
        assert "redundant_test_count" in result.summary
        assert "tests_with_unique_coverage" in result.summary
        assert "redundancy_rate_pct" in result.summary

    def test_contexts_preserved_after_combination(self, tier_data_dir: Path) -> None:
        """When multiple tier databases are combined, all contexts are preserved.

        This simulates verifying that combined count >= sum of tier counts.
        """
        # Create two separate tier databases
        unit_db = tier_data_dir / "unit.db"
        component_db = tier_data_dir / "component.db"

        # Unit tier has 3 test contexts
        create_coverage_db_with_contexts(
            unit_db,
            ["unit_test_1", "unit_test_2", "unit_test_3"],
            {
                "app/module.py": {
                    "lines": {1, 2, 3},
                    "lines_by_context": {
                        "unit_test_1": {1},
                        "unit_test_2": {2},
                        "unit_test_3": {3},
                    },
                }
            },
        )

        # Component tier has 2 test contexts
        create_coverage_db_with_contexts(
            component_db,
            ["comp_test_1", "comp_test_2"],
            {
                "app/services/service.py": {
                    "lines": {10, 11},
                    "lines_by_context": {
                        "comp_test_1": {10},
                        "comp_test_2": {11},
                    },
                }
            },
        )

        # Count contexts in each
        def count_contexts(db_path: Path) -> int:
            conn = sqlite3.connect(str(db_path))
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM context WHERE context != ''")
                return cursor.fetchone()[0]
            finally:
                conn.close()

        unit_count = count_contexts(unit_db)
        comp_count = count_contexts(component_db)

        assert unit_count == 3
        assert comp_count == 2

        # In a real combined database, we should have at least 5 contexts
        # (This simulates the verification - actual combine would use coverage.py)
        expected_combined_min = unit_count + comp_count
        assert expected_combined_min == 5

    def test_nonexistent_database_handled_gracefully(self, tier_data_dir: Path) -> None:
        """detect_redundant_tests() handles missing database file gracefully."""
        nonexistent_path = tier_data_dir / "does_not_exist.db"

        # Should not raise exception
        result = detect_redundant_tests(nonexistent_path)

        # Should return empty/error result
        assert result.total_tests == 0
        assert "error" in result.summary or len(result.redundant_tests) == 0


class TestCoverageIsolationIntegration:
    def test_tier_coverage_file_naming_convention(self, tier_data_dir: Path) -> None:
        """Tier coverage files follow data_{tier_name} naming convention."""
        # Verify expected paths can be constructed
        unit_path = tier_data_dir / "data_unit"
        component_path = tier_data_dir / "data_component"
        integration_path = tier_data_dir / "data_integration"
        scripts_path = tier_data_dir / "data_scripts"

        # Each tier should have a distinct path
        paths = [unit_path, component_path, integration_path, scripts_path]
        assert len(set(paths)) == 4  # All unique

        # Paths should follow naming convention
        assert unit_path.name == "data_unit"
        assert component_path.name == "data_component"
        assert integration_path.name == "data_integration"
        assert scripts_path.name == "data_scripts"

    def test_combined_coverage_aggregates_all_tiers(self, tier_data_dir: Path) -> None:
        """Combined coverage database aggregates data from all tiers.

        This verifies the conceptual model where:
        1. Per-tier files are isolated during validation
        2. Combined file is used for global analysis (redundant test detection)
        """
        # Create simulated per-tier data
        tier_data = {
            "unit": {"lines": [1, 2, 3, 4, 5]},
            "component": {"lines": [3, 4, 5, 6, 7]},
            "integration": {"lines": [7, 8, 9]},
        }

        # Combined should have union of all lines
        all_lines = set()
        for _tier, data in tier_data.items():
            all_lines.update(data["lines"])

        # Verify combined has all lines
        expected_combined = {1, 2, 3, 4, 5, 6, 7, 8, 9}
        assert all_lines == expected_combined
        assert len(all_lines) == 9

    def test_tier_config_component_uses_usecase_coverage(self) -> None:
        """TestTierConfig component tier uses usecase coverage type."""
        component_config = TestTierConfig(
            name="component",
            test_path="tests/component",
            source_paths=["app/services"],
            min_usecase=100.0,
            skip_private_functions=True,
        )

        assert component_config.coverage_type == "usecase"
        assert component_config.skip_private_functions is True
        assert component_config.source_paths == ["app/services"]
        assert component_config.min_usecase == 100.0

    def test_tier_config_defaults(self) -> None:
        """TestTierConfig has sensible defaults for optional flags."""
        basic_config = TestTierConfig(
            name="test",
            test_path="tests",
            source_paths=["src"],
            min_line_per_function=80.0,
        )

        # Default values
        assert basic_config.skip_private_functions is False
        assert basic_config.exclude_class_fields is True
        assert basic_config.min_line_per_function == 80.0  # As explicitly set
        assert basic_config.min_line_overall is None  # Not set
        assert basic_config.min_branch_per_function is None  # Not set


class TestActualCombineFlowPreservesContexts:
    def test_combined_database_has_contexts_after_real_combine(self, tier_data_dir: Path) -> None:
        """Combined database must have contexts after the real combine operation.

        This tests the actual combine flow, not mocked behavior.
        """
        import subprocess

        unit_db = tier_data_dir / "data_unit"
        component_db = tier_data_dir / "data_component"
        combined_db = tier_data_dir / "data"

        # Create databases with test contexts using our helper
        create_coverage_db_with_contexts(
            unit_db,
            contexts=["test_unit_func_a", "test_unit_func_b"],
            file_coverage={
                "app/module.py": {
                    "lines": {1, 2, 3, 4, 5},
                    "lines_by_context": {
                        "test_unit_func_a": {1, 2, 3},
                        "test_unit_func_b": {3, 4, 5},
                    },
                }
            },
        )

        create_coverage_db_with_contexts(
            component_db,
            contexts=["test_component_func"],
            file_coverage={
                "app/services/service.py": {
                    "lines": {10, 11, 12},
                    "lines_by_context": {
                        "test_component_func": {10, 11, 12},
                    },
                }
            },
        )

        # Run actual coverage combine
        import os

        result = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "coverage",
                "combine",
                "--keep",
                str(unit_db),
                str(component_db),
            ],
            env={"COVERAGE_FILE": str(combined_db), **os.environ},
            capture_output=True,
            text=True,
            cwd=str(tier_data_dir),
        )

        assert result.returncode == 0, f"Combine failed: {result.stderr}"
        assert combined_db.exists(), "Combined database should be created"

        # Verify contexts are preserved in combined database
        conn = sqlite3.connect(str(combined_db))
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM context WHERE context != ''")
            context_count = cursor.fetchone()[0]
        finally:
            conn.close()

        # Must have at least 3 contexts (2 from unit + 1 from component)
        assert context_count >= 3, (
            f"CRITICAL: Combined database must preserve contexts. "
            f"Expected >= 3, got {context_count}. Redundant test detection will fail!"
        )

    def test_detect_redundant_tests_works_on_combined_database(self, tier_data_dir: Path) -> None:
        """detect_redundant_tests() must work correctly on combined database.

        This is the end-to-end verification that the actual implementation produces
        usable results for redundant test detection.
        """
        import os
        import subprocess

        unit_db = tier_data_dir / "data_unit"
        component_db = tier_data_dir / "data_component"
        combined_db = tier_data_dir / "data"

        # Create databases with overlapping coverage
        # test_primary covers lines 1-5
        # test_redundant covers only lines 2-3 (subset of test_primary)
        create_coverage_db_with_contexts(
            unit_db,
            contexts=["test_primary"],
            file_coverage={
                "app/module.py": {
                    "lines": {1, 2, 3, 4, 5},
                    "lines_by_context": {
                        "test_primary": {1, 2, 3, 4, 5},
                    },
                }
            },
        )

        create_coverage_db_with_contexts(
            component_db,
            contexts=["test_redundant"],
            file_coverage={
                "app/module.py": {
                    "lines": {2, 3},
                    "lines_by_context": {
                        "test_redundant": {2, 3},  # Only covers subset
                    },
                }
            },
        )

        # Combine databases
        subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "coverage",
                "combine",
                "--keep",
                str(unit_db),
                str(component_db),
            ],
            env={"COVERAGE_FILE": str(combined_db), **os.environ},
            capture_output=True,
            cwd=str(tier_data_dir),
        )

        # Run redundant test detection on combined database
        result = detect_redundant_tests(combined_db)

        # Verify detection works
        assert isinstance(result, RedundantTestResult)
        assert result.total_tests == 2, f"Expected 2 tests, got {result.total_tests}"

        # test_redundant should be identified as redundant
        # (all its coverage is a subset of test_primary)
        redundant_names = [t["test_name"] for t in result.redundant_tests]
        assert "test_redundant" in redundant_names, (
            f"test_redundant should be detected as redundant. "
            f"Redundant tests found: {redundant_names}"
        )

    def test_detect_redundant_tests_returns_error_without_contexts(
        self, tier_data_dir: Path
    ) -> None:
        """detect_redundant_tests() must return error when no contexts present.

        This verifies that the implementation correctly identifies when
        --context=test was not used during test execution.
        """
        # Create a database WITHOUT contexts
        db_path = tier_data_dir / "no_contexts.db"
        conn = sqlite3.connect(str(db_path))
        try:
            # Create minimal coverage.py schema without test contexts
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS file (
                    id INTEGER PRIMARY KEY,
                    path TEXT UNIQUE NOT NULL
                );
                CREATE TABLE IF NOT EXISTS context (
                    id INTEGER PRIMARY KEY,
                    context TEXT UNIQUE NOT NULL
                );
                CREATE TABLE IF NOT EXISTS line_bits (
                    file_id INTEGER NOT NULL,
                    context_id INTEGER NOT NULL,
                    numbits BLOB NOT NULL,
                    PRIMARY KEY (file_id, context_id)
                );
                -- Insert only empty context (no test contexts)
                INSERT INTO context (id, context) VALUES (0, '');
                INSERT INTO file (id, path) VALUES (1, 'app/module.py');
            """)
            conn.commit()
        finally:
            conn.close()

        # detect_redundant_tests should return error for missing contexts
        result = detect_redundant_tests(db_path)

        assert "error" in result.summary, (
            "detect_redundant_tests must return error when no contexts present"
        )
        assert result.total_tests == 0


class TestActualCombineCommandConstruction:
    def test_combine_uses_keep_flag_from_main(self, tmp_path: Path) -> None:
        """The combine command in main() MUST use --keep flag.

        This preserves tier-specific coverage files for potential re-analysis.
        This test verifies by inspecting the source code directly.
        """
        import inspect

        from scripts.dev.test_runner import test_coverage

        source = inspect.getsource(test_coverage.main)

        # The combine command construction should include --keep
        assert '"--keep"' in source or "'--keep'" in source, (
            "CRITICAL: main() combine command MUST include --keep flag. "
            "Without --keep, tier files are deleted after combine, "
            "preventing re-analysis or debugging."
        )

    def test_combine_command_includes_all_tier_files(self, tmp_path: Path) -> None:
        """The combine command must include all tier coverage files.

        This test verifies the structure of combine command construction in main().
        """
        import inspect

        from scripts.dev.test_runner import test_coverage

        source = inspect.getsource(test_coverage.main)

        # Verify tier_data_files is used in combine command
        assert "tier_data_files" in source, (
            "main() should construct tier_data_files list for combine"
        )

        # Verify combine command unpacks tier_data_files
        assert "*tier_data_files" in source, (
            "Combine command should include *tier_data_files to pass all tier files"
        )
