import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.test_runner.test_coverage import TestTierConfig
from scripts.dev.test_runner.test_strategies import (
    IntegrationTestStrategy,
    LineBranchTestStrategy,
    create_strategy,
)


class TestPerTierCoverageFileCreation:
    def test_unit_tier_uses_data_unit_file(self, tmp_path: Path) -> None:
        """Unit tier strategy should use .coverage/data_unit as COVERAGE_FILE."""
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

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        captured_env: dict[str, str] = {}

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            nonlocal captured_env
            captured_env = env or {}
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "scripts.dev.test_runner.test_strategies._run_command",
            side_effect=mock_run_command,
        ):
            strategy.run_tests()

        # Verify COVERAGE_FILE is set to tier-specific path
        assert "COVERAGE_FILE" in captured_env
        assert captured_env["COVERAGE_FILE"] == str(tier_coverage_file)
        assert captured_env["COVERAGE_FILE"].endswith("data_unit")

    def test_component_tier_uses_data_component_file(self, tmp_path: Path) -> None:
        """Component tier strategy should use .coverage/data_component as COVERAGE_FILE."""
        config = TestTierConfig(
            name="component",
            test_path="tests/component",
            source_paths=["app/services"],
            min_line_per_function=80.0,
        )
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"
        tier_coverage_file = coverage_dir / "data_component"

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        captured_env: dict[str, str] = {}

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            nonlocal captured_env
            captured_env = env or {}
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "scripts.dev.test_runner.test_strategies._run_command",
            side_effect=mock_run_command,
        ):
            strategy.run_tests()

        assert "COVERAGE_FILE" in captured_env
        assert captured_env["COVERAGE_FILE"] == str(tier_coverage_file)
        assert captured_env["COVERAGE_FILE"].endswith("data_component")

    def test_scripts_tier_uses_data_scripts_file(self, tmp_path: Path) -> None:
        """Scripts tier strategy should use .coverage/data_scripts as COVERAGE_FILE."""
        config = TestTierConfig(
            name="scripts",
            test_path="scripts/tests",
            source_paths=["scripts", "tools"],
            min_line_per_function=80.0,
        )
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"
        tier_coverage_file = coverage_dir / "data_scripts"

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        captured_env: dict[str, str] = {}

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            nonlocal captured_env
            captured_env = env or {}
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "scripts.dev.test_runner.test_strategies._run_command",
            side_effect=mock_run_command,
        ):
            strategy.run_tests()

        assert "COVERAGE_FILE" in captured_env
        assert captured_env["COVERAGE_FILE"] == str(tier_coverage_file)
        assert captured_env["COVERAGE_FILE"].endswith("data_scripts")


