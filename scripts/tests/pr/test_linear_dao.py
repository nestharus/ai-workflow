"""Unit tests for Linear API client (linear_dao.py).

Comprehensive tests for LinearClient including initialization, error handling,
API operations, pagination, and backwards-compatible free functions.
"""

from __future__ import annotations

import json
import urllib.error
from collections.abc import Generator
from typing import Any
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

# ============================================================================
# Test Helpers
# ============================================================================


def make_mock_response(data: dict[str, Any]) -> MagicMock:
    """Create a mock urllib response with the given data."""
    response_body = json.dumps(data).encode("utf-8")
    mock_response = MagicMock()
    mock_response.read.return_value = response_body
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = lambda s, *args: None
    return mock_response


# ============================================================================
# TestLinearClientInit
# ============================================================================


class TestLinearClientInit:
    """Tests for LinearClient initialization."""

    def test_init_with_explicit_api_key(self) -> None:
        """Initialize client with explicit API key."""
        client = LinearClient(api_key="test-api-key-123")
        assert client._api_key == "test-api-key-123"

    def test_init_from_env_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Initialize client from LINEAR_API_KEY environment variable."""
        monkeypatch.setenv("LINEAR_API_KEY", "env-api-key-456")
        client = LinearClient()
        assert client._api_key == "env-api-key-456"

    def test_init_prefers_explicit_key_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit API key takes precedence over environment variable."""
        monkeypatch.setenv("LINEAR_API_KEY", "env-key")
        client = LinearClient(api_key="explicit-key")
        assert client._api_key == "explicit-key"

    def test_init_raises_when_no_key_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Raise LinearAPIError when no API key is provided or in environment."""
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        with pytest.raises(LinearAPIError) as exc_info:
            LinearClient()
        assert "LINEAR_API_KEY environment variable not set" in str(exc_info.value)

    def test_init_raises_for_empty_api_key(self) -> None:
        """Raise LinearAPIError when api_key is empty string."""
        with pytest.raises(LinearAPIError) as exc_info:
            LinearClient(api_key="")
        assert "API key is empty" in str(exc_info.value)

    def test_init_raises_for_whitespace_only_api_key(self) -> None:
        """Raise LinearAPIError when api_key is whitespace only."""
        with pytest.raises(LinearAPIError) as exc_info:
            LinearClient(api_key="   ")
        assert "API key is empty" in str(exc_info.value)

        with pytest.raises(LinearAPIError) as exc_info:
            LinearClient(api_key="\t\n")
        assert "API key is empty" in str(exc_info.value)

    def test_init_trims_whitespace_from_env_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment API key is trimmed of leading/trailing whitespace."""
        monkeypatch.setenv("LINEAR_API_KEY", "  env-key-with-whitespace  ")
        client = LinearClient()
        assert client._api_key == "env-key-with-whitespace"

    def test_init_raises_for_whitespace_only_env_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Raise LinearAPIError when environment API key is whitespace only."""
        monkeypatch.setenv("LINEAR_API_KEY", "   ")
        with pytest.raises(LinearAPIError) as exc_info:
            LinearClient()
        assert "LINEAR_API_KEY environment variable not set" in str(exc_info.value)


# ============================================================================
# TestLinearClientRunGraphQL
# ============================================================================


class TestLinearClientRunGraphQL:
    """Tests for _run_graphql error handling."""

    def test_network_failure_raises_error(self) -> None:
        """Network/DNS failures raise LinearAPIError."""
        client = LinearClient(api_key="test-key")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError("Name or service not known")

            with pytest.raises(LinearAPIError) as exc_info:
                client._run_graphql("query { viewer { id } }")

            assert "Linear API request failed" in str(exc_info.value)
            assert "Name or service not known" in str(exc_info.value)

    def test_http_error_raises_error(self) -> None:
        """HTTP errors raise LinearAPIError with status code."""
        client = LinearClient(api_key="test-key")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.HTTPError(
                url="https://api.linear.app/graphql",
                code=401,
                msg="Unauthorized",
                hdrs={},  # type: ignore[arg-type]
                fp=None,
            )

            with pytest.raises(LinearAPIError) as exc_info:
                client._run_graphql("query { viewer { id } }")

            assert "Linear API HTTP error" in str(exc_info.value)
            assert "401" in str(exc_info.value)
            assert "Unauthorized" in str(exc_info.value)

    def test_graphql_errors_raise_error(self) -> None:
        """GraphQL responses containing errors array raise LinearAPIError.

        Extracted messages should be properly formatted.
        """
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response({"errors": [{"message": "Field 'foo' doesn't exist"}]})

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client._run_graphql("query { foo }")

            error_str = str(exc_info.value)
            assert error_str == "Linear API error: Field 'foo' doesn't exist"

    def test_graphql_multiple_errors_joined(self) -> None:
        """Multiple GraphQL errors are joined with semicolons."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "errors": [
                    {"message": "First error"},
                    {"message": "Second error"},
                    {"message": "Third error"},
                ]
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client._run_graphql("query { foo }")

            error_str = str(exc_info.value)
            assert error_str == "Linear API error: First error; Second error; Third error"

    def test_graphql_errors_without_message_field(self) -> None:
        """GraphQL errors without message field fall back to Unknown error."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {"errors": [{"code": "SOME_ERROR_CODE", "extensions": {"foo": "bar"}}]}
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client._run_graphql("query { foo }")

            error_str = str(exc_info.value)
            assert error_str == "Linear API error: Unknown error"

    def test_graphql_errors_mixed_with_and_without_message(self) -> None:
        """GraphQL errors with mixed message/no-message are handled correctly."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "errors": [
                    {"message": "Valid error message"},
                    {"code": "NO_MESSAGE"},
                    {"message": "Another valid message"},
                ]
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client._run_graphql("query { foo }")

            error_str = str(exc_info.value)
            assert error_str == "Linear API error: Valid error message; Another valid message"

    def test_graphql_errors_not_a_list_raises_error(self) -> None:
        """GraphQL errors field that is not a list raises LinearAPIError."""
        client = LinearClient(api_key="test-key")

        # Test with string instead of list
        mock_response = make_mock_response({"errors": "Not a list"})

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client._run_graphql("query { foo }")

            error_str = str(exc_info.value)
            assert error_str == "Linear API returned malformed errors field"

    def test_graphql_errors_as_dict_raises_error(self) -> None:
        """GraphQL errors field that is a dict raises LinearAPIError."""
        client = LinearClient(api_key="test-key")

        # Test with dict instead of list
        mock_response = make_mock_response({"errors": {"message": "Single error as dict"}})

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client._run_graphql("query { foo }")

            error_str = str(exc_info.value)
            assert error_str == "Linear API returned malformed errors field"

    def test_malformed_json_raises_error(self) -> None:
        """Malformed JSON responses raise LinearAPIError."""
        client = LinearClient(api_key="test-key")

        mock_response = MagicMock()
        mock_response.read.return_value = b"not valid json {"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *args: None

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client._run_graphql("query { viewer { id } }")

            assert "Linear API returned malformed JSON" in str(exc_info.value)

    def test_non_object_json_raises_error(self) -> None:
        """Non-object JSON responses (arrays, strings, etc.) raise LinearAPIError."""
        client = LinearClient(api_key="test-key")

        # Test with array response
        mock_response = MagicMock()
        mock_response.read.return_value = b'["item1", "item2"]'
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *args: None

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client._run_graphql("query { viewer { id } }")

            assert "Linear API returned non-object JSON response" in str(exc_info.value)

    def test_string_json_raises_error(self) -> None:
        """String JSON responses raise LinearAPIError."""
        client = LinearClient(api_key="test-key")

        mock_response = MagicMock()
        mock_response.read.return_value = b'"just a string"'
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *args: None

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client._run_graphql("query { viewer { id } }")

            assert "Linear API returned non-object JSON response" in str(exc_info.value)

    def test_null_json_raises_error(self) -> None:
        """Null JSON responses raise LinearAPIError."""
        client = LinearClient(api_key="test-key")

        mock_response = MagicMock()
        mock_response.read.return_value = b"null"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *args: None

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client._run_graphql("query { viewer { id } }")

            assert "Linear API returned non-object JSON response" in str(exc_info.value)

    def test_non_utf8_response_raises_error(self) -> None:
        """Non-UTF-8 response bytes raise LinearAPIError."""
        client = LinearClient(api_key="test-key")

        # Invalid UTF-8 sequence: 0x80 is a continuation byte without a leading byte
        mock_response = MagicMock()
        mock_response.read.return_value = b"\x80\x81\x82 invalid utf-8"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *args: None

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client._run_graphql("query { viewer { id } }")

            assert "Linear API returned non-UTF-8 response" in str(exc_info.value)

    def test_api_key_not_in_error_messages(self) -> None:
        """API key is not leaked in error messages."""
        secret_key = "lin_secret_key_12345678"
        client = LinearClient(api_key=secret_key)

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.HTTPError(
                url="https://api.linear.app/graphql",
                code=401,
                msg="Invalid API key",
                hdrs={},  # type: ignore[arg-type]
                fp=None,
            )

            with pytest.raises(LinearAPIError) as exc_info:
                client._run_graphql("query { viewer { id } }")

            # Verify API key is NOT in error message
            assert secret_key not in str(exc_info.value)

    def test_api_key_not_in_graphql_error_messages(self) -> None:
        """API key is not leaked in GraphQL error responses."""
        secret_key = "lin_api_secret_987654"
        client = LinearClient(api_key=secret_key)

        mock_response = make_mock_response({"errors": [{"message": "Authentication failed"}]})

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client._run_graphql("query { viewer { id } }")

            assert secret_key not in str(exc_info.value)

    def test_successful_request_returns_data(self) -> None:
        """Successful requests return parsed JSON data."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {"data": {"viewer": {"id": "user-123", "name": "Test User"}}}
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = client._run_graphql("query { viewer { id name } }")

        assert result["data"]["viewer"]["id"] == "user-123"
        assert result["data"]["viewer"]["name"] == "Test User"

    def test_variables_are_sent_in_payload(self) -> None:
        """Variables are included in the request payload."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response({"data": {"issue": {"id": "issue-123"}}})

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            client._run_graphql(
                "query($id: String!) { issue(id: $id) { id } }",
                variables={"id": "NES-123"},
            )

            # Check the request payload
            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            payload = json.loads(request.data.decode("utf-8"))

            assert "variables" in payload
            assert payload["variables"]["id"] == "NES-123"

    def test_default_timeout_is_30_seconds(self) -> None:
        """Default timeout is 30 seconds when not specified."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response({"data": {"viewer": {"id": "123"}}})

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            client._run_graphql("query { viewer { id } }")

            # Check the timeout argument
            call_args = mock_urlopen.call_args
            assert call_args[1]["timeout"] == 30

    def test_custom_timeout_is_used(self) -> None:
        """Custom timeout is passed to urlopen."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response({"data": {"viewer": {"id": "123"}}})

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            client._run_graphql("query { viewer { id } }", timeout=60)

            # Check the timeout argument
            call_args = mock_urlopen.call_args
            assert call_args[1]["timeout"] == 60


