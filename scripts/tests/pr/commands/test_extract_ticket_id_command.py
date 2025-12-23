"""Tests for scripts/pr/commands/extract_ticket_id_command.py."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.pr.commands.extract_ticket_id_command import extract_ticket_id_command


class TestExtractTicketIdCommand:
    """Tests for extract_ticket_id_command() function."""

    def test_no_branch_name_not_on_branch(self, capsys: pytest.CaptureFixture) -> None:
        """Test when no branch name provided and not on a branch."""
        with patch("scripts.pr.git_dao.get_current_branch", return_value=None):
            result = extract_ticket_id_command(None)

        assert result == 1
        captured = capsys.readouterr()
        assert "Not on a branch" in captured.err

    def test_no_ticket_id_pattern_found(self, capsys: pytest.CaptureFixture) -> None:
        """Test when branch name has no ticket ID pattern."""
        with patch(
            "scripts.pr.commands.extract_ticket_id_command._extract_ticket_id_from_branch",
            return_value=None,
        ):
            result = extract_ticket_id_command("main")

        assert result == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["branch_name"] == "main"
        assert output["ticket_id"] is None
        assert output["valid"] is False
        assert "No ticket ID pattern found" in output["reason"]

    def test_ticket_id_found_and_valid(self, capsys: pytest.CaptureFixture) -> None:
        """Test when ticket ID is found and validated against Linear."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"title": "Fix bug in parser"}

        with (
            patch(
                "scripts.pr.commands.extract_ticket_id_command._extract_ticket_id_from_branch",
                return_value="NES-123",
            ),
            patch(
                "scripts.pr.commands.extract_ticket_id_command._get_default_client",
                return_value=mock_client,
            ),
        ):
            result = extract_ticket_id_command("mrasolomon/nes-123-fix-bug")

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["branch_name"] == "mrasolomon/nes-123-fix-bug"
        assert output["ticket_id"] == "NES-123"
        assert output["valid"] is True
        assert output["ticket_title"] == "Fix bug in parser"

    def test_ticket_id_found_but_not_in_linear(self, capsys: pytest.CaptureFixture) -> None:
        """Test when ticket ID is found but doesn't exist in Linear."""
        from scripts.clients.linear_client import LinearClientError

        mock_client = MagicMock()
        mock_client.get_ticket_info.side_effect = LinearClientError("NOT_FOUND", "Not found")

        with (
            patch(
                "scripts.pr.commands.extract_ticket_id_command._extract_ticket_id_from_branch",
                return_value="NES-999",
            ),
            patch(
                "scripts.pr.commands.extract_ticket_id_command._get_default_client",
                return_value=mock_client,
            ),
        ):
            result = extract_ticket_id_command("nes-999-nonexistent")

        assert result == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["branch_name"] == "nes-999-nonexistent"
        assert output["ticket_id"] == "NES-999"
        assert output["valid"] is False
        assert "not found in Linear" in output["reason"]

    def test_uses_current_branch_when_none_provided(self, capsys: pytest.CaptureFixture) -> None:
        """Test that current branch is used when no branch name provided."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"title": "Feature"}

        with (
            patch("scripts.pr.git_dao.get_current_branch", return_value="nes-456-feature"),
            patch(
                "scripts.pr.commands.extract_ticket_id_command._extract_ticket_id_from_branch",
                return_value="NES-456",
            ),
            patch(
                "scripts.pr.commands.extract_ticket_id_command._get_default_client",
                return_value=mock_client,
            ),
        ):
            result = extract_ticket_id_command(None)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["branch_name"] == "nes-456-feature"
        assert output["ticket_id"] == "NES-456"

    def test_branch_with_path_prefix(self, capsys: pytest.CaptureFixture) -> None:
        """Test extracting ticket ID from branch with path prefix."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"title": "Bug fix"}

        with (
            patch(
                "scripts.pr.commands.extract_ticket_id_command._extract_ticket_id_from_branch",
                return_value="PROJ-789",
            ),
            patch(
                "scripts.pr.commands.extract_ticket_id_command._get_default_client",
                return_value=mock_client,
            ),
        ):
            result = extract_ticket_id_command("feature/proj-789-bug-fix")

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ticket_id"] == "PROJ-789"
        assert output["valid"] is True

    def test_provided_branch_name_used(self, capsys: pytest.CaptureFixture) -> None:
        """Test that provided branch name is used instead of current branch."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"title": "Test"}

        with patch("scripts.pr.git_dao.get_current_branch") as mock_current:
            with (
                patch(
                    "scripts.pr.commands.extract_ticket_id_command._extract_ticket_id_from_branch",
                    return_value="ABC-111",
                ),
                patch(
                    "scripts.pr.commands.extract_ticket_id_command._get_default_client",
                    return_value=mock_client,
                ),
            ):
                result = extract_ticket_id_command("abc-111-test")

            # get_current_branch should not be called when branch_name is provided
            mock_current.assert_not_called()

        assert result == 0
