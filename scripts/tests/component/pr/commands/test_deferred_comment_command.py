"""Tests for scripts/pr/commands/deferred_comment_command.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.pr.commands.deferred_comment_command import deferred_comment_command


class TestDeferredCommentCommand:
    """Tests for deferred_comment_command() function."""

    def test_thread_file_not_found(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test when thread file doesn't exist."""
        non_existent = tmp_path / "nonexistent.json"

        result = deferred_comment_command(non_existent, "Reply body")

        assert result == 1
        captured = capsys.readouterr()
        assert "Thread file not found" in captured.err

    def test_thread_file_is_directory(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test when thread file path is a directory."""
        dir_path = tmp_path / "directory"
        dir_path.mkdir()

        result = deferred_comment_command(dir_path, "Reply body")

        assert result == 1
        captured = capsys.readouterr()
        assert "Thread file not found" in captured.err

    def test_successful_deferred_reply(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test successfully storing a deferred reply."""
        thread_file = tmp_path / "thread.json"
        original_data = {
            "thread_id": "thread-123",
            "comments": [{"id": "comment-1", "body": "Original comment"}],
        }
        thread_file.write_text(json.dumps(original_data), encoding="utf-8")

        result = deferred_comment_command(thread_file, "My deferred reply")

        assert result == 0
        captured = capsys.readouterr()
        assert "Stored deferred reply" in captured.out

        # Verify the file was updated
        updated_data = json.loads(thread_file.read_text(encoding="utf-8"))
        assert updated_data["deferred_reply"] == "My deferred reply"
        assert updated_data["thread_id"] == "thread-123"

    def test_updates_existing_deferred_reply(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test updating an existing deferred reply."""
        thread_file = tmp_path / "thread.json"
        original_data = {"thread_id": "thread-456", "deferred_reply": "Old reply"}
        thread_file.write_text(json.dumps(original_data), encoding="utf-8")

        result = deferred_comment_command(thread_file, "Updated reply")

        assert result == 0

        updated_data = json.loads(thread_file.read_text(encoding="utf-8"))
        assert updated_data["deferred_reply"] == "Updated reply"

    def test_preserves_existing_data(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test that existing data in thread file is preserved."""
        thread_file = tmp_path / "thread.json"
        original_data = {
            "thread_id": "thread-789",
            "path": "src/file.py",
            "line": 42,
            "comments": [{"id": "c1", "body": "Comment 1"}],
            "custom_field": "preserved",
        }
        thread_file.write_text(json.dumps(original_data), encoding="utf-8")

        result = deferred_comment_command(thread_file, "New reply")

        assert result == 0

        updated_data = json.loads(thread_file.read_text(encoding="utf-8"))
        assert updated_data["thread_id"] == "thread-789"
        assert updated_data["path"] == "src/file.py"
        assert updated_data["line"] == 42
        assert updated_data["comments"] == [{"id": "c1", "body": "Comment 1"}]
        assert updated_data["custom_field"] == "preserved"
        assert updated_data["deferred_reply"] == "New reply"

    def test_multiline_reply_body(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test storing a multiline reply body."""
        thread_file = tmp_path / "thread.json"
        thread_file.write_text('{"thread_id": "test"}', encoding="utf-8")

        multiline_body = """This is line 1.
This is line 2.

This is line 4 after a blank line.
```python
def example():
    pass
```"""

        result = deferred_comment_command(thread_file, multiline_body)

        assert result == 0

        updated_data = json.loads(thread_file.read_text(encoding="utf-8"))
        assert updated_data["deferred_reply"] == multiline_body

    def test_special_characters_in_reply(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test storing reply with special characters."""
        thread_file = tmp_path / "thread.json"
        thread_file.write_text('{"thread_id": "test"}', encoding="utf-8")

        special_body = 'Reply with "quotes", \\backslashes\\, and unicode: {}'

        result = deferred_comment_command(thread_file, special_body)

        assert result == 0

        updated_data = json.loads(thread_file.read_text(encoding="utf-8"))
        assert updated_data["deferred_reply"] == special_body
