"""Track and validate additions (new IDs in target files not present in originals).

This module provides utilities for detecting and validating additions during
documentation migrations. Additions are new IDs/content that appear in target
files but were not present in the original source files. The system queries
comparison CSVs for `origin_type='split_only'` entries and tracks them in
`.knowledge/additions/additions.csv`.

Usage:
    # Track additions across all patterns
    uv run knowledge.track-additions

    # Track additions for a specific pattern
    uv run knowledge.track-additions --pattern api-patterns

    # Validate an addition
    uv run knowledge.validate-addition --id <addition_id> --validated --in-scope --meaningful

Args:
    --pattern: Filter by pattern name (e.g., api-patterns) (optional).
    --id: Addition UUID to validate (required for validate-addition).
    --validated: Mark the addition as reviewed.
    --in-scope: Mark the addition as within project scope.
    --meaningful: Mark the addition as providing meaningful value.
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

from scripts.dev.utils import REPO_ROOT, utc_timestamp

CSV_COLUMNS = [
    "addition_id",
    "element_id",
    "target_file",
    "added_text",
    "detected_at",
    "validated",
    "in_scope",
    "meaningful",
]


class AdditionRecord(TypedDict):
    """An addition record for tracking new IDs in target files.

    Attributes:
        addition_id: Unique UUID for this addition record.
        element_id: YAML element identifier found in target file.
        target_file: Relative path to the target file where new content was added.
        added_text: Text content of the added element.
        detected_at: ISO 8601 basic format timestamp when addition was detected.
        validated: Whether addition has been reviewed ("true" or "false").
        in_scope: Whether addition is within project scope ("true" or "false").
        meaningful: Whether addition provides meaningful value ("true" or "false").
    """

    addition_id: str
    element_id: str
    target_file: str
    added_text: str
    detected_at: str
    validated: str
    in_scope: str
    meaningful: str


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


def append_addition(csv_path: Path, record: AdditionRecord) -> None:
    """Append an addition record to the CSV file.

    Uses DuckDB to read existing data, add the new record, and write back.

    Args:
        csv_path: Path to the CSV file.
        record: Addition record to append.
    """
    conn = duckdb.connect()
    try:
        conn.execute(f"""
            CREATE TABLE additions AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """)
        placeholders = ", ".join("?" for _ in CSV_COLUMNS)
        values = [record[col] for col in CSV_COLUMNS]  # type: ignore[literal-required]
        conn.execute(f"INSERT INTO additions VALUES ({placeholders})", values)
        conn.execute(f"COPY additions TO '{csv_path}' (HEADER, DELIMITER ',')")
    finally:
        conn.close()


def is_already_tracked(csv_path: Path, element_id: str, target_file: str) -> bool:
    """Check if an addition record already exists.

    Uses DuckDB to query the CSV file for matching records based on
    element ID and target file path for duplicate detection.

    Args:
        csv_path: Path to the CSV file.
        element_id: Element identifier to check.
        target_file: Relative path to target file.

    Returns:
        True if a matching addition record exists, False otherwise.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return False

    query = """
        SELECT COUNT(*) as cnt
        FROM read_csv_auto(?)
        WHERE element_id = ?
        AND target_file = ?
    """
    try:
        result = duckdb.execute(
            query,
            [str(csv_path), element_id, target_file],
        ).fetchone()
        return result is not None and result[0] > 0
    except duckdb.Error:
        return False


def get_comparison_csv_paths(
    knowledge_path: Path,
    pattern: str | None = None,
) -> list[Path]:
    """Find comparison CSV files in the knowledge directory.

    Args:
        knowledge_path: Base knowledge directory path.
        pattern: Optional pattern name to filter by (e.g., 'api-patterns').

    Returns:
        List of paths to comparison CSV files.
    """
    comparisons_dir = knowledge_path / "comparisons"
    if not comparisons_dir.exists():
        return []

    if pattern:
        csv_path = comparisons_dir / f"{pattern}.csv"
        return [csv_path] if csv_path.exists() else []

    return sorted(comparisons_dir.glob("*.csv"))


