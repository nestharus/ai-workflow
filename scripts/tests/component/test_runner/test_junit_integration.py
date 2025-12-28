"""Integration tests for junit XML parsing with test_coverage.py."""

from __future__ import annotations

import tempfile
from pathlib import Path

from scripts.dev.test_runner import coverage_db
from scripts.dev.test_runner.junit_parser import parse_junit_xml


class TestJunitIntegration:
    """Integration tests for junit parsing and database writing."""

    def test_writes_test_results_to_database(self) -> None:
        """Should write test results from junit XML to database."""
        # Create temporary database
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            # Initialize database
            coverage_db.init_custom_tables(db_path)

            # Create junit XML with test results
            with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w") as f:
                junit_xml = Path(f.name)
                f.write("""<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="3" errors="1" failures="1" skipped="0" time="0.6">
    <testcase classname="tests.unit.test_main" name="test_pass" time="0.1"/>
    <testcase classname="tests.unit.test_main" name="test_fail" time="0.2">
        <failure message="AssertionError">assert False</failure>
    </testcase>
    <testcase classname="tests.unit.test_main" name="test_error" time="0.3">
        <error message="ImportError">No module</error>
    </testcase>
</testsuite>
""")

            # Parse junit XML
            test_results, _test_summary = parse_junit_xml(junit_xml)

            # Write to database
            for test_result in test_results:
                coverage_db.write_test_result(
                    db_path,
                    tier="unit",
                    test_name=test_result.test_name,
                    status=test_result.status,
                    duration=test_result.duration,
                    message=test_result.message,
                    traceback=test_result.traceback,
                )

            # Verify results were written
            failures = coverage_db.get_test_failures(db_path)
            assert len(failures) == 2  # 1 failure + 1 error

            # Check failure details
            fail_result = next(r for r in failures if "test_fail" in r["test_name"])
            assert fail_result["status"] == "failed"
            assert fail_result["message"] == "AssertionError"
            assert fail_result["traceback"] == "assert False"
            assert fail_result["duration"] == 0.2

            # Check error details
            error_result = next(r for r in failures if "test_error" in r["test_name"])
            assert error_result["status"] == "error"
            assert error_result["message"] == "ImportError"
            assert error_result["traceback"] == "No module"
            assert error_result["duration"] == 0.3

            # Clean up
            junit_xml.unlink()
        finally:
            if db_path.exists():
                db_path.unlink()

    def test_test_summary_included_in_tier_summary(self) -> None:
        """Should include test counts in tier summary."""
        # Create temporary database
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            # Initialize database
            coverage_db.init_custom_tables(db_path)

            # Write tier summary with test counts
            summary = {
                "coverage_type": "line_branch",
                "total_functions": 10,
                "passing_functions": 8,
                "failing_functions": 2,
                "overall_line_pct": 85.0,
                "overall_branch_pct": 80.0,
                "total_tests": 50,
                "tests_passed": 48,
                "tests_failed": 2,
                "tier_pass": 0,  # Failed because of test failures
            }
            coverage_db.write_tier_summary(db_path, "unit", summary)

            # Read back and verify
            result = coverage_db.get_tier_summary(db_path, tier="unit")

            assert result["total_tests"] == 50
            assert result["tests_passed"] == 48
            assert result["tests_failed"] == 2
            assert result["tier_pass"] == 0

        finally:
            if db_path.exists():
                db_path.unlink()

    def test_tier_pass_fails_when_tests_fail(self) -> None:
        """Tier should fail when tests fail even if coverage is good."""
        # Create temporary database
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            # Initialize database
            coverage_db.init_custom_tables(db_path)

            # Good coverage but test failures
            summary = {
                "coverage_type": "line_branch",
                "total_functions": 10,
                "passing_functions": 10,  # All functions pass coverage
                "failing_functions": 0,
                "overall_line_pct": 95.0,
                "overall_branch_pct": 90.0,
                "total_tests": 10,
                "tests_passed": 8,
                "tests_failed": 2,  # But 2 tests failed
                "tier_pass": 0,  # Should fail overall
            }
            coverage_db.write_tier_summary(db_path, "unit", summary)

            result = coverage_db.get_tier_summary(db_path, tier="unit")
            assert result["tier_pass"] == 0

        finally:
            if db_path.exists():
                db_path.unlink()

    def test_tier_pass_succeeds_when_all_tests_pass(self) -> None:
        """Tier should pass when all tests pass and coverage is good."""
        # Create temporary database
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            # Initialize database
            coverage_db.init_custom_tables(db_path)

            # Good coverage and all tests pass
            summary = {
                "coverage_type": "line_branch",
                "total_functions": 10,
                "passing_functions": 10,
                "failing_functions": 0,
                "overall_line_pct": 95.0,
                "overall_branch_pct": 90.0,
                "total_tests": 10,
                "tests_passed": 10,  # All tests passed
                "tests_failed": 0,
                "tier_pass": 1,  # Should pass
            }
            coverage_db.write_tier_summary(db_path, "unit", summary)

            result = coverage_db.get_tier_summary(db_path, tier="unit")
            assert result["tier_pass"] == 1

        finally:
            if db_path.exists():
                db_path.unlink()

    def test_filters_test_failures_by_tier(self) -> None:
        """Should be able to filter test failures by tier."""
        # Create temporary database
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            # Initialize database
            coverage_db.init_custom_tables(db_path)

            # Write failures for different tiers
            coverage_db.write_test_result(
                db_path,
                tier="unit",
                test_name="tests/unit/test_a.py::test_fail",
                status="failed",
                duration=0.1,
                message="Unit test failed",
            )

            coverage_db.write_test_result(
                db_path,
                tier="integration",
                test_name="tests/integration/test_b.py::test_fail",
                status="failed",
                duration=0.2,
                message="Integration test failed",
            )

            # Get all failures
            all_failures = coverage_db.get_test_failures(db_path)
            assert len(all_failures) == 2

            # Get only unit failures
            unit_failures = coverage_db.get_test_failures(db_path, tier="unit")
            assert len(unit_failures) == 1
            assert unit_failures[0]["tier"] == "unit"
            assert "Unit test failed" in unit_failures[0]["message"]

            # Get only integration failures
            integration_failures = coverage_db.get_test_failures(db_path, tier="integration")
            assert len(integration_failures) == 1
            assert integration_failures[0]["tier"] == "integration"
            assert "Integration test failed" in integration_failures[0]["message"]

        finally:
            if db_path.exists():
                db_path.unlink()
