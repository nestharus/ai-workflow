import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scripts.dev.test_runner.test_files as test_files_module
from scripts.dev.test_runner.test_files import (
    _HAS_FULL_MATCH,
    FAILED_LINE_PATTERN,
    FAILURE_HEADER_PATTERN,
    REPO_ROOT,
    TierConfig,
    _extract_short_test_name,
    _find_failed_tests_for_file,
    _find_repo_root,
    _glob_pattern_to_regex,
    _test_path_matches_file,
    _validate_tier_config,
    file_matches_tier,
    find_test_files,
    match_pattern,
    normalize_path,
    run_tests,
    run_tests_for_files,
)


class TestFindRepoRoot:
    def test_returns_fallback_when_no_marker_found(self, tmp_path: Path) -> None:
        """Falls back to hardcoded parent traversal when no marker is found."""
        # Create a directory structure with no markers
        no_markers_dir = tmp_path / "no_markers" / "deep" / "path"
        no_markers_dir.mkdir(parents=True)

        with patch("scripts.dev.test_runner.test_files.logger") as mock_logger:
            result = _find_repo_root(no_markers_dir)

            # Should log a warning
            mock_logger.warning.assert_called_once()
            assert "No repository marker" in mock_logger.warning.call_args[0][0]

            # Should return the fallback (4 levels up from the module file)
            # The fallback is relative to the actual test_files.py, not our tmp_path
            assert result.exists()


