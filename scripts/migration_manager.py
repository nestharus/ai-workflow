"""Migration manager for orchestrating YAML documentation migration tasks.

This module provides CLI commands for managing migration workflows:
- `start-migration`: Store original files with timestamps and create task records
- `validate-migration`: Rerun comparisons and mark tasks as completed or failed

Usage:
    uv run start-migration --original-file docs/development/original.api-patterns.yml
    uv run validate-migration --task-id <uuid>

The migration workflow:
1. start-migration copies the original file to .knowledge/originals/ with timestamp
2. Creates a task record in .knowledge/migrations/tasks.csv with status='pending'
3. User performs migration work on the target documentation
4. validate-migration runs comparison, checks for unresolved differences
5. Updates task status to 'completed' or 'failed' based on validation results
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import uuid
from pathlib import Path
from shutil import copy2
from typing import TYPE_CHECKING, TypedDict

import duckdb

from scripts.utils import REPO_ROOT, utc_timestamp

if TYPE_CHECKING:
    from collections.abc import Sequence

CSV_COLUMNS = [
    "task_id",
    "original_file_ref",
    "pattern_name",
    "status",
    "created_at",
    "validated_at",
]
VALID_STATUSES = ["pending", "in_progress", "completed", "failed"]


class MigrationTask(TypedDict):
    """Schema for migration task records."""

    task_id: str
    original_file_ref: str
    pattern_name: str
    status: str
    created_at: str
    validated_at: str


def ensure_csv_exists(csv_path: Path) -> None:
    """Create tasks.csv with header if it does not exist.

    Args:
        csv_path: Path to the tasks.csv file.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if not csv_path.exists():
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()


def append_task(csv_path: Path, task: MigrationTask) -> None:
    """Append a task record to the tasks CSV.

    Args:
        csv_path: Path to the tasks.csv file.
        task: Task record to append.
    """
    ensure_csv_exists(csv_path)
    with csv_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writerow(task)


def get_task_by_id(csv_path: Path, task_id: str) -> MigrationTask | None:
    """Query tasks.csv for a task by ID using DuckDB.

    Args:
        csv_path: Path to the tasks.csv file.
        task_id: UUID of the task to find.

    Returns:
        Task record if found, None otherwise.
    """
    if not csv_path.exists():
        return None

    query = "SELECT * FROM read_csv_auto(?) WHERE task_id = ?"
    result = duckdb.execute(query, [str(csv_path), task_id]).fetchone()

    if result is None:
        return None

    return MigrationTask(
        task_id=result[0],
        original_file_ref=result[1],
        pattern_name=result[2],
        status=result[3],
        created_at=result[4],
        validated_at=result[5] if result[5] else "",
    )


def update_task_status(
    csv_path: Path,
    task_id: str,
    new_status: str,
    validated_at: str | None = None,
) -> bool:
    """Update the status of a task in tasks.csv.

    Args:
        csv_path: Path to the tasks.csv file.
        task_id: UUID of the task to update.
        new_status: New status value.
        validated_at: Optional validation timestamp.

    Returns:
        True if task was found and updated, False otherwise.
    """
    if not csv_path.exists():
        return False

    tasks: list[MigrationTask] = []
    found = False

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["task_id"] == task_id:
                row["status"] = new_status
                if validated_at is not None:
                    row["validated_at"] = validated_at
                found = True
            tasks.append(
                MigrationTask(
                    task_id=row["task_id"],
                    original_file_ref=row["original_file_ref"],
                    pattern_name=row["pattern_name"],
                    status=row["status"],
                    created_at=row["created_at"],
                    validated_at=row["validated_at"],
                )
            )

    if not found:
        return False

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(tasks)

    return True


def extract_pattern_from_path(file_path: Path) -> str:
    """Extract pattern name from file path.

    Handles files like 'original.api-patterns.yml' -> 'api-patterns'
    or 'api-patterns.yml' -> 'api-patterns'.

    Args:
        file_path: Path to the file.

    Returns:
        Extracted pattern name.
    """
    stem = file_path.stem
    if stem.startswith("original."):
        stem = stem[9:]
    if stem.endswith(".yml") or stem.endswith(".yaml"):
        stem = Path(stem).stem
    return stem


def save_original_with_timestamp(
    source_path: Path,
    knowledge_path: Path,
    pattern_name: str,
) -> str:
    """Copy file to .knowledge/originals/ with timestamp prefix.

    Args:
        source_path: Path to the source file.
        knowledge_path: Path to the .knowledge directory.
        pattern_name: Extracted pattern name for the file.

    Returns:
        Relative path to the saved file from knowledge_path.
    """
    originals_dir = knowledge_path / "originals"
    originals_dir.mkdir(parents=True, exist_ok=True)

    timestamp = utc_timestamp()
    dest_name = f"{timestamp}-{pattern_name}.yml"
    dest_path = originals_dir / dest_name

    copy2(source_path, dest_path)

    return f"originals/{dest_name}"


