"""Linear API data access operations - Backwards-Compatible Facade.

This module is a thin, backwards-compatible wrapper around the canonical
implementation at scripts/clients/linear_client.py.

For new code, import directly from the canonical location:
    from scripts.clients.linear_client import LinearClient, LinearClientError

This module re-exports LinearClient and LinearClientError (as LinearAPIError)
for compatibility with existing scripts. It also provides backwards-compatible
free functions that delegate to the canonical client.

Exports:
    LinearClient: Re-exported from scripts.clients.linear_client
    LinearAPIError: Alias for LinearClientError (backwards compatibility)
    _get_default_client: Returns the shared LinearClient instance
    _get_linear_api_key: Legacy function to get API key from environment
    _run_linear_graphql: Legacy function to run GraphQL queries

Free functions (delegate to _get_default_client()):
    fetch_github_attachments: Fetch GitHub PR attachments for a ticket
    get_ticket_info: Get basic ticket information
    get_done_state_id: Get 'Done' workflow state ID for a team
    set_ticket_state: Update a ticket's workflow state
"""

from __future__ import annotations

from typing import Any

from scripts.clients.linear_client import (
    LinearClient,
    LinearClientError,
    _get_default_client,
)

# NOTE: New code should import LinearClient directly from scripts.clients.linear_client
# This module exists only for backwards compatibility with existing scripts.

# Backwards-compatible alias for existing code that imports LinearAPIError
LinearAPIError = LinearClientError

__all__ = [
    "LinearAPIError",
    "LinearClient",
    "_get_linear_api_key",
    "_run_linear_graphql",
    "fetch_github_attachments",
    "get_done_state_id",
    "get_ticket_info",
    "set_ticket_state",
]


# Backwards-compatible free functions


def _get_linear_api_key() -> str:
    """Get the Linear API key from environment.

    Returns:
        The Linear API key.

    Raises:
        LinearAPIError: If LINEAR_API_KEY environment variable not set.
    """
    import os

    api_key = os.environ.get("LINEAR_API_KEY")
    if not api_key:
        raise LinearAPIError("MISSING_API_KEY", "LINEAR_API_KEY environment variable not set")
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
    return _get_default_client()._run_graphql(query)


def fetch_github_attachments(ticket_id: str) -> list[dict[str, Any]]:
    """Fetch all GitHub PR attachments for a ticket with pagination.

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-123").

    Returns:
        List of attachment dictionaries with url and title.

    Raises:
        LinearAPIError: If the API call fails.
    """
    return _get_default_client().fetch_github_attachments(ticket_id)


def get_ticket_info(ticket_id: str) -> dict[str, Any]:
    """Get basic ticket info from Linear.

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-123").

    Returns:
        Dictionary with ticket data.

    Raises:
        LinearAPIError: If ticket not found or API call fails.
    """
    return _get_default_client().get_ticket_info(ticket_id)


def get_done_state_id(team_id: str) -> str:
    """Get the 'Done' workflow state ID for a team.

    Args:
        team_id: Linear team ID.

    Returns:
        The workflow state ID for 'Done' state.

    Raises:
        LinearAPIError: If no done state found or API call fails.
    """
    return _get_default_client().get_done_state_id(team_id)


def set_ticket_state(issue_uuid: str, state_id: str) -> bool:
    """Update a Linear ticket's state.

    Args:
        issue_uuid: Linear issue UUID (not the identifier like NES-123).
        state_id: Target workflow state ID.

    Returns:
        True if successful.

    Raises:
        LinearAPIError: If the API call fails.
    """
    _get_default_client().set_ticket_state(issue_uuid, state_id)
    return True
