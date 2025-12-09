"""Unit tests for the Linear client Python wrapper.

These tests verify that the LinearClient wrapper correctly handles initialization,
GraphQL API calls, JSON parsing, and error handling without making actual API calls.
"""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from scripts.clients.linear_client import LinearClient, LinearClientError


def create_mock_response(data: dict[str, Any]) -> MagicMock:
    """Create a mock HTTP response with the given data.

    Args:
        data: Dictionary to return as JSON response body.

    Returns:
        Mock object that behaves like an HTTP response.
    """
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(data).encode("utf-8")
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    return mock_response


class TestLinearClientInit:
    """Test LinearClient initialization and configuration."""

    def test_init_with_api_key(self) -> None:
        """Initialize client with explicit API key."""
        client = LinearClient(api_key="test_api_key")
        assert client._api_key == "test_api_key"

    def test_init_with_api_key_strips_whitespace(self) -> None:
        """Initialize client with API key strips leading/trailing whitespace."""
        client = LinearClient(api_key="  test_api_key  ")
        assert client._api_key == "test_api_key"

    def test_init_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Initialize client from LINEAR_API_KEY environment variable."""
        monkeypatch.setenv("LINEAR_API_KEY", "env_api_key")
        client = LinearClient()
        assert client._api_key == "env_api_key"

    def test_init_from_env_strips_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Initialize client from env variable strips leading/trailing whitespace."""
        monkeypatch.setenv("LINEAR_API_KEY", "  env_api_key  ")
        client = LinearClient()
        assert client._api_key == "env_api_key"

    def test_init_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Raise error when no API key is provided or in environment."""
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        with pytest.raises(LinearClientError) as exc_info:
            LinearClient()
        assert exc_info.value.code == "MISSING_API_KEY"
        assert "LINEAR_API_KEY must be provided" in exc_info.value.message

    def test_init_does_not_validate_scripts_directory(self) -> None:
        """Client initialization does not check scripts directory existence.

        The scripts directory is only validated when a script is actually invoked.
        """
        # Client should initialize even if scripts directory doesn't exist
        # (the check happens in _run_script, not __init__)
        client = LinearClient(api_key="test_key")
        assert client._api_key == "test_key"


class TestLinearClientGetIssue:
    """Test the get_issue method."""

    def test_get_issue_success(self, mocker: MockerFixture) -> None:
        """Successfully fetch issue details."""
        mock_response = {
            "data": {
                "issue": {
                    "id": "issue-123",
                    "identifier": "NES-24",
                    "title": "Test Issue",
                    "description": "Test description",
                    "url": "https://linear.app/issue/NES-24",
                    "branchName": "nes-24-test-issue",
                    "priority": 2,
                    "estimate": None,
                    "createdAt": "2025-01-01T00:00:00Z",
                    "updatedAt": "2025-01-02T00:00:00Z",
                    "completedAt": None,
                    "canceledAt": None,
                    "dueDate": None,
                    "team": None,
                    "assignee": None,
                    "state": None,
                    "project": None,
                    "parent": None,
                    "comments": {"totalCount": 0},
                    "children": {"totalCount": 0},
                }
            }
        }

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value = create_mock_response(mock_response)

        client = LinearClient(api_key="test_key")
        result = client.get_issue("NES-24")

        assert result["id"] == "issue-123"
        assert result["identifier"] == "NES-24"
        assert result["title"] == "Test Issue"

        # Verify urlopen was called
        mock_urlopen.assert_called_once()

    def test_get_issue_not_found(self, mocker: MockerFixture) -> None:
        """Raise error when issue is not found."""
        mock_response = {"data": {"issue": None}}

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value = create_mock_response(mock_response)

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("INVALID-999")

        assert exc_info.value.code == "NOT_FOUND"
        assert "INVALID-999" in exc_info.value.message

    def test_get_issue_parse_error(self, mocker: MockerFixture) -> None:
        """Raise error when JSON parsing fails."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"Invalid JSON"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value = mock_response

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        assert exc_info.value.code == "PARSE_ERROR"


