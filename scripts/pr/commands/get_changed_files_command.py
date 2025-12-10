"""Get list of files changed in a PR."""

from __future__ import annotations

import json
import sys

from scripts.pr import github_dao


def get_changed_files_command(pr_number: int) -> int:
    """Get list of files changed in a PR.

    Args:
        pr_number: PR number.

    Returns:
        Exit code (0 for success).
    """
    try:
        files = github_dao.get_pr_changed_files(pr_number)
        print(json.dumps(files, indent=2))
        return 0
    except github_dao.GraphQLError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
