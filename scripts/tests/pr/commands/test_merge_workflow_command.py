"""Tests for merge_workflow_command module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.pr.commands.merge_workflow_command import merge_workflow_command


class TestMergeWorkflowCommandBasic:
    """Basic tests for merge_workflow_command."""

    def test_success_returns_zero(self, tmp_path: Path) -> None:
        """Test successful workflow returns 0."""
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        with (
            patch("scripts.pr.commands.merge_workflow_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.merge_workflow_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_open_prs_for_ticket"
            ) as mock_prs,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_default_client"
            ) as mock_client_fn,
        ):
            mock_gh.merge_pr.return_value = True
            mock_git.remove_worktree.return_value = (True, "")
            mock_git.delete_branch.return_value = (True, "")
            mock_prs.return_value = []
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.get_ticket_info.return_value = {"team_id": "team-1", "id": "uuid-1"}
            mock_client.get_done_state_id.return_value = "done-state-1"

            result = merge_workflow_command(
                "NES-123", 42, working_dir, "feature-branch", "main", is_worktree=True
            )

        assert result == 0

    def test_merge_failure_returns_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that merge failure returns 1."""
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        with patch("scripts.pr.commands.merge_workflow_command.github_dao") as mock_gh:
            mock_gh.merge_pr.return_value = False

            result = merge_workflow_command("NES-123", 42, working_dir, "feature-branch", "main")

        captured = capsys.readouterr()
        assert "Error merging PR" in captured.err
        assert result == 1


class TestMergeWorkflowCommandWorktree:
    """Tests for worktree handling in merge_workflow_command."""

    def test_removes_worktree_when_is_worktree_true(self, tmp_path: Path) -> None:
        """Test that worktree is removed when is_worktree=True."""
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        with (
            patch("scripts.pr.commands.merge_workflow_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.merge_workflow_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_open_prs_for_ticket"
            ) as mock_prs,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_default_client"
            ) as mock_client_fn,
        ):
            mock_gh.merge_pr.return_value = True
            mock_git.remove_worktree.return_value = (True, "")
            mock_git.delete_branch.return_value = (True, "")
            mock_prs.return_value = []
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.get_ticket_info.return_value = {"team_id": "team-1", "id": "uuid-1"}
            mock_client.get_done_state_id.return_value = "done-state-1"

            merge_workflow_command(
                "NES-123", 42, working_dir, "feature-branch", "main", is_worktree=True
            )

        mock_git.remove_worktree.assert_called_once_with(working_dir)

    def test_skips_worktree_removal_when_is_worktree_false(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that worktree removal is skipped when is_worktree=False."""
        working_dir = tmp_path / "repo"
        working_dir.mkdir()

        with (
            patch("scripts.pr.commands.merge_workflow_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.merge_workflow_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_open_prs_for_ticket"
            ) as mock_prs,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_default_client"
            ) as mock_client_fn,
        ):
            mock_gh.merge_pr.return_value = True
            mock_prs.return_value = []
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.get_ticket_info.return_value = {"team_id": "team-1", "id": "uuid-1"}
            mock_client.get_done_state_id.return_value = "done-state-1"

            merge_workflow_command(
                "NES-123", 42, working_dir, "feature-branch", "main", is_worktree=False
            )

        mock_git.remove_worktree.assert_not_called()
        mock_git.delete_branch.assert_not_called()
        captured = capsys.readouterr()
        assert "Skipping worktree removal" in captured.out
        assert "Skipping branch deletion" in captured.out

    def test_handles_worktree_removal_failure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that worktree removal failure is reported but doesn't stop workflow."""
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        with (
            patch("scripts.pr.commands.merge_workflow_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.merge_workflow_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_open_prs_for_ticket"
            ) as mock_prs,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_default_client"
            ) as mock_client_fn,
        ):
            mock_gh.merge_pr.return_value = True
            mock_git.remove_worktree.return_value = (False, "Worktree locked")
            mock_git.delete_branch.return_value = (True, "")
            mock_prs.return_value = []
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.get_ticket_info.return_value = {"team_id": "team-1", "id": "uuid-1"}
            mock_client.get_done_state_id.return_value = "done-state-1"

            result = merge_workflow_command(
                "NES-123", 42, working_dir, "feature-branch", "main", is_worktree=True
            )

        captured = capsys.readouterr()
        assert "Failed to remove worktree" in captured.err
        assert result == 0  # Still succeeds

    def test_handles_missing_worktree_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test handling when worktree directory doesn't exist."""
        working_dir = tmp_path / "nonexistent"  # Doesn't exist

        with (
            patch("scripts.pr.commands.merge_workflow_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.merge_workflow_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_open_prs_for_ticket"
            ) as mock_prs,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_default_client"
            ) as mock_client_fn,
        ):
            mock_gh.merge_pr.return_value = True
            mock_git.delete_branch.return_value = (True, "")
            mock_prs.return_value = []
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.get_ticket_info.return_value = {"team_id": "team-1", "id": "uuid-1"}
            mock_client.get_done_state_id.return_value = "done-state-1"

            result = merge_workflow_command(
                "NES-123", 42, working_dir, "feature-branch", "main", is_worktree=True
            )

        captured = capsys.readouterr()
        assert "Worktree not found" in captured.out
        mock_git.remove_worktree.assert_not_called()
        assert result == 0


