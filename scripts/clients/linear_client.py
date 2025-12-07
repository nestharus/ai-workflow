"""Python wrapper for Linear TypeScript CLI scripts.

This module provides a Python interface to the Linear API by wrapping
TypeScript CLI scripts that use the @linear/sdk.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast


class LinearClientError(Exception):
    """Raised when a Linear API operation fails."""

    def __init__(self, code: str, message: str) -> None:
        """Initialize the error with a code and message.

        Args:
            code: Error code identifying the type of error
            message: Human-readable error message
        """
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class LinearClient:
    """Python wrapper for Linear TypeScript CLI scripts."""

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize client with API key from argument or LINEAR_API_KEY env var.

        Args:
            api_key: Linear API key. If not provided, uses LINEAR_API_KEY env var.

        Raises:
            LinearClientError: If no API key is provided or found in environment
        """
        self._api_key = api_key or os.environ.get("LINEAR_API_KEY")
        if not self._api_key:
            raise LinearClientError(
                "MISSING_API_KEY",
                "LINEAR_API_KEY must be provided or set in environment",
            )

        # Determine the scripts directory (existence checked in _run_script)
        self._scripts_dir = Path(__file__).parent / "linear"

    def _run_script(self, script_name: str, args: list[str]) -> dict[str, Any]:
        """Run a TypeScript script and return parsed JSON response.

        Args:
            script_name: Name of the script file (without .js extension)
            args: Command-line arguments to pass to the script

        Returns:
            Parsed JSON response data

        Raises:
            LinearClientError: If the script fails or returns an error
        """
        # Check if scripts directory exists
        if not self._scripts_dir.exists():
            raise LinearClientError(
                "SCRIPTS_NOT_FOUND",
                f"Linear scripts directory not found at {self._scripts_dir}",
            )

        script_path = self._scripts_dir / "dist" / f"{script_name}.js"
        if not script_path.exists():
            raise LinearClientError(
                "SCRIPT_NOT_FOUND",
                f"Script {script_name}.js not found at {script_path}",
            )

        # Run the script via node
        # Build environment with API key (validated in __init__)
        env: dict[str, str] = {**os.environ, "LINEAR_API_KEY": cast("str", self._api_key)}
        try:
            result = subprocess.run(
                ["node", str(script_path), *args],
                cwd=str(self._scripts_dir),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            raise LinearClientError(
                "NODE_NOT_FOUND",
                "Node.js is not installed or not found on PATH",
            ) from None
        except OSError as e:
            raise LinearClientError(
                "SUBPROCESS_ERROR",
                f"Failed to run script: {e}",
            ) from None

        # Parse the JSON response
        try:
            response = json.loads(result.stdout)
        except json.JSONDecodeError:
            # If JSON parsing fails, use stderr or a generic error
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            raise LinearClientError("PARSE_ERROR", error_msg) from None

        # Validate response is a dict (scripts always return JSON objects)
        if not isinstance(response, dict):
            raise LinearClientError("PARSE_ERROR", "Expected JSON object response")

        # Check if the response indicates an error
        if not response.get("ok", False):
            error = response.get("error", {})
            code = error.get("code", "UNKNOWN_ERROR")
            message = error.get("message", "Unknown error occurred")
            raise LinearClientError(code, message)

        return cast("dict[str, Any]", response.get("data", {}))

    def get_issue(self, issue_id: str) -> dict[str, Any]:
        """Fetch issue details by ID.

        Args:
            issue_id: Linear issue ID (e.g., "NES-24" or UUID)

        Returns:
            Dictionary with issue data including:
            - id: str
            - identifier: str
            - title: str
            - description: str | None
            - priority: int
            - estimate: int | None
            - url: str
            - branchName: str
            - createdAt: str
            - updatedAt: str
            - completedAt: str | None
            - canceledAt: str | None
            - dueDate: str | None
            - team: dict | None (id, name, key)
            - assignee: dict | None (id, name, email)
            - state: dict | None (id, name, type)
            - project: dict | None (id, name)
            - parent: dict | None (id, identifier, title)
            - commentCount: int
            - childrenCount: int

        Raises:
            LinearClientError: If the operation fails
        """
        return self._run_script("get-issue", ["--issue-id", issue_id])

    def create_issue(
        self,
        team: str,
        title: str,
        description: str | None = None,
        project: str | None = None,
        priority: int | None = None,
    ) -> dict[str, Any]:
        """Create a new issue.

        Args:
            team: Team identifier - can be a UUID, team key (e.g., "NES"), or team name
                  (e.g., "Neshq"). The CLI will resolve names/keys to UUIDs automatically.
            title: Issue title
            description: Issue description (optional)
            project: Project ID (optional)
            priority: Priority 0-4 (0=None, 1=Urgent, 2=High, 3=Normal, 4=Low) (optional)

        Returns:
            Dictionary with created issue data including:
            - id: str
            - identifier: str
            - title: str
            - url: str
            - branchName: str

        Raises:
            LinearClientError: If the operation fails
        """
        args = ["--team", team, "--title", title]

        if description is not None:
            args.extend(["--description", description])

        if project is not None:
            args.extend(["--project", project])

        if priority is not None:
            args.extend(["--priority", str(priority)])

        return self._run_script("create-issue", args)

    def update_issue(
        self,
        issue_id: str,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: int | None = None,
    ) -> dict[str, Any]:
        """Update an existing issue.

        Args:
            issue_id: Linear issue ID
            title: New issue title (optional)
            description: New issue description (optional)
            status: New status/state ID (optional)
            priority: New priority 0-4 (optional)

        Returns:
            Dictionary with updated issue data including:
            - id: str
            - identifier: str
            - title: str
            - url: str
            - updatedAt: str

        Raises:
            LinearClientError: If the operation fails. In particular, raises
                LinearClientError with code ``NO_UPDATES`` if none of the optional
                fields (title, description, status, priority) are provided.
        """
        args = ["--issue-id", issue_id]

        if title is not None:
            args.extend(["--title", title])

        if description is not None:
            args.extend(["--description", description])

        if status is not None:
            args.extend(["--state", status])

        if priority is not None:
            args.extend(["--priority", str(priority)])

        return self._run_script("update-issue", args)

    def list_comments(self, issue_id: str) -> list[dict[str, Any]]:
        """List all comments on an issue.

        Args:
            issue_id: Linear issue ID

        Returns:
            List of comment dictionaries, each containing:
            - id: str
            - body: str
            - createdAt: str
            - updatedAt: str
            - user: dict | None

        Raises:
            LinearClientError: If the operation fails
        """
        data = self._run_script("list-comments", ["--issue-id", issue_id])
        return cast("list[dict[str, Any]]", data.get("comments", []))

    def create_comment(self, issue_id: str, body: str) -> dict[str, Any]:
        """Create a comment on an issue.

        Args:
            issue_id: Linear issue ID
            body: Comment body text

        Returns:
            Dictionary with created comment data including:
            - id: str
            - body: str
            - createdAt: str
            - issueId: str
            - user: dict | None

        Raises:
            LinearClientError: If the operation fails
        """
        return self._run_script("create-comment", ["--issue-id", issue_id, "--body", body])

    def list_projects(self) -> list[dict[str, Any]]:
        """List projects in the workspace (first page only).

        Returns:
            List of project dictionaries, each containing:
            - id: str
            - name: str
            - description: str | None
            - url: str
            - slugId: str
            - startedAt: str | None
            - completedAt: str | None
            - targetDate: str | None
            - createdAt: str
            - updatedAt: str
            - archivedAt: str | None
            - lead: dict | None
            - state: str | None
            - teams: list[dict]

        Raises:
            LinearClientError: If the operation fails
        """
        data = self._run_script("list-projects", [])
        return cast("list[dict[str, Any]]", data.get("projects", []))

    def list_teams(self) -> list[dict[str, Any]]:
        """List all teams in the workspace.

        Returns:
            List of team dictionaries, each containing:
            - id: str
            - name: str
            - key: str
            - description: str | None
            - createdAt: str
            - updatedAt: str
            - archivedAt: str | None
            - private: bool
            - timezone: str | None

        Raises:
            LinearClientError: If the operation fails
        """
        data = self._run_script("list-teams", [])
        return cast("list[dict[str, Any]]", data.get("teams", []))
