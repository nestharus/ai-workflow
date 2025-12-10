"""Fetch and process PR review threads.

Fetches unresolved threads from a PR, filters by line numbers, auto-resolves
threads with thumbs-up reactions, and saves remaining threads to JSON files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.pr import github_dao

from .util import (
    _format_thread_for_agent,
    _has_thumbs_up_from_author,
    _thread_has_line_number,
)


def fetch_threads_command(pr_number: int, output_dir: Path) -> int:
    """Fetch threads, filter, format, resolve thumbs-up threads, and save to files.

    Args:
        pr_number: PR number to fetch threads from.
        output_dir: Directory to write thread files to.

    Returns:
        Exit code (0 for success).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Clean existing thread files
    for existing in output_dir.glob("thread_*.json"):
        existing.unlink()

    threads = github_dao.fetch_unresolved_threads(pr_number)
    print(f"Fetched {len(threads)} unresolved threads from PR #{pr_number}")

    # Filter to only threads with line numbers
    threads_with_lines = [t for t in threads if _thread_has_line_number(t)]
    print(f"Filtered to {len(threads_with_lines)} threads with line numbers")

    # Separate threads with thumbs-up (auto-resolve) from those needing attention
    threads_to_resolve: list[dict[str, Any]] = []
    threads_to_process: list[dict[str, Any]] = []

    for thread in threads_with_lines:
        if _has_thumbs_up_from_author(thread):
            threads_to_resolve.append(thread)
        else:
            threads_to_process.append(thread)

    # Auto-resolve thumbs-up threads
    print(f"Auto-resolving {len(threads_to_resolve)} threads with thumbs-up reactions")
    for thread in threads_to_resolve:
        thread_id = thread.get("id")
        if thread_id:
            success = github_dao.resolve_thread(thread_id)
            status = "resolved" if success else "failed"
            path = thread.get("path", "unknown")
            line = thread.get("line", "?")
            print(f"  {status}: {path}:{line}")

    # Write remaining threads to files
    print(f"Writing {len(threads_to_process)} threads to {output_dir}")
    files_created: list[Path] = []
    for index, thread in enumerate(threads_to_process):
        formatted = _format_thread_for_agent(thread, index)
        file_path = output_dir / f"thread_{index}.json"
        file_path.write_text(json.dumps(formatted, indent=2), encoding="utf-8")
        files_created.append(file_path)
        print(f"  Created: {file_path}")

    print("\nSummary:")
    print(f"  Total unresolved threads: {len(threads)}")
    print(f"  Threads with line numbers: {len(threads_with_lines)}")
    print(f"  Auto-resolved (thumbs-up): {len(threads_to_resolve)}")
    print(f"  Files created for review: {len(files_created)}")

    return 0