class TestMultipleTiersCreateDistinctFiles:
    def test_multiple_tiers_have_different_coverage_file_paths(self, tmp_path: Path) -> None:
        """Different tiers should write to different COVERAGE_FILE paths."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"

        tier_configs = [
            TestTierConfig(
                name="unit",
                test_path="tests/unit",
                source_paths=["app"],
                min_line_per_function=80.0,
            ),
            TestTierConfig(
                name="component",
                test_path="tests/unit",
                source_paths=["app/services"],
                min_line_per_function=80.0,
            ),
            TestTierConfig(
                name="scripts",
                test_path="scripts/tests",
                source_paths=["scripts"],
                min_line_per_function=80.0,
            ),
        ]

        captured_envs: dict[str, dict[str, str]] = {}

        for config in tier_configs:
            tier_coverage_file = coverage_dir / f"data_{config.name}"
            strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

            def make_mock(tier_name: str) -> Any:
                def mock_run_command(
                    cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
                ) -> MagicMock:
                    captured_envs[tier_name] = env or {}
                    result = MagicMock()
                    result.returncode = 0
                    return result

                return mock_run_command

            with patch(
                "scripts.dev.test_runner.test_strategies._run_command",
                side_effect=make_mock(config.name),
            ):
                strategy.run_tests()

        # Verify all tiers captured different COVERAGE_FILE paths
        coverage_files = [env["COVERAGE_FILE"] for env in captured_envs.values()]

        # All paths should be unique
        assert len(set(coverage_files)) == len(tier_configs), (
            f"Coverage files should be unique per tier: {coverage_files}"
        )

        # Each tier should have the correct suffix
        for tier_name, env in captured_envs.items():
            assert env["COVERAGE_FILE"].endswith(f"data_{tier_name}"), (
                f"Tier {tier_name} should write to data_{tier_name}"
            )


class TestOldSharedDataFileNotUsed:
    def test_tier_strategy_does_not_use_shared_data_file(self, tmp_path: Path) -> None:
        """LineBranchTestStrategy should NOT use .coverage/data as COVERAGE_FILE."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"

        # Old shared file (should NOT be used)
        shared_data_file = coverage_dir / "data"
        shared_data_file.touch()

        # Tier-specific file (SHOULD be used)
        tier_coverage_file = coverage_dir / "data_unit"

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        captured_env: dict[str, str] = {}

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            nonlocal captured_env
            captured_env = env or {}
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "scripts.dev.test_runner.test_strategies._run_command",
            side_effect=mock_run_command,
        ):
            strategy.run_tests()

        # Verify COVERAGE_FILE is NOT the shared data file
        assert captured_env["COVERAGE_FILE"] != str(shared_data_file), (
            "Strategy should NOT use shared .coverage/data file"
        )
        assert captured_env["COVERAGE_FILE"] == str(tier_coverage_file)

    def test_collect_results_uses_tier_specific_file_not_shared(self, tmp_path: Path) -> None:
        """collect_results() should use tier-specific coverage file for JSON generation."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"
        tier_coverage_file = coverage_dir / "data_unit"

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)
        strategy._tests_ran = True

        captured_env: dict[str, str] = {}

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            nonlocal captured_env
            captured_env = env or {}

            # Create the JSON file that collect_results() expects
            if "json" in cmd:
                json_path = coverage_dir / f"temp_{config.name}.json"
                json_path.write_text(
                    json.dumps(
                        {
                            "totals": {
                                "num_statements": 100,
                                "covered_lines": 80,
                                "missing_lines": 20,
                                "percent_covered": 80.0,
                                "num_branches": 50,
                                "covered_branches": 40,
                                "num_partial_branches": 5,
                                "missing_branches": 5,
                                "percent_covered_branches": 80.0,
                            },
                            "files": {},
                        }
                    )
                )

            result = MagicMock()
            result.returncode = 0
            return result

        with (
            patch(
                "scripts.dev.test_runner.test_strategies._run_command",
                side_effect=mock_run_command,
            ),
            patch("scripts.dev.test_runner.coverage_db.write_tier_config"),
        ):
            strategy.collect_results()

        # Verify collect_results used tier-specific COVERAGE_FILE
        assert captured_env["COVERAGE_FILE"] == str(tier_coverage_file)
        assert not captured_env["COVERAGE_FILE"].endswith("/data")


class TestTierIsolationDoesNotCreateOtherTierFiles:
    def test_running_unit_tier_only_creates_unit_coverage_file(self, tmp_path: Path) -> None:
        """Running unit tier should only set COVERAGE_FILE to data_unit, not other tiers."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"
        tier_coverage_file = coverage_dir / "data_unit"

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        all_captured_envs: list[dict[str, str]] = []

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            if env:
                all_captured_envs.append(env.copy())
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "scripts.dev.test_runner.test_strategies._run_command",
            side_effect=mock_run_command,
        ):
            strategy.run_tests()

        # Verify only unit tier coverage file was referenced
        for env in all_captured_envs:
            if "COVERAGE_FILE" in env:
                assert "data_unit" in env["COVERAGE_FILE"]
                assert "data_component" not in env["COVERAGE_FILE"]
                assert "data_integration" not in env["COVERAGE_FILE"]
                assert "data_scripts" not in env["COVERAGE_FILE"]


