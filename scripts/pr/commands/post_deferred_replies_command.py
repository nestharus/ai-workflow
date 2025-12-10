"""Post deferred replies from thread files to a PR."""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.pr import github_dao

from .util import _read_thread_file


def post_deferred_replies_command(pr_number: int, threads_dir: Path) -> int:
    """Post deferred replies from thread files to a PR.

    Args:
        pr_number: PR number to post replies on.
        threads_dir: Directory containing thread JSON files with deferred replies.

    Returns:
        Exit code (0 for success).
    """
    if not threads_dir.is_dir():
        print(f"Threads directory not found: {threads_dir}", file=sys.stderr)
        return 1

    thread_files = sorted(threads_dir.glob("thread_*.json"))
    replies_posted = 0
    for thread_file in thread_files:
        thread_data = _read_thread_file(thread_file)
        deferred_reply = thread_data.get("deferred_reply")
        if deferred_reply:
            comments = thread_data.get("comments", [])
            if not comments:
                print(
                    f"Warning: No comments in thread file: {thread_file}",
                    file=sys.stderr,
                )
                continue

            comment_id = comments[-1].get("database_id")
            if not comment_id:
                print(
                    f"Warning: No database_id in comment: {thread_file}",
                    file=sys.stderr,
                )
                continue

            github_dao.post_reply_to_comment(pr_number, comment_id, deferred_reply)
            replies_posted += 1
            path = thread_data.get("path", "unknown")
            line = thread_data.get("line", "?")
            print(f"Posted deferred reply to {path}:{line}")

    print(f"Posted {replies_posted} deferred reply(ies)")
    return 0
