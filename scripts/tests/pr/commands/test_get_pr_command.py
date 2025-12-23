"""Tests for get_pr_command module."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.pr.commands.get_pr_command import get_pr_command


class TestGetPrCommandNoIdentifier:
    """Tests for get_pr_command with no identifier (current branch)."""

    def test_no_identifier_uses_current_branch(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that None identifier uses current branch."""
        with (
            patch("scripts.pr.commands.get_pr_command.git_dao") as mock_git,
            patch("scripts.pr.commands.get_pr_command.github_dao") as mock_gh,
        ):
            mock_git.get_current_branch.return_value = "feature-branch"
            mock_git.is_inside_worktree.return_value = False
            mock_gh.get_pr_for_branch.return_value = {
                "pr_number": 42,
                "pr_url": "https://github.com/owner/repo/pull/42",
                "base_branch": "main",
            }

            result = get_pr_command(None)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["branch_name"] == "feature-branch"
        assert output["pr_number"] == 42
        assert output["is_worktree"] is False
        assert output["working_directory"] == "."
        assert result == 0

    def test_no_identifier_not_on_branch_returns_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test error when not on a branch with no identifier."""
        with patch("scripts.pr.commands.get_pr_command.git_dao") as mock_git:
            mock_git.get_current_branch.return_value = None
            mock_git.is_inside_worktree.return_value = False

            result = get_pr_command(None)

        captured = capsys.readouterr()
        assert "Error: Not on a branch" in captured.err
        assert result == 1

    def test_no_identifier_in_worktree(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test handling when in a worktree with no identifier."""
        with (
            patch("scripts.pr.commands.get_pr_command.git_dao") as mock_git,
            patch("scripts.pr.commands.get_pr_command.github_dao") as mock_gh,
        ):
            mock_git.get_current_branch.return_value = "my-branch"
            mock_git.is_inside_worktree.return_value = True
            mock_gh.get_pr_for_branch.return_value = None  # No PR

            result = get_pr_command(None)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["is_worktree"] is True
        assert output["worktree_path"] == ".worktrees/my-branch"
        assert output["pr_number"] is None
        assert result == 0


