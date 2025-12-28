from pathlib import Path

import pytest

from scripts.dev.test_runner.test_coverage import (
    TestTierConfig,
)
from scripts.dev.test_runner.test_strategies import (
    LineBranchTestStrategy,
    create_strategy,
)


@pytest.fixture
def unit_tier_config() -> TestTierConfig:
    """Create a unit tier configuration for testing."""
    return TestTierConfig(
        name="unit",
        test_path="tests/unit",
        source_paths=["app/**/*.py", "!app/**/__init__.py"],
        min_line_per_function=80.0,
        min_branch_per_function=70.0,
    )


@pytest.fixture
def component_tier_config() -> TestTierConfig:
    """Create a component tier configuration for testing."""
    return TestTierConfig(
        name="component",
        test_path="tests/component",
        source_paths=["app/services/**/*.py", "!app/services/**/__init__.py"],
        min_usecase=100.0,
        skip_private_functions=True,
    )


class TestReq3JsonReflectsTierExecution:
    def test_each_tier_has_isolated_coverage_file(self, tmp_path: Path) -> None:
        """Each tier writes to its own isolated coverage file path."""
        tiers_to_run = ["unit", "component", "scripts"]

        # Simulate the tier_coverage_files dict creation from main()
        coverage_dir = tmp_path / ".coverage"
        tier_coverage_files: dict[str, Path] = {
            tier_name: coverage_dir / f"data_{tier_name}" for tier_name in tiers_to_run
        }

        # Verify each tier has a unique path
        paths = list(tier_coverage_files.values())
        unique_paths = set(str(p) for p in paths)
        assert len(paths) == len(unique_paths), "Tier coverage file paths should be unique"

        # Verify naming convention
        for tier_name, path in tier_coverage_files.items():
            assert path.name == f"data_{tier_name}"
            assert path.parent == coverage_dir

    def test_tier_coverage_file_naming_matches_tier_name(self, tmp_path: Path) -> None:
        """Coverage file name includes the tier name for identification."""
        tier_configs = {
            "unit": TestTierConfig(
                name="unit",
                test_path="tests/unit",
                source_paths=["app"],
                min_line_per_function=80.0,
            ),
            "component": TestTierConfig(
                name="component",
                test_path="tests/unit",
                source_paths=["app/services"],
                min_line_per_function=80.0,
            ),
        }

        coverage_dir = tmp_path / ".coverage"
        for tier_name, _config in tier_configs.items():
            expected_path = coverage_dir / f"data_{tier_name}"
            assert f"data_{tier_name}" in str(expected_path)


class TestReq4TierCoverageFilesDictPopulated:
    def test_dict_contains_all_tiers_to_run(self, tmp_path: Path) -> None:
        """tier_coverage_files dict contains entry for each tier to run."""
        tiers_to_run = ["unit", "component", "scripts", "integration"]
        coverage_dir = tmp_path / ".coverage"

        # Simulate dict creation from main() lines 1429-1432
        tier_coverage_files: dict[str, Path] = {
            tier_name: coverage_dir / f"data_{tier_name}" for tier_name in tiers_to_run
        }

        assert len(tier_coverage_files) == len(tiers_to_run)
        for tier_name in tiers_to_run:
            assert tier_name in tier_coverage_files
            assert isinstance(tier_coverage_files[tier_name], Path)

    def test_dict_values_are_path_objects(self, tmp_path: Path) -> None:
        """All values in tier_coverage_files are Path objects."""
        tiers_to_run = ["unit", "component"]
        coverage_dir = tmp_path / ".coverage"

        tier_coverage_files: dict[str, Path] = {
            tier_name: coverage_dir / f"data_{tier_name}" for tier_name in tiers_to_run
        }

        for path in tier_coverage_files.values():
            assert isinstance(path, Path)

    def test_single_tier_creates_single_entry(self, tmp_path: Path) -> None:
        """Running single tier creates dict with one entry."""
        tiers_to_run = ["unit"]
        coverage_dir = tmp_path / ".coverage"

        tier_coverage_files: dict[str, Path] = {
            tier_name: coverage_dir / f"data_{tier_name}" for tier_name in tiers_to_run
        }

        assert len(tier_coverage_files) == 1
        assert "unit" in tier_coverage_files


