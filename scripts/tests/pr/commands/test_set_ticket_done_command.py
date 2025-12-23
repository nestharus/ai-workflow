"""Tests for set_ticket_done_command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.clients.linear_client import LinearClientError
from scripts.pr.commands.set_ticket_done_command import set_ticket_done_command


class TestSetTicketDoneCommand:
    """Tests for set_ticket_done_command function."""

    def test_success_marks_ticket_done(self) -> None:
        """Should return 0 and print success message when ticket is marked done."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {
            "id": "issue-uuid-123",
            "team_id": "team-uuid-456",
        }
        mock_client.get_done_state_id.return_value = "done-state-id"
        mock_client.set_ticket_state.return_value = {"stateName": "Done"}

        with patch(
            "scripts.pr.commands.set_ticket_done_command._get_default_client",
            return_value=mock_client,
        ):
            result = set_ticket_done_command("NES-123")

        assert result == 0
        mock_client.get_ticket_info.assert_called_once_with("NES-123")
        mock_client.get_done_state_id.assert_called_once_with("team-uuid-456")
        mock_client.set_ticket_state.assert_called_once_with("issue-uuid-123", "done-state-id")

    def test_missing_team_id_returns_error(self) -> None:
        """Should return 1 when team_id is missing from ticket info."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {
            "id": "issue-uuid-123",
            "team_id": None,  # Missing team_id
        }

        with patch(
            "scripts.pr.commands.set_ticket_done_command._get_default_client",
            return_value=mock_client,
        ):
            result = set_ticket_done_command("NES-123")

        assert result == 1
        mock_client.get_done_state_id.assert_not_called()
        mock_client.set_ticket_state.assert_not_called()

    def test_missing_issue_uuid_returns_error(self) -> None:
        """Should return 1 when issue UUID is missing from ticket info."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {
            "id": None,  # Missing issue UUID
            "team_id": "team-uuid-456",
        }
        mock_client.get_done_state_id.return_value = "done-state-id"

        with patch(
            "scripts.pr.commands.set_ticket_done_command._get_default_client",
            return_value=mock_client,
        ):
            result = set_ticket_done_command("NES-123")

        assert result == 1
        mock_client.set_ticket_state.assert_not_called()

    def test_linear_client_error_returns_error(self) -> None:
        """Should return 1 when LinearClientError is raised."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.side_effect = LinearClientError(
            "NOT_FOUND", "Ticket not found: NES-999"
        )

        with patch(
            "scripts.pr.commands.set_ticket_done_command._get_default_client",
            return_value=mock_client,
        ):
            result = set_ticket_done_command("NES-999")

        assert result == 1

    def test_empty_team_id_string_returns_error(self) -> None:
        """Should return 1 when team_id is an empty string."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {
            "id": "issue-uuid-123",
            "team_id": "",  # Empty string
        }

        with patch(
            "scripts.pr.commands.set_ticket_done_command._get_default_client",
            return_value=mock_client,
        ):
            result = set_ticket_done_command("NES-123")

        assert result == 1
        mock_client.get_done_state_id.assert_not_called()

    def test_empty_issue_uuid_string_returns_error(self) -> None:
        """Should return 1 when issue UUID is an empty string."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {
            "id": "",  # Empty string
            "team_id": "team-uuid-456",
        }
        mock_client.get_done_state_id.return_value = "done-state-id"

        with patch(
            "scripts.pr.commands.set_ticket_done_command._get_default_client",
            return_value=mock_client,
        ):
            result = set_ticket_done_command("NES-123")

        assert result == 1
        mock_client.set_ticket_state.assert_not_called()
