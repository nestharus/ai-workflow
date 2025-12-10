"""Command to request a CodeRabbit review on a pull request."""

from __future__ import annotations

from scripts.pr import github_dao


def request_review_command(pr_number: int) -> int:
    """Request a CodeRabbit review on a PR.

    Args:
        pr_number: PR number to request review on.

    Returns:
        Exit code (0 for success).
    """
    github_dao.post_pr_comment(pr_number, "@coderabbitai review")
    print(f"Requested CodeRabbit review on PR #{pr_number}")
    return 0
