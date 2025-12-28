import json
from pathlib import Path

from scripts.pr.commands.post_deferred_replies_command import (
    post_deferred_replies_command,
)


class TestPostDeferredRepliesCommand:
    def test_returns_error_when_dir_not_found(self, tmp_path: Path, capsys) -> None:
        """Should return 1 when threads directory does not exist."""
        threads_dir = tmp_path / "nonexistent"
        result = post_deferred_replies_command(123, threads_dir)

        assert result == 1
        captured = capsys.readouterr()
        assert "Threads directory not found" in captured.err

    def test_returns_success_with_empty_dir(self, tmp_path: Path, capsys) -> None:
        """Should return 0 when threads dir is empty."""
        threads_dir = tmp_path / "threads"
        threads_dir.mkdir()

        result = post_deferred_replies_command(123, threads_dir)

        assert result == 0
        captured = capsys.readouterr()
        assert "Posted 0 deferred reply(ies)" in captured.out

    def test_skips_threads_without_deferred_reply(self, tmp_path: Path, capsys) -> None:
        """Should skip threads that don't have deferred_reply."""
        threads_dir = tmp_path / "threads"
        threads_dir.mkdir()

        # Thread without deferred_reply
        (threads_dir / "thread_001.json").write_text(json.dumps({"path": "file.py", "line": 10}))

        result = post_deferred_replies_command(123, threads_dir)

        assert result == 0
        captured = capsys.readouterr()
        assert "Posted 0 deferred reply(ies)" in captured.out

    def test_warns_when_no_comments(self, tmp_path: Path, capsys) -> None:
        """Should warn when thread has deferred_reply but no comments."""
        threads_dir = tmp_path / "threads"
        threads_dir.mkdir()

        (threads_dir / "thread_001.json").write_text(
            json.dumps(
                {
                    "path": "file.py",
                    "line": 10,
                    "deferred_reply": "My reply",
                    "comments": [],
                }
            )
        )

        result = post_deferred_replies_command(123, threads_dir)

        assert result == 0
        captured = capsys.readouterr()
        assert "Warning: No comments in thread file" in captured.err
        assert "Posted 0 deferred reply(ies)" in captured.out

    def test_warns_when_no_database_id(self, tmp_path: Path, capsys) -> None:
        """Should warn when last comment has no database_id."""
        threads_dir = tmp_path / "threads"
        threads_dir.mkdir()

        (threads_dir / "thread_001.json").write_text(
            json.dumps(
                {
                    "path": "file.py",
                    "line": 10,
                    "deferred_reply": "My reply",
                    "comments": [{"id": "comment-1", "body": "test"}],
                }
            )
        )

        result = post_deferred_replies_command(123, threads_dir)

        assert result == 0
        captured = capsys.readouterr()
        assert "Warning: No database_id in comment" in captured.err
        assert "Posted 0 deferred reply(ies)" in captured.out
