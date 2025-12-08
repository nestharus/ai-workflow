"""Unit tests for the Linear client Python wrapper.

These tests verify that the LinearClient wrapper correctly handles initialization,
subprocess execution, JSON parsing, and error handling without making actual API calls.
"""

import json
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

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

        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
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
        (cmd,) = mock_run.call_args[0]
        assert "node" in cmd
        assert "--issue-id" in cmd
        assert "NES-24" in cmd
        assert mock_run.call_args[1]["env"]["LINEAR_API_KEY"] == "test_key"

    def test_get_issue_not_found(self, mocker: MockerFixture) -> None:
        """Raise error when issue is not found."""
        mock_response = {
            "ok": False,
            "error": {"code": "NOT_FOUND", "message": "Issue not found"},
        }

        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("INVALID-999")

        assert exc_info.value.code == "NOT_FOUND"
        assert exc_info.value.message == "Issue not found"

    def test_get_issue_parse_error(self, mocker: MockerFixture) -> None:
        """Raise error when JSON parsing fails."""
        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
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

    def test_create_issue_success(self, mocker: MockerFixture) -> None:
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

        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
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
        (cmd,) = mock_run.call_args[0]
        assert "--team" in cmd
        assert "NES" in cmd
        assert "--title" in cmd
        assert "New Feature" in cmd
        assert "--description" in cmd
        assert "Feature description" in cmd
        assert "--priority" in cmd
        assert "2" in cmd

    def test_create_issue_empty_team(self, mocker: MockerFixture) -> None:
        """Raise error when team is an empty string."""
        mock_response = {
            "ok": False,
            "error": {"code": "INVALID_INPUT", "message": "Team is required"},
        }

        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError):
            # This will be caught by the wrapper's error handling
            # The actual validation happens in TypeScript, so we simulate the error
            client.create_issue(team="", title="Test")

    def test_create_issue_without_optional_params(self, mocker: MockerFixture) -> None:
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

        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        result = client.create_issue(team="NES", title="Simple Issue")

        assert result["identifier"] == "NES-100"

        # Verify only required arguments are passed
        (cmd,) = mock_run.call_args[0]
        assert "--team" in cmd
        assert "--title" in cmd
        assert "--description" not in cmd
        assert "--priority" not in cmd


class TestLinearClientUpdateIssue:
    """Test the update_issue method."""

    def test_update_issue_success(self, mocker: MockerFixture) -> None:
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

        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
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
        (cmd,) = mock_run.call_args[0]
        assert "--issue-id" in cmd
        assert "NES-24" in cmd
        assert "--title" in cmd
        assert "Updated Title" in cmd
        assert "--priority" in cmd
        assert "1" in cmd

    def test_update_issue_partial_update(self, mocker: MockerFixture) -> None:
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

        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        client.update_issue(issue_id="NES-24", priority=3)

        # Verify only issue-id and priority are passed
        (cmd,) = mock_run.call_args[0]
        assert "--issue-id" in cmd
        assert "--priority" in cmd
        assert "--title" not in cmd
        assert "--description" not in cmd

    def test_update_issue_no_updates_error(self, mocker: MockerFixture) -> None:
        """Raise NO_UPDATES error when no updatable fields are provided."""
        mock_response = {
            "ok": False,
            "error": {
                "code": "NO_UPDATES",
                "message": "No fields provided to update",
            },
        }

        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            # Only issue_id provided, no updatable fields
            client.update_issue(issue_id="NES-24")

        assert exc_info.value.code == "NO_UPDATES"
        assert "No fields provided to update" in exc_info.value.message


class TestLinearClientComments:
    """Test comment-related methods."""

    def test_list_comments_success(self, mocker: MockerFixture) -> None:
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

        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        comments = client.list_comments("NES-24")

        assert len(comments) == 2
        assert comments[0]["body"] == "First comment"
        assert comments[1]["body"] == "Second comment"
        assert comments[0]["user"]["name"] == "Test User"

    def test_list_comments_empty(self, mocker: MockerFixture) -> None:
        """Return empty list when no comments exist."""
        mock_response = {"ok": True, "data": {"comments": []}}

        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        comments = client.list_comments("NES-24")

        assert len(comments) == 0
        assert isinstance(comments, list)

    def test_create_comment_success(self, mocker: MockerFixture) -> None:
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

        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        result = client.create_comment(issue_id="NES-24", body="New comment")

        assert result["id"] == "comment-new"
        assert result["body"] == "New comment"

        # Verify arguments
        (cmd,) = mock_run.call_args[0]
        assert "--issue-id" in cmd
        assert "NES-24" in cmd
        assert "--body" in cmd
        assert "New comment" in cmd


