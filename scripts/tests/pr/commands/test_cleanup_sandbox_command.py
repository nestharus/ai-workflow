"""Tests for scripts/pr/commands/cleanup_sandbox_command.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.clients.linear_client import LinearClientError
from scripts.pr import github_dao
from scripts.pr.commands.cleanup_sandbox_command import cleanup_sandbox_command

MODULE = "scripts.pr.commands.cleanup_sandbox_command"


@pytest.fixture
def mock_git_dao():
    """Mock git_dao functions."""
    with patch(f"{MODULE}.git_dao") as mock_git:
        mock_git.get_repo_root.return_value = Path("/repo")
        mock_git.get_current_branch.return_value = "current-branch"
        mock_git.branch_exists.return_value = False
        mock_git.remove_shared_clone.return_value = (True, "")
        yield mock_git


class TestCleanupSandboxCommand:
    """Tests for cleanup_sandbox_command() function."""

    def test_not_in_git_repo(self, mock_git_dao, capsys: pytest.CaptureFixture) -> None:
        """Test when not in a git repository."""
        mock_git_dao.get_repo_root.return_value = None
        result = cleanup_sandbox_command(None)

        assert result == 1
        captured = capsys.readouterr()
        assert "Not in a git repository" in captured.err

    def test_no_identifier_not_on_branch(self, mock_git_dao, capsys: pytest.CaptureFixture) -> None:
        """Test when no identifier and not on a branch."""
        mock_git_dao.get_current_branch.return_value = None
        result = cleanup_sandbox_command(None)

        assert result == 1
        captured = capsys.readouterr()
        assert "Not on a branch" in captured.err

    def test_pr_id_no_head_branch(self, mock_git_dao, capsys: pytest.CaptureFixture) -> None:
        """Test when PR ID provided but no head branch in PR info."""
        with patch(f"{MODULE}.github_dao") as mock_gh:
            mock_gh.get_pr_info.return_value = {"head_branch": None}
            result = cleanup_sandbox_command("#17")

        assert result == 1
        captured = capsys.readouterr()
        assert "Could not determine branch for PR" in captured.err

    def test_ticket_id_no_branch_name(self, mock_git_dao, capsys: pytest.CaptureFixture) -> None:
        """Test when ticket ID provided but no branch name in Linear."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": None}

        with patch(f"{MODULE}._get_default_client", return_value=mock_client):
            result = cleanup_sandbox_command("NES-123")

        assert result == 1
        captured = capsys.readouterr()
        assert "No branch name for ticket" in captured.err

    def test_ticket_id_with_existing_branch(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test when ticket ID resolves to existing branch."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": "mrasolomon/nes-123-feature"}

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        sandbox_dir = repo_root / ".git" / "rebase-sandbox" / "mrasolomon-nes-123-feature"
        sandbox_dir.mkdir(parents=True)

        with patch(f"{MODULE}.git_dao") as mock_git:
            mock_git.get_repo_root.return_value = repo_root
            mock_git.remove_shared_clone.return_value = (True, "")
            with patch(f"{MODULE}._get_default_client", return_value=mock_client), patch(
                f"{MODULE}._find_existing_branch_for_ticket",
                return_value="mrasolomon/nes-123-feature",
            ):
                result = cleanup_sandbox_command("NES-123")

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["status"] == "removed"

    def test_ticket_id_no_existing_branch_fallback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test when ticket ID has no existing branch, falls back to expected name."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": "mrasolomon/nes-123-feature"}

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        sandbox_dir = repo_root / ".git" / "rebase-sandbox" / "mrasolomon-nes-123-feature"
        sandbox_dir.mkdir(parents=True)

        with patch(f"{MODULE}.git_dao") as mock_git:
            mock_git.get_repo_root.return_value = repo_root
            mock_git.remove_shared_clone.return_value = (True, "")
            with patch(f"{MODULE}._get_default_client", return_value=mock_client), patch(
                f"{MODULE}._find_existing_branch_for_ticket", return_value=None
            ), patch(
                f"{MODULE}._get_expected_branch_name",
                return_value="mrasolomon/nes-123-feature",
            ):
                result = cleanup_sandbox_command("NES-123")

        assert result == 0

    def test_branch_name_direct(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test with branch name provided directly."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        sandbox_dir = repo_root / ".git" / "rebase-sandbox" / "my-branch"
        sandbox_dir.mkdir(parents=True)

        with patch(f"{MODULE}.git_dao") as mock_git:
            mock_git.get_repo_root.return_value = repo_root
            mock_git.remove_shared_clone.return_value = (True, "")
            result = cleanup_sandbox_command("my-branch")

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["status"] == "removed"

    def test_sandbox_not_found(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test when sandbox directory doesn't exist."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        # Don't create the sandbox directory

        with patch(f"{MODULE}.git_dao") as mock_git:
            mock_git.get_repo_root.return_value = repo_root
            result = cleanup_sandbox_command("my-branch")

        assert result == 1
        captured = capsys.readouterr()
        assert "No sandbox found" in captured.err

    def test_remove_shared_clone_fails(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test when remove_shared_clone fails."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        sandbox_dir = repo_root / ".git" / "rebase-sandbox" / "my-branch"
        sandbox_dir.mkdir(parents=True)

        with patch(f"{MODULE}.git_dao") as mock_git:
            mock_git.get_repo_root.return_value = repo_root
            mock_git.remove_shared_clone.return_value = (False, "Permission denied")
            result = cleanup_sandbox_command("my-branch")

        assert result == 1
        captured = capsys.readouterr()
        assert "Error removing sandbox" in captured.err

    def test_linear_client_error(self, mock_git_dao, capsys: pytest.CaptureFixture) -> None:
        """Test handling of LinearClientError."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.side_effect = LinearClientError("API_ERROR", "API error")

        with patch(f"{MODULE}._get_default_client", return_value=mock_client):
            result = cleanup_sandbox_command("NES-123")

        assert result == 1
        captured = capsys.readouterr()
        assert "API error" in captured.err

    def test_graphql_error(self, mock_git_dao, capsys: pytest.CaptureFixture) -> None:
        """Test handling of GraphQLError."""
        with patch(f"{MODULE}.github_dao") as mock_gh:
            mock_gh.GraphQLError = github_dao.GraphQLError
            mock_gh.get_pr_info.side_effect = github_dao.GraphQLError("GraphQL error")
            result = cleanup_sandbox_command("#17")

        assert result == 1
        captured = capsys.readouterr()
        assert "GraphQL error" in captured.err

    def test_pr_id_with_hash(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test PR ID with # prefix."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        sandbox_dir = repo_root / ".git" / "rebase-sandbox" / "feature-branch"
        sandbox_dir.mkdir(parents=True)

        with patch(f"{MODULE}.git_dao") as mock_git:
            mock_git.get_repo_root.return_value = repo_root
            mock_git.remove_shared_clone.return_value = (True, "")
            with patch(f"{MODULE}.github_dao") as mock_gh:
                mock_gh.get_pr_info.return_value = {"head_branch": "feature-branch"}
                result = cleanup_sandbox_command("#42")

        assert result == 0

    def test_no_identifier_uses_current_branch(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test when no identifier, uses current branch."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        sandbox_dir = repo_root / ".git" / "rebase-sandbox" / "current-branch"
        sandbox_dir.mkdir(parents=True)

        with patch(f"{MODULE}.git_dao") as mock_git:
            mock_git.get_repo_root.return_value = repo_root
            mock_git.get_current_branch.return_value = "current-branch"
            mock_git.remove_shared_clone.return_value = (True, "")
            result = cleanup_sandbox_command(None)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "current-branch" in output["sandbox_path"]
