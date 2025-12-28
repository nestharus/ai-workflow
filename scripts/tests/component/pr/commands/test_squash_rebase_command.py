from pathlib import Path

from scripts.pr.commands.squash_rebase_command import squash_rebase_command


class TestSquashRebaseCommand:
    def test_worktree_not_found_returns_error(self) -> None:
        """Should return 1 when worktree directory does not exist."""
        result = squash_rebase_command(Path("/nonexistent/path"), "main")
        assert result == 1
