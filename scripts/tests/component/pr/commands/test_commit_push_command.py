from pathlib import Path

import pytest

from scripts.pr.commands.commit_push_command import commit_push_command


class TestCommitPushCommand:
    def test_worktree_not_found(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test when worktree directory doesn't exist."""
        non_existent = tmp_path / "nonexistent"

        result = commit_push_command(non_existent, "Test commit")

        assert result == 1
        captured = capsys.readouterr()
        assert "Worktree not found" in captured.err