# ============================================================================
# TestResolveTeamId
# ============================================================================


class TestResolveTeamId:
    """Tests for _resolve_team_id."""

    def test_uuid_returns_as_is(self) -> None:
        """Valid UUID string returns as-is without API call."""
        client = LinearClient(api_key="test-key")
        uuid = "12345678-1234-1234-1234-123456789012"

        # Should not make any API calls for a valid UUID
        with patch.object(client, "list_teams") as mock_list:
            result = client._resolve_team_id(uuid)

        assert result == uuid
        mock_list.assert_not_called()

    def test_team_key_lookup_case_insensitive(self) -> None:
        """Team key lookup is case-insensitive."""
        client = LinearClient(api_key="test-key")

        mock_teams = [
            {"id": "team-uuid-1", "key": "NES", "name": "Nexus Engineering"},
            {"id": "team-uuid-2", "key": "QA", "name": "Quality Assurance"},
        ]

        with patch.object(client, "list_teams", return_value=mock_teams):
            # Test lowercase
            result_lower = client._resolve_team_id("nes")
            assert result_lower == "team-uuid-1"

            # Test uppercase
            result_upper = client._resolve_team_id("NES")
            assert result_upper == "team-uuid-1"

            # Test mixed case
            result_mixed = client._resolve_team_id("Nes")
            assert result_mixed == "team-uuid-1"

    def test_team_name_lookup_case_insensitive(self) -> None:
        """Team name lookup is case-insensitive."""
        client = LinearClient(api_key="test-key")

        mock_teams = [
            {"id": "team-uuid-1", "key": "NES", "name": "Nexus Engineering"},
            {"id": "team-uuid-2", "key": "QA", "name": "Quality Assurance"},
        ]

        with patch.object(client, "list_teams", return_value=mock_teams):
            # Test exact match
            result = client._resolve_team_id("Nexus Engineering")
            assert result == "team-uuid-1"

            # Test lowercase
            result_lower = client._resolve_team_id("nexus engineering")
            assert result_lower == "team-uuid-1"

    def test_key_takes_precedence_over_name(self) -> None:
        """Team key lookup takes precedence over name lookup."""
        client = LinearClient(api_key="test-key")

        mock_teams = [
            {"id": "team-uuid-1", "key": "TEST", "name": "Production Team"},
            {"id": "team-uuid-2", "key": "PROD", "name": "TEST"},
        ]

        with patch.object(client, "list_teams", return_value=mock_teams):
            # "TEST" matches key of team-1, should return team-1
            result = client._resolve_team_id("TEST")
            assert result == "team-uuid-1"

    def test_not_found_returns_none(self) -> None:
        """Returns None when team is not found."""
        client = LinearClient(api_key="test-key")

        mock_teams = [
            {"id": "team-uuid-1", "key": "NES", "name": "Nexus Engineering"},
        ]

        with patch.object(client, "list_teams", return_value=mock_teams):
            result = client._resolve_team_id("nonexistent")
            assert result is None

    def test_empty_string_returns_none_without_api_call(self) -> None:
        """Empty string returns None without calling list_teams."""
        client = LinearClient(api_key="test-key")

        with patch.object(client, "list_teams") as mock_list:
            result = client._resolve_team_id("")

        assert result is None
        mock_list.assert_not_called()

    def test_whitespace_only_returns_none_without_api_call(self) -> None:
        """Whitespace-only string returns None without calling list_teams."""
        client = LinearClient(api_key="test-key")

        with patch.object(client, "list_teams") as mock_list:
            # Test various whitespace strings
            for whitespace in ["   ", "\t", "\n", "  \t\n  "]:
                result = client._resolve_team_id(whitespace)
                assert result is None

        mock_list.assert_not_called()

    def test_excessively_long_string_returns_none_without_api_call(self) -> None:
        """String over 100 characters returns None without calling list_teams."""
        client = LinearClient(api_key="test-key")

        long_string = "a" * 101

        with patch.object(client, "list_teams") as mock_list:
            result = client._resolve_team_id(long_string)

        assert result is None
        mock_list.assert_not_called()

    def test_string_exactly_100_chars_is_allowed(self) -> None:
        """String of exactly 100 characters is still processed (calls list_teams)."""
        client = LinearClient(api_key="test-key")

        string_100 = "a" * 100
        mock_teams: list[dict[str, Any]] = []

        with patch.object(client, "list_teams", return_value=mock_teams) as mock_list:
            result = client._resolve_team_id(string_100)

        # Should return None because no matching team, but list_teams should be called
        assert result is None
        mock_list.assert_called_once()

    def test_uuid_with_surrounding_whitespace_is_trimmed(self) -> None:
        """UUID with surrounding whitespace is trimmed and returned."""
        client = LinearClient(api_key="test-key")
        uuid = "12345678-1234-1234-1234-123456789012"
        padded_uuid = f"  {uuid}  "

        with patch.object(client, "list_teams") as mock_list:
            result = client._resolve_team_id(padded_uuid)

        assert result == uuid
        mock_list.assert_not_called()


