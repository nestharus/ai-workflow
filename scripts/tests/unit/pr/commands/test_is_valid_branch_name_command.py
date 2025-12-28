"""Tests for is_valid_branch_name_command module."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.pr.commands.is_valid_branch_name_command import is_valid_branch_name_command


class TestIsValidBranchNameCommand:
    """Tests for the is_valid_branch_name_command function."""

    def test_valid_exact_match_returns_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that exact branch name match returns 0."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": "nes-123-feature"}

        with (
            patch(
                "scripts.pr.commands.is_valid_branch_name_command._get_default_client",
                return_value=mock_client,
            ),
            patch(
                "scripts.pr.commands.is_valid_branch_name_command._is_valid_branch_name"
            ) as mock_valid,
        ):
            mock_valid.return_value = True
            result = is_valid_branch_name_command("NES-123", "nes-123-feature")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["is_valid"] is True
        assert output["ticket_id"] == "NES-123"
        assert output["branch_name"] == "nes-123-feature"
        assert output["expected_base"] == "nes-123-feature"
        assert result == 0

    def test_valid_with_counter_suffix_returns_zero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that branch name with counter suffix returns 0 if valid."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": "nes-123-feature"}

        with (
            patch(
                "scripts.pr.commands.is_valid_branch_name_command._get_default_client",
                return_value=mock_client,
            ),
            patch(
                "scripts.pr.commands.is_valid_branch_name_command._is_valid_branch_name"
            ) as mock_valid,
        ):
            mock_valid.return_value = True
            result = is_valid_branch_name_command("NES-123", "nes-123-feature-2")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["is_valid"] is True
        assert result == 0

    def test_invalid_branch_name_returns_one(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that invalid branch name returns 1."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": "nes-123-feature"}

        with (
            patch(
                "scripts.pr.commands.is_valid_branch_name_command._get_default_client",
                return_value=mock_client,
            ),
            patch(
                "scripts.pr.commands.is_valid_branch_name_command._is_valid_branch_name"
            ) as mock_valid,
        ):
            mock_valid.return_value = False
            result = is_valid_branch_name_command("NES-123", "wrong-branch-name")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["is_valid"] is False
        assert result == 1

    def test_no_branch_name_in_ticket_returns_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that missing branch name in ticket returns error."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": None}

        with patch(
            "scripts.pr.commands.is_valid_branch_name_command._get_default_client",
            return_value=mock_client,
        ):
            result = is_valid_branch_name_command("NES-456", "some-branch")

        captured = capsys.readouterr()
        assert "Error: No branch name found for ticket NES-456" in captured.err
        assert result == 1

    def test_empty_branch_name_in_ticket_returns_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that empty branch name in ticket returns error."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": ""}

        with patch(
            "scripts.pr.commands.is_valid_branch_name_command._get_default_client",
            return_value=mock_client,
        ):
            result = is_valid_branch_name_command("NES-789", "some-branch")

        captured = capsys.readouterr()
        assert "Error: No branch name found for ticket NES-789" in captured.err
        assert result == 1

    def test_linear_client_error_returns_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that LinearClientError returns 1 and prints error."""
        from scripts.clients.linear_client import LinearClientError

        mock_client = MagicMock()
        mock_client.get_ticket_info.side_effect = LinearClientError("NOT_FOUND", "Ticket not found")

        with patch(
            "scripts.pr.commands.is_valid_branch_name_command._get_default_client",
            return_value=mock_client,
        ):
            result = is_valid_branch_name_command("INVALID-999", "any-branch")

        captured = capsys.readouterr()
        assert "Error: NOT_FOUND: Ticket not found" in captured.err
        assert result == 1

    def test_calls_is_valid_branch_name_with_correct_args(self) -> None:
        """Test that _is_valid_branch_name is called with correct arguments."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": "expected-base"}

        with (
            patch(
                "scripts.pr.commands.is_valid_branch_name_command._get_default_client",
                return_value=mock_client,
            ),
            patch(
                "scripts.pr.commands.is_valid_branch_name_command._is_valid_branch_name"
            ) as mock_valid,
        ):
            mock_valid.return_value = True
            is_valid_branch_name_command("NES-1", "actual-branch")

        mock_valid.assert_called_once_with("actual-branch", "expected-base")

    def test_output_json_structure(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that output JSON has correct structure."""
        mock_client = MagicMock()
        mock_client.get_ticket_info.return_value = {"branch_name": "nes-50-task"}

        with (
            patch(
                "scripts.pr.commands.is_valid_branch_name_command._get_default_client",
                return_value=mock_client,
            ),
            patch(
                "scripts.pr.commands.is_valid_branch_name_command._is_valid_branch_name"
            ) as mock_valid,
        ):
            mock_valid.return_value = True
            is_valid_branch_name_command("NES-50", "nes-50-task")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert set(output.keys()) == {"ticket_id", "branch_name", "expected_base", "is_valid"}