class TestNoCovAppendFlag:
    def test_run_tests_does_not_include_cov_append(self, tmp_path: Path) -> None:
        """LineBranchTestStrategy.run_tests() should NOT include --cov-append flag."""
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

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        captured_cmd: list[str] = []

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            nonlocal captured_cmd
            captured_cmd = cmd
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "scripts.dev.test_runner.test_strategies._run_command",
            side_effect=mock_run_command,
        ):
            strategy.run_tests()

        # Verify --cov-append is NOT in the command
        assert "--cov-append" not in captured_cmd, (
            f"run_tests() should NOT use --cov-append flag. Command was: {captured_cmd}"
        )

    def test_run_tests_command_has_cov_but_not_cov_append(self, tmp_path: Path) -> None:
        """pytest command should have --cov flags but NOT --cov-append."""
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

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        captured_calls: list[list[str]] = []

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            captured_calls.append(cmd.copy())
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "scripts.dev.test_runner.test_strategies._run_command",
            side_effect=mock_run_command,
        ):
            strategy.run_tests()

        # Get the first command (coverage run command)
        captured_cmd = captured_calls[0]

        # Should have coverage flags
        cov_flags = [
            arg
            for arg in captured_cmd
            if arg.startswith("--source=")
            or arg.startswith("--omit=")
            or arg == "--branch"
            or arg == "--context=test"
        ]
        assert len(cov_flags) > 0, "Should have coverage flags in command"

        # Should have --source=<source> and --branch
        assert any("--source=" in arg for arg in captured_cmd)
        assert "--branch" in captured_cmd

        # But NOT --cov-append
        assert "--cov-append" not in captured_cmd

    def test_all_tiers_do_not_use_cov_append(self, tmp_path: Path) -> None:
        """All line_branch tier strategies should NOT use --cov-append."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"

        tier_configs = [
            TestTierConfig(
                name="unit",
                test_path="tests/unit",
                source_paths=["app"],
                min_line_per_function=80.0,
            ),
            TestTierConfig(
                name="component",
                test_path="tests/unit",
                source_paths=["app/services"],
                min_line_per_function=80.0,
            ),
            TestTierConfig(
                name="scripts",
                test_path="scripts/tests",
                source_paths=["scripts"],
                min_line_per_function=80.0,
            ),
        ]

        for config in tier_configs:
            tier_coverage_file = coverage_dir / f"data_{config.name}"
            strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

            captured_calls: list[list[str]] = []

            def mock_run_command(
                cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
            ) -> MagicMock:
                captured_calls.append(cmd.copy())  # noqa: B023
                result = MagicMock()
                result.returncode = 0
                return result

            with patch(
                "scripts.dev.test_runner.test_strategies._run_command",
                side_effect=mock_run_command,
            ):
                strategy.run_tests()

            # Get the first command (coverage run command)
            captured_cmd = captured_calls[0]

            assert "--cov-append" not in captured_cmd, (
                f"Tier {config.name} should NOT use --cov-append. Command was: {captured_cmd}"
            )


class TestCleanDatabasePerTier:
    def test_tier_starts_fresh_with_isolated_coverage_file(self, tmp_path: Path) -> None:
        """Each tier writes to isolated file, ensuring fresh coverage data."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"

        # Simulate pre-existing "stale" data in the tier coverage file
        tier_coverage_file = coverage_dir / "data_unit"
        tier_coverage_file.write_text("stale_coverage_data")

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        captured_env: dict[str, str] = {}

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            nonlocal captured_env
            captured_env = env or {}
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "scripts.dev.test_runner.test_strategies._run_command",
            side_effect=mock_run_command,
        ):
            strategy.run_tests()

        # The strategy should use COVERAGE_FILE pointing to tier-specific file
        # Without --cov-append, coverage.py will overwrite (not append) the file
        assert captured_env["COVERAGE_FILE"] == str(tier_coverage_file)

    def test_metrics_identical_run_alone_vs_combined_simulation(self, tmp_path: Path) -> None:
        """Simulated metrics should be identical whether run alone or combined.

        This tests the principle: since --cov-append is not used, each tier
        writes fresh data, so running tiers separately vs together should
        produce identical per-tier metrics.
        """
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        tier_coverage_file = coverage_dir / "data_unit"

        # Run 1: Simulate running unit tier alone
        strategy1 = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        run1_env: dict[str, str] = {}
        run1_cmd: list[str] = []

        def mock_run_command_1(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            nonlocal run1_env, run1_cmd
            run1_env = env or {}
            run1_cmd = cmd
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "scripts.dev.test_runner.test_strategies._run_command",
            side_effect=mock_run_command_1,
        ):
            strategy1.run_tests()

        # Run 2: Simulate running unit tier after component tier (combined scenario)
        strategy2 = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        run2_env: dict[str, str] = {}
        run2_cmd: list[str] = []

        def mock_run_command_2(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            nonlocal run2_env, run2_cmd
            run2_env = env or {}
            run2_cmd = cmd
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "scripts.dev.test_runner.test_strategies._run_command",
            side_effect=mock_run_command_2,
        ):
            strategy2.run_tests()

        # The commands and env should be identical regardless of run order
        assert run1_cmd == run2_cmd, (
            "pytest command should be identical whether run alone or in sequence"
        )
        assert run1_env == run2_env, (
            "COVERAGE_FILE env should be identical whether run alone or in sequence"
        )

        # Neither run should have --cov-append
        assert "--cov-append" not in run1_cmd
        assert "--cov-append" not in run2_cmd