class TestMergeWorkflowCommandBranchDeletion:
    """Tests for branch deletion in merge_workflow_command."""

    def test_deletes_branch_when_is_worktree_true(self, tmp_path: Path) -> None:
        """Test that branch is deleted when is_worktree=True."""
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        with (
            patch("scripts.pr.commands.merge_workflow_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.merge_workflow_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_open_prs_for_ticket"
            ) as mock_prs,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_default_client"
            ) as mock_client_fn,
        ):
            mock_gh.merge_pr.return_value = True
            mock_git.remove_worktree.return_value = (True, "")
            mock_git.delete_branch.return_value = (True, "")
            mock_prs.return_value = []
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.get_ticket_info.return_value = {"team_id": "team-1", "id": "uuid-1"}
            mock_client.get_done_state_id.return_value = "done-state-1"

            merge_workflow_command(
                "NES-123", 42, working_dir, "my-feature", "main", is_worktree=True
            )

        mock_git.delete_branch.assert_called_once_with("my-feature")

    def test_handles_branch_deletion_failure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that branch deletion failure is reported but doesn't stop workflow."""
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        with (
            patch("scripts.pr.commands.merge_workflow_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.merge_workflow_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_open_prs_for_ticket"
            ) as mock_prs,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_default_client"
            ) as mock_client_fn,
        ):
            mock_gh.merge_pr.return_value = True
            mock_git.remove_worktree.return_value = (True, "")
            mock_git.delete_branch.return_value = (False, "Branch not found")
            mock_prs.return_value = []
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.get_ticket_info.return_value = {"team_id": "team-1", "id": "uuid-1"}
            mock_client.get_done_state_id.return_value = "done-state-1"

            result = merge_workflow_command(
                "NES-123", 42, working_dir, "feature-branch", "main", is_worktree=True
            )

        captured = capsys.readouterr()
        assert "Failed to delete branch" in captured.err
        assert result == 0


class TestMergeWorkflowCommandFetchPrune:
    """Tests for fetch and prune in merge_workflow_command."""

    def test_fetches_and_prunes_remote_branches(self, tmp_path: Path) -> None:
        """Test that remote branches are fetched and pruned."""
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        with (
            patch("scripts.pr.commands.merge_workflow_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.merge_workflow_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_open_prs_for_ticket"
            ) as mock_prs,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_default_client"
            ) as mock_client_fn,
        ):
            mock_gh.merge_pr.return_value = True
            mock_git.remove_worktree.return_value = (True, "")
            mock_git.delete_branch.return_value = (True, "")
            mock_prs.return_value = []
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.get_ticket_info.return_value = {"team_id": "team-1", "id": "uuid-1"}
            mock_client.get_done_state_id.return_value = "done-state-1"

            merge_workflow_command(
                "NES-123", 42, working_dir, "feature-branch", "main", is_worktree=True
            )

        mock_git.fetch_all_prune.assert_called_once()


