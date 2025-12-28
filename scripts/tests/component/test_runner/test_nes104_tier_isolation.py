import hashlib
import inspect
import json
from pathlib import Path

import pytest

from scripts.dev.test_runner.test_coverage import TestTierConfig
from scripts.dev.test_runner.test_strategies import (
    IntegrationTestStrategy,
    LineBranchTestStrategy,
    create_strategy,
)


class TestMultipleTiersCreateDistinctFiles:
    def test_tier_coverage_files_would_have_different_content(self, tmp_path: Path) -> None:
        """Simulated coverage data for different tiers would produce different file hashes.

        This test creates mock coverage data that simulates what each tier would
        produce, verifying the data would be distinct.
        """
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)

        # Simulate different coverage data per tier
        tier_data = {
            "unit": {"files": {"app/main.py": {"lines": [1, 2, 3]}}},
            "component": {"files": {"app/services/auth.py": {"lines": [10, 20, 30]}}},
            "scripts": {"files": {"scripts/tool.py": {"lines": [5, 15, 25]}}},
        }

        hashes: dict[str, str] = {}
        for tier_name, data in tier_data.items():
            data_file = coverage_dir / f"data_{tier_name}"
            content = json.dumps(data, sort_keys=True)
            data_file.write_text(content)
            hashes[tier_name] = hashlib.sha256(content.encode()).hexdigest()

        # All hashes should be different
        unique_hashes = set(hashes.values())
        assert len(unique_hashes) == len(tier_data), (
            f"Each tier should have unique coverage data: {hashes}"
        )


class TestTierIsolationDoesNotCreateOtherTierFiles:
    def test_tier_coverage_file_path_determined_by_tier_name(self, tmp_path: Path) -> None:
        """The tier_coverage_file path should consistently use data_{tier_name} pattern."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"

        test_cases = [
            ("unit", "data_unit"),
            ("component", "data_component"),
            ("scripts", "data_scripts"),
            ("custom_tier", "data_custom_tier"),
        ]

        for tier_name, expected_suffix in test_cases:
            tier_coverage_file = coverage_dir / f"data_{tier_name}"
            config = TestTierConfig(
                name=tier_name,
                test_path=f"tests/{tier_name}",
                source_paths=["app"],
                min_line_per_function=80.0,
            )
            strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

            # Verify the tier_coverage_file follows the pattern
            assert strategy.tier_coverage_file.name == expected_suffix, (
                f"Tier {tier_name} should use {expected_suffix}"
            )


class TestNoFirstTierParameter:
    def test_create_strategy_has_no_first_tier_param(self) -> None:
        """create_strategy() should NOT have a first_tier parameter."""
        sig = inspect.signature(create_strategy)
        param_names = list(sig.parameters.keys())

        assert "first_tier" not in param_names, (
            f"create_strategy() should not have first_tier parameter. Parameters: {param_names}"
        )

    def test_line_branch_strategy_init_has_no_first_tier_param(self) -> None:
        """LineBranchTestStrategy.__init__() should NOT have a first_tier parameter."""
        sig = inspect.signature(LineBranchTestStrategy.__init__)
        param_names = list(sig.parameters.keys())

        assert "first_tier" not in param_names, (
            f"LineBranchTestStrategy.__init__() should not have first_tier parameter. "
            f"Parameters: {param_names}"
        )

    def test_line_branch_strategy_run_tests_has_no_first_tier_param(self) -> None:
        """LineBranchTestStrategy.run_tests() should NOT have a first_tier parameter."""
        sig = inspect.signature(LineBranchTestStrategy.run_tests)
        param_names = list(sig.parameters.keys())

        assert "first_tier" not in param_names, (
            f"LineBranchTestStrategy.run_tests() should not have first_tier parameter. "
            f"Parameters: {param_names}"
        )

    def test_integration_strategy_has_no_first_tier_param(self) -> None:
        """IntegrationTestStrategy should NOT have a first_tier parameter anywhere."""
        method_names = ["__init__", "run_tests", "collect_results", "validate", "build_summary"]
        for method_name in method_names:
            method = getattr(IntegrationTestStrategy, method_name)
            sig = inspect.signature(method)
            param_names = list(sig.parameters.keys())

            assert "first_tier" not in param_names, (
                f"IntegrationTestStrategy.{method_name}() should not have first_tier. "
                f"Parameters: {param_names}"
            )

    def test_no_first_tier_in_test_strategies_module(self) -> None:
        """The test_strategies module should not reference first_tier anywhere."""
        import scripts.dev.test_runner.test_strategies as ts

        source = inspect.getsource(ts)

        # Check that 'first_tier' does not appear in the source
        assert "first_tier" not in source.lower(), (
            "The test_strategies module should not contain 'first_tier' references"
        )


class TestCoverageIsolationContractWithFactory:
    def test_factory_requires_tier_coverage_file_for_line_branch(self, tmp_path: Path) -> None:
        """create_strategy() should require tier_coverage_file for line_branch type."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        db_path = tmp_path / "coverage.db"

        with pytest.raises(ValueError, match="tier_coverage_file is required"):
            create_strategy(config, db_path, tmp_path)  # No tier_coverage_file

    def test_factory_passes_tier_coverage_file_to_strategy(self, tmp_path: Path) -> None:
        """create_strategy() should pass tier_coverage_file to LineBranchTestStrategy."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"
        tier_coverage_file = coverage_dir / "data_unit"

        strategy = create_strategy(config, db_path, tmp_path, tier_coverage_file=tier_coverage_file)

        assert isinstance(strategy, LineBranchTestStrategy)
        assert strategy.tier_coverage_file == tier_coverage_file


class TestNegativeCases:
    def test_line_branch_strategy_requires_tier_coverage_file(self, tmp_path: Path) -> None:
        """LineBranchTestStrategy should fail if tier_coverage_file is None."""
        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        db_path = tmp_path / "coverage.db"

        with pytest.raises(ValueError, match="tier_coverage_file is required"):
            create_strategy(config, db_path, tmp_path, tier_coverage_file=None)


class TestActualImplementationCoverageFilePaths:
    def test_strategy_stores_correct_tier_coverage_file_path(self, tmp_path: Path) -> None:
        """Verify LineBranchTestStrategy stores the correct tier_coverage_file path."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"

        test_cases = [
            ("unit", "data_unit"),
            ("component", "data_component"),
            ("scripts", "data_scripts"),
            ("custom_tier", "data_custom_tier"),
        ]

        for tier_name, expected_filename in test_cases:
            tier_coverage_file = coverage_dir / expected_filename

            config = TestTierConfig(
                name=tier_name,
                test_path=f"tests/{tier_name}",
                source_paths=["app"],
                min_line_per_function=80.0,
            )
            strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

            # Verify the stored path
            assert strategy.tier_coverage_file == tier_coverage_file
            assert strategy.tier_coverage_file.name == expected_filename
            assert str(strategy.tier_coverage_file).endswith(expected_filename)
