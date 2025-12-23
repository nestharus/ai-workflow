"""Tests for post_reply_command function."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scripts.pr.commands.post_reply_command import post_reply_command


class TestPostReplyCommand:
    """Tests for post_reply_command function."""

    def test_returns_error_when_file_not_found(self, tmp_path: Path, capsys) -> None:
        """Should return 1 when thread file does not exist."""
        thread_file = tmp_path / "nonexistent.json"
        result = post_reply_command(123, thread_file, "test reply")

        assert result == 1
        captured = capsys.readouterr()
        assert "Thread file not found" in captured.err

    def test_returns_error_when_no_comments(self, tmp_path: Path, capsys) -> None:
        """Should return 1 when thread file has no comments."""
        thread_file = tmp_path / "thread.json"
        thread_file.write_text(json.dumps({"path": "file.py", "comments": []}))

        result = post_reply_command(123, thread_file, "test reply")

        assert result == 1
        captured = capsys.readouterr()
        assert "No comments in thread file" in captured.err

    def test_returns_error_when_no_database_id(self, tmp_path: Path, capsys) -> None:
        """Should return 1 when last comment has no database_id."""
        thread_file = tmp_path / "thread.json"
        thread_file.write_text(
            json.dumps(
                {
                    "comments": [{"id": "comment-1", "body": "test"}],
                }
            )
        )

        result = post_reply_command(123, thread_file, "test reply")

        assert result == 1
        captured = capsys.readouterr()
        assert "No database_id in comment" in captured.err

    def test_posts_reply_successfully(self, tmp_path: Path, capsys) -> None:
        """Should return 0 when reply is posted successfully."""
        thread_file = tmp_path / "thread.json"
        thread_file.write_text(
            json.dumps(
                {
                    "comments": [
                        {"id": "comment-1", "database_id": 456, "body": "original"},
                    ],
                }
            )
        )

        with patch("scripts.pr.commands.post_reply_command.github_dao") as mock_github:
            result = post_reply_command(123, thread_file, "my reply")

        assert result == 0
        mock_github.post_reply_to_comment.assert_called_once_with(123, 456, "my reply")
        captured = capsys.readouterr()
        assert "Posted reply to comment 456" in captured.out

    def test_uses_last_comment_for_reply(self, tmp_path: Path) -> None:
        """Should reply to the last comment in the thread."""
        thread_file = tmp_path / "thread.json"
        thread_file.write_text(
            json.dumps(
                {
                    "comments": [
                        {"id": "comment-1", "database_id": 100, "body": "first"},
                        {"id": "comment-2", "database_id": 200, "body": "second"},
                        {"id": "comment-3", "database_id": 300, "body": "third"},
                    ],
                }
            )
        )

        with patch("scripts.pr.commands.post_reply_command.github_dao") as mock_github:
            result = post_reply_command(42, thread_file, "reply text")

        assert result == 0
        # Should use the last comment's database_id (300)
        mock_github.post_reply_to_comment.assert_called_once_with(42, 300, "reply text")
