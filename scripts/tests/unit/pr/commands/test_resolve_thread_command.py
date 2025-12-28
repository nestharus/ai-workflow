import json
from pathlib import Path
from unittest.mock import patch

from scripts.pr.commands.resolve_thread_command import resolve_thread_command


class TestResolveThreadCommand:
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
