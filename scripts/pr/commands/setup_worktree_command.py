"""Setup a git worktree for a Linear ticket."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.clients.linear_client import LinearClientError, _get_default_client
from scripts.pr import git_dao

from .util import _find_available_branch_name, _find_existing_branch_for_ticket


def setup_worktree_command(ticket_id: str) -> int:
    """Setup a git worktree for a Linear ticket.

    Gets the branch name from Linear and either:
    1. Reuses an existing worktree if one exists for this ticket (with pull)
    2. Creates a new worktree with a new branch

    When reusing an existing worktree, the command pulls latest changes.
    When creating a new worktree, if the branch name from Linear already
    exists (locally or on remote), a counter is appended (e.g.,
    branch-name-2, branch-name-3).

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-87").

    Returns:
        Exit code (0 for success).
    """
    try:
        # Get ticket info including branchName from Linear
        info = _get_default_client().get_ticket_info(ticket_id)
        base_branch_name = info.get("branch_name")

        if not base_branch_name:
            print(f"Error: No branch name found for ticket {ticket_id}", file=sys.stderr)
            return 1

        # Get current branch (base branch for PR)
        base_branch = git_dao.get_current_branch()
        if not base_branch:
            print("Error: Could not determine current branch", file=sys.stderr)
            return 1

        # Fetch origin to get latest remote refs before checking branch existence
        print("Fetching origin...", file=sys.stderr)
        success, err = git_dao.fetch_origin()
        if not success:
            print(f"Error fetching origin: {err}", file=sys.stderr)
            return 1

        # First, check if an existing branch/worktree exists for this ticket
        existing_branch = _find_existing_branch_for_ticket(base_branch_name)
        if existing_branch:
            base_dir = Path(".worktrees").resolve()
            existing_worktree_path = (base_dir / existing_branch).resolve()

            # Check if the worktree exists on disk
            if git_dao.worktree_exists(existing_worktree_path):
                print(
                    f"Found existing worktree at {existing_worktree_path}, pulling latest...",
                    file=sys.stderr,
                )

                # Pull latest changes in the worktree
                success, err = git_dao.pull_in_worktree(existing_worktree_path)
                if not success:
                    print(f"Warning: Could not pull in worktree: {err}", file=sys.stderr)
                    # Continue anyway, the worktree still exists

                print(
                    json.dumps(
                        {
                            "status": "exists",
                            "worktree_path": str(existing_worktree_path),
                            "branch_name": existing_branch,
                            "base_branch": base_branch,
                            "pulled": success,
                        },
                        indent=2,
                    )
                )
                return 0

        # No existing worktree found, create a new one
        # Find an available branch name (adds counter if needed)
        branch_name = _find_available_branch_name(base_branch_name)

        # Worktree base directory
        base_dir = Path(".worktrees").resolve()
        # Note: branch names with slashes create nested directories
        worktree_path = (base_dir / branch_name).resolve()
        # Ensure the resolved path stays within .worktrees to avoid traversal
        try:
            worktree_path.relative_to(base_dir)
        except ValueError:
            print("Error: Unsafe branch name resolves outside .worktrees", file=sys.stderr)
            return 1

        # Check if worktree already exists at this path (edge case)
        if git_dao.worktree_exists(worktree_path):
            print(
                json.dumps(
                    {
                        "status": "exists",
                        "worktree_path": str(worktree_path),
                        "branch_name": branch_name,
                        "base_branch": base_branch,
                    },
                    indent=2,
                )
            )
            return 0

        # Create worktree with new branch
        print(
            f"Creating worktree at {worktree_path} (new branch: {branch_name})...",
            file=sys.stderr,
        )

        success, err = git_dao.create_worktree(worktree_path, branch_name, create_branch=True)
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
                    "base_branch": base_branch,
                    "branch_created": True,
                },
                indent=2,
            )
        )
        return 0

    except (LinearClientError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
