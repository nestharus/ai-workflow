"""Linear API data access operations.

Provides low-level functions for interacting with the Linear GraphQL API.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

LINEAR_API_URL = "https://api.linear.app/graphql"


class LinearAPIError(RuntimeError):
    """Raised when a Linear API call fails."""

    def __init__(self, message: str) -> None:
        """Initialize with error message."""
        super().__init__(message)


class LinearClient:
    """Client for interacting with the Linear GraphQL API.

    Provides methods for fetching and updating Linear tickets, attachments,
    and workflow states.

    Attributes:
        _api_key: The Linear API key used for authentication.
    """

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize the Linear client.

        Args:
            api_key: Optional Linear API key. If not provided, defaults to
                the LINEAR_API_KEY environment variable.

        Raises:
            LinearAPIError: If no API key is provided and LINEAR_API_KEY
                environment variable is not set.
        """
        if api_key is not None:
            self._api_key = api_key
        else:
            env_key = os.environ.get("LINEAR_API_KEY")
            if not env_key:
                raise LinearAPIError("LINEAR_API_KEY environment variable not set")
            self._api_key = env_key

    def _run_graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a GraphQL query against Linear API.

        All user-supplied values must be passed via the variables parameter,
        not interpolated into the query string. Query strings should only
        contain static GraphQL structure and $variable placeholders.

        Args:
            query: GraphQL query string with $variable placeholders.
            variables: Dictionary of variable values to send with the query.

        Returns:
            Parsed JSON response data.

        Raises:
            LinearAPIError: If the API call fails due to network issues,
                HTTP errors, GraphQL errors, or malformed responses.
        """
        payload: dict[str, Any] = {"query": query}
        if variables is not None:
            payload["variables"] = variables

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            LINEAR_API_URL,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": self._api_key,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise LinearAPIError(f"Linear API HTTP error: {e.code} {e.reason}") from e
        except urllib.error.URLError as e:
            raise LinearAPIError(f"Linear API request failed: {e.reason}") from e

        try:
            result: dict[str, Any] = json.loads(response_body)
        except json.JSONDecodeError as e:
            raise LinearAPIError(f"Linear API returned malformed JSON: {e}") from e

        if "errors" in result:
            raise LinearAPIError(f"Linear API error: {result['errors']}")

        return result

    def fetch_github_attachments(self, ticket_id: str) -> list[dict[str, Any]]:
        """Fetch all GitHub PR attachments for a ticket with pagination.

        Args:
            ticket_id: Linear ticket ID (e.g., "NES-123").

        Returns:
            List of attachment dictionaries with url and title.

        Raises:
            LinearAPIError: If the API call fails.
        """
        all_attachments: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            query = """
query($ticketId: String!, $after: String) {
  issue(id: $ticketId) {
    attachments(
      first: 100
      filter: {url: {contains: "github.com"}}
      after: $after
    ) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        url
        title
      }
    }
  }
}
"""
            variables: dict[str, Any] = {"ticketId": ticket_id}
            if cursor is not None:
                variables["after"] = cursor

            result = self._run_graphql(query, variables)
            issue = result.get("data", {}).get("issue")
            if not issue:
                break

            attachments = issue.get("attachments", {})
            nodes = attachments.get("nodes", [])
            all_attachments.extend(nodes)

            page_info = attachments.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")

        return all_attachments

    def get_ticket_info(self, ticket_id: str) -> dict[str, Any]:
        """Get basic ticket info from Linear.

        Args:
            ticket_id: Linear ticket ID (e.g., "NES-123").

        Returns:
            Dictionary with ticket data including id, identifier, title,
            branch_name, state, state_type, and team_id.

        Raises:
            LinearAPIError: If ticket not found or API call fails.
        """
        query = """
