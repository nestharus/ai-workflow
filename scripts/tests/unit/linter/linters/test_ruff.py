from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.linter.base import LinterResult
from scripts.dev.linter.linters.ruff import RuffLinter


class TestRuffLinterRunWithFiles:
    @patch("scripts.dev.linter.linters.ruff.filter_files_with_config")
    @patch("scripts.dev.linter.linters.ruff.run_checked")
    @patch("scripts.dev.linter.linters.ruff.get_executable")
    def test_run_with_python_files(
        self,
        mock_get_exe: MagicMock,
        mock_run_checked: MagicMock,
        mock_filter: MagicMock,
    ) -> None:
        """Test run with Python files specified (lines 31-41, branch 32 True)."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_filter.return_value = (["app/main.py", "app/utils.py"], None)

        linter = RuffLinter()
        result = linter.run(files=["app/main.py", "config.yaml", "app/utils.py"])

        assert result.success is True
        assert mock_run_checked.call_count == 2  # format + check
        calls = mock_run_checked.call_args_list
        # First call should be format
        assert "format" in calls[0][0][0]
        # Second call should be check --fix
        assert "check" in calls[1][0][0]
        assert "--fix" in calls[1][0][0]

    @patch("scripts.dev.linter.linters.ruff.get_executable")
    def test_run_with_no_python_files(
        self,
        mock_get_exe: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when no Python files in list (lines 33-36, branch 34 True)."""
        mock_get_exe.return_value = "/usr/bin/uv"

        linter = RuffLinter()
        result = linter.run(files=["config.yaml", "README.md"])

        assert result.success is True
        captured = capsys.readouterr()
        assert "No Python files to lint with ruff" in captured.out


class TestRuffLinterConfigErrors:
    @patch("scripts.dev.linter.linters.ruff.run_checked")
    @patch("scripts.dev.linter.linters.ruff.filter_files_with_config")
    @patch("scripts.dev.linter.linters.ruff.get_executable")
    def test_run_config_file_not_found(
        self,
        mock_get_exe: MagicMock,
        mock_filter: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run when config file is not found."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_filter.return_value = (
            [],
            LinterResult(success=False, message="Config file not found"),
        )

        linter = RuffLinter()
        result = linter.run(files=["test.py"])

        assert result.success is False
        assert result.message == "Config file not found"
        mock_run_checked.assert_not_called()

    @patch("scripts.dev.linter.linters.ruff.run_checked")
    @patch("scripts.dev.linter.linters.ruff.filter_files_with_config")
    @patch("scripts.dev.linter.linters.ruff.get_executable")
    def test_run_config_parse_error(
        self,
        mock_get_exe: MagicMock,
        mock_filter: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run when config file has parse errors."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_filter.return_value = (
            [],
            LinterResult(success=False, message="Config load error: YAML parse error"),
        )

        linter = RuffLinter()
        result = linter.run(files=["test.py"])

        assert result.success is False
        assert "Config load error" in (result.message or "")
        mock_run_checked.assert_not_called()

    @patch("scripts.dev.linter.linters.ruff.run_checked")
    @patch("scripts.dev.linter.linters.ruff.filter_files_with_config")
    @patch("scripts.dev.linter.linters.ruff.get_executable")
    def test_run_included_paths_invalid_type(
        self,
        mock_get_exe: MagicMock,
        mock_filter: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run when included_paths is not a list."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_filter.return_value = (
            [],
            LinterResult(success=False, message="Invalid included_paths config"),
        )

        linter = RuffLinter()
        result = linter.run(files=["test.py"])

        assert result.success is False
        assert result.message == "Invalid included_paths config"
        mock_run_checked.assert_not_called()


class TestRuffLinterRunWithoutFiles:
    @patch("scripts.dev.linter.linters.ruff.run_checked")
    @patch("scripts.dev.linter.linters.ruff.get_executable")
    def test_run_full_repo_scan(
        self,
        mock_get_exe: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run without files (full repo scan) (line 29, branch 32 False)."""
        mock_get_exe.return_value = "/usr/bin/uv"

        linter = RuffLinter()
        result = linter.run(files=None)

        assert result.success is True
        assert mock_run_checked.call_count == 2
        # Verify "." is used for full repo
        format_call = mock_run_checked.call_args_list[0][0][0]
        check_call = mock_run_checked.call_args_list[1][0][0]
        assert "." in format_call
        assert "." in check_call


class TestRuffLinterRunCheckedCalls:
    @patch("scripts.dev.linter.linters.ruff.filter_files_with_config")
    @patch("scripts.dev.linter.linters.ruff.run_checked")
    @patch("scripts.dev.linter.linters.ruff.get_executable")
    def test_run_checked_call_order(
        self,
        mock_get_exe: MagicMock,
        mock_run_checked: MagicMock,
        mock_filter: MagicMock,
    ) -> None:
        """Test that format is called before check (lines 39-40)."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_filter.return_value = (["test.py"], None)

        linter = RuffLinter()
        result = linter.run(files=["test.py"])

        assert result.success is True
        calls = mock_run_checked.call_args_list
        format_call_idx = None
        check_call_idx = None
        for i, c in enumerate(calls):
            if "format" in c[0][0]:
                format_call_idx = i
            if "check" in c[0][0]:
                check_call_idx = i
        assert format_call_idx is not None
        assert check_call_idx is not None
        assert format_call_idx < check_call_idx  # format before check

    @patch("scripts.dev.linter.linters.ruff.filter_files_with_config")
    @patch("scripts.dev.linter.linters.ruff.run_checked")
    @patch("scripts.dev.linter.linters.ruff.get_executable")
    def test_run_checked_includes_fix_flag(
        self,
        mock_get_exe: MagicMock,
        mock_run_checked: MagicMock,
        mock_filter: MagicMock,
    ) -> None:
        """Test that check command includes --fix flag (line 40)."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_filter.return_value = (["test.py"], None)

        linter = RuffLinter()
        result = linter.run(files=["test.py"])

        assert result.success is True
        check_call = None
        for c in mock_run_checked.call_args_list:
            if "check" in c[0][0]:
                check_call = c[0][0]
                break
        assert check_call is not None
        assert "--fix" in check_call
