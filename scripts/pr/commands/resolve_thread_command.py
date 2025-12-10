"""Command to resolve a GitHub review thread."""

import sys
from pathlib import Path

from scripts.pr import github_dao
from scripts.pr.commands.util import _read_thread_file


def resolve_thread_command(thread_file: Path) -> int:
    """Resolve a review thread by reading the thread file.

    Args:
        thread_file: Path to the thread JSON file containing thread_id.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    if not thread_file.is_file():
        print(f"Error: Thread file not found: {thread_file}", file=sys.stderr)
        return 1

    thread_data = _read_thread_file(thread_file)
    thread_id = thread_data.get("thread_id")
    if not thread_id:
        print(f"Error: No thread_id in file: {thread_file}", file=sys.stderr)
        return 1

    success = github_dao.resolve_thread(thread_id)
    if success:
        print(f"Resolved thread: {thread_id}")
        return 0
    print(f"Failed to resolve thread: {thread_id}", file=sys.stderr)
    return 1
