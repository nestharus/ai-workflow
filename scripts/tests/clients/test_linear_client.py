"""Unit tests for the Linear client Python wrapper.

These tests verify that the LinearClient wrapper correctly handles initialization,
subprocess execution, JSON parsing, and error handling without making actual API calls.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.clients.linear_client import LinearClient, LinearClientError


class TestLinearClientInit:
    """Test LinearClient initialization and configuration."""

    def test_init_with_api_key(self) -> None:
        """Initialize client with explicit API key."""
        client = LinearClient(api_key="test_api_key")
        assert client._api_key == "test_api_key"

    def test_init_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Initialize client from LINEAR_API_KEY environment variable."""
        monkeypatch.setenv("LINEAR_API_KEY", "env_api_key")
        client = LinearClient()
        assert client._api_key == "env_api_key"

    def test_init_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Raise error when no API key is provided or in environment."""
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        with pytest.raises(LinearClientError) as exc_info:
            LinearClient()
        assert exc_info.value.code == "MISSING_API_KEY"
        assert "LINEAR_API_KEY must be provided" in exc_info.value.message

    def test_init_validates_scripts_directory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Raise error when scripts directory does not exist."""
        # Create client normally first to get the actual scripts_dir
        client = LinearClient(api_key="test_key")
        original_scripts_dir = client._scripts_dir

        # Mock the scripts directory to point to non-existent location
        monkeypatch.setattr(
            Path,
            "exists",
            lambda self: self != original_scripts_dir,
        )

        with pytest.raises(LinearClientError) as exc_info:
            LinearClient(api_key="test_key")
        assert exc_info.value.code == "SCRIPTS_NOT_FOUND"


class TestLinearClientGetIssue:
    """Test the get_issue method."""

    def test_get_issue_success(self, mocker: MagicMock) -> None:
        """Successfully fetch issue details."""
        mock_response = {
            "ok": True,
            "data": {
                "id": "issue-123",
                "identifier": "NES-24",
                "title": "Test Issue",
                "description": "Test description",
                "url": "https://linear.app/issue/NES-24",
                "branchName": "nes-24-test-issue",
                "priority": 2,
                "createdAt": "2025-01-01T00:00:00Z",
                "updatedAt": "2025-01-02T00:00:00Z",
            },
        }

        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        result = client.get_issue("NES-24")

        assert result["id"] == "issue-123"
        assert result["identifier"] == "NES-24"
        assert result["title"] == "Test Issue"

        # Verify subprocess was called correctly
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert "node" in call_args[0][0]
        assert "--issue-id" in call_args[0][0]
        assert "NES-24" in call_args[0][0]
        assert call_args[1]["env"]["LINEAR_API_KEY"] == "test_key"

    def test_get_issue_not_found(self, mocker: MagicMock) -> None:
        """Raise error when issue is not found."""
        mock_response = {
            "ok": False,
            "error": {"code": "NOT_FOUND", "message": "Issue not found"},
        }

        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("INVALID-999")

        assert exc_info.value.code == "NOT_FOUND"
        assert exc_info.value.message == "Issue not found"

    def test_get_issue_parse_error(self, mocker: MagicMock) -> None:
        """Raise error when JSON parsing fails."""
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = "Invalid JSON"
        mock_run.return_value.stderr = "JSON parse error"
        mock_run.return_value.returncode = 1

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        assert exc_info.value.code == "PARSE_ERROR"
        assert "JSON parse error" in exc_info.value.message


