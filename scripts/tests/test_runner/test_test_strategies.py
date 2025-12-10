"""Tests for test strategy implementations.

These tests verify the Strategy pattern implementation for test coverage tiers.
They focus on:
- TestStrategy abstract class contract
- LineBranchTestStrategy lifecycle and behavior
- IntegrationTestStrategy lifecycle and behavior
- create_strategy() factory function
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.dev.test_runner.junit_parser import TestSummary
from scripts.dev.test_runner.test_coverage import (
    CoverageResult,
    TestTierConfig,
    UseCase,
    UseCaseCoverageResult,
)
from scripts.dev.test_runner.test_strategies import (
    IntegrationTestStrategy,
    LineBranchTestStrategy,
    create_strategy,
)


class TestCreateStrategyFactory:
    """Tests for the create_strategy() factory function."""

    def test_creates_line_branch_strategy(self, tmp_path: Path) -> None:
        """Factory returns LineBranchTestStrategy for line_branch type."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            coverage_type="line_branch",
        )
        db_path = tmp_path / "coverage.db"

        strategy = create_strategy(config, db_path, tmp_path, first_tier=True)

        assert isinstance(strategy, LineBranchTestStrategy)
        assert strategy.config == config
        assert strategy.first_tier is True

    def test_creates_integration_strategy(self, tmp_path: Path) -> None:
        """Factory returns IntegrationTestStrategy for usecase type."""
        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            coverage_type="usecase",
        )
        use_cases = [
            UseCase(
                id="UC-TEST-001",
                endpoint="/test",
                method="GET",
                description="Test",
                test_tier="integration",
            )
        ]
        db_path = tmp_path / "coverage.db"

        strategy = create_strategy(config, db_path, tmp_path, use_cases=use_cases)

        assert isinstance(strategy, IntegrationTestStrategy)
        assert strategy.use_cases == use_cases

    def test_raises_for_unknown_coverage_type(self, tmp_path: Path) -> None:
        """Factory raises ValueError for unknown coverage type."""
        config = TestTierConfig(
            name="unknown",
            test_path="tests",
            source_paths=["app"],
            coverage_type="unknown_type",
        )
        db_path = tmp_path / "coverage.db"

        with pytest.raises(ValueError, match="Unknown coverage type"):
            create_strategy(config, db_path, tmp_path)

    def test_raises_for_usecase_without_use_cases(self, tmp_path: Path) -> None:
        """Factory raises ValueError when usecase type is used without use_cases."""
        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            coverage_type="usecase",
        )
        db_path = tmp_path / "coverage.db"

        with pytest.raises(ValueError, match="use_cases must be provided"):
            create_strategy(config, db_path, tmp_path)