query($ticketId: String!) {
  issue(id: $ticketId) {
    id
    identifier
    title
    branchName
    state {
      id
      name
      type
    }
    team {
      id
    }
  }
}
"""
        variables = {"ticketId": ticket_id}
        result = self._run_graphql(query, variables)
        issue = result.get("data", {}).get("issue")
        if not issue:
            raise LinearAPIError(f"Ticket not found: {ticket_id}")

        return {
            "id": issue.get("id"),
            "identifier": issue.get("identifier"),
            "title": issue.get("title"),
            "branch_name": issue.get("branchName"),
            "state": issue.get("state", {}).get("name"),
            "state_type": issue.get("state", {}).get("type"),
            "team_id": issue.get("team", {}).get("id"),
        }

    def get_done_state_id(self, team_id: str) -> str:
        """Get the 'Done' workflow state ID for a team.

        Args:
            team_id: Linear team ID.

        Returns:
            The workflow state ID for 'Done' state.

        Raises:
            LinearAPIError: If no done state found or API call fails.
        """
        query = """
query($teamId: String!) {
  team(id: $teamId) {
    states(filter: {type: {eq: "completed"}}) {
      nodes {
        id
        name
        type
      }
    }
  }
}
"""
        variables = {"teamId": team_id}
        result = self._run_graphql(query, variables)
        states = result.get("data", {}).get("team", {}).get("states", {}).get("nodes", [])

        if states:
            return str(states[0].get("id"))

        raise LinearAPIError(f"No 'Done' state found for team {team_id}")

    def set_ticket_state(self, issue_uuid: str, state_id: str) -> bool:
        """Update a Linear ticket's state.

        Args:
            issue_uuid: Linear issue UUID (not the identifier like NES-123).
            state_id: Target workflow state ID.

        Returns:
            True if successful, False otherwise.

        Raises:
            LinearAPIError: If the API call fails.
        """
        mutation = """
mutation($issueId: String!, $stateId: String!) {
  issueUpdate(id: $issueId, input: {stateId: $stateId}) {
    success
    issue {
      state {
        name
      }
    }
  }
}
"""
        variables = {"issueId": issue_uuid, "stateId": state_id}
        result = self._run_graphql(mutation, variables)
        success = result.get("data", {}).get("issueUpdate", {}).get("success", False)
        return bool(success)

    def _resolve_team_id(self, team: str) -> str | None:
        """Resolve a team identifier to a team UUID.

        Attempts to resolve the team identifier in the following order:
        1. If the string matches UUID pattern, return as-is
        2. Search teams by key (case-insensitive)
        3. Search teams by name (case-insensitive)

        Args:
            team: Team identifier - can be a UUID, team key, or team name.

        Returns:
            The team UUID if found, None otherwise.
        """
        # UUID pattern: 8-4-4-4-12 hex characters
        uuid_pattern = re.compile(
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        )
        if uuid_pattern.match(team):
            return team

        # Fetch all teams and search by key, then by name (case-insensitive)
        teams = self.list_teams(include_archived=True)
        team_lower = team.lower()

        # First, search by key (case-insensitive)
        for t in teams:
            if t.get("key", "").lower() == team_lower:
                return str(t.get("id"))

        # Then, search by name (case-insensitive)
        for t in teams:
            if t.get("name", "").lower() == team_lower:
                return str(t.get("id"))

        return None

    def list_teams(self, include_archived: bool = False) -> list[dict[str, Any]]:
        """List all teams in the Linear workspace.

        Fetches teams with cursor-based pagination to retrieve all results.

        Args:
            include_archived: Whether to include archived teams. Defaults to False.

        Returns:
            List of team dictionaries, each containing:
            - id: Team UUID
            - name: Team name
            - key: Team key (e.g., "NES")
            - description: Team description
            - createdAt: ISO timestamp when team was created
            - updatedAt: ISO timestamp when team was last updated
            - archivedAt: ISO timestamp when archived (or None)
            - private: Whether the team is private
            - timezone: Team timezone

        Raises:
            LinearAPIError: If the API call fails.
        """
        all_teams: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            query = """
