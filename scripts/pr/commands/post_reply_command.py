"""Post a reply to a PR comment."""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.pr import github_dao

from .util import _read_thread_file


def post_reply_command(pr_number: int, thread_file: Path, body: str) -> int:
    """Post a reply to a PR comment.

    Args:
        pr_number: PR number.
        thread_file: Path to the thread JSON file containing comment info.
        body: Reply body text.

    Returns:
        Exit code (0 for success).
    """
    if not thread_file.is_file():
        print(f"Error: Thread file not found: {thread_file}", file=sys.stderr)
        return 1

    thread_data = _read_thread_file(thread_file)
    comments = thread_data.get("comments", [])
    if not comments:
        print(f"Error: No comments in thread file: {thread_file}", file=sys.stderr)
        return 1

    # Reply to the last comment in the thread
    comment_id = comments[-1].get("database_id")
    if not comment_id:
        print(f"Error: No database_id in comment: {thread_file}", file=sys.stderr)
        return 1

    github_dao.post_reply_to_comment(pr_number, comment_id, body)
    print(f"Posted reply to comment {comment_id}")
    return 0
