"""Tests for linter base module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from scripts.dev.linter.base import (
    InvalidCommandError,
    LinterResult,
    filter_files_with_config,
    get_executable,
    run_checked,
)


class TestInvalidCommandError:
    """Tests for InvalidCommandError exception class."""

    def test_init_sets_standard_message(self) -> None:
        """Test that __init__ sets the standard validation message (line 28)."""
        error = InvalidCommandError()
        assert str(error) == "command must be a non-empty list of strings"

    def test_is_type_error(self) -> None:
        """Test that InvalidCommandError is a TypeError."""
        error = InvalidCommandError()
        assert isinstance(error, TypeError)

    def test_can_be_raised_and_caught(self) -> None:
        """Test that InvalidCommandError can be raised and caught properly."""
        with pytest.raises(InvalidCommandError) as exc_info:
            raise InvalidCommandError()
        assert "command must be a non-empty list of strings" in str(exc_info.value)


class TestGetExecutable:
    """Tests for get_executable function."""

    def test_get_executable_found(self) -> None:
        """Test get_executable when executable exists."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/python"
            result = get_executable("python", "Python not found")
            assert result == "/usr/bin/python"
            mock_which.assert_called_once_with("python")

    def test_get_executable_not_found_raises_runtime_error(self) -> None:
        """Test get_executable raises RuntimeError when executable not found (lines 77-80)."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = None  # Simulates executable not found
            with pytest.raises(RuntimeError) as exc_info:
                get_executable("nonexistent_tool", "Custom error: tool not found")
            assert str(exc_info.value) == "Custom error: tool not found"
            mock_which.assert_called_once_with("nonexistent_tool")

    def test_get_executable_not_found_with_different_messages(self) -> None:
        """Test get_executable with different error messages."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = None

            # Test with detailed error message
            with pytest.raises(RuntimeError) as exc_info:
                get_executable(
                    "gitleaks", "gitleaks not found. Install with: brew install gitleaks"
                )
            assert "gitleaks not found" in str(exc_info.value)

    def test_get_executable_returns_string_path(self) -> None:
        """Test that get_executable returns a string path."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/local/bin/ruff"
            result = get_executable("ruff", "ruff not found")
            assert isinstance(result, str)
            assert result == "/usr/local/bin/ruff"


class TestRunChecked:
    """Tests for run_checked function."""

    def test_run_checked_success(self) -> None:
        """Test run_checked with a successful command."""
        with patch("subprocess.check_call") as mock_check_call:
            mock_check_call.return_value = 0
            run_checked(["echo", "hello"])
            mock_check_call.assert_called_once_with(["echo", "hello"], cwd=None)

    def test_run_checked_with_cwd(self) -> None:
        """Test run_checked with a working directory."""
        with patch("subprocess.check_call") as mock_check_call:
            mock_check_call.return_value = 0
            cwd = Path("/tmp")
            run_checked(["ls", "-la"], cwd=cwd)
            mock_check_call.assert_called_once_with(["ls", "-la"], cwd=cwd)

    def test_run_checked_empty_list_raises_invalid_command_error(self) -> None:
        """Test run_checked with empty list raises InvalidCommandError (lines 44, 47-48)."""
        with pytest.raises(InvalidCommandError) as exc_info:
            run_checked([])
        assert "command must be a non-empty list of strings" in str(exc_info.value)

    def test_run_checked_non_list_raises_invalid_command_error(self) -> None:
        """Test run_checked with non-list raises InvalidCommandError (line 44)."""
        with pytest.raises(InvalidCommandError):
            run_checked("echo hello")  # type: ignore[arg-type]

    def test_run_checked_list_with_non_strings_raises_invalid_command_error(self) -> None:
        """Test run_checked with non-string elements raises InvalidCommandError (line 44)."""
        with pytest.raises(InvalidCommandError):
            run_checked(["echo", 123])  # type: ignore[list-item]

    def test_run_checked_none_raises_invalid_command_error(self) -> None:
        """Test run_checked with None raises InvalidCommandError."""
        with pytest.raises(InvalidCommandError):
            run_checked(None)  # type: ignore[arg-type]

    def test_run_checked_mixed_types_raises_invalid_command_error(self) -> None:
        """Test run_checked with mixed types in list raises InvalidCommandError."""
        with pytest.raises(InvalidCommandError):
            run_checked(["command", None, "arg"])  # type: ignore[list-item]

    def test_run_checked_subprocess_error_propagates(self) -> None:
        """Test that subprocess errors propagate correctly."""
        with patch("subprocess.check_call") as mock_check_call:
            mock_check_call.side_effect = subprocess.CalledProcessError(1, "test")
            with pytest.raises(subprocess.CalledProcessError):
                run_checked(["failing_command"])


class TestLinterResult:
    """Tests for LinterResult dataclass."""

    def test_linter_result_success(self) -> None:
        """Test creating a successful LinterResult."""
        result = LinterResult(success=True)
        assert result.success is True
        assert result.message is None

    def test_linter_result_failure_with_message(self) -> None:
        """Test creating a failed LinterResult with message."""
        result = LinterResult(success=False, message="Linting failed")
        assert result.success is False
        assert result.message == "Linting failed"

    def test_linter_result_success_with_message(self) -> None:
        """Test creating a successful LinterResult with message."""
        result = LinterResult(success=True, message="All checks passed")
        assert result.success is True
        assert result.message == "All checks passed"


class TestFilterFilesWithConfig:
    """Tests for filter_files_with_config helper function."""

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_config_file_not_found(
        self,
        mock_load_yaml_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test when config file is not found."""
        mock_load_yaml_config.side_effect = FileNotFoundError("Config not found")

        files, error = filter_files_with_config(["test.py"], Path("/fake/config.yaml"), "mypy")

        assert files == []
        assert error is not None
        assert error.success is False
        assert error.message == "Config file not found"
        captured = capsys.readouterr()
        assert "Mypy config file not found" in captured.out

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_config_yaml_parse_error(
        self,
        mock_load_yaml_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test when config file has YAML parse errors."""
        mock_load_yaml_config.side_effect = yaml.YAMLError("invalid YAML syntax")

        files, error = filter_files_with_config(["test.py"], Path("/fake/config.yaml"), "ruff")

        assert files == []
        assert error is not None
        assert error.success is False
        assert "Config parse error" in (error.message or "")
        captured = capsys.readouterr()
        assert "Failed to parse ruff config" in captured.out
        assert "invalid YAML syntax" in captured.out

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_config_permission_error(
        self,
        mock_load_yaml_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test when config file has permission issues."""
        mock_load_yaml_config.side_effect = PermissionError("Permission denied")

        files, error = filter_files_with_config(["test.py"], Path("/fake/config.yaml"), "mypy")

        assert files == []
        assert error is not None
        assert error.success is False
        assert "Config permission error" in (error.message or "")
        captured = capsys.readouterr()
        assert "Permission denied reading mypy config" in captured.out

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_unexpected_exception_propagates(
        self,
        mock_load_yaml_config: MagicMock,
    ) -> None:
        """Test that unexpected exceptions propagate instead of being swallowed."""
        mock_load_yaml_config.side_effect = RuntimeError("Unexpected error")

        with pytest.raises(RuntimeError, match="Unexpected error"):
            filter_files_with_config(["test.py"], Path("/fake/config.yaml"), "ruff")

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_included_paths_invalid_type(
        self,
        mock_load_yaml_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test when included_paths is not a list."""
        mock_load_yaml_config.return_value = {"included_paths": "not-a-list"}

        files, error = filter_files_with_config(["test.py"], Path("/fake/config.yaml"), "mypy")

        assert files == []
        assert error is not None
        assert error.success is False
        assert error.message == "Invalid included_paths config"
        captured = capsys.readouterr()
        assert "Invalid included_paths in mypy config" in captured.out
        assert "expected list" in captured.out

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_no_included_paths_returns_all_files(
        self,
        mock_load_yaml_config: MagicMock,
    ) -> None:
        """Test when config has no included_paths - all files returned."""
        mock_load_yaml_config.return_value = {}

        files, error = filter_files_with_config(
            ["app/main.py", "tests/test_main.py"], Path("/fake/config.yaml"), "mypy"
        )

        assert files == ["app/main.py", "tests/test_main.py"]
        assert error is None

    @patch("scripts.dev.linter.base.load_yaml_config")
    @patch("scripts.dev.linter.base.is_path_included")
    def test_filters_files_by_included_paths(
        self,
        mock_is_included: MagicMock,
        mock_load_yaml_config: MagicMock,
    ) -> None:
        """Test filtering files with included_paths patterns."""
        mock_load_yaml_config.return_value = {"included_paths": ["app/**/*.py"]}
        mock_is_included.side_effect = lambda path, patterns: path.startswith("app/")

        files, error = filter_files_with_config(
            ["app/main.py", "tests/test_main.py", "app/utils.py"],
            Path("/fake/config.yaml"),
            "mypy",
        )

        assert files == ["app/main.py", "app/utils.py"]
        assert error is None

    @patch("scripts.dev.linter.base.load_yaml_config")
    @patch("scripts.dev.linter.base.is_path_included")
    def test_all_files_filtered_returns_empty_list(
        self,
        mock_is_included: MagicMock,
        mock_load_yaml_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test when all files are filtered out."""
        mock_load_yaml_config.return_value = {"included_paths": ["app/**/*.py"]}
        mock_is_included.return_value = False

        files, error = filter_files_with_config(
            ["tests/test_main.py", "tests/test_utils.py"],
            Path("/fake/config.yaml"),
            "mypy",
        )

        assert files == []
        assert error is None
        captured = capsys.readouterr()
        assert "No Python files match mypy included_paths filter" in captured.out

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_empty_included_paths_list_returns_all_files(
        self,
        mock_load_yaml_config: MagicMock,
    ) -> None:
        """Test when included_paths is empty list - all files returned."""
        mock_load_yaml_config.return_value = {"included_paths": []}

        files, error = filter_files_with_config(
            ["app/main.py", "tests/test_main.py"], Path("/fake/config.yaml"), "ruff"
        )

        assert files == ["app/main.py", "tests/test_main.py"]
        assert error is None