class TestLinearClientCreateIssue:
    """Test the create_issue method."""

    def test_create_issue_success(self, mocker: MockerFixture) -> None:
        """Successfully create a new issue."""
        # First call: list_teams for team resolution
        teams_response = {
            "data": {
                "teams": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {"id": "team-uuid-123", "name": "Nexus", "key": "NES"},
                    ],
                }
            }
        }
        # Second call: issueCreate mutation
        create_response = {
            "data": {
                "issueCreate": {
                    "success": True,
                    "issue": {
                        "id": "new-issue-123",
                        "identifier": "NES-99",
                        "title": "New Feature",
                        "url": "https://linear.app/issue/NES-99",
                        "branchName": "nes-99-new-feature",
                    },
                }
            }
        }

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.side_effect = [
            create_mock_response(teams_response),
            create_mock_response(create_response),
        ]

        client = LinearClient(api_key="test_key")
        result = client.create_issue(
            team="NES",
            title="New Feature",
            description="Feature description",
            priority=2,
        )

        assert result["identifier"] == "NES-99"
        assert result["title"] == "New Feature"

    def test_create_issue_empty_team(self, mocker: MockerFixture) -> None:
        """Raise error when team is an empty string."""
        # Empty team will cause _resolve_team_id to return None
        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client.create_issue(team="", title="Test")

        assert exc_info.value.code == "NOT_FOUND"

    def test_create_issue_without_optional_params(self, mocker: MockerFixture) -> None:
        """Create issue with only required parameters."""
        # First call: list_teams for team resolution
        teams_response = {
            "data": {
                "teams": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {"id": "team-uuid-123", "name": "Nexus", "key": "NES"},
                    ],
                }
            }
        }
        # Second call: issueCreate mutation
        create_response = {
            "data": {
                "issueCreate": {
                    "success": True,
                    "issue": {
                        "id": "new-issue-456",
                        "identifier": "NES-100",
                        "title": "Simple Issue",
                        "url": "https://linear.app/issue/NES-100",
                        "branchName": "nes-100-simple-issue",
                    },
                }
            }
        }

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.side_effect = [
            create_mock_response(teams_response),
            create_mock_response(create_response),
        ]

        client = LinearClient(api_key="test_key")
        result = client.create_issue(team="NES", title="Simple Issue")

        assert result["identifier"] == "NES-100"


class TestLinearClientUpdateIssue:
    """Test the update_issue method."""

    def test_update_issue_success(self, mocker: MockerFixture) -> None:
        """Successfully update an existing issue."""
        mock_response = {
            "data": {
                "issueUpdate": {
                    "success": True,
                    "issue": {
                        "id": "issue-123",
                        "identifier": "NES-24",
                        "title": "Updated Title",
                        "url": "https://linear.app/issue/NES-24",
                        "updatedAt": "2025-01-03T00:00:00Z",
                    },
                }
            }
        }

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value = create_mock_response(mock_response)

        client = LinearClient(api_key="test_key")
        result = client.update_issue(
            issue_id="NES-24",
            title="Updated Title",
            priority=1,
        )

        assert result["title"] == "Updated Title"
        assert result["updatedAt"] == "2025-01-03T00:00:00Z"

    def test_update_issue_partial_update(self, mocker: MockerFixture) -> None:
        """Update only some fields of an issue."""
        mock_response = {
            "data": {
                "issueUpdate": {
                    "success": True,
                    "issue": {
                        "id": "issue-123",
                        "identifier": "NES-24",
                        "title": "Original Title",
                        "url": "https://linear.app/issue/NES-24",
                        "updatedAt": "2025-01-03T00:00:00Z",
                    },
                }
            }
        }

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value = create_mock_response(mock_response)

        client = LinearClient(api_key="test_key")
        result = client.update_issue(issue_id="NES-24", priority=3)

        assert result["identifier"] == "NES-24"

    def test_update_issue_no_updates_error(self, mocker: MockerFixture) -> None:
        """Raise NO_UPDATES error when no updatable fields are provided."""
        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            # Only issue_id provided, no updatable fields
            client.update_issue(issue_id="NES-24")

        assert exc_info.value.code == "NO_UPDATES"
        assert "At least one field must be provided" in exc_info.value.message


