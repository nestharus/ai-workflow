"""Tests for rebase_finish_command function."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.pr.commands.rebase_finish_command import rebase_finish_command


class TestRebaseFinishCommand:
    """Tests for rebase_finish_command function."""

    def test_returns_error_when_not_in_repo(self, capsys) -> None:
        """Should return 1 when not in a git repository."""
        with patch("scripts.pr.commands.rebase_finish_command.git_dao") as mock_git:
            mock_git.get_repo_root.return_value = None

            result = rebase_finish_command()

        assert result == 1
        captured = capsys.readouterr()
        assert "Not in a git repository" in captured.err

    def test_returns_error_when_not_on_branch(self, tmp_path: Path, capsys) -> None:
        """Should return 1 when not on any branch (no identifier)."""
        with patch("scripts.pr.commands.rebase_finish_command.git_dao") as mock_git:
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = None

            result = rebase_finish_command(identifier=None)

        assert result == 1
        captured = capsys.readouterr()
        assert "Not on a branch" in captured.err

    def test_returns_error_when_no_sandbox(self, tmp_path: Path, capsys) -> None:
        """Should return 1 when sandbox does not exist."""
        with patch("scripts.pr.commands.rebase_finish_command.git_dao") as mock_git:
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "feature"

            result = rebase_finish_command()

        assert result == 1
        captured = capsys.readouterr()
        assert "No sandbox found" in captured.err

    def test_uses_pr_info_for_pr_identifier(self, tmp_path: Path, capsys) -> None:
        """Should fetch PR info when identifier is a PR number."""
        sandbox_path = tmp_path / ".git" / "rebase-sandbox" / "pr-branch"
        sandbox_path.mkdir(parents=True)

        with (
            patch("scripts.pr.commands.rebase_finish_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_finish_command.github_dao") as mock_github,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "main"
            mock_git.force_push.return_value = (True, "")
            mock_git.reset_hard_to_remote.return_value = (True, "")
            mock_git.remove_shared_clone.return_value = (True, "")
            mock_github.get_pr_info.return_value = {"head_branch": "pr-branch"}

            result = rebase_finish_command(identifier="42")

        assert result == 0
        mock_github.get_pr_info.assert_called_once_with(42)

    def test_returns_error_when_pr_has_no_branch(self, tmp_path: Path, capsys) -> None:
        """Should return 1 when PR has no head branch."""
        with (
            patch("scripts.pr.commands.rebase_finish_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_finish_command.github_dao") as mock_github,
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "main"
            mock_github.get_pr_info.return_value = {"head_branch": None}

            result = rebase_finish_command(identifier="#55")

        assert result == 1
        captured = capsys.readouterr()
        assert "Could not determine branch for PR" in captured.err

    def test_uses_ticket_info_for_ticket_identifier(self, tmp_path: Path, capsys) -> None:
        """Should fetch ticket info when identifier is a ticket ID."""
        sandbox_path = tmp_path / ".git" / "rebase-sandbox" / "nes-87-fix-bug"
        sandbox_path.mkdir(parents=True)

        with (
            patch("scripts.pr.commands.rebase_finish_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_finish_command._get_default_client") as mock_linear,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "main"
            mock_git.branch_exists.return_value = True
            mock_git.force_push.return_value = (True, "")
            mock_git.reset_hard_to_remote.return_value = (True, "")
            mock_git.remove_shared_clone.return_value = (True, "")

            mock_client = MagicMock()
            mock_client.get_ticket_info.return_value = {"branch_name": "nes-87-fix-bug"}
            mock_linear.return_value = mock_client

            result = rebase_finish_command(identifier="NES-87")

        assert result == 0
        mock_client.get_ticket_info.assert_called_once_with("NES-87")

    def test_returns_error_when_no_branch_for_ticket(self, tmp_path: Path, capsys) -> None:
        """Should return 1 when ticket has no branch name."""
        with (
            patch("scripts.pr.commands.rebase_finish_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_finish_command._get_default_client") as mock_linear,
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "main"

            mock_client = MagicMock()
            mock_client.get_ticket_info.return_value = {"branch_name": None}
            mock_linear.return_value = mock_client

            result = rebase_finish_command(identifier="NES-88")

        assert result == 1
        captured = capsys.readouterr()
        assert "No branch name for ticket" in captured.err

    def test_uses_branch_name_directly(self, tmp_path: Path, capsys) -> None:
        """Should use identifier as branch name when it's not PR/ticket."""
        sandbox_path = tmp_path / ".git" / "rebase-sandbox" / "my-feature"
        sandbox_path.mkdir(parents=True)

        with (
            patch("scripts.pr.commands.rebase_finish_command.git_dao") as mock_git,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "main"
            mock_git.force_push.return_value = (True, "")
            mock_git.reset_hard_to_remote.return_value = (True, "")
            mock_git.remove_shared_clone.return_value = (True, "")

            result = rebase_finish_command(identifier="my-feature")

        assert result == 0
        captured = capsys.readouterr()
        stdout_json = json.loads(captured.out)
        assert stdout_json["branch_name"] == "my-feature"

    def test_returns_error_when_push_fails(self, tmp_path: Path, capsys) -> None:
        """Should return 1 when force push fails."""
        sandbox_path = tmp_path / ".git" / "rebase-sandbox" / "feature"
        sandbox_path.mkdir(parents=True)

        with (
            patch("scripts.pr.commands.rebase_finish_command.git_dao") as mock_git,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "feature"
            mock_git.force_push.return_value = (False, "Push rejected")

            result = rebase_finish_command()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error pushing: Push rejected" in captured.err

    def test_warns_when_sync_fails(self, tmp_path: Path, capsys) -> None:
        """Should warn but continue when sync fails."""
        sandbox_path = tmp_path / ".git" / "rebase-sandbox" / "feature"
        sandbox_path.mkdir(parents=True)

        with (
            patch("scripts.pr.commands.rebase_finish_command.git_dao") as mock_git,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "feature"
            mock_git.force_push.return_value = (True, "")
            mock_git.reset_hard_to_remote.return_value = (False, "Sync error")
            mock_git.remove_shared_clone.return_value = (True, "")

            result = rebase_finish_command()

        # Should still succeed
        assert result == 0
        captured = capsys.readouterr()
        assert "Warning: Failed to sync source worktree: Sync error" in captured.err

    def test_warns_when_cleanup_fails(self, tmp_path: Path, capsys) -> None:
        """Should warn but continue when sandbox cleanup fails."""
        sandbox_path = tmp_path / ".git" / "rebase-sandbox" / "feature"
        sandbox_path.mkdir(parents=True)

        with (
            patch("scripts.pr.commands.rebase_finish_command.git_dao") as mock_git,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "feature"
            mock_git.force_push.return_value = (True, "")
            mock_git.reset_hard_to_remote.return_value = (True, "")
            mock_git.remove_shared_clone.return_value = (False, "Cleanup error")

            result = rebase_finish_command()

        # Should still succeed
        assert result == 0
        captured = capsys.readouterr()
        assert "Warning: Failed to remove sandbox: Cleanup error" in captured.err

    def test_handles_linear_client_error(self, tmp_path: Path, capsys) -> None:
        """Should return 1 on LinearClientError."""
        from scripts.clients.linear_client import LinearClientError

        with (
            patch("scripts.pr.commands.rebase_finish_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_finish_command._get_default_client") as mock_linear,
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "main"

            mock_linear.side_effect = LinearClientError("API_ERROR", "API error")

            result = rebase_finish_command(identifier="NES-99")

        assert result == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    def test_handles_graphql_error(self, tmp_path: Path, capsys) -> None:
        """Should return 1 on GraphQLError."""
        from scripts.pr import github_dao
        from scripts.pr.github_dao import GraphQLError

        with (
            patch("scripts.pr.commands.rebase_finish_command.git_dao") as mock_git,
            patch.object(github_dao, "get_pr_info") as mock_get_pr_info,
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "main"
            mock_get_pr_info.side_effect = GraphQLError("API error")

            result = rebase_finish_command(identifier="#42")

        assert result == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    def test_uses_worktree_path_when_different_branch(self, tmp_path: Path, capsys) -> None:
        """Should use worktree path when on different branch."""
        # Create worktree directory
        worktree_path = tmp_path / ".worktrees" / "other-branch"
        worktree_path.mkdir(parents=True)
        sandbox_path = tmp_path / ".git" / "rebase-sandbox" / "other-branch"
        sandbox_path.mkdir(parents=True)

        with patch("scripts.pr.commands.rebase_finish_command.git_dao") as mock_git:
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "main"  # Different from other-branch
            mock_git.force_push.return_value = (True, "")
            mock_git.reset_hard_to_remote.return_value = (True, "")
            mock_git.remove_shared_clone.return_value = (True, "")

            result = rebase_finish_command(identifier="other-branch")

        assert result == 0
        # Verify reset_hard_to_remote was called with worktree path
        call_args = mock_git.reset_hard_to_remote.call_args[0]
        source_path = call_args[0]
        assert ".worktrees" in str(source_path)

    def test_completes_full_workflow(self, tmp_path: Path, capsys) -> None:
        """Should complete force push, sync, and cleanup successfully."""
        sandbox_path = tmp_path / ".git" / "rebase-sandbox" / "feature"
        sandbox_path.mkdir(parents=True)

        with (
            patch("scripts.pr.commands.rebase_finish_command.git_dao") as mock_git,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "feature"
            mock_git.force_push.return_value = (True, "")
            mock_git.reset_hard_to_remote.return_value = (True, "")
            mock_git.remove_shared_clone.return_value = (True, "")

            result = rebase_finish_command()

        assert result == 0
        mock_git.force_push.assert_called_once()
        mock_git.reset_hard_to_remote.assert_called_once()
        mock_git.remove_shared_clone.assert_called_once()
        captured = capsys.readouterr()
        stdout_json = json.loads(captured.out)
        assert stdout_json["status"] == "success"
