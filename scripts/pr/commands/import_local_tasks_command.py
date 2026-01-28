"""Import local task body files into JSON task files."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _extract_file_path(content: str) -> str | None:
    """Extract file path from task content.

    Looks for patterns like:
    - "Relevant files: path/to/file.md"
    - "Relevant files: path1.md and path2.md" (returns first)
    - "file: path/to/file.md"

    Returns the first file path found, or None.
    """
    # Pattern for "Relevant files:" section
    relevant_match = re.search(r"Relevant files?:\s*(.+?)(?:\n|$)", content, re.IGNORECASE)
    if relevant_match:
        files_text = relevant_match.group(1).strip()
        # Split by " and " or commas to get individual files
        # Take the first file path
        parts = re.split(r"\s+and\s+|,\s*", files_text)
        for part in parts:
            part = re.sub(r"^\s*([-+*]|\d+\.)\s*", "", part).strip()
            # Check if it looks like a file path (has extension or path separator)
            if part and ("." in part or "/" in part or "\\" in part):
                # Normalize Windows paths to Unix
                return part.replace("\\", "/")

    # Pattern for "file: path" or "in file.ext"
    file_match = re.search(
        r"(?:file:\s*|in\s+(?:the\s+)?file\s*[`'\"]?)([^\s`'\"]+\.[a-zA-Z0-9]+)",
        content,
        re.IGNORECASE,
    )
    if file_match:
        return file_match.group(1).replace("\\", "/")

    return None


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
        # Extract file path from content if present
        file_path = _extract_file_path(body)
        if file_path:
            task_data["path"] = file_path

        task_file = output_dir / f"local_{index}.json"
        task_file.write_text(json.dumps(task_data, indent=2), encoding="utf-8")
        print(f"Created: {task_file}")

    print(f"\nImported {len(tasks)} local task(s)")
    return 0