query($includeArchived: Boolean!, $after: String) {
  teams(first: 100, includeArchived: $includeArchived, after: $after) {
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      id
      name
      key
      description
      createdAt
      updatedAt
      archivedAt
      private
      timezone
    }
  }
}
"""
            variables: dict[str, Any] = {"includeArchived": include_archived}
            if cursor is not None:
                variables["after"] = cursor

            result = self._run_graphql(query, variables)
            teams_data = result.get("data", {}).get("teams", {})
            nodes = teams_data.get("nodes", [])
            all_teams.extend(nodes)

            page_info = teams_data.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")

        return all_teams

    def _validate_priority(self, priority: int | None) -> None:
        """Validate that priority is within the valid range.

        Args:
            priority: Priority value to validate. Can be None (no validation needed)
                or an integer from 0-4.

        Raises:
            LinearAPIError: If priority is not None and not in range 0-4.
        """
        if priority is not None and (priority < 0 or priority > 4):
            raise LinearAPIError(f"Priority must be between 0 and 4, got: {priority}")

    def create_issue(
        self,
        title: str,
        team: str,
        description: str | None = None,
        assignee_id: str | None = None,
        project_id: str | None = None,
        priority: int | None = None,
        state_id: str | None = None,
        parent_id: str | None = None,
        label_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new issue in Linear.

        Args:
            title: The title of the issue.
            team: Team identifier - can be a UUID, team key, or team name.
            description: Optional issue description in Markdown format.
            assignee_id: Optional UUID of the user to assign the issue to.
            project_id: Optional UUID of the project to add the issue to.
            priority: Optional priority level (0=No priority, 1=Urgent,
                2=High, 3=Normal, 4=Low).
            state_id: Optional UUID of the workflow state.
            parent_id: Optional UUID of the parent issue (for sub-issues).
            label_ids: Optional list of label UUIDs to apply to the issue.

        Returns:
            Dictionary containing the created issue data:
            - id: Issue UUID
            - identifier: Issue identifier (e.g., "NES-123")
            - title: Issue title
            - url: Issue URL
            - branchName: Suggested branch name for the issue

        Raises:
            LinearAPIError: If team not found, priority is invalid, or API call fails.
        """
        self._validate_priority(priority)

        team_id = self._resolve_team_id(team)
        if team_id is None:
            raise LinearAPIError(f"Team not found: {team}")

        mutation = """
mutation IssueCreate($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    success
    issue {
      id
      identifier
      title
      url
      branchName
    }
  }
}
"""
        # Build input object with required and optional fields
        input_data: dict[str, Any] = {
            "title": title,
            "teamId": team_id,
        }

        if description is not None:
            input_data["description"] = description
        if assignee_id is not None:
            input_data["assigneeId"] = assignee_id
        if project_id is not None:
            input_data["projectId"] = project_id
        if priority is not None:
            input_data["priority"] = priority
        if state_id is not None:
            input_data["stateId"] = state_id
        if parent_id is not None:
            input_data["parentId"] = parent_id
        if label_ids is not None:
            input_data["labelIds"] = label_ids

        variables = {"input": input_data}
        result = self._run_graphql(mutation, variables)

        issue_create = result.get("data", {}).get("issueCreate", {})
        if not issue_create.get("success"):
            raise LinearAPIError("Failed to create issue")

        issue = issue_create.get("issue", {})
        return {
            "id": issue.get("id"),
            "identifier": issue.get("identifier"),
            "title": issue.get("title"),
            "url": issue.get("url"),
            "branchName": issue.get("branchName"),
        }

    def update_issue(
        self,
        issue_id: str,
        title: str | None = None,
        description: str | None = None,
        assignee_id: str | None = None,
        project_id: str | None = None,
        priority: int | None = None,
        state_id: str | None = None,
        parent_id: str | None = None,
        label_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Update an existing issue in Linear.

        Args:
            issue_id: UUID or identifier of the issue to update.
            title: Optional new title for the issue.
            description: Optional new description in Markdown format.
            assignee_id: Optional UUID of the user to assign the issue to.
            project_id: Optional UUID of the project to add the issue to.
            priority: Optional priority level (0=No priority, 1=Urgent,
                2=High, 3=Normal, 4=Low).
            state_id: Optional UUID of the workflow state.
            parent_id: Optional UUID of the parent issue (for sub-issues).
            label_ids: Optional list of label UUIDs to apply to the issue.

        Returns:
            Dictionary containing the updated issue data:
            - id: Issue UUID
            - identifier: Issue identifier (e.g., "NES-123")
            - title: Issue title
            - url: Issue URL
            - updatedAt: ISO timestamp when issue was last updated

        Raises:
            LinearAPIError: If no fields to update, priority is invalid,
                or API call fails.
        """
        self._validate_priority(priority)

        # Build input object with only provided fields
        input_data: dict[str, Any] = {}

        if title is not None:
            input_data["title"] = title
        if description is not None:
            input_data["description"] = description
        if assignee_id is not None:
            input_data["assigneeId"] = assignee_id
        if project_id is not None:
            input_data["projectId"] = project_id
        if priority is not None:
            input_data["priority"] = priority
        if state_id is not None:
            input_data["stateId"] = state_id
        if parent_id is not None:
            input_data["parentId"] = parent_id
        if label_ids is not None:
            input_data["labelIds"] = label_ids

        if not input_data:
            raise LinearAPIError("At least one field must be provided to update an issue")

        mutation = """
mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) {
    success
    issue {
      id
      identifier
      title
      url
      updatedAt
    }
  }
}
"""
        variables = {"id": issue_id, "input": input_data}
        result = self._run_graphql(mutation, variables)

        issue_update = result.get("data", {}).get("issueUpdate", {})
        if not issue_update.get("success"):
            raise LinearAPIError(f"Failed to update issue: {issue_id}")

        issue = issue_update.get("issue", {})
        return {
            "id": issue.get("id"),
            "identifier": issue.get("identifier"),
            "title": issue.get("title"),
            "url": issue.get("url"),
            "updatedAt": issue.get("updatedAt"),
        }

    def list_projects(
        self, team_id: str | None = None, include_archived: bool = False
    ) -> list[dict[str, Any]]:
        """List all projects in the Linear workspace.

        Fetches projects with cursor-based pagination to retrieve all results.
        Optionally filters by team.

        Args:
            team_id: Optional team UUID or team key/name to filter projects.
                If a team key or name is provided, it will be resolved to a UUID.
            include_archived: Whether to include archived projects. Defaults to False.

        Returns:
            List of project dictionaries, each containing:
            - id: Project UUID
            - name: Project name
            - description: Project description
            - url: Project URL
            - slugId: Project slug ID
            - startedAt: ISO timestamp when project was started
            - completedAt: ISO timestamp when project was completed
            - targetDate: Target completion date
            - createdAt: ISO timestamp when project was created
            - updatedAt: ISO timestamp when project was last updated
            - archivedAt: ISO timestamp when archived (or None)
            - state: Project state
            - lead: Project lead (user info)
            - teams: List of teams associated with the project

        Raises:
            LinearAPIError: If the API call fails or team not found.
        """
        # Resolve team_id if provided
        resolved_team_id: str | None = None
        if team_id is not None:
            resolved_team_id = self._resolve_team_id(team_id)
            if resolved_team_id is None:
                raise LinearAPIError(f"Team not found: {team_id}")

        all_projects: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            # Build filter dynamically based on team_id
            if resolved_team_id is not None:
                query = """
