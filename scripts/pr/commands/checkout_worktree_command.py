"""Checkout an existing branch into a worktree.

This module provides the checkout_worktree_command function which handles
checking out existing branches into git worktrees, supporting both Linear
ticket IDs and branch names as identifiers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.clients.linear_client import LinearClientError, _get_default_client
from scripts.pr import git_dao

from .util import (
    _find_existing_branch_for_ticket,
    _get_expected_branch_name,
    _looks_like_ticket_id,
)


def checkout_worktree_command(identifier: str) -> int:
    """Checkout an existing branch into a worktree.

    Takes either a Linear ticket ID (e.g., "NES-87") or a branch name. If the
    identifier looks like a ticket ID (contains a dash with letters before it),
    fetches the branch name from Linear. Otherwise, uses the identifier as the
    branch name directly.

    Unlike setup_worktree_command, this command:
    - Does NOT create a new branch (only checks out existing branches)
    - Errors if the branch doesn't exist locally or on remote
    - If the branch exists only on remote, creates a local tracking branch

    Args:
        identifier: Linear ticket ID (e.g., "NES-87") or branch name.

    Returns:
        Exit code (0 for success).
    """
    # Determine if identifier is a ticket ID or branch name
    is_ticket_id = _looks_like_ticket_id(identifier)

    # Fetch origin to get latest remote refs before looking up branches
    print("Fetching origin...", file=sys.stderr)
    success, err = git_dao.fetch_origin()
    if not success:
        print(f"Error fetching origin: {err}", file=sys.stderr)
        return 1

    if is_ticket_id:
        # Fetch branch name from Linear and find existing branch
        try:
            info = _get_default_client().get_ticket_info(identifier)
            linear_branch_name = info.get("branch_name")
            if not linear_branch_name:
                print(
                    f"Error: No branch name found for ticket {identifier}",
                    file=sys.stderr,
                )
                return 1

            # Find the actual existing branch (may be truncated or have counter suffix)
            branch_name = _find_existing_branch_for_ticket(linear_branch_name)
            if not branch_name:
                expected = _get_expected_branch_name(linear_branch_name)
                print(
                    f"Error: No existing branch found for ticket {identifier}.",
                    file=sys.stderr,
                )
                print(
                    f"Expected branch pattern: '{expected}' (or with -2, -3, etc. suffix)",
                    file=sys.stderr,
                )
                print(
                    "Use 'uv run pr setup-worktree' or '/execute-plan' to create a new branch.",
                    file=sys.stderr,
                )
                return 1
        except LinearClientError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    else:
        branch_name = identifier

    # Check if branch exists locally or only on remote
    exists_local = git_dao.branch_exists_local(branch_name)
    exists_remote = git_dao.branch_exists_remote(branch_name)

    if not exists_local and not exists_remote:
        print(
            f"Error: Branch '{branch_name}' does not exist locally or on remote.",
            file=sys.stderr,
        )
        print(
            "Use 'uv run pr setup-worktree' or '/execute-plan' to create a new branch.",
            file=sys.stderr,
        )
        return 1

    # Worktree path: .worktrees/<branch_name>
    worktree_path = Path(".worktrees") / branch_name

    # Check if worktree already exists at this path
    if git_dao.worktree_exists(worktree_path):
        print(
            json.dumps(
                {
                    "status": "exists",
                    "worktree_path": str(worktree_path),
                    "branch_name": branch_name,
                    "branch_created": False,
                },
                indent=2,
            )
        )
        return 0

    # Create worktree for existing branch (not creating a new branch)
    if exists_local:
        # Branch exists locally, just checkout
        print(
            f"Creating worktree at {worktree_path} (existing local branch: {branch_name})...",
            file=sys.stderr,
        )
        success, err = git_dao.create_worktree(worktree_path, branch_name, create_branch=False)
    else:
        # Branch only exists on remote, create local tracking branch
        print(
            f"Creating worktree at {worktree_path} (tracking remote branch: {branch_name})...",
            file=sys.stderr,
        )
        # Use git worktree add with remote tracking
        success, err = git_dao.create_worktree_tracking(worktree_path, branch_name)

    if not success:
        print(f"Error creating worktree: {err}", file=sys.stderr)
        return 1

    # Output result as JSON
    print(
        json.dumps(
            {
                "status": "created",
                "worktree_path": str(worktree_path),
                "branch_name": branch_name,
                "branch_created": False,
                "tracked_remote": not exists_local,
            },
            indent=2,
        )
    )
    return 0
