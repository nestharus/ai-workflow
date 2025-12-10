"""Open PR command implementation."""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.pr import github_dao


def open_pr_command(worktree: Path, title: str, body: str, branch: str) -> int:
    """Create a new PR for a branch.

    Args:
        worktree: Path to the git worktree.
        title: PR title.
        body: PR body text.
        branch: Branch name for the PR head.

    Returns:
        Exit code (0 for success).
    """
    if not worktree.is_dir():
        print(f"Error: Worktree not found at {worktree}", file=sys.stderr)
        return 1

    success, result = github_dao.create_pr(str(worktree), title, body, branch)
    if not success:
        print(f"Error creating PR: {result}", file=sys.stderr)
        return 1

    print(result)
    return 0