def count_unresolved_differences(
    knowledge_path: Path,
    pattern_name: str,
) -> int:
    """Count unresolved differences for a pattern using DuckDB.

    Args:
        knowledge_path: Path to the .knowledge directory.
        pattern_name: Pattern name to filter by.

    Returns:
        Number of unresolved comparison differences.
    """
    comparisons_dir = knowledge_path / "comparisons"
    resolutions_path = knowledge_path / "resolutions" / "resolutions.csv"

    if not comparisons_dir.exists():
        return 0

    comparison_files = list(comparisons_dir.glob(f"*{pattern_name}*.csv"))
    if not comparison_files:
        return 0

    total_unresolved = 0

    for comp_file in comparison_files:
        if resolutions_path.exists():
            query = """
                SELECT COUNT(*) FROM read_csv_auto(?) c
                LEFT JOIN read_csv_auto(?) r
                ON c.file_hash = r.file_hash AND c.section_key = r.section_key
                WHERE r.file_hash IS NULL
            """
            result = duckdb.execute(query, [str(comp_file), str(resolutions_path)]).fetchone()
        else:
            query = "SELECT COUNT(*) FROM read_csv_auto(?)"
            result = duckdb.execute(query, [str(comp_file)]).fetchone()

        if result:
            total_unresolved += result[0]

    return total_unresolved


def start_migration(original_file: Path, knowledge_path: Path) -> int:
    """Start a new migration task.

    Args:
        original_file: Path to the original file to migrate.
        knowledge_path: Path to the .knowledge directory.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    if not original_file.exists():
        print(f"Error: Original file not found: {original_file}", file=sys.stderr)
        return 1

    if not original_file.is_file():
        print(f"Error: Path is not a file: {original_file}", file=sys.stderr)
        return 1

    try:
        original_file.resolve().relative_to(REPO_ROOT)
    except ValueError:
        print(f"Error: File must be within repository: {original_file}", file=sys.stderr)
        return 1

    pattern_name = extract_pattern_from_path(original_file)
    original_file_ref = save_original_with_timestamp(original_file, knowledge_path, pattern_name)

    task_id = str(uuid.uuid4())
    task = MigrationTask(
        task_id=task_id,
        original_file_ref=original_file_ref,
        pattern_name=pattern_name,
        status="pending",
        created_at=utc_timestamp(),
        validated_at="",
    )

    tasks_csv = knowledge_path / "migrations" / "tasks.csv"
    append_task(tasks_csv, task)

    print(f"Migration task created: {task_id}")
    print(f"Original file saved to: {knowledge_path / original_file_ref}")
    print(f"Pattern: {pattern_name}")

    return 0


def validate_migration(
    task_id: str,
    knowledge_path: Path,
    base_comparison_path: Path,
) -> int:
    """Validate and complete a migration task.

    Args:
        task_id: UUID of the task to validate.
        knowledge_path: Path to the .knowledge directory.
        base_comparison_path: Base path for comparison command.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    tasks_csv = knowledge_path / "migrations" / "tasks.csv"
    task = get_task_by_id(tasks_csv, task_id)

    if task is None:
        print(f"Error: Task not found: {task_id}", file=sys.stderr)
        return 1

    if task["status"] == "completed":
        print(f"Task {task_id} is already completed (validated at {task['validated_at']})")
        return 0

    update_task_status(tasks_csv, task_id, "in_progress")

    print(f"Validating migration for pattern: {task['pattern_name']}")
    print("Running comparison...")

    try:
        result = subprocess.run(  # noqa: S603
            ["uv", "run", "compare-yml-docs", "--path", str(base_comparison_path)],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO_ROOT,
        )
        if result.returncode != 0:
            print(f"Comparison command output:\n{result.stdout}", file=sys.stderr)
            if result.stderr:
                print(f"Comparison errors:\n{result.stderr}", file=sys.stderr)
    except FileNotFoundError:
        print("Error: Could not run compare-yml-docs command", file=sys.stderr)
        update_task_status(tasks_csv, task_id, "failed")
        return 1

    unresolved_count = count_unresolved_differences(knowledge_path, task["pattern_name"])

    if unresolved_count > 0:
        update_task_status(tasks_csv, task_id, "failed")
        print(f"Validation failed: {unresolved_count} unresolved difference(s) found")
        print("Use 'uv run query-comparisons' to see details")
        print("Use 'uv run mark-resolved' to resolve intentional differences")
        return 1

    update_task_status(tasks_csv, task_id, "completed", utc_timestamp())
    print(f"Migration validated successfully for task {task_id}")

    return 0


def parse_start_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse arguments for start-migration command.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Start a new migration task by storing the original file.",
    )
    parser.add_argument(
        "--original-file",
        type=Path,
        required=True,
        help="Path to the original file to migrate.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        help="Path to the .knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def parse_validate_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse arguments for validate-migration command.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Validate and complete a migration task.",
    )
    parser.add_argument(
        "--task-id",
        type=str,
        required=True,
        help="UUID of the migration task to validate.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        help="Path to the .knowledge directory (default: .knowledge).",
    )
    parser.add_argument(
        "--comparison-path",
        type=Path,
        default=Path("docs/development"),
        help="Base path for comparison command (default: docs/development).",
    )
    return parser.parse_args(argv)


def main_start() -> int:
    """Entry point for start-migration command.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    try:
        args = parse_start_args()
        original_file = (REPO_ROOT / args.original_file).resolve()
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()
        return start_migration(original_file, knowledge_path)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def main_validate() -> int:
    """Entry point for validate-migration command.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    try:
        args = parse_validate_args()
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()
        comparison_path = (REPO_ROOT / args.comparison_path).resolve()
        return validate_migration(args.task_id, knowledge_path, comparison_path)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main_start())
