import pytest

from scripts.dev.linter.base import (
    InvalidCommandError,
    LinterResult,
    filter_files_with_config,
    get_executable,
    run_checked,
)


class TestInvalidCommandError:
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


class TestRunChecked:
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


class TestLinterResult:
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
