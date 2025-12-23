"""Tests for scripts/dev/commands/update_plan.py - run function."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.clients.linear_client import LinearClientError
from scripts.dev.commands.update_plan import run


class TestUpdatePlanRun:
    """Tests for the run function covering lines 38-142."""

    def test_returns_error_when_ticket_validation_fails(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test run returns 1 when ticket validation fails (lines 55-59)."""
        with patch("scripts.dev.commands.update_plan.LinearClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get_issue.side_effect = LinearClientError("NOT_FOUND", "Ticket not found")
            mock_client_class.return_value = mock_client

            result = run("NES-999")

            assert result == 1
            captured = capsys.readouterr()
            assert "Ticket validation failed" in captured.err

    def test_returns_error_when_ticket_has_no_description(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test run returns 1 when ticket has no description (lines 67-70)."""
        with (
            patch("scripts.dev.commands.update_plan.LinearClient") as mock_client_class,
            patch("scripts.dev.commands.update_plan.TMP_DIR", tmp_path),
        ):
            mock_client = MagicMock()
            mock_client.get_issue.return_value = {"title": "Test Ticket", "description": ""}
            mock_client_class.return_value = mock_client

            result = run("NES-100")

            assert result == 1
            captured = capsys.readouterr()
            assert "no description" in captured.err
            assert "create-plan" in captured.err

    def test_returns_zero_when_no_unresolved_comments(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test run returns 0 when no unresolved comments (lines 87-89)."""
        with (
            patch("scripts.dev.commands.update_plan.LinearClient") as mock_client_class,
            patch("scripts.dev.commands.update_plan.TMP_DIR", tmp_path),
            patch("scripts.dev.commands.update_plan._fetch_unresolved_comments") as mock_fetch,
        ):
            mock_client = MagicMock()
            mock_client.get_issue.return_value = {
                "title": "Test Ticket",
                "description": "Some description",
            }
            mock_client_class.return_value = mock_client
            mock_fetch.return_value = None  # No comments

            result = run("NES-100")

            assert result == 0
            captured = capsys.readouterr()
            assert "No unresolved comments" in captured.err

    def test_returns_zero_when_no_comments_extracted(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test run returns 0 when no comments extracted (lines 95-97)."""
        with (
            patch("scripts.dev.commands.update_plan.LinearClient") as mock_client_class,
            patch("scripts.dev.commands.update_plan.TMP_DIR", tmp_path),
            patch("scripts.dev.commands.update_plan._fetch_unresolved_comments") as mock_fetch,
            patch("scripts.dev.commands.update_plan.parse_comments_with_haiku") as mock_parse,
        ):
            mock_client = MagicMock()
            mock_client.get_issue.return_value = {
                "title": "Test Ticket",
                "description": "Some description",
            }
            mock_client_class.return_value = mock_client
            mock_fetch.return_value = {"totalCount": 1, "comments": []}
            mock_parse.return_value = []  # No comments extracted

            result = run("NES-100")

            assert result == 0
            captured = capsys.readouterr()
            assert "No comments extracted" in captured.err

    def test_returns_error_when_planner_fails(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test run returns 1 when planner fails (lines 112-114)."""
        with (
            patch("scripts.dev.commands.update_plan.LinearClient") as mock_client_class,
            patch("scripts.dev.commands.update_plan.TMP_DIR", tmp_path),
            patch("scripts.dev.commands.update_plan.invoke_planner") as mock_planner,
        ):
            mock_client = MagicMock()
            mock_client.get_issue.return_value = {
                "title": "Test Ticket",
                "description": "Some description",
            }
            mock_client_class.return_value = mock_client
            mock_planner.return_value = (1, "", "Planner error")  # Non-zero exit

            result = run("NES-100", update_prompt="Fix the tests")

            assert result == 1
            captured = capsys.readouterr()
            assert "Planner failed" in captured.err

    def test_uses_provided_update_prompt(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test run uses provided update_prompt instead of fetching comments (line 78-81)."""
        with (
            patch("scripts.dev.commands.update_plan.LinearClient") as mock_client_class,
            patch("scripts.dev.commands.update_plan.TMP_DIR", tmp_path),
            patch("scripts.dev.commands.update_plan.invoke_planner") as mock_planner,
            patch("scripts.dev.commands.update_plan._update_ticket_from_file"),
            patch("scripts.dev.commands.update_plan._post_update_comment"),
        ):
            mock_client = MagicMock()
            mock_client.get_issue.return_value = {
                "title": "Test Ticket",
                "description": "Some description",
            }
            mock_client_class.return_value = mock_client
            mock_planner.return_value = (0, "Updated plan", "")

            result = run("NES-100", update_prompt="Add error handling")

            assert result == 0
            captured = capsys.readouterr()
            assert "Using provided update prompt" in captured.err
            # Planner should be called with the prompt
            mock_planner.assert_called_once()
            call_args = mock_planner.call_args[0][0]
            assert "Add error handling" in call_args

    def test_returns_error_on_exception(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test run returns 1 on unexpected exception (lines 134-136)."""
        with (
            patch("scripts.dev.commands.update_plan.LinearClient") as mock_client_class,
            patch("scripts.dev.commands.update_plan.TMP_DIR", tmp_path),
            patch("scripts.dev.commands.update_plan.invoke_planner") as mock_planner,
        ):
            mock_client = MagicMock()
            mock_client.get_issue.return_value = {
                "title": "Test Ticket",
                "description": "Some description",
            }
            mock_client_class.return_value = mock_client
            mock_planner.side_effect = RuntimeError("Unexpected error")

            result = run("NES-100", update_prompt="Fix tests")

            assert result == 1
            captured = capsys.readouterr()
            assert "Error:" in captured.err

    def test_cleanup_removes_temp_file(self, tmp_path: Path) -> None:
        """Test run cleans up temp file in finally block (lines 139-142)."""
        with (
            patch("scripts.dev.commands.update_plan.LinearClient") as mock_client_class,
            patch("scripts.dev.commands.update_plan.TMP_DIR", tmp_path),
        ):
            mock_client = MagicMock()
            mock_client.get_issue.return_value = {
                "title": "Test Ticket",
                "description": "Some description",
            }
            mock_client_class.return_value = mock_client

            # Let it fail after creating the temp file
            with patch(
                "scripts.dev.commands.update_plan._fetch_unresolved_comments",
                return_value=None,
            ):
                run("NES-100")

            # Temp file should be cleaned up
            expected_file = tmp_path / "NES-100.md"
            assert not expected_file.exists()

    def test_successful_workflow_with_multiple_comments(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test successful run with multiple comments (lines 101-132)."""
        with (
            patch("scripts.dev.commands.update_plan.LinearClient") as mock_client_class,
            patch("scripts.dev.commands.update_plan.TMP_DIR", tmp_path),
            patch("scripts.dev.commands.update_plan._fetch_unresolved_comments") as mock_fetch,
            patch("scripts.dev.commands.update_plan.parse_comments_with_haiku") as mock_parse,
            patch("scripts.dev.commands.update_plan.invoke_planner") as mock_planner,
            patch("scripts.dev.commands.update_plan._update_ticket_from_file") as mock_update,
            patch("scripts.dev.commands.update_plan._post_update_comment") as mock_post,
            patch("scripts.dev.commands.update_plan._create_combined_summary") as mock_combine,
        ):
            mock_client = MagicMock()
            mock_client.get_issue.return_value = {
                "title": "Test Ticket",
                "description": "Some description",
            }
            mock_client_class.return_value = mock_client
            mock_fetch.return_value = {"totalCount": 2, "comments": ["c1", "c2"]}
            mock_parse.return_value = ["Comment 1", "Comment 2"]
            mock_planner.return_value = (0, "Summary", "")
            mock_combine.return_value = "Combined summary"

            result = run("NES-100")

            assert result == 0
            assert mock_planner.call_count == 2
            mock_update.assert_called_once()
            mock_post.assert_called_once()

    def test_default_summary_when_planner_output_empty(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test default summary is used when planner output is empty (line 117)."""
        with (
            patch("scripts.dev.commands.update_plan.LinearClient") as mock_client_class,
            patch("scripts.dev.commands.update_plan.TMP_DIR", tmp_path),
            patch("scripts.dev.commands.update_plan.invoke_planner") as mock_planner,
            patch("scripts.dev.commands.update_plan._update_ticket_from_file"),
            patch("scripts.dev.commands.update_plan._post_update_comment"),
        ):
            mock_client = MagicMock()
            mock_client.get_issue.return_value = {
                "title": "Test Ticket",
                "description": "Some description",
            }
            mock_client_class.return_value = mock_client
            mock_planner.return_value = (0, "", "")  # Empty output

            result = run("NES-100", update_prompt="Fix tests")

            assert result == 0
            # Should use default summary "Update 1 applied"
            captured = capsys.readouterr()
            assert "Update 1 complete" in captured.err
