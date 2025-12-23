"""Tests for rebase_start_command function."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.pr.commands.rebase_start_command import (
    _find_existing_branch_for_ticket,
    _get_expected_branch_name,
    _looks_like_pr_id,
    _looks_like_ticket_id,
    rebase_start_command,
)


class TestLooksLikePrId:
    """Tests for _looks_like_pr_id helper."""

    def test_matches_plain_number(self) -> None:
        """Should return int for plain number."""
        assert _looks_like_pr_id("42") == 42

    def test_matches_hash_prefixed_number(self) -> None:
        """Should return int for hash-prefixed number."""
        assert _looks_like_pr_id("#123") == 123

    def test_returns_none_for_text(self) -> None:
        """Should return None for non-numeric text."""
        assert _looks_like_pr_id("feature") is None

    def test_returns_none_for_ticket_id(self) -> None:
        """Should return None for ticket ID."""
        assert _looks_like_pr_id("NES-87") is None


class TestLooksLikeTicketId:
    """Tests for _looks_like_ticket_id helper."""

    def test_matches_uppercase_ticket(self) -> None:
        """Should return True for uppercase ticket ID."""
        assert _looks_like_ticket_id("NES-87") is True

    def test_matches_lowercase_ticket(self) -> None:
        """Should return True for lowercase ticket ID."""
        assert _looks_like_ticket_id("proj-123") is True

    def test_returns_false_for_number(self) -> None:
        """Should return False for plain number."""
        assert _looks_like_ticket_id("42") is False

    def test_returns_false_for_branch_name(self) -> None:
        """Should return False for branch name."""
        assert _looks_like_ticket_id("feature-branch") is False


class TestGetExpectedBranchName:
    """Tests for _get_expected_branch_name helper."""

    def test_returns_name_if_within_limit(self) -> None:
        """Should return name unchanged if within limit."""
        assert _get_expected_branch_name("short-name") == "short-name"

    def test_truncates_long_name(self) -> None:
        """Should truncate name to 50 characters."""
        long_name = "a" * 60
        result = _get_expected_branch_name(long_name)
        assert len(result) == 50
        assert result == "a" * 50


class TestFindExistingBranchForTicket:
    """Tests for _find_existing_branch_for_ticket helper."""

    def test_returns_base_if_exists(self) -> None:
        """Should return base branch if it exists."""
        with patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git:
            mock_git.branch_exists.return_value = True
            result = _find_existing_branch_for_ticket("nes-87-fix-bug")

        assert result == "nes-87-fix-bug"

    def test_returns_counter_suffix_if_exists(self) -> None:
        """Should return branch with counter suffix if it exists."""
        with patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git:
            # Base doesn't exist, but -2 does
            mock_git.branch_exists.side_effect = [False, True]
            result = _find_existing_branch_for_ticket("nes-87-fix-bug")

        assert result == "nes-87-fix-bug-2"

    def test_returns_none_if_no_match(self) -> None:
        """Should return None if no matching branch exists."""
        with patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git:
            mock_git.branch_exists.return_value = False
            result = _find_existing_branch_for_ticket("nes-87-fix-bug")

        assert result is None


class TestRebaseStartCommand:
    """Tests for rebase_start_command function."""

    def test_returns_error_when_not_in_repo(self, capsys) -> None:
        """Should return 2 when not in a git repository."""
        with patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git:
            mock_git.get_repo_root.return_value = None

            result = rebase_start_command()

        assert result == 2
        captured = capsys.readouterr()
        assert "Not in a git repository" in captured.err

    def test_returns_error_when_not_on_branch(self, tmp_path: Path, capsys) -> None:
        """Should return 2 when not on any branch (no identifier)."""
        with patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git:
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = None

            result = rebase_start_command(identifier=None)

        assert result == 2
        captured = capsys.readouterr()
        assert "Not on a branch" in captured.err

    def test_returns_error_when_source_path_not_exists(self, tmp_path: Path, capsys) -> None:
        """Should return 2 when source path does not exist."""
        with (
            patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_start_command.github_dao") as mock_github,
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "main"  # Different from feature
            mock_github.get_pr_for_branch.return_value = None

            result = rebase_start_command(identifier="feature")

        assert result == 2
        captured = capsys.readouterr()
        assert "Source path does not exist" in captured.err

    def test_cleans_existing_sandbox(self, tmp_path: Path, capsys) -> None:
        """Should clean existing sandbox before creating new one."""
        sandbox_path = tmp_path / ".git" / "rebase-sandbox" / "feature"
        sandbox_path.mkdir(parents=True)

        with (
            patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_start_command.github_dao") as mock_github,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "feature"
            mock_git.remove_shared_clone.return_value = (True, "")
            mock_git.create_shared_clone.return_value = (True, "")
            mock_git.fetch_branch.return_value = (True, "")
            mock_git.get_merge_base.return_value = ("abc123", "")
            mock_git.get_commits_between.return_value = []
            mock_git.count_commits_ahead.return_value = (1, "")
            mock_git.rebase.return_value = (True, False, "")
            mock_github.get_pr_for_branch.return_value = None

            result = rebase_start_command()

        mock_git.remove_shared_clone.assert_called_once()
        assert result == 0

    def test_returns_error_when_cleanup_fails(self, tmp_path: Path, capsys) -> None:
        """Should return 2 when cleanup of existing sandbox fails."""
        sandbox_path = tmp_path / ".git" / "rebase-sandbox" / "feature"
        sandbox_path.mkdir(parents=True)

        with (
            patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_start_command.github_dao") as mock_github,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "feature"
            mock_git.remove_shared_clone.return_value = (False, "Cleanup failed")
            mock_github.get_pr_for_branch.return_value = None

            result = rebase_start_command()

        assert result == 2
        captured = capsys.readouterr()
        assert "Error cleaning up existing sandbox" in captured.err

    def test_returns_error_when_clone_fails(self, tmp_path: Path, capsys) -> None:
        """Should return 2 when create_shared_clone fails."""
        with (
            patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_start_command.github_dao") as mock_github,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "feature"
            mock_git.create_shared_clone.return_value = (False, "Clone failed")
            mock_github.get_pr_for_branch.return_value = None

            result = rebase_start_command()

        assert result == 2
        captured = capsys.readouterr()
        assert "Error creating sandbox" in captured.err

    def test_returns_error_when_fetch_fails(self, tmp_path: Path, capsys) -> None:
        """Should return 2 when fetch fails."""
        with (
            patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_start_command.github_dao") as mock_github,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "feature"
            mock_git.create_shared_clone.return_value = (True, "")
            mock_git.fetch_branch.return_value = (False, "Fetch failed")
            mock_github.get_pr_for_branch.return_value = None

            result = rebase_start_command()

        assert result == 2
        captured = capsys.readouterr()
        assert "Error fetching branch" in captured.err

    def test_returns_error_when_merge_base_fails(self, tmp_path: Path, capsys) -> None:
        """Should return 2 when merge base lookup fails."""
        with (
            patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_start_command.github_dao") as mock_github,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "feature"
            mock_git.create_shared_clone.return_value = (True, "")
            mock_git.fetch_branch.return_value = (True, "")
            mock_git.get_merge_base.return_value = ("", "No merge base")
            mock_github.get_pr_for_branch.return_value = None

            result = rebase_start_command()

        assert result == 2
        captured = capsys.readouterr()
        assert "Error finding merge base" in captured.err

    def test_returns_error_when_count_commits_fails(self, tmp_path: Path, capsys) -> None:
        """Should return 2 when commit count fails."""
        with (
            patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_start_command.github_dao") as mock_github,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "feature"
            mock_git.create_shared_clone.return_value = (True, "")
            mock_git.fetch_branch.return_value = (True, "")
            mock_git.get_merge_base.return_value = ("abc123", "")
            mock_git.get_commits_between.return_value = []
            mock_git.count_commits_ahead.return_value = (-1, "Count failed")
            mock_github.get_pr_for_branch.return_value = None

            result = rebase_start_command()

        assert result == 2
        captured = capsys.readouterr()
        assert "Error counting commits" in captured.err

    def test_squashes_multiple_commits(self, tmp_path: Path, capsys) -> None:
        """Should squash when more than 1 commit ahead."""
        with (
            patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_start_command.github_dao") as mock_github,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "feature"
            mock_git.create_shared_clone.return_value = (True, "")
            mock_git.fetch_branch.return_value = (True, "")
            mock_git.get_merge_base.return_value = ("abc123", "")
            mock_git.get_commits_between.return_value = []
            mock_git.count_commits_ahead.return_value = (3, "")
            mock_git.get_last_commit_message.return_value = "Last commit msg"
            mock_git.soft_reset.return_value = (True, "")
            mock_git.commit.return_value = True
            mock_git.rebase.return_value = (True, False, "")
            mock_github.get_pr_for_branch.return_value = None

            result = rebase_start_command()

        assert result == 0
        mock_git.soft_reset.assert_called_once()
        mock_git.commit.assert_called_once()
        captured = capsys.readouterr()
        assert "Squashing 3 commits" in captured.err

    def test_returns_error_when_soft_reset_fails(self, tmp_path: Path, capsys) -> None:
        """Should return 2 when soft reset fails during squash."""
        with (
            patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_start_command.github_dao") as mock_github,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "feature"
            mock_git.create_shared_clone.return_value = (True, "")
            mock_git.fetch_branch.return_value = (True, "")
            mock_git.get_merge_base.return_value = ("abc123", "")
            mock_git.get_commits_between.return_value = []
            mock_git.count_commits_ahead.return_value = (3, "")
            mock_git.get_last_commit_message.return_value = "msg"
            mock_git.soft_reset.return_value = (False, "Reset failed")
            mock_github.get_pr_for_branch.return_value = None

            result = rebase_start_command()

        assert result == 2
        captured = capsys.readouterr()
        assert "Error during soft reset" in captured.err

    def test_returns_error_when_squash_commit_fails(self, tmp_path: Path, capsys) -> None:
        """Should return 2 when squash commit fails."""
        with (
            patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_start_command.github_dao") as mock_github,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "feature"
            mock_git.create_shared_clone.return_value = (True, "")
            mock_git.fetch_branch.return_value = (True, "")
            mock_git.get_merge_base.return_value = ("abc123", "")
            mock_git.get_commits_between.return_value = []
            mock_git.count_commits_ahead.return_value = (3, "")
            mock_git.get_last_commit_message.return_value = "msg"
            mock_git.soft_reset.return_value = (True, "")
            mock_git.commit.return_value = False
            mock_github.get_pr_for_branch.return_value = None

            result = rebase_start_command()

        assert result == 2
        captured = capsys.readouterr()
        assert "Error creating squashed commit" in captured.err

    def test_returns_one_on_conflicts(self, tmp_path: Path, capsys) -> None:
        """Should return 1 when rebase has conflicts."""
        with (
            patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_start_command.github_dao") as mock_github,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "feature"
            mock_git.create_shared_clone.return_value = (True, "")
            mock_git.fetch_branch.return_value = (True, "")
            mock_git.get_merge_base.return_value = ("abc123", "")
            mock_git.get_commits_between.return_value = ["def456"]
            mock_git.count_commits_ahead.return_value = (1, "")
            mock_git.rebase.return_value = (False, True, "Conflict!")
            mock_git.get_conflicted_files.return_value = ["file1.py", "file2.py"]
            mock_git.get_head_sha.return_value = "head123"
            mock_github.get_pr_for_branch.return_value = None

            result = rebase_start_command()

        assert result == 1
        captured = capsys.readouterr()
        assert "Rebase conflicts detected" in captured.err
        stdout_json = json.loads(captured.out)
        assert stdout_json["has_conflicts"] is True
        assert stdout_json["conflicted_files"] == ["file1.py", "file2.py"]

    def test_returns_error_when_rebase_fails_no_conflicts(self, tmp_path: Path, capsys) -> None:
        """Should return 2 when rebase fails without conflicts."""
        with (
            patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_start_command.github_dao") as mock_github,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "feature"
            mock_git.create_shared_clone.return_value = (True, "")
            mock_git.fetch_branch.return_value = (True, "")
            mock_git.get_merge_base.return_value = ("abc123", "")
            mock_git.get_commits_between.return_value = []
            mock_git.count_commits_ahead.return_value = (1, "")
            mock_git.rebase.return_value = (False, False, "Unknown rebase error")
            mock_github.get_pr_for_branch.return_value = None

            result = rebase_start_command()

        assert result == 2
        captured = capsys.readouterr()
        assert "Error during rebase" in captured.err

    def test_uses_pr_info_for_pr_identifier(self, tmp_path: Path) -> None:
        """Should fetch PR info when identifier is a PR number."""
        with (
            patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_start_command.github_dao") as mock_github,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "pr-branch"
            mock_git.create_shared_clone.return_value = (True, "")
            mock_git.fetch_branch.return_value = (True, "")
            mock_git.get_merge_base.return_value = ("abc123", "")
            mock_git.get_commits_between.return_value = []
            mock_git.count_commits_ahead.return_value = (1, "")
            mock_git.rebase.return_value = (True, False, "")
            mock_github.get_pr_info.return_value = {
                "head_branch": "pr-branch",
                "base_branch": "develop",
            }

            result = rebase_start_command(identifier="#42")

        assert result == 0
        mock_github.get_pr_info.assert_called_once_with(42)

    def test_returns_error_when_pr_has_no_branch(self, tmp_path: Path, capsys) -> None:
        """Should return 2 when PR has no head branch."""
        with (
            patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_start_command.github_dao") as mock_github,
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "main"
            mock_github.get_pr_info.return_value = {"head_branch": None}

            result = rebase_start_command(identifier="42")

        assert result == 2
        captured = capsys.readouterr()
        assert "Could not determine head branch for PR" in captured.err

    def test_uses_ticket_info_for_ticket_identifier(self, tmp_path: Path) -> None:
        """Should fetch ticket info when identifier is a ticket ID."""
        with (
            patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_start_command.github_dao"),
            patch("scripts.pr.commands.rebase_start_command._get_default_client") as mock_linear,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "nes-87-fix-bug"
            mock_git.branch_exists.return_value = True
            mock_git.create_shared_clone.return_value = (True, "")
            mock_git.fetch_branch.return_value = (True, "")
            mock_git.get_merge_base.return_value = ("abc123", "")
            mock_git.get_commits_between.return_value = []
            mock_git.count_commits_ahead.return_value = (1, "")
            mock_git.rebase.return_value = (True, False, "")

            mock_client = MagicMock()
            mock_client.get_ticket_info.return_value = {"branch_name": "nes-87-fix-bug"}
            mock_client.fetch_github_attachments.return_value = []
            mock_linear.return_value = mock_client

            result = rebase_start_command(identifier="NES-87")

        assert result == 0
        mock_client.get_ticket_info.assert_called_once_with("NES-87")

    def test_returns_error_when_no_branch_for_ticket(self, tmp_path: Path, capsys) -> None:
        """Should return 2 when ticket has no branch name."""
        with (
            patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_start_command._get_default_client") as mock_linear,
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "main"

            mock_client = MagicMock()
            mock_client.get_ticket_info.return_value = {"branch_name": None}
            mock_linear.return_value = mock_client

            result = rebase_start_command(identifier="NES-88")

        assert result == 2
        captured = capsys.readouterr()
        assert "No branch name configured for ticket" in captured.err

    def test_handles_linear_client_error(self, tmp_path: Path, capsys) -> None:
        """Should return 2 on LinearClientError."""
        from scripts.clients.linear_client import LinearClientError

        with (
            patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_start_command._get_default_client") as mock_linear,
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "main"

            mock_linear.side_effect = LinearClientError("API_ERROR", "API error")

            result = rebase_start_command(identifier="NES-99")

        assert result == 2
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    def test_handles_graphql_error(self, tmp_path: Path, capsys) -> None:
        """Should return 2 on GraphQLError."""
        from scripts.pr import github_dao
        from scripts.pr.github_dao import GraphQLError

        with (
            patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git,
            patch.object(github_dao, "get_pr_info") as mock_get_pr_info,
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "main"
            mock_get_pr_info.side_effect = GraphQLError("API error")

            result = rebase_start_command(identifier="#42")

        assert result == 2
        captured = capsys.readouterr()
        assert "Error fetching PR info from GitHub" in captured.err

    def test_completes_full_workflow_success(self, tmp_path: Path, capsys) -> None:
        """Should complete full rebase workflow successfully."""
        with (
            patch("scripts.pr.commands.rebase_start_command.git_dao") as mock_git,
            patch("scripts.pr.commands.rebase_start_command.github_dao") as mock_github,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_git.get_repo_root.return_value = tmp_path
            mock_git.get_current_branch.return_value = "feature"
            mock_git.create_shared_clone.return_value = (True, "")
            mock_git.fetch_branch.return_value = (True, "")
            mock_git.get_merge_base.return_value = ("abc123", "")
            mock_git.get_commits_between.return_value = ["def456"]
            mock_git.count_commits_ahead.return_value = (1, "")
            mock_git.rebase.return_value = (True, False, "")
            mock_github.get_pr_for_branch.return_value = {"pr_number": 42, "base_branch": "main"}

            result = rebase_start_command()

        assert result == 0
        captured = capsys.readouterr()
        assert "Squash and rebase completed successfully" in captured.err
        stdout_json = json.loads(captured.out)
        assert stdout_json["has_conflicts"] is False
        assert stdout_json["branch_name"] == "feature"
        assert stdout_json["base_branch"] == "main"
        assert stdout_json["pr_number"] == 42
