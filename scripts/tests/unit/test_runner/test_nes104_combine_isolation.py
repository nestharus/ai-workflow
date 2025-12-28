import json
from pathlib import Path


class TestCovContextFlagInPytestCommand:
    def test_line_branch_strategy_includes_cov_context_flag(self, tmp_path: Path) -> None:
        """LineBranchTestStrategy.run_tests() MUST include --context=test flag.

        This test captures the actual pytest command constructed by the strategy
        and verifies --context=test is present.
        """
        from unittest.mock import MagicMock, patch

        from scripts.dev.test_runner.test_coverage import TestTierConfig
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

        # CRITICAL CHECK: --context=test MUST be in the command
        assert "--context=test" in captured_cmd, (
            f"CRITICAL: --context=test flag is MISSING from pytest command.\n"
            f"Without this flag, per-test contexts won't be recorded in coverage data.\n"
            f"This breaks redundant test detection.\n"
            f"Actual command: {captured_cmd}"
        )

    def test_cov_context_flag_position_in_command(self, tmp_path: Path) -> None:
        """Verify --context=test is positioned correctly with other coverage flags."""
        from unittest.mock import MagicMock, patch

        from scripts.dev.test_runner.test_coverage import TestTierConfig
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

        # Collect all coverage-related flags
        cov_flags = [
            arg
            for arg in captured_cmd
            if arg.startswith("--source=")
            or arg.startswith("--omit=")
            or arg == "--branch"
            or arg == "--context=test"
        ]

        # Should have multiple coverage flags
        assert len(cov_flags) >= 3, f"Expected at least 3 coverage flags, got: {cov_flags}"

        # Must include these specific flags
        assert "--context=test" in captured_cmd, f"Missing --context=test in: {cov_flags}"
        assert "--branch" in captured_cmd, f"Missing --branch in: {cov_flags}"
        assert any("--source=" in arg for arg in cov_flags), (
            f"Missing --source=<path> in: {cov_flags}"
        )

    def test_all_line_branch_tiers_include_cov_context_flag(self, tmp_path: Path) -> None:
        """All line_branch tier strategies MUST include --context=test flag."""
        from unittest.mock import MagicMock, patch

        from scripts.dev.test_runner.test_coverage import TestTierConfig
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
                f"CRITICAL: Tier '{config.name}' is MISSING --context=test flag.\n"
                f"Command: {captured_cmd}"
            )


class TestTierValidationUsesCorrectFile:
    def test_collect_results_uses_tier_specific_coverage_file(self, tmp_path: Path) -> None:
        """collect_results() should use tier-specific COVERAGE_FILE, not combined."""
        from unittest.mock import MagicMock, patch

        from scripts.dev.test_runner.test_coverage import TestTierConfig
        from scripts.dev.test_runner.test_strategies import LineBranchTestStrategy

        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True)
        db_path = coverage_dir / "coverage.db"
        tier_coverage_file = coverage_dir / "data_unit"
        combined_file = coverage_dir / "data"

        # Create both files to ensure the test doesn't accidentally use wrong one
        combined_file.touch()

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

        # CRITICAL: collect_results() must use tier-specific file, NOT combined
        assert "COVERAGE_FILE" in captured_env
        assert captured_env["COVERAGE_FILE"] == str(tier_coverage_file), (
            f"collect_results() should use tier-specific file, not combined.\n"
            f"Expected: {tier_coverage_file}\n"
            f"Got: {captured_env['COVERAGE_FILE']}"
        )
        assert captured_env["COVERAGE_FILE"] != str(combined_file), (
            "collect_results() must NOT use combined coverage file for tier validation"
        )