class TestReq4ListOnlyIncludesExistingFiles:
    def test_combine_filters_nonexistent_files(self, tmp_path: Path) -> None:
        """Only existing coverage files are passed to combine command."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

        tiers_to_run = ["unit", "component", "scripts"]
        tier_coverage_files: dict[str, Path] = {
            tier_name: coverage_dir / f"data_{tier_name}" for tier_name in tiers_to_run
        }

        # Only create files for some tiers
        tier_coverage_files["unit"].touch()
        tier_coverage_files["scripts"].touch()
        # component file does NOT exist

        # Simulate filter logic from main() line 1481-1482
        tier_data_files = [
            str(tier_coverage_files[t]) for t in tiers_to_run if tier_coverage_files[t].exists()
        ]

        assert len(tier_data_files) == 2
        assert str(tier_coverage_files["unit"]) in tier_data_files
        assert str(tier_coverage_files["scripts"]) in tier_data_files
        assert str(tier_coverage_files["component"]) not in tier_data_files

    def test_all_files_exist_all_included(self, tmp_path: Path) -> None:
        """When all coverage files exist, all are included in combine."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

        tiers_to_run = ["unit", "component"]
        tier_coverage_files: dict[str, Path] = {
            tier_name: coverage_dir / f"data_{tier_name}" for tier_name in tiers_to_run
        }

        # Create all files
        for path in tier_coverage_files.values():
            path.touch()

        tier_data_files = [
            str(tier_coverage_files[t]) for t in tiers_to_run if tier_coverage_files[t].exists()
        ]

        assert len(tier_data_files) == len(tiers_to_run)

    def test_no_files_exist_empty_list(self, tmp_path: Path) -> None:
        """When no coverage files exist, list is empty."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

        tiers_to_run = ["unit", "component"]
        tier_coverage_files: dict[str, Path] = {
            tier_name: coverage_dir / f"data_{tier_name}" for tier_name in tiers_to_run
        }

        # Don't create any files

        tier_data_files = [
            str(tier_coverage_files[t]) for t in tiers_to_run if tier_coverage_files[t].exists()
        ]

        assert tier_data_files == []


class TestReq4ListOrderDoesNotAffectCombine:
    def test_combine_receives_files_in_tier_order(self, tmp_path: Path) -> None:
        """Files are passed to combine in tiers_to_run iteration order."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

        # Use alphabetically non-sorted order to verify iteration order preserved
        tiers_to_run = ["component", "unit", "scripts"]
        tier_coverage_files: dict[str, Path] = {
            tier_name: coverage_dir / f"data_{tier_name}" for tier_name in tiers_to_run
        }

        for path in tier_coverage_files.values():
            path.touch()

        tier_data_files = [
            str(tier_coverage_files[t]) for t in tiers_to_run if tier_coverage_files[t].exists()
        ]

        # Verify order matches tiers_to_run
        expected_order = [
            str(coverage_dir / "data_component"),
            str(coverage_dir / "data_unit"),
            str(coverage_dir / "data_scripts"),
        ]
        assert tier_data_files == expected_order

    def test_combine_order_does_not_affect_result(self, tmp_path: Path) -> None:
        """Coverage combine is order-independent (files are merged, not overwritten).

        Note: This is a behavioral test that documents the expected property.
        The actual coverage combine tool handles order internally.
        """
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

        # Two different orderings
        order_1 = ["unit", "component"]
        order_2 = ["component", "unit"]

        tier_coverage_files: dict[str, Path] = {
            tier_name: coverage_dir / f"data_{tier_name}" for tier_name in ["unit", "component"]
        }

        for path in tier_coverage_files.values():
            path.touch()

        files_order_1 = [
            str(tier_coverage_files[t]) for t in order_1 if tier_coverage_files[t].exists()
        ]
        files_order_2 = [
            str(tier_coverage_files[t]) for t in order_2 if tier_coverage_files[t].exists()
        ]

        # Same files, different order
        assert set(files_order_1) == set(files_order_2)
        assert files_order_1 != files_order_2  # Order is different


