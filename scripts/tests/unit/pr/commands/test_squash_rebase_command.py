import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts.pr.commands.squash_rebase_command import squash_rebase_command


class TestSquashRebaseCommand:
    def test_fetch_branch_failure_returns_error(self) -> None:
        """Should return 1 when fetch branch fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = Path(tmpdir)
            with patch("scripts.pr.commands.squash_rebase_command.git_dao") as mock_git:
                mock_git.fetch_branch.return_value = (False, "network error")

                result = squash_rebase_command(worktree, "main")

            assert result == 1

    def test_count_commits_failure_returns_error(self) -> None:
        """Should return 1 when counting commits fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = Path(tmpdir)
            with patch("scripts.pr.commands.squash_rebase_command.git_dao") as mock_git:
                mock_git.fetch_branch.return_value = (True, "")
                mock_git.count_commits_ahead.return_value = (-1, "git error")

                result = squash_rebase_command(worktree, "main")

            assert result == 1

    def test_single_commit_skips_squash(self) -> None:
        """Should skip squash when there is only one commit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = Path(tmpdir)
            with patch("scripts.pr.commands.squash_rebase_command.git_dao") as mock_git:
                mock_git.fetch_branch.return_value = (True, "")
                mock_git.count_commits_ahead.return_value = (1, "")
                mock_git.rebase.return_value = (True, False, "")

                result = squash_rebase_command(worktree, "main")

            assert result == 0
            mock_git.get_merge_base.assert_not_called()
            mock_git.soft_reset.assert_not_called()

    def test_zero_commits_skips_squash(self) -> None:
        """Should skip squash when there are no commits ahead."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = Path(tmpdir)
            with patch("scripts.pr.commands.squash_rebase_command.git_dao") as mock_git:
                mock_git.fetch_branch.return_value = (True, "")
                mock_git.count_commits_ahead.return_value = (0, "")
                mock_git.rebase.return_value = (True, False, "")

                result = squash_rebase_command(worktree, "main")

            assert result == 0
            mock_git.get_merge_base.assert_not_called()

    def test_multiple_commits_performs_squash(self) -> None:
        """Should squash commits when there are multiple commits."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = Path(tmpdir)
            with patch("scripts.pr.commands.squash_rebase_command.git_dao") as mock_git:
                mock_git.fetch_branch.return_value = (True, "")
                mock_git.count_commits_ahead.return_value = (3, "")
                mock_git.get_merge_base.return_value = ("abc123", "")
                mock_git.get_last_commit_message.return_value = "Original message"
                mock_git.soft_reset.return_value = (True, "")
                mock_git.commit.return_value = True
                mock_git.rebase.return_value = (True, False, "")

                result = squash_rebase_command(worktree, "main")

            assert result == 0
            mock_git.get_merge_base.assert_called_once()
            mock_git.soft_reset.assert_called_once()
            mock_git.commit.assert_called_once_with(worktree, "Original message")

    def test_merge_base_failure_returns_error(self) -> None:
        """Should return 1 when getting merge base fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = Path(tmpdir)
            with patch("scripts.pr.commands.squash_rebase_command.git_dao") as mock_git:
                mock_git.fetch_branch.return_value = (True, "")
                mock_git.count_commits_ahead.return_value = (3, "")
                mock_git.get_merge_base.return_value = ("", "git error")

                result = squash_rebase_command(worktree, "main")

            assert result == 1

    def test_soft_reset_failure_returns_error(self) -> None:
        """Should return 1 when soft reset fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = Path(tmpdir)
            with patch("scripts.pr.commands.squash_rebase_command.git_dao") as mock_git:
                mock_git.fetch_branch.return_value = (True, "")
                mock_git.count_commits_ahead.return_value = (3, "")
                mock_git.get_merge_base.return_value = ("abc123", "")
                mock_git.get_last_commit_message.return_value = "Original message"
                mock_git.soft_reset.return_value = (False, "git error")

                result = squash_rebase_command(worktree, "main")

            assert result == 1

    def test_commit_failure_returns_error(self) -> None:
        """Should return 1 when commit fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = Path(tmpdir)
            with patch("scripts.pr.commands.squash_rebase_command.git_dao") as mock_git:
                mock_git.fetch_branch.return_value = (True, "")
                mock_git.count_commits_ahead.return_value = (3, "")
                mock_git.get_merge_base.return_value = ("abc123", "")
                mock_git.get_last_commit_message.return_value = "Original message"
                mock_git.soft_reset.return_value = (True, "")
                mock_git.commit.return_value = False

                result = squash_rebase_command(worktree, "main")

            assert result == 1

    def test_rebase_conflict_returns_error(self) -> None:
        """Should return 1 when rebase has conflicts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = Path(tmpdir)
            with patch("scripts.pr.commands.squash_rebase_command.git_dao") as mock_git:
                mock_git.fetch_branch.return_value = (True, "")
                mock_git.count_commits_ahead.return_value = (1, "")
                mock_git.rebase.return_value = (False, True, "CONFLICT in file.py")

                result = squash_rebase_command(worktree, "main")

            assert result == 1

    def test_rebase_failure_no_conflict_returns_error(self) -> None:
        """Should return 1 when rebase fails without conflicts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = Path(tmpdir)
            with patch("scripts.pr.commands.squash_rebase_command.git_dao") as mock_git:
                mock_git.fetch_branch.return_value = (True, "")
                mock_git.count_commits_ahead.return_value = (1, "")
                mock_git.rebase.return_value = (False, False, "rebase error")

                result = squash_rebase_command(worktree, "main")

            assert result == 1

    def test_success_returns_zero(self) -> None:
        """Should return 0 on successful squash and rebase."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = Path(tmpdir)
            with patch("scripts.pr.commands.squash_rebase_command.git_dao") as mock_git:
                mock_git.fetch_branch.return_value = (True, "")
                mock_git.count_commits_ahead.return_value = (3, "")
                mock_git.get_merge_base.return_value = ("abc123", "")
                mock_git.get_last_commit_message.return_value = "Feature commit"
                mock_git.soft_reset.return_value = (True, "")
                mock_git.commit.return_value = True
                mock_git.rebase.return_value = (True, False, "")

                result = squash_rebase_command(worktree, "main")

            assert result == 0
