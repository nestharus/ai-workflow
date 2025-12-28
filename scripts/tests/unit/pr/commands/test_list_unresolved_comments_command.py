"""Tests for list_unresolved_comments_command module."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.pr.commands.list_unresolved_comments_command import (
    list_unresolved_comments_command,
)


class TestListUnresolvedCommentsCommand:
    """Tests for the list_unresolved_comments_command function."""

    def test_success_returns_zero_and_prints_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test successful retrieval prints JSON and returns 0."""
        mock_result = {
            "issueId": "uuid-123",
            "issueIdentifier": "NES-123",
            "comments": [
                {"id": "c1", "body": "First comment", "user": {"name": "Alice"}},
                {"id": "c2", "body": "Second comment", "user": {"name": "Bob"}},
            ],
            "totalCount": 2,
        }

        with patch(
            "scripts.pr.commands.list_unresolved_comments_command.LinearClient"
        ) as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.list_unresolved_comments.return_value = mock_result

            result = list_unresolved_comments_command("NES-123")

        mock_instance.list_unresolved_comments.assert_called_once_with("NES-123")
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output == mock_result
        assert result == 0

    def test_empty_comments_returns_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that empty comments list returns 0."""
        mock_result = {
            "issueId": "uuid-456",
            "issueIdentifier": "NES-456",
            "comments": [],
            "totalCount": 0,
        }

        with patch(
            "scripts.pr.commands.list_unresolved_comments_command.LinearClient"
        ) as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.list_unresolved_comments.return_value = mock_result

            result = list_unresolved_comments_command("NES-456")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["totalCount"] == 0
        assert output["comments"] == []
        assert result == 0

    def test_linear_client_error_returns_one(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that LinearClientError returns 1 and prints error."""
        from scripts.clients.linear_client import LinearClientError

        with patch(
            "scripts.pr.commands.list_unresolved_comments_command.LinearClient"
        ) as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.list_unresolved_comments.side_effect = LinearClientError(
                "NOT_FOUND", "Issue not found"
            )

            result = list_unresolved_comments_command("INVALID-999")

        captured = capsys.readouterr()
        assert "Error: NOT_FOUND: Issue not found" in captured.err
        assert result == 1

    def test_creates_new_client_instance(self) -> None:
        """Test that a new LinearClient instance is created for each call."""
        with patch(
            "scripts.pr.commands.list_unresolved_comments_command.LinearClient"
        ) as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.list_unresolved_comments.return_value = {
                "issueId": "uuid",
                "issueIdentifier": "NES-1",
                "comments": [],
                "totalCount": 0,
            }

            list_unresolved_comments_command("NES-1")

        MockClient.assert_called_once()

    def test_handles_comments_with_user_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test handling of comments with full user info."""
        mock_result = {
            "issueId": "uuid",
            "issueIdentifier": "NES-789",
            "comments": [
                {
                    "id": "c1",
                    "body": "Comment body",
                    "createdAt": "2024-01-01T00:00:00Z",
                    "updatedAt": "2024-01-02T00:00:00Z",
                    "user": {
                        "id": "user-1",
                        "name": "Test User",
                        "email": "test@example.com",
                    },
                },
            ],
            "totalCount": 1,
        }

        with patch(
            "scripts.pr.commands.list_unresolved_comments_command.LinearClient"
        ) as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.list_unresolved_comments.return_value = mock_result

            result = list_unresolved_comments_command("NES-789")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["comments"][0]["user"]["name"] == "Test User"
        assert result == 0

    def test_handles_comments_without_user_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test handling of comments without user info (system comments)."""
        mock_result = {
            "issueId": "uuid",
            "issueIdentifier": "NES-111",
            "comments": [
                {
                    "id": "c1",
                    "body": "System comment",
                    "user": None,
                },
            ],
            "totalCount": 1,
        }

        with patch(
            "scripts.pr.commands.list_unresolved_comments_command.LinearClient"
        ) as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.list_unresolved_comments.return_value = mock_result

            result = list_unresolved_comments_command("NES-111")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["comments"][0]["user"] is None
        assert result == 0