class TestMergeWorkflowCommandTicketState:
    """Tests for ticket state updates in merge_workflow_command."""

    def test_skips_ticket_operations_when_no_ticket_id(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that ticket operations are skipped when ticket_id is None."""
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        with (
            patch("scripts.pr.commands.merge_workflow_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.merge_workflow_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_open_prs_for_ticket"
            ) as mock_prs,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_default_client"
            ) as mock_client_fn,
        ):
            mock_gh.merge_pr.return_value = True
            mock_git.remove_worktree.return_value = (True, "")
            mock_git.delete_branch.return_value = (True, "")

            result = merge_workflow_command(
                None, 42, working_dir, "feature-branch", "main", is_worktree=True
            )

        captured = capsys.readouterr()
        assert "Skipping ticket operations (no ticket ID provided)" in captured.out
        mock_prs.assert_not_called()
        assert result == 0

    def test_marks_ticket_done_when_no_remaining_prs(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that ticket is marked Done when no remaining open PRs."""
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        with (
            patch("scripts.pr.commands.merge_workflow_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.merge_workflow_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_open_prs_for_ticket"
            ) as mock_prs,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_default_client"
            ) as mock_client_fn,
        ):
            mock_gh.merge_pr.return_value = True
            mock_git.remove_worktree.return_value = (True, "")
            mock_git.delete_branch.return_value = (True, "")
            mock_prs.return_value = []  # No remaining PRs
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.get_ticket_info.return_value = {"team_id": "team-1", "id": "uuid-123"}
            mock_client.get_done_state_id.return_value = "done-state-1"

            result = merge_workflow_command(
                "NES-123", 42, working_dir, "feature-branch", "main", is_worktree=True
            )

        mock_client.set_ticket_state.assert_called_once_with("uuid-123", "done-state-1")
        captured = capsys.readouterr()
        assert "Marked NES-123 as Done" in captured.out
        assert result == 0

    def test_skips_mark_done_when_remaining_prs(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that ticket is not marked Done when there are remaining open PRs."""
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        with (
            patch("scripts.pr.commands.merge_workflow_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.merge_workflow_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_open_prs_for_ticket"
            ) as mock_prs,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_default_client"
            ) as mock_client_fn,
        ):
            mock_gh.merge_pr.return_value = True
            mock_git.remove_worktree.return_value = (True, "")
            mock_git.delete_branch.return_value = (True, "")
            mock_prs.return_value = [
                {"number": 43, "url": "https://github.com/owner/repo/pull/43"},
            ]
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client

            result = merge_workflow_command(
                "NES-123", 42, working_dir, "feature-branch", "main", is_worktree=True
            )

        mock_client.set_ticket_state.assert_not_called()
        captured = capsys.readouterr()
        assert "has 1 remaining open PR(s)" in captured.out
        assert "Next open PR: #43" in captured.out
        assert result == 0

    def test_handles_linear_client_error_in_pr_check(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that LinearClientError in PR check is reported but doesn't stop workflow."""
        from scripts.clients.linear_client import LinearClientError

        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        with (
            patch("scripts.pr.commands.merge_workflow_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.merge_workflow_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_open_prs_for_ticket"
            ) as mock_prs,
        ):
            mock_gh.merge_pr.return_value = True
            mock_git.remove_worktree.return_value = (True, "")
            mock_git.delete_branch.return_value = (True, "")
            mock_prs.side_effect = LinearClientError("API_ERROR", "Connection failed")

            result = merge_workflow_command(
                "NES-123", 42, working_dir, "feature-branch", "main", is_worktree=True
            )

        captured = capsys.readouterr()
        assert "Error checking remaining PRs" in captured.err
        assert result == 0

    def test_handles_missing_team_id(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test handling when team_id is not available."""
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        with (
            patch("scripts.pr.commands.merge_workflow_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.merge_workflow_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_open_prs_for_ticket"
            ) as mock_prs,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_default_client"
            ) as mock_client_fn,
        ):
            mock_gh.merge_pr.return_value = True
            mock_git.remove_worktree.return_value = (True, "")
            mock_git.delete_branch.return_value = (True, "")
            mock_prs.return_value = []
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.get_ticket_info.return_value = {"team_id": None, "id": "uuid-123"}

            result = merge_workflow_command(
                "NES-123", 42, working_dir, "feature-branch", "main", is_worktree=True
            )

        captured = capsys.readouterr()
        assert "Could not get team ID" in captured.err
        assert result == 0

    def test_handles_missing_issue_uuid(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test handling when issue UUID is not available."""
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        with (
            patch("scripts.pr.commands.merge_workflow_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.merge_workflow_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_open_prs_for_ticket"
            ) as mock_prs,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_default_client"
            ) as mock_client_fn,
        ):
            mock_gh.merge_pr.return_value = True
            mock_git.remove_worktree.return_value = (True, "")
            mock_git.delete_branch.return_value = (True, "")
            mock_prs.return_value = []
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.get_ticket_info.return_value = {"team_id": "team-1", "id": None}
            mock_client.get_done_state_id.return_value = "done-state-1"

            result = merge_workflow_command(
                "NES-123", 42, working_dir, "feature-branch", "main", is_worktree=True
            )

        captured = capsys.readouterr()
        assert "Could not get issue UUID" in captured.err
        assert result == 0

    def test_handles_linear_client_error_in_set_state(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that LinearClientError when setting state is reported."""
        from scripts.clients.linear_client import LinearClientError

        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        with (
            patch("scripts.pr.commands.merge_workflow_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.merge_workflow_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_open_prs_for_ticket"
            ) as mock_prs,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_default_client"
            ) as mock_client_fn,
        ):
            mock_gh.merge_pr.return_value = True
            mock_git.remove_worktree.return_value = (True, "")
            mock_git.delete_branch.return_value = (True, "")
            mock_prs.return_value = []
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.get_ticket_info.return_value = {"team_id": "team-1", "id": "uuid-123"}
            mock_client.get_done_state_id.side_effect = LinearClientError(
                "NOT_FOUND", "Team not found"
            )

            result = merge_workflow_command(
                "NES-123", 42, working_dir, "feature-branch", "main", is_worktree=True
            )

        captured = capsys.readouterr()
        assert "Linear API error" in captured.err
        assert result == 0


class TestMergeWorkflowCommandSummary:
    """Tests for summary output in merge_workflow_command."""

    def test_prints_summary(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that summary is printed at the end."""
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        with (
            patch("scripts.pr.commands.merge_workflow_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.merge_workflow_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_open_prs_for_ticket"
            ) as mock_prs,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_default_client"
            ) as mock_client_fn,
        ):
            mock_gh.merge_pr.return_value = True
            mock_git.remove_worktree.return_value = (True, "")
            mock_git.delete_branch.return_value = (True, "")
            mock_prs.return_value = []
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.get_ticket_info.return_value = {"team_id": "team-1", "id": "uuid-1"}
            mock_client.get_done_state_id.return_value = "done-state-1"

            merge_workflow_command(
                "NES-456", 99, working_dir, "my-branch", "develop", is_worktree=True
            )

        captured = capsys.readouterr()
        assert "MERGE WORKFLOW COMPLETE" in captured.out
        assert "Ticket: NES-456" in captured.out
        assert "PR: #99" in captured.out
        assert "Branch: my-branch" in captured.out
        assert "Target: develop" in captured.out

    def test_prints_warnings_in_summary(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that warnings are printed in summary."""
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        with (
            patch("scripts.pr.commands.merge_workflow_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.merge_workflow_command.git_dao") as mock_git,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_open_prs_for_ticket"
            ) as mock_prs,
            patch(
                "scripts.pr.commands.merge_workflow_command._get_default_client"
            ) as mock_client_fn,
        ):
            mock_gh.merge_pr.return_value = True
            mock_git.remove_worktree.return_value = (False, "Error 1")
            mock_git.delete_branch.return_value = (False, "Error 2")
            mock_prs.return_value = []
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.get_ticket_info.return_value = {"team_id": "team-1", "id": "uuid-1"}
            mock_client.get_done_state_id.return_value = "done-state-1"

            merge_workflow_command("NES-123", 42, working_dir, "feature", "main", is_worktree=True)

        captured = capsys.readouterr()
        assert "Warnings (2)" in captured.out
        assert "Failed to remove worktree" in captured.out
        assert "Failed to delete branch" in captured.out

    def test_summary_shows_na_for_no_ticket(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that summary shows N/A when no ticket ID."""
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        with (
            patch("scripts.pr.commands.merge_workflow_command.github_dao") as mock_gh,
            patch("scripts.pr.commands.merge_workflow_command.git_dao") as mock_git,
        ):
            mock_gh.merge_pr.return_value = True
            mock_git.remove_worktree.return_value = (True, "")
            mock_git.delete_branch.return_value = (True, "")

            merge_workflow_command(None, 42, working_dir, "feature", "main", is_worktree=True)

        captured = capsys.readouterr()
        assert "Ticket: N/A" in captured.out
