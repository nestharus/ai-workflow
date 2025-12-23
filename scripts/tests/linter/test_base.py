"""Tests for linter base module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.dev.linter.base import (
    InvalidCommandError,
    LinterResult,
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