class ComparisonQueryError(RuntimeError):
    """Raised when comparison CSV queries fail."""

    def __init__(self, failed_paths: list[Path]) -> None:
        """Initialize with list of failed CSV paths.

        Args:
            failed_paths: List of CSV paths that failed to query.
        """
        paths_str = ", ".join(str(p) for p in failed_paths)
        super().__init__(f"Failed to query comparison CSVs: {paths_str}")
        self.failed_paths = failed_paths


def query_split_only_additions(
    knowledge_path: Path,
    pattern: str | None = None,
) -> tuple[dict[str, list[dict[str, str]]], list[Path]]:
    """Query comparison CSVs for split_only entries (additions).

    Args:
        knowledge_path: Base knowledge directory path.
        pattern: Optional pattern name to filter by.

    Returns:
        Tuple of (results_by_pattern, failed_paths) where results_by_pattern is a
        dictionary mapping pattern names to lists of addition dicts with keys:
        element_id, target_file, added_text; and failed_paths is a list of CSV
        paths that failed to query due to DuckDB errors.

    Raises:
        FileNotFoundError: If no comparison CSV files are found.
        ComparisonQueryError: If all comparison CSV files fail to query.
    """
    csv_paths = get_comparison_csv_paths(knowledge_path, pattern)
    if not csv_paths:
        msg = f"No comparison CSV files found in {knowledge_path / 'comparisons'}"
        raise FileNotFoundError(msg)

    results_by_pattern: dict[str, list[dict[str, str]]] = {}
    failed_paths: list[Path] = []

    for csv_path in csv_paths:
        pattern_name = csv_path.stem

        query = """
            SELECT id, source_file, original_text
            FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
            WHERE origin_type = 'split_only'
        """

        try:
            result = duckdb.execute(query, [str(csv_path)])
            rows = result.fetchall()
        except duckdb.Error:
            failed_paths.append(csv_path)
            continue

        additions: list[dict[str, str]] = []
        for row in rows:
            element_id = str(row[0] or "")
            target_file = str(row[1] or "")
            added_text = str(row[2] or "")

            if element_id and target_file:
                additions.append(
                    {
                        "element_id": element_id,
                        "target_file": target_file,
                        "added_text": added_text,
                    }
                )

        if additions:
            results_by_pattern[pattern_name] = additions

    # If all files failed, raise an error
    if failed_paths and not results_by_pattern:
        raise ComparisonQueryError(failed_paths)

    return results_by_pattern, failed_paths


def _get_display_path(file_path: Path) -> str:
    """Get a display-friendly path, relative to REPO_ROOT if possible.

    Args:
        file_path: Absolute path to format.

    Returns:
        Path string relative to REPO_ROOT, or absolute path if outside repo.
    """
    try:
        return file_path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return file_path.as_posix()


