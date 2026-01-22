"""Parse review.txt format into task JSON files."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _parse_review_block(block: str) -> dict[str, str | int | None] | None:
    """Parse a single review block into task data.

    Args:
        block: A single review block (text between --- separators).

    Returns:
        Task data dict with path, line, content, or None if not actionable.
    """
    lines = block.strip().split("\n")
    if not lines:
        return None

    # Check status - only process [OPEN] blocks
    first_line = lines[0].strip()
    if first_line == "[CLEAN]":
        return None
    if first_line == "[RESOLVED]":
        return None
    if first_line != "[OPEN]":
        # If no status marker, treat as raw content (legacy format)
        pass

    # Parse fields
    file_path: str | None = None
    line_num: int | None = None
    content_parts: list[str] = []

    for line in lines:
        line = line.strip()

        # Skip status markers
        if line in ("[OPEN]", "[RESOLVED]", "[CLEAN]"):
            continue

        # Parse known fields
        if line.startswith("File:"):
            file_path = line[5:].strip()
        elif line.startswith("Line:"):
            try:
                line_num = int(line[5:].strip())
            except ValueError:
                pass
        elif line.startswith("Issue:"):
            content_parts.append(line)
        elif line.startswith("Action:"):
            content_parts.append(line)
        elif line.startswith("Fix:"):
            content_parts.append(line)
        elif line.startswith("Expected:"):
            content_parts.append(line)
        elif line.startswith("Current:"):
            content_parts.append(line)
        elif line:
            # Include other non-empty lines in content
            content_parts.append(line)

    if not file_path:
        return None

    content = "\n".join(content_parts)
    if not content:
        return None

    return {
        "path": file_path,
        "line": line_num,
        "content": content,
    }


def parse_review_tasks_command(
    review_file: Path,
    output_dir: Path,
) -> int:
    """Parse review.txt format into task JSON files.

    Reads a review file in the implementation-reviewer format and creates
    individual task JSON files for each [OPEN] issue.

    Args:
        review_file: Path to review.txt file.
        output_dir: Directory to write task JSON files.

    Returns:
        Exit code (0 for success).
    """
    if not review_file.is_file():
        print(f"Error: Review file not found: {review_file}", file=sys.stderr)
        return 1

    content = review_file.read_text(encoding="utf-8")

    # Check if this is a clean review
    if content.strip().startswith("[CLEAN]"):
        print("Review is clean - no tasks to create")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)

    # Split by --- separator
    blocks = re.split(r"\n---\n", content)

    tasks_created = 0
    for index, block in enumerate(blocks):
        task_data = _parse_review_block(block)
        if task_data is None:
            continue

        # Add metadata
        task_data["index"] = index
        task_data["origin"] = "review"

        # Write task file
        task_file = output_dir / f"review_{index:03d}.json"
        task_file.write_text(json.dumps(task_data, indent=2), encoding="utf-8")
        print(f"Created: {task_file}")
        tasks_created += 1

    if tasks_created == 0:
        print("No actionable tasks found in review")
    else:
        print(f"\nCreated {tasks_created} task(s) from review")

    return 0
