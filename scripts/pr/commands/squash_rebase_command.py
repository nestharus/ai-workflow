"""Squash and rebase command for PR operations.

Provides functionality to squash commits and rebase onto a target branch.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.pr import git_dao


def squash_rebase_command(worktree: Path, base_branch: str) -> int:
    """Squash all commits and rebase onto base branch.

    Args:
        worktree: Path to the git worktree.
        base_branch: Target branch to rebase onto.

    Returns:
        Exit code (0 for success, 1 if conflicts need resolution).
    """
    if not worktree.is_dir():
        print(f"Error: Worktree not found at {worktree}", file=sys.stderr)
        return 1

    # Fetch latest target branch
    print(f"Fetching origin/{base_branch}...")
    success, err = git_dao.fetch_branch(worktree, base_branch)
    if not success:
        print(f"Error fetching branch: {err}", file=sys.stderr)
        return 1

    # Count commits ahead of target branch
    commit_count, err = git_dao.count_commits_ahead(worktree, base_branch)
    if commit_count < 0:
        print(f"Error counting commits: {err}", file=sys.stderr)
        return 1

    print(f"Found {commit_count} commit(s) ahead of origin/{base_branch}")

    # If more than 1 commit, squash them using soft reset and recommit
    if commit_count > 1:
        print(f"Squashing {commit_count} commits...")

        # Get the merge base
        merge_base, err = git_dao.get_merge_base(worktree, base_branch)
        if not merge_base:
            print(f"Error finding merge base: {err}", file=sys.stderr)
            return 1

        # Get the current commit message for the squashed commit
        commit_msg = git_dao.get_last_commit_message(worktree)

        # Soft reset to merge base, keeping changes staged
        success, err = git_dao.soft_reset(worktree, merge_base)
        if not success:
            print(f"Error during soft reset: {err}", file=sys.stderr)
            return 1

        # Recommit with the original message
        success = git_dao.commit(worktree, commit_msg)
        if not success:
            print("Error creating squashed commit", file=sys.stderr)
            return 1

        print("Commits squashed successfully")

    # Rebase onto target branch
    print(f"Rebasing onto origin/{base_branch}...")
    success, has_conflicts, err = git_dao.rebase(worktree, base_branch)

    if not success:
        if has_conflicts:
            print("Rebase conflicts detected. Resolve conflicts and continue.")
            print("After resolving: git add <files> && git rebase --continue")
            return 1
        print(f"Error during rebase: {err}", file=sys.stderr)
        return 1

    print("Squash and rebase completed successfully")
    return 0
