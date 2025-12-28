import json
from pathlib import Path
from unittest.mock import patch

from scripts.pr.commands.post_deferred_replies_command import (
    post_deferred_replies_command,
)


class TestPostDeferredRepliesCommand:
    def test_posts_deferred_reply_successfully(self, tmp_path: Path, capsys) -> None:
        """Should post deferred reply and return 0."""
        threads_dir = tmp_path / "threads"
        threads_dir.mkdir()

        (threads_dir / "thread_001.json").write_text(
            json.dumps(
                {
                    "path": "src/file.py",
                    "line": 42,
                    "deferred_reply": "This is fixed now",
                    "comments": [{"id": "comment-1", "database_id": 999, "body": "original"}],
                }
            )
        )

        with patch("scripts.pr.commands.post_deferred_replies_command.github_dao") as mock_github:
            result = post_deferred_replies_command(123, threads_dir)

        assert result == 0
        mock_github.post_reply_to_comment.assert_called_once_with(123, 999, "This is fixed now")
        captured = capsys.readouterr()
        assert "Posted deferred reply to src/file.py:42" in captured.out
        assert "Posted 1 deferred reply(ies)" in captured.out

    def test_posts_multiple_deferred_replies(self, tmp_path: Path, capsys) -> None:
        """Should post all deferred replies from multiple thread files."""
        threads_dir = tmp_path / "threads"
        threads_dir.mkdir()

        (threads_dir / "thread_001.json").write_text(
            json.dumps(
                {
                    "path": "file1.py",
                    "line": 10,
                    "deferred_reply": "Reply 1",
                    "comments": [{"database_id": 100}],
                }
            )
        )
        (threads_dir / "thread_002.json").write_text(
            json.dumps(
                {
                    "path": "file2.py",
                    "line": 20,
                    "deferred_reply": "Reply 2",
                    "comments": [{"database_id": 200}],
                }
            )
        )
        (threads_dir / "thread_003.json").write_text(
            json.dumps(
                {
                    "path": "file3.py",
                    "line": 30,
                    # No deferred_reply - should be skipped
                    "comments": [{"database_id": 300}],
                }
            )
        )

        with patch("scripts.pr.commands.post_deferred_replies_command.github_dao") as mock_github:
            result = post_deferred_replies_command(123, threads_dir)

        assert result == 0
        assert mock_github.post_reply_to_comment.call_count == 2
        captured = capsys.readouterr()
        assert "Posted 2 deferred reply(ies)" in captured.out

    def test_uses_last_comment_database_id(self, tmp_path: Path) -> None:
        """Should use the last comment's database_id for reply."""
        threads_dir = tmp_path / "threads"
        threads_dir.mkdir()

        (threads_dir / "thread_001.json").write_text(
            json.dumps(
                {
                    "path": "file.py",
                    "line": 10,
                    "deferred_reply": "My reply",
                    "comments": [
                        {"database_id": 100},
                        {"database_id": 200},
                        {"database_id": 300},  # Last one
                    ],
                }
            )
        )

        with patch("scripts.pr.commands.post_deferred_replies_command.github_dao") as mock_github:
            post_deferred_replies_command(123, threads_dir)

        mock_github.post_reply_to_comment.assert_called_once_with(123, 300, "My reply")
