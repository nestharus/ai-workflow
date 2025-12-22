"""Rebase start command - create sandbox, gather context, squash and rebase."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.clients.linear_client import LinearClientError, _get_default_client
from scripts.pr import git_dao, github_dao

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


def rebase_start_command(identifier: str | None = None) -> int:
    """Create sandbox, gather context, squash and rebase onto base branch.

    Combines promote-worktree + context gathering + squash-rebase into one command.
    Returns all context needed for conflict resolution if conflicts occur.

    Args:
        identifier: PR ID, ticket ID, branch name, or None for current branch.

    Returns:
        Exit code (0 for success, 1 for conflicts needing resolution, 2 for error).
    """
    try:
        repo_root = git_dao.get_repo_root()
        if repo_root is None:
            print("Error: Not in a git repository", file=sys.stderr)
            return 2

        current_branch = git_dao.get_current_branch()

        # Determine branch and worktree info
        branch_name: str | None
        pr_number: int | None
        base_branch: str | None

        if identifier is None:
            if not current_branch:
                print("Error: Not on a branch", file=sys.stderr)
                return 2

            branch_name = current_branch
            pr_data = github_dao.get_pr_for_branch(branch_name)
            if pr_data:
                pr_number = pr_data.get("pr_number")
                base_branch = pr_data.get("base_branch", "main")
            else:
                pr_number = None
                base_branch = "main"

        elif (pr_id := _looks_like_pr_id(identifier)) is not None:
            gh_pr_info = github_dao.get_pr_info(pr_id)
            branch_name = gh_pr_info.get("head_branch")
            base_branch = gh_pr_info.get("base_branch", "main")

            if not branch_name:
                print(f"Error: Could not determine head branch for PR #{pr_id}", file=sys.stderr)
                return 2

            pr_number = pr_id

        elif _looks_like_ticket_id(identifier):
            info = _get_default_client().get_ticket_info(identifier)
            linear_branch_name = info.get("branch_name")

            if not linear_branch_name:
                print(f"Error: No branch name configured for ticket {identifier}", file=sys.stderr)
                return 2

            branch_name = _find_existing_branch_for_ticket(linear_branch_name)
            if not branch_name:
                branch_name = _get_expected_branch_name(linear_branch_name)

            # Try to get base_branch from PR if one exists
            attachments = _get_default_client().fetch_github_attachments(identifier)
            pr_number = None
            base_branch = "main"
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
            pr_data = github_dao.get_pr_for_branch(branch_name)
            if pr_data:
                pr_number = pr_data.get("pr_number")
                base_branch = pr_data.get("base_branch", "main")
            else:
                pr_number = None
                base_branch = "main"

        # Determine source path
        working_directory = "."
        if current_branch != branch_name:
            working_directory = f".worktrees/{branch_name}"

        source_path = Path.cwd() if working_directory == "." else repo_root / working_directory

        if not source_path.is_dir():
            print(f"Error: Source path does not exist: {source_path}", file=sys.stderr)
            return 2

        # Create sandbox
        sanitized_branch = branch_name.replace("/", "-") if branch_name else "unknown"
        sandbox_path = repo_root / ".git" / "rebase-sandbox" / sanitized_branch

        # Clean up existing sandbox if present
        if sandbox_path.exists():
            success, err = git_dao.remove_shared_clone(sandbox_path)
            if not success:
                print(f"Error cleaning up existing sandbox: {err}", file=sys.stderr)
                return 2

        # Create shared clone
        print(f"Creating rebase sandbox at: {sandbox_path}", file=sys.stderr)
        success, err = git_dao.create_shared_clone(source_path, sandbox_path, branch_name)
        if not success:
            print(f"Error creating sandbox: {err}", file=sys.stderr)
            return 2

        # Gather merge context
        print(f"Fetching origin/{base_branch}...", file=sys.stderr)
        success, err = git_dao.fetch_branch(sandbox_path, base_branch)
        if not success:
            print(f"Error fetching branch: {err}", file=sys.stderr)
            return 2

        # Get merge base
        base_commit, err = git_dao.get_merge_base(sandbox_path, base_branch)
        if not base_commit:
            print(f"Error finding merge base: {err}", file=sys.stderr)
            return 2

        # Get target commits
        target_commits = git_dao.get_commits_between(
            sandbox_path, base_commit, f"origin/{base_branch}"
        )

        # Count commits ahead
        commit_count, err = git_dao.count_commits_ahead(sandbox_path, base_branch)
        if commit_count < 0:
            print(f"Error counting commits: {err}", file=sys.stderr)
            return 2

        print(f"Found {commit_count} commit(s) ahead of origin/{base_branch}", file=sys.stderr)

        # Squash if needed
        if commit_count > 1:
            print(f"Squashing {commit_count} commits...", file=sys.stderr)
            commit_msg = git_dao.get_last_commit_message(sandbox_path)
            success, err = git_dao.soft_reset(sandbox_path, base_commit)
            if not success:
                print(f"Error during soft reset: {err}", file=sys.stderr)
                return 2

            success = git_dao.commit(sandbox_path, commit_msg)
            if not success:
                print("Error creating squashed commit", file=sys.stderr)
                return 2

            print("Commits squashed successfully", file=sys.stderr)

        # Rebase
        print(f"Rebasing onto origin/{base_branch}...", file=sys.stderr)
        success, has_conflicts, err = git_dao.rebase(sandbox_path, base_branch)

        # Build result
        result: dict[str, Any] = {
            "sandbox_path": str(sandbox_path),
            "source_path": str(source_path),
            "branch_name": branch_name,
            "base_branch": base_branch,
            "pr_number": pr_number,
            "base_commit": base_commit,
            "target_commits": target_commits,
            "has_conflicts": has_conflicts,
        }

        if has_conflicts:
            # Get conflicted files and source commit
            conflicted_files = git_dao.get_conflicted_files(sandbox_path)
            source_commit = git_dao.get_head_sha(sandbox_path)
            result["conflicted_files"] = conflicted_files
            result["source_commit"] = source_commit
            print("Rebase conflicts detected", file=sys.stderr)
            print(json.dumps(result, indent=2))
            return 1

        if not success:
            print(f"Error during rebase: {err}", file=sys.stderr)
            return 2

        print("Squash and rebase completed successfully", file=sys.stderr)
        print(json.dumps(result, indent=2))
        return 0

    except LinearClientError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except github_dao.GraphQLError as e:
        print(f"Error fetching PR info from GitHub: {e}", file=sys.stderr)
        return 2
