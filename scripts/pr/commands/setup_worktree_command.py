"""Setup a git worktree for a Linear ticket."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.pr import git_dao, linear_dao

from .util import _find_available_branch_name


def setup_worktree_command(ticket_id: str) -> int:
    """Setup a git worktree for a Linear ticket.

    Gets the branch name from Linear, finds an available branch name (adding
    a counter if needed), and creates a new worktree with that branch.

    This command ALWAYS creates a new branch. If the branch name from Linear
    already exists (locally or on remote), a counter is appended (e.g.,
    branch-name-2, branch-name-3).

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-87").

    Returns:
        Exit code (0 for success).
    """
    try:
        # Get ticket info including branchName from Linear
        info = linear_dao.get_ticket_info(ticket_id)
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

        # Find an available branch name (adds counter if needed)
        # This always creates a new branch, never reuses an existing one
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

        # Check if worktree already exists at this path
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

    except (linear_dao.LinearAPIError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
