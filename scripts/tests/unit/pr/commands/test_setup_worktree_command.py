"""Tests for setup_worktree_command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.clients.linear_client import LinearClientError
from scripts.pr.commands.setup_worktree_command import setup_worktree_command


class TestSetupWorktreeCommand:
    """Tests for setup_worktree_command function."""

    def test_success_creates_new_worktree(self) -> None:
        """Should return 0 and create worktree when successful."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {
            "branch_name": "feature-branch",
        }

        with (
            patch(
                "scripts.pr.commands.setup_worktree_command._get_default_client",
                return_value=mock_client,
            ),
            patch("scripts.pr.commands.setup_worktree_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.setup_worktree_command._find_available_branch_name"
            ) as mock_find,
        ):
            mock_git.get_current_branch.return_value = "main"
            mock_git.fetch_origin.return_value = (True, "")
            mock_find.return_value = "feature-branch"
            mock_git.worktree_exists.return_value = False
            mock_git.create_worktree.return_value = (True, "")

            result = setup_worktree_command("NES-123")

        assert result == 0
        mock_client.get_ticket_info.assert_called_once_with("NES-123")
        mock_git.create_worktree.assert_called_once()

    def test_missing_branch_name_returns_error(self) -> None:
        """Should return 1 when branch_name is missing from ticket info."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {
            "branch_name": None,
        }

        with patch(
            "scripts.pr.commands.setup_worktree_command._get_default_client",
            return_value=mock_client,
        ):
            result = setup_worktree_command("NES-123")

        assert result == 1

    def test_empty_branch_name_returns_error(self) -> None:
        """Should return 1 when branch_name is empty string."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {
            "branch_name": "",
        }

        with patch(
            "scripts.pr.commands.setup_worktree_command._get_default_client",
            return_value=mock_client,
        ):
            result = setup_worktree_command("NES-123")

        assert result == 1

    def test_cannot_determine_current_branch_returns_error(self) -> None:
        """Should return 1 when current branch cannot be determined."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {
            "branch_name": "feature-branch",
        }

        with (
            patch(
                "scripts.pr.commands.setup_worktree_command._get_default_client",
                return_value=mock_client,
            ),
            patch("scripts.pr.commands.setup_worktree_command.git_dao") as mock_git,
        ):
            mock_git.get_current_branch.return_value = None

            result = setup_worktree_command("NES-123")

        assert result == 1

    def test_fetch_origin_failure_returns_error(self) -> None:
        """Should return 1 when fetch origin fails."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {
            "branch_name": "feature-branch",
        }

        with (
            patch(
                "scripts.pr.commands.setup_worktree_command._get_default_client",
                return_value=mock_client,
            ),
            patch("scripts.pr.commands.setup_worktree_command.git_dao") as mock_git,
        ):
            mock_git.get_current_branch.return_value = "main"
            mock_git.fetch_origin.return_value = (False, "network error")

            result = setup_worktree_command("NES-123")

        assert result == 1

    def test_worktree_already_exists_returns_success(self) -> None:
        """Should return 0 with exists status when worktree already exists."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {
            "branch_name": "feature-branch",
        }

        with (
            patch(
                "scripts.pr.commands.setup_worktree_command._get_default_client",
                return_value=mock_client,
            ),
            patch("scripts.pr.commands.setup_worktree_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.setup_worktree_command._find_available_branch_name"
            ) as mock_find,
        ):
            mock_git.get_current_branch.return_value = "main"
            mock_git.fetch_origin.return_value = (True, "")
            mock_find.return_value = "feature-branch"
            mock_git.worktree_exists.return_value = True

            result = setup_worktree_command("NES-123")

        assert result == 0
        mock_git.create_worktree.assert_not_called()

    def test_create_worktree_failure_returns_error(self) -> None:
        """Should return 1 when worktree creation fails."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {
            "branch_name": "feature-branch",
        }

        with (
            patch(
                "scripts.pr.commands.setup_worktree_command._get_default_client",
                return_value=mock_client,
            ),
            patch("scripts.pr.commands.setup_worktree_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.setup_worktree_command._find_available_branch_name"
            ) as mock_find,
        ):
            mock_git.get_current_branch.return_value = "main"
            mock_git.fetch_origin.return_value = (True, "")
            mock_find.return_value = "feature-branch"
            mock_git.worktree_exists.return_value = False
            mock_git.create_worktree.return_value = (False, "branch already exists")

            result = setup_worktree_command("NES-123")

        assert result == 1

    def test_linear_client_error_returns_error(self) -> None:
        """Should return 1 when LinearClientError is raised."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.side_effect = LinearClientError(
            "NOT_FOUND", "Ticket not found: NES-999"
        )

        with patch(
            "scripts.pr.commands.setup_worktree_command._get_default_client",
            return_value=mock_client,
        ):
            result = setup_worktree_command("NES-999")

        assert result == 1

    def test_runtime_error_returns_error(self) -> None:
        """Should return 1 when RuntimeError is raised."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {
            "branch_name": "feature-branch",
        }

        with (
            patch(
                "scripts.pr.commands.setup_worktree_command._get_default_client",
                return_value=mock_client,
            ),
            patch("scripts.pr.commands.setup_worktree_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.setup_worktree_command._find_available_branch_name"
            ) as mock_find,
        ):
            mock_git.get_current_branch.return_value = "main"
            mock_git.fetch_origin.return_value = (True, "")
            mock_find.side_effect = RuntimeError("Could not find available branch name")

            result = setup_worktree_command("NES-123")

        assert result == 1

    def test_unsafe_branch_name_traversal_returns_error(self) -> None:
        """Should return 1 when branch name resolves outside .worktrees."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {
            "branch_name": "../../../etc/passwd",  # Path traversal attempt
        }

        with (
            patch(
                "scripts.pr.commands.setup_worktree_command._get_default_client",
                return_value=mock_client,
            ),
            patch("scripts.pr.commands.setup_worktree_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.setup_worktree_command._find_available_branch_name"
            ) as mock_find,
        ):
            mock_git.get_current_branch.return_value = "main"
            mock_git.fetch_origin.return_value = (True, "")
            mock_find.return_value = "../../../etc/passwd"

            result = setup_worktree_command("NES-123")

        assert result == 1
