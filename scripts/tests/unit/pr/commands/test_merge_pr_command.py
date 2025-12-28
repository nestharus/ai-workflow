"""Tests for merge_pr_command module."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.pr.commands.merge_pr_command import merge_pr_command


class TestMergePrCommand:
    """Tests for the merge_pr_command function."""

    def test_success_returns_zero_and_prints_message(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test successful merge prints message and returns 0."""
        with patch("scripts.pr.commands.merge_pr_command.github_dao") as mock_gh:
            mock_gh.merge_pr.return_value = True
            result = merge_pr_command(42)

        mock_gh.merge_pr.assert_called_once_with(42, squash=True, auto=True)
        captured = capsys.readouterr()
        assert "Merged PR #42" in captured.out
        assert result == 0

    def test_failure_returns_one_and_prints_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test failed merge prints error and returns 1."""
        with patch("scripts.pr.commands.merge_pr_command.github_dao") as mock_gh:
            mock_gh.merge_pr.return_value = False
            result = merge_pr_command(99)

        captured = capsys.readouterr()
        assert "Error merging PR #99" in captured.err
        assert result == 1

    def test_uses_squash_merge(self) -> None:
        """Test that squash merge is used."""
        with patch("scripts.pr.commands.merge_pr_command.github_dao") as mock_gh:
            mock_gh.merge_pr.return_value = True
            merge_pr_command(1)

        mock_gh.merge_pr.assert_called_once_with(1, squash=True, auto=True)

    def test_uses_auto_merge(self) -> None:
        """Test that auto merge is enabled."""
        with patch("scripts.pr.commands.merge_pr_command.github_dao") as mock_gh:
            mock_gh.merge_pr.return_value = True
            merge_pr_command(5)

        call_args = mock_gh.merge_pr.call_args
        assert call_args.kwargs.get("auto") is True

    def test_passes_correct_pr_number(self) -> None:
        """Test that correct PR number is passed to DAO."""
        with patch("scripts.pr.commands.merge_pr_command.github_dao") as mock_gh:
            mock_gh.merge_pr.return_value = True
            merge_pr_command(123)

        mock_gh.merge_pr.assert_called_once_with(123, squash=True, auto=True)
