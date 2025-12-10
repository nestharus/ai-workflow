"""Command to merge a pull request."""

from __future__ import annotations

import sys

from scripts.pr import github_dao


def merge_pr_command(pr_number: int) -> int:
    """Merge a PR using squash merge.

    Args:
        pr_number: PR number to merge.

    Returns:
        Exit code (0 for success).
    """
    success = github_dao.merge_pr(pr_number, squash=True, auto=True)
    if not success:
        print(f"Error merging PR #{pr_number}", file=sys.stderr)
        return 1

    print(f"Merged PR #{pr_number}")
    return 0
