"""Deferred comment command implementation.

Handles storing deferred replies in thread files for later posting.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .util import _read_thread_file


def deferred_comment_command(thread_file: Path, body: str) -> int:
    """Store a deferred reply in a thread file for later posting.

    Args:
        thread_file: Path to the thread JSON file.
        body: Reply body text to store.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    if not thread_file.is_file():
        print(f"Error: Thread file not found: {thread_file}", file=sys.stderr)
        return 1

    thread_data = _read_thread_file(thread_file)
    thread_data["deferred_reply"] = body
    thread_file.write_text(json.dumps(thread_data, indent=2), encoding="utf-8")
    print(f"Stored deferred reply in: {thread_file}")
    return 0
