"""Set ticket done command implementation."""

from __future__ import annotations

import sys

from scripts.pr import linear_dao


def set_ticket_done_command(ticket_id: str) -> int:
    """Mark a Linear ticket as Done.

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-123").

    Returns:
        Exit code (0 for success).
    """
    try:
        info = linear_dao.get_ticket_info(ticket_id)
        team_id = info.get("team_id")
        if not team_id:
            print(f"Error: Could not get team ID for {ticket_id}", file=sys.stderr)
            return 1

        done_state_id = linear_dao.get_done_state_id(team_id)
        issue_uuid = info.get("id")
        if not issue_uuid:
            print(f"Error: Could not get issue UUID for {ticket_id}", file=sys.stderr)
            return 1
        success = linear_dao.set_ticket_state(issue_uuid, done_state_id)

        if success:
            print(f"Marked {ticket_id} as Done")
            return 0
        print(f"Failed to mark {ticket_id} as Done", file=sys.stderr)
        return 1
    except linear_dao.LinearAPIError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