class TestEdgeCases:
    def test_custom_tier_name_uses_correct_data_file_pattern(self, tmp_path: Path) -> None:
        """Custom tier names should still follow data_{tier_name} pattern."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"

        custom_tier_name = "my_custom_tier"
        tier_coverage_file = coverage_dir / f"data_{custom_tier_name}"

        config = TestTierConfig(
            name=custom_tier_name,
            test_path="tests/custom",
            source_paths=["custom_app"],
            min_line_per_function=80.0,
        )
        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        captured_env: dict[str, str] = {}

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            nonlocal captured_env
            captured_env = env or {}
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "scripts.dev.test_runner.test_strategies._run_command",
            side_effect=mock_run_command,
        ):
            strategy.run_tests()

        assert captured_env["COVERAGE_FILE"].endswith(f"data_{custom_tier_name}")

    def test_strategy_with_empty_source_paths_still_isolates(self, tmp_path: Path) -> None:
        """Even with unusual config, tier isolation should be maintained."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"
        tier_coverage_file = coverage_dir / "data_empty"

        config = TestTierConfig(
            name="empty",
            test_path="tests/empty",
            source_paths=[],  # Empty source paths
            min_line_per_function=80.0,
        )
        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        captured_env: dict[str, str] = {}

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            nonlocal captured_env
            captured_env = env or {}
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "scripts.dev.test_runner.test_strategies._run_command",
            side_effect=mock_run_command,
        ):
            strategy.run_tests()

        # Tier isolation should still be maintained
        assert "COVERAGE_FILE" in captured_env
        assert captured_env["COVERAGE_FILE"] == str(tier_coverage_file)

    def test_usecase_tier_does_not_use_coverage_file(self, tmp_path: Path) -> None:
        """IntegrationTestStrategy (usecase type) should NOT set COVERAGE_FILE."""
        from scripts.dev.test_runner.test_coverage import UseCase

        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"

        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
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
        strategy = IntegrationTestStrategy(config, db_path, tmp_path, use_cases)

        captured_env: dict[str, str] = {}

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            nonlocal captured_env
            captured_env = env or {}
            result = MagicMock()
            result.returncode = 0
            return result

        with (
            patch(
                "scripts.dev.test_runner.test_strategies._run_command",
                side_effect=mock_run_command,
            ),
            patch("scripts.dev.test_runner.coverage_db.write_tier_config"),
        ):
            strategy.run_tests()

        # Usecase tier should NOT set COVERAGE_FILE
        assert "COVERAGE_FILE" not in captured_env, (
            "IntegrationTestStrategy should not set COVERAGE_FILE"
        )


class TestNegativeCases:
    def test_cannot_use_shared_data_file_as_tier_coverage_file(self, tmp_path: Path) -> None:
        """Using just 'data' (shared file) should work but is discouraged.

        This test documents that while technically allowed, using the shared
        data file defeats tier isolation. The pattern should always be data_{tier}.
        """
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"

        # Using 'data' directly (not recommended, but should work)
        shared_data_file = coverage_dir / "data"

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        strategy = LineBranchTestStrategy(config, db_path, tmp_path, shared_data_file)

        captured_env: dict[str, str] = {}

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            nonlocal captured_env
            captured_env = env or {}
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "scripts.dev.test_runner.test_strategies._run_command",
            side_effect=mock_run_command,
        ):
            strategy.run_tests()

        # Works but uses shared file (defeats isolation)
        # This is documented behavior, not a test failure
        assert captured_env["COVERAGE_FILE"] == str(shared_data_file)