class TestGetPrCommandPrId:
    """Tests for get_pr_command with PR ID identifier."""

    def test_pr_id_with_hash(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test PR ID identifier with # prefix."""
        with (
            patch("scripts.pr.commands.get_pr_command.git_dao") as mock_git,
            patch("scripts.pr.commands.get_pr_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.get_pr_command._looks_like_pr_id") as mock_pr_id,
        ):
            mock_pr_id.return_value = 17
            mock_git.get_current_branch.return_value = "other-branch"
            mock_git.is_inside_worktree.return_value = False
            mock_gh.get_pr_info.return_value = {
                "head_branch": "nes-87-feature",
                "base_branch": "main",
                "state": "OPEN",
            }

            result = get_pr_command("#17")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["pr_number"] == 17
        assert output["branch_name"] == "nes-87-feature"
        assert output["base_branch"] == "main"
        assert output["is_worktree"] is True  # Different branch
        assert result == 0

    def test_pr_id_numeric(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test numeric PR ID identifier."""
        with (
            patch("scripts.pr.commands.get_pr_command.git_dao") as mock_git,
            patch("scripts.pr.commands.get_pr_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.get_pr_command._looks_like_pr_id") as mock_pr_id,
        ):
            mock_pr_id.return_value = 25
            mock_git.get_current_branch.return_value = "nes-99-other"
            mock_git.is_inside_worktree.return_value = False
            mock_gh.get_pr_info.return_value = {
                "head_branch": "nes-25-fix",
                "base_branch": "develop",
                "state": "OPEN",
            }

            result = get_pr_command("25")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["pr_number"] == 25
        assert output["branch_name"] == "nes-25-fix"
        assert result == 0

    def test_pr_id_no_head_branch_returns_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test error when PR has no head branch."""
        with (
            patch("scripts.pr.commands.get_pr_command.git_dao") as mock_git,
            patch("scripts.pr.commands.get_pr_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.get_pr_command._looks_like_pr_id") as mock_pr_id,
        ):
            mock_pr_id.return_value = 99
            mock_git.get_current_branch.return_value = "main"
            mock_git.is_inside_worktree.return_value = False
            mock_gh.get_pr_info.return_value = {
                "head_branch": None,
                "base_branch": "main",
            }

            result = get_pr_command("99")

        captured = capsys.readouterr()
        assert "Error: Could not determine head branch for PR #99" in captured.err
        assert result == 1

    def test_pr_id_on_same_branch(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test PR ID when already on the same branch."""
        with (
            patch("scripts.pr.commands.get_pr_command.git_dao") as mock_git,
            patch("scripts.pr.commands.get_pr_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.get_pr_command._looks_like_pr_id") as mock_pr_id,
        ):
            mock_pr_id.return_value = 10
            mock_git.get_current_branch.return_value = "same-branch"
            mock_git.is_inside_worktree.return_value = True
            mock_gh.get_pr_info.return_value = {
                "head_branch": "same-branch",
                "base_branch": "main",
            }

            result = get_pr_command("10")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["is_worktree"] is True  # From is_inside_worktree
        assert output["working_directory"] == "."
        assert result == 0


class TestGetPrCommandTicketId:
    """Tests for get_pr_command with ticket ID identifier."""

    def test_ticket_id_with_open_pr(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test ticket ID identifier with existing open PR."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": "nes-87-feature"}
        mock_client.fetch_github_attachments.return_value = [
            {"url": "https://github.com/owner/repo/pull/42"},
        ]

        with (
            patch("scripts.pr.commands.get_pr_command.git_dao") as mock_git,
            patch("scripts.pr.commands.get_pr_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.get_pr_command._looks_like_pr_id") as mock_pr_id,
            patch("scripts.pr.commands.get_pr_command._looks_like_ticket_id") as mock_ticket_id,
            patch(
                "scripts.pr.commands.get_pr_command._get_default_client",
                return_value=mock_client,
            ),
        ):
            mock_pr_id.return_value = None
            mock_ticket_id.return_value = True
            mock_git.get_current_branch.return_value = "other"
            mock_git.is_inside_worktree.return_value = False
            mock_gh.get_pr_info.return_value = {
                "head_branch": "nes-87-feature",
                "base_branch": "main",
                "state": "OPEN",
            }

            result = get_pr_command("NES-87")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["branch_name"] == "nes-87-feature"
        assert output["pr_number"] == 42
        assert output["pr_url"] == "https://github.com/owner/repo/pull/42"
        assert result == 0

    def test_ticket_id_no_branch_name_returns_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test error when ticket has no branch name."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": None}

        with (
            patch("scripts.pr.commands.get_pr_command.git_dao") as mock_git,
            patch("scripts.pr.commands.get_pr_command._looks_like_pr_id") as mock_pr_id,
            patch("scripts.pr.commands.get_pr_command._looks_like_ticket_id") as mock_ticket_id,
            patch(
                "scripts.pr.commands.get_pr_command._get_default_client",
                return_value=mock_client,
            ),
        ):
            mock_pr_id.return_value = None
            mock_ticket_id.return_value = True
            mock_git.get_current_branch.return_value = "main"
            mock_git.is_inside_worktree.return_value = False

            result = get_pr_command("NES-100")

        captured = capsys.readouterr()
        assert "Error: No branch name configured for ticket NES-100" in captured.err
        assert result == 1

    def test_ticket_id_no_open_pr_uses_existing_branch(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test ticket ID with no open PR falls back to existing branch."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": "nes-50-feature"}
        mock_client.fetch_github_attachments.return_value = []

        with (
            patch("scripts.pr.commands.get_pr_command.git_dao") as mock_git,
            patch("scripts.pr.commands.get_pr_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.get_pr_command._looks_like_pr_id") as mock_pr_id,
            patch("scripts.pr.commands.get_pr_command._looks_like_ticket_id") as mock_ticket_id,
            patch(
                "scripts.pr.commands.get_pr_command._find_existing_branch_for_ticket"
            ) as mock_find,
            patch(
                "scripts.pr.commands.get_pr_command._get_default_client",
                return_value=mock_client,
            ),
        ):
            mock_pr_id.return_value = None
            mock_ticket_id.return_value = True
            mock_git.get_current_branch.return_value = "other"
            mock_git.is_inside_worktree.return_value = False
            mock_find.return_value = "nes-50-feature"

            result = get_pr_command("NES-50")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["branch_name"] == "nes-50-feature"
        assert output["pr_number"] is None
        assert result == 0

    def test_ticket_id_no_existing_branch_uses_expected_name(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test ticket ID with no existing branch uses expected name."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": "nes-60-new-feature"}
        mock_client.fetch_github_attachments.return_value = []

        with (
            patch("scripts.pr.commands.get_pr_command.git_dao") as mock_git,
            patch("scripts.pr.commands.get_pr_command._looks_like_pr_id") as mock_pr_id,
            patch("scripts.pr.commands.get_pr_command._looks_like_ticket_id") as mock_ticket_id,
            patch(
                "scripts.pr.commands.get_pr_command._find_existing_branch_for_ticket"
            ) as mock_find,
            patch("scripts.pr.commands.get_pr_command._get_expected_branch_name") as mock_expected,
            patch(
                "scripts.pr.commands.get_pr_command._get_default_client",
                return_value=mock_client,
            ),
        ):
            mock_pr_id.return_value = None
            mock_ticket_id.return_value = True
            mock_git.get_current_branch.return_value = "other"
            mock_git.is_inside_worktree.return_value = False
            mock_find.return_value = None
            mock_expected.return_value = "nes-60-new-feature"

            result = get_pr_command("NES-60")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["branch_name"] == "nes-60-new-feature"
        assert result == 0

    def test_ticket_id_on_same_branch(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test ticket ID when already on the correct branch."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": "nes-70-current"}
        mock_client.fetch_github_attachments.return_value = [
            {"url": "https://github.com/owner/repo/pull/70"},
        ]

        with (
            patch("scripts.pr.commands.get_pr_command.git_dao") as mock_git,
            patch("scripts.pr.commands.get_pr_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.get_pr_command._looks_like_pr_id") as mock_pr_id,
            patch("scripts.pr.commands.get_pr_command._looks_like_ticket_id") as mock_ticket_id,
            patch(
                "scripts.pr.commands.get_pr_command._get_default_client",
                return_value=mock_client,
            ),
        ):
            mock_pr_id.return_value = None
            mock_ticket_id.return_value = True
            mock_git.get_current_branch.return_value = "nes-70-current"
            mock_git.is_inside_worktree.return_value = True
            mock_gh.get_pr_info.return_value = {
                "head_branch": "nes-70-current",
                "base_branch": "main",
                "state": "OPEN",
            }

            result = get_pr_command("NES-70")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["working_directory"] == "."
        assert output["is_worktree"] is True
        assert result == 0

    def test_ticket_id_closed_pr_skipped(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that closed PRs are skipped when looking for open PRs."""
        from scripts.pr.github_dao import GraphQLError

        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": "nes-80-feature"}
        mock_client.fetch_github_attachments.return_value = [
            {"url": "https://github.com/owner/repo/pull/80"},
            {"url": "https://github.com/owner/repo/pull/81"},
        ]

        with (
            patch("scripts.pr.commands.get_pr_command.git_dao") as mock_git,
            patch("scripts.pr.commands.get_pr_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.get_pr_command._looks_like_pr_id") as mock_pr_id,
            patch("scripts.pr.commands.get_pr_command._looks_like_ticket_id") as mock_ticket_id,
            patch(
                "scripts.pr.commands.get_pr_command._get_default_client",
                return_value=mock_client,
            ),
        ):
            mock_pr_id.return_value = None
            mock_ticket_id.return_value = True
            mock_git.get_current_branch.return_value = "other"
            mock_git.is_inside_worktree.return_value = False
            mock_gh.GraphQLError = GraphQLError
            # First PR is closed, second is open, third call is to get base_branch
            mock_gh.get_pr_info.side_effect = [
                {"head_branch": "old-branch", "base_branch": "main", "state": "CLOSED"},
                {"head_branch": "nes-80-feature", "base_branch": "main", "state": "OPEN"},
                {"head_branch": "nes-80-feature", "base_branch": "main", "state": "OPEN"},
            ]

            result = get_pr_command("NES-80")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["pr_number"] == 81
        assert output["branch_name"] == "nes-80-feature"
        assert result == 0

    def test_ticket_id_graphql_error_continues(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that GraphQL errors when checking PRs don't stop processing."""
        from scripts.pr.github_dao import GraphQLError

        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": "nes-90-feature"}
        mock_client.fetch_github_attachments.return_value = [
            {"url": "https://github.com/owner/repo/pull/90"},
        ]

        with (
            patch("scripts.pr.commands.get_pr_command.git_dao") as mock_git,
            patch("scripts.pr.commands.get_pr_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.get_pr_command._looks_like_pr_id") as mock_pr_id,
            patch("scripts.pr.commands.get_pr_command._looks_like_ticket_id") as mock_ticket_id,
            patch(
                "scripts.pr.commands.get_pr_command._find_existing_branch_for_ticket"
            ) as mock_find,
            patch(
                "scripts.pr.commands.get_pr_command._get_default_client",
                return_value=mock_client,
            ),
        ):
            mock_pr_id.return_value = None
            mock_ticket_id.return_value = True
            mock_git.get_current_branch.return_value = "other"
            mock_git.is_inside_worktree.return_value = False
            mock_gh.GraphQLError = GraphQLError
            mock_gh.get_pr_info.side_effect = GraphQLError("API error")
            mock_find.return_value = "nes-90-feature"

            result = get_pr_command("NES-90")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["branch_name"] == "nes-90-feature"
        assert output["pr_number"] is None  # No PR found due to error
        assert result == 0


class TestGetPrCommandBranchName:
    """Tests for get_pr_command with branch name identifier."""

    def test_branch_name_with_pr(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test branch name identifier with existing PR."""
        with (
            patch("scripts.pr.commands.get_pr_command.git_dao") as mock_git,
            patch("scripts.pr.commands.get_pr_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.get_pr_command._looks_like_pr_id") as mock_pr_id,
            patch("scripts.pr.commands.get_pr_command._looks_like_ticket_id") as mock_ticket_id,
        ):
            mock_pr_id.return_value = None
            mock_ticket_id.return_value = False
            mock_git.get_current_branch.return_value = "other-branch"
            mock_git.is_inside_worktree.return_value = False
            mock_gh.get_pr_for_branch.return_value = {
                "pr_number": 55,
                "pr_url": "https://github.com/owner/repo/pull/55",
                "base_branch": "main",
            }

            result = get_pr_command("feature-x")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["branch_name"] == "feature-x"
        assert output["pr_number"] == 55
        assert output["is_worktree"] is True  # Different branch
        assert result == 0

    def test_branch_name_without_pr(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test branch name identifier without existing PR."""
        with (
            patch("scripts.pr.commands.get_pr_command.git_dao") as mock_git,
            patch("scripts.pr.commands.get_pr_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.get_pr_command._looks_like_pr_id") as mock_pr_id,
            patch("scripts.pr.commands.get_pr_command._looks_like_ticket_id") as mock_ticket_id,
        ):
            mock_pr_id.return_value = None
            mock_ticket_id.return_value = False
            mock_git.get_current_branch.return_value = "other"
            mock_git.is_inside_worktree.return_value = False
            mock_gh.get_pr_for_branch.return_value = None

            result = get_pr_command("new-branch")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["branch_name"] == "new-branch"
        assert output["pr_number"] is None
        assert output["pr_url"] is None
        assert result == 0

    def test_branch_name_on_same_branch(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test branch name when already on the same branch."""
        with (
            patch("scripts.pr.commands.get_pr_command.git_dao") as mock_git,
            patch("scripts.pr.commands.get_pr_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.get_pr_command._looks_like_pr_id") as mock_pr_id,
            patch("scripts.pr.commands.get_pr_command._looks_like_ticket_id") as mock_ticket_id,
        ):
            mock_pr_id.return_value = None
            mock_ticket_id.return_value = False
            mock_git.get_current_branch.return_value = "same-branch"
            mock_git.is_inside_worktree.return_value = False
            mock_gh.get_pr_for_branch.return_value = None

            result = get_pr_command("same-branch")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["is_worktree"] is False
        assert output["working_directory"] == "."
        assert result == 0


class TestGetPrCommandErrors:
    """Tests for error handling in get_pr_command."""

    def test_linear_client_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test LinearClientError handling."""
        from scripts.clients.linear_client import LinearClientError

        mock_client = MagicMock()
        mock_client.get_ticket_info.side_effect = LinearClientError(
            "API_ERROR", "Connection failed"
        )

        with (
            patch("scripts.pr.commands.get_pr_command.git_dao") as mock_git,
            patch("scripts.pr.commands.get_pr_command._looks_like_pr_id") as mock_pr_id,
            patch("scripts.pr.commands.get_pr_command._looks_like_ticket_id") as mock_ticket_id,
            patch(
                "scripts.pr.commands.get_pr_command._get_default_client",
                return_value=mock_client,
            ),
        ):
            mock_pr_id.return_value = None
            mock_ticket_id.return_value = True
            mock_git.get_current_branch.return_value = "main"
            mock_git.is_inside_worktree.return_value = False

            result = get_pr_command("NES-999")

        captured = capsys.readouterr()
        assert "Error: API_ERROR: Connection failed" in captured.err
        assert result == 1

    def test_graphql_error_in_pr_lookup(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test GraphQLError handling during PR lookup."""
        from scripts.pr.github_dao import GraphQLError

        with (
            patch("scripts.pr.commands.get_pr_command.git_dao") as mock_git,
            patch("scripts.pr.commands.get_pr_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.get_pr_command._looks_like_pr_id") as mock_pr_id,
        ):
            mock_pr_id.return_value = 42
            mock_git.get_current_branch.return_value = "main"
            mock_git.is_inside_worktree.return_value = False
            mock_gh.GraphQLError = GraphQLError
            mock_gh.get_pr_info.side_effect = GraphQLError("GitHub API error")

            result = get_pr_command("42")

        captured = capsys.readouterr()
        assert "Error fetching PR info from GitHub" in captured.err
        assert result == 1