class TestLinearClientCreateIssue:
    """Test the create_issue method."""

    def test_create_issue_success(self, mocker: MagicMock) -> None:
        """Successfully create a new issue."""
        mock_response = {
            "ok": True,
            "data": {
                "id": "new-issue-123",
                "identifier": "NES-99",
                "title": "New Feature",
                "url": "https://linear.app/issue/NES-99",
                "branchName": "nes-99-new-feature",
            },
        }

        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        result = client.create_issue(
            team="NES",
            title="New Feature",
            description="Feature description",
            priority=2,
        )

        assert result["identifier"] == "NES-99"
        assert result["title"] == "New Feature"

        # Verify arguments
        call_args = mock_run.call_args[0][0]
        assert "--team" in call_args
        assert "NES" in call_args
        assert "--title" in call_args
        assert "New Feature" in call_args
        assert "--body" in call_args
        assert "Feature description" in call_args
        assert "--priority" in call_args
        assert "2" in call_args

    def test_create_issue_missing_team(self, mocker: MagicMock) -> None:
        """Raise error when team is not provided."""
        mock_response = {
            "ok": False,
            "error": {"code": "INVALID_INPUT", "message": "Team is required"},
        }

        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError):
            # This will be caught by the wrapper's error handling
            # The actual validation happens in TypeScript, so we simulate the error
            client.create_issue(team="", title="Test")

    def test_create_issue_with_optional_params(self, mocker: MagicMock) -> None:
        """Create issue with only required parameters."""
        mock_response = {
            "ok": True,
            "data": {
                "id": "new-issue-456",
                "identifier": "NES-100",
                "title": "Simple Issue",
                "url": "https://linear.app/issue/NES-100",
                "branchName": "nes-100-simple-issue",
            },
        }

        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        result = client.create_issue(team="NES", title="Simple Issue")

        assert result["identifier"] == "NES-100"

        # Verify only required arguments are passed
        call_args = mock_run.call_args[0][0]
        assert "--team" in call_args
        assert "--title" in call_args
        assert "--body" not in call_args
        assert "--priority" not in call_args


class TestLinearClientUpdateIssue:
    """Test the update_issue method."""

    def test_update_issue_success(self, mocker: MagicMock) -> None:
        """Successfully update an existing issue."""
        mock_response = {
            "ok": True,
            "data": {
                "id": "issue-123",
                "identifier": "NES-24",
                "title": "Updated Title",
                "url": "https://linear.app/issue/NES-24",
                "updatedAt": "2025-01-03T00:00:00Z",
            },
        }

        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        result = client.update_issue(
            issue_id="NES-24",
            title="Updated Title",
            priority=1,
        )

        assert result["title"] == "Updated Title"
        assert result["updatedAt"] == "2025-01-03T00:00:00Z"

        # Verify arguments
        call_args = mock_run.call_args[0][0]
        assert "--issue-id" in call_args
        assert "NES-24" in call_args
        assert "--title" in call_args
        assert "Updated Title" in call_args
        assert "--priority" in call_args
        assert "1" in call_args

    def test_update_issue_partial_update(self, mocker: MagicMock) -> None:
        """Update only some fields of an issue."""
        mock_response = {
            "ok": True,
            "data": {
                "id": "issue-123",
                "identifier": "NES-24",
                "title": "Original Title",
                "url": "https://linear.app/issue/NES-24",
                "updatedAt": "2025-01-03T00:00:00Z",
            },
        }

        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        client.update_issue(issue_id="NES-24", priority=3)

        # Verify only issue-id and priority are passed
        call_args = mock_run.call_args[0][0]
        assert "--issue-id" in call_args
        assert "--priority" in call_args
        assert "--title" not in call_args
        assert "--body" not in call_args


class TestLinearClientComments:
    """Test comment-related methods."""

    def test_list_comments_success(self, mocker: MagicMock) -> None:
        """Successfully list comments on an issue."""
        mock_response = {
            "ok": True,
            "data": {
                "comments": [
                    {
                        "id": "comment-1",
                        "body": "First comment",
                        "createdAt": "2025-01-01T00:00:00Z",
                        "updatedAt": "2025-01-01T00:00:00Z",
                        "user": {"id": "user-1", "name": "Test User"},
                    },
                    {
                        "id": "comment-2",
                        "body": "Second comment",
                        "createdAt": "2025-01-02T00:00:00Z",
                        "updatedAt": "2025-01-02T00:00:00Z",
                        "user": {"id": "user-2", "name": "Another User"},
                    },
                ]
            },
        }

        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        comments = client.list_comments("NES-24")

        assert len(comments) == 2
        assert comments[0]["body"] == "First comment"
        assert comments[1]["body"] == "Second comment"
        assert comments[0]["user"]["name"] == "Test User"

    def test_list_comments_empty(self, mocker: MagicMock) -> None:
        """Return empty list when no comments exist."""
        mock_response = {"ok": True, "data": {"comments": []}}

        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        comments = client.list_comments("NES-24")

        assert len(comments) == 0
        assert isinstance(comments, list)

    def test_create_comment_success(self, mocker: MagicMock) -> None:
        """Successfully create a comment on an issue."""
        mock_response = {
            "ok": True,
            "data": {
                "id": "comment-new",
                "body": "New comment",
                "createdAt": "2025-01-03T00:00:00Z",
                "issueId": "issue-123",
                "user": {"id": "user-1", "name": "Test User"},
            },
        }

        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        result = client.create_comment(issue_id="NES-24", body="New comment")

        assert result["id"] == "comment-new"
        assert result["body"] == "New comment"

        # Verify arguments
        call_args = mock_run.call_args[0][0]
        assert "--issue-id" in call_args
        assert "NES-24" in call_args
        assert "--body" in call_args
        assert "New comment" in call_args


