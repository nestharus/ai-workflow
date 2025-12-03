"""Track resolved documentation sections using content hashes.

This module provides utilities for tracking resolution status of documentation
sections during migrations. It computes SHA-256 hashes of text content and files,
stores timestamped copies in `.knowledge/originals/`, and appends resolution records
to `.knowledge/resolutions/resolved.csv`.

Resolution tracking uses both file paths and content hashes for uniqueness checks.
The `id` column stores the YAML element identifier, while `resolution_id` provides
a unique UUID for each resolution record. Duplicate detection is based on
(id, source_file, split_file) to support path-level uniqueness.

Projection Versioning (per fact_redesign.md lines 1289-1327):
    The CSV schema includes projection versioning fields for structural integrity:

    - projection_version: Identifies slicing/FieldFact/text projection rules
      (e.g., 'fieldfacts.v2'). Version bumps when slicing, FieldFact structure,
      or text projection format changes.

    - *_content_hash: SHA-256 of canonical FieldFact payload, providing
      structural hashing independent of text formatting. Changes only when
      field values/names change, not when text projection format changes.

    - *_text_hash: SHA-256 of synthetic fact-line text projection. Now reflects
      sliced representations with $ref tokens (per fact_redesign lines 131-133),
      meaning parent hashes don't change when nested element internals change.

    Schema evolution is append-only: existing CSV readers selecting original
    columns remain unaffected.

Usage:
    uv run knowledge.mark-resolved --id <element_id> --source-file <path> \
      --split-file <path> [<path> ...]

Args:
    --id: Element identifier to mark as resolved.
    --source-file: Path to the source YAML file.
    --split-file: One or more paths to split YAML files.
    --knowledge-path: Base knowledge directory (default: .knowledge).
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

import duckdb

from scripts.dev.utils import REPO_ROOT, utc_timestamp
from scripts.knowledge.compare_yaml_docs import (
    compute_element_content_hash,
    extract_ids_and_text,
    parse_yaml_file,
)

# Current projection version for text projection contract
# Per fact_redesign.md lines 1398-1426, this identifies:
# - Element slicing rules (nested-id replacement with $ref)
# - FieldFact extraction (roles, grouping, artifact root tagging)
# - Text projection format ([ancestor > element_id] field_path = value)
PROJECTION_VERSION = "fieldfacts.v2"

CSV_COLUMNS = [
    "resolution_id",
    "id",
    "source_file",
    "split_file",
    "original_text_hash",
    "split_text_hash",
    "source_file_hash",
    "split_file_hash",
    "resolved_at",
    # New columns for projection versioning (per fact_redesign.md lines 1289-1327)
    # Append-only schema evolution: existing CSV readers selecting original columns
    # remain unaffected
    "projection_version",
    "original_content_hash",
    "split_content_hash",
]


class ResolutionRecord(TypedDict):
    """A resolution record for tracking resolved documentation sections.

    Per fact_redesign.md lines 1289-1327, records include projection versioning
    and content hashes for structural integrity tracking.

    projection_version identifies the slicing/FieldFact/text projection rules.
    *_content_hash provides structural hashing independent of text formatting.
    *_text_hash reflects sliced representations with $ref tokens (primary for
    backward compatibility).

    Attributes:
        resolution_id: Unique UUID for this resolution record.
        id: YAML element identifier being resolved.
        source_file: Relative path to the source YAML file.
        split_file: Relative path to the split YAML file.
        original_text_hash: SHA-256 hash of original fact-line text projection.
        split_text_hash: SHA-256 hash of split fact-line text projection.
        source_file_hash: SHA-256 hash of source file at resolution time.
        split_file_hash: SHA-256 hash of split file at resolution time.
        resolved_at: ISO 8601 timestamp of resolution.
        projection_version: Version of text projection contract (e.g., 'fieldfacts.v2').
        original_content_hash: SHA-256 of canonical FieldFact payload for original.
        split_content_hash: SHA-256 of canonical FieldFact payload for split.
    """

    resolution_id: str
    id: str
    source_file: str
    split_file: str
    original_text_hash: str
    split_text_hash: str
    source_file_hash: str
    split_file_hash: str
    resolved_at: str
    projection_version: str
    original_content_hash: str
    split_content_hash: str


def compute_text_hash(text: str) -> str:
    """Compute SHA-256 hash of text content.

    Args:
        text: Text content to hash.

    Returns:
        Hexadecimal digest of the SHA-256 hash.
    """
    normalized = text.strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of file content.

    Args:
        file_path: Path to the file to hash.

    Returns:
        Hexadecimal digest of the SHA-256 hash.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    content = file_path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def save_original_file(source_path: Path, knowledge_path: Path) -> Path:
    """Copy source file to originals directory with timestamp.

    Args:
        source_path: Path to the source file to copy.
        knowledge_path: Base knowledge directory path.

    Returns:
        Path to the saved copy in originals directory.

    Raises:
        FileNotFoundError: If the source file does not exist.
    """
    originals_dir = knowledge_path / "originals"
    originals_dir.mkdir(parents=True, exist_ok=True)

    timestamp = utc_timestamp()
    dest_name = f"{timestamp}-{source_path.name}"
    dest_path = originals_dir / dest_name

    shutil.copy2(source_path, dest_path)
    return dest_path


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


def append_resolution(csv_path: Path, record: ResolutionRecord) -> None:
    """Append a resolution record to the CSV file.

    Uses DuckDB to read existing data, add the new record, and write back.

    Args:
        csv_path: Path to the CSV file.
        record: Resolution record to append.
    """
    conn = duckdb.connect()
    try:
        conn.execute(f"""
            CREATE TABLE resolutions AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """)
        placeholders = ", ".join("?" for _ in CSV_COLUMNS)
        values = [record[col] for col in CSV_COLUMNS]  # type: ignore[literal-required]
        conn.execute(f"INSERT INTO resolutions VALUES ({placeholders})", values)
        conn.execute(f"COPY resolutions TO '{csv_path}' (HEADER, DELIMITER ',')")
    finally:
        conn.close()


def is_already_resolved(
    csv_path: Path,
    element_id: str,
    source_file_path: str,
    split_file_path: str,
) -> bool:
    """Check if a resolution record already exists.

    Uses DuckDB to query the CSV file for matching records based on
    element ID and file paths for path-level uniqueness.

    Args:
        csv_path: Path to the CSV file.
        element_id: Element identifier to check.
        source_file_path: Relative path to source file.
        split_file_path: Relative path to split file.

    Returns:
        True if a matching resolution record exists, False otherwise.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return False

    query = """
        SELECT COUNT(*) as cnt
        FROM read_csv_auto(?)
        WHERE id = ?
        AND source_file = ?
        AND split_file = ?
    """
    try:
        result = duckdb.execute(
            query,
            [str(csv_path), element_id, source_file_path, split_file_path],
        ).fetchone()
        return result is not None and result[0] > 0
    except duckdb.Error:
        return False


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


