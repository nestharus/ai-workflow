"""Tests for scripts.dev.linter.linters.ruff module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.linter.linters.ruff import RuffLinter


class TestRuffLinterInit:
    """Tests for RuffLinter class attributes."""

    def test_name(self) -> None:
        """Test linter name attribute."""
        linter = RuffLinter()
        assert linter.name == "ruff"

    def test_supports_file_filtering(self) -> None:
        """Test supports_file_filtering attribute."""
        linter = RuffLinter()
        assert linter.supports_file_filtering is True


class TestRuffLinterRunWithFiles:
    """Tests for RuffLinter.run with file filtering."""

    @patch("scripts.dev.linter.linters.ruff.run_checked")
    @patch("scripts.dev.linter.linters.ruff.get_executable")
    def test_run_with_python_files(
        self,
        mock_get_exe: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run with Python files specified (lines 31-41, branch 32 True)."""
        mock_get_exe.return_value = "/usr/bin/uv"

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


class TestRuffLinterRunWithoutFiles:
    """Tests for RuffLinter.run without file filtering."""

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
    """Tests for RuffLinter.run run_checked call verification."""

    @patch("scripts.dev.linter.linters.ruff.run_checked")
    @patch("scripts.dev.linter.linters.ruff.get_executable")
    def test_run_checked_call_order(
        self,
        mock_get_exe: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test that format is called before check (lines 39-40)."""
        mock_get_exe.return_value = "/usr/bin/uv"

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

    @patch("scripts.dev.linter.linters.ruff.run_checked")
    @patch("scripts.dev.linter.linters.ruff.get_executable")
    def test_run_checked_includes_fix_flag(
        self,
        mock_get_exe: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test that check command includes --fix flag (line 40)."""
        mock_get_exe.return_value = "/usr/bin/uv"

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
