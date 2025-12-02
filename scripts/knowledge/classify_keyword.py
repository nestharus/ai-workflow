"""Classify keyword candidates and promote them to the keywords table.

This module provides functionality to classify extracted keyword candidates,
assign them to categories, and promote validated candidates to the canonical
keywords table.

Usage:
    # Classify a candidate by ID
    uv run classify-keyword --id <candidate_id> --category domain --subcategory fastapi

    # Classify with rejection
    uv run classify-keyword --id <candidate_id> --reject --reason "too generic"

    # Batch classify from file
    uv run classify-keyword --batch classifications.json

Args:
    --id: Candidate ID to classify.
    --category: Primary category (domain, pattern, concept, entity).
    --subcategory: Subcategory within the primary category.
    --reject: Mark candidate as rejected.
    --reason: Reason for rejection or classification notes.
    --batch: JSON file with batch classifications.
    --knowledge-path: Base knowledge directory (default: .knowledge).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

import duckdb

from scripts.dev.utils import REPO_ROOT, utc_timestamp

KEYWORD_COLUMNS = [
    "keyword_id",
    "term",
    "category",
    "subcategory",
    "source_candidate_id",
    "source_file",
    "classified_at",
    "classification_notes",
]


class KeywordRecord(TypedDict):
    """A classified keyword record.

    Attributes:
        keyword_id: Unique identifier for this keyword.
        term: The canonical keyword term.
        category: Primary category (domain, pattern, concept, entity).
        subcategory: Subcategory within primary category.
        source_candidate_id: Original candidate ID this was promoted from.
        source_file: Original source file where term was found.
        classified_at: ISO 8601 timestamp when classified.
        classification_notes: Optional notes about classification.
    """

    keyword_id: str
    term: str
    category: str
    subcategory: str
    source_candidate_id: str
    source_file: str
    classified_at: str
    classification_notes: str


def ensure_keywords_csv_exists(csv_path: Path) -> None:
    """Create keywords CSV file with header if it doesn't exist.

    Args:
        csv_path: Path to the keywords CSV file.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not csv_path.exists() or csv_path.stat().st_size == 0
    if needs_header:
        cols_select = ", ".join(f"'' AS {col}" for col in KEYWORD_COLUMNS)
        query = f"COPY (SELECT * FROM (SELECT {cols_select}) WHERE 1=0) "
        query += f"TO '{csv_path}' (HEADER, DELIMITER ',')"
        duckdb.execute(query)


def get_candidate_by_id(candidates_csv: Path, candidate_id: str) -> dict[str, str] | None:
    """Retrieve a candidate record by ID.

    Args:
        candidates_csv: Path to the candidates CSV file.
        candidate_id: ID of the candidate to retrieve.

    Returns:
        Candidate record as dictionary, or None if not found.
    """
    if not candidates_csv.exists():
        return None

    query = """
        SELECT *
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE candidate_id = ?
    """
    try:
        conn = duckdb.connect()
        result = conn.execute(query, [str(candidates_csv), candidate_id])
        columns = [desc[0] for desc in result.description]
        row = result.fetchone()
        conn.close()
        if row:
            return dict(zip(columns, row, strict=False))
    except duckdb.Error:
        pass
    return None


def append_keyword(csv_path: Path, record: KeywordRecord) -> None:
    """Append a keyword record to the keywords CSV.

    Args:
        csv_path: Path to the keywords CSV file.
        record: Keyword record to append.
    """
    conn = duckdb.connect()
    try:
        conn.execute(f"""
            CREATE TABLE keywords AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """)
        placeholders = ", ".join("?" for _ in KEYWORD_COLUMNS)
        values = [record[col] for col in KEYWORD_COLUMNS]  # type: ignore[literal-required]
        conn.execute(f"INSERT INTO keywords VALUES ({placeholders})", values)
        conn.execute(f"COPY keywords TO '{csv_path}' (HEADER, DELIMITER ',')")
    finally:
        conn.close()


def is_keyword_exists(csv_path: Path, term: str) -> bool:
    """Check if a keyword already exists.

    Args:
        csv_path: Path to the keywords CSV file.
        term: Term to check.

    Returns:
        True if keyword exists, False otherwise.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return False

    query = """
        SELECT COUNT(*) as cnt
        FROM read_csv_auto(?)
        WHERE term = ?
    """
    try:
        result = duckdb.execute(query, [str(csv_path), term]).fetchone()
        return result is not None and result[0] > 0
    except duckdb.Error:
        return False


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for keyword classification.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Classify keyword candidates and promote to keywords table.",
    )
    parser.add_argument(
        "--id",
        dest="candidate_id",
        help="Candidate ID to classify.",
    )
    parser.add_argument(
        "--category",
        choices=["domain", "pattern", "concept", "entity"],
        help="Primary category for the keyword.",
    )
    parser.add_argument(
        "--subcategory",
        help="Subcategory within the primary category.",
    )
    parser.add_argument(
        "--reject",
        action="store_true",
        help="Mark candidate as rejected.",
    )
    parser.add_argument(
        "--reason",
        help="Reason for rejection or classification notes.",
    )
    parser.add_argument(
        "--batch",
        type=Path,
        help="JSON file with batch classifications.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def classify_keyword_main(args: argparse.Namespace) -> int:
    """Run keyword classification.

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error.
    """
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    keywords_dir = knowledge_path / "keywords"

    if not args.candidate_id and not args.batch:
        print("Error: Must specify --id or --batch", file=sys.stderr)
        return 1

    if args.candidate_id and not args.reject and not args.category:
        print("Error: Must specify --category or --reject", file=sys.stderr)
        return 1

    # Placeholder for actual classification logic (Phase 2)
    print(f"Knowledge path: {knowledge_path}")
    print(f"Keywords dir: {keywords_dir}")
    print("Keyword classification not yet implemented (Phase 2).")

    return 0


def main() -> int:
    """Entry point for classify-keyword command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_args()
    return classify_keyword_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