def extract_text_for_id(file_path: Path, element_id: str) -> str:
    """Extract text content for a specific ID from a YAML file.

    The text hash is computed from the sliced representation per the fact
    redesign (lines 131-133 of docs/plans/fact_redesign.md). Child content
    is excluded and replaced with $ref tokens, ensuring that the hash
    reflects only the parent element's direct content.

    Args:
        file_path: Path to the YAML file.
        element_id: Element identifier to extract.

    Returns:
        Text content for the specified ID (sliced representation).

    Raises:
        ValueError: If the ID is not found in the file.
        FileNotFoundError: If the file does not exist.
    """
    data = parse_yaml_file(file_path)
    # extract_ids_and_text uses sliced representations with child content
    # replaced by $ref tokens per the fact redesign specification
    ids_text = extract_ids_and_text(data)

    if element_id not in ids_text:
        display_path = _get_display_path(file_path)
        msg = f"ID '{element_id}' not found in {display_path}"
        raise ValueError(msg)

    return ids_text[element_id]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for resolution tracking.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Track resolved documentation sections using content hashes.",
    )
    parser.add_argument(
        "--id",
        required=True,
        help="Element identifier to mark as resolved.",
    )
    parser.add_argument(
        "--source-file",
        type=Path,
        required=True,
        help="Path to the source YAML file.",
    )
    parser.add_argument(
        "--split-file",
        type=Path,
        nargs="*",
        default=[],
        help="One or more paths to split YAML files.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        help="Base knowledge directory, relative to REPO_ROOT or absolute (default: .knowledge).",
    )
    return parser.parse_args(argv)


