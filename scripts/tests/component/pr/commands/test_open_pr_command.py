from pathlib import Path

import pytest

from scripts.pr.commands.open_pr_command import open_pr_command


class TestOpenPrCommand:
    def test_worktree_not_found_returns_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test error when worktree directory doesn't exist."""
        nonexistent = tmp_path / "nonexistent"

        result = open_pr_command(nonexistent, "Title", "Body", "branch")

        captured = capsys.readouterr()
        assert "Error: Worktree not found" in captured.err
        assert str(nonexistent) in captured.err
        assert result == 1

    def test_file_as_worktree_returns_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test error when worktree path is a file, not directory."""
        file_path = tmp_path / "not_a_directory"
        file_path.write_text("content")

        result = open_pr_command(file_path, "Title", "Body", "branch")

        captured = capsys.readouterr()
        assert "Error: Worktree not found" in captured.err
        assert result == 1
