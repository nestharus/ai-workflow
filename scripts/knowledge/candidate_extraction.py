"""Stage 1: Extract keyword candidates from YAML documentation using spaCy NLP.

This module scans YAML documentation files and extracts potential keyword candidates
using spaCy's NLP pipeline. Candidates include noun phrases, named entities, and
technical terms identified through part-of-speech tagging.

Usage:
    # Extract candidates from all YAML docs
    uv run extract-keyword-candidates

    # Extract from specific directory
    uv run extract-keyword-candidates --source docs/

    # Specify output path
    uv run extract-keyword-candidates --output .knowledge/keywords/candidates.csv

Args:
    --source: Source directory containing YAML files (default: docs/).
    --output: Output CSV path (default: .knowledge/keywords/candidates.csv).
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

CSV_COLUMNS = [
    "candidate_id",
    "term",
    "source_file",
    "source_element_id",
    "extraction_method",
    "pos_tags",
    "confidence_score",
    "extracted_at",
]


class CandidateRecord(TypedDict):
    """A keyword candidate record extracted from documentation.

    Attributes:
        candidate_id: Unique identifier for this candidate.
        term: The extracted term or phrase.
        source_file: Relative path to the source YAML file.
        source_element_id: YAML element ID where term was found.
        extraction_method: Method used (noun_phrase, named_entity, technical_term).
        pos_tags: Part-of-speech tags for the term.
        confidence_score: Extraction confidence (0.0-1.0).
        extracted_at: ISO 8601 timestamp when extracted.
    """

    candidate_id: str
    term: str
    source_file: str
    source_element_id: str
    extraction_method: str
    pos_tags: str
    confidence_score: str
    extracted_at: str


def ensure_csv_exists(csv_path: Path) -> None:
    """Create CSV file with header row if it doesn't exist or is empty.

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


def append_candidate(csv_path: Path, record: CandidateRecord) -> None:
    """Append a candidate record to the CSV file.

    Args:
        csv_path: Path to the CSV file.
        record: Candidate record to append.
    """
    conn = duckdb.connect()
    try:
        conn.execute(f"""
            CREATE TABLE candidates AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """)
        placeholders = ", ".join("?" for _ in CSV_COLUMNS)
        values = [record[col] for col in CSV_COLUMNS]  # type: ignore[literal-required]
        conn.execute(f"INSERT INTO candidates VALUES ({placeholders})", values)
        conn.execute(f"COPY candidates TO '{csv_path}' (HEADER, DELIMITER ',')")
    finally:
        conn.close()


def is_candidate_tracked(csv_path: Path, term: str, source_file: str) -> bool:
    """Check if a candidate already exists for this term and source.

    Args:
        csv_path: Path to the CSV file.
        term: Term to check.
        source_file: Source file path.

    Returns:
        True if candidate exists, False otherwise.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return False

    query = """
        SELECT COUNT(*) as cnt
        FROM read_csv_auto(?)
        WHERE term = ?
        AND source_file = ?
    """
    try:
        result = duckdb.execute(query, [str(csv_path), term, source_file]).fetchone()
        return result is not None and result[0] > 0
    except duckdb.Error:
        return False


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for candidate extraction.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Extract keyword candidates from YAML documentation using spaCy.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("docs"),
        help="Source directory containing YAML files (default: docs/).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output CSV path (default: .knowledge/keywords/candidates.csv).",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def extract_candidates_main(args: argparse.Namespace) -> int:
    """Run candidate extraction from YAML documentation.

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error.
    """
    # Resolve paths
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    if args.source.is_absolute():
        source_path = args.source.resolve()
    else:
        source_path = (REPO_ROOT / args.source).resolve()

    if not source_path.exists():
        print(f"Error: Source directory not found: {source_path}", file=sys.stderr)
        return 1

    # Determine output path
    if args.output:
        csv_path = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    else:
        csv_path = knowledge_path / "keywords" / "candidates.csv"

    csv_path = csv_path.resolve()

    # Placeholder for actual extraction logic (Phase 2)
    print(f"Source: {source_path}")
    print(f"Output: {csv_path}")
    print("Candidate extraction not yet implemented (Phase 2).")

    return 0


def main() -> int:
    """Entry point for extract-keyword-candidates command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_args()
    return extract_candidates_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