def main() -> int:
    """Run resolution tracking and record results.

    Returns:
        0 on success, 1 on error.
    """
    args = parse_args()

    split_files: list[Path] = args.split_file
    if not split_files:
        print("Error: At least one --split-file is required.", file=sys.stderr)
        return 1

    source_file = (REPO_ROOT / args.source_file).resolve()

    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    if not source_file.exists():
        print(f"Error: Source file not found: {source_file}", file=sys.stderr)
        return 1

    if not source_file.is_relative_to(REPO_ROOT):
        print(f"Error: Source file must be within repository: {source_file}", file=sys.stderr)
        return 1

    source_file_rel = source_file.relative_to(REPO_ROOT).as_posix()

    try:
        original_text = extract_text_for_id(source_file, args.id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Parse source file once for content hash computation
    source_data = parse_yaml_file(source_file)

    original_text_hash = compute_text_hash(original_text)
    source_file_hash = compute_file_hash(source_file)
    # Compute structural content hash from canonical FieldFact payload
    # Per fact_redesign.md lines 1446-1469, this provides hash stability
    # independent of text formatting changes
    original_content_hash = compute_element_content_hash(source_data, args.id)

    csv_path = knowledge_path / "resolutions" / "resolved.csv"
    records_created = 0
    errors: list[str] = []
    saved_split_files: set[Path] = set()

    # Save source file once before processing split files
    source_file_saved = False

    for split_file_arg in split_files:
        split_file = (REPO_ROOT / split_file_arg).resolve()

        if not split_file.exists():
            errors.append(f"Split file not found: {split_file}")
            continue

        if not split_file.is_relative_to(REPO_ROOT):
            errors.append(f"Split file must be within repository: {split_file}")
            continue

        split_file_rel = split_file.relative_to(REPO_ROOT).as_posix()

        try:
            split_text = extract_text_for_id(split_file, args.id)
        except ValueError as exc:
            errors.append(f"Error in {split_file_rel}: {exc}")
            continue
        except FileNotFoundError as exc:
            errors.append(f"Error in {split_file_rel}: {exc}")
            continue

        if is_already_resolved(csv_path, args.id, source_file_rel, split_file_rel):
            print(f"ID '{args.id}' is already resolved for {split_file_rel}, skipping.")
            continue

        split_text_hash = compute_text_hash(split_text)
        split_file_hash = compute_file_hash(split_file)
        # Compute structural content hash for split file
        split_data = parse_yaml_file(split_file)
        split_content_hash = compute_element_content_hash(split_data, args.id)

        # Save source file only once per invocation
        if not source_file_saved:
            save_original_file(source_file, knowledge_path)
            source_file_saved = True

        # Save each split file only once per invocation
        if split_file not in saved_split_files:
            save_original_file(split_file, knowledge_path)
            saved_split_files.add(split_file)

        resolved_at = utc_timestamp()
        record = ResolutionRecord(
            resolution_id=str(uuid.uuid4()),
            id=args.id,
            source_file=source_file_rel,
            split_file=split_file_rel,
            original_text_hash=original_text_hash,
            split_text_hash=split_text_hash,
            source_file_hash=source_file_hash,
            split_file_hash=split_file_hash,
            resolved_at=resolved_at,
            # New projection versioning fields (per fact_redesign.md lines 1289-1327)
            # Text hashes now reflect sliced representations with $ref tokens
            projection_version=PROJECTION_VERSION,
            original_content_hash=original_content_hash,
            split_content_hash=split_content_hash,
        )

        ensure_csv_exists(csv_path)
        append_resolution(csv_path, record)
        records_created += 1

    if records_created > 0:
        record_word = "record" if records_created == 1 else "records"
        print(f"Resolution recorded for '{args.id}' ({records_created} {record_word})")

    if errors:
        print("\nErrors encountered:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
