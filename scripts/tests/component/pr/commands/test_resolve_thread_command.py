import json
from pathlib import Path

from scripts.pr.commands.resolve_thread_command import resolve_thread_command


class TestResolveThreadCommand:
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
