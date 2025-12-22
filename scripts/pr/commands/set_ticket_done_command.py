"""Set ticket done command implementation."""

from __future__ import annotations

import sys

from scripts.clients.linear_client import LinearClientError, _get_default_client


def set_ticket_done_command(ticket_id: str) -> int:
    """Mark a Linear ticket as Done.

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-123").

    Returns:
        Exit code (0 for success).
    """
    try:
        info = _get_default_client().get_ticket_info(ticket_id)
        team_id = info.get("team_id")
        if not team_id:
            print(f"Error: Could not get team ID for {ticket_id}", file=sys.stderr)
            return 1

        done_state_id = _get_default_client().get_done_state_id(team_id)
        issue_uuid = info.get("id")
        if not issue_uuid:
            print(f"Error: Could not get issue UUID for {ticket_id}", file=sys.stderr)
            return 1
        _get_default_client().set_ticket_state(issue_uuid, done_state_id)

        print(f"Marked {ticket_id} as Done")
        return 0
    except LinearClientError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
