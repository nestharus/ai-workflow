"""Tests for scripts/pr/commands/checkout_worktree_command.py."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.clients.linear_client import LinearClientError
from scripts.pr.commands.checkout_worktree_command import checkout_worktree_command


@pytest.fixture
def mock_git_dao():
    """Mock git_dao functions."""
    with patch("scripts.pr.commands.checkout_worktree_command.git_dao") as mock_git:
        mock_git.fetch_origin.return_value = (True, "")
        mock_git.branch_exists_local.return_value = False
        mock_git.branch_exists_remote.return_value = False
        mock_git.worktree_exists.return_value = False
        mock_git.create_worktree.return_value = (True, "")
        mock_git.create_worktree_tracking.return_value = (True, "")
        yield mock_git


class TestCheckoutWorktreeCommand:
    """Tests for checkout_worktree_command() function."""

    def test_fetch_origin_fails(self, mock_git_dao, capsys: pytest.CaptureFixture) -> None:
        """Test when git fetch origin fails."""
        mock_git_dao.fetch_origin.return_value = (False, "Network error")

        with patch(
            "scripts.pr.commands.checkout_worktree_command._looks_like_ticket_id",
            return_value=False,
        ):
            result = checkout_worktree_command("feature-branch")

        assert result == 1
        captured = capsys.readouterr()
        assert "Error fetching origin" in captured.err

    def test_ticket_id_no_branch_name_from_linear(
        self, mock_git_dao, capsys: pytest.CaptureFixture
    ) -> None:
        """Test when ticket has no branch name in Linear."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": None}

        with (
            patch(
                "scripts.pr.commands.checkout_worktree_command._looks_like_ticket_id",
                return_value=True,
            ),
            patch(
                "scripts.pr.commands.checkout_worktree_command._get_default_client",
                return_value=mock_client,
            ),
        ):
            result = checkout_worktree_command("NES-123")

        assert result == 1
        captured = capsys.readouterr()
        assert "No branch name found for ticket" in captured.err

    def test_ticket_id_no_existing_branch(
        self, mock_git_dao, capsys: pytest.CaptureFixture
    ) -> None:
        """Test when ticket has branch name but branch doesn't exist."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": "mrasolomon/nes-123-feature"}

        with (
            patch(
                "scripts.pr.commands.checkout_worktree_command._looks_like_ticket_id",
                return_value=True,
            ),
            patch(
                "scripts.pr.commands.checkout_worktree_command._get_default_client",
                return_value=mock_client,
            ),
            patch(
                "scripts.pr.commands.checkout_worktree_command._find_existing_branch_for_ticket",
                return_value=None,
            ),
            patch(
                "scripts.pr.commands.checkout_worktree_command._get_expected_branch_name",
                return_value="mrasolomon/nes-123-feature",
            ),
        ):
            result = checkout_worktree_command("NES-123")

        assert result == 1
        captured = capsys.readouterr()
        assert "No existing branch found for ticket" in captured.err

    def test_ticket_id_linear_client_error(
        self, mock_git_dao, capsys: pytest.CaptureFixture
    ) -> None:
        """Test when Linear API call fails."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.side_effect = LinearClientError("API_ERROR", "API error")

        with (
            patch(
                "scripts.pr.commands.checkout_worktree_command._looks_like_ticket_id",
                return_value=True,
            ),
            patch(
                "scripts.pr.commands.checkout_worktree_command._get_default_client",
                return_value=mock_client,
            ),
        ):
            result = checkout_worktree_command("NES-123")

        assert result == 1
        captured = capsys.readouterr()
        assert "API error" in captured.err

    def test_branch_name_not_exists(self, mock_git_dao, capsys: pytest.CaptureFixture) -> None:
        """Test when branch doesn't exist locally or remotely."""
        mock_git_dao.branch_exists_local.return_value = False
        mock_git_dao.branch_exists_remote.return_value = False

        with patch(
            "scripts.pr.commands.checkout_worktree_command._looks_like_ticket_id",
            return_value=False,
        ):
            result = checkout_worktree_command("nonexistent-branch")

        assert result == 1
        captured = capsys.readouterr()
        assert "does not exist locally or on remote" in captured.err

    def test_worktree_already_exists(self, mock_git_dao, capsys: pytest.CaptureFixture) -> None:
        """Test when worktree already exists at the path."""
        mock_git_dao.branch_exists_local.return_value = True
        mock_git_dao.worktree_exists.return_value = True

        with patch(
            "scripts.pr.commands.checkout_worktree_command._looks_like_ticket_id",
            return_value=False,
        ):
            result = checkout_worktree_command("existing-branch")

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["status"] == "exists"
        assert output["branch_created"] is False

    def test_create_worktree_local_branch_success(
        self, mock_git_dao, capsys: pytest.CaptureFixture
    ) -> None:
        """Test successfully creating worktree for local branch."""
        mock_git_dao.branch_exists_local.return_value = True
        mock_git_dao.worktree_exists.return_value = False
        mock_git_dao.create_worktree.return_value = (True, "")

        with patch(
            "scripts.pr.commands.checkout_worktree_command._looks_like_ticket_id",
            return_value=False,
        ):
            result = checkout_worktree_command("local-branch")

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["status"] == "created"
        assert output["tracked_remote"] is False

    def test_create_worktree_remote_branch_success(
        self, mock_git_dao, capsys: pytest.CaptureFixture
    ) -> None:
        """Test successfully creating worktree tracking remote branch."""
        mock_git_dao.branch_exists_local.return_value = False
        mock_git_dao.branch_exists_remote.return_value = True
        mock_git_dao.worktree_exists.return_value = False
        mock_git_dao.create_worktree_tracking.return_value = (True, "")

        with patch(
            "scripts.pr.commands.checkout_worktree_command._looks_like_ticket_id",
            return_value=False,
        ):
            result = checkout_worktree_command("remote-branch")

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["status"] == "created"
        assert output["tracked_remote"] is True

    def test_create_worktree_fails(self, mock_git_dao, capsys: pytest.CaptureFixture) -> None:
        """Test when create_worktree fails."""
        mock_git_dao.branch_exists_local.return_value = True
        mock_git_dao.worktree_exists.return_value = False
        mock_git_dao.create_worktree.return_value = (False, "Worktree error")

        with patch(
            "scripts.pr.commands.checkout_worktree_command._looks_like_ticket_id",
            return_value=False,
        ):
            result = checkout_worktree_command("branch")

        assert result == 1
        captured = capsys.readouterr()
        assert "Error creating worktree" in captured.err

    def test_ticket_id_with_found_branch(self, mock_git_dao, capsys: pytest.CaptureFixture) -> None:
        """Test successfully finding existing branch for ticket ID."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": "mrasolomon/nes-123-feature"}
        mock_git_dao.branch_exists_local.return_value = True
        mock_git_dao.worktree_exists.return_value = False
        mock_git_dao.create_worktree.return_value = (True, "")

        with (
            patch(
                "scripts.pr.commands.checkout_worktree_command._looks_like_ticket_id",
                return_value=True,
            ),
            patch(
                "scripts.pr.commands.checkout_worktree_command._get_default_client",
                return_value=mock_client,
            ),
            patch(
                "scripts.pr.commands.checkout_worktree_command._find_existing_branch_for_ticket",
                return_value="mrasolomon/nes-123-feature",
            ),
        ):
            result = checkout_worktree_command("NES-123")

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["status"] == "created"
