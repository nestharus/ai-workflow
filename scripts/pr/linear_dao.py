"""Linear API data access operations.

Provides low-level functions for interacting with the Linear GraphQL API.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

LINEAR_API_URL = "https://api.linear.app/graphql"


class LinearAPIError(RuntimeError):
    """Raised when a Linear API call fails."""

    def __init__(self, message: str) -> None:
        """Initialize with error message."""
        super().__init__(message)


def _get_linear_api_key() -> str:
    """Get the Linear API key from environment."""
    api_key = os.environ.get("LINEAR_API_KEY")
    if not api_key:
        raise LinearAPIError("LINEAR_API_KEY environment variable not set")
    return api_key


def _run_linear_graphql(query: str) -> dict[str, Any]:
    """Run a GraphQL query against Linear API.

    Args:
        query: GraphQL query string.

    Returns:
        Parsed JSON response.

    Raises:
        LinearAPIError: If the API call fails.
    """
    api_key = _get_linear_api_key()
    data = json.dumps({"query": query}).encode("utf-8")
    req = urllib.request.Request(
        LINEAR_API_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": api_key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result: dict[str, Any] = json.loads(response.read().decode("utf-8"))
            if "errors" in result:
                raise LinearAPIError(f"Linear API error: {result['errors']}")
            return result
    except urllib.error.URLError as e:
        raise LinearAPIError(f"Linear API request failed: {e}") from e


def fetch_github_attachments(ticket_id: str) -> list[dict[str, Any]]:
    """Fetch all GitHub PR attachments for a ticket with pagination.

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-123").

    Returns:
        List of attachment dictionaries with url and title.
    """
    all_attachments: list[dict[str, Any]] = []
    cursor: str | None = None

    while True:
        after_clause = f', after: "{cursor}"' if cursor else ""
        query = f"""
{{
  issue(id: "{ticket_id}") {{
    attachments(
      first: 100
      filter: {{url: {{contains: "github.com"}}}}
      {after_clause}
    ) {{
      pageInfo {{
        hasNextPage
        endCursor
      }}
      nodes {{
        url
        title
      }}
    }}
  }}
}}
"""
        result = _run_linear_graphql(query)
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


def get_ticket_info(ticket_id: str) -> dict[str, Any]:
    """Get basic ticket info from Linear.

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-123").

    Returns:
        Dictionary with ticket data.

    Raises:
        LinearAPIError: If ticket not found.
    """
    query = f"""
{{
  issue(id: "{ticket_id}") {{
    id
    identifier
    title
    branchName
    state {{
      id
      name
      type
    }}
    team {{
      id
    }}
  }}
}}
"""
    result = _run_linear_graphql(query)
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


def get_done_state_id(team_id: str) -> str:
    """Get the 'Done' workflow state ID for a team.

    Args:
        team_id: Linear team ID.

    Returns:
        The workflow state ID for 'Done' state.

    Raises:
        LinearAPIError: If no done state found.
    """
    query = f"""
{{
  team(id: "{team_id}") {{
    states(filter: {{type: {{eq: "completed"}}}}) {{
      nodes {{
        id
        name
        type
      }}
    }}
  }}
}}
"""
    result = _run_linear_graphql(query)
    states = result.get("data", {}).get("team", {}).get("states", {}).get("nodes", [])

    if states:
        return str(states[0].get("id"))

    raise LinearAPIError(f"No 'Done' state found for team {team_id}")


def set_ticket_state(issue_uuid: str, state_id: str) -> bool:
    """Update a Linear ticket's state.

    Args:
        issue_uuid: Linear issue UUID (not the identifier like NES-123).
        state_id: Target workflow state ID.

    Returns:
        True if successful.
    """
    mutation = f"""
mutation {{
  issueUpdate(id: "{issue_uuid}", input: {{stateId: "{state_id}"}}) {{
    success
    issue {{
      state {{
        name
      }}
    }}
  }}
}}
"""
    result = _run_linear_graphql(mutation)
    success = result.get("data", {}).get("issueUpdate", {}).get("success", False)
    return bool(success)
