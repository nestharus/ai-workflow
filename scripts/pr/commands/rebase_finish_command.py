"""Rebase finish command implementation.

Force push, sync source worktree, and cleanup sandbox.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from scripts.clients.linear_client import LinearClientError, _get_default_client
from scripts.pr import git_dao, github_dao

from .util import (
    _find_existing_branch_for_ticket,
    _get_expected_branch_name,
    _looks_like_pr_id,
    _looks_like_ticket_id,
)


def rebase_finish_command(identifier: str | None = None) -> int:
    """Force push, sync source worktree, and cleanup sandbox.

    Combines force push + sync + cleanup into one command.

    Args:
        identifier: PR ID, ticket ID, branch name, or None for current branch.

    Returns:
        Exit code (0 for success).
    """
    try:
        repo_root = git_dao.get_repo_root()
        if repo_root is None:
            print("Error: Not in a git repository", file=sys.stderr)
            return 1

        current_branch = git_dao.get_current_branch()

        # Determine branch name
        branch_name: str | None
        if identifier is None:
            branch_name = current_branch
            if not branch_name:
                print("Error: Not on a branch", file=sys.stderr)
                return 1
        elif (pr_id := _looks_like_pr_id(identifier)) is not None:
            gh_pr_info = github_dao.get_pr_info(pr_id)
            branch_name = gh_pr_info.get("head_branch")
            if not branch_name:
                print(f"Error: Could not determine branch for PR #{pr_id}", file=sys.stderr)
                return 1
        elif _looks_like_ticket_id(identifier):
            info = _get_default_client().get_ticket_info(identifier)
            linear_branch_name = info.get("branch_name")
            if not linear_branch_name:
                print(f"Error: No branch name for ticket {identifier}", file=sys.stderr)
                return 1
            branch_name = _find_existing_branch_for_ticket(linear_branch_name)
            if not branch_name:
                branch_name = _get_expected_branch_name(linear_branch_name)
        else:
            branch_name = identifier

        # Find sandbox
        sanitized_branch = branch_name.replace("/", "-")
        sandbox_path = repo_root / ".git" / "rebase-sandbox" / sanitized_branch

        if not sandbox_path.exists():
            print(f"Error: No sandbox found at: {sandbox_path}", file=sys.stderr)
            return 1

        # Determine source path
        working_directory = "."
        if current_branch != branch_name:
            working_directory = f".worktrees/{branch_name}"

        source_path = Path.cwd() if working_directory == "." else repo_root / working_directory

        # Force push from sandbox
        print("Force pushing from sandbox...", file=sys.stderr)
        success, err = git_dao.force_push(sandbox_path)
        if not success:
            print(f"Error pushing: {err}", file=sys.stderr)
            return 1

        # Sync source worktree if it exists
        if source_path.is_dir():
            print(f"Syncing source worktree: {source_path}", file=sys.stderr)
            success, err = git_dao.reset_hard_to_remote(source_path, branch_name)
            if not success:
                print(f"Warning: Failed to sync source worktree: {err}", file=sys.stderr)

        # Cleanup sandbox
        print("Cleaning up sandbox...", file=sys.stderr)
        success, err = git_dao.remove_shared_clone(sandbox_path)
        if not success:
            print(f"Warning: Failed to remove sandbox: {err}", file=sys.stderr)

        result: dict[str, Any] = {
            "status": "success",
            "branch_name": branch_name,
            "source_path": str(source_path),
        }
        print(json.dumps(result, indent=2))
        return 0

    except LinearClientError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except github_dao.GraphQLError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
