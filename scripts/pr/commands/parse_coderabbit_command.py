"""Parse CodeRabbit review files into task JSON files.

Parses CodeRabbit review output and creates individual task JSON files
compatible with the pr-comment-handler agent.
"""

from __future__ import annotations

import json
import re
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any


def _parse_line_spec(line_text: str) -> tuple[int | None, int | None]:
    """Parse a line specification like 'Line: 1 to 10' or 'Line: 5'.

    Args:
        line_text: The line specification text (e.g., "Line: 1 to 10").

    Returns:
        Tuple of (start_line, end_line). For single lines, both are the same.
        Returns (None, None) if parsing fails.
    """
    # Match "Line: X to Y" pattern
    range_match = re.match(r"Line:\s*(\d+)\s+to\s+(\d+)", line_text, re.IGNORECASE)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        return (start, end)

    # Match "Line: X" pattern (single line)
    single_match = re.match(r"Line:\s*(\d+)", line_text, re.IGNORECASE)
    if single_match:
        line_num = int(single_match.group(1))
        return (line_num, line_num)

    return (None, None)


def _parse_section(section: str, index: int) -> dict[str, Any] | None:
    """Parse a single CodeRabbit review section into a task dictionary.

    Args:
        section: The text content of one review section.
        index: The index number for this task.

    Returns:
        Task dictionary or None if section is invalid/empty.
    """
    lines = section.strip().split("\n")
    if not lines:
        return None

    path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    comment_type: str | None = None
    content: str | None = None

    prompt_started = False
    prompt_lines: list[str] = []

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("File:"):
            path = stripped[5:].strip()
        elif stripped.startswith("Line:"):
            line_start, line_end = _parse_line_spec(stripped)
        elif stripped.startswith("Type:"):
            comment_type = stripped[5:].strip()
        elif stripped.startswith("Prompt for AI Agent:"):
            prompt_started = True
            # Check if there's content on the same line after the prefix
            remainder = stripped[len("Prompt for AI Agent:") :].strip()
            if remainder:
                prompt_lines.append(remainder)
        elif prompt_started:
            prompt_lines.append(line)

    # Clean up the content - remove leading/trailing blank lines
    while prompt_lines and not prompt_lines[0].strip():
        prompt_lines.pop(0)
    while prompt_lines and not prompt_lines[-1].strip():
        prompt_lines.pop()

    content = "\n".join(prompt_lines).strip() if prompt_lines else None

    # Require at least path and content
    if not path or not content:
        return None

    return {
        "index": index,
        "origin": "CODERABBIT",
        "path": path,
        "line": line_start,
        "start_line": line_start,
        "end_line": line_end,
        "type": comment_type,
        "content": content,
        "comments": [
            {
                "body": content,
                "author": "coderabbit",
            }
        ],
    }


def parse_coderabbit_command(review_file: Path, output_dir: Path) -> int:
    """Parse a CodeRabbit review file and create task JSON files.

    Args:
        review_file: Path to the CodeRabbit review file.
        output_dir: Directory to write task JSON files to.

    Returns:
        Exit code (0 for success).
    """
    if not review_file.is_file():
        print(f"Error: Review file not found: {review_file}")
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    # Clean existing coderabbit task files
    for existing in output_dir.glob("coderabbit_*.json"):
        existing.unlink()

    content = review_file.read_text(encoding="utf-8")

    # Split by separator lines
    separator = "=" * 76  # 76 equals signs in the separator
    sections = re.split(rf"^{separator}$", content, flags=re.MULTILINE)

    # Parse each section
    tasks: list[dict[str, Any]] = []
    for section in sections:
        if not section.strip():
            continue
        # Skip header sections (like "Starting CodeRabbit review...")
        if "Prompt for AI Agent:" not in section:
            continue

        task = _parse_section(section, len(tasks))
        if task:
            tasks.append(task)

    print(f"Parsed {len(tasks)} review comments from {review_file.name}")

    # Write task files with error handling and atomic writes
    files_created: list[Path] = []
    for task in tasks:
        file_path = output_dir / f"coderabbit_{task['index']}.json"
        try:
            # Use atomic write: write to temp file then rename
            content = json.dumps(task, indent=2)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=output_dir,
                suffix=".tmp",
                delete=False,
            ) as tmp_file:
                tmp_file.write(content)
                tmp_path = Path(tmp_file.name)
            # Atomic rename
            tmp_path.rename(file_path)
            files_created.append(file_path)
            print(f"  Created: {file_path}")
        except (OSError, PermissionError) as e:
            print(f"Error: Failed to write task file {file_path}: {e}")
            # Cleanup already created files
            for created_file in files_created:
                with suppress(OSError):
                    created_file.unlink()
            # Also try to clean up temp file if it exists
            if "tmp_path" in locals() and tmp_path.exists():
                with suppress(OSError):
                    tmp_path.unlink()
            return 1

    print("\nSummary:")
    print(f"  Review file: {review_file}")
    print(f"  Tasks created: {len(files_created)}")

    return 0
