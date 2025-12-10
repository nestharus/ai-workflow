"""Import local task body files into JSON task files."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def import_local_tasks_command(output_dir: Path, body_files: list[Path]) -> int:
    """Import local task body files into JSON task files.

    Args:
        output_dir: Directory to write the local task JSON files to.
        body_files: List of paths to body files (plain text with task content).

    Returns:
        Exit code (0 for success).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    for index, body_file in enumerate(body_files):
        if not body_file.is_file():
            print(f"Warning: Body file not found: {body_file}", file=sys.stderr)
            continue

        body = body_file.read_text(encoding="utf-8").strip()

        task_data = {
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
        task_file = output_dir / f"local_{index}.json"
        task_file.write_text(json.dumps(task_data, indent=2), encoding="utf-8")
        print(f"Created: {task_file}")

        # Delete the body file after import
        body_file.unlink()
        print(f"Deleted: {body_file}")

    print(f"\nImported {len(body_files)} local task(s)")
    return 0