query($includeArchived: Boolean!, $teamId: ID!, $after: String) {
  projects(
    first: 100
    includeArchived: $includeArchived
    filter: {accessibleTeams: {id: {eq: $teamId}}}
    after: $after
  ) {
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      id
      name
      description
      url
      slugId
      startedAt
      completedAt
      targetDate
      createdAt
      updatedAt
      archivedAt
      state
      lead {
        id
        name
        email
      }
      teams {
        nodes {
          id
          name
          key
        }
      }
    }
  }
}
"""
            else:
                query = """
query($includeArchived: Boolean!, $after: String) {
  projects(first: 100, includeArchived: $includeArchived, after: $after) {
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      id
      name
      description
      url
      slugId
      startedAt
      completedAt
      targetDate
      createdAt
      updatedAt
      archivedAt
      state
      lead {
        id
        name
        email
      }
      teams {
        nodes {
          id
          name
          key
        }
      }
    }
  }
}
"""
            variables: dict[str, Any] = {"includeArchived": include_archived}
            if resolved_team_id is not None:
                variables["teamId"] = resolved_team_id
            if cursor is not None:
                variables["after"] = cursor

            result = self._run_graphql(query, variables)
            projects_data = result.get("data", {}).get("projects", {})
            nodes = projects_data.get("nodes", [])
            all_projects.extend(nodes)

            page_info = projects_data.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")

        return all_projects

    def create_comment(self, issue_id: str, body: str) -> dict[str, Any]:
        """Create a comment on a Linear issue.

        Args:
            issue_id: Issue identifier (e.g., "NES-123") or UUID.
            body: The comment body in Markdown format.

        Returns:
            Dictionary containing the created comment data:
            - id: Comment UUID
            - body: Comment body text
            - createdAt: ISO timestamp when comment was created
            - issueId: UUID of the issue the comment belongs to
            - user: User info dict with id, name, email (or None for system comments)

        Raises:
            LinearAPIError: If the issue is not found or API call fails.
        """
        mutation = """
