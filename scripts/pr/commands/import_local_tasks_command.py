"""Import local task body files into JSON task files."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _extract_file_paths(content: str) -> list[str]:
    """Extract file paths from task content.

    Supports two formats:
    1. Backtick format: `file:path/to/file.md` (can appear multiple times)
    2. Referenced Files section:
       ### Referenced Files
       - path/to/file.md
       - path/to/other.md

    Returns list of file paths found (empty if none).
    """
    paths: list[str] = []

    # Try backtick format (find all occurrences)
    for match in re.finditer(r"`file:([^`]+)`", content):
        path = match.group(1).strip().replace("\\", "/")
        if path and path not in paths:
            paths.append(path)

    # Try Referenced Files section
    # Match "### Referenced Files" or "## Referenced Files" followed by list items
    ref_match = re.search(
        r"#{2,3}\s*Referenced Files\s*\n((?:\s*-\s*.+\n?)+)",
        content,
        re.IGNORECASE,
    )
    if ref_match:
        list_content = ref_match.group(1)
        for item_match in re.finditer(r"-\s*(.+)", list_content):
            path = item_match.group(1).strip().replace("\\", "/")
            if path and path not in paths:
                paths.append(path)

    return paths


def import_local_tasks_command(
    output_dir: Path,
    body_files: list[Path] | None = None,
    from_file: Path | None = None,
) -> int:
    """Import local task body files into JSON task files.

    Args:
        output_dir: Directory to write the local task JSON files to.
        body_files: List of paths to body files (plain text with task content).
        from_file: Single file containing multiple tasks separated by ---.

    Returns:
        Exit code (0 for success).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    tasks: list[tuple[int, str]] = []

    # If --from-file is provided, read and split by ---
    if from_file is not None:
        if not from_file.is_file():
            print(f"Error: Tasks file not found: {from_file}", file=sys.stderr)
            return 1

        content = from_file.read_text(encoding="utf-8")
        # Split by --- on its own line
        parts = content.split("\n---\n")
        tasks = [(i, part.strip()) for i, part in enumerate(parts) if part.strip()]

    # Otherwise, read from body files
    elif body_files:
        for index, body_file in enumerate(body_files):
            if not body_file.is_file():
                print(f"Warning: Body file not found: {body_file}", file=sys.stderr)
                continue

            body = body_file.read_text(encoding="utf-8").strip()
            tasks.append((index, body))

            # Delete the body file after import
            body_file.unlink()
            print(f"Deleted: {body_file}")

    if not tasks:
        print("No tasks to import")
        return 0

    for index, body in tasks:
        task_data: dict[str, object] = {
            "index": index,
            "origin": "LOCAL",
            "content": body,
            "comments": [
                {
                    "body": body,
                    "author": "local",
                }
            ],
        }
        # Extract file paths from content if present
        file_paths = _extract_file_paths(body)
        if file_paths:
            task_data["paths"] = file_paths

        task_file = output_dir / f"local_{index}.json"
        task_file.write_text(json.dumps(task_data, indent=2), encoding="utf-8")
        print(f"Created: {task_file}")

    print(f"\nImported {len(tasks)} local task(s)")
    return 0
