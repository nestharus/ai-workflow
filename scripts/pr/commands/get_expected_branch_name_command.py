"""Get expected branch name command implementation.

High-level command function that orchestrates DAO operations.
"""

from __future__ import annotations

import json
import sys

from scripts.clients.linear_client import LinearClientError, _get_default_client

MAX_BRANCH_NAME_LENGTH = 50


def get_expected_branch_name_command(ticket_id: str) -> int:
    """Get the expected branch name for a Linear ticket.

    This returns the base branch name from Linear (before any counter suffixes
    are added). The name is truncated to 50 characters if needed.

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-87").

    Returns:
        Exit code (0 for success).
    """
    try:
        info = _get_default_client().get_ticket_info(ticket_id)
        branch_name = info.get("branch_name")

        if not branch_name:
            print(f"Error: No branch name found for ticket {ticket_id}", file=sys.stderr)
            return 1

        # Truncate to max length (matching _find_available_branch_name behavior)
        if len(branch_name) > MAX_BRANCH_NAME_LENGTH:
            branch_name = branch_name[:MAX_BRANCH_NAME_LENGTH]

        print(
            json.dumps(
                {
                    "ticket_id": ticket_id,
                    "expected_branch_name": branch_name,
                },
                indent=2,
            )
        )
        return 0

    except LinearClientError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