class TestLineBranchTestStrategyLifecycle:
    """Tests for LineBranchTestStrategy lifecycle guards."""

    @pytest.fixture
    def strategy(self, tmp_path: Path) -> LineBranchTestStrategy:
        """Create a strategy instance for testing."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            coverage_type="line_branch",
            min_line_per_function=80.0,
            min_branch_per_function=70.0,
        )
        return LineBranchTestStrategy(config, tmp_path / "coverage.db", tmp_path, first_tier=True)

    def test_collect_results_before_run_tests_raises(
        self, strategy: LineBranchTestStrategy
    ) -> None:
        """collect_results() raises if run_tests() not called."""
        with pytest.raises(RuntimeError, match=r"run_tests.*must be called"):
            strategy.collect_results()

    def test_validate_before_collect_results_raises(self, strategy: LineBranchTestStrategy) -> None:
        """validate() raises if collect_results() not called."""
        with pytest.raises(RuntimeError, match=r"collect_results.*must be called"):
            strategy.validate()

    def test_build_summary_before_collect_results_raises(
        self, strategy: LineBranchTestStrategy
    ) -> None:
        """build_summary() raises if collect_results() not called."""
        with pytest.raises(RuntimeError, match=r"collect_results.*must be called"):
            strategy.build_summary()

    def test_initial_state(self, strategy: LineBranchTestStrategy) -> None:
        """Strategy starts with correct initial state."""
        assert strategy._tests_ran is False
        assert strategy._results_collected is False
        assert strategy._failures == []
        assert strategy.test_summary is None
        assert strategy.coverage_result is None

    def test_collect_results_raises_when_coverage_json_missing(
        self, strategy: LineBranchTestStrategy, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """collect_results() raises RuntimeError when coverage JSON is missing.

        This ensures a stronger lifecycle invariant: _results_collected remains
        False when results could not actually be collected, rather than deferring
        the error to build_summary().
        """
        # Simulate that run_tests() was called successfully
        strategy._tests_ran = True

        # Mock _run_command to avoid calling real uv/coverage binaries
        import scripts.dev.test_runner.test_strategies as ts

        monkeypatch.setattr(ts, "_run_command", lambda *a, **k: None)

        # collect_results() should raise because no coverage JSON file exists
        with pytest.raises(RuntimeError, match=r"Coverage JSON report could not be generated"):
            strategy.collect_results()

        # Verify lifecycle invariant: _tests_ran is True, _results_collected is False
        assert strategy._tests_ran is True
        assert strategy._results_collected is False
        assert strategy.coverage_result is None


class TestIntegrationTestStrategyLifecycle:
    """Tests for IntegrationTestStrategy lifecycle guards."""

    @pytest.fixture
    def strategy(self, tmp_path: Path) -> IntegrationTestStrategy:
        """Create a strategy instance for testing."""
        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            coverage_type="usecase",
            min_usecase=100.0,
        )
        use_cases = [
            UseCase(
                id="UC-TEST-001",
                endpoint="/test",
                method="GET",
                description="Test",
                test_tier="integration",
            )
        ]
        return IntegrationTestStrategy(config, tmp_path / "coverage.db", tmp_path, use_cases)

    def test_initial_state(self, strategy: IntegrationTestStrategy) -> None:
        """Strategy starts with correct initial state."""
        assert strategy._tests_ran is False
        assert strategy._results_collected is False
        assert strategy._failures == []
        assert strategy.test_summary is None
        assert strategy.usecase_result is None
        assert len(strategy.use_cases) == 1

    def test_collect_results_before_run_tests_raises(
        self, strategy: IntegrationTestStrategy
    ) -> None:
        """collect_results() raises if run_tests() not called."""
        with pytest.raises(RuntimeError, match=r"run_tests.*must be called"):
            strategy.collect_results()

    def test_validate_before_collect_results_raises(
        self, strategy: IntegrationTestStrategy
    ) -> None:
        """validate() raises if collect_results() not called."""
        with pytest.raises(RuntimeError, match=r"collect_results.*must be called"):
            strategy.validate()

    def test_build_summary_before_collect_results_raises(
        self, strategy: IntegrationTestStrategy
    ) -> None:
        """build_summary() raises if collect_results() not called."""
        with pytest.raises(RuntimeError, match=r"collect_results.*must be called"):
            strategy.build_summary()


class TestLineBranchTestStrategyBuildSummary:
    """Tests for LineBranchTestStrategy.build_summary() output format."""

    def test_build_summary_has_all_required_fields(self, tmp_path: Path) -> None:
        """build_summary() returns dict with all cc_tier_summary schema fields."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            coverage_type="line_branch",
            min_line_per_function=80.0,
            min_branch_per_function=70.0,
        )
        strategy = LineBranchTestStrategy(
            config, tmp_path / "coverage.db", tmp_path, first_tier=True
        )

        # Manually set state as if lifecycle completed
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.coverage_result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=80,
            missing_lines=20,
            line_coverage_pct=80.0,
            total_branches=50,
            covered_branches=35,
            missing_branches=15,
            branch_coverage_pct=70.0,
            files={},
            functions={
                "app/test.py::test_func": {
                    "name": "test_func",
                    "file": "app/test.py",
                    "line_coverage": 90.0,
                    "branch_coverage": 80.0,
                }
            },
        )

        summary = strategy.build_summary()

        # Check all required fields
        required_fields = [
            "coverage_type",
            "total_functions",
            "passing_functions",
            "failing_functions",
            "overall_line_pct",
            "overall_branch_pct",
            "total_tests",
            "tests_passed",
            "tests_failed",
            "tier_pass",
            "total_usecases",
            "usecases_covered",
        ]
        for field in required_fields:
            assert field in summary, f"Missing field: {field}"

        assert summary["coverage_type"] == "line_branch"
        assert summary["total_usecases"] == 0  # Default for line_branch
        assert summary["usecases_covered"] == 0  # Default for line_branch

    def test_build_summary_tier_pass_clean_run(self, tmp_path: Path) -> None:
        """tier_pass is 1 when no coverage failures and no test failures."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            coverage_type="line_branch",
            min_line_per_function=80.0,
            min_branch_per_function=70.0,
        )
        strategy = LineBranchTestStrategy(
            config, tmp_path / "coverage.db", tmp_path, first_tier=True
        )

        # Set state as if lifecycle completed with passing coverage
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy._failures = []  # No coverage failures
        strategy.test_summary = TestSummary(total=10, passed=10, failed=0, errors=0, skipped=0)
        strategy.coverage_result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=90,
            missing_lines=10,
            line_coverage_pct=90.0,
            total_branches=50,
            covered_branches=40,
            missing_branches=10,
            branch_coverage_pct=80.0,
            files={},
            functions={
                "app/test.py::good_func": {
                    "name": "good_func",
                    "file": "app/test.py",
                    "line_coverage": 95.0,  # Above 80% threshold
                    "branch_coverage": 85.0,  # Above 70% threshold
                }
            },
        )

        summary = strategy.build_summary()

        assert summary["tier_pass"] == 1

    def test_build_summary_tier_pass_with_coverage_failures(self, tmp_path: Path) -> None:
        """tier_pass is 0 when coverage failures exist (even with no test failures)."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            coverage_type="line_branch",
            min_line_per_function=80.0,
            min_branch_per_function=70.0,
        )
        strategy = LineBranchTestStrategy(
            config, tmp_path / "coverage.db", tmp_path, first_tier=True
        )

        strategy._tests_ran = True
        strategy._results_collected = True
        strategy._failures = ["unit: Function app/test.py::bad_func line coverage 50.0% < 80.0%"]
        strategy.test_summary = TestSummary(total=10, passed=10, failed=0, errors=0, skipped=0)
        strategy.coverage_result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=50,
            missing_lines=50,
            line_coverage_pct=50.0,
            total_branches=50,
            covered_branches=25,
            missing_branches=25,
            branch_coverage_pct=50.0,
            files={},
            functions={
                "app/test.py::bad_func": {
                    "name": "bad_func",
                    "file": "app/test.py",
                    "line_coverage": 50.0,  # Below 80% threshold
                    "branch_coverage": 50.0,  # Below 70% threshold
                }
            },
        )

        summary = strategy.build_summary()

        assert summary["tier_pass"] == 0

    def test_build_summary_tier_pass_with_test_failures(self, tmp_path: Path) -> None:
        """tier_pass is 0 when test failures exist (even with no coverage failures)."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            coverage_type="line_branch",
            min_line_per_function=80.0,
            min_branch_per_function=70.0,
        )
        strategy = LineBranchTestStrategy(
            config, tmp_path / "coverage.db", tmp_path, first_tier=True
        )

        strategy._tests_ran = True
        strategy._results_collected = True
        strategy._failures = []  # No coverage failures
        strategy.test_summary = TestSummary(total=10, passed=8, failed=2, errors=0, skipped=0)
        strategy.coverage_result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=90,
            missing_lines=10,
            line_coverage_pct=90.0,
            total_branches=50,
            covered_branches=40,
            missing_branches=10,
            branch_coverage_pct=80.0,
            files={},
            functions={
                "app/test.py::good_func": {
                    "name": "good_func",
                    "file": "app/test.py",
                    "line_coverage": 95.0,
                    "branch_coverage": 85.0,
                }
            },
        )

        summary = strategy.build_summary()

        assert summary["tier_pass"] == 0


class TestIntegrationTestStrategyBuildSummary:
    """Tests for IntegrationTestStrategy.build_summary() output format."""

    def test_build_summary_has_all_required_fields(self, tmp_path: Path) -> None:
        """build_summary() returns dict with all cc_tier_summary schema fields."""
        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            coverage_type="usecase",
            min_usecase=100.0,
        )
        use_cases: list[UseCase] = []
        strategy = IntegrationTestStrategy(config, tmp_path / "coverage.db", tmp_path, use_cases)

        # Manually set state as if lifecycle completed
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.usecase_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=10,
            covered_cases=8,
            uncovered_cases=["UC-TEST-001", "UC-TEST-002"],
            coverage_pct=80.0,
        )

        summary = strategy.build_summary()

        # Check all required fields
        required_fields = [
            "coverage_type",
            "total_usecases",
            "usecases_covered",
            "tier_pass",
            "total_functions",
            "passing_functions",
            "failing_functions",
            "overall_line_pct",
            "overall_branch_pct",
            "total_tests",
            "tests_passed",
            "tests_failed",
        ]
        for field in required_fields:
            assert field in summary, f"Missing field: {field}"

        assert summary["coverage_type"] == "usecase"
        assert summary["total_usecases"] == 10
        assert summary["usecases_covered"] == 8
        assert summary["total_functions"] == 0  # Default for usecase

    def test_build_summary_tier_pass_when_no_failures(self, tmp_path: Path) -> None:
        """tier_pass is 1 when no coverage failures exist (validate() passed or skipped)."""
        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            coverage_type="usecase",
            min_usecase=80.0,
        )
        use_cases: list[UseCase] = []
        strategy = IntegrationTestStrategy(config, tmp_path / "coverage.db", tmp_path, use_cases)

        strategy._tests_ran = True
        strategy._results_collected = True
        strategy._failures = []  # No coverage failures (validate passed or --no-validate used)
        strategy.usecase_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=10,
            covered_cases=9,
            uncovered_cases=["UC-010"],
            coverage_pct=90.0,  # Above 80% threshold
        )

        summary = strategy.build_summary()

        assert summary["tier_pass"] == 1

    def test_build_summary_tier_pass_when_failures_exist(self, tmp_path: Path) -> None:
        """tier_pass is 0 when coverage failures exist (from validate())."""
        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            coverage_type="usecase",
            min_usecase=100.0,
        )
        use_cases: list[UseCase] = []
        strategy = IntegrationTestStrategy(config, tmp_path / "coverage.db", tmp_path, use_cases)

        strategy._tests_ran = True
        strategy._results_collected = True
        # Simulate failures populated by validate()
        strategy._failures = [
            "integration: Use-case coverage 80.0% < 100.0% minimum",
            "  - Uncovered: UC-001",
            "  - Uncovered: UC-002",
        ]
        strategy.usecase_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=10,
            covered_cases=8,
            uncovered_cases=["UC-001", "UC-002"],
            coverage_pct=80.0,  # Below 100% threshold
        )

        summary = strategy.build_summary()

        assert summary["tier_pass"] == 0

    def test_build_summary_tier_pass_when_no_validate_skips_failures(self, tmp_path: Path) -> None:
        """tier_pass is 1 when --no-validate is used (validate() not called, _failures empty).

        This test verifies that when main() uses --no-validate and skips calling validate(),
        the tier_pass will be 1 even if coverage is below threshold, because _failures
        remains empty. This aligns IntegrationTestStrategy with LineBranchTestStrategy.
        """
        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            coverage_type="usecase",
            min_usecase=100.0,  # Threshold is 100%
        )
        use_cases: list[UseCase] = []
        strategy = IntegrationTestStrategy(config, tmp_path / "coverage.db", tmp_path, use_cases)

        strategy._tests_ran = True
        strategy._results_collected = True
        # Simulate --no-validate: validate() not called, so _failures remains empty
        strategy._failures = []
        strategy.usecase_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=10,
            covered_cases=8,
            uncovered_cases=["UC-001", "UC-002"],
            coverage_pct=80.0,  # Below 100% threshold, but validate() was not called
        )

        summary = strategy.build_summary()

        # With --no-validate, tier_pass should be 1 because _failures is empty
        assert summary["tier_pass"] == 1


class TestLineBranchTestStrategyValidationFailures:
    """Tests for LineBranchTestStrategy.validate() failure scenarios."""

    def test_validate_returns_failures_when_line_coverage_below_threshold(
        self, tmp_path: Path
    ) -> None:
        """validate() returns failure message when line coverage is below threshold."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            coverage_type="line_branch",
            min_line_per_function=80.0,
            min_branch_per_function=70.0,
        )
        strategy = LineBranchTestStrategy(
            config, tmp_path / "coverage.db", tmp_path, first_tier=True
        )

        # Set state as if lifecycle completed with low coverage
        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.coverage_result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=50,
            missing_lines=50,
            line_coverage_pct=50.0,
            total_branches=50,
            covered_branches=40,
            missing_branches=10,
            branch_coverage_pct=80.0,
            files={},
            functions={
                "app/service.py::process_data": {
                    "name": "process_data",
                    "file": "app/service.py",
                    "start_line": 10,
                    "end_line": 30,
                    "line_coverage": 60.0,  # Below 80% threshold
                    "branch_coverage": 90.0,  # Above 70% threshold
                    "missing_lines": [15, 16, 17],
                    "missing_branches": [],
                }
            },
        )

        failures = strategy.validate()

        assert len(failures) == 1
        assert "app/service.py::process_data" in failures[0]
        assert "line coverage" in failures[0]
        assert "60.0%" in failures[0]
        assert "80.0%" in failures[0]

    def test_validate_returns_failures_when_branch_coverage_below_threshold(
        self, tmp_path: Path
    ) -> None:
        """validate() returns failure message when branch coverage is below threshold."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            coverage_type="line_branch",
            min_line_per_function=80.0,
            min_branch_per_function=70.0,
        )
        strategy = LineBranchTestStrategy(
            config, tmp_path / "coverage.db", tmp_path, first_tier=True
        )

        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.coverage_result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=90,
            missing_lines=10,
            line_coverage_pct=90.0,
            total_branches=50,
            covered_branches=25,
            missing_branches=25,
            branch_coverage_pct=50.0,
            files={},
            functions={
                "app/service.py::handle_request": {
                    "name": "handle_request",
                    "file": "app/service.py",
                    "start_line": 40,
                    "end_line": 60,
                    "line_coverage": 95.0,  # Above 80% threshold
                    "branch_coverage": 50.0,  # Below 70% threshold
                    "missing_lines": [],
                    "missing_branches": [(45, 46), (50, 51)],
                }
            },
        )

        failures = strategy.validate()

        assert len(failures) == 1
        assert "app/service.py::handle_request" in failures[0]
        assert "branch coverage" in failures[0]
        assert "50.0%" in failures[0]
        assert "70.0%" in failures[0]

    def test_validate_returns_multiple_failures_for_multiple_functions(
        self, tmp_path: Path
    ) -> None:
        """validate() returns multiple failure messages when multiple functions fail."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            coverage_type="line_branch",
            min_line_per_function=80.0,
            min_branch_per_function=70.0,
        )
        strategy = LineBranchTestStrategy(
            config, tmp_path / "coverage.db", tmp_path, first_tier=True
        )

        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.coverage_result = CoverageResult(
            suite_name="unit",
            total_lines=200,
            covered_lines=100,
            missing_lines=100,
            line_coverage_pct=50.0,
            total_branches=100,
            covered_branches=50,
            missing_branches=50,
            branch_coverage_pct=50.0,
            files={},
            functions={
                "app/service.py::func_a": {
                    "name": "func_a",
                    "file": "app/service.py",
                    "start_line": 10,
                    "end_line": 20,
                    "line_coverage": 50.0,  # Fail line
                    "branch_coverage": 90.0,
                    "missing_lines": [15],
                    "missing_branches": [],
                },
                "app/service.py::func_b": {
                    "name": "func_b",
                    "file": "app/service.py",
                    "start_line": 30,
                    "end_line": 40,
                    "line_coverage": 40.0,  # Fail line
                    "branch_coverage": 60.0,  # Fail branch
                    "missing_lines": [35],
                    "missing_branches": [(36, 37)],
                },
            },
        )

        failures = strategy.validate()

        # func_a: 1 failure (line)
        # func_b: 2 failures (line + branch)
        assert len(failures) == 3
        line_failures = [f for f in failures if "line coverage" in f]
        branch_failures = [f for f in failures if "branch coverage" in f]
        assert len(line_failures) == 2
        assert len(branch_failures) == 1

    def test_validate_returns_empty_when_all_thresholds_met(self, tmp_path: Path) -> None:
        """validate() returns empty list when all functions meet thresholds."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            coverage_type="line_branch",
            min_line_per_function=80.0,
            min_branch_per_function=70.0,
        )
        strategy = LineBranchTestStrategy(
            config, tmp_path / "coverage.db", tmp_path, first_tier=True
        )

        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.coverage_result = CoverageResult(
            suite_name="unit",
            total_lines=100,
            covered_lines=95,
            missing_lines=5,
            line_coverage_pct=95.0,
            total_branches=50,
            covered_branches=45,
            missing_branches=5,
            branch_coverage_pct=90.0,
            files={},
            functions={
                "app/service.py::good_func": {
                    "name": "good_func",
                    "file": "app/service.py",
                    "start_line": 10,
                    "end_line": 30,
                    "line_coverage": 95.0,  # Above 80%
                    "branch_coverage": 90.0,  # Above 70%
                    "missing_lines": [],
                    "missing_branches": [],
                }
            },
        )

        failures = strategy.validate()

        assert failures == []


class TestIntegrationTestStrategyValidationFailures:
    """Tests for IntegrationTestStrategy.validate() failure scenarios."""

    def test_validate_returns_failure_when_usecase_coverage_below_threshold(
        self, tmp_path: Path
    ) -> None:
        """validate() returns failure message when use-case coverage is below threshold."""
        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            coverage_type="usecase",
            min_usecase=100.0,
        )
        use_cases: list[UseCase] = []
        strategy = IntegrationTestStrategy(config, tmp_path / "coverage.db", tmp_path, use_cases)

        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.usecase_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=10,
            covered_cases=8,
            uncovered_cases=["UC-001", "UC-002"],
            coverage_pct=80.0,  # Below 100% threshold
        )

        failures = strategy.validate()

        assert len(failures) == 3  # 1 main message + 2 uncovered items
        assert "Use-case coverage 80.0%" in failures[0]
        assert "100.0% minimum" in failures[0]
        assert "UC-001" in failures[1]
        assert "UC-002" in failures[2]

    def test_validate_truncates_uncovered_usecases_to_10(self, tmp_path: Path) -> None:
        """validate() truncates uncovered use-case list to 10 with '... and N more'."""
        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            coverage_type="usecase",
            min_usecase=100.0,
        )
        use_cases: list[UseCase] = []
        strategy = IntegrationTestStrategy(config, tmp_path / "coverage.db", tmp_path, use_cases)

        strategy._tests_ran = True
        strategy._results_collected = True
        # Create 15 uncovered use cases
        uncovered = [f"UC-{i:03d}" for i in range(15)]
        strategy.usecase_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=20,
            covered_cases=5,
            uncovered_cases=uncovered,
            coverage_pct=25.0,
        )

        failures = strategy.validate()

        # 1 main message + 10 uncovered items + 1 "... and N more"
        assert len(failures) == 12
        assert "Use-case coverage 25.0%" in failures[0]
        # First 10 uncovered should be listed
        for i in range(10):
            assert f"UC-{i:03d}" in failures[i + 1]
        # Last message should indicate remaining count
        assert "... and 5 more" in failures[11]

    def test_validate_returns_empty_when_usecase_threshold_met(self, tmp_path: Path) -> None:
        """validate() returns empty list when use-case coverage meets threshold."""
        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            coverage_type="usecase",
            min_usecase=80.0,
        )
        use_cases: list[UseCase] = []
        strategy = IntegrationTestStrategy(config, tmp_path / "coverage.db", tmp_path, use_cases)

        strategy._tests_ran = True
        strategy._results_collected = True
        strategy.usecase_result = UseCaseCoverageResult(
            tier="integration",
            total_cases=10,
            covered_cases=9,
            uncovered_cases=["UC-010"],
            coverage_pct=90.0,  # Above 80% threshold
        )

        failures = strategy.validate()

        assert failures == []
