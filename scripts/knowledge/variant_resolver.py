"""Stage 5: Track and resolve keyword variants using embeddings.

This module provides functionality for identifying and tracking keyword variants
(synonyms, abbreviations, alternate spellings) using embedding similarity. It
uses Qwen embeddings to find semantically similar terms and tracks them as
variant candidates.

Usage:
    # Track variants for all keywords
    uv run track-keyword-variants

    # Track variants for specific keyword
    uv run track-keyword-variants --keyword-id <id>

    # Set similarity threshold
    uv run track-keyword-variants --threshold 0.85

Args:
    --keyword-id: Specific keyword ID to find variants for.
    --threshold: Minimum similarity threshold (default: 0.85).
    --model: HuggingFace model for embeddings.
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

VARIANT_COLUMNS = [
    "variant_id",
    "keyword_id",
    "variant_term",
    "similarity_score",
    "source_file",
    "detected_at",
    "validated",
    "is_canonical",
]


class VariantRecord(TypedDict):
    """A keyword variant candidate record.

    Attributes:
        variant_id: Unique identifier for this variant.
        keyword_id: ID of the canonical keyword this is a variant of.
        variant_term: The variant term.
        similarity_score: Embedding similarity score (0.0-1.0).
        source_file: File where variant was found.
        detected_at: ISO 8601 timestamp when detected.
        validated: Whether variant has been validated ("true" or "false").
        is_canonical: Whether this is the canonical form ("true" or "false").
    """

    variant_id: str
    keyword_id: str
    variant_term: str
    similarity_score: str
    source_file: str
    detected_at: str
    validated: str
    is_canonical: str


def ensure_variants_csv_exists(csv_path: Path) -> None:
    """Create variants CSV file with header if it doesn't exist.

    Args:
        csv_path: Path to the variants CSV file.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not csv_path.exists() or csv_path.stat().st_size == 0
    if needs_header:
        cols_select = ", ".join(f"'' AS {col}" for col in VARIANT_COLUMNS)
        query = f"COPY (SELECT * FROM (SELECT {cols_select}) WHERE 1=0) "
        query += f"TO '{csv_path}' (HEADER, DELIMITER ',')"
        duckdb.execute(query)


def append_variant(csv_path: Path, record: VariantRecord) -> None:
    """Append a variant record to the variants CSV.

    Args:
        csv_path: Path to the variants CSV file.
        record: Variant record to append.
    """
    conn = duckdb.connect()
    try:
        conn.execute(f"""
            CREATE TABLE variants AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """)
        placeholders = ", ".join("?" for _ in VARIANT_COLUMNS)
        values = [record[col] for col in VARIANT_COLUMNS]  # type: ignore[literal-required]
        conn.execute(f"INSERT INTO variants VALUES ({placeholders})", values)
        conn.execute(f"COPY variants TO '{csv_path}' (HEADER, DELIMITER ',')")
    finally:
        conn.close()


def is_variant_tracked(csv_path: Path, keyword_id: str, variant_term: str) -> bool:
    """Check if a variant already exists.

    Args:
        csv_path: Path to the variants CSV file.
        keyword_id: Keyword ID to check.
        variant_term: Variant term to check.

    Returns:
        True if variant exists, False otherwise.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return False

    query = """
        SELECT COUNT(*) as cnt
        FROM read_csv_auto(?)
        WHERE keyword_id = ?
        AND variant_term = ?
    """
    try:
        result = duckdb.execute(query, [str(csv_path), keyword_id, variant_term]).fetchone()
        return result is not None and result[0] > 0
    except duckdb.Error:
        return False


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for variant tracking.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Track and resolve keyword variants using embeddings.",
    )
    parser.add_argument(
        "--keyword-id",
        dest="keyword_id",
        help="Specific keyword ID to find variants for.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="Minimum similarity threshold (default: 0.85).",
    )
    parser.add_argument(
        "--model",
        default="Qwen/Qwen3-Embedding-0.6B",
        help="HuggingFace model for embeddings.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def track_variants_main(args: argparse.Namespace) -> int:
    """Run variant tracking.

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error.
    """
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    keywords_csv = knowledge_path / "keywords" / "keywords.csv"
    variants_csv = knowledge_path / "keywords" / "variant_candidates.csv"

    if not keywords_csv.exists():
        print(f"Error: Keywords CSV not found: {keywords_csv}", file=sys.stderr)
        return 1

    print(f"Model: {args.model}")
    print(f"Threshold: {args.threshold}")
    print(f"Keywords: {keywords_csv}")
    print(f"Variants: {variants_csv}")

    # Placeholder for actual variant tracking logic (Phase 5)
    print("Variant tracking not yet implemented (Phase 5).")

    return 0


def main_track() -> int:
    """Entry point for track-keyword-variants command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_args()
    return track_variants_main(args)


if __name__ == "__main__":
    raise SystemExit(main_track())
