import json
from pathlib import Path

from scripts.pr.commands.post_reply_command import post_reply_command


class TestPostReplyCommand:
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