mutation CommentCreate($input: CommentCreateInput!) {
  commentCreate(input: $input) {
    success
    comment {
      id
      body
      createdAt
      issue {
        id
      }
      user {
        id
        name
        email
      }
    }
  }
}
"""
        variables = {"input": {"issueId": issue_id, "body": body}}
        result = self._run_graphql(mutation, variables)

        comment_create = result.get("data", {}).get("commentCreate", {})
        if not comment_create.get("success"):
            raise LinearAPIError(f"Failed to create comment on issue: {issue_id}")

        comment = comment_create.get("comment", {})
        user_data = comment.get("user")
        user_info: dict[str, Any] | None = None
        if user_data:
            user_info = {
                "id": user_data.get("id"),
                "name": user_data.get("name"),
                "email": user_data.get("email"),
            }

        return {
            "id": comment.get("id"),
            "body": comment.get("body"),
            "createdAt": comment.get("createdAt"),
            "issueId": comment.get("issue", {}).get("id"),
            "user": user_info,
        }

    def list_comments(self, issue_id: str) -> dict[str, Any]:
        """List all comments for a Linear issue with pagination.

        First fetches the issue to get the UUID if an identifier is provided
        (e.g., "NES-123"), then retrieves all comments using pagination.

        Args:
            issue_id: Issue identifier (e.g., "NES-123") or UUID.

        Returns:
            Dictionary containing:
            - issueId: UUID of the issue
            - issueIdentifier: Issue identifier (e.g., "NES-123")
            - comments: List of comment dictionaries, each containing:
                - id: Comment UUID
                - body: Comment body text
                - createdAt: ISO timestamp when comment was created
                - updatedAt: ISO timestamp when comment was last updated
                - user: User info dict with id, name, email (or None for system comments)
            - totalCount: Total number of comments retrieved

        Raises:
            LinearAPIError: If the issue is not found or API call fails.
        """
        all_comments: list[dict[str, Any]] = []
        cursor: str | None = None
        issue_uuid: str | None = None
        issue_identifier: str | None = None

        while True:
            query = """
