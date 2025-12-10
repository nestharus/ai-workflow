"""Create a shared clone sandbox for safe rebase/merge operations."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.pr import git_dao, github_dao, linear_dao

from .util import (
    _find_existing_branch_for_ticket,
    _get_expected_branch_name,
    _looks_like_pr_id,
    _looks_like_ticket_id,
)


def promote_worktree_command(identifier: str | None = None) -> int:
    """Create a shared clone sandbox for safe rebase/merge operations.

    ALWAYS creates a sandbox, whether working from repo root or a worktree.
    This keeps the source directory unblocked during rebase/merge operations.

    The sandbox is created at .git/rebase-sandbox/<sanitized-branch-name>/
    The source_path points to wherever the clean code lives (repo root or worktree).

    Args:
        identifier: PR ID, ticket ID, branch name, or None for current branch.

    Returns:
        Exit code (0 for success).
    """
    try:
        current_branch = git_dao.get_current_branch()
        in_worktree = git_dao.is_inside_worktree()
        repo_root = git_dao.get_repo_root()

        if repo_root is None:
            print("Error: Not in a git repository", file=sys.stderr)
            return 1

        # Determine branch and worktree info (reuse logic from get_pr_command)
        branch_name: str | None
        worktree_path: str | None
        working_directory: str
        pr_number: int | None
        base_branch: str | None

        if identifier is None:
            if not current_branch:
                print("Error: Not on a branch", file=sys.stderr)
                return 1

            branch_name = current_branch
            worktree_path = f".worktrees/{branch_name}" if in_worktree else None
            working_directory = "."

            pr_data = github_dao.get_pr_for_branch(branch_name)
            if pr_data:
                pr_number = pr_data.get("pr_number")
                base_branch = pr_data.get("base_branch")
            else:
                pr_number = None
                base_branch = "main"  # Default fallback

        elif (pr_id := _looks_like_pr_id(identifier)) is not None:
            gh_pr_info = github_dao.get_pr_info(pr_id)
            branch_name = gh_pr_info.get("head_branch")
            base_branch = gh_pr_info.get("base_branch")

            if not branch_name:
                print(
                    f"Error: Could not determine head branch for PR #{pr_id}",
                    file=sys.stderr,
                )
                return 1

            pr_number = pr_id
            worktree_path = f".worktrees/{branch_name}"
            working_directory = "." if current_branch == branch_name else worktree_path

        elif _looks_like_ticket_id(identifier):
            info = linear_dao.get_ticket_info(identifier)
            linear_branch_name = info.get("branch_name")

            if not linear_branch_name:
                print(
                    f"Error: No branch name configured for ticket {identifier}",
                    file=sys.stderr,
                )
                return 1

            # Find existing branch
            branch_name = _find_existing_branch_for_ticket(linear_branch_name)
            if not branch_name:
                branch_name = _get_expected_branch_name(linear_branch_name)

            worktree_path = f".worktrees/{branch_name}"
            working_directory = "." if current_branch == branch_name else worktree_path

            # Try to get base_branch from PR if one exists
            attachments = linear_dao.fetch_github_attachments(identifier)
            pr_number = None
            base_branch = "main"  # Default
            for attachment in attachments:
                url = attachment.get("url", "")
                if "/pull/" in url:
                    match = re.search(r"/pull/(\d+)", url)
                    if match:
                        try:
                            gh_pr_info = github_dao.get_pr_info(int(match.group(1)))
                            if gh_pr_info.get("state") == "OPEN":
                                pr_number = int(match.group(1))
                                base_branch = gh_pr_info.get("base_branch", "main")
                                break
                        except github_dao.GraphQLError:
                            continue
        else:
            branch_name = identifier
            worktree_path = f".worktrees/{branch_name}"
            working_directory = "." if current_branch == branch_name else worktree_path

            pr_data = github_dao.get_pr_for_branch(branch_name)
            if pr_data:
                pr_number = pr_data.get("pr_number")
                base_branch = pr_data.get("base_branch")
            else:
                pr_number = None
                base_branch = "main"

        # Determine source path (where to clone from)
        source_path = Path.cwd() if working_directory == "." else repo_root / working_directory

        if not source_path.is_dir():
            print(f"Error: Source path does not exist: {source_path}", file=sys.stderr)
            return 1

        # Create sanitized name for sandbox directory (replace slashes with dashes)
        sanitized_branch = branch_name.replace("/", "-") if branch_name else "unknown"
        sandbox_path = repo_root / ".git" / "rebase-sandbox" / sanitized_branch

        # Check if sandbox already exists
        if sandbox_path.exists():
            print(f"Sandbox already exists at: {sandbox_path}", file=sys.stderr)
            print("Use 'uv run pr cleanup-sandbox' to remove it first", file=sys.stderr)
            # Return existing sandbox info
            result: dict[str, Any] = {
                "status": "exists",
                "sandbox_path": str(sandbox_path),
                "source_path": str(source_path),
                "branch_name": branch_name,
                "base_branch": base_branch,
                "pr_number": pr_number,
            }
            print(json.dumps(result, indent=2))
            return 0

        # Create shared clone
        print(f"Creating rebase sandbox at: {sandbox_path}", file=sys.stderr)
        success, err = git_dao.create_shared_clone(source_path, sandbox_path, branch_name)
        if not success:
            print(f"Error creating sandbox: {err}", file=sys.stderr)
            return 1

        result = {
            "status": "created",
            "sandbox_path": str(sandbox_path),
            "source_path": str(source_path),
            "branch_name": branch_name,
            "base_branch": base_branch,
            "pr_number": pr_number,
        }
        print(json.dumps(result, indent=2))
        return 0

    except linear_dao.LinearAPIError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except github_dao.GraphQLError as e:
        print(f"Error fetching PR info from GitHub: {e}", file=sys.stderr)
        return 1