class TestActualImplementationCoverageFileEnvironment:
    def test_actual_run_tests_sets_coverage_file_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify run_tests() actually passes COVERAGE_FILE to subprocess.run().

        This test intercepts subprocess.run() directly to verify the actual
        environment dictionary contains COVERAGE_FILE.
        """
        import subprocess

        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"
        tier_coverage_file = coverage_dir / "data_unit"

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        captured_calls: list[dict[str, Any]] = []

        def mock_subprocess_run(*args: Any, **kwargs: Any) -> MagicMock:
            """Capture subprocess.run() calls to verify env is passed."""
            captured_calls.append(
                {
                    "args": args,
                    "kwargs": kwargs,
                }
            )
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        # Patch subprocess.run directly to verify what _run_command passes
        monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

        strategy.run_tests()

        # Verify at least one call was made
        assert len(captured_calls) > 0, "No subprocess.run() calls captured"

        # Find the pytest call (should be the first one)
        pytest_call = captured_calls[0]
        call_kwargs = pytest_call["kwargs"]

        # Verify env is passed and contains COVERAGE_FILE
        assert "env" in call_kwargs, "subprocess.run() was not called with env parameter"
        env = call_kwargs["env"]
        assert "COVERAGE_FILE" in env, "COVERAGE_FILE not in subprocess.run() env"
        assert env["COVERAGE_FILE"] == str(tier_coverage_file), (
            f"COVERAGE_FILE expected {tier_coverage_file}, got {env['COVERAGE_FILE']}"
        )

    def test_actual_coverage_file_path_matches_tier_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify COVERAGE_FILE path ends with data_{tier_name} for each tier."""
        import subprocess

        test_cases = [
            ("unit", "data_unit"),
            ("component", "data_component"),
            ("scripts", "data_scripts"),
        ]

        for tier_name, expected_suffix in test_cases:
            coverage_dir = tmp_path / ".coverage" / tier_name
            coverage_dir.mkdir(parents=True, exist_ok=True)
            db_path = coverage_dir / "coverage.db"
            tier_coverage_file = coverage_dir / f"data_{tier_name}"

            config = TestTierConfig(
                name=tier_name,
                test_path=f"tests/{tier_name}",
                source_paths=["app"],
                min_line_per_function=80.0,
            )
            strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

            captured_env: dict[str, str] | None = None

            def mock_subprocess_run(*args: Any, **kwargs: Any) -> MagicMock:
                nonlocal captured_env
                if "env" in kwargs:
                    captured_env = kwargs["env"]
                result = MagicMock()
                result.returncode = 0
                return result

            monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

            strategy.run_tests()

            assert captured_env is not None, f"No env captured for tier {tier_name}"
            assert "COVERAGE_FILE" in captured_env, f"COVERAGE_FILE not set for tier {tier_name}"
            assert captured_env["COVERAGE_FILE"].endswith(expected_suffix), (
                f"Tier {tier_name}: COVERAGE_FILE should end with {expected_suffix}, "
                f"got {captured_env['COVERAGE_FILE']}"
            )


