"""Tests for resolve_thread_command function."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scripts.pr.commands.resolve_thread_command import resolve_thread_command


class TestResolveThreadCommand:
    """Tests for resolve_thread_command function."""

    def test_returns_error_when_file_not_found(self, tmp_path: Path, capsys) -> None:
        """Should return 1 when thread file does not exist."""
        thread_file = tmp_path / "nonexistent.json"
        result = resolve_thread_command(thread_file)

        assert result == 1
        captured = capsys.readouterr()
        assert "Thread file not found" in captured.err

    def test_returns_error_when_no_thread_id(self, tmp_path: Path, capsys) -> None:
        """Should return 1 when thread file has no thread_id."""
        thread_file = tmp_path / "thread.json"
        thread_file.write_text(json.dumps({"path": "file.py", "line": 10}))

        result = resolve_thread_command(thread_file)

        assert result == 1
        captured = capsys.readouterr()
        assert "No thread_id in file" in captured.err

    def test_returns_success_when_thread_resolved(self, tmp_path: Path, capsys) -> None:
        """Should return 0 when thread is successfully resolved."""
        thread_file = tmp_path / "thread.json"
        thread_file.write_text(json.dumps({"thread_id": "thread-123"}))

        with patch("scripts.pr.commands.resolve_thread_command.github_dao") as mock_github:
            mock_github.resolve_thread.return_value = True
            result = resolve_thread_command(thread_file)

        assert result == 0
        mock_github.resolve_thread.assert_called_once_with("thread-123")
        captured = capsys.readouterr()
        assert "Resolved thread: thread-123" in captured.out

    def test_returns_error_when_resolve_fails(self, tmp_path: Path, capsys) -> None:
        """Should return 1 when resolve_thread returns False."""
        thread_file = tmp_path / "thread.json"
        thread_file.write_text(json.dumps({"thread_id": "thread-456"}))

        with patch("scripts.pr.commands.resolve_thread_command.github_dao") as mock_github:
            mock_github.resolve_thread.return_value = False
            result = resolve_thread_command(thread_file)

        assert result == 1
        captured = capsys.readouterr()
        assert "Failed to resolve thread: thread-456" in captured.err
