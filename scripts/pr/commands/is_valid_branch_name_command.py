"""Validate branch names against expected Linear ticket branch patterns."""

from __future__ import annotations

import json
import sys

from scripts.clients.linear_client import LinearClientError, _get_default_client

from .util import _is_valid_branch_name


def is_valid_branch_name_command(ticket_id: str, branch_name: str) -> int:
    """Check if a branch name matches the expected pattern for a ticket.

    A branch name is valid if it matches either:
    1. The expected branch name from Linear (truncated to 50 chars)
    2. The pattern <expected_branch>-N where N >= 2 (for counter suffixes)

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-87").
        branch_name: Branch name to validate.

    Returns:
        Exit code (0 for valid, 1 for invalid or error).
    """
    try:
        info = _get_default_client().get_ticket_info(ticket_id)
        expected_base = info.get("branch_name")

        if not expected_base:
            print(f"Error: No branch name found for ticket {ticket_id}", file=sys.stderr)
            return 1

        is_valid = _is_valid_branch_name(branch_name, expected_base)

        print(
            json.dumps(
                {
                    "ticket_id": ticket_id,
                    "branch_name": branch_name,
                    "expected_base": expected_base,
                    "is_valid": is_valid,
                },
                indent=2,
            )
        )

        return 0 if is_valid else 1

    except LinearClientError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
