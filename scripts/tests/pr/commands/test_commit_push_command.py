"""Tests for scripts/pr/commands/commit_push_command.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.pr.commands.commit_push_command import commit_push_command


class TestCommitPushCommand:
    """Tests for commit_push_command() function."""

    def test_worktree_not_found(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test when worktree directory doesn't exist."""
        non_existent = tmp_path / "nonexistent"

        result = commit_push_command(non_existent, "Test commit")

        assert result == 1
        captured = capsys.readouterr()
        assert "Worktree not found" in captured.err

    def test_get_status_error(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test when git status returns an error."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        with patch("scripts.pr.git_dao.get_status", return_value=("", "Git error")):
            result = commit_push_command(worktree, "Test commit")

        assert result == 1
        captured = capsys.readouterr()
        assert "Git error" in captured.err

    def test_no_changes_to_commit(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test when there are no changes to commit."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        with patch("scripts.pr.git_dao.get_status", return_value=("", None)):
            result = commit_push_command(worktree, "Test commit")

        assert result == 0
        captured = capsys.readouterr()
        assert "No changes to commit" in captured.out

    def test_stage_all_fails(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test when staging changes fails."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        with (
            patch("scripts.pr.git_dao.get_status", return_value=("M file.txt", None)),
            patch("scripts.pr.git_dao.stage_all", return_value=False),
        ):
            result = commit_push_command(worktree, "Test commit")

        assert result == 1
        captured = capsys.readouterr()
        assert "Error staging" in captured.err

    def test_commit_fails(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test when commit fails."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        with (
            patch("scripts.pr.git_dao.get_status", return_value=("M file.txt", None)),
            patch("scripts.pr.git_dao.stage_all", return_value=True),
            patch("scripts.pr.git_dao.commit", return_value=False),
        ):
            result = commit_push_command(worktree, "Test commit")

        assert result == 1
        captured = capsys.readouterr()
        assert "Error committing" in captured.err

    def test_push_fails(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test when push fails."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        with (
            patch("scripts.pr.git_dao.get_status", return_value=("M file.txt", None)),
            patch("scripts.pr.git_dao.stage_all", return_value=True),
            patch("scripts.pr.git_dao.commit", return_value=True),
            patch("scripts.pr.git_dao.push", return_value=(False, "Push rejected")),
        ):
            result = commit_push_command(worktree, "Test commit")

        assert result == 1
        captured = capsys.readouterr()
        assert "Error pushing" in captured.err

    def test_successful_commit_push(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test successful commit and push."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        with (
            patch("scripts.pr.git_dao.get_status", return_value=("M file.txt", None)),
            patch("scripts.pr.git_dao.stage_all", return_value=True),
            patch("scripts.pr.git_dao.commit", return_value=True),
            patch("scripts.pr.git_dao.push", return_value=(True, "")),
        ):
            result = commit_push_command(worktree, "Test commit message")

        assert result == 0
        captured = capsys.readouterr()
        assert "Successfully committed and pushed" in captured.out
        assert "Test commit message" in captured.out

    def test_successful_commit_push_with_set_upstream(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test successful commit and push with set_upstream=True."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        with (
            patch("scripts.pr.git_dao.get_status", return_value=("M file.txt", None)),
            patch("scripts.pr.git_dao.stage_all", return_value=True),
            patch("scripts.pr.git_dao.commit", return_value=True),
            patch("scripts.pr.git_dao.push", return_value=(True, "")) as mock_push,
        ):
            result = commit_push_command(worktree, "Test commit", set_upstream=True)
            mock_push.assert_called_once_with(worktree, set_upstream=True)

        assert result == 0