# ============================================================================
# TestValidatePriority
# ============================================================================


class TestValidatePriority:
    """Tests for _validate_priority."""

    @pytest.mark.parametrize("priority", [0, 1, 2, 3, 4])
    def test_valid_priorities_pass(self, priority: int) -> None:
        """Valid priorities (0-4) do not raise errors."""
        client = LinearClient(api_key="test-key")
        # Should not raise
        client._validate_priority(priority)

    def test_none_priority_passes(self) -> None:
        """None priority (no priority set) does not raise."""
        client = LinearClient(api_key="test-key")
        client._validate_priority(None)

    @pytest.mark.parametrize("invalid_priority", [-1, 5, 100, -100])
    def test_invalid_priorities_raise(self, invalid_priority: int) -> None:
        """Invalid priorities raise LinearAPIError."""
        client = LinearClient(api_key="test-key")
        with pytest.raises(LinearAPIError) as exc_info:
            client._validate_priority(invalid_priority)
        assert "Priority must be between 0 and 4" in str(exc_info.value)
        assert str(invalid_priority) in str(exc_info.value)

    @pytest.mark.parametrize("invalid_type", ["3", "high", 2.5, [], {}])
    def test_invalid_type_raises(self, invalid_type: object) -> None:
        """Non-integer types raise LinearAPIError instead of TypeError."""
        client = LinearClient(api_key="test-key")
        with pytest.raises(LinearAPIError) as exc_info:
            client._validate_priority(invalid_type)  # type: ignore[arg-type]
        assert "Priority must be between 0 and 4" in str(exc_info.value)

    @pytest.mark.parametrize("bool_value", [True, False])
    def test_boolean_raises(self, bool_value: bool) -> None:
        """Boolean values are rejected even though bool is subclass of int."""
        client = LinearClient(api_key="test-key")
        with pytest.raises(LinearAPIError) as exc_info:
            client._validate_priority(bool_value)  # type: ignore[arg-type]
        assert "Priority must be between 0 and 4" in str(exc_info.value)


# ============================================================================
# TestListTeams
# ============================================================================


