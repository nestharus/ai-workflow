"""Tests for get_expected_branch_name_command module."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.pr.commands.get_expected_branch_name_command import (
    MAX_BRANCH_NAME_LENGTH,
    get_expected_branch_name_command,
)


class TestGetExpectedBranchNameCommand:
    """Tests for the get_expected_branch_name_command function."""

    def test_success_returns_zero_and_prints_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test successful retrieval prints JSON and returns 0."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": "nes-123-feature"}

        with patch(
            "scripts.pr.commands.get_expected_branch_name_command._get_default_client",
            return_value=mock_client,
        ):
            result = get_expected_branch_name_command("NES-123")

        mock_client.get_ticket_info.assert_called_once_with("NES-123")
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output == {
            "ticket_id": "NES-123",
            "expected_branch_name": "nes-123-feature",
        }
        assert result == 0

    def test_truncates_long_branch_names(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that branch names longer than MAX_BRANCH_NAME_LENGTH are truncated."""
        long_name = "a" * 60  # Longer than MAX_BRANCH_NAME_LENGTH (50)
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": long_name}

        with patch(
            "scripts.pr.commands.get_expected_branch_name_command._get_default_client",
            return_value=mock_client,
        ):
            result = get_expected_branch_name_command("NES-999")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["expected_branch_name"] == "a" * MAX_BRANCH_NAME_LENGTH
        assert len(output["expected_branch_name"]) == MAX_BRANCH_NAME_LENGTH
        assert result == 0

    def test_does_not_truncate_short_branch_names(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that branch names shorter than MAX_BRANCH_NAME_LENGTH are not truncated."""
        short_name = "nes-1-fix"
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": short_name}

        with patch(
            "scripts.pr.commands.get_expected_branch_name_command._get_default_client",
            return_value=mock_client,
        ):
            result = get_expected_branch_name_command("NES-1")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["expected_branch_name"] == short_name
        assert result == 0

    def test_no_branch_name_returns_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that missing branch name returns 1 and prints error."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": None}

        with patch(
            "scripts.pr.commands.get_expected_branch_name_command._get_default_client",
            return_value=mock_client,
        ):
            result = get_expected_branch_name_command("NES-123")

        captured = capsys.readouterr()
        assert "Error: No branch name found for ticket NES-123" in captured.err
        assert result == 1

    def test_empty_branch_name_returns_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that empty branch name returns 1 and prints error."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": ""}

        with patch(
            "scripts.pr.commands.get_expected_branch_name_command._get_default_client",
            return_value=mock_client,
        ):
            result = get_expected_branch_name_command("NES-456")

        captured = capsys.readouterr()
        assert "Error: No branch name found for ticket NES-456" in captured.err
        assert result == 1

    def test_linear_client_error_returns_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that LinearClientError returns 1 and prints error."""
        from scripts.clients.linear_client import LinearClientError

        mock_client = MagicMock()
        mock_client.get_ticket_info.side_effect = LinearClientError("NOT_FOUND", "Ticket not found")

        with patch(
            "scripts.pr.commands.get_expected_branch_name_command._get_default_client",
            return_value=mock_client,
        ):
            result = get_expected_branch_name_command("INVALID-999")

        captured = capsys.readouterr()
        assert "Error: NOT_FOUND: Ticket not found" in captured.err
        assert result == 1

    def test_exact_max_length_branch_name(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that branch names exactly at MAX_BRANCH_NAME_LENGTH are preserved."""
        exact_length_name = "x" * MAX_BRANCH_NAME_LENGTH
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": exact_length_name}

        with patch(
            "scripts.pr.commands.get_expected_branch_name_command._get_default_client",
            return_value=mock_client,
        ):
            result = get_expected_branch_name_command("NES-50")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["expected_branch_name"] == exact_length_name
        assert len(output["expected_branch_name"]) == MAX_BRANCH_NAME_LENGTH
        assert result == 0
