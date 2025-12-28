"""Aggregate task JSON files by file.

Reads task JSON files from a directory and groups them by the target file path,
producing a summary suitable for parallel processing by file.

Supports multiple task sources:
- coderabbit_*.json (from parse-coderabbit command)
- thread_*.json (from fetch-threads command)
- local_*.json (from import-local-tasks command)
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

# Task file patterns to search for
TASK_PATTERNS = ["coderabbit_*.json", "thread_*.json", "local_*.json"]

# Key for tasks without a file path (e.g., local tasks)
GLOBAL_TASKS_KEY = "__global__"


def aggregate_tasks_command(input_dir: Path, *, files_only: bool = False) -> int:
    """Aggregate task JSON files by target file path.

    Reads task JSON files matching known patterns from the input directory and
    groups them by the 'path' field, producing a JSON output mapping files to
    their tasks. Tasks without a 'path' field are grouped under '__global__'.

    Args:
        input_dir: Directory containing task JSON files.
        files_only: If True, output only the file paths (one per line) instead of JSON.

    Returns:
        Exit code (0 for success).
    """
    if not input_dir.is_dir():
        print(f"Error: Input directory not found: {input_dir}", file=sys.stderr)
        return 1

    # Find all task files matching any pattern
    task_files: list[Path] = []
    for pattern in TASK_PATTERNS:
        task_files.extend(input_dir.glob(pattern))

    # Sort by filename for consistent ordering
    task_files = sorted(task_files, key=lambda p: p.name)

    if not task_files:
        print(f"Error: No task files found in {input_dir}", file=sys.stderr)
        print(f"  Searched for: {', '.join(TASK_PATTERNS)}", file=sys.stderr)
        return 1

    # Group tasks by file path
    tasks_by_file: dict[str, list[str]] = defaultdict(list)

    for task_file in task_files:
        try:
            content = task_file.read_text(encoding="utf-8")
        except OSError as e:
            print(f"Warning: Failed to read file {task_file}: {e}", file=sys.stderr)
            continue

        try:
            task_data = json.loads(content)
        except json.JSONDecodeError as e:
            print(f"Warning: Invalid JSON in file {task_file}: {e}", file=sys.stderr)
            continue

        # Validate that parsed JSON is an object (dict)
        if not isinstance(task_data, dict):
            print(
                f"Warning: Expected JSON object in {task_file.name}, "
                f"got {type(task_data).__name__}; treating as global task",
                file=sys.stderr,
            )
            tasks_by_file[GLOBAL_TASKS_KEY].append(task_file.name)
            continue

        # Multiple distinct task files may legitimately reference the same target path
        # (e.g., separate CodeRabbit suggestions for the same file). We intentionally
        # append all filenames without deduplication to preserve each task.
        file_path = task_data.get("path")

        # Validate path is a non-empty string before using as dict key
        if isinstance(file_path, str) and file_path.strip():
            tasks_by_file[file_path].append(task_file.name)
        elif file_path is not None:
            # Log warning for unexpected path type/value and treat as global task
            print(
                f"Warning: Invalid 'path' in {task_file.name}: "
                f"expected non-empty string, got {type(file_path).__name__}={file_path!r}; "
                f"treating as global task",
                file=sys.stderr,
            )
            tasks_by_file[GLOBAL_TASKS_KEY].append(task_file.name)
        else:
            # Tasks without a path go to global bucket
            tasks_by_file[GLOBAL_TASKS_KEY].append(task_file.name)

    # Sort each list of task filenames for deterministic output
    for file_path in tasks_by_file:
        tasks_by_file[file_path].sort()

    # Build output structure - exclude __global__ from files list
    files = sorted(k for k in tasks_by_file if k != GLOBAL_TASKS_KEY)
    task_count = sum(len(tasks) for tasks in tasks_by_file.values())

    if files_only:
        # Output just the file paths, one per line (for piping to file-hash)
        for file_path in files:
            print(file_path)
    else:
        # Sort tasks_by_file keys for deterministic output: regular files first (sorted),
        # then __global__ at the end if present
        sorted_tasks_by_file = {
            k: tasks_by_file[k]
            for k in sorted(tasks_by_file.keys(), key=lambda x: (x == GLOBAL_TASKS_KEY, x))
        }
        output = {
            "files": files,
            "tasks_by_file": sorted_tasks_by_file,
            "task_count": task_count,
        }
        print(json.dumps(output, indent=2))

    return 0
