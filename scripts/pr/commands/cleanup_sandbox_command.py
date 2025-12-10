"""Cleanup sandbox command for removing rebase sandboxes created by promote-worktree."""

from __future__ import annotations

import json
import re
import sys

from scripts.pr import git_dao, github_dao, linear_dao

MAX_BRANCH_NAME_LENGTH = 50


def _get_expected_branch_name(linear_branch_name: str) -> str:
    """Get the expected branch name from a Linear branch name.

    Truncates the branch name to MAX_BRANCH_NAME_LENGTH characters to match
    what _find_available_branch_name would produce when creating a new branch.

    Args:
        linear_branch_name: The branch name from Linear (may exceed 50 chars).

    Returns:
        The truncated branch name (max 50 characters).
    """
    if len(linear_branch_name) > MAX_BRANCH_NAME_LENGTH:
        return linear_branch_name[:MAX_BRANCH_NAME_LENGTH]
    return linear_branch_name


def _find_existing_branch_for_ticket(linear_branch_name: str) -> str | None:
    """Find an existing branch that matches the expected pattern for a ticket.

    Searches for branches matching the expected name or with counter suffixes
    (-2, -3, etc.). Returns the first existing branch found.

    Args:
        linear_branch_name: The branch name from Linear (may exceed 50 chars).

    Returns:
        The existing branch name if found, None otherwise.
    """
    expected_base = _get_expected_branch_name(linear_branch_name)

    # Check if the base expected branch exists
    if git_dao.branch_exists(expected_base):
        return expected_base

    # Check for counter suffixes (-2, -3, etc.)
    for counter in range(2, 101):
        suffix = f"-{counter}"
        # Truncate base to ensure total length stays within max_length
        truncated_base = expected_base[: MAX_BRANCH_NAME_LENGTH - len(suffix)]
        candidate = f"{truncated_base}{suffix}"
        if git_dao.branch_exists(candidate):
            return candidate

    return None


def _looks_like_pr_id(identifier: str) -> int | None:
    """Check if identifier looks like a PR ID (e.g., 17 or #17).

    Args:
        identifier: String to check.

    Returns:
        PR number if it matches, None otherwise.
    """
    # Strip leading # if present
    cleaned = identifier.lstrip("#")
    if cleaned.isdigit():
        return int(cleaned)
    return None


def _looks_like_ticket_id(identifier: str) -> bool:
    """Check if identifier looks like a Linear ticket ID (e.g., NES-87).

    Ticket IDs have format: LETTERS-NUMBER (e.g., NES-87, PROJ-123).

    Args:
        identifier: String to check.

    Returns:
        True if it matches the ticket ID pattern (letters-digits).
    """
    return bool(re.match(r"^[A-Za-z]+-\d+$", identifier))


def cleanup_sandbox_command(identifier: str | None = None) -> int:
    """Remove a rebase sandbox created by promote-worktree.

    Args:
        identifier: PR ID, ticket ID, branch name, or None for current branch.
                   Used to determine which sandbox to remove.

    Returns:
        Exit code (0 for success).
    """
    try:
        repo_root = git_dao.get_repo_root()
        if repo_root is None:
            print("Error: Not in a git repository", file=sys.stderr)
            return 1

        # Determine branch name
        branch_name: str | None
        if identifier is None:
            branch_name = git_dao.get_current_branch()
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
            info = linear_dao.get_ticket_info(identifier)
            linear_branch_name = info.get("branch_name")
            if not linear_branch_name:
                print(f"Error: No branch name for ticket {identifier}", file=sys.stderr)
                return 1
            branch_name = _find_existing_branch_for_ticket(linear_branch_name)
            if not branch_name:
                branch_name = _get_expected_branch_name(linear_branch_name)
        else:
            branch_name = identifier

        # Sanitize branch name for sandbox path
        sanitized_branch = branch_name.replace("/", "-")
        sandbox_path = repo_root / ".git" / "rebase-sandbox" / sanitized_branch

        if not sandbox_path.exists():
            print(f"No sandbox found at: {sandbox_path}", file=sys.stderr)
            return 1

        success, err = git_dao.remove_shared_clone(sandbox_path)
        if not success:
            print(f"Error removing sandbox: {err}", file=sys.stderr)
            return 1

        print(json.dumps({"status": "removed", "sandbox_path": str(sandbox_path)}, indent=2))
        return 0

    except linear_dao.LinearAPIError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except github_dao.GraphQLError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
