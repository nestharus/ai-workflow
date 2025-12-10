"""Command to list unresolved comments for a Linear ticket."""

from __future__ import annotations

import json
import sys

from scripts.pr import linear_dao


def list_unresolved_comments_command(ticket_id: str) -> int:
    """List unresolved comments for a Linear ticket.

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-123").

    Returns:
        Exit code (0 for success).
    """
    try:
        client = linear_dao.LinearClient()
        result = client.list_unresolved_comments(ticket_id)
        print(json.dumps(result, indent=2))
        return 0
    except linear_dao.LinearAPIError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
