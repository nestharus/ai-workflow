"""Tests for scripts.dev.zip_changes module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.zip_changes import (
    GitCommandError,
    get_commit_files,
    get_uncommitted_files,
    run_git_command,
)


class TestGitCommandError:
    """Tests for GitCommandError exception."""

    def test_stores_command(self) -> None:
        """Should store the command that failed."""
        cmd = ["git", "status"]
        error = GitCommandError(cmd, 1, "error message")

        assert error.cmd == cmd

    def test_stores_returncode(self) -> None:
        """Should store the return code."""
        error = GitCommandError(["git"], 42, "error message")

        assert error.returncode == 42

    def test_stores_stderr(self) -> None:
        """Should store the stderr output."""
        error = GitCommandError(["git"], 1, "error message")

        assert error.stderr == "error message"

    def test_formats_message(self) -> None:
        """Should format a descriptive error message."""
        error = GitCommandError(["git", "status"], 1, "fatal: not a repo")

        assert "git status" in str(error)
        assert "exit 1" in str(error)
        assert "fatal: not a repo" in str(error)


class TestRunGitCommand:
    """Tests for run_git_command function."""

    def test_returns_stdout_on_success(self) -> None:
        """Should return stdout when command succeeds."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "output text"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = run_git_command(["git", "status"])

        assert result == "output text"

    def test_raises_on_nonzero_exit(self) -> None:
        """Should raise GitCommandError on non-zero exit code."""
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        mock_result.stderr = "fatal: not a git repository"

        with (
            patch("subprocess.run", return_value=mock_result),
            pytest.raises(GitCommandError) as exc_info,
        ):
            run_git_command(["git", "status"])

        assert exc_info.value.returncode == 128
        assert "not a git repository" in exc_info.value.stderr

    def test_raises_on_os_error(self) -> None:
        """Should raise GitCommandError on OSError (e.g., command not found)."""
        with (
            patch("subprocess.run", side_effect=OSError("git not found")),
            pytest.raises(GitCommandError) as exc_info,
        ):
            run_git_command(["git", "status"])

        assert exc_info.value.returncode == -1
        assert "git not found" in exc_info.value.stderr

    def test_preserves_command_in_error(self) -> None:
        """Should preserve the command in the error for debugging."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error"

        with (
            patch("subprocess.run", return_value=mock_result),
            pytest.raises(GitCommandError) as exc_info,
        ):
            run_git_command(["git", "diff-tree", "--no-commit-id", "abc123"])

        assert exc_info.value.cmd == ["git", "diff-tree", "--no-commit-id", "abc123"]


class TestGetUncommittedFiles:
    """Tests for get_uncommitted_files function."""

    def test_raises_git_command_error_on_failure(self) -> None:
        """Should raise GitCommandError when git status fails."""
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        mock_result.stderr = "fatal: not a git repository"

        with (
            patch("subprocess.run", return_value=mock_result),
            pytest.raises(GitCommandError) as exc_info,
        ):
            get_uncommitted_files()

        assert "git status" in str(exc_info.value)

    def test_returns_empty_on_no_changes(self) -> None:
        """Should return empty list when no uncommitted changes."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = get_uncommitted_files()

        assert result == []


class TestGetCommitFiles:
    """Tests for get_commit_files function."""

    def test_raises_git_command_error_on_invalid_sha(self) -> None:
        """Should raise GitCommandError when SHA is invalid."""
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        mock_result.stderr = "fatal: bad object invalid-sha"

        with (
            patch("subprocess.run", return_value=mock_result),
            pytest.raises(GitCommandError) as exc_info,
        ):
            get_commit_files("invalid-sha")

        assert "git diff-tree" in str(exc_info.value)
        assert "bad object" in exc_info.value.stderr

    def test_returns_empty_on_no_files(self) -> None:
        """Should return empty list when commit has no files."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = get_commit_files("abc123")

        assert result == []