query IssueComments($id: String!, $after: String) {
  issue(id: $id) {
    id
    identifier
    comments(first: 100, after: $after) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        id
        body
        createdAt
        updatedAt
        user {
          id
          name
          email
        }
      }
    }
  }
}
"""
            variables: dict[str, Any] = {"id": issue_id}
            if cursor is not None:
                variables["after"] = cursor

            result = self._run_graphql(query, variables)
            issue = result.get("data", {}).get("issue")
            if not issue:
                raise LinearAPIError(f"Issue not found: {issue_id}")

            # Capture issue UUID and identifier on first iteration
            if issue_uuid is None:
                issue_uuid = issue.get("id")
                issue_identifier = issue.get("identifier")

            comments_data = issue.get("comments", {})
            nodes = comments_data.get("nodes", [])

            for node in nodes:
                user_data = node.get("user")
                user_info: dict[str, Any] | None = None
                if user_data:
                    user_info = {
                        "id": user_data.get("id"),
                        "name": user_data.get("name"),
                        "email": user_data.get("email"),
                    }
                all_comments.append(
                    {
                        "id": node.get("id"),
                        "body": node.get("body"),
                        "createdAt": node.get("createdAt"),
                        "updatedAt": node.get("updatedAt"),
                        "user": user_info,
                    }
                )

            page_info = comments_data.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")

        return {
            "issueId": issue_uuid,
            "issueIdentifier": issue_identifier,
            "comments": all_comments,
            "totalCount": len(all_comments),
        }


# Module-level default client instance (lazily initialized)
_default_client: LinearClient | None = None


def _get_default_client() -> LinearClient:
    """Get or create the default LinearClient instance.

    Returns:
        The default LinearClient instance.

    Raises:
        LinearAPIError: If LINEAR_API_KEY environment variable is not set.
    """
    global _default_client
    if _default_client is None:
        _default_client = LinearClient()
    return _default_client


# Backwards-compatible free functions


def _get_linear_api_key() -> str:
    """Get the Linear API key from environment.

    Returns:
        The Linear API key.

    Raises:
        LinearAPIError: If LINEAR_API_KEY environment variable not set.
    """
    api_key = os.environ.get("LINEAR_API_KEY")
    if not api_key:
        raise LinearAPIError("LINEAR_API_KEY environment variable not set")
    return api_key


def _run_linear_graphql(query: str) -> dict[str, Any]:
    """Run a GraphQL query against Linear API.

    This is a backwards-compatible wrapper that delegates to the default
    LinearClient instance. Note that this function does not support
    GraphQL variables - prefer using LinearClient._run_graphql directly
    for new code.

    Args:
        query: GraphQL query string.

    Returns:
        Parsed JSON response.

    Raises:
        LinearAPIError: If the API call fails.
    """
    client = _get_default_client()
    return client._run_graphql(query)


def fetch_github_attachments(ticket_id: str) -> list[dict[str, Any]]:
    """Fetch all GitHub PR attachments for a ticket with pagination.

    This is a backwards-compatible wrapper that delegates to the default
    LinearClient instance.

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-123").

    Returns:
        List of attachment dictionaries with url and title.

    Raises:
        LinearAPIError: If the API call fails.
    """
    client = _get_default_client()
    return client.fetch_github_attachments(ticket_id)


def get_ticket_info(ticket_id: str) -> dict[str, Any]:
    """Get basic ticket info from Linear.

    This is a backwards-compatible wrapper that delegates to the default
    LinearClient instance.

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-123").

    Returns:
        Dictionary with ticket data.

    Raises:
        LinearAPIError: If ticket not found or API call fails.
    """
    client = _get_default_client()
    return client.get_ticket_info(ticket_id)


def get_done_state_id(team_id: str) -> str:
    """Get the 'Done' workflow state ID for a team.

    This is a backwards-compatible wrapper that delegates to the default
    LinearClient instance.

    Args:
        team_id: Linear team ID.

    Returns:
        The workflow state ID for 'Done' state.

    Raises:
        LinearAPIError: If no done state found or API call fails.
    """
    client = _get_default_client()
    return client.get_done_state_id(team_id)


def set_ticket_state(issue_uuid: str, state_id: str) -> bool:
    """Update a Linear ticket's state.

    This is a backwards-compatible wrapper that delegates to the default
    LinearClient instance.

    Args:
        issue_uuid: Linear issue UUID (not the identifier like NES-123).
        state_id: Target workflow state ID.

    Returns:
        True if successful.

    Raises:
        LinearAPIError: If the API call fails.
    """
    client = _get_default_client()
    return client.set_ticket_state(issue_uuid, state_id)
