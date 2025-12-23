"""Tests for open_pr_command module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.pr.commands.open_pr_command import open_pr_command


class TestOpenPrCommand:
    """Tests for the open_pr_command function."""

    def test_success_returns_zero_and_prints_result(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test successful PR creation prints result and returns 0."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        with patch("scripts.pr.commands.open_pr_command.github_dao") as mock_gh:
            mock_gh.create_pr.return_value = (
                True,
                "https://github.com/owner/repo/pull/42",
            )
            result = open_pr_command(worktree, "PR Title", "PR body text", "feature-branch")

        mock_gh.create_pr.assert_called_once_with(
            str(worktree), "PR Title", "PR body text", "feature-branch"
        )
        captured = capsys.readouterr()
        assert "https://github.com/owner/repo/pull/42" in captured.out
        assert result == 0

    def test_worktree_not_found_returns_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test error when worktree directory doesn't exist."""
        nonexistent = tmp_path / "nonexistent"

        result = open_pr_command(nonexistent, "Title", "Body", "branch")

        captured = capsys.readouterr()
        assert "Error: Worktree not found" in captured.err
        assert str(nonexistent) in captured.err
        assert result == 1

    def test_create_pr_failure_returns_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test error when create_pr fails."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        with patch("scripts.pr.commands.open_pr_command.github_dao") as mock_gh:
            mock_gh.create_pr.return_value = (False, "Branch does not exist on remote")
            result = open_pr_command(worktree, "Title", "Body", "bad-branch")

        captured = capsys.readouterr()
        assert "Error creating PR: Branch does not exist on remote" in captured.err
        assert result == 1

    def test_passes_correct_arguments_to_create_pr(self, tmp_path: Path) -> None:
        """Test that arguments are passed correctly to create_pr."""
        worktree = tmp_path / "my_worktree"
        worktree.mkdir()

        with patch("scripts.pr.commands.open_pr_command.github_dao") as mock_gh:
            mock_gh.create_pr.return_value = (True, "url")
            open_pr_command(
                worktree,
                "My PR Title",
                "My PR body with description",
                "my-feature-branch",
            )

        mock_gh.create_pr.assert_called_once_with(
            str(worktree),
            "My PR Title",
            "My PR body with description",
            "my-feature-branch",
        )

    def test_handles_empty_title(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test handling of empty title."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        with patch("scripts.pr.commands.open_pr_command.github_dao") as mock_gh:
            mock_gh.create_pr.return_value = (True, "url")
            result = open_pr_command(worktree, "", "Body", "branch")

        # Should still call create_pr with empty title
        mock_gh.create_pr.assert_called_once()
        assert mock_gh.create_pr.call_args[0][1] == ""
        assert result == 0

    def test_handles_empty_body(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test handling of empty body."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        with patch("scripts.pr.commands.open_pr_command.github_dao") as mock_gh:
            mock_gh.create_pr.return_value = (True, "url")
            result = open_pr_command(worktree, "Title", "", "branch")

        mock_gh.create_pr.assert_called_once()
        assert mock_gh.create_pr.call_args[0][2] == ""
        assert result == 0

    def test_handles_multiline_body(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test handling of multiline body text."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        multiline_body = "Line 1\nLine 2\n\n## Header\n- Item 1\n- Item 2"

        with patch("scripts.pr.commands.open_pr_command.github_dao") as mock_gh:
            mock_gh.create_pr.return_value = (True, "url")
            result = open_pr_command(worktree, "Title", multiline_body, "branch")

        mock_gh.create_pr.assert_called_once()
        assert mock_gh.create_pr.call_args[0][2] == multiline_body
        assert result == 0

    def test_handles_special_characters_in_title(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test handling of special characters in title."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        special_title = "feat: Add support for 'quotes' & <brackets>"

        with patch("scripts.pr.commands.open_pr_command.github_dao") as mock_gh:
            mock_gh.create_pr.return_value = (True, "url")
            result = open_pr_command(worktree, special_title, "Body", "branch")

        mock_gh.create_pr.assert_called_once()
        assert mock_gh.create_pr.call_args[0][1] == special_title
        assert result == 0

    def test_file_as_worktree_returns_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test error when worktree path is a file, not directory."""
        file_path = tmp_path / "not_a_directory"
        file_path.write_text("content")

        result = open_pr_command(file_path, "Title", "Body", "branch")

        captured = capsys.readouterr()
        assert "Error: Worktree not found" in captured.err
        assert result == 1