class TestActualImplementationNoCovAppend:
    def test_actual_pytest_command_excludes_cov_append(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify actual pytest command constructed by run_tests() has no --cov-append."""
        import subprocess

        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"
        tier_coverage_file = coverage_dir / "data_unit"

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        captured_cmd: list[str] | None = None

        def mock_subprocess_run(cmd: list[str], *args: Any, **kwargs: Any) -> MagicMock:
            nonlocal captured_cmd
            captured_cmd = cmd
            result = MagicMock()
            result.returncode = 0
            return result

        monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

        strategy.run_tests()

        assert captured_cmd is not None, "No command captured"
        assert "--cov-append" not in captured_cmd, (
            f"Actual command should NOT contain --cov-append. Command was: {' '.join(captured_cmd)}"
        )

    def test_actual_pytest_command_has_cov_flags_but_not_append(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify coverage command has --source and --branch but NOT --cov-append."""
        import subprocess

        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"
        tier_coverage_file = coverage_dir / "data_unit"

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app", "lib"],  # Multiple source paths
            min_line_per_function=80.0,
        )
        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        captured_calls: list[list[str]] = []

        def mock_subprocess_run(cmd: list[str], *args: Any, **kwargs: Any) -> MagicMock:
            captured_calls.append(cmd.copy())
            result = MagicMock()
            result.returncode = 0
            return result

        monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

        strategy.run_tests()

        # Get the first command (coverage run command)
        assert len(captured_calls) > 0, "No commands captured"
        captured_cmd = captured_calls[0]

        # Should have --source flag with comma-separated paths
        source_flags = [arg for arg in captured_cmd if arg.startswith("--source=")]
        assert len(source_flags) == 1, f"Expected 1 --source= flag, got {source_flags}"
        # The source flag should contain both paths
        source_arg = source_flags[0]
        assert "app" in source_arg and "lib" in source_arg, (
            f"Source flag should contain both app and lib: {source_arg}"
        )

        # Should have --branch
        assert "--branch" in captured_cmd, "Missing --branch flag"

        # Should NOT have --cov-append
        assert "--cov-append" not in captured_cmd, "Command should NOT contain --cov-append"

    def test_all_tiers_actual_command_excludes_cov_append(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify all line_branch tiers produce commands without --cov-append."""
        import subprocess

        tier_configs = [
            ("unit", "tests/unit", ["app"]),
            ("component", "tests/unit", ["app/services"]),
            ("scripts", "scripts/tests", ["scripts", "tools"]),
        ]

        for tier_name, test_path, source_paths in tier_configs:
            coverage_dir = tmp_path / ".coverage" / tier_name
            coverage_dir.mkdir(parents=True, exist_ok=True)
            db_path = coverage_dir / "coverage.db"
            tier_coverage_file = coverage_dir / f"data_{tier_name}"

            config = TestTierConfig(
                name=tier_name,
                test_path=test_path,
                source_paths=source_paths,
                min_line_per_function=80.0,
            )
            strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

            captured_cmd: list[str] | None = None

            def mock_subprocess_run(cmd: list[str], *args: Any, **kwargs: Any) -> MagicMock:
                nonlocal captured_cmd
                captured_cmd = cmd
                result = MagicMock()
                result.returncode = 0
                return result

            monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

            strategy.run_tests()

            assert captured_cmd is not None, f"No command captured for tier {tier_name}"
            assert "--cov-append" not in captured_cmd, (
                f"Tier {tier_name} command should NOT contain --cov-append. "
                f"Command was: {' '.join(captured_cmd)}"
            )


class TestActualImplementationCoverageFilePaths:
    def test_collect_results_uses_same_coverage_file_as_run_tests(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify collect_results() uses same COVERAGE_FILE as run_tests()."""
        import subprocess

        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"
        tier_coverage_file = coverage_dir / "data_unit"

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        # Track all env COVERAGE_FILE values from subprocess calls
        coverage_file_values: list[str] = []

        def mock_subprocess_run(cmd: list[str], *args: Any, **kwargs: Any) -> MagicMock:
            if "env" in kwargs and kwargs["env"] is not None:
                env = kwargs["env"]
                if "COVERAGE_FILE" in env:
                    coverage_file_values.append(env["COVERAGE_FILE"])
            result = MagicMock()
            result.returncode = 0
            return result

        monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

        # Run tests
        strategy.run_tests()
        run_tests_coverage_files = coverage_file_values.copy()
        coverage_file_values.clear()

        # Create minimal coverage JSON for collect_results
        json_output_path = coverage_dir / "temp_unit.json"
        json_output_path.write_text(
            json.dumps(
                {
                    "totals": {
                        "num_statements": 100,
                        "covered_lines": 80,
                        "missing_lines": 20,
                        "percent_covered": 80.0,
                        "num_branches": 50,
                        "covered_branches": 40,
                        "num_partial_branches": 5,
                        "missing_branches": 5,
                        "percent_covered_branches": 80.0,
                    },
                    "files": {},
                }
            )
        )

        # Collect results (will call coverage json command)
        with patch("scripts.dev.test_runner.coverage_db.write_tier_config"):
            strategy.collect_results()

        collect_results_coverage_files = coverage_file_values

        # Both phases should use the same COVERAGE_FILE
        assert len(run_tests_coverage_files) > 0, "run_tests() did not set COVERAGE_FILE"
        assert len(collect_results_coverage_files) > 0, (
            "collect_results() did not set COVERAGE_FILE"
        )

        # All COVERAGE_FILE values should be the same
        all_values = run_tests_coverage_files + collect_results_coverage_files
        unique_values = set(all_values)
        assert len(unique_values) == 1, (
            f"COVERAGE_FILE inconsistent between run_tests and collect_results: {all_values}"
        )
        assert all_values[0] == str(tier_coverage_file), (
            f"COVERAGE_FILE should be {tier_coverage_file}, got {all_values[0]}"
        )


class TestActualImplementationCommandStructure:
    def test_actual_command_contains_test_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify actual pytest command contains the configured test path."""
        import subprocess

        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"
        tier_coverage_file = coverage_dir / "data_unit"

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit/subfolder",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        captured_calls: list[list[str]] = []

        def mock_subprocess_run(cmd: list[str], *args: Any, **kwargs: Any) -> MagicMock:
            captured_calls.append(cmd.copy())
            result = MagicMock()
            result.returncode = 0
            return result

        monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

        strategy.run_tests()

        # Get the first command (coverage run command)
        assert len(captured_calls) > 0, "No commands captured"
        captured_cmd = captured_calls[0]

        assert "tests/unit/subfolder" in captured_cmd, f"Test path not in command: {captured_cmd}"

    def test_actual_command_contains_junit_xml_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify actual pytest command contains --junitxml flag."""
        import subprocess

        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"
        tier_coverage_file = coverage_dir / "data_unit"

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        captured_calls: list[list[str]] = []

        def mock_subprocess_run(cmd: list[str], *args: Any, **kwargs: Any) -> MagicMock:
            captured_calls.append(cmd.copy())
            result = MagicMock()
            result.returncode = 0
            return result

        monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

        strategy.run_tests()

        # Get the first command (coverage run command)
        assert len(captured_calls) > 0, "No commands captured"
        captured_cmd = captured_calls[0]

        # Find --junitxml flag
        junitxml_flags = [arg for arg in captured_cmd if arg.startswith("--junitxml=")]
        assert len(junitxml_flags) == 1, f"Expected 1 --junitxml flag, got {junitxml_flags}"
        assert "junit_unit.xml" in junitxml_flags[0], (
            f"JUnit XML filename should contain tier name: {junitxml_flags[0]}"
        )

    def test_actual_command_contains_cov_context(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify actual pytest command contains --context=test."""
        import subprocess

        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"
        tier_coverage_file = coverage_dir / "data_unit"

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            min_line_per_function=80.0,
        )
        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        captured_calls: list[list[str]] = []

        def mock_subprocess_run(cmd: list[str], *args: Any, **kwargs: Any) -> MagicMock:
            captured_calls.append(cmd.copy())
            result = MagicMock()
            result.returncode = 0
            return result

        monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

        strategy.run_tests()

        # Get the first command (coverage run command)
        assert len(captured_calls) > 0, "No commands captured"
        captured_cmd = captured_calls[0]

        assert "--context=test" in captured_cmd, (
            f"Missing --context=test flag in command: {captured_cmd}"
        )


class TestActualImplementationIntegrationStrategy:
    def test_integration_strategy_does_not_set_coverage_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify IntegrationTestStrategy does NOT set COVERAGE_FILE env var."""
        import subprocess

        from scripts.dev.test_runner.test_coverage import UseCase

        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"

        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
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
        strategy = IntegrationTestStrategy(config, db_path, tmp_path, use_cases)

        captured_env: dict[str, str] | None = None

        def mock_subprocess_run(cmd: list[str], *args: Any, **kwargs: Any) -> MagicMock:
            nonlocal captured_env
            captured_env = kwargs.get("env")
            result = MagicMock()
            result.returncode = 0
            return result

        monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

        with patch("scripts.dev.test_runner.coverage_db.write_tier_config"):
            strategy.run_tests()

        # IntegrationTestStrategy should NOT set COVERAGE_FILE
        # (it may pass env=None or env without COVERAGE_FILE)
        if captured_env is not None:
            assert "COVERAGE_FILE" not in captured_env, (
                "IntegrationTestStrategy should NOT set COVERAGE_FILE env var"
            )

    def test_integration_strategy_command_has_no_cov_flags(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify IntegrationTestStrategy command has NO --cov flags."""
        import subprocess

        from scripts.dev.test_runner.test_coverage import UseCase

        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"

        config = TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
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
        strategy = IntegrationTestStrategy(config, db_path, tmp_path, use_cases)

        captured_cmd: list[str] | None = None

        def mock_subprocess_run(cmd: list[str], *args: Any, **kwargs: Any) -> MagicMock:
            nonlocal captured_cmd
            captured_cmd = cmd
            result = MagicMock()
            result.returncode = 0
            return result

        monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

        with patch("scripts.dev.test_runner.coverage_db.write_tier_config"):
            strategy.run_tests()

        assert captured_cmd is not None

        # No --cov flags at all
        cov_flags = [arg for arg in captured_cmd if "--cov" in arg]
        assert len(cov_flags) == 0, (
            f"IntegrationTestStrategy should NOT have --cov flags. Found: {cov_flags}"
        )
