"""Track information movements between files during migrations.

This module provides utilities for recording information movements from source
files to target files during documentation migrations. It tracks the source/target
locations, reasons for the move, coverage descriptions, and before/after sentence
context for validation purposes.

Movement records link to resolution records via `element_id` to track the complete
lifecycle of information changes during migrations.

Usage:
    uv run record-movement --id <element_id> --source-file <path> --target-file <path> \
        --reason "..." --coverage "..." --before-text "..." --after-text-source "..." \
        --target-before "..." --target-after "..."

Args:
    --id: Element identifier being moved (links to comparisons/resolutions).
    --source-file: Path to the source file where information originated.
    --target-file: Path to the target file where information was moved.
    --reason: Explanation of why the information was moved.
    --coverage: Description of what information is being covered/moved.
    --before-text: Original sentence in source file before the move.
    --after-text-source: Sentence in source file after information was removed.
    --target-before: Sentence in target file before information was added.
    --target-after: Sentence in target file after information was added.
    --knowledge-path: Base knowledge directory (default: .knowledge).
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

import duckdb

from scripts.utils import REPO_ROOT, utc_timestamp

CSV_COLUMNS = [
    "movement_id",
    "element_id",
    "source_file",
    "target_file",
    "reason",
    "coverage_description",
    "before_sentence",
    "after_sentence_source",
    "target_before_sentence",
    "target_after_sentence",
    "moved_at",
]


class MovementRecord(TypedDict):
    """A movement record for tracking information movements between files.

    Attributes:
        movement_id: Unique UUID for this movement record.
        element_id: YAML element identifier being moved.
        source_file: Relative path to the source file where information originated.
        target_file: Relative path to the target file where information was moved.
        reason: Explanation of why the information was moved.
        coverage_description: Description of what information is being covered/moved.
        before_sentence: Original sentence in source file before the move.
        after_sentence_source: Sentence in source file after information was removed.
        target_before_sentence: Sentence in target file before information was added.
        target_after_sentence: Sentence in target file after information was added.
        moved_at: ISO 8601 basic format timestamp of the movement.
    """

    movement_id: str
    element_id: str
    source_file: str
    target_file: str
    reason: str
    coverage_description: str
    before_sentence: str
    after_sentence_source: str
    target_before_sentence: str
    target_after_sentence: str
    moved_at: str


def ensure_csv_exists(csv_path: Path) -> None:
    """Create CSV file with header row if it doesn't exist or is empty.

    Uses DuckDB to create an empty CSV with proper headers.

    Args:
        csv_path: Path to the CSV file.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not csv_path.exists() or csv_path.stat().st_size == 0
    if needs_header:
        cols_select = ", ".join(f"'' AS {col}" for col in CSV_COLUMNS)
        query = f"COPY (SELECT * FROM (SELECT {cols_select}) WHERE 1=0) "
        query += f"TO '{csv_path}' (HEADER, DELIMITER ',')"
        duckdb.execute(query)


def append_movement(csv_path: Path, record: MovementRecord) -> None:
    """Append a movement record to the CSV file.

    Uses DuckDB to read existing data, add the new record, and write back.

    Args:
        csv_path: Path to the CSV file.
        record: Movement record to append.
    """
    conn = duckdb.connect()
    try:
        create_query = f"""
            CREATE TABLE movements AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """
        conn.execute(create_query)
        placeholders = ", ".join("?" for _ in CSV_COLUMNS)
        values = [record[col] for col in CSV_COLUMNS]  # type: ignore[literal-required]
        conn.execute(f"INSERT INTO movements VALUES ({placeholders})", values)
        conn.execute(f"COPY movements TO '{csv_path}' (HEADER, DELIMITER ',')")
    finally:
        conn.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for movement tracking.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Track information movements between files during migrations.",
    )
    parser.add_argument(
        "--id",
        required=True,
        help="Element identifier being moved (links to comparisons/resolutions).",
    )
    parser.add_argument(
        "--source-file",
        type=Path,
        required=True,
        help="Path to the source file where information originated.",
    )
    parser.add_argument(
        "--target-file",
        type=Path,
        required=True,
        help="Path to the target file where information was moved.",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Explanation of why the information was moved.",
    )
    parser.add_argument(
        "--coverage",
        required=True,
        help="Description of what information is being covered/moved.",
    )
    parser.add_argument(
        "--before-text",
        required=True,
        help="Original sentence in source file before the move.",
    )
    parser.add_argument(
        "--after-text-source",
        required=True,
        help="Sentence in source file after information was removed.",
    )
    parser.add_argument(
        "--target-before",
        required=True,
        help="Sentence in target file before information was added.",
    )
    parser.add_argument(
        "--target-after",
        required=True,
        help="Sentence in target file after information was added.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        help="Base knowledge directory, relative to REPO_ROOT or absolute (default: .knowledge).",
    )
    return parser.parse_args(argv)


def main() -> int:
    """Run movement tracking and record results.

    Returns:
        0 on success, 1 on error.
    """
    args = parse_args()

    source_file = (REPO_ROOT / args.source_file).resolve()
    target_file = (REPO_ROOT / args.target_file).resolve()

    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    if not source_file.exists():
        print(f"Error: Source file not found: {source_file}", file=sys.stderr)
        return 1

    if not target_file.exists():
        print(f"Error: Target file not found: {target_file}", file=sys.stderr)
        return 1

    if not source_file.is_relative_to(REPO_ROOT):
        print(f"Error: Source file must be within repository: {source_file}", file=sys.stderr)
        return 1

    if not target_file.is_relative_to(REPO_ROOT):
        print(f"Error: Target file must be within repository: {target_file}", file=sys.stderr)
        return 1

    source_file_rel = source_file.relative_to(REPO_ROOT).as_posix()
    target_file_rel = target_file.relative_to(REPO_ROOT).as_posix()

    movement_id = str(uuid.uuid4())
    moved_at = utc_timestamp()

    record = MovementRecord(
        movement_id=movement_id,
        element_id=args.id,
        source_file=source_file_rel,
        target_file=target_file_rel,
        reason=args.reason,
        coverage_description=args.coverage,
        before_sentence=args.before_text,
        after_sentence_source=args.after_text_source,
        target_before_sentence=args.target_before,
        target_after_sentence=args.target_after,
        moved_at=moved_at,
    )

    csv_path = knowledge_path / "movements" / "movements.csv"
    ensure_csv_exists(csv_path)
    append_movement(csv_path, record)

    print(f"Movement recorded with ID: {movement_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
