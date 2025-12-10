"""Extract ticket ID from a branch name and validate it against Linear."""

from __future__ import annotations

import json
import sys

from scripts.pr import git_dao, linear_dao

from .util import _extract_ticket_id_from_branch


def extract_ticket_id_command(branch_name: str | None = None) -> int:
    """Extract ticket ID from a branch name.

    If branch_name is not provided, uses the current branch.
    Validates the extracted ticket ID against Linear API.

    Args:
        branch_name: Branch name to parse, or None to use current branch.

    Returns:
        Exit code (0 for success with valid ticket, 1 for no ticket or error).
    """
    # Get branch name if not provided
    if branch_name is None:
        branch_name = git_dao.get_current_branch()
        if not branch_name:
            print("Error: Not on a branch", file=sys.stderr)
            return 1

    # Extract potential ticket ID
    ticket_id = _extract_ticket_id_from_branch(branch_name)

    if not ticket_id:
        print(
            json.dumps(
                {
                    "branch_name": branch_name,
                    "ticket_id": None,
                    "valid": False,
                    "reason": "No ticket ID pattern found in branch name",
                },
                indent=2,
            )
        )
        return 1

    # Validate against Linear API
    try:
        info = linear_dao.get_ticket_info(ticket_id)
        # If we get here without exception, ticket exists
        print(
            json.dumps(
                {
                    "branch_name": branch_name,
                    "ticket_id": ticket_id,
                    "valid": True,
                    "ticket_title": info.get("title"),
                },
                indent=2,
            )
        )
        return 0
    except linear_dao.LinearAPIError:
        print(
            json.dumps(
                {
                    "branch_name": branch_name,
                    "ticket_id": ticket_id,
                    "valid": False,
                    "reason": f"Ticket {ticket_id} not found in Linear",
                },
                indent=2,
            )
        )
        return 1
