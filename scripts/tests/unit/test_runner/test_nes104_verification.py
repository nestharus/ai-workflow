from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from scripts.dev.test_runner.test_coverage import (
    CoverageResult,
    TestTierConfig,
)


class TestActualCovContextFlagPassed:
    def test_run_tests_includes_cov_context_test_flag(self, tmp_path: Path) -> None:
        """LineBranchTestStrategy.run_tests() MUST include --context=test in pytest cmd.

        This verifies the actual implementation passes the flag, not just expected behavior.
        """
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

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

        # CRITICAL: Verify --context=test is in the actual command
        assert "--context=test" in captured_cmd, (
            f"CRITICAL: --context=test MUST be in pytest command for redundant "
            f"test detection. Actual command: {captured_cmd}"
        )

    def test_run_tests_cov_context_flag_in_correct_position(self, tmp_path: Path) -> None:
        """--context=test should appear after --source and --branch flags.

        This ensures the coverage context flag is not accidentally overridden.
        """
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

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

        # Find indices of relevant flags
        source_index = next(
            (i for i, arg in enumerate(captured_cmd) if arg.startswith("--source=")), -1
        )
        cov_branch_index = next((i for i, arg in enumerate(captured_cmd) if arg == "--branch"), -1)
        cov_context_index = next(
            (i for i, arg in enumerate(captured_cmd) if arg == "--context=test"), -1
        )

        # Verify all flags exist
        assert source_index >= 0, "--source= flag missing"
        assert cov_branch_index >= 0, "--branch flag missing"
        assert cov_context_index >= 0, "--context=test flag missing"

        # Verify --context=test comes after --source
        assert cov_context_index > source_index, "--context=test should come after --source="

    def test_all_line_branch_tiers_include_cov_context_flag(self, tmp_path: Path) -> None:
        """All line_branch tier strategies MUST include --context=test.

        Unit, component, and scripts tiers all need this flag for consistent
        redundant test detection.
        """
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

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
                test_path="tests/component",
                source_paths=["app/services"],
                min_line_per_function=80.0,
            ),
            TestTierConfig(
                name="scripts",
                test_path="scripts/tests",
                source_paths=["scripts", "tools"],
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

            assert "--context=test" in captured_cmd, (
                f"CRITICAL: Tier '{config.name}' MUST include --context=test. "
                f"Command: {captured_cmd}"
            )


class TestActualTierIsolationViaCoverageFile:
    def test_run_tests_sets_correct_coverage_file_env(self, tmp_path: Path) -> None:
        """run_tests() MUST set COVERAGE_FILE env var to tier-specific path.

        This is the key mechanism for tier isolation - each tier writes
        to an isolated coverage file.
        """
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

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
        assert "COVERAGE_FILE" in captured_env, "COVERAGE_FILE env var must be set"
        assert captured_env["COVERAGE_FILE"] == str(tier_coverage_file), (
            f"COVERAGE_FILE must point to tier-specific file. "
            f"Expected: {tier_coverage_file}, Got: {captured_env['COVERAGE_FILE']}"
        )

    def test_collect_results_uses_tier_specific_coverage_file(self, tmp_path: Path) -> None:
        """collect_results() MUST use tier-specific COVERAGE_FILE for JSON generation.

        This ensures per-tier validation uses only that tier's coverage data.
        """
        import json

        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

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
        strategy._tests_ran = True

        captured_envs: list[dict[str, str]] = []

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            if env:
                captured_envs.append(env.copy())
            # Create the expected JSON file if it's a coverage json command
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

        # Verify all commands used tier-specific COVERAGE_FILE
        for env in captured_envs:
            assert env.get("COVERAGE_FILE") == str(tier_coverage_file), (
                f"collect_results must use tier-specific COVERAGE_FILE. "
                f"Expected: {tier_coverage_file}, Got: {env.get('COVERAGE_FILE')}"
            )

    def test_different_tiers_use_different_coverage_files(self, tmp_path: Path) -> None:
        """Different tiers MUST use different COVERAGE_FILE paths.

        This verifies the isolation mechanism prevents cross-tier contamination.
        """
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"

        tier_configs = [
            ("unit", "data_unit"),
            ("component", "data_component"),
            ("scripts", "data_scripts"),
        ]

        captured_coverage_files: dict[str, str] = {}

        for tier_name, expected_filename in tier_configs:
            config = TestTierConfig(
                name=tier_name,
                test_path=f"tests/{tier_name}",
                source_paths=["app"],
                min_line_per_function=80.0,
            )
            tier_coverage_file = coverage_dir / expected_filename
            strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

            def make_mock_for_tier(name: str) -> Any:
                def mock_run_command(
                    cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
                ) -> MagicMock:
                    if env and "COVERAGE_FILE" in env:
                        captured_coverage_files[name] = env["COVERAGE_FILE"]
                    result = MagicMock()
                    result.returncode = 0
                    return result

                return mock_run_command

            with patch(
                "scripts.dev.test_runner.test_strategies._run_command",
                side_effect=make_mock_for_tier(tier_name),
            ):
                strategy.run_tests()

        # Verify all tiers use different COVERAGE_FILE paths
        coverage_file_values = list(captured_coverage_files.values())
        assert len(set(coverage_file_values)) == len(tier_configs), (
            f"Each tier must use a unique COVERAGE_FILE. Values: {captured_coverage_files}"
        )

        # Verify each tier uses the correct filename
        for tier_name, expected_filename in tier_configs:
            assert tier_name in captured_coverage_files
            assert captured_coverage_files[tier_name].endswith(expected_filename), (
                f"Tier {tier_name} should use {expected_filename}. "
                f"Got: {captured_coverage_files[tier_name]}"
            )


class TestActualPytestCommandConstruction:
    def test_complete_pytest_command_structure(self, tmp_path: Path) -> None:
        """Verify the complete pytest command structure for line_branch tiers.

        This captures the actual command and validates all required flags.
        """
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        config = TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app", "lib"],  # Multiple source paths
            min_line_per_function=80.0,
        )
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"
        tier_coverage_file = coverage_dir / "data_unit"

        strategy = LineBranchTestStrategy(config, db_path, tmp_path, tier_coverage_file)

        captured_calls: list[list[str]] = []
        captured_envs: list[dict[str, str]] = []

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            captured_calls.append(cmd.copy())
            captured_envs.append(env.copy() if env else {})
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "scripts.dev.test_runner.test_strategies._run_command",
            side_effect=mock_run_command,
        ):
            strategy.run_tests()

        # Get the first command (coverage run command)
        assert len(captured_calls) > 0, "No commands captured"
        captured_cmd = captured_calls[0]
        captured_env = captured_envs[0]

        # Verify command structure
        assert "uv" in captured_cmd
        assert "coverage" in captured_cmd
        assert "run" in captured_cmd
        assert "pytest" in captured_cmd

        # Verify test path is included
        assert config.test_path in captured_cmd

        # Verify coverage flags - now uses --source=app,lib instead of --cov=app --cov=lib
        source_flags = [arg for arg in captured_cmd if arg.startswith("--source=")]
        assert len(source_flags) == 1, f"Expected 1 --source= flag, got {source_flags}"
        source_arg = source_flags[0]
        for source_path in config.source_paths:
            assert source_path in source_arg, (
                f"Missing {source_path} in --source flag: {source_arg}"
            )

        # Verify required coverage flags
        required_flags = [
            "--branch",
            "--context=test",
        ]
        for flag in required_flags:
            assert flag in captured_cmd, f"Missing required flag: {flag}"

        # Verify environment
        assert captured_env.get("COVERAGE_FILE") == str(tier_coverage_file)

    def test_integration_strategy_no_coverage_flags(self, tmp_path: Path) -> None:
        """IntegrationTestStrategy should NOT include coverage flags.

        This verifies that usecase tiers run pytest without coverage instrumentation.
        """
        from scripts.dev.test_runner.test_coverage import UseCase
        from scripts.dev.test_runner.test_strategies import IntegrationTestStrategy

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

        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"

        strategy = IntegrationTestStrategy(config, db_path, tmp_path, use_cases)

        captured_cmd: list[str] = []
        captured_env: dict[str, str] = {}

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            nonlocal captured_cmd, captured_env
            captured_cmd = cmd
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

        # Verify NO coverage flags
        assert not any(arg.startswith("--cov") for arg in captured_cmd), (
            f"Integration strategy should NOT have coverage flags. "
            f"Found: {[arg for arg in captured_cmd if arg.startswith('--cov')]}"
        )

        # Verify NO COVERAGE_FILE env var
        assert "COVERAGE_FILE" not in captured_env, (
            "Integration strategy should not set COVERAGE_FILE"
        )

    def test_junit_xml_path_construction(self, tmp_path: Path) -> None:
        """Verify JUnit XML path is correctly constructed for test results parsing."""
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

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
        assert len(captured_calls) > 0, "No commands captured"
        captured_cmd = captured_calls[0]

        # Find the --junitxml argument
        junitxml_arg = next((arg for arg in captured_cmd if arg.startswith("--junitxml=")), None)
        assert junitxml_arg is not None, "Missing --junitxml= argument"

        # Verify path structure
        expected_suffix = f"junit_{config.name}.xml"
        assert expected_suffix in junitxml_arg, (
            f"JUnit XML path should include tier name. "
            f"Expected suffix: {expected_suffix}, Got: {junitxml_arg}"
        )
