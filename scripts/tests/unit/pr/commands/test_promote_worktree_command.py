"""Tests for promote_worktree_command function."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.pr.commands.promote_worktree_command import promote_worktree_command


class TestPromoteWorktreeCommand:
    """Tests for promote_worktree_command function."""

    def test_returns_error_when_not_in_repo(self, capsys) -> None:
        """Should return 1 when not in a git repository."""
        with patch("scripts.pr.commands.promote_worktree_command.git_dao") as mock_git:
            mock_git.get_current_branch.return_value = "feature"
            mock_git.is_inside_worktree.return_value = False
            mock_git.get_repo_root.return_value = None

            result = promote_worktree_command()

        assert result == 1
        captured = capsys.readouterr()
        assert "Not in a git repository" in captured.err

    def test_returns_error_when_not_on_branch(self, tmp_path: Path, capsys) -> None:
        """Should return 1 when not on any branch (no identifier)."""
        with patch("scripts.pr.commands.promote_worktree_command.git_dao") as mock_git:
            mock_git.get_current_branch.return_value = None
            mock_git.is_inside_worktree.return_value = False
            mock_git.get_repo_root.return_value = tmp_path

            result = promote_worktree_command(identifier=None)

        assert result == 1
        captured = capsys.readouterr()
        assert "Not on a branch" in captured.err

    def test_creates_sandbox_from_current_branch(self, tmp_path: Path, capsys) -> None:
        """Should create sandbox using current branch when no identifier."""
        _sandbox_path = tmp_path / ".git" / "rebase-sandbox" / "feature-branch"

        with (
            patch("scripts.pr.commands.promote_worktree_command.git_dao") as mock_git,
            patch("scripts.pr.commands.promote_worktree_command.github_dao") as mock_github,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_current_branch.return_value = "feature-branch"
            mock_git.is_inside_worktree.return_value = False
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.create_shared_clone.return_value = (True, "")
            mock_github.get_pr_for_branch.return_value = {
                "pr_number": 123,
                "base_branch": "main",
            }

            result = promote_worktree_command(identifier=None)

        assert result == 0
        mock_git.create_shared_clone.assert_called_once()
        captured = capsys.readouterr()
        assert "Creating rebase sandbox" in captured.err
        # Parse JSON output
        stdout_json = json.loads(captured.out)
        assert stdout_json["status"] == "created"
        assert stdout_json["branch_name"] == "feature-branch"

    def test_returns_error_when_pr_branch_not_found(self, tmp_path: Path, capsys) -> None:
        """Should return 1 when PR has no head branch."""
        with (
            patch("scripts.pr.commands.promote_worktree_command.git_dao") as mock_git,
            patch("scripts.pr.commands.promote_worktree_command.github_dao") as mock_github,
        ):
            mock_git.get_current_branch.return_value = "main"
            mock_git.is_inside_worktree.return_value = False
            mock_git.get_repo_root.return_value = tmp_path
            mock_github.get_pr_info.return_value = {"head_branch": None, "base_branch": "main"}

            result = promote_worktree_command(identifier="#42")

        assert result == 1
        captured = capsys.readouterr()
        assert "Could not determine head branch for PR" in captured.err

    def test_uses_pr_info_for_pr_identifier(self, tmp_path: Path, capsys) -> None:
        """Should fetch PR info when identifier is a PR number."""
        # Create worktree directory since we're on "main" but the PR is for "pr-branch"
        worktree_path = tmp_path / ".worktrees" / "pr-branch"
        worktree_path.mkdir(parents=True)

        with (
            patch("scripts.pr.commands.promote_worktree_command.git_dao") as mock_git,
            patch("scripts.pr.commands.promote_worktree_command.github_dao") as mock_github,
        ):
            mock_git.get_current_branch.return_value = "main"
            mock_git.is_inside_worktree.return_value = False
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.create_shared_clone.return_value = (True, "")
            mock_github.get_pr_info.return_value = {
                "head_branch": "pr-branch",
                "base_branch": "develop",
            }

            result = promote_worktree_command(identifier="42")

        assert result == 0
        mock_github.get_pr_info.assert_called_once_with(42)

    def test_uses_ticket_info_for_ticket_identifier(self, tmp_path: Path, capsys) -> None:
        """Should fetch ticket info when identifier is a ticket ID."""
        with (
            patch("scripts.pr.commands.promote_worktree_command.git_dao") as mock_git,
            patch("scripts.pr.commands.promote_worktree_command.github_dao"),
            patch(
                "scripts.pr.commands.promote_worktree_command._get_default_client"
            ) as mock_linear,
            patch(
                "scripts.pr.commands.promote_worktree_command._find_existing_branch_for_ticket"
            ) as mock_find_branch,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_current_branch.return_value = "nes-87-fix-bug"  # Same as branch
            mock_git.is_inside_worktree.return_value = False
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.create_shared_clone.return_value = (True, "")

            mock_client = MagicMock()
            mock_client.get_ticket_info.return_value = {"branch_name": "nes-87-fix-bug"}
            mock_client.fetch_github_attachments.return_value = []
            mock_linear.return_value = mock_client
            mock_find_branch.return_value = "nes-87-fix-bug"

            result = promote_worktree_command(identifier="NES-87")

        assert result == 0
        mock_client.get_ticket_info.assert_called_once_with("NES-87")

    def test_returns_error_when_no_branch_for_ticket(self, tmp_path: Path, capsys) -> None:
        """Should return 1 when ticket has no branch name."""
        with (
            patch("scripts.pr.commands.promote_worktree_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.promote_worktree_command._get_default_client"
            ) as mock_linear,
        ):
            mock_git.get_current_branch.return_value = "main"
            mock_git.is_inside_worktree.return_value = False
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.branch_exists.return_value = False

            mock_client = MagicMock()
            mock_client.get_ticket_info.return_value = {"branch_name": None}
            mock_linear.return_value = mock_client

            result = promote_worktree_command(identifier="NES-88")

        assert result == 1
        captured = capsys.readouterr()
        assert "No branch name configured for ticket" in captured.err

    def test_uses_branch_name_directly(self, tmp_path: Path, capsys) -> None:
        """Should use identifier as branch name when it's not PR/ticket."""
        # Create worktree directory since identifier is different from current branch
        worktree_path = tmp_path / ".worktrees" / "my-feature-branch"
        worktree_path.mkdir(parents=True)

        with (
            patch("scripts.pr.commands.promote_worktree_command.git_dao") as mock_git,
            patch("scripts.pr.commands.promote_worktree_command.github_dao") as mock_github,
        ):
            mock_git.get_current_branch.return_value = "main"
            mock_git.is_inside_worktree.return_value = False
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.create_shared_clone.return_value = (True, "")
            mock_github.get_pr_for_branch.return_value = None

            result = promote_worktree_command(identifier="my-feature-branch")

        assert result == 0
        captured = capsys.readouterr()
        stdout_json = json.loads(captured.out)
        assert stdout_json["branch_name"] == "my-feature-branch"

    def test_returns_existing_sandbox_info(self, tmp_path: Path, capsys) -> None:
        """Should return existing sandbox info when sandbox already exists."""
        sandbox_path = tmp_path / ".git" / "rebase-sandbox" / "feature"
        sandbox_path.mkdir(parents=True)

        with (
            patch("scripts.pr.commands.promote_worktree_command.git_dao") as mock_git,
            patch("scripts.pr.commands.promote_worktree_command.github_dao") as mock_github,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_current_branch.return_value = "feature"
            mock_git.is_inside_worktree.return_value = False
            mock_git.get_repo_root.return_value = tmp_path
            mock_github.get_pr_for_branch.return_value = {"pr_number": 1, "base_branch": "main"}

            result = promote_worktree_command(identifier=None)

        assert result == 0
        captured = capsys.readouterr()
        assert "Sandbox already exists" in captured.err
        stdout_json = json.loads(captured.out)
        assert stdout_json["status"] == "exists"

    def test_returns_error_when_source_path_not_exists(self, tmp_path: Path, capsys) -> None:
        """Should return 1 when source path does not exist."""
        with (
            patch("scripts.pr.commands.promote_worktree_command.git_dao") as mock_git,
            patch("scripts.pr.commands.promote_worktree_command.github_dao") as mock_github,
        ):
            mock_git.get_current_branch.return_value = "main"  # Not same as feature
            mock_git.is_inside_worktree.return_value = False
            mock_git.get_repo_root.return_value = tmp_path
            mock_github.get_pr_for_branch.return_value = {"pr_number": 1, "base_branch": "main"}

            # Request different branch that doesn't exist as worktree
            result = promote_worktree_command(identifier="feature")

        assert result == 1
        captured = capsys.readouterr()
        assert "Source path does not exist" in captured.err

    def test_returns_error_when_clone_fails(self, tmp_path: Path, capsys) -> None:
        """Should return 1 when create_shared_clone fails."""
        with (
            patch("scripts.pr.commands.promote_worktree_command.git_dao") as mock_git,
            patch("scripts.pr.commands.promote_worktree_command.github_dao") as mock_github,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_current_branch.return_value = "feature"
            mock_git.is_inside_worktree.return_value = False
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.create_shared_clone.return_value = (False, "Clone failed")
            mock_github.get_pr_for_branch.return_value = None

            result = promote_worktree_command(identifier=None)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error creating sandbox: Clone failed" in captured.err

    def test_handles_linear_client_error(self, tmp_path: Path, capsys) -> None:
        """Should return 1 on LinearClientError."""
        from scripts.clients.linear_client import LinearClientError

        with (
            patch("scripts.pr.commands.promote_worktree_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.promote_worktree_command._get_default_client"
            ) as mock_linear,
        ):
            mock_git.get_current_branch.return_value = "main"
            mock_git.is_inside_worktree.return_value = False
            mock_git.get_repo_root.return_value = tmp_path

            mock_linear.side_effect = LinearClientError("API_ERROR", "API error")

            result = promote_worktree_command(identifier="NES-99")

        assert result == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    def test_handles_graphql_error(self, tmp_path: Path, capsys) -> None:
        """Should return 1 on GraphQLError."""
        from scripts.pr import github_dao
        from scripts.pr.github_dao import GraphQLError

        with (
            patch("scripts.pr.commands.promote_worktree_command.git_dao") as mock_git,
            patch.object(github_dao, "get_pr_info") as mock_get_pr_info,
        ):
            mock_git.get_current_branch.return_value = "main"
            mock_git.is_inside_worktree.return_value = False
            mock_git.get_repo_root.return_value = tmp_path
            mock_get_pr_info.side_effect = GraphQLError("API error")

            result = promote_worktree_command(identifier="#42")

        assert result == 1
        captured = capsys.readouterr()
        assert "Error fetching PR info from GitHub" in captured.err

    def test_sanitizes_branch_name_with_slashes(self, tmp_path: Path, capsys) -> None:
        """Should replace slashes with dashes in sandbox path."""
        with (
            patch("scripts.pr.commands.promote_worktree_command.git_dao") as mock_git,
            patch("scripts.pr.commands.promote_worktree_command.github_dao") as mock_github,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_current_branch.return_value = "user/feature/branch"
            mock_git.is_inside_worktree.return_value = False
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.create_shared_clone.return_value = (True, "")
            mock_github.get_pr_for_branch.return_value = None

            result = promote_worktree_command(identifier=None)

        assert result == 0
        # Verify sandbox path uses sanitized name
        call_args = mock_git.create_shared_clone.call_args[0]
        sandbox_path = call_args[1]
        assert "user-feature-branch" in str(sandbox_path)

    def test_fetches_pr_from_ticket_attachments(self, tmp_path: Path, capsys) -> None:
        """Should get PR info from ticket GitHub attachments."""
        with (
            patch("scripts.pr.commands.promote_worktree_command.git_dao") as mock_git,
            patch("scripts.pr.commands.promote_worktree_command.github_dao") as mock_github,
            patch(
                "scripts.pr.commands.promote_worktree_command._get_default_client"
            ) as mock_linear,
            patch(
                "scripts.pr.commands.promote_worktree_command._find_existing_branch_for_ticket"
            ) as mock_find_branch,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_current_branch.return_value = "nes-87-fix-bug"  # Same as branch
            mock_git.is_inside_worktree.return_value = False
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.create_shared_clone.return_value = (True, "")

            mock_client = MagicMock()
            mock_client.get_ticket_info.return_value = {"branch_name": "nes-87-fix-bug"}
            mock_client.fetch_github_attachments.return_value = [
                {"url": "https://github.com/org/repo/pull/123"}
            ]
            mock_linear.return_value = mock_client
            mock_find_branch.return_value = "nes-87-fix-bug"

            mock_github.get_pr_info.return_value = {
                "state": "OPEN",
                "base_branch": "develop",
            }

            result = promote_worktree_command(identifier="NES-87")

        assert result == 0
        mock_github.get_pr_info.assert_called_with(123)
        captured = capsys.readouterr()
        stdout_json = json.loads(captured.out)
        assert stdout_json["base_branch"] == "develop"
        assert stdout_json["pr_number"] == 123