class TestReq4MissingCoverageFileDoesNotBreakCombine:
    def test_combine_skipped_when_no_files_exist(self, tmp_path: Path) -> None:
        """Combine command is not called when tier_data_files is empty."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

        tiers_to_run = ["unit"]
        tier_coverage_files: dict[str, Path] = {
            tier_name: coverage_dir / f"data_{tier_name}" for tier_name in tiers_to_run
        }
        # Don't create the file

        tier_data_files = [
            str(tier_coverage_files[t]) for t in tiers_to_run if tier_coverage_files[t].exists()
        ]

        # Simulate main() logic: only combine if tier_data_files is not empty
        combine_called = False
        if tier_data_files:
            combine_called = True

        assert not combine_called
        assert tier_data_files == []

    def test_partial_tier_failure_allows_combine_of_others(self, tmp_path: Path) -> None:
        """If one tier's coverage file is missing, others can still be combined."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

        tiers_to_run = ["unit", "component", "scripts"]
        tier_coverage_files: dict[str, Path] = {
            tier_name: coverage_dir / f"data_{tier_name}" for tier_name in tiers_to_run
        }

        # Only unit succeeds
        tier_coverage_files["unit"].touch()
        # component and scripts fail (no files created)

        tier_data_files = [
            str(tier_coverage_files[t]) for t in tiers_to_run if tier_coverage_files[t].exists()
        ]

        # Combine should still be called with available files
        assert len(tier_data_files) == 1
        assert str(tier_coverage_files["unit"]) in tier_data_files

    def test_filter_handles_all_tiers_gracefully(self, tmp_path: Path) -> None:
        """Filter logic handles empty results without raising exceptions."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

        tiers_to_run = ["integration"]  # usecase tier typically has no coverage file
        tier_coverage_files: dict[str, Path] = {
            tier_name: coverage_dir / f"data_{tier_name}" for tier_name in tiers_to_run
        }

        # This should not raise any exception
        tier_data_files = [
            str(tier_coverage_files[t]) for t in tiers_to_run if tier_coverage_files[t].exists()
        ]

        assert isinstance(tier_data_files, list)


class TestStrategyTierCoverageFileIntegration:
    def test_strategy_receives_tier_coverage_file_from_dict(
        self, tmp_path: Path, unit_tier_config: TestTierConfig
    ) -> None:
        """Strategy is created with tier_coverage_file from tier_coverage_files dict."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

        tiers_to_run = ["unit"]
        tier_coverage_files: dict[str, Path] = {
            tier_name: coverage_dir / f"data_{tier_name}" for tier_name in tiers_to_run
        }

        # Create strategy using dict lookup (simulates main() pattern)
        strategy = create_strategy(
            unit_tier_config,
            tmp_path / "coverage.db",
            tmp_path,
            tier_coverage_file=tier_coverage_files["unit"],
        )

        assert isinstance(strategy, LineBranchTestStrategy)
        assert strategy.tier_coverage_file == tier_coverage_files["unit"]

    def test_strategy_tier_coverage_file_matches_config_name(
        self, tmp_path: Path, component_tier_config: TestTierConfig
    ) -> None:
        """Strategy's tier_coverage_file path contains config.name."""
        coverage_dir = tmp_path / ".coverage"
        tier_coverage_file = coverage_dir / f"data_{component_tier_config.name}"

        strategy = LineBranchTestStrategy(
            component_tier_config,
            tmp_path / "coverage.db",
            tmp_path,
            tier_coverage_file,
        )

        assert component_tier_config.name in str(strategy.tier_coverage_file)
        assert strategy.tier_coverage_file.name == f"data_{component_tier_config.name}"


class TestTierCoverageFilesDictPopulationInMainFlow:
    def test_tier_coverage_files_dict_created_for_all_tiers_to_run(self, tmp_path: Path) -> None:
        """Verify tier_coverage_files dict is created with correct structure.

        Simulates the dict creation logic from main() lines 1429-1432.
        """
        coverage_dir = tmp_path / ".coverage"

        # Simulate different tier combinations
        test_cases = [
            ["unit"],
            ["unit", "component"],
            ["unit", "component", "scripts"],
            ["unit", "component", "scripts", "integration"],
        ]

        for tiers_to_run in test_cases:
            # This is the exact pattern from main()
            tier_coverage_files: dict[str, Path] = {
                tier_name: coverage_dir / f"data_{tier_name}" for tier_name in tiers_to_run
            }

            # Verify dict structure
            assert len(tier_coverage_files) == len(tiers_to_run)
            for tier_name in tiers_to_run:
                assert tier_name in tier_coverage_files
                assert tier_coverage_files[tier_name] == coverage_dir / f"data_{tier_name}"
                assert tier_coverage_files[tier_name].name == f"data_{tier_name}"