class TestListTeams:
    """Tests for list_teams method."""

    def test_list_teams_without_archived(self) -> None:
        """List teams without archived teams."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "teams": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                "id": "team-1",
                                "name": "Engineering",
                                "key": "ENG",
                                "description": "Engineering team",
                                "createdAt": "2024-01-01T00:00:00Z",
                                "updatedAt": "2024-01-02T00:00:00Z",
                                "archivedAt": None,
                                "private": False,
                                "timezone": "America/New_York",
                            }
                        ],
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            teams = client.list_teams(include_archived=False)

        assert len(teams) == 1
        assert teams[0]["id"] == "team-1"
        assert teams[0]["key"] == "ENG"

    def test_list_teams_with_archived(self) -> None:
        """List teams including archived teams."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "teams": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                "id": "team-1",
                                "name": "Active Team",
                                "key": "ACT",
                                "archivedAt": None,
                            },
                            {
                                "id": "team-2",
                                "name": "Archived Team",
                                "key": "ARC",
                                "archivedAt": "2024-06-01T00:00:00Z",
                            },
                        ],
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            teams = client.list_teams(include_archived=True)

            # Verify includeArchived is True in the request
            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            payload = json.loads(request.data.decode("utf-8"))
            assert payload["variables"]["includeArchived"] is True

        assert len(teams) == 2

    def test_list_teams_with_pagination(self) -> None:
        """List teams with multi-page pagination."""
        client = LinearClient(api_key="test-key")

        # First page response
        page1_response = make_mock_response(
            {
                "data": {
                    "teams": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                        "nodes": [
                            {"id": "team-1", "name": "Team 1", "key": "T1"},
                            {"id": "team-2", "name": "Team 2", "key": "T2"},
                        ],
                    }
                }
            }
        )

        # Second page response
        page2_response = make_mock_response(
            {
                "data": {
                    "teams": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {"id": "team-3", "name": "Team 3", "key": "T3"},
                        ],
                    }
                }
            }
        )

        with patch(
            "urllib.request.urlopen", side_effect=[page1_response, page2_response]
        ) as mock_urlopen:
            teams = client.list_teams()

            # Should have made 2 requests
            assert mock_urlopen.call_count == 2

            # Second request should have the cursor
            second_call = mock_urlopen.call_args_list[1]
            request = second_call[0][0]
            payload = json.loads(request.data.decode("utf-8"))
            assert payload["variables"]["after"] == "cursor-1"

        # All teams from both pages should be merged in order
        assert len(teams) == 3
        assert teams[0]["id"] == "team-1"
        assert teams[1]["id"] == "team-2"
        assert teams[2]["id"] == "team-3"

    def test_list_teams_caching(self) -> None:
        """Verify list_teams caches results to avoid redundant API calls."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "teams": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [{"id": "team-1", "name": "Team 1", "key": "T1"}],
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            # First call should hit the API
            teams1 = client.list_teams()
            assert mock_urlopen.call_count == 1
            assert len(teams1) == 1

            # Second call should use cache, no additional API call
            teams2 = client.list_teams()
            assert mock_urlopen.call_count == 1  # Still 1, not 2
            assert teams1 is teams2  # Same list object from cache

    def test_list_teams_caching_per_include_archived(self) -> None:
        """Verify caching is separate for include_archived True/False."""
        client = LinearClient(api_key="test-key")

        mock_response_active = make_mock_response(
            {
                "data": {
                    "teams": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [{"id": "team-1", "name": "Active", "key": "ACT"}],
                    }
                }
            }
        )
        mock_response_all = make_mock_response(
            {
                "data": {
                    "teams": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {"id": "team-1", "name": "Active", "key": "ACT"},
                            {"id": "team-2", "name": "Archived", "key": "ARC"},
                        ],
                    }
                }
            }
        )

        with patch(
            "urllib.request.urlopen",
            side_effect=[mock_response_active, mock_response_all],
        ) as mock_urlopen:
            # Call without archived
            teams_active = client.list_teams(include_archived=False)
            assert mock_urlopen.call_count == 1
            assert len(teams_active) == 1

            # Call with archived - should hit API again (different cache key)
            teams_all = client.list_teams(include_archived=True)
            assert mock_urlopen.call_count == 2
            assert len(teams_all) == 2

            # Repeat calls should use cache
            client.list_teams(include_archived=False)
            client.list_teams(include_archived=True)
            assert mock_urlopen.call_count == 2  # No additional calls


# ============================================================================
# TestListProjects
# ============================================================================


class TestListProjects:
    """Tests for list_projects method."""

    def test_list_projects_without_team_filter(self) -> None:
        """List all projects without team filter."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "projects": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                "id": "project-1",
                                "name": "Project Alpha",
                                "description": "First project",
                                "url": "https://linear.app/project/alpha",
                                "slugId": "alpha",
                                "state": "in_progress",
                            }
                        ],
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            projects = client.list_projects()

        assert len(projects) == 1
        assert projects[0]["id"] == "project-1"

    def test_list_projects_with_team_filter(self) -> None:
        """List projects filtered by team."""
        client = LinearClient(api_key="test-key")

        # Mock _resolve_team_id to return a UUID
        team_uuid = "team-uuid-123"

        mock_response = make_mock_response(
            {
                "data": {
                    "projects": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {"id": "project-1", "name": "Team Project"},
                        ],
                    }
                }
            }
        )

        with (
            patch.object(client, "_resolve_team_id", return_value=team_uuid),
            patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen,
        ):
            projects = client.list_projects(team_id="NES")

            # Verify teamId is in the request
            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            payload = json.loads(request.data.decode("utf-8"))
            assert payload["variables"]["teamId"] == team_uuid

        assert len(projects) == 1

    def test_list_projects_team_not_found(self) -> None:
        """Raise error when team filter is not found."""
        client = LinearClient(api_key="test-key")

        with patch.object(client, "_resolve_team_id", return_value=None):
            with pytest.raises(LinearAPIError) as exc_info:
                client.list_projects(team_id="nonexistent")

            assert "Team not found" in str(exc_info.value)

    def test_list_projects_with_archived(self) -> None:
        """List projects including archived."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "projects": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [],
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            client.list_projects(include_archived=True)

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            payload = json.loads(request.data.decode("utf-8"))
            assert payload["variables"]["includeArchived"] is True

    def test_list_projects_with_pagination(self) -> None:
        """List projects with multi-page pagination."""
        client = LinearClient(api_key="test-key")

        page1_response = make_mock_response(
            {
                "data": {
                    "projects": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "proj-cursor-1"},
                        "nodes": [
                            {"id": "project-1", "name": "Project 1"},
                            {"id": "project-2", "name": "Project 2"},
                        ],
                    }
                }
            }
        )

        page2_response = make_mock_response(
            {
                "data": {
                    "projects": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {"id": "project-3", "name": "Project 3"},
                        ],
                    }
                }
            }
        )

        with patch(
            "urllib.request.urlopen", side_effect=[page1_response, page2_response]
        ) as mock_urlopen:
            projects = client.list_projects()

            assert mock_urlopen.call_count == 2

        assert len(projects) == 3
        assert projects[0]["id"] == "project-1"
        assert projects[1]["id"] == "project-2"
        assert projects[2]["id"] == "project-3"


# ============================================================================
# TestCreateIssue
# ============================================================================


class TestCreateIssue:
    """Tests for create_issue method."""

    def test_create_issue_minimal(self) -> None:
        """Create issue with minimal required parameters."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "issueCreate": {
                        "success": True,
                        "issue": {
                            "id": "issue-uuid-123",
                            "identifier": "NES-99",
                            "title": "New Issue",
                            "url": "https://linear.app/issue/NES-99",
                            "branchName": "nes-99-new-issue",
                        },
                    }
                }
            }
        )

        with (
            patch.object(client, "_resolve_team_id", return_value="team-uuid"),
            patch("urllib.request.urlopen", return_value=mock_response),
        ):
            result = client.create_issue(title="New Issue", team="NES")

        assert result["id"] == "issue-uuid-123"
        assert result["identifier"] == "NES-99"
        assert result["title"] == "New Issue"

    def test_create_issue_all_parameters(self) -> None:
        """Create issue with all optional parameters."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "issueCreate": {
                        "success": True,
                        "issue": {
                            "id": "issue-uuid-456",
                            "identifier": "NES-100",
                            "title": "Full Issue",
                            "url": "https://linear.app/issue/NES-100",
                            "branchName": "nes-100-full-issue",
                        },
                    }
                }
            }
        )

        with (
            patch.object(client, "_resolve_team_id", return_value="team-uuid"),
            patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen,
        ):
            client.create_issue(
                title="Full Issue",
                team="NES",
                description="Issue description",
                assignee_id="user-uuid",
                project_id="project-uuid",
                priority=2,
                state_id="state-uuid",
                parent_id="parent-uuid",
                label_ids=["label-1", "label-2"],
            )

            # Verify all fields in the input
            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            payload = json.loads(request.data.decode("utf-8"))
            input_data = payload["variables"]["input"]

            assert input_data["title"] == "Full Issue"
            assert input_data["teamId"] == "team-uuid"
            assert input_data["description"] == "Issue description"
            assert input_data["assigneeId"] == "user-uuid"
            assert input_data["projectId"] == "project-uuid"
            assert input_data["priority"] == 2
            assert input_data["stateId"] == "state-uuid"
            assert input_data["parentId"] == "parent-uuid"
            assert input_data["labelIds"] == ["label-1", "label-2"]

    def test_create_issue_team_not_found(self) -> None:
        """Raise error when team is not found."""
        client = LinearClient(api_key="test-key")

        with patch.object(client, "_resolve_team_id", return_value=None):
            with pytest.raises(LinearAPIError) as exc_info:
                client.create_issue(title="Issue", team="nonexistent")

            assert "Team not found" in str(exc_info.value)

    def test_create_issue_invalid_priority(self) -> None:
        """Raise error for invalid priority."""
        client = LinearClient(api_key="test-key")

        with pytest.raises(LinearAPIError) as exc_info:
            client.create_issue(title="Issue", team="NES", priority=5)

        assert "Priority must be between 0 and 4" in str(exc_info.value)

    def test_create_issue_api_failure(self) -> None:
        """Raise error when API returns success=False."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {"data": {"issueCreate": {"success": False, "issue": None}}}
        )

        with (
            patch.object(client, "_resolve_team_id", return_value="team-uuid"),
            patch("urllib.request.urlopen", return_value=mock_response),
        ):
            with pytest.raises(LinearAPIError) as exc_info:
                client.create_issue(title="Issue", team="NES")

            assert "Failed to create issue" in str(exc_info.value)

    def test_create_issue_uses_variables_not_string_interpolation(self) -> None:
        """Verify create_issue uses variables payload (security test)."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "issueCreate": {
                        "success": True,
                        "issue": {
                            "id": "id",
                            "identifier": "NES-1",
                            "title": "t",
                            "url": "u",
                            "branchName": "b",
                        },
                    }
                }
            }
        )

        with (
            patch.object(client, "_resolve_team_id", return_value="team-uuid"),
            patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen,
        ):
            client.create_issue(title="Test", team="NES")

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            payload = json.loads(request.data.decode("utf-8"))

            # Query should use $input variable, not interpolation
            assert "$input" in payload["query"]
            assert "variables" in payload
            assert "input" in payload["variables"]

    def test_create_issue_special_characters_in_title(self) -> None:
        """Special characters in title are properly escaped via variables."""
        client = LinearClient(api_key="test-key")

        special_title = 'Issue with "quotes" and \\backslashes\\ and $special chars'

        mock_response = make_mock_response(
            {
                "data": {
                    "issueCreate": {
                        "success": True,
                        "issue": {
                            "id": "id",
                            "identifier": "NES-1",
                            "title": special_title,
                            "url": "u",
                            "branchName": "b",
                        },
                    }
                }
            }
        )

        with (
            patch.object(client, "_resolve_team_id", return_value="team-uuid"),
            patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen,
        ):
            client.create_issue(title=special_title, team="NES")

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            payload = json.loads(request.data.decode("utf-8"))

            # Title should be in variables, not in query string
            assert payload["variables"]["input"]["title"] == special_title
            # Query should NOT contain the special characters
            assert special_title not in payload["query"]


# ============================================================================
# TestUpdateIssue
# ============================================================================


class TestUpdateIssue:
    """Tests for update_issue method."""

    def test_update_issue_single_field(self) -> None:
        """Update issue with a single field."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "issueUpdate": {
                        "success": True,
                        "issue": {
                            "id": "issue-uuid",
                            "identifier": "NES-123",
                            "title": "Updated Title",
                            "url": "https://linear.app/issue/NES-123",
                            "updatedAt": "2024-12-01T00:00:00Z",
                        },
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = client.update_issue(issue_id="NES-123", title="Updated Title")

        assert result["title"] == "Updated Title"
        assert result["updatedAt"] == "2024-12-01T00:00:00Z"

    def test_update_issue_multiple_fields(self) -> None:
        """Update issue with multiple fields."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "issueUpdate": {
                        "success": True,
                        "issue": {
                            "id": "issue-uuid",
                            "identifier": "NES-123",
                            "title": "New Title",
                            "url": "url",
                            "updatedAt": "now",
                        },
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            client.update_issue(
                issue_id="NES-123",
                title="New Title",
                description="New description",
                priority=1,
            )

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            payload = json.loads(request.data.decode("utf-8"))
            input_data = payload["variables"]["input"]

            assert input_data["title"] == "New Title"
            assert input_data["description"] == "New description"
            assert input_data["priority"] == 1

    def test_update_issue_no_fields_raises(self) -> None:
        """Raise error when no fields are provided to update."""
        client = LinearClient(api_key="test-key")

        with pytest.raises(LinearAPIError) as exc_info:
            client.update_issue(issue_id="NES-123")

        assert "At least one field must be provided" in str(exc_info.value)

    def test_update_issue_invalid_priority(self) -> None:
        """Raise error for invalid priority."""
        client = LinearClient(api_key="test-key")

        with pytest.raises(LinearAPIError) as exc_info:
            client.update_issue(issue_id="NES-123", priority=-1)

        assert "Priority must be between 0 and 4" in str(exc_info.value)

    def test_update_issue_uses_variables(self) -> None:
        """Verify update_issue uses variables payload (security test)."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "issueUpdate": {
                        "success": True,
                        "issue": {
                            "id": "id",
                            "identifier": "i",
                            "title": "t",
                            "url": "u",
                            "updatedAt": "u",
                        },
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            client.update_issue(issue_id="NES-123", title="Test")

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            payload = json.loads(request.data.decode("utf-8"))

            assert "$id" in payload["query"]
            assert "$input" in payload["query"]
            assert "variables" in payload

    def test_update_issue_special_characters_in_description(self) -> None:
        """Special characters in description are properly escaped via variables."""
        client = LinearClient(api_key="test-key")

        special_desc = 'Description with\n"quotes"\n\\backslashes\\ and ${injection}'

        mock_response = make_mock_response(
            {
                "data": {
                    "issueUpdate": {
                        "success": True,
                        "issue": {
                            "id": "id",
                            "identifier": "i",
                            "title": "t",
                            "url": "u",
                            "updatedAt": "u",
                        },
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            client.update_issue(issue_id="NES-123", description=special_desc)

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            payload = json.loads(request.data.decode("utf-8"))

            assert payload["variables"]["input"]["description"] == special_desc
            assert special_desc not in payload["query"]


# ============================================================================
# TestCreateComment
# ============================================================================


class TestCreateComment:
    """Tests for create_comment method."""

    def test_create_comment_success(self) -> None:
        """Successfully create a comment."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "commentCreate": {
                        "success": True,
                        "comment": {
                            "id": "comment-uuid-123",
                            "body": "This is a comment",
                            "createdAt": "2024-12-01T00:00:00Z",
                            "issue": {"id": "issue-uuid"},
                            "user": {
                                "id": "user-uuid",
                                "name": "Test User",
                                "email": "test@example.com",
                            },
                        },
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = client.create_comment(issue_id="NES-123", body="This is a comment")

        assert result["id"] == "comment-uuid-123"
        assert result["body"] == "This is a comment"
        assert result["user"]["name"] == "Test User"

    def test_create_comment_api_failure(self) -> None:
        """Raise error when API returns success=False."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {"data": {"commentCreate": {"success": False, "comment": None}}}
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client.create_comment(issue_id="NES-123", body="Comment")

            assert "Failed to create comment" in str(exc_info.value)

    def test_create_comment_null_response(self) -> None:
        """Raise error when API returns commentCreate as null.

        When the GraphQL API returns data.commentCreate as null (not missing),
        the client should handle this gracefully rather than raising AttributeError.
        """
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response({"data": {"commentCreate": None}})

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client.create_comment(issue_id="NES-123", body="Comment")

            assert "Failed to create comment" in str(exc_info.value)

    def test_create_comment_uses_variables(self) -> None:
        """Verify create_comment uses variables payload (security test)."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "commentCreate": {
                        "success": True,
                        "comment": {
                            "id": "id",
                            "body": "b",
                            "createdAt": "c",
                            "issue": {"id": "i"},
                            "user": None,
                        },
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            client.create_comment(issue_id="NES-123", body="Test comment")

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            payload = json.loads(request.data.decode("utf-8"))

            assert "$input" in payload["query"]
            assert "variables" in payload
            assert payload["variables"]["input"]["body"] == "Test comment"

    def test_create_comment_special_characters(self) -> None:
        """Special characters in body are properly escaped via variables."""
        client = LinearClient(api_key="test-key")

        special_body = (
            '```python\ndef foo():\n    return "bar"\n```\n\n$100 <script>alert(1)</script>'
        )

        mock_response = make_mock_response(
            {
                "data": {
                    "commentCreate": {
                        "success": True,
                        "comment": {
                            "id": "id",
                            "body": special_body,
                            "createdAt": "c",
                            "issue": {"id": "i"},
                            "user": None,
                        },
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            client.create_comment(issue_id="NES-123", body=special_body)

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            payload = json.loads(request.data.decode("utf-8"))

            assert payload["variables"]["input"]["body"] == special_body
            assert special_body not in payload["query"]


# ============================================================================
# TestListComments
# ============================================================================


class TestListComments:
    """Tests for list_comments method."""

    def test_list_comments_success(self) -> None:
        """Successfully list comments for an issue."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "issue": {
                        "id": "issue-uuid",
                        "identifier": "NES-123",
                        "comments": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "id": "comment-1",
                                    "body": "First comment",
                                    "createdAt": "2024-01-01T00:00:00Z",
                                    "updatedAt": "2024-01-01T00:00:00Z",
                                    "user": {
                                        "id": "user-1",
                                        "name": "User One",
                                        "email": "one@test.com",
                                    },
                                },
                                {
                                    "id": "comment-2",
                                    "body": "Second comment",
                                    "createdAt": "2024-01-02T00:00:00Z",
                                    "updatedAt": "2024-01-02T00:00:00Z",
                                    "user": None,
                                },
                            ],
                        },
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = client.list_comments("NES-123")

        assert result["issueId"] == "issue-uuid"
        assert result["issueIdentifier"] == "NES-123"
        assert result["totalCount"] == 2
        assert len(result["comments"]) == 2
        assert result["comments"][0]["body"] == "First comment"
        assert result["comments"][0]["user"]["name"] == "User One"
        assert result["comments"][1]["user"] is None

    def test_list_comments_issue_not_found(self) -> None:
        """Raise error when issue is not found."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response({"data": {"issue": None}})

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client.list_comments("INVALID-999")

            assert "Issue not found" in str(exc_info.value)

    def test_list_comments_with_pagination(self) -> None:
        """List comments with pagination."""
        client = LinearClient(api_key="test-key")

        page1_response = make_mock_response(
            {
                "data": {
                    "issue": {
                        "id": "issue-uuid",
                        "identifier": "NES-123",
                        "comments": {
                            "pageInfo": {"hasNextPage": True, "endCursor": "comment-cursor-1"},
                            "nodes": [
                                {
                                    "id": "comment-1",
                                    "body": "Comment 1",
                                    "createdAt": "c1",
                                    "updatedAt": "u1",
                                    "user": None,
                                },
                            ],
                        },
                    }
                }
            }
        )

        page2_response = make_mock_response(
            {
                "data": {
                    "issue": {
                        "id": "issue-uuid",
                        "identifier": "NES-123",
                        "comments": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "id": "comment-2",
                                    "body": "Comment 2",
                                    "createdAt": "c2",
                                    "updatedAt": "u2",
                                    "user": None,
                                },
                            ],
                        },
                    }
                }
            }
        )

        with patch(
            "urllib.request.urlopen", side_effect=[page1_response, page2_response]
        ) as mock_urlopen:
            result = client.list_comments("NES-123")

            assert mock_urlopen.call_count == 2

        assert result["totalCount"] == 2
        assert result["comments"][0]["id"] == "comment-1"
        assert result["comments"][1]["id"] == "comment-2"

    def test_list_comments_pagination_stall_raises_error(self) -> None:
        """Pagination stall (repeated cursor) raises LinearAPIError."""
        client = LinearClient(api_key="test-key")

        # API returns hasNextPage=True but same endCursor, which would cause infinite loop
        stalled_response = make_mock_response(
            {
                "data": {
                    "issue": {
                        "id": "issue-uuid",
                        "identifier": "NES-123",
                        "comments": {
                            "pageInfo": {"hasNextPage": True, "endCursor": "same-cursor"},
                            "nodes": [
                                {
                                    "id": "c1",
                                    "body": "Comment",
                                    "createdAt": "c",
                                    "updatedAt": "u",
                                    "user": None,
                                }
                            ],
                        },
                    }
                }
            }
        )

        # Second response also returns same cursor - would cause infinite loop
        with patch("urllib.request.urlopen", side_effect=[stalled_response, stalled_response]):
            with pytest.raises(LinearAPIError) as exc_info:
                client.list_comments("NES-123")

            assert "Pagination did not advance" in str(exc_info.value)

    def test_list_comments_null_comments_field(self) -> None:
        """Handle API returning null for comments field without AttributeError."""
        client = LinearClient(api_key="test-key")

        # API returns null instead of comments object
        mock_response = make_mock_response(
            {
                "data": {
                    "issue": {
                        "id": "issue-uuid",
                        "identifier": "NES-123",
                        "comments": None,  # null from API
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = client.list_comments("NES-123")

        assert result["issueId"] == "issue-uuid"
        assert result["issueIdentifier"] == "NES-123"
        assert result["totalCount"] == 0
        assert result["comments"] == []


# ============================================================================
# TestFetchGithubAttachments
# ============================================================================


class TestFetchGithubAttachments:
    """Tests for fetch_github_attachments method."""

    def test_fetch_attachments_success(self) -> None:
        """Successfully fetch GitHub attachments."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "issue": {
                        "attachments": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {"url": "https://github.com/org/repo/pull/1", "title": "PR #1"},
                                {"url": "https://github.com/org/repo/pull/2", "title": "PR #2"},
                            ],
                        }
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            attachments = client.fetch_github_attachments("NES-123")

        assert len(attachments) == 2
        assert attachments[0]["url"] == "https://github.com/org/repo/pull/1"

    def test_fetch_attachments_issue_not_found(self) -> None:
        """Return empty list when issue has no attachments or not found."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response({"data": {"issue": None}})

        with patch("urllib.request.urlopen", return_value=mock_response):
            attachments = client.fetch_github_attachments("INVALID-999")

        assert attachments == []

    def test_fetch_attachments_with_pagination(self) -> None:
        """Fetch attachments with pagination."""
        client = LinearClient(api_key="test-key")

        page1_response = make_mock_response(
            {
                "data": {
                    "issue": {
                        "attachments": {
                            "pageInfo": {"hasNextPage": True, "endCursor": "attach-cursor"},
                            "nodes": [
                                {"url": "https://github.com/org/repo/pull/1", "title": "PR #1"}
                            ],
                        }
                    }
                }
            }
        )

        page2_response = make_mock_response(
            {
                "data": {
                    "issue": {
                        "attachments": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {"url": "https://github.com/org/repo/pull/2", "title": "PR #2"}
                            ],
                        }
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", side_effect=[page1_response, page2_response]):
            attachments = client.fetch_github_attachments("NES-123")

        assert len(attachments) == 2


# ============================================================================
# TestGetTicketInfo
# ============================================================================


class TestGetTicketInfo:
    """Tests for get_ticket_info method."""

    def test_get_ticket_info_success(self) -> None:
        """Successfully get ticket info."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "issue": {
                        "id": "issue-uuid-123",
                        "identifier": "NES-123",
                        "title": "Test Issue",
                        "branchName": "nes-123-test-issue",
                        "state": {"id": "state-uuid", "name": "In Progress", "type": "started"},
                        "team": {"id": "team-uuid"},
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            info = client.get_ticket_info("NES-123")

        assert info["id"] == "issue-uuid-123"
        assert info["identifier"] == "NES-123"
        assert info["title"] == "Test Issue"
        assert info["branch_name"] == "nes-123-test-issue"
        assert info["state"] == "In Progress"
        assert info["state_type"] == "started"
        assert info["team_id"] == "team-uuid"

    def test_get_ticket_info_not_found(self) -> None:
        """Raise error when ticket not found."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response({"data": {"issue": None}})

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client.get_ticket_info("INVALID-999")

            assert "Ticket not found" in str(exc_info.value)

    def test_get_ticket_info_null_nested_objects(self) -> None:
        """Handle null state and team gracefully without AttributeError."""
        client = LinearClient(api_key="test-key")

        # API may return null for nested objects like state or team
        mock_response = make_mock_response(
            {
                "data": {
                    "issue": {
                        "id": "issue-uuid-123",
                        "identifier": "NES-123",
                        "title": "Test Issue",
                        "branchName": "nes-123-test-issue",
                        "state": None,  # null from API
                        "team": None,  # null from API
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            info = client.get_ticket_info("NES-123")

        assert info["id"] == "issue-uuid-123"
        assert info["identifier"] == "NES-123"
        assert info["title"] == "Test Issue"
        assert info["branch_name"] == "nes-123-test-issue"
        assert info["state"] is None
        assert info["state_type"] is None
        assert info["team_id"] is None


# ============================================================================
# TestGetDoneStateId
# ============================================================================


class TestGetDoneStateId:
    """Tests for get_done_state_id method."""

    def test_get_done_state_id_success(self) -> None:
        """Successfully get done state ID."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "team": {
                        "states": {
                            "nodes": [
                                {"id": "done-state-uuid", "name": "Done", "type": "completed"},
                            ]
                        }
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            state_id = client.get_done_state_id("team-uuid")

        assert state_id == "done-state-uuid"

    def test_get_done_state_id_team_not_found(self) -> None:
        """Raise error when team is not found (null from API)."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response({"data": {"team": None}})

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client.get_done_state_id("invalid-team-uuid")

            assert "Team not found" in str(exc_info.value)
            assert "invalid-team-uuid" in str(exc_info.value)

    def test_get_done_state_id_not_found(self) -> None:
        """Raise error when no done state found."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response({"data": {"team": {"states": {"nodes": []}}}})

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client.get_done_state_id("team-uuid")

            assert "No 'Done' state found" in str(exc_info.value)

    def test_get_done_state_id_missing_id_field(self) -> None:
        """Raise error when state exists but id field is missing."""
        client = LinearClient(api_key="test-key")

        # API returns a state node but without an id field
        mock_response = make_mock_response(
            {
                "data": {
                    "team": {
                        "states": {
                            "nodes": [
                                {"name": "Done", "type": "completed"},  # missing "id"
                            ]
                        }
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client.get_done_state_id("team-uuid")

            assert "No 'Done' state ID found" in str(exc_info.value)

    def test_get_done_state_id_null_id_field(self) -> None:
        """Raise error when state exists but id field is null."""
        client = LinearClient(api_key="test-key")

        # API returns a state node but with null id
        mock_response = make_mock_response(
            {
                "data": {
                    "team": {
                        "states": {
                            "nodes": [
                                {"id": None, "name": "Done", "type": "completed"},
                            ]
                        }
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(LinearAPIError) as exc_info:
                client.get_done_state_id("team-uuid")

            assert "No 'Done' state ID found" in str(exc_info.value)


# ============================================================================
# TestSetTicketState
# ============================================================================


class TestSetTicketState:
    """Tests for set_ticket_state method."""

    def test_set_ticket_state_success(self) -> None:
        """Successfully set ticket state returns dict with stateName."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "issueUpdate": {
                        "success": True,
                        "issue": {"state": {"name": "Done"}},
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = client.set_ticket_state("issue-uuid", "done-state-uuid")

        assert result == {"stateName": "Done"}

    def test_set_ticket_state_failure(self) -> None:
        """Raise LinearAPIError when state update fails."""
        client = LinearClient(api_key="test-key")

        mock_response = make_mock_response(
            {"data": {"issueUpdate": {"success": False, "issue": None}}}
        )

        with (
            patch("urllib.request.urlopen", return_value=mock_response),
            pytest.raises(LinearAPIError) as exc_info,
        ):
            client.set_ticket_state("issue-uuid", "invalid-state-uuid")

        assert "Failed to update state for issue: issue-uuid" in str(exc_info.value)


# ============================================================================
# TestBackwardsCompatibleFunctions
# ============================================================================


class TestBackwardsCompatibleFunctions:
    """Tests for backwards-compatible module-level functions."""

    @pytest.fixture(autouse=True)
    def reset_default_client(self) -> Generator[None]:
        """Reset the default client before and after each test."""
        import scripts.pr.linear_dao as linear_dao_module

        linear_dao_module._default_client = None
        yield
        linear_dao_module._default_client = None

    def test_get_linear_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_get_linear_api_key returns key from environment."""
        monkeypatch.setenv("LINEAR_API_KEY", "env-key-value")
        assert _get_linear_api_key() == "env-key-value"

    def test_get_linear_api_key_raises_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_get_linear_api_key raises when env var not set."""
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        with pytest.raises(LinearAPIError) as exc_info:
            _get_linear_api_key()
        assert "LINEAR_API_KEY environment variable not set" in str(exc_info.value)

    def test_get_default_client_creates_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_get_default_client creates and caches a LinearClient instance."""
        monkeypatch.setenv("LINEAR_API_KEY", "test-key")

        client = _get_default_client()
        assert isinstance(client, LinearClient)

        # Second call should return same instance
        client2 = _get_default_client()
        assert client is client2

    def test_run_linear_graphql_delegates_to_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_run_linear_graphql delegates to default client."""
        monkeypatch.setenv("LINEAR_API_KEY", "test-key")

        mock_response = make_mock_response({"data": {"viewer": {"id": "123"}}})

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = _run_linear_graphql("query { viewer { id } }")

        assert result["data"]["viewer"]["id"] == "123"

    def test_fetch_github_attachments_delegates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """fetch_github_attachments free function delegates to default client."""
        monkeypatch.setenv("LINEAR_API_KEY", "test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "issue": {
                        "attachments": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [{"url": "https://github.com/pr/1", "title": "PR"}],
                        }
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            attachments = fetch_github_attachments("NES-123")

        assert len(attachments) == 1
        assert attachments[0]["url"] == "https://github.com/pr/1"

    def test_get_ticket_info_delegates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_ticket_info free function delegates to default client."""
        monkeypatch.setenv("LINEAR_API_KEY", "test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "issue": {
                        "id": "uuid",
                        "identifier": "NES-1",
                        "title": "Title",
                        "branchName": "branch",
                        "state": {"id": "s", "name": "State", "type": "started"},
                        "team": {"id": "t"},
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            info = get_ticket_info("NES-1")

        assert info["identifier"] == "NES-1"

    def test_get_done_state_id_delegates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_done_state_id free function delegates to default client."""
        monkeypatch.setenv("LINEAR_API_KEY", "test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "team": {
                        "states": {
                            "nodes": [{"id": "done-id", "name": "Done", "type": "completed"}]
                        }
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            state_id = get_done_state_id("team-uuid")

        assert state_id == "done-id"

    def test_set_ticket_state_delegates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """set_ticket_state free function delegates to default client."""
        monkeypatch.setenv("LINEAR_API_KEY", "test-key")

        mock_response = make_mock_response(
            {
                "data": {
                    "issueUpdate": {
                        "success": True,
                        "issue": {"state": {"name": "Done"}},
                    }
                }
            }
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = set_ticket_state("issue-uuid", "state-uuid")

        assert result is True