class TestRunTestsDeduplication:
    def test_deduplicates_full_and_short_test_names(self) -> None:
        """Full test IDs and short names for same test are deduplicated."""
        with patch("scripts.dev.test_runner.test_files.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = (
                "_________________________ test_bar _________________________\n"
                "AssertionError: test failed\n"
                "FAILED tests/unit/test_foo.py::test_bar - AssertionError\n"
            )
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            _passed, _exit_code, _output, failed_tests = run_tests(["test.py"])

            # Should only have the full identifier, not both full and short
            assert len(failed_tests) == 1
            assert "tests/unit/test_foo.py::test_bar" in failed_tests
            assert "test_bar" not in failed_tests

    def test_keeps_short_name_when_no_full_id_available(self) -> None:
        """Short test name is kept when no full identifier is found."""
        with patch("scripts.dev.test_runner.test_files.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            # Only failure header, no FAILED summary line
            mock_result.stdout = (
                "_________________________ test_orphan _________________________\n"
                "AssertionError: test failed\n"
            )
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            _passed, _exit_code, _output, failed_tests = run_tests(["test.py"])

            # Should have the short name since no full identifier exists
            assert "test_orphan" in failed_tests

    def test_multiple_tests_deduplicated_correctly(self) -> None:
        """Multiple tests are deduplicated correctly."""
        with patch("scripts.dev.test_runner.test_files.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = (
                "_________________________ test_one _________________________\n"
                "AssertionError\n"
                "_________________________ test_two _________________________\n"
                "AssertionError\n"
                "FAILED tests/unit/test_foo.py::test_one - AssertionError\n"
                "FAILED tests/unit/test_foo.py::test_two - AssertionError\n"
            )
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            _passed, _exit_code, _output, failed_tests = run_tests(["test.py"])

            # Should have only full identifiers
            assert len(failed_tests) == 2
            assert "tests/unit/test_foo.py::test_one" in failed_tests
            assert "tests/unit/test_foo.py::test_two" in failed_tests
            assert "test_one" not in failed_tests
            assert "test_two" not in failed_tests


class TestRunTestsDeduplicationClassAndParametrized:
    def test_deduplicates_class_method_full_and_short(self) -> None:
        """Class method full IDs and short names are deduplicated correctly."""
        with patch("scripts.dev.test_runner.test_files.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = (
                "_________________________ TestClass::test_method _________________________\n"
                "AssertionError: test failed\n"
                "FAILED tests/unit/test_foo.py::TestClass::test_method - AssertionError\n"
            )
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            _passed, _exit_code, _output, failed_tests = run_tests(["test.py"])

            # Should have only the full identifier
            assert len(failed_tests) == 1
            assert "tests/unit/test_foo.py::TestClass::test_method" in failed_tests
            # Short class::method name should be deduplicated
            assert "TestClass::test_method" not in failed_tests

    def test_deduplicates_parametrized_full_and_short(self) -> None:
        """Parametrized test full IDs and short names are deduplicated correctly."""
        with patch("scripts.dev.test_runner.test_files.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = (
                "_________________________ test_validate[input1] _________________________\n"
                "AssertionError: test failed\n"
                "FAILED tests/unit/test_foo.py::test_validate[input1] - AssertionError\n"
            )
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            _passed, _exit_code, _output, failed_tests = run_tests(["test.py"])

            # Should have only the full identifier
            assert len(failed_tests) == 1
            assert "tests/unit/test_foo.py::test_validate[input1]" in failed_tests
            # Short parametrized name should be deduplicated
            assert "test_validate[input1]" not in failed_tests

    def test_deduplicates_class_parametrized_full_and_short(self) -> None:
        """Class method with params: full IDs and short names are deduplicated."""
        with patch("scripts.dev.test_runner.test_files.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = (
                "_________________________ TestValidator::test_check[case1] _________________________\n"
                "AssertionError: test failed\n"
                "FAILED tests/unit/test_foo.py::TestValidator::test_check[case1] - AssertionError\n"
            )
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            _passed, _exit_code, _output, failed_tests = run_tests(["test.py"])

            # Should have only the full identifier
            assert len(failed_tests) == 1
            assert "tests/unit/test_foo.py::TestValidator::test_check[case1]" in failed_tests
            # Short name should be deduplicated
            assert "TestValidator::test_check[case1]" not in failed_tests

    def test_multiple_parametrized_failures_deduplicated(self) -> None:
        """Multiple parametrized failures are deduplicated correctly."""
        with patch("scripts.dev.test_runner.test_files.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = (
                "_________________________ test_parse[json] _________________________\n"
                "AssertionError\n"
                "_________________________ test_parse[xml] _________________________\n"
                "AssertionError\n"
                "_________________________ test_parse[yaml] _________________________\n"
                "AssertionError\n"
                "FAILED tests/unit/test_parser.py::test_parse[json] - AssertionError\n"
                "FAILED tests/unit/test_parser.py::test_parse[xml] - AssertionError\n"
                "FAILED tests/unit/test_parser.py::test_parse[yaml] - AssertionError\n"
            )
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            _passed, _exit_code, _output, failed_tests = run_tests(["test.py"])

            # Should have only full identifiers
            assert len(failed_tests) == 3
            assert "tests/unit/test_parser.py::test_parse[json]" in failed_tests
            assert "tests/unit/test_parser.py::test_parse[xml]" in failed_tests
            assert "tests/unit/test_parser.py::test_parse[yaml]" in failed_tests
            # Short names should not be present
            assert "test_parse[json]" not in failed_tests
            assert "test_parse[xml]" not in failed_tests
            assert "test_parse[yaml]" not in failed_tests

    def test_keeps_short_parametrized_name_when_no_full_id(self) -> None:
        """Short parametrized name is kept when no full identifier is found."""
        with patch("scripts.dev.test_runner.test_files.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            # Only failure header, no FAILED summary line
            mock_result.stdout = (
                "_________________________ test_orphan[param1] _________________________\n"
                "AssertionError: test failed\n"
            )
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            _passed, _exit_code, _output, failed_tests = run_tests(["test.py"])

            # Should have the short name since no full identifier exists
            assert "test_orphan[param1]" in failed_tests


class TestFailedTestMappingClassAndParametrized:
    @pytest.fixture
    def mock_tiers(self) -> list[TierConfig]:
        """Create mock tier configurations for testing."""
        return [
            TierConfig(
                name="unit",
                test_path="tests/unit",
                source_patterns=["app/**/*.py"],
            ),
        ]

    def test_maps_class_method_failures_to_correct_file(self, mock_tiers: list[TierConfig]) -> None:
        """Class method test failures are mapped to the correct source file."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):

            def find_tests_side_effect(source_file: str, tier: TierConfig) -> list[str]:
                if source_file == "app/core/factory.py":
                    return ["tests/unit/app/core/test_factory.py"]
                elif source_file == "app/core/models.py":
                    return ["tests/unit/app/core/test_models.py"]
                return []

            mock_find_tests.side_effect = find_tests_side_effect

            # Class method failure in test_factory.py
            mock_run_tests.return_value = (
                False,
                1,
                "FAILED tests/unit/app/core/test_factory.py::TestFactory::test_create - AssertionError",
                ["tests/unit/app/core/test_factory.py::TestFactory::test_create"],
            )

            files = ["app/core/factory.py", "app/core/models.py"]
            results = run_tests_for_files(files, tiers=mock_tiers)

            factory_result = next(r for r in results if r.file == "app/core/factory.py")
            models_result = next(r for r in results if r.file == "app/core/models.py")

            # factory.py should have the class method failure
            assert not factory_result.passed
            assert (
                "tests/unit/app/core/test_factory.py::TestFactory::test_create"
                in factory_result.failed_tests
            )

            # models.py should have no failures
            assert models_result.passed
            assert models_result.failed_tests == []

    def test_maps_parametrized_failures_to_correct_file(self, mock_tiers: list[TierConfig]) -> None:
        """Parametrized test failures are mapped to the correct source file."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):

            def find_tests_side_effect(source_file: str, tier: TierConfig) -> list[str]:
                if source_file == "app/core/parser.py":
                    return ["tests/unit/app/core/test_parser.py"]
                elif source_file == "app/core/validator.py":
                    return ["tests/unit/app/core/test_validator.py"]
                return []

            mock_find_tests.side_effect = find_tests_side_effect

            # Multiple parametrized failures in test_parser.py
            mock_run_tests.return_value = (
                False,
                1,
                "FAILED tests/unit/app/core/test_parser.py::test_parse[json]\nFAILED tests/unit/app/core/test_parser.py::test_parse[xml]",
                [
                    "tests/unit/app/core/test_parser.py::test_parse[json]",
                    "tests/unit/app/core/test_parser.py::test_parse[xml]",
                ],
            )

            files = ["app/core/parser.py", "app/core/validator.py"]
            results = run_tests_for_files(files, tiers=mock_tiers)

            parser_result = next(r for r in results if r.file == "app/core/parser.py")
            validator_result = next(r for r in results if r.file == "app/core/validator.py")

            # parser.py should have both parametrized failures
            assert not parser_result.passed
            assert len(parser_result.failed_tests) == 2
            assert (
                "tests/unit/app/core/test_parser.py::test_parse[json]" in parser_result.failed_tests
            )
            assert (
                "tests/unit/app/core/test_parser.py::test_parse[xml]" in parser_result.failed_tests
            )

            # validator.py should have no failures
            assert validator_result.passed
            assert validator_result.failed_tests == []

    def test_maps_class_parametrized_failures_correctly(self, mock_tiers: list[TierConfig]) -> None:
        """Class method parametrized test failures are mapped correctly."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):

            def find_tests_side_effect(source_file: str, tier: TierConfig) -> list[str]:
                if source_file == "app/core/validator.py":
                    return ["tests/unit/app/core/test_validator.py"]
                return []

            mock_find_tests.side_effect = find_tests_side_effect

            # Class method with parametrized failure
            mock_run_tests.return_value = (
                False,
                1,
                "FAILED tests/unit/app/core/test_validator.py::TestValidator::test_validate[empty_string]",
                [
                    "tests/unit/app/core/test_validator.py::TestValidator::test_validate[empty_string]"
                ],
            )

            files = ["app/core/validator.py"]
            results = run_tests_for_files(files, tiers=mock_tiers)

            assert len(results) == 1
            assert not results[0].passed
            assert (
                "tests/unit/app/core/test_validator.py::TestValidator::test_validate[empty_string]"
                in results[0].failed_tests
            )


class TestRunTestsExceptionHandling:
    def test_returns_error_when_uv_not_found(self) -> None:
        """Test that missing uv executable returns clear error with exit code -3."""
        with patch("scripts.dev.test_runner.test_files.shutil.which") as mock_which:
            mock_which.return_value = None

            passed, exit_code, output, failed_tests = run_tests(["test.py"])

            assert passed is False
            assert exit_code == -3
            assert "uv" in output
            assert "not found" in output.lower()
            assert "TEST_RUNNER_CMD" in output
            assert failed_tests == []

    def test_uses_custom_test_runner_cmd_from_env(self) -> None:
        """Test that TEST_RUNNER_CMD environment variable overrides default."""
        import os

        with (
            patch.dict(os.environ, {"TEST_RUNNER_CMD": "python -m pytest"}),
            patch("scripts.dev.test_runner.test_files.subprocess.run") as mock_run,
        ):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "All tests passed"
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            passed, _, _, _ = run_tests(["test.py"])

            # Verify custom command was used
            call_args = mock_run.call_args
            cmd = call_args[0][0]
            assert cmd[:3] == ["python", "-m", "pytest"]
            assert passed is True

    def test_handles_oserror_when_command_not_found(self) -> None:
        """Test that OSError is caught and returns failure tuple."""
        with patch("scripts.dev.test_runner.test_files.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("No such file or directory: 'uv'")

            passed, exit_code, output, failed_tests = run_tests(["test.py"])

            assert passed is False
            assert exit_code == -2
            assert "Failed to execute test command" in output
            assert "No such file or directory" in output
            assert failed_tests == []

    def test_handles_subprocess_error(self) -> None:
        """Test that SubprocessError is caught and return failure tuple."""
        with patch("scripts.dev.test_runner.test_files.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.SubprocessError("Subprocess failed")

            passed, exit_code, output, failed_tests = run_tests(["test.py"])

            assert passed is False
            assert exit_code == -2
            assert "Subprocess error running tests" in output
            assert failed_tests == []

    def test_handles_timeout_expired(self) -> None:
        """Test that TimeoutExpired is caught and returns failure tuple."""
        with patch("scripts.dev.test_runner.test_files.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=60)

            passed, exit_code, output, failed_tests = run_tests(["test.py"], timeout=60)

            assert passed is False
            assert exit_code == -1
            assert "timeout" in output.lower()
            assert failed_tests == []


class TestRunTestsForFilesAggregation:
    @pytest.fixture
    def mock_tiers(self) -> list[TierConfig]:
        """Create mock tier configurations for testing."""
        return [
            TierConfig(
                name="unit",
                test_path="tests/unit",
                source_patterns=["app/**/*.py"],
            ),
            TierConfig(
                name="scripts",
                test_path="scripts/tests",
                source_patterns=["scripts/**/*.py"],
            ),
        ]

    def test_groups_files_into_tiers(self, mock_tiers: list[TierConfig]) -> None:
        """Test that files are correctly grouped into their respective tiers."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):
            # Mock test file discovery
            def find_tests_side_effect(source_file: str, tier: TierConfig) -> list[str]:
                test_map = {
                    "app/core/factory.py": ["tests/unit/app/core/test_factory.py"],
                    "app/core/models.py": ["tests/unit/app/core/test_models.py"],
                    "scripts/dev/linter.py": ["scripts/tests/dev/test_linter.py"],
                }
                return test_map.get(source_file, [])

            mock_find_tests.side_effect = find_tests_side_effect

            # Mock run_tests to return success with no failures
            mock_run_tests.return_value = (True, 0, "All tests passed", [])

            files = [
                "app/core/factory.py",
                "app/core/models.py",
                "scripts/dev/linter.py",
            ]
            results = run_tests_for_files(files, tiers=mock_tiers)

            # Verify results contain files from both tiers
            result_tiers = {r.tier for r in results}
            assert "unit" in result_tiers
            assert "scripts" in result_tiers

            # Verify file-tier assignment
            unit_files = [r.file for r in results if r.tier == "unit"]
            scripts_files = [r.file for r in results if r.tier == "scripts"]

            assert "app/core/factory.py" in unit_files
            assert "app/core/models.py" in unit_files
            assert "scripts/dev/linter.py" in scripts_files

    def test_maps_failed_tests_to_correct_source_file(self, mock_tiers: list[TierConfig]) -> None:
        """Test that failed test entries are mapped back to the exact source file."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):
            # Multiple source files in same tier with different test files
            def find_tests_side_effect(source_file: str, tier: TierConfig) -> list[str]:
                if source_file == "app/core/factory.py":
                    return ["tests/unit/app/core/test_factory.py"]
                elif source_file == "app/core/models.py":
                    return ["tests/unit/app/core/test_models.py"]
                return []

            mock_find_tests.side_effect = find_tests_side_effect

            # Only test_factory.py has failures
            mock_run_tests.return_value = (
                False,
                1,
                "FAILED tests/unit/app/core/test_factory.py::test_create - AssertionError",
                ["tests/unit/app/core/test_factory.py::test_create"],
            )

            files = ["app/core/factory.py", "app/core/models.py"]
            results = run_tests_for_files(files, tiers=mock_tiers)

            # Find results for each file
            factory_result = next(r for r in results if r.file == "app/core/factory.py")
            models_result = next(r for r in results if r.file == "app/core/models.py")

            # factory.py should have the failed test mapped to it
            assert not factory_result.passed
            assert "tests/unit/app/core/test_factory.py::test_create" in factory_result.failed_tests

            # models.py should have no failed tests mapped to it
            assert models_result.passed
            assert models_result.failed_tests == []

    def test_file_with_no_failures_passes_when_tier_has_failures(
        self, mock_tiers: list[TierConfig]
    ) -> None:
        """Test that files with no associated failures pass even when other files in same tier fail."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):

            def find_tests_side_effect(source_file: str, tier: TierConfig) -> list[str]:
                test_map = {
                    "app/core/factory.py": ["tests/unit/app/core/test_factory.py"],
                    "app/core/models.py": ["tests/unit/app/core/test_models.py"],
                    "app/core/utils.py": ["tests/unit/app/core/test_utils.py"],
                }
                return test_map.get(source_file, [])

            mock_find_tests.side_effect = find_tests_side_effect

            # Only factory tests fail, models and utils pass
            mock_run_tests.return_value = (
                False,
                1,
                "FAILED tests/unit/app/core/test_factory.py::test_one\nFAILED tests/unit/app/core/test_factory.py::test_two",
                [
                    "tests/unit/app/core/test_factory.py::test_one",
                    "tests/unit/app/core/test_factory.py::test_two",
                ],
            )

            files = [
                "app/core/factory.py",
                "app/core/models.py",
                "app/core/utils.py",
            ]
            results = run_tests_for_files(files, tiers=mock_tiers)

            factory_result = next(r for r in results if r.file == "app/core/factory.py")
            models_result = next(r for r in results if r.file == "app/core/models.py")
            utils_result = next(r for r in results if r.file == "app/core/utils.py")

            # factory.py failed
            assert not factory_result.passed
            assert len(factory_result.failed_tests) == 2

            # models.py and utils.py pass despite being in same tier run
            assert models_result.passed
            assert models_result.failed_tests == []
            assert utils_result.passed
            assert utils_result.failed_tests == []

    def test_handles_absolute_paths_in_failed_tests(self, mock_tiers: list[TierConfig]) -> None:
        """Test that absolute paths in failed test output are correctly matched."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):

            def find_tests_side_effect(source_file: str, tier: TierConfig) -> list[str]:
                if source_file == "app/core/factory.py":
                    return ["tests/unit/app/core/test_factory.py"]
                return []

            mock_find_tests.side_effect = find_tests_side_effect

            # Simulate pytest returning absolute paths
            mock_run_tests.return_value = (
                False,
                1,
                "FAILED /home/user/project/tests/unit/app/core/test_factory.py::test_create",
                ["/home/user/project/tests/unit/app/core/test_factory.py::test_create"],
            )

            files = ["app/core/factory.py"]
            results = run_tests_for_files(files, tiers=mock_tiers)

            factory_result = results[0]

            # Should match despite absolute path in output
            assert not factory_result.passed
            assert len(factory_result.failed_tests) == 1

    def test_avoids_substring_false_positives(self, mock_tiers: list[TierConfig]) -> None:
        """Test that substring matches do not cause false positive failure mapping."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):
            # test_foo.py vs test_foobar.py - substring match should not occur
            def find_tests_side_effect(source_file: str, tier: TierConfig) -> list[str]:
                if source_file == "app/core/foo.py":
                    return ["tests/unit/app/core/test_foo.py"]
                elif source_file == "app/core/foobar.py":
                    return ["tests/unit/app/core/test_foobar.py"]
                return []

            mock_find_tests.side_effect = find_tests_side_effect

            # Only test_foobar.py fails
            mock_run_tests.return_value = (
                False,
                1,
                "FAILED tests/unit/app/core/test_foobar.py::test_something",
                ["tests/unit/app/core/test_foobar.py::test_something"],
            )

            files = ["app/core/foo.py", "app/core/foobar.py"]
            results = run_tests_for_files(files, tiers=mock_tiers)

            foo_result = next(r for r in results if r.file == "app/core/foo.py")
            foobar_result = next(r for r in results if r.file == "app/core/foobar.py")

            # foo.py should NOT have test_foobar.py failures attributed to it
            assert foo_result.passed
            assert foo_result.failed_tests == []

            # foobar.py should have the failure
            assert not foobar_result.passed
            assert len(foobar_result.failed_tests) == 1

    def test_handles_relative_paths_in_test_mapping(self, mock_tiers: list[TierConfig]) -> None:
        """Test that relative paths work correctly in test file mapping."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):

            def find_tests_side_effect(source_file: str, tier: TierConfig) -> list[str]:
                if source_file == "app/core/factory.py":
                    return ["tests/unit/app/core/test_factory.py"]
                return []

            mock_find_tests.side_effect = find_tests_side_effect

            # Relative path in output (normal pytest behavior)
            mock_run_tests.return_value = (
                False,
                1,
                "FAILED tests/unit/app/core/test_factory.py::test_create",
                ["tests/unit/app/core/test_factory.py::test_create"],
            )

            files = ["app/core/factory.py"]
            results = run_tests_for_files(files, tiers=mock_tiers)

            assert len(results) == 1
            assert not results[0].passed
            assert len(results[0].failed_tests) == 1

    def test_multiple_tiers_run_independently(self, mock_tiers: list[TierConfig]) -> None:
        """Test that files in different tiers are tested independently."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):

            def find_tests_side_effect(source_file: str, tier: TierConfig) -> list[str]:
                if source_file == "app/core/factory.py":
                    return ["tests/unit/app/core/test_factory.py"]
                elif source_file == "scripts/dev/linter.py":
                    return ["scripts/tests/dev/test_linter.py"]
                return []

            mock_find_tests.side_effect = find_tests_side_effect

            # Track which test files were passed to run_tests
            test_file_calls: list[list[str]] = []

            def run_tests_side_effect(
                test_files: list[str], timeout: int = 300
            ) -> tuple[bool, int, str, list[str]]:
                test_file_calls.append(test_files)
                return (True, 0, "All tests passed", [])

            mock_run_tests.side_effect = run_tests_side_effect

            files = ["app/core/factory.py", "scripts/dev/linter.py"]
            run_tests_for_files(files, tiers=mock_tiers)

            # Verify run_tests was called twice (once per tier)
            assert len(test_file_calls) == 2

            # Verify each tier got its own test files
            all_test_files = [tf for call in test_file_calls for tf in call]
            assert "tests/unit/app/core/test_factory.py" in all_test_files
            assert "scripts/tests/dev/test_linter.py" in all_test_files

    def test_infra_error_marks_all_files_as_failed(self, mock_tiers: list[TierConfig]) -> None:
        """Test that infrastructure errors (timeout, OSError) mark all files as failed."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):

            def find_tests_side_effect(source_file: str, tier: TierConfig) -> list[str]:
                if source_file == "app/core/factory.py":
                    return ["tests/unit/app/core/test_factory.py"]
                elif source_file == "app/core/models.py":
                    return ["tests/unit/app/core/test_models.py"]
                return []

            mock_find_tests.side_effect = find_tests_side_effect

            # Simulate timeout (exit_code -1)
            mock_run_tests.return_value = (
                False,
                -1,
                "Test timeout after 300s",
                [],
            )

            files = ["app/core/factory.py", "app/core/models.py"]
            results = run_tests_for_files(files, tiers=mock_tiers)

            # Both files should be marked as failed due to infra error
            assert all(not r.passed for r in results)
            assert all(r.exit_code == -1 for r in results)


class TestRunTestsForFilesEmptyTiers:
    def test_raises_error_when_load_returns_empty(self) -> None:
        """Test that error is raised when load_tier_configs returns empty list."""
        with patch("scripts.dev.test_runner.test_files.load_tier_configs") as mock_load:
            mock_load.return_value = []

            with pytest.raises(ValueError) as exc_info:
                run_tests_for_files(["app/core/factory.py"])

            assert "No tier configurations found" in str(exc_info.value)


class TestRunTestsForFilesNoTestsFound:
    @pytest.fixture
    def mock_tiers(self) -> list[TierConfig]:
        """Create mock tier configurations for testing."""
        return [
            TierConfig(
                name="unit",
                test_path="tests/unit",
                source_patterns=["app/**/*.py"],
            ),
        ]

    def test_no_tests_found_sets_no_tests_true(self, mock_tiers: list[TierConfig]) -> None:
        """Test that files with no matching tests have no_tests=True."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):
            # No test files found for this source file
            mock_find_tests.return_value = []
            mock_run_tests.return_value = (True, 0, "No test files to run", [])

            files = ["app/core/factory.py"]
            results = run_tests_for_files(files, tiers=mock_tiers)

            assert len(results) == 1
            result = results[0]
            assert result.no_tests is True
            assert result.passed is False
            assert result.test_files == []
            assert result.output == "No tests found for source file"

    def test_no_tests_found_sets_passed_false(self, mock_tiers: list[TierConfig]) -> None:
        """Test that files with no matching tests are marked as failed."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):
            mock_find_tests.return_value = []
            mock_run_tests.return_value = (True, 0, "No test files to run", [])

            files = ["app/core/factory.py"]
            results = run_tests_for_files(files, tiers=mock_tiers)

            assert len(results) == 1
            assert results[0].passed is False

    def test_with_tests_has_no_tests_false(self, mock_tiers: list[TierConfig]) -> None:
        """Test that files with matching tests have no_tests=False."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):
            mock_find_tests.return_value = ["tests/unit/app/core/test_factory.py"]
            mock_run_tests.return_value = (True, 0, "All tests passed", [])

            files = ["app/core/factory.py"]
            results = run_tests_for_files(files, tiers=mock_tiers)

            assert len(results) == 1
            result = results[0]
            assert result.no_tests is False
            assert result.passed is True
            assert result.test_files == ["tests/unit/app/core/test_factory.py"]

    def test_mixed_files_some_with_no_tests(self, mock_tiers: list[TierConfig]) -> None:
        """Test that files with and without tests are handled correctly together."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):

            def find_tests_side_effect(source_file: str, tier: TierConfig) -> list[str]:
                if source_file == "app/core/factory.py":
                    return ["tests/unit/app/core/test_factory.py"]
                # No tests for models.py
                return []

            mock_find_tests.side_effect = find_tests_side_effect
            mock_run_tests.return_value = (True, 0, "All tests passed", [])

            files = ["app/core/factory.py", "app/core/models.py"]
            results = run_tests_for_files(files, tiers=mock_tiers)

            factory_result = next(r for r in results if r.file == "app/core/factory.py")
            models_result = next(r for r in results if r.file == "app/core/models.py")

            # factory.py has tests and passes
            assert factory_result.no_tests is False
            assert factory_result.passed is True

            # models.py has no tests
            assert models_result.no_tests is True
            assert models_result.passed is False
            assert models_result.output == "No tests found for source file"

    def test_consumers_can_distinguish_no_tests_from_test_pass(
        self, mock_tiers: list[TierConfig]
    ) -> None:
        """Test that consumers can distinguish 'no tests' from 'tests passed'."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):

            def find_tests_side_effect(source_file: str, tier: TierConfig) -> list[str]:
                if source_file == "app/core/factory.py":
                    return ["tests/unit/app/core/test_factory.py"]
                return []

            mock_find_tests.side_effect = find_tests_side_effect
            mock_run_tests.return_value = (True, 0, "All tests passed", [])

            files = ["app/core/factory.py", "app/core/models.py"]
            results = run_tests_for_files(files, tiers=mock_tiers)

            # Filter logic consumers can use
            tests_passed = [r for r in results if r.passed and not r.no_tests]
            no_tests = [r for r in results if r.no_tests]
            tests_failed = [r for r in results if not r.passed and not r.no_tests]

            assert len(tests_passed) == 1
            assert tests_passed[0].file == "app/core/factory.py"

            assert len(no_tests) == 1
            assert no_tests[0].file == "app/core/models.py"

            assert len(tests_failed) == 0


class TestUnattributedFailedTests:
    @pytest.fixture
    def mock_tiers(self) -> list[TierConfig]:
        """Create mock tier configurations for testing."""
        return [
            TierConfig(
                name="unit",
                test_path="tests/unit",
                source_patterns=["app/**/*.py"],
            ),
        ]

    def test_creates_synthetic_result_for_unattributed_failures(
        self, mock_tiers: list[TierConfig]
    ) -> None:
        """Unattributed failures create a synthetic TestResult with file='<unattributed>'."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):
            # Source file has test_factory.py, but failure is in test_other.py
            def find_tests_side_effect(source_file: str, tier: TierConfig) -> list[str]:
                if source_file == "app/core/factory.py":
                    return ["tests/unit/app/core/test_factory.py"]
                return []

            mock_find_tests.side_effect = find_tests_side_effect

            # Failure in a test file not mapped to any source file
            mock_run_tests.return_value = (
                False,
                1,
                "FAILED tests/unit/app/other/test_unmapped.py::test_something",
                ["tests/unit/app/other/test_unmapped.py::test_something"],
            )

            files = ["app/core/factory.py"]
            results = run_tests_for_files(files, tiers=mock_tiers)

            # Should have 2 results: one for factory.py (passed), one for unattributed
            assert len(results) == 2

            factory_result = next(r for r in results if r.file == "app/core/factory.py")
            unattributed_result = next(r for r in results if r.file == "<unattributed>")

            # factory.py should pass (its test file didn't fail)
            assert factory_result.passed is True
            assert factory_result.failed_tests == []

            # Unattributed result should have the unmapped failure
            assert unattributed_result.passed is False
            assert unattributed_result.tier == "unit"
            assert (
                "tests/unit/app/other/test_unmapped.py::test_something"
                in unattributed_result.failed_tests
            )

    def test_no_synthetic_result_when_all_failures_attributed(
        self, mock_tiers: list[TierConfig]
    ) -> None:
        """No synthetic result is created when all failures are attributed to source files."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):

            def find_tests_side_effect(source_file: str, tier: TierConfig) -> list[str]:
                if source_file == "app/core/factory.py":
                    return ["tests/unit/app/core/test_factory.py"]
                return []

            mock_find_tests.side_effect = find_tests_side_effect

            # Failure in the mapped test file
            mock_run_tests.return_value = (
                False,
                1,
                "FAILED tests/unit/app/core/test_factory.py::test_create",
                ["tests/unit/app/core/test_factory.py::test_create"],
            )

            files = ["app/core/factory.py"]
            results = run_tests_for_files(files, tiers=mock_tiers)

            # Should only have 1 result for factory.py (no unattributed)
            assert len(results) == 1
            assert results[0].file == "app/core/factory.py"
            assert results[0].passed is False
            assert "tests/unit/app/core/test_factory.py::test_create" in results[0].failed_tests

    def test_no_synthetic_result_when_no_failures(self, mock_tiers: list[TierConfig]) -> None:
        """No synthetic result is created when there are no failures."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):

            def find_tests_side_effect(source_file: str, tier: TierConfig) -> list[str]:
                if source_file == "app/core/factory.py":
                    return ["tests/unit/app/core/test_factory.py"]
                return []

            mock_find_tests.side_effect = find_tests_side_effect
            mock_run_tests.return_value = (True, 0, "All tests passed", [])

            files = ["app/core/factory.py"]
            results = run_tests_for_files(files, tiers=mock_tiers)

            # Should only have 1 result for factory.py
            assert len(results) == 1
            assert results[0].file == "app/core/factory.py"
            assert results[0].passed is True

    def test_logs_warning_for_unattributed_failures(self, mock_tiers: list[TierConfig]) -> None:
        """A warning is logged when unattributed failures are detected."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
            patch("scripts.dev.test_runner.test_files.logger") as mock_logger,
        ):

            def find_tests_side_effect(source_file: str, tier: TierConfig) -> list[str]:
                if source_file == "app/core/factory.py":
                    return ["tests/unit/app/core/test_factory.py"]
                return []

            mock_find_tests.side_effect = find_tests_side_effect

            mock_run_tests.return_value = (
                False,
                1,
                "FAILED tests/unit/app/other/test_unmapped.py::test_something",
                ["tests/unit/app/other/test_unmapped.py::test_something"],
            )

            files = ["app/core/factory.py"]
            run_tests_for_files(files, tiers=mock_tiers)

            # Verify warning was logged
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert "unit" in call_args[0][1]  # tier name
            assert call_args[0][2] == 1  # count of unattributed

    def test_multiple_unattributed_failures(self, mock_tiers: list[TierConfig]) -> None:
        """Multiple unattributed failures are collected in the synthetic result."""
        with (
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):

            def find_tests_side_effect(source_file: str, tier: TierConfig) -> list[str]:
                if source_file == "app/core/factory.py":
                    return ["tests/unit/app/core/test_factory.py"]
                return []

            mock_find_tests.side_effect = find_tests_side_effect

            # Multiple failures in unmapped test files
            mock_run_tests.return_value = (
                False,
                1,
                "FAILED tests/unit/app/other/test_a.py::test_one\nFAILED tests/unit/app/other/test_b.py::test_two",
                [
                    "tests/unit/app/other/test_a.py::test_one",
                    "tests/unit/app/other/test_b.py::test_two",
                ],
            )

            files = ["app/core/factory.py"]
            results = run_tests_for_files(files, tiers=mock_tiers)

            unattributed_result = next(r for r in results if r.file == "<unattributed>")
            assert len(unattributed_result.failed_tests) == 2
            assert "tests/unit/app/other/test_a.py::test_one" in unattributed_result.failed_tests
            assert "tests/unit/app/other/test_b.py::test_two" in unattributed_result.failed_tests


class TestFindTestFilesFallbackLogging:
    def test_logs_debug_when_fallback_matches_tests(self, tmp_path: Path) -> None:
        """Debug message is logged when fallback glob pattern matches tests."""
        # Create a temporary test file structure
        test_base = tmp_path / "tests" / "unit"
        test_base.mkdir(parents=True)
        (test_base / "test_mymodule_foo.py").touch()

        tier = TierConfig(
            name="unit",
            test_path=str(test_base.relative_to(tmp_path)),
            source_patterns=["app/**/*.py"],
        )

        with (
            patch("scripts.dev.test_runner.test_files.REPO_ROOT", tmp_path),
            patch("scripts.dev.test_runner.test_files.logger") as mock_logger,
        ):
            # Source file that doesn't have direct mapping, triggers fallback
            find_test_files("app/mymodule.py", tier)

            # Verify debug was logged with matches
            mock_logger.debug.assert_called_once()
            call_args = mock_logger.debug.call_args
            assert "Fallback glob pattern matched tests" in call_args[0][0]
            assert "mymodule" in call_args[0][1]  # module_name

    def test_logs_debug_when_fallback_finds_no_tests(self, tmp_path: Path) -> None:
        """Debug message is logged when fallback glob pattern finds no tests."""
        # Create empty test directory
        test_base = tmp_path / "tests" / "unit"
        test_base.mkdir(parents=True)

        tier = TierConfig(
            name="unit",
            test_path=str(test_base.relative_to(tmp_path)),
            source_patterns=["app/**/*.py"],
        )

        with (
            patch("scripts.dev.test_runner.test_files.REPO_ROOT", tmp_path),
            patch("scripts.dev.test_runner.test_files.logger") as mock_logger,
        ):
            # Source file with no matching tests
            find_test_files("app/orphan.py", tier)

            # Verify debug was logged indicating no matches
            mock_logger.debug.assert_called_once()
            call_args = mock_logger.debug.call_args
            assert "found no tests" in call_args[0][0]
            assert "orphan" in call_args[0][1]  # module_name


class TestNoMatchingTierLogging:
    @pytest.fixture
    def mock_tiers(self) -> list[TierConfig]:
        """Create mock tier configurations for testing."""
        return [
            TierConfig(
                name="unit",
                test_path="tests/unit",
                source_patterns=["app/**/*.py"],
            ),
        ]

    def test_logs_warning_when_file_has_no_matching_tier(
        self, mock_tiers: list[TierConfig]
    ) -> None:
        """A warning is logged when a file doesn't match any tier patterns."""
        with patch("scripts.dev.test_runner.test_files.logger") as mock_logger:
            # File that doesn't match any tier pattern
            files = ["unknown/path/file.py"]
            run_tests_for_files(files, tiers=mock_tiers)

            # Verify warning was logged
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert "No matching tier" in call_args[0][0]
            assert "unknown/path/file.py" in call_args[0][1]

    def test_no_warning_when_file_matches_tier(self, mock_tiers: list[TierConfig]) -> None:
        """No warning is logged when a file matches a tier."""
        with (
            patch("scripts.dev.test_runner.test_files.logger") as mock_logger,
            patch("scripts.dev.test_runner.test_files.find_test_files") as mock_find_tests,
            patch("scripts.dev.test_runner.test_files.run_tests") as mock_run_tests,
        ):
            mock_find_tests.return_value = ["tests/unit/app/core/test_factory.py"]
            mock_run_tests.return_value = (True, 0, "All tests passed", [])

            files = ["app/core/factory.py"]
            run_tests_for_files(files, tiers=mock_tiers)

            # No warning should be logged
            mock_logger.warning.assert_not_called()


class TestFallbackWarning:
    def test_logs_warning_when_fallback_is_used(self) -> None:
        """Warning is logged once when fallback regex matching is used."""
        with (
            patch.object(test_files_module, "_HAS_FULL_MATCH", False),
            patch.object(test_files_module, "_FALLBACK_WARNING_LOGGED", False),
            patch("scripts.dev.test_runner.test_files.logger") as mock_logger,
        ):
            # First call should log warning
            match_pattern("app/core/factory.py", "app/**/*.py")

            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert "fallback regex-based glob matching" in call_args[0][0]
            assert "Python < 3.13" in call_args[0][0]

    def test_warning_logged_only_once(self) -> None:
        """Warning is logged only once even with multiple match_pattern calls."""
        with (
            patch.object(test_files_module, "_HAS_FULL_MATCH", False),
            patch.object(test_files_module, "_FALLBACK_WARNING_LOGGED", False),
            patch("scripts.dev.test_runner.test_files.logger") as mock_logger,
        ):
            # Multiple calls
            match_pattern("app/core/factory.py", "app/**/*.py")
            match_pattern("app/core/models.py", "app/**/*.py")
            match_pattern("scripts/dev/linter.py", "scripts/**/*.py")

            # Warning should be logged only once
            assert mock_logger.warning.call_count == 1

    def test_no_warning_when_full_match_available(self) -> None:
        """No warning is logged when PurePosixPath.full_match is available."""
        # Only run this test if full_match is actually available (Python 3.13+)
        if not _HAS_FULL_MATCH:
            pytest.skip("PurePosixPath.full_match not available")

        with patch("scripts.dev.test_runner.test_files.logger") as mock_logger:
            match_pattern("app/core/factory.py", "app/**/*.py")

            # No fallback warning should be logged
            for call in mock_logger.warning.call_args_list:
                assert "fallback regex-based glob matching" not in call[0][0]

    def test_warning_mentions_docstring_for_limitations(self) -> None:
        """Warning message directs users to docstring for known limitations."""
        with (
            patch.object(test_files_module, "_HAS_FULL_MATCH", False),
            patch.object(test_files_module, "_FALLBACK_WARNING_LOGGED", False),
            patch("scripts.dev.test_runner.test_files.logger") as mock_logger,
        ):
            match_pattern("app/core/factory.py", "app/**/*.py")

            call_args = mock_logger.warning.call_args
            assert "_glob_pattern_to_regex" in call_args[0][0]
            assert "limitations" in call_args[0][0].lower()
