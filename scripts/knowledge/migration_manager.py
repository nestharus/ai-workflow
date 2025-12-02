"""Migration manager for orchestrating YAML documentation migration tasks.

This module provides CLI commands for managing migration workflows:
- `start-migration`: Store original files with timestamps and create task records
- `validate-migration`: Rerun comparisons, check for unresolved differences, and
  mark tasks as 'completed' (validated successfully) or 'failed'

Usage:
    uv run knowledge.start-migration --original-file docs/development/original.api-patterns.yml
    uv run knowledge.validate-migration --task-id <uuid>

The migration workflow:
1. start-migration copies the original file to .knowledge/originals/ with timestamp
2. Creates a task record in .knowledge/migrations/tasks.csv with status='pending'
3. User performs migration work on the target documentation
4. validate-migration runs comparison, checks for unresolved differences
5. Updates task status to 'completed' (validated) or 'failed' based on results

The validate-migration command passes the original file reference from tasks.csv
to the comparison command via the --original-files parameter. This enables
comparison of timestamped originals stored in .knowledge/originals/ against
current split files in the target directory.

Task statuses:
- pending: Task created, migration work not yet started
- in_progress: Validation is currently running
- completed: Migration validated successfully with no unresolved differences
- failed: Validation found unresolved differences requiring attention
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import uuid
from pathlib import Path
from shutil import copy2
from typing import TYPE_CHECKING, TypedDict

import duckdb

from scripts.dev.utils import REPO_ROOT, utc_timestamp

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

    Uses DuckDB to create an empty CSV with proper headers.

    Args:
        csv_path: Path to the tasks.csv file.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if not csv_path.exists():
        cols_select = ", ".join(f"'' AS {col}" for col in CSV_COLUMNS)
        query = f"COPY (SELECT * FROM (SELECT {cols_select}) WHERE 1=0) "
        query += f"TO '{csv_path}' (HEADER, DELIMITER ',')"
        duckdb.execute(query)


def append_task(csv_path: Path, task: MigrationTask) -> None:
    """Append a task record to the tasks CSV.

    Uses DuckDB to read existing data, add the new task, and write back.

    Args:
        csv_path: Path to the tasks.csv file.
        task: Task record to append.
    """
    ensure_csv_exists(csv_path)
    conn = duckdb.connect()
    try:
        conn.execute(f"""
            CREATE TABLE tasks AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """)
        placeholders = ", ".join("?" for _ in CSV_COLUMNS)
        values = [task[col] for col in CSV_COLUMNS]  # type: ignore[literal-required]
        conn.execute(f"INSERT INTO tasks VALUES ({placeholders})", values)
        conn.execute(f"COPY tasks TO '{csv_path}' (HEADER, DELIMITER ',')")
    finally:
        conn.close()


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

    Uses DuckDB to read, update, and write the CSV file.

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

    conn = duckdb.connect()
    try:
        conn.execute(f"""
            CREATE TABLE tasks AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """)

        result = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE task_id = ?",
            [task_id],
        ).fetchone()

        if result is None or result[0] == 0:
            return False

        if validated_at is not None:
            conn.execute(
                "UPDATE tasks SET status = ?, validated_at = ? WHERE task_id = ?",
                [new_status, validated_at, task_id],
            )
        else:
            conn.execute(
                "UPDATE tasks SET status = ? WHERE task_id = ?",
                [new_status, task_id],
            )

        conn.execute(f"COPY tasks TO '{csv_path}' (HEADER, DELIMITER ',')")
        return True
    finally:
        conn.close()


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

    Joins comparison rows with resolutions on (id, source_file, split_file) columns
    and counts rows where no matching resolution exists.

    Args:
        knowledge_path: Path to the .knowledge directory.
        pattern_name: Pattern name to filter by.

    Returns:
        Number of unresolved comparison differences.
    """
    comparisons_dir = knowledge_path / "comparisons"
    resolutions_path = knowledge_path / "resolutions" / "resolved.csv"

    if not comparisons_dir.exists():
        return 0

    comparison_files = list(comparisons_dir.glob(f"*{pattern_name}*.csv"))
    if not comparison_files:
        return 0

    total_unresolved = 0

    for comp_file in comparison_files:
        if resolutions_path.exists():
            query = """
                SELECT COUNT(*)
                FROM read_csv_auto(?, ALL_VARCHAR=TRUE) c
                LEFT JOIN read_csv_auto(?, ALL_VARCHAR=TRUE) r
                ON c.id = r.id
                AND c.source_file = r.source_file
                AND c.split_file = r.split_file
                WHERE r.id IS NULL
            """
            result = duckdb.execute(query, [str(comp_file), str(resolutions_path)]).fetchone()
        else:
            query = "SELECT COUNT(*) FROM read_csv_auto(?, ALL_VARCHAR=TRUE)"
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


def get_original_file_path(knowledge_path: Path, original_file_ref: str) -> Path:
    """Construct the full path to a timestamped original file from its reference.

    Args:
        knowledge_path: Path to the .knowledge directory.
        original_file_ref: Relative reference to the original file stored in tasks.csv
            (e.g., "originals/20251201T134735Z-api-patterns.yml").

    Returns:
        Resolved Path object to the timestamped original file.
    """
    return (knowledge_path / original_file_ref).resolve()


def validate_migration(
    task_id: str,
    knowledge_path: Path,
    base_comparison_path: Path,
) -> int:
    """Validate and complete a migration task.

    Retrieves the original file reference from the task record and passes it
    to the comparison command via --original-files parameter, enabling comparison
    of timestamped originals from .knowledge/originals/ against current split files.

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

    original_file_ref = task["original_file_ref"]
    original_file_path = get_original_file_path(knowledge_path, original_file_ref)

    if not original_file_path.exists():
        print(
            f"Error: Original file not found: {original_file_path}",
            file=sys.stderr,
        )
        update_task_status(tasks_csv, task_id, "failed")
        return 1

    update_task_status(tasks_csv, task_id, "in_progress")

    print(f"Validating migration for pattern: {task['pattern_name']}")
    print(f"Using original file: {original_file_path}")
    print("Running comparison...")

    try:
        result = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "uv",
                "run",
                "compare-yml-docs",
                "--path",
                str(base_comparison_path),
                "--original-files",
                str(original_file_path),
            ],
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
        print("Use 'uv run knowledge.query-comparisons' to see details")
        print("Use 'uv run knowledge.mark-resolved' to resolve intentional differences")
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
        help="Base knowledge directory, relative to REPO_ROOT or absolute (default: .knowledge).",
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
        help="Base knowledge directory, relative to REPO_ROOT or absolute (default: .knowledge).",
    )
    parser.add_argument(
        "--comparison-path",
        type=Path,
        default=Path("docs/development"),
        help="Base path for comparison, relative to REPO_ROOT or absolute "
        "(default: docs/development).",
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

        if args.knowledge_path.is_absolute():
            knowledge_path = args.knowledge_path.resolve()
        else:
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

        if args.knowledge_path.is_absolute():
            knowledge_path = args.knowledge_path.resolve()
        else:
            knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

        if args.comparison_path.is_absolute():
            comparison_path = args.comparison_path.resolve()
        else:
            comparison_path = (REPO_ROOT / args.comparison_path).resolve()

        return validate_migration(args.task_id, knowledge_path, comparison_path)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main_start())