class TestLinearClientComments:
    """Test comment-related methods."""

    def test_list_comments_success(self, mocker: MockerFixture) -> None:
        """Successfully list comments on an issue."""
        mock_response = {
            "data": {
                "issue": {
                    "id": "issue-123",
                    "identifier": "NES-24",
                    "comments": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                "id": "comment-1",
                                "body": "First comment",
                                "createdAt": "2025-01-01T00:00:00Z",
                                "updatedAt": "2025-01-01T00:00:00Z",
                                "user": {
                                    "id": "user-1",
                                    "name": "Test User",
                                    "email": "test@example.com",
                                },
                            },
                            {
                                "id": "comment-2",
                                "body": "Second comment",
                                "createdAt": "2025-01-02T00:00:00Z",
                                "updatedAt": "2025-01-02T00:00:00Z",
                                "user": {
                                    "id": "user-2",
                                    "name": "Another User",
                                    "email": "another@example.com",
                                },
                            },
                        ],
                    },
                }
            }
        }

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value = create_mock_response(mock_response)

        client = LinearClient(api_key="test_key")
        result = client.list_comments("NES-24")

        assert len(result["comments"]) == 2
        assert result["comments"][0]["body"] == "First comment"
        assert result["comments"][1]["body"] == "Second comment"
        assert result["comments"][0]["user"]["name"] == "Test User"

    def test_list_comments_empty(self, mocker: MockerFixture) -> None:
        """Return empty list when no comments exist."""
        mock_response = {
            "data": {
                "issue": {
                    "id": "issue-123",
                    "identifier": "NES-24",
                    "comments": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [],
                    },
                }
            }
        }

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value = create_mock_response(mock_response)

        client = LinearClient(api_key="test_key")
        result = client.list_comments("NES-24")

        assert len(result["comments"]) == 0
        assert isinstance(result["comments"], list)

    def test_create_comment_success(self, mocker: MockerFixture) -> None:
        """Successfully create a comment on an issue."""
        mock_response = {
            "data": {
                "commentCreate": {
                    "success": True,
                    "comment": {
                        "id": "comment-new",
                        "body": "New comment",
                        "createdAt": "2025-01-03T00:00:00Z",
                        "issue": {"id": "issue-123"},
                        "user": {"id": "user-1", "name": "Test User", "email": "test@example.com"},
                    },
                }
            }
        }

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value = create_mock_response(mock_response)

        client = LinearClient(api_key="test_key")
        result = client.create_comment(issue_id="NES-24", body="New comment")

        assert result["id"] == "comment-new"
        assert result["body"] == "New comment"


class TestLinearClientListProjects:
    """Test the list_projects method."""

    def test_list_projects_success(self, mocker: MockerFixture) -> None:
        """Successfully list all projects."""
        mock_response = {
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
                            "createdAt": "2025-01-01T00:00:00Z",
                            "updatedAt": "2025-01-02T00:00:00Z",
                            "archivedAt": None,
                            "state": "in_progress",
                        },
                        {
                            "id": "project-2",
                            "name": "Project Beta",
                            "description": None,
                            "url": "https://linear.app/project/beta",
                            "slugId": "beta",
                            "createdAt": "2025-01-01T00:00:00Z",
                            "updatedAt": "2025-01-02T00:00:00Z",
                            "archivedAt": None,
                            "state": "planned",
                        },
                    ],
                }
            }
        }

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value = create_mock_response(mock_response)

        client = LinearClient(api_key="test_key")
        projects = client.list_projects()

        assert len(projects) == 2
        assert projects[0]["name"] == "Project Alpha"
        assert projects[1]["name"] == "Project Beta"

    def test_list_projects_empty(self, mocker: MockerFixture) -> None:
        """Return empty list when no projects exist."""
        mock_response = {
            "data": {
                "projects": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [],
                }
            }
        }

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value = create_mock_response(mock_response)

        client = LinearClient(api_key="test_key")
        projects = client.list_projects()

        assert len(projects) == 0
        assert isinstance(projects, list)

    def test_list_projects_flattens_teams(self, mocker: MockerFixture) -> None:
        """Verify teams.nodes is flattened to teams list."""
        mock_response = {
            "data": {
                "projects": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {
                            "id": "project-1",
                            "name": "Project Alpha",
                            "teams": {
                                "nodes": [
                                    {"id": "team-1", "name": "Engineering", "key": "ENG"},
                                    {"id": "team-2", "name": "Design", "key": "DES"},
                                ]
                            },
                        },
                        {
                            "id": "project-2",
                            "name": "Project Beta",
                            "teams": {
                                "nodes": [{"id": "team-1", "name": "Engineering", "key": "ENG"}]
                            },
                        },
                    ],
                }
            }
        }

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value = create_mock_response(mock_response)

        client = LinearClient(api_key="test_key")
        projects = client.list_projects()

        # Verify teams is now a flat list, not nested under nodes
        assert len(projects) == 2
        assert isinstance(projects[0]["teams"], list)
        assert len(projects[0]["teams"]) == 2
        assert projects[0]["teams"][0]["key"] == "ENG"
        assert projects[0]["teams"][1]["key"] == "DES"
        assert isinstance(projects[1]["teams"], list)
        assert len(projects[1]["teams"]) == 1


class TestLinearClientListTeams:
    """Test the list_teams method."""

    def test_list_teams_success(self, mocker: MockerFixture) -> None:
        """Successfully list all teams."""
        mock_response = {
            "data": {
                "teams": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {
                            "id": "team-1",
                            "name": "Engineering",
                            "key": "ENG",
                            "description": "Engineering team",
                            "createdAt": "2025-01-01T00:00:00Z",
                            "updatedAt": "2025-01-02T00:00:00Z",
                            "archivedAt": None,
                            "private": False,
                            "timezone": "America/New_York",
                        },
                        {
                            "id": "team-2",
                            "name": "Nexus",
                            "key": "NES",
                            "description": None,
                            "createdAt": "2025-01-01T00:00:00Z",
                            "updatedAt": "2025-01-02T00:00:00Z",
                            "archivedAt": None,
                            "private": True,
                            "timezone": None,
                        },
                    ],
                }
            }
        }

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value = create_mock_response(mock_response)

        client = LinearClient(api_key="test_key")
        teams = client.list_teams()

        assert len(teams) == 2
        assert teams[0]["key"] == "ENG"
        assert teams[1]["key"] == "NES"

    def test_list_teams_empty(self, mocker: MockerFixture) -> None:
        """Return empty list when no teams exist."""
        mock_response = {
            "data": {
                "teams": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [],
                }
            }
        }

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value = create_mock_response(mock_response)

        client = LinearClient(api_key="test_key")
        teams = client.list_teams()

        assert len(teams) == 0
        assert isinstance(teams, list)

    def test_list_teams_caching(self, mocker: MockerFixture) -> None:
        """Verify list_teams caches results to avoid redundant API calls."""
        mock_response = {
            "data": {
                "teams": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {
                            "id": "team-1",
                            "name": "Engineering",
                            "key": "ENG",
                            "description": "Engineering team",
                            "createdAt": "2025-01-01T00:00:00Z",
                            "updatedAt": "2025-01-02T00:00:00Z",
                            "archivedAt": None,
                            "private": False,
                            "timezone": "America/New_York",
                        },
                    ],
                }
            }
        }

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value = create_mock_response(mock_response)

        client = LinearClient(api_key="test_key")

        # First call should hit the API
        teams1 = client.list_teams()
        assert mock_urlopen.call_count == 1
        assert len(teams1) == 1

        # Second call should use cache, no additional API call
        teams2 = client.list_teams()
        assert mock_urlopen.call_count == 1  # Still 1, not 2
        assert teams1 is teams2  # Same list object from cache

    def test_list_teams_caching_per_include_archived(self, mocker: MockerFixture) -> None:
        """Verify caching is separate for include_archived True/False."""
        mock_response_active = {
            "data": {
                "teams": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [{"id": "team-1", "name": "Active", "key": "ACT"}],
                }
            }
        }
        mock_response_all = {
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

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.side_effect = [
            create_mock_response(mock_response_active),
            create_mock_response(mock_response_all),
        ]

        client = LinearClient(api_key="test_key")

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


class TestLinearClientErrorHandling:
    """Test error handling and edge cases."""

    def test_http_error_handling(self, mocker: MockerFixture) -> None:
        """Raise API_ERROR on HTTP errors from urlopen."""
        import urllib.error

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.linear.app/graphql",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=None,
        )

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        assert exc_info.value.code == "API_ERROR"
        assert "401" in exc_info.value.message

    def test_url_error_handling(self, mocker: MockerFixture) -> None:
        """Raise API_ERROR on URLError from urlopen."""
        import urllib.error

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        assert exc_info.value.code == "API_ERROR"
        assert "Connection refused" in exc_info.value.message

    def test_invalid_json_handling(self, mocker: MockerFixture) -> None:
        """Handle malformed JSON responses."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"ok": true, invalid json'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value = mock_response

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        assert exc_info.value.code == "PARSE_ERROR"

    def test_api_key_not_in_error_messages(self, mocker: MockerFixture) -> None:
        """Ensure API key is not leaked in error messages."""
        # GraphQL error response
        mock_response = {"errors": [{"message": "Invalid API key provided"}]}

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value = create_mock_response(mock_response)

        client = LinearClient(api_key="test-linear-api-key-12345")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        # Verify the API key is not in the error message
        error_message = str(exc_info.value)
        assert "test-linear-api-key-12345" not in error_message
        assert "GRAPHQL_ERROR" in error_message

    def test_graphql_error_handling(self, mocker: MockerFixture) -> None:
        """Handle GraphQL errors from the API."""
        mock_response = {
            "errors": [
                {"message": "Field 'issue' not found"},
                {"message": "Invalid query"},
            ]
        }

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value = create_mock_response(mock_response)

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        assert exc_info.value.code == "GRAPHQL_ERROR"
        assert "Field 'issue' not found" in exc_info.value.message

    def test_empty_response_data(self, mocker: MockerFixture) -> None:
        """Handle empty data in successful response."""
        mock_response = {"data": {"issue": None}}

        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value = create_mock_response(mock_response)

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        # Should raise NOT_FOUND when issue is None
        assert exc_info.value.code == "NOT_FOUND"


class TestLinearCLIOutputFormat:
    """Test that linear_cli.py output matches TypeScript CLI contract."""

    def test_list_projects_output_format(
        self, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify list_projects outputs data nested under 'projects' key."""
        from scripts.clients import linear_cli

        mock_projects = [
            {"id": "project-1", "name": "Project Alpha"},
            {"id": "project-2", "name": "Project Beta"},
        ]

        mocker.patch.object(linear_cli, "LinearClient")
        linear_cli.LinearClient.return_value.list_projects.return_value = mock_projects

        linear_cli.list_projects()
        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["ok"] is True
        assert "data" in output
        assert "projects" in output["data"]
        assert output["data"]["projects"] == mock_projects

    def test_list_teams_output_format(
        self, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify list_teams outputs data nested under 'teams' key."""
        from scripts.clients import linear_cli

        mock_teams = [
            {"id": "team-1", "name": "Engineering", "key": "ENG"},
            {"id": "team-2", "name": "Nexus", "key": "NES"},
        ]

        mocker.patch.object(linear_cli, "LinearClient")
        linear_cli.LinearClient.return_value.list_teams.return_value = mock_teams

        linear_cli.list_teams()
        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["ok"] is True
        assert "data" in output
        assert "teams" in output["data"]
        assert output["data"]["teams"] == mock_teams

    def test_list_comments_output_format(
        self, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify list_comments outputs data nested under 'comments' key."""
        from scripts.clients import linear_cli

        mock_comments = [
            {"id": "comment-1", "body": "First comment"},
            {"id": "comment-2", "body": "Second comment"},
        ]

        mocker.patch.object(linear_cli, "LinearClient")
        linear_cli.LinearClient.return_value.list_comments.return_value = mock_comments

        linear_cli.list_comments("NES-24")
        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["ok"] is True
        assert "data" in output
        assert "comments" in output["data"]
        assert output["data"]["comments"] == mock_comments

    def test_get_issue_output_format(
        self, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify get_issue outputs data directly (not nested in a list key)."""
        from scripts.clients import linear_cli

        mock_issue = {
            "id": "issue-123",
            "identifier": "NES-24",
            "title": "Test Issue",
        }

        mocker.patch.object(linear_cli, "LinearClient")
        linear_cli.LinearClient.return_value.get_issue.return_value = mock_issue

        linear_cli.get_issue("NES-24")
        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["ok"] is True
        assert "data" in output
        # For scalar returns, data is the object directly (not nested)
        assert output["data"] == mock_issue

    def test_create_issue_output_format(
        self, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify create_issue outputs data directly (not nested in a list key)."""
        from scripts.clients import linear_cli

        mock_issue = {
            "id": "new-issue-123",
            "identifier": "NES-99",
            "title": "New Feature",
        }

        mocker.patch.object(linear_cli, "LinearClient")
        linear_cli.LinearClient.return_value.create_issue.return_value = mock_issue

        linear_cli.create_issue(team="NES", title="New Feature")
        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["ok"] is True
        assert "data" in output
        assert output["data"] == mock_issue

    def test_create_comment_output_format(
        self, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify create_comment outputs data directly (not nested in a list key)."""
        from scripts.clients import linear_cli

        mock_comment = {
            "id": "comment-new",
            "body": "New comment",
        }

        mocker.patch.object(linear_cli, "LinearClient")
        linear_cli.LinearClient.return_value.create_comment.return_value = mock_comment

        linear_cli.create_comment(issue_id="NES-24", body="New comment")
        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["ok"] is True
        assert "data" in output
        assert output["data"] == mock_comment

    def test_missing_command_outputs_json_error(
        self, capsys: pytest.CaptureFixture[str], mocker: MockerFixture
    ) -> None:
        """Verify that missing command outputs JSON error, not usage text."""
        from scripts.clients import linear_cli

        # Simulate running with no command
        mocker.patch("sys.argv", ["linear"])

        with pytest.raises(SystemExit) as exc_info:
            linear_cli.main()

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["ok"] is False
        assert "error" in output
        assert output["error"]["code"] == "INVALID_INPUT"
        assert "command is required" in output["error"]["message"]

    def test_invalid_argument_outputs_json_error(
        self, capsys: pytest.CaptureFixture[str], mocker: MockerFixture
    ) -> None:
        """Verify that invalid arguments output JSON error, not usage text."""
        from scripts.clients import linear_cli

        # Simulate passing an invalid command
        mocker.patch("sys.argv", ["linear", "create-issue", "--invalid-option", "value"])

        with pytest.raises(SystemExit) as exc_info:
            linear_cli.main()

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["ok"] is False
        assert "error" in output
        assert output["error"]["code"] == "INVALID_INPUT"

    def test_missing_required_argument_outputs_json_error(
        self, capsys: pytest.CaptureFixture[str], mocker: MockerFixture
    ) -> None:
        """Verify that missing required argument outputs JSON error."""
        from scripts.clients import linear_cli

        # create-issue requires --team and --title
        mocker.patch("sys.argv", ["linear", "create-issue"])

        with pytest.raises(SystemExit) as exc_info:
            linear_cli.main()

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["ok"] is False
        assert "error" in output
        assert output["error"]["code"] == "INVALID_INPUT"
        assert "--team" in output["error"]["message"]


class TestLinearClientNetworkErrors:
    """Test network error handling in _run_graphql."""

    def test_timeout_error_raises_api_error(self, mocker: MockerFixture) -> None:
        """Verify TimeoutError is caught and wrapped as LinearClientError."""

        # Mock urlopen to raise TimeoutError
        mocker.patch(
            "urllib.request.urlopen",
            side_effect=TimeoutError("timed out"),
        )

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client._run_graphql("query { viewer { id } }", timeout=30)

        assert exc_info.value.code == "API_ERROR"
        assert "timed out" in exc_info.value.message
        assert "30 seconds" in exc_info.value.message

    def test_timeout_error_includes_custom_timeout_value(self, mocker: MockerFixture) -> None:
        """Verify TimeoutError message includes the configured timeout value."""

        mocker.patch(
            "urllib.request.urlopen",
            side_effect=TimeoutError("timed out"),
        )

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client._run_graphql("query { viewer { id } }", timeout=60)

        assert "60 seconds" in exc_info.value.message

    def test_socket_timeout_raises_api_error(self, mocker: MockerFixture) -> None:
        """Verify socket.timeout is caught and wrapped as LinearClientError."""

        # Mock urlopen to raise socket.timeout
        mocker.patch(
            "urllib.request.urlopen",
            side_effect=TimeoutError("timed out"),
        )

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client._run_graphql("query { viewer { id } }", timeout=30)

        assert exc_info.value.code == "API_ERROR"
        assert "timed out" in exc_info.value.message
        assert "30 seconds" in exc_info.value.message

    def test_socket_timeout_includes_custom_timeout_value(self, mocker: MockerFixture) -> None:
        """Verify socket.timeout error message includes the configured timeout value."""

        mocker.patch(
            "urllib.request.urlopen",
            side_effect=TimeoutError("timed out"),
        )

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client._run_graphql("query { viewer { id } }", timeout=60)

        assert "60 seconds" in exc_info.value.message

    def test_json_serialization_error_raises_parse_error(self, mocker: MockerFixture) -> None:
        """Verify TypeError from json.dumps is wrapped as LinearClientError."""

        # Create a non-serializable object
        class NonSerializable:
            pass

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client._run_graphql(
                "query { viewer { id } }",
                variables={"bad": NonSerializable()},
            )

        assert exc_info.value.code == "PARSE_ERROR"
        assert "Failed to serialize request payload to JSON" in exc_info.value.message


class TestFetchGitHubAttachments:
    """Tests for fetch_github_attachments method."""

    def test_fetch_attachments_success(self, mocker: MockerFixture) -> None:
        """Successfully fetch GitHub attachments."""
        mock_response = create_mock_response(
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
        mocker.patch("urllib.request.urlopen", return_value=mock_response)

        client = LinearClient(api_key="test-key")
        attachments = client.fetch_github_attachments("NES-123")

        assert len(attachments) == 2
        assert attachments[0]["url"] == "https://github.com/org/repo/pull/1"
        assert attachments[1]["url"] == "https://github.com/org/repo/pull/2"

    def test_fetch_attachments_ticket_not_found_raises(self, mocker: MockerFixture) -> None:
        """Raise NOT_FOUND error when ticket does not exist."""
        mock_response = create_mock_response({"data": {"issue": None}})
        mocker.patch("urllib.request.urlopen", return_value=mock_response)

        client = LinearClient(api_key="test-key")
        with pytest.raises(LinearClientError) as exc_info:
            client.fetch_github_attachments("INVALID-999")

        assert exc_info.value.code == "NOT_FOUND"
        assert "Ticket not found: INVALID-999" in exc_info.value.message

    def test_fetch_attachments_with_pagination(self, mocker: MockerFixture) -> None:
        """Fetch attachments across multiple pages."""
        page1_response = create_mock_response(
            {
                "data": {
                    "issue": {
                        "attachments": {
                            "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                            "nodes": [
                                {"url": "https://github.com/org/repo/pull/1", "title": "PR #1"}
                            ],
                        }
                    }
                }
            }
        )
        page2_response = create_mock_response(
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
        mocker.patch("urllib.request.urlopen", side_effect=[page1_response, page2_response])

        client = LinearClient(api_key="test-key")
        attachments = client.fetch_github_attachments("NES-123")

        assert len(attachments) == 2
        assert attachments[0]["url"] == "https://github.com/org/repo/pull/1"
        assert attachments[1]["url"] == "https://github.com/org/repo/pull/2"
