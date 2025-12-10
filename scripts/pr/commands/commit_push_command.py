"""Commit and push changes from a worktree."""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.pr import git_dao


def commit_push_command(worktree: Path, message: str, *, set_upstream: bool = False) -> int:
    """Commit and push changes from a worktree.

    Args:
        worktree: Path to the git worktree.
        message: Commit message.
        set_upstream: If True, set upstream tracking with -u flag on push.

    Returns:
        Exit code (0 for success).
    """
    if not worktree.is_dir():
        print(f"Error: Worktree not found at {worktree}", file=sys.stderr)
        return 1

    # Check for changes
    status, err = git_dao.get_status(worktree)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    if not status:
        print("No changes to commit")
        return 0

    # Stage all changes
    if not git_dao.stage_all(worktree):
        print("Error staging", file=sys.stderr)
        return 1

    # Commit
    if not git_dao.commit(worktree, message):
        print("Error committing", file=sys.stderr)
        return 1

    # Push
    success, err = git_dao.push(worktree, set_upstream=set_upstream)
    if not success:
        print(f"Error pushing: {err}", file=sys.stderr)
        return 1

    print(f"Successfully committed and pushed: {message}")
    return 0
