"""Get PR info for a PR ID, ticket ID, branch name, or current branch."""

from __future__ import annotations

import json
import re
import sys
from typing import Any

from scripts.clients.linear_client import LinearClientError, _get_default_client
from scripts.pr import git_dao, github_dao

from .util import (
    _find_existing_branch_for_ticket,
    _get_expected_branch_name,
    _looks_like_pr_id,
    _looks_like_ticket_id,
)


def get_pr_command(identifier: str | None = None) -> int:
    """Get PR info for a PR ID, ticket ID, branch name, or current branch.

    Accepts:
    - Nothing: Uses current branch
    - PR ID (e.g., 17 or #17): Gets branch from GitHub PR
    - Ticket ID (e.g., NES-87): Looks up branch from Linear
    - Branch name: Uses branch directly

    Args:
        identifier: PR ID, ticket ID, branch name, or None for current branch.

    Returns:
        Exit code (0 for success).
    """
    try:
        current_branch = git_dao.get_current_branch()
        in_worktree = git_dao.is_inside_worktree()

        # Declare variables that will be assigned in different branches
        branch_name: str | None
        worktree_path: str | None
        is_worktree: bool
        working_directory: str
        pr_number: int | None
        pr_url: str | None
        base_branch: str | None

        if identifier is None:
            # No argument: use current branch
            if not current_branch:
                print("Error: Not on a branch", file=sys.stderr)
                return 1

            branch_name = current_branch
            worktree_path = f".worktrees/{branch_name}" if in_worktree else None
            is_worktree = in_worktree
            working_directory = "."

            # Get PR info from GitHub
            pr_data = github_dao.get_pr_for_branch(branch_name)
            if pr_data:
                pr_number = pr_data.get("pr_number")
                pr_url = pr_data.get("pr_url")
                base_branch = pr_data.get("base_branch")
            else:
                pr_number = None
                pr_url = None
                base_branch = None

        elif (pr_id := _looks_like_pr_id(identifier)) is not None:
            # PR ID: get branch info from GitHub PR
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
            pr_url = (
                f"https://github.com/{github_dao.REPO_OWNER}/{github_dao.REPO_NAME}/pull/{pr_id}"
            )
            worktree_path = f".worktrees/{branch_name}" if branch_name else None

            # Determine working directory based on current branch and worktree status
            if current_branch == branch_name:
                is_worktree = in_worktree
                working_directory = "."
            else:
                is_worktree = True
                working_directory = worktree_path if worktree_path else "."

        elif _looks_like_ticket_id(identifier):
            # Ticket ID: get branch from Linear
            info = _get_default_client().get_ticket_info(identifier)
            linear_branch_name = info.get("branch_name")

            if not linear_branch_name:
                print(
                    f"Error: No branch name configured for ticket {identifier}",
                    file=sys.stderr,
                )
                return 1

            # Fetch GitHub attachments to find PR
            attachments = _get_default_client().fetch_github_attachments(identifier)

            # Collect all PR candidates from attachments
            pr_url = None
            pr_number = None
            pr_candidates: list[tuple[str, int]] = []
            for attachment in attachments:
                url = attachment.get("url", "")
                if "/pull/" in url:
                    match = re.search(r"/pull/(\d+)", url)
                    if match:
                        pr_candidates.append((url, int(match.group(1))))

            # Find the first open PR by checking state via GitHub API
            # Also get the actual branch name from GitHub if PR exists
            branch_name = None
            for url, number in pr_candidates:
                try:
                    gh_pr_info = github_dao.get_pr_info(number)
                    if gh_pr_info.get("state") == "OPEN":
                        pr_url = url
                        pr_number = number
                        # Use branch name from GitHub PR (most accurate)
                        branch_name = gh_pr_info.get("head_branch")
                        break
                except github_dao.GraphQLError:
                    continue

            # If no open PR found, find existing branch or use expected truncated name
            if not branch_name:
                branch_name = _find_existing_branch_for_ticket(linear_branch_name)
                if not branch_name:
                    # Fall back to expected truncated name for worktree path
                    branch_name = _get_expected_branch_name(linear_branch_name)

            worktree_path = f".worktrees/{branch_name}"

            # Determine working directory based on current branch and worktree status
            if current_branch == branch_name:
                # We're on the correct branch (either main repo or inside worktree)
                is_worktree = in_worktree
                working_directory = "."
            else:
                # We're on a different branch, need to use the worktree
                is_worktree = True
                working_directory = worktree_path

            # If we have a PR number, fetch the base branch from GitHub
            base_branch = None
            if pr_number:
                gh_pr_info = github_dao.get_pr_info(pr_number)
                base_branch = gh_pr_info.get("base_branch")

        else:
            # Branch name: use directly
            branch_name = identifier
            worktree_path = f".worktrees/{branch_name}"

            # Determine working directory based on current branch and worktree status
            if current_branch == branch_name:
                is_worktree = in_worktree
                working_directory = "."
            else:
                is_worktree = True
                working_directory = worktree_path

            # Get PR info from GitHub
            pr_data = github_dao.get_pr_for_branch(branch_name)
            if pr_data:
                pr_number = pr_data.get("pr_number")
                pr_url = pr_data.get("pr_url")
                base_branch = pr_data.get("base_branch")
            else:
                pr_number = None
                pr_url = None
                base_branch = None

        pr_info: dict[str, Any] = {
            "branch_name": branch_name,
            "worktree_path": worktree_path,
            "working_directory": working_directory,
            "is_worktree": is_worktree,
            "pr_number": pr_number,
            "pr_url": pr_url,
            "base_branch": base_branch,
        }

        print(json.dumps(pr_info, indent=2))
        return 0
    except LinearClientError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except github_dao.GraphQLError as e:
        print(f"Error fetching PR info from GitHub: {e}", file=sys.stderr)
        return 1
