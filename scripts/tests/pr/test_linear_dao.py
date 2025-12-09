"""Unit tests for Linear API facade (linear_dao.py).

This module tests ONLY the facade layer responsibilities:
1. Import re-exports work correctly (LinearClient, _get_default_client)
2. Aliasing works (LinearAPIError is an alias for LinearClientError)
3. Correct delegation to _get_default_client() from free functions

Detailed HTTP/JSON behaviour is tested in scripts/tests/clients/test_linear_client.py.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from scripts.pr.linear_dao import (
    LinearAPIError,
    LinearClient,
    _get_default_client,
    _get_linear_api_key,
    _run_linear_graphql,
    fetch_github_attachments,
    get_done_state_id,
    get_ticket_info,
    set_ticket_state,
)


class TestLinearAPIErrorAlias:
    """Tests verifying LinearAPIError is aliased to LinearClientError."""

    def test_linear_api_error_is_linear_client_error(self) -> None:
        """LinearAPIError should be an alias for LinearClientError."""
        from scripts.clients.linear_client import LinearClientError
        assert LinearAPIError is LinearClientError

    def test_linear_api_error_has_code_and_message(self) -> None:
        """LinearAPIError instances have code and message attributes."""
        error = LinearAPIError("TEST_CODE", "Test message")
        assert error.code == "TEST_CODE"
        assert error.message == "Test message"
        assert str(error) == "TEST_CODE: Test message"


class TestLinearClientReExport:
    """Tests verifying LinearClient is re-exported from linear_dao."""

    def test_linear_client_is_reexported(self) -> None:
        """LinearClient from linear_dao is the same as from linear_client."""
        from scripts.clients.linear_client import LinearClient as CanonicalClient
        assert LinearClient is CanonicalClient


class TestGetDefaultClientReExport:
    """Tests verifying _get_default_client is re-exported from linear_dao."""

    def test_get_default_client_is_reexported(self) -> None:
        """_get_default_client from linear_dao is the same as from linear_client."""
        from scripts.clients.linear_client import _get_default_client as canonical_fn
        assert _get_default_client is canonical_fn


class TestBackwardsCompatibleFunctions:
    """Tests for backwards-compatible module-level functions.

    These tests verify that free functions delegate to _get_default_client()
    correctly by mocking at the scripts.clients.linear_client layer,
    NOT by patching urllib.request.urlopen.
    """

    @pytest.fixture(autouse=True)
    def reset_default_client(self) -> Generator[None]:
        """Reset the default client before and after each test."""
        import scripts.clients.linear_client as linear_client_module
        linear_client_module._default_client = None
        yield
        linear_client_module._default_client = None

    def test_get_linear_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_get_linear_api_key returns key from environment."""
        monkeypatch.setenv("LINEAR_API_KEY", "env-key-value")
        assert _get_linear_api_key() == "env-key-value"

    def test_get_linear_api_key_raises_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_get_linear_api_key raises when env var not set."""
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        with pytest.raises(LinearAPIError) as exc_info:
            _get_linear_api_key()
        assert exc_info.value.code == "MISSING_API_KEY"
        assert "LINEAR_API_KEY" in exc_info.value.message

    def test_get_default_client_creates_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_get_default_client creates and caches a LinearClient instance."""
        monkeypatch.setenv("LINEAR_API_KEY", "test-key")
        client = _get_default_client()
        assert isinstance(client, LinearClient)
        # Second call should return same instance
        client2 = _get_default_client()
        assert client is client2

    def test_run_linear_graphql_delegates_to_client(self) -> None:
        """_run_linear_graphql delegates to _get_default_client()._run_graphql."""
        mock_client = MagicMock(spec=LinearClient)
        mock_client._run_graphql.return_value = {"data": {"viewer": {"id": "123"}}}

        with patch("scripts.pr.linear_dao._get_default_client", return_value=mock_client):
            result = _run_linear_graphql("query { viewer { id } }")

        mock_client._run_graphql.assert_called_once_with("query { viewer { id } }")
        assert result["data"]["viewer"]["id"] == "123"

    def test_fetch_github_attachments_delegates(self) -> None:
        """fetch_github_attachments free function delegates to _get_default_client()."""
        mock_client = MagicMock(spec=LinearClient)
        mock_client.fetch_github_attachments.return_value = [
            {"url": "https://github.com/pr/1", "title": "PR"}
        ]

        with patch("scripts.pr.linear_dao._get_default_client", return_value=mock_client):
            attachments = fetch_github_attachments("NES-123")

        mock_client.fetch_github_attachments.assert_called_once_with("NES-123")
        assert len(attachments) == 1
        assert attachments[0]["url"] == "https://github.com/pr/1"

    def test_get_ticket_info_delegates(self) -> None:
        """get_ticket_info free function delegates to _get_default_client()."""
        mock_client = MagicMock(spec=LinearClient)
        mock_client.get_ticket_info.return_value = {
            "id": "uuid",
            "identifier": "NES-1",
            "title": "Title",
            "branch_name": "branch",
            "state": "State",
            "state_type": "started",
            "team_id": "t",
        }

        with patch("scripts.pr.linear_dao._get_default_client", return_value=mock_client):
            info = get_ticket_info("NES-1")

        mock_client.get_ticket_info.assert_called_once_with("NES-1")
        assert info["identifier"] == "NES-1"

    def test_get_done_state_id_delegates(self) -> None:
        """get_done_state_id free function delegates to _get_default_client()."""
        mock_client = MagicMock(spec=LinearClient)
        mock_client.get_done_state_id.return_value = "done-id"

        with patch("scripts.pr.linear_dao._get_default_client", return_value=mock_client):
            state_id = get_done_state_id("team-uuid")

        mock_client.get_done_state_id.assert_called_once_with("team-uuid")
        assert state_id == "done-id"

    def test_set_ticket_state_delegates_and_returns_true(self) -> None:
        """set_ticket_state free function delegates and returns True on success."""
        mock_client = MagicMock(spec=LinearClient)
        mock_client.set_ticket_state.return_value = {"stateName": "Done"}

        with patch("scripts.pr.linear_dao._get_default_client", return_value=mock_client):
            result = set_ticket_state("issue-uuid", "state-uuid")

        mock_client.set_ticket_state.assert_called_once_with("issue-uuid", "state-uuid")
        assert result is True

    def test_set_ticket_state_returns_true_for_any_client_return(self) -> None:
        """set_ticket_state returns True when underlying client returns any value.

        This is a simple behavioural check - the free function always returns True
        if the client method does not raise an exception.
        """
        mock_client = MagicMock(spec=LinearClient)
        # Client returns an arbitrary dict - free function should still return True
        mock_client.set_ticket_state.return_value = {"arbitrary": "value"}

        with patch("scripts.pr.linear_dao._get_default_client", return_value=mock_client):
            result = set_ticket_state("issue-uuid", "state-uuid")

        assert result is True
