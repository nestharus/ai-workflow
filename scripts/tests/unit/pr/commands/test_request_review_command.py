"""Tests for request_review_command function."""

from __future__ import annotations

from unittest.mock import patch

from scripts.pr.commands.request_review_command import request_review_command


class TestRequestReviewCommand:
    """Tests for request_review_command function."""

    def test_posts_coderabbit_comment(self) -> None:
        """Should post @coderabbitai review comment."""
        with patch("scripts.pr.commands.request_review_command.github_dao") as mock_github:
            result = request_review_command(123)

        mock_github.post_pr_comment.assert_called_once_with(123, "@coderabbitai review")
        assert result == 0

    def test_returns_zero_on_success(self) -> None:
        """Should return 0 on success."""
        with patch("scripts.pr.commands.request_review_command.github_dao"):
            result = request_review_command(42)

        assert result == 0

    def test_prints_confirmation_message(self, capsys) -> None:
        """Should print confirmation message."""
        with patch("scripts.pr.commands.request_review_command.github_dao"):
            request_review_command(99)

        captured = capsys.readouterr()
        assert "Requested CodeRabbit review on PR #99" in captured.out
