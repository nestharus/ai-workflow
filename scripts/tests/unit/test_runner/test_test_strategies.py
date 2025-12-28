from pathlib import Path

import pytest

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


class TestLineBranchTestStrategyLifecycle:
    @pytest.fixture
    def strategy(self, tmp_path: Path) -> LineBranchTestStrategy:
        """Create a strategy instance for testing."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
            min_branch_per_function=70.0,
        )
        return LineBranchTestStrategy(
            config, tmp_path / "coverage.db", tmp_path, tmp_path / "data_unit"
        )

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


class TestIntegrationTestStrategyCollectResults:
    def test_collect_results_scans_usecases_and_writes_coverage(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """collect_results() scans for use-case markers and writes to database.

        This covers lines 699-730 in test_strategies.py.
        """
        from scripts.dev.test_runner import coverage_db
        from scripts.dev.test_runner import test_strategies as ts

        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            min_usecase=100.0,
        )
        use_cases = [
            UseCase(
                id="UC-INT-001",
                endpoint="/test",
                method="GET",
                description="Test use case 1",
                test_tier="integration",
            ),
            UseCase(
                id="UC-INT-002",
                endpoint="/test2",
                method="POST",
                description="Test use case 2",
                test_tier="integration",
            ),
        ]
        db_path = tmp_path / "coverage.db"
        strategy = IntegrationTestStrategy(config, db_path, tmp_path, use_cases)

        # Mark tests as run
        strategy._tests_ran = True

        # Mock _scan_tests_for_usecases to return coverage for first use case
        mock_scan_result = {
            "UC-INT-001": [
                {"file": "tests/integration/test_api.py", "test_function": "test_get_api"}
            ]
        }
        monkeypatch.setattr(ts, "_scan_tests_for_usecases", lambda *args: mock_scan_result)

        # Mock write_usecase_coverage to track calls
        written_usecases = []

        def mock_write_usecase_coverage(db_path, uc_id, covered, test_file, test_function):
            written_usecases.append(
                {
                    "uc_id": uc_id,
                    "covered": covered,
                    "test_file": test_file,
                    "test_function": test_function,
                }
            )

        monkeypatch.setattr(coverage_db, "write_usecase_coverage", mock_write_usecase_coverage)
        monkeypatch.setattr(coverage_db, "write_tier_config", lambda *args: None)

        # Call collect_results
        strategy.collect_results()

        # Verify state
        assert strategy._results_collected is True
        assert strategy.usecase_result is not None
        assert strategy.usecase_result.total_cases == 2
        assert strategy.usecase_result.covered_cases == 1

        # Verify write_usecase_coverage was called for both use cases
        assert len(written_usecases) == 2

        # First use case should be covered
        covered_uc = next(uc for uc in written_usecases if uc["uc_id"] == "UC-INT-001")
        assert covered_uc["covered"] is True
        assert covered_uc["test_file"] == "tests/integration/test_api.py"
        assert covered_uc["test_function"] == "test_get_api"

        # Second use case should not be covered
        uncovered_uc = next(uc for uc in written_usecases if uc["uc_id"] == "UC-INT-002")
        assert uncovered_uc["covered"] is False
        assert uncovered_uc["test_file"] is None
        assert uncovered_uc["test_function"] is None


class TestCreateStrategyUnknownType:
    def test_create_strategy_raises_for_unknown_coverage_type(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """create_strategy() raises ValueError for unknown coverage type.

        This covers lines 891-892 in test_strategies.py.
        """
        # Create a config that would have an unknown coverage type
        # We need to manually set coverage_type by overriding the property
        config = TestTierConfig(
            name="unknown",
            test_path="tests/unknown",
            source_paths=["app"],
            min_line_per_function=80.0,
        )

        # Monkeypatch the coverage_type property to return an unknown type
        monkeypatch.setattr(TestTierConfig, "coverage_type", property(lambda self: "unknown_type"))

        db_path = tmp_path / "coverage.db"

        with pytest.raises(ValueError, match=r"Unknown coverage type: unknown_type"):
            create_strategy(config, db_path, tmp_path, tier_coverage_file=tmp_path / "data")