def track_additions_main(args: argparse.Namespace) -> int:
    """Run addition tracking and record results.

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error.
    """
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    if not knowledge_path.exists():
        print(f"Error: Knowledge directory not found: {knowledge_path}", file=sys.stderr)
        return 1

    try:
        results_by_pattern, failed_paths = query_split_only_additions(
            knowledge_path=knowledge_path,
            pattern=args.pattern,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ComparisonQueryError as exc:
        print(f"Error: Could not read comparison CSVs: {exc}", file=sys.stderr)
        return 1

    # Warn about partial failures if some files succeeded but others failed
    if failed_paths:
        print("Warning: Failed to query the following comparison CSVs:", file=sys.stderr)
        for failed_path in failed_paths:
            display_path = _get_display_path(failed_path)
            print(f"  - {display_path}", file=sys.stderr)

    if not results_by_pattern:
        print("No additions (split_only entries) found in comparison data.")
        return 0

    csv_path = knowledge_path / "additions" / "additions.csv"
    ensure_csv_exists(csv_path)

    total_tracked = 0
    total_skipped = 0

    for pattern_name, additions in results_by_pattern.items():
        pattern_tracked = 0
        pattern_skipped = 0

        for addition in additions:
            element_id = addition["element_id"]
            target_file = addition["target_file"]
            added_text = addition["added_text"]

            if is_already_tracked(csv_path, element_id, target_file):
                pattern_skipped += 1
                continue

            record = AdditionRecord(
                addition_id=str(uuid.uuid4()),
                element_id=element_id,
                target_file=target_file,
                added_text=added_text,
                detected_at=utc_timestamp(),
                validated="false",
                in_scope="false",
                meaningful="false",
            )
            append_addition(csv_path, record)
            pattern_tracked += 1

        if pattern_tracked > 0 or pattern_skipped > 0:
            msg = f"{pattern_name}: {pattern_tracked} tracked, {pattern_skipped} skipped"
            print(f"{msg} (duplicates)")

        total_tracked += pattern_tracked
        total_skipped += pattern_skipped

    print(f"\nTotal: {total_tracked} additions tracked, {total_skipped} skipped")

    if total_tracked > 0:
        display_path = _get_display_path(csv_path)
        print(f"Output: {display_path}")

    return 0


def validate_addition_main(args: argparse.Namespace) -> int:
    """Update validation flags for an existing addition record.

    Uses DuckDB to read, update, and write the CSV file.

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error.
    """
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    csv_path = knowledge_path / "additions" / "additions.csv"

    if not csv_path.exists():
        print(f"Error: Additions CSV not found: {csv_path}", file=sys.stderr)
        return 1

    conn = duckdb.connect()
    try:
        conn.execute(f"""
            CREATE TABLE additions AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """)

        result = conn.execute(
            "SELECT * FROM additions WHERE addition_id = ?",
            [args.id],
        ).fetchone()

        if result is None:
            print(f"Error: Addition with ID '{args.id}' not found", file=sys.stderr)
            return 1

        update_parts: list[str] = []
        update_values: list[str] = []

        if args.validated:
            update_parts.append("validated = ?")
            update_values.append("true")
        if args.in_scope:
            update_parts.append("in_scope = ?")
            update_values.append("true")
        if args.meaningful:
            update_parts.append("meaningful = ?")
            update_values.append("true")

        if update_parts:
            update_values.append(args.id)
            conn.execute(
                f"UPDATE additions SET {', '.join(update_parts)} WHERE addition_id = ?",
                update_values,
            )

        conn.execute(f"COPY additions TO '{csv_path}' (HEADER, DELIMITER ',')")

        select_sql = (
            "SELECT validated, in_scope, meaningful, element_id "
            "FROM additions WHERE addition_id = ?"
        )
        updated = conn.execute(select_sql, [args.id]).fetchone()

        element_id = updated[3] if updated else "unknown"
        print(f"Updated addition '{args.id}' (element: {element_id})")
        print(f"  validated: {updated[0] if updated else 'unknown'}")
        print(f"  in_scope: {updated[1] if updated else 'unknown'}")
        print(f"  meaningful: {updated[2] if updated else 'unknown'}")
    finally:
        conn.close()

    return 0


def parse_track_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for addition tracking.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Track additions (new IDs in target files not present in originals).",
    )
    parser.add_argument(
        "--pattern",
        help="Pattern name to track additions for (e.g., api-patterns).",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        help="Base knowledge directory, relative to REPO_ROOT or absolute (default: .knowledge).",
    )
    return parser.parse_args(argv)


def parse_validate_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for addition validation.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Validate an addition record by updating its status flags.",
    )
    parser.add_argument(
        "--id",
        required=True,
        help="Addition UUID to validate.",
    )
    parser.add_argument(
        "--validated",
        action="store_true",
        help="Mark the addition as reviewed.",
    )
    parser.add_argument(
        "--in-scope",
        action="store_true",
        dest="in_scope",
        help="Mark the addition as within project scope.",
    )
    parser.add_argument(
        "--meaningful",
        action="store_true",
        help="Mark the addition as providing meaningful value.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        help="Base knowledge directory, relative to REPO_ROOT or absolute (default: .knowledge).",
    )
    return parser.parse_args(argv)


def main_track() -> int:
    """Entry point for track-additions command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_track_args()
    return track_additions_main(args)


def main_validate() -> int:
    """Entry point for validate-addition command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_validate_args()
    return validate_addition_main(args)


if __name__ == "__main__":
    raise SystemExit(main_track())
