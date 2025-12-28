import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

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


@pytest.fixture
def mock_coverage_json_data() -> dict[str, Any]:
    """Create mock coverage JSON data."""
    return {
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
        "files": {
            "app/service.py": {
                "executed_lines": list(range(1, 81)),
                "missing_lines": list(range(81, 101)),
                "missing_branches": [],
            }
        },
    }


class TestReq3JsonGeneratedFromTierCoverageFile:
    def test_coverage_file_env_var_set_for_unit_tier(
        self, tmp_path: Path, unit_tier_config: TestTierConfig
    ) -> None:
        """COVERAGE_FILE env var is set to tier-specific file during test run."""
        tier_coverage_file = tmp_path / ".coverage" / "data_unit"
        strategy = LineBranchTestStrategy(
            unit_tier_config,
            tmp_path / "coverage.db",
            tmp_path,
            tier_coverage_file,
        )

        captured_env: dict[str, str] = {}

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            if env:
                captured_env.update(env)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "scripts.dev.test_runner.test_strategies._run_command", side_effect=mock_run_command
        ):
            strategy.run_tests()

        assert "COVERAGE_FILE" in captured_env
        assert captured_env["COVERAGE_FILE"] == str(tier_coverage_file)

    def test_coverage_file_env_var_set_for_component_tier(
        self, tmp_path: Path, component_tier_config: TestTierConfig
    ) -> None:
        """COVERAGE_FILE env var uses tier-specific path for component tier."""
        tier_coverage_file = tmp_path / ".coverage" / "data_component"
        strategy = LineBranchTestStrategy(
            component_tier_config,
            tmp_path / "coverage.db",
            tmp_path,
            tier_coverage_file,
        )

        captured_env: dict[str, str] = {}

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            if env:
                captured_env.update(env)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "scripts.dev.test_runner.test_strategies._run_command", side_effect=mock_run_command
        ):
            strategy.run_tests()

        assert "COVERAGE_FILE" in captured_env
        assert captured_env["COVERAGE_FILE"] == str(tier_coverage_file)

    def test_json_report_uses_tier_coverage_file(
        self, tmp_path: Path, unit_tier_config: TestTierConfig, mock_coverage_json_data: dict
    ) -> None:
        """JSON report generation uses the tier-specific coverage file."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)
        tier_coverage_file = coverage_dir / "data_unit"
        tier_coverage_file.touch()

        strategy = LineBranchTestStrategy(
            unit_tier_config,
            tmp_path / "coverage.db",
            tmp_path,
            tier_coverage_file,
        )
        strategy._tests_ran = True

        json_generation_env: dict[str, str] = {}

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            if env:
                json_generation_env.update(env)
            # Check if this is the coverage json command
            if "coverage" in cmd and "json" in cmd:
                # Create the JSON file that collect_results expects
                json_path = coverage_dir / f"temp_{unit_tier_config.name}.json"
                json_path.write_text(json.dumps(mock_coverage_json_data))
            result = MagicMock()
            result.returncode = 0
            return result

        with (
            patch(
                "scripts.dev.test_runner.test_strategies._run_command",
                side_effect=mock_run_command,
            ),
            patch("scripts.dev.test_runner.test_strategies.coverage_db.write_tier_config"),
            patch("scripts.dev.test_runner.test_strategies.coverage_db.write_function_coverage"),
        ):
            strategy.collect_results()

        # Verify the COVERAGE_FILE was set to tier-specific file
        assert "COVERAGE_FILE" in json_generation_env
        assert json_generation_env["COVERAGE_FILE"] == str(tier_coverage_file)


class TestReq3JsonGeneratedBeforeFunctionCoverage:
    def test_json_generation_command_precedes_function_calculation(
        self, tmp_path: Path, unit_tier_config: TestTierConfig, mock_coverage_json_data: dict
    ) -> None:
        """The coverage json command runs before function coverage is calculated.

        This test verifies the ordering by checking that:
        1. _run_command is called with 'coverage json' command
        2. The JSON file must exist before _calculate_function_coverage can work
        """
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)
        tier_coverage_file = coverage_dir / "data_unit"
        tier_coverage_file.touch()

        strategy = LineBranchTestStrategy(
            unit_tier_config,
            tmp_path / "coverage.db",
            tmp_path,
            tier_coverage_file,
        )
        strategy._tests_ran = True

        command_sequence: list[str] = []

        def mock_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            # Record command type
            if "coverage" in cmd and "json" in cmd:
                command_sequence.append("coverage_json")
                # Create the expected JSON file
                json_path = coverage_dir / f"temp_{unit_tier_config.name}.json"
                json_path.write_text(json.dumps(mock_coverage_json_data))
            result = MagicMock()
            result.returncode = 0
            return result

        with (
            patch(
                "scripts.dev.test_runner.test_strategies._run_command",
                side_effect=mock_run_command,
            ),
            patch("scripts.dev.test_runner.test_strategies.coverage_db.write_tier_config"),
            patch("scripts.dev.test_runner.test_strategies.coverage_db.write_function_coverage"),
        ):
            strategy.collect_results()

        # Verify coverage json was called
        assert "coverage_json" in command_sequence

        # Verify coverage_result was populated (function coverage calculated after JSON)
        assert strategy.coverage_result is not None
        assert strategy._results_collected is True


class TestReq3EachTierJsonIndependent:
    def test_multiple_tiers_have_separate_json_outputs(
        self, tmp_path: Path, mock_coverage_json_data: dict
    ) -> None:
        """Each tier generates its own temporary JSON file."""
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

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
        ]

        json_output_paths: list[str] = []

        for config in tier_configs:
            tier_coverage_file = coverage_dir / f"data_{config.name}"
            tier_coverage_file.touch()

            strategy = LineBranchTestStrategy(
                config,
                tmp_path / "coverage.db",
                tmp_path,
                tier_coverage_file,
            )
            strategy._tests_ran = True

            def mock_run_command(
                cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
            ) -> MagicMock:
                if "coverage" in cmd and "json" in cmd:
                    # Find the -o argument to get output path
                    for i, arg in enumerate(cmd):
                        if arg == "-o" and i + 1 < len(cmd):
                            json_output_paths.append(cmd[i + 1])
                            # Create the JSON file
                            Path(cmd[i + 1]).parent.mkdir(parents=True, exist_ok=True)
                            Path(cmd[i + 1]).write_text(json.dumps(mock_coverage_json_data))
                            break
                result = MagicMock()
                result.returncode = 0
                return result

            with (
                patch(
                    "scripts.dev.test_runner.test_strategies._run_command",
                    side_effect=mock_run_command,
                ),
                patch("scripts.dev.test_runner.test_strategies.coverage_db.write_tier_config"),
                patch(
                    "scripts.dev.test_runner.test_strategies.coverage_db.write_function_coverage"
                ),
            ):
                strategy.collect_results()

        # Verify each tier used a different JSON output path
        assert len(json_output_paths) == 2
        assert json_output_paths[0] != json_output_paths[1]

        # Verify naming pattern includes tier name
        for i, config in enumerate(tier_configs):
            assert config.name in json_output_paths[i]


class TestActualCoverageJsonCommandInvocation:
    def test_coverage_json_command_uses_tier_specific_env_in_collect_results(
        self, tmp_path: Path, unit_tier_config: TestTierConfig, mock_coverage_json_data: dict
    ) -> None:
        """Verify coverage json command is invoked with tier-specific COVERAGE_FILE.

        This test captures the actual command invocation during collect_results()
        and verifies that the COVERAGE_FILE environment variable is correctly set
        to the tier-specific coverage file path.
        """
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)
        tier_coverage_file = coverage_dir / "data_unit"
        tier_coverage_file.touch()

        strategy = LineBranchTestStrategy(
            unit_tier_config,
            tmp_path / "coverage.db",
            tmp_path,
            tier_coverage_file,
        )
        strategy._tests_ran = True

        # Capture all command invocations
        captured_calls: list[dict[str, Any]] = []

        def capture_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            captured_calls.append(
                {
                    "cmd": cmd.copy(),
                    "capture": capture,
                    "env": env.copy() if env else None,
                }
            )
            # Create JSON file if this is the coverage json command
            if "coverage" in cmd and "json" in cmd:
                json_path = coverage_dir / f"temp_{unit_tier_config.name}.json"
                json_path.write_text(json.dumps(mock_coverage_json_data))
            result = MagicMock()
            result.returncode = 0
            return result

        with (
            patch(
                "scripts.dev.test_runner.test_strategies._run_command",
                side_effect=capture_run_command,
            ),
            patch("scripts.dev.test_runner.test_strategies.coverage_db.write_tier_config"),
            patch("scripts.dev.test_runner.test_strategies.coverage_db.write_function_coverage"),
        ):
            strategy.collect_results()

        # Find the coverage json command call
        json_cmd_calls = [
            call for call in captured_calls if "coverage" in call["cmd"] and "json" in call["cmd"]
        ]

        assert len(json_cmd_calls) == 1, "Expected exactly one coverage json command call"
        json_call = json_cmd_calls[0]

        # Verify COVERAGE_FILE env var is set to tier-specific file
        assert json_call["env"] is not None, "Environment should be set for coverage json"
        assert "COVERAGE_FILE" in json_call["env"], "COVERAGE_FILE should be in env"
        assert json_call["env"]["COVERAGE_FILE"] == str(tier_coverage_file), (
            f"COVERAGE_FILE should be {tier_coverage_file}, got {json_call['env']['COVERAGE_FILE']}"
        )

    def test_coverage_json_output_path_uses_tier_specific_naming(
        self, tmp_path: Path, unit_tier_config: TestTierConfig, mock_coverage_json_data: dict
    ) -> None:
        """Verify coverage json command outputs to temp_{tier_name}.json.

        This test captures the -o argument to verify JSON output path
        follows the tier-specific naming convention.
        """
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)
        tier_coverage_file = coverage_dir / "data_unit"
        tier_coverage_file.touch()

        strategy = LineBranchTestStrategy(
            unit_tier_config,
            tmp_path / "coverage.db",
            tmp_path,
            tier_coverage_file,
        )
        strategy._tests_ran = True

        captured_json_output_path: list[str] = []

        def capture_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            if "coverage" in cmd and "json" in cmd:
                # Extract -o argument value
                for i, arg in enumerate(cmd):
                    if arg == "-o" and i + 1 < len(cmd):
                        captured_json_output_path.append(cmd[i + 1])
                        # Create the JSON file
                        json_path = Path(cmd[i + 1])
                        json_path.parent.mkdir(parents=True, exist_ok=True)
                        json_path.write_text(json.dumps(mock_coverage_json_data))
                        break
            result = MagicMock()
            result.returncode = 0
            return result

        with (
            patch(
                "scripts.dev.test_runner.test_strategies._run_command",
                side_effect=capture_run_command,
            ),
            patch("scripts.dev.test_runner.test_strategies.coverage_db.write_tier_config"),
            patch("scripts.dev.test_runner.test_strategies.coverage_db.write_function_coverage"),
        ):
            strategy.collect_results()

        assert len(captured_json_output_path) == 1, "Expected exactly one JSON output path"
        output_path = captured_json_output_path[0]

        # Verify path follows tier-specific naming convention
        assert f"temp_{unit_tier_config.name}.json" in output_path, (
            f"JSON output should be temp_{unit_tier_config.name}.json, got {output_path}"
        )

    def test_multiple_tiers_use_different_coverage_files_for_json_generation(
        self, tmp_path: Path, mock_coverage_json_data: dict
    ) -> None:
        """Verify each tier uses its own COVERAGE_FILE for JSON generation.

        This test runs collect_results() for multiple tiers and verifies each
        tier's coverage json command uses the correct tier-specific COVERAGE_FILE.
        """
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

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
                source_paths=["scripts"],
                min_line_per_function=80.0,
            ),
        ]

        captured_coverage_files: dict[str, str] = {}

        for config in tier_configs:
            tier_coverage_file = coverage_dir / f"data_{config.name}"
            tier_coverage_file.touch()

            strategy = LineBranchTestStrategy(
                config,
                tmp_path / "coverage.db",
                tmp_path,
                tier_coverage_file,
            )
            strategy._tests_ran = True

            def make_capture_fn(tier_name: str) -> Any:
                def capture_run_command(
                    cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
                ) -> MagicMock:
                    if "coverage" in cmd and "json" in cmd and env:
                        captured_coverage_files[tier_name] = env.get("COVERAGE_FILE", "")
                        # Create the JSON file
                        json_path = coverage_dir / f"temp_{tier_name}.json"
                        json_path.write_text(json.dumps(mock_coverage_json_data))
                    result = MagicMock()
                    result.returncode = 0
                    return result

                return capture_run_command

            with (
                patch(
                    "scripts.dev.test_runner.test_strategies._run_command",
                    side_effect=make_capture_fn(config.name),
                ),
                patch("scripts.dev.test_runner.test_strategies.coverage_db.write_tier_config"),
                patch(
                    "scripts.dev.test_runner.test_strategies.coverage_db.write_function_coverage"
                ),
            ):
                strategy.collect_results()

        # Verify each tier used its own coverage file
        assert len(captured_coverage_files) == 3, "All 3 tiers should have captured COVERAGE_FILE"

        for tier_name in ["unit", "component", "scripts"]:
            expected_path = str(coverage_dir / f"data_{tier_name}")
            assert captured_coverage_files[tier_name] == expected_path, (
                f"Tier {tier_name} should use {expected_path}, "
                f"got {captured_coverage_files[tier_name]}"
            )


class TestActualSubprocessCallCapture:
    def test_run_tests_captures_pytest_command_with_coverage_env(
        self, tmp_path: Path, unit_tier_config: TestTierConfig
    ) -> None:
        """Verify run_tests() invokes coverage run with correct COVERAGE_FILE env.

        This test captures the complete subprocess call during run_tests()
        and verifies all coverage-related arguments and environment variables.
        """
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)
        tier_coverage_file = coverage_dir / "data_unit"

        strategy = LineBranchTestStrategy(
            unit_tier_config,
            tmp_path / "coverage.db",
            tmp_path,
            tier_coverage_file,
        )

        # Capture ALL commands since run_tests calls _run_command multiple times
        captured_calls: list[dict[str, Any]] = []

        def capture_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            captured_calls.append(
                {
                    "cmd": cmd.copy(),
                    "capture": capture,
                    "env": env.copy() if env else None,
                }
            )
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "scripts.dev.test_runner.test_strategies._run_command",
            side_effect=capture_run_command,
        ):
            strategy.run_tests()

        # Verify commands were captured (coverage run + coverage report)
        assert len(captured_calls) >= 1, "At least one command should be captured"

        # First call should be coverage run (the main test execution command)
        first_call = captured_calls[0]
        cmd = first_call["cmd"]

        # Verify it's a coverage run command that invokes pytest via -m
        assert "coverage" in cmd, "Should use coverage command"
        assert "run" in cmd, "Should use 'coverage run' subcommand"
        assert "-m" in cmd, "Should use -m to invoke pytest as module"
        assert "pytest" in cmd, "Should invoke pytest"

        # Verify COVERAGE_FILE env var
        assert first_call["env"] is not None, "Env should be set"
        assert "COVERAGE_FILE" in first_call["env"], "COVERAGE_FILE should be set"
        assert first_call["env"]["COVERAGE_FILE"] == str(tier_coverage_file), (
            f"COVERAGE_FILE should be {tier_coverage_file}"
        )

        # Verify coverage command structure (using coverage run instead of pytest-cov)
        assert "coverage" in cmd, "Should use coverage command"
        assert "run" in cmd, "Should use 'coverage run' subcommand"
        assert "--branch" in cmd, "--branch should be present"
        assert "--context=test" in cmd, "--context=test should be present"

        # Verify --source argument is present
        source_args = [arg for arg in cmd if arg.startswith("--source=")]
        assert len(source_args) >= 1, "Should have --source argument"

    def test_collect_results_captures_coverage_json_command_structure(
        self, tmp_path: Path, unit_tier_config: TestTierConfig, mock_coverage_json_data: dict
    ) -> None:
        """Verify collect_results() invokes coverage json with correct structure.

        This test captures the complete coverage json command and verifies
        all arguments including the -o output path.
        """
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)
        tier_coverage_file = coverage_dir / "data_unit"
        tier_coverage_file.touch()

        strategy = LineBranchTestStrategy(
            unit_tier_config,
            tmp_path / "coverage.db",
            tmp_path,
            tier_coverage_file,
        )
        strategy._tests_ran = True

        captured_json_call: dict[str, Any] = {}

        def capture_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            if "coverage" in cmd and "json" in cmd:
                captured_json_call["cmd"] = cmd.copy()
                captured_json_call["capture"] = capture
                captured_json_call["env"] = env.copy() if env else None
                # Create the JSON file
                for i, arg in enumerate(cmd):
                    if arg == "-o" and i + 1 < len(cmd):
                        json_path = Path(cmd[i + 1])
                        json_path.parent.mkdir(parents=True, exist_ok=True)
                        json_path.write_text(json.dumps(mock_coverage_json_data))
                        break
            result = MagicMock()
            result.returncode = 0
            return result

        with (
            patch(
                "scripts.dev.test_runner.test_strategies._run_command",
                side_effect=capture_run_command,
            ),
            patch("scripts.dev.test_runner.test_strategies.coverage_db.write_tier_config"),
            patch("scripts.dev.test_runner.test_strategies.coverage_db.write_function_coverage"),
        ):
            strategy.collect_results()

        # Verify command structure
        assert "cmd" in captured_json_call, "Coverage json command should be captured"
        cmd = captured_json_call["cmd"]

        # Verify command components
        assert "uv" in cmd, "Should use uv runner"
        assert "coverage" in cmd, "Should invoke coverage"
        assert "json" in cmd, "Should be json subcommand"
        assert "-o" in cmd, "Should have -o flag for output"

        # Verify -o argument points to temp_{tier}.json
        o_index = cmd.index("-o")
        output_path = cmd[o_index + 1]
        assert f"temp_{unit_tier_config.name}.json" in output_path

        # Verify environment
        assert captured_json_call["env"] is not None
        assert captured_json_call["env"]["COVERAGE_FILE"] == str(tier_coverage_file)

    def test_full_strategy_lifecycle_captures_all_subprocess_calls(
        self, tmp_path: Path, unit_tier_config: TestTierConfig, mock_coverage_json_data: dict
    ) -> None:
        """Verify full strategy lifecycle captures all expected subprocess calls.

        This test runs the complete strategy lifecycle (run_tests + collect_results)
        and verifies all subprocess calls use consistent tier-specific paths.
        """
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)
        tier_coverage_file = coverage_dir / "data_unit"

        strategy = LineBranchTestStrategy(
            unit_tier_config,
            tmp_path / "coverage.db",
            tmp_path,
            tier_coverage_file,
        )

        all_captured_calls: list[dict[str, Any]] = []

        def capture_run_command(
            cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
        ) -> MagicMock:
            call_info = {
                "cmd": cmd.copy(),
                "capture": capture,
                "env": env.copy() if env else None,
                "cmd_type": "unknown",
            }
            # Categorize the command
            if "pytest" in cmd:
                call_info["cmd_type"] = "pytest"
                # Create coverage data file for later
                tier_coverage_file.touch()
            elif "coverage" in cmd and "json" in cmd:
                call_info["cmd_type"] = "coverage_json"
                # Create the JSON file
                json_path = coverage_dir / f"temp_{unit_tier_config.name}.json"
                json_path.write_text(json.dumps(mock_coverage_json_data))

            all_captured_calls.append(call_info)
            result = MagicMock()
            result.returncode = 0
            return result

        with (
            patch(
                "scripts.dev.test_runner.test_strategies._run_command",
                side_effect=capture_run_command,
            ),
            patch("scripts.dev.test_runner.test_strategies.coverage_db.write_tier_config"),
            patch("scripts.dev.test_runner.test_strategies.coverage_db.write_function_coverage"),
        ):
            strategy.run_tests()
            strategy.collect_results()

        # Verify we captured both pytest and coverage json calls
        pytest_calls = [c for c in all_captured_calls if c["cmd_type"] == "pytest"]
        json_calls = [c for c in all_captured_calls if c["cmd_type"] == "coverage_json"]

        assert len(pytest_calls) == 1, "Should have exactly one pytest call"
        assert len(json_calls) == 1, "Should have exactly one coverage json call"

        # Verify both use the same tier-specific COVERAGE_FILE
        pytest_cov_file = pytest_calls[0]["env"]["COVERAGE_FILE"]
        json_cov_file = json_calls[0]["env"]["COVERAGE_FILE"]

        assert pytest_cov_file == json_cov_file, (
            f"pytest and coverage json should use same COVERAGE_FILE: "
            f"pytest={pytest_cov_file}, json={json_cov_file}"
        )
        assert pytest_cov_file == str(tier_coverage_file), (
            f"COVERAGE_FILE should be {tier_coverage_file}"
        )


class TestTierCoverageFilesDictPopulationInMainFlow:
    def test_strategy_lookup_from_tier_coverage_files_dict(
        self, tmp_path: Path, mock_coverage_json_data: dict
    ) -> None:
        """Verify strategies are created with tier_coverage_file from dict lookup.

        Simulates the strategy creation pattern from main() lines 1455-1461.
        """
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

        tiers_to_run = ["unit", "component"]
        tier_configs = {
            "unit": TestTierConfig(
                name="unit",
                test_path="tests/unit",
                source_paths=["app"],
                min_line_per_function=80.0,
            ),
            "component": TestTierConfig(
                name="component",
                test_path="tests/component",
                source_paths=["app/services"],
                min_line_per_function=80.0,
            ),
        }

        # Create tier_coverage_files dict (main() pattern)
        tier_coverage_files: dict[str, Path] = {
            tier_name: coverage_dir / f"data_{tier_name}" for tier_name in tiers_to_run
        }

        # Create strategies using dict lookup (main() pattern)
        strategies: list[LineBranchTestStrategy] = []
        for tier_name in tiers_to_run:
            config = tier_configs[tier_name]
            strategy = create_strategy(
                config,
                tmp_path / "coverage.db",
                tmp_path,
                tier_coverage_file=tier_coverage_files[tier_name],  # Dict lookup
            )
            strategies.append(strategy)

        # Verify each strategy has correct tier_coverage_file
        for i, tier_name in enumerate(tiers_to_run):
            assert strategies[i].tier_coverage_file == tier_coverage_files[tier_name]
            assert strategies[i].tier_coverage_file.name == f"data_{tier_name}"

    def test_tier_coverage_files_dict_passed_correctly_through_execution(
        self, tmp_path: Path, mock_coverage_json_data: dict
    ) -> None:
        """Verify tier_coverage_file from dict is used in actual execution.

        This test creates strategies from dict lookup and runs them to verify
        the tier_coverage_file is correctly passed through to subprocess calls.
        """
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

        tiers_to_run = ["unit", "component"]

        # Create tier_coverage_files dict
        tier_coverage_files: dict[str, Path] = {
            tier_name: coverage_dir / f"data_{tier_name}" for tier_name in tiers_to_run
        }

        captured_env_per_tier: dict[str, str] = {}

        for tier_name in tiers_to_run:
            config = TestTierConfig(
                name=tier_name,
                test_path=f"tests/{tier_name}",
                source_paths=["app"],
                min_line_per_function=80.0,
            )

            strategy = create_strategy(
                config,
                tmp_path / "coverage.db",
                tmp_path,
                tier_coverage_file=tier_coverage_files[tier_name],
            )

            def make_capture_fn(t_name: str) -> Any:
                def capture_run_command(
                    cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
                ) -> MagicMock:
                    if env and "COVERAGE_FILE" in env:
                        captured_env_per_tier[t_name] = env["COVERAGE_FILE"]
                    result = MagicMock()
                    result.returncode = 0
                    return result

                return capture_run_command

            with patch(
                "scripts.dev.test_runner.test_strategies._run_command",
                side_effect=make_capture_fn(tier_name),
            ):
                strategy.run_tests()

        # Verify each tier used its own coverage file from the dict
        for tier_name in tiers_to_run:
            expected = str(tier_coverage_files[tier_name])
            assert captured_env_per_tier[tier_name] == expected, (
                f"Tier {tier_name} should use {expected}, got {captured_env_per_tier[tier_name]}"
            )


class TestEnvironmentVariableIsolation:
    def test_sequential_tier_execution_maintains_env_isolation(
        self, tmp_path: Path, mock_coverage_json_data: dict
    ) -> None:
        """Verify sequential tier execution uses isolated COVERAGE_FILE env vars.

        This test simulates running multiple tiers sequentially and verifies
        each tier's subprocess calls use only that tier's COVERAGE_FILE.
        """
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)

        tier_names = ["unit", "component", "scripts"]

        # Track all COVERAGE_FILE values per tier
        tier_env_history: dict[str, list[str]] = {name: [] for name in tier_names}

        for tier_name in tier_names:
            tier_coverage_file = coverage_dir / f"data_{tier_name}"
            tier_coverage_file.touch()

            config = TestTierConfig(
                name=tier_name,
                test_path=f"tests/{tier_name}",
                source_paths=["app"],
                min_line_per_function=80.0,
            )

            strategy = LineBranchTestStrategy(
                config,
                tmp_path / "coverage.db",
                tmp_path,
                tier_coverage_file,
            )
            strategy._tests_ran = True

            def make_capture_fn(t_name: str) -> Any:
                def capture_run_command(
                    cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
                ) -> MagicMock:
                    if env and "COVERAGE_FILE" in env:
                        tier_env_history[t_name].append(env["COVERAGE_FILE"])
                    # Create JSON file if needed
                    if "coverage" in cmd and "json" in cmd:
                        json_path = coverage_dir / f"temp_{t_name}.json"
                        json_path.write_text(json.dumps(mock_coverage_json_data))
                    result = MagicMock()
                    result.returncode = 0
                    return result

                return capture_run_command

            with (
                patch(
                    "scripts.dev.test_runner.test_strategies._run_command",
                    side_effect=make_capture_fn(tier_name),
                ),
                patch("scripts.dev.test_runner.test_strategies.coverage_db.write_tier_config"),
                patch(
                    "scripts.dev.test_runner.test_strategies.coverage_db.write_function_coverage"
                ),
            ):
                strategy.collect_results()

        # Verify each tier only used its own coverage file
        for tier_name in tier_names:
            expected_path = str(coverage_dir / f"data_{tier_name}")
            env_values = tier_env_history[tier_name]

            assert len(env_values) >= 1, f"Tier {tier_name} should have at least one COVERAGE_FILE"
            for env_value in env_values:
                assert env_value == expected_path, (
                    f"Tier {tier_name} should only use {expected_path}, but found {env_value}"
                )

            # Verify no cross-tier contamination
            for other_tier in tier_names:
                if other_tier != tier_name:
                    other_path = str(coverage_dir / f"data_{other_tier}")
                    assert other_path not in env_values, (
                        f"Tier {tier_name} should not use {other_tier}'s coverage file"
                    )