class TestLinearClientListProjects:
    """Test the list_projects method."""

    def test_list_projects_success(self, mocker: MockerFixture) -> None:
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

        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        projects = client.list_projects()

        assert len(projects) == 2
        assert projects[0]["name"] == "Project Alpha"
        assert projects[1]["name"] == "Project Beta"

    def test_list_projects_empty(self, mocker: MockerFixture) -> None:
        """Return empty list when no projects exist."""
        mock_response = {"ok": True, "data": {"projects": []}}

        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        projects = client.list_projects()

        assert len(projects) == 0
        assert isinstance(projects, list)


class TestLinearClientListTeams:
    """Test the list_teams method."""

    def test_list_teams_success(self, mocker: MockerFixture) -> None:
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

        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        teams = client.list_teams()

        assert len(teams) == 2
        assert teams[0]["key"] == "ENG"
        assert teams[1]["key"] == "NES"

    def test_list_teams_empty(self, mocker: MockerFixture) -> None:
        """Return empty list when no teams exist."""
        mock_response = {"ok": True, "data": {"teams": []}}

        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        teams = client.list_teams()

        assert len(teams) == 0
        assert isinstance(teams, list)


class TestLinearClientErrorHandling:
    """Test error handling and edge cases."""

    def test_scripts_directory_not_found_on_invoke(self, tmp_path: Path) -> None:
        """Raise error when scripts directory does not exist during script invocation."""
        client = LinearClient(api_key="test_key")

        # Point to a non-existent directory
        client._scripts_dir = tmp_path / "nonexistent"

        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        assert exc_info.value.code == "SCRIPTS_NOT_FOUND"

    def test_node_not_found_error(self, mocker: MockerFixture) -> None:
        """Raise NODE_NOT_FOUND error when Node.js is not installed."""
        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
        # Mock subprocess.run to raise FileNotFoundError (simulating node not found)
        mock_run = mocker.patch("subprocess.run")
        mock_run.side_effect = FileNotFoundError("node not found")

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        assert exc_info.value.code == "NODE_NOT_FOUND"
        assert "Node.js" in exc_info.value.message

    def test_subprocess_os_error(self, mocker: MockerFixture) -> None:
        """Raise SUBPROCESS_ERROR on OSError from subprocess.run."""
        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
        # Mock subprocess.run to raise OSError
        mock_run = mocker.patch("subprocess.run")
        mock_run.side_effect = OSError("Permission denied")

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        assert exc_info.value.code == "SUBPROCESS_ERROR"
        assert "Permission denied" in exc_info.value.message

    def test_subprocess_failure_handling(self, mocker: MockerFixture) -> None:
        """Handle subprocess execution failures gracefully."""
        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "Node.js error"
        mock_run.return_value.returncode = 1

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        assert exc_info.value.code == "PARSE_ERROR"

    def test_invalid_json_handling(self, mocker: MockerFixture) -> None:
        """Handle malformed JSON responses."""
        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = '{"ok": true, invalid json'
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        assert exc_info.value.code == "PARSE_ERROR"

    def test_api_key_not_in_error_messages(self, mocker: MockerFixture) -> None:
        """Ensure API key is not leaked in error messages."""
        mock_response = {
            "ok": False,
            "error": {
                "code": "UNAUTHORIZED",
                "message": "Invalid API key provided",
            },
        }

        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test-linear-api-key-12345")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        # Verify the API key is not in the error message
        error_message = str(exc_info.value)
        assert "test-linear-api-key-12345" not in error_message
        assert "UNAUTHORIZED" in error_message

    def test_script_not_found_error(self, tmp_path: Path) -> None:
        """Raise error when script file does not exist."""
        client = LinearClient(api_key="test_key")

        # Create a scripts directory that exists but doesn't have the dist/script file
        fake_scripts_dir = tmp_path / "linear"
        fake_scripts_dir.mkdir()
        (fake_scripts_dir / "dist").mkdir()
        # Note: we don't create get-issue.js, so it will be "not found"

        client._scripts_dir = fake_scripts_dir

        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        assert exc_info.value.code == "SCRIPT_NOT_FOUND"
        assert "get-issue.js" in exc_info.value.message

    def test_unknown_error_code(self, mocker: MockerFixture) -> None:
        """Handle unknown error codes from the API."""
        mock_response = {
            "ok": False,
            "error": {},  # Missing code and message
        }

        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        with pytest.raises(LinearClientError) as exc_info:
            client.get_issue("NES-24")

        assert exc_info.value.code == "UNKNOWN_ERROR"
        assert "Unknown error occurred" in exc_info.value.message

    def test_empty_response_data(self, mocker: MockerFixture) -> None:
        """Handle empty data in successful response."""
        mock_response = {"ok": True}  # Missing data field

        # Mock Path.exists to bypass file existence checks
        mocker.patch.object(Path, "exists", return_value=True)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value.stdout = json.dumps(mock_response)
        mock_run.return_value.returncode = 0

        client = LinearClient(api_key="test_key")
        result = client.get_issue("NES-24")

        # Should return empty dict when data is missing
        assert result == {}


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