class TestLinearClientListProjects:
    """Test the list_projects method."""

    def test_list_projects_success(self, mocker: MagicMock) -> None:
        """Successfully list all projects."""
        mock_response = {
            "ok": True,
            "data": {
                "projects": [
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
                ]
            },
        }

        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        projects = client.list_projects()

        assert len(projects) == 2
        assert projects[0]["name"] == "Project Alpha"
        assert projects[1]["name"] == "Project Beta"

    def test_list_projects_empty(self, mocker: MagicMock) -> None:
        """Return empty list when no projects exist."""
        mock_response = {"ok": True, "data": {"projects": []}}

        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        projects = client.list_projects()

        assert len(projects) == 0
        assert isinstance(projects, list)


class TestLinearClientListTeams:
    """Test the list_teams method."""

    def test_list_teams_success(self, mocker: MagicMock) -> None:
        """Successfully list all teams."""
        mock_response = {
            "ok": True,
            "data": {
                "teams": [
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
                ]
            },
        }

        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        teams = client.list_teams()

        assert len(teams) == 2
        assert teams[0]["key"] == "ENG"
        assert teams[1]["key"] == "NES"

    def test_list_teams_empty(self, mocker: MagicMock) -> None:
        """Return empty list when no teams exist."""
        mock_response = {"ok": True, "data": {"teams": []}}

        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        teams = client.list_teams()

        assert len(teams) == 0
        assert isinstance(teams, list)


class TestLinearClientErrorHandling:
    """Test error handling and edge cases."""

    def test_subprocess_failure_handling(self, mocker: MagicMock) -> None:
        """Handle subprocess execution failures gracefully."""
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "Node.js error"
        mock_run.return_value.returncode = 1

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        assert exc_info.value.code == "PARSE_ERROR"

    def test_invalid_json_handling(self, mocker: MagicMock) -> None:
        """Handle malformed JSON responses."""
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = '{"ok": true, invalid json'
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        assert exc_info.value.code == "PARSE_ERROR"

    def test_api_key_not_in_error_messages(self, mocker: MagicMock) -> None:
        """Ensure API key is not leaked in error messages."""
        mock_response = {
            "ok": False,
            "error": {
                "code": "UNAUTHORIZED",
                "message": "Invalid API key provided",
            },
        }

        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="secret_api_key_12345")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        # Verify the API key is not in the error message
        error_message = str(exc_info.value)
        assert "secret_api_key_12345" not in error_message
        assert "UNAUTHORIZED" in error_message

    def test_script_not_found_error(self, mocker: MagicMock) -> None:
        """Raise error when script file does not exist."""
        client = LinearClient(api_key="test_key")

        # Mock the script path to not exist
        original_exists = Path.exists

        def mock_exists(self: Path) -> bool:
            """
            Simulate Path.exists so that any path containing "get-issue.js" is reported missing while other paths use the original existence check.
            
            Parameters:
                self (Path): The path to check.
            
            Returns:
                bool: `False` if the path string contains "get-issue.js", otherwise the result of the original Path.exists for `self`.
            """
            if "get-issue.js" in str(self):
                return False
            return original_exists(self)

        mocker.patch.object(Path, "exists", mock_exists)

        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        assert exc_info.value.code == "SCRIPT_NOT_FOUND"
        assert "get-issue.js" in exc_info.value.message

    def test_unknown_error_code(self, mocker: MagicMock) -> None:
        """Handle unknown error codes from the API."""
        mock_response = {
            "ok": False,
            "error": {},  # Missing code and message
        }

        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        assert exc_info.value.code == "UNKNOWN_ERROR"
        assert "Unknown error occurred" in exc_info.value.message

    def test_empty_response_data(self, mocker: MagicMock) -> None:
        """Handle empty data in successful response."""
        mock_response = {"ok": True}  # Missing data field

        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        result = client.get_issue("NES-24")

        # Should return empty dict when data is missing
        assert result == {}