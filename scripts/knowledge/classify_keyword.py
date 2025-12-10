r"""Classify keyword candidates by updating the candidates CSV.

This module provides CLI functionality for sub-agents to persist classification
decisions for keyword candidates. Sub-agents call this script instead of
modifying CSV files directly, ensuring consistent data access patterns.

Usage:
    # Classify a candidate as keep (true keyword)
    uv run knowledge.classify-keyword \
      --id <candidate_id> \
      --keep true \
      --confidence 0.94 \
      --reason "Central concept (connection management layer)."

    # Classify a candidate as noise (not a keyword)
    uv run knowledge.classify-keyword \
      --id <candidate_id> \
      --keep false \
      --confidence 0.87 \
      --reason "Too generic, common English word."

Args:
    --id: Candidate UUID to classify (required).
    --keep: Classification decision - 'true' to keep, 'false' to discard (required).
    --confidence: Confidence score between 0.0 and 1.0 (required).
    --reason: Short explanation for the classification decision (required).
    --knowledge-path: Base knowledge directory (default: .knowledge).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import duckdb

from scripts.dev.utils import REPO_ROOT, utc_timestamp
from scripts.knowledge.keyword_schema import KEYWORD_COLUMNS

__all__ = ["KEYWORD_COLUMNS"]  # Re-export for backwards compatibility


def update_candidate_classification(
    csv_path: Path,
    candidate_id: str,
    keep: str,
    confidence: str,
    reason: str,
) -> bool:
    """Update classification fields for a candidate in the CSV.

    Uses DuckDB to read the CSV, update the record, and write back.

    Args:
        csv_path: Path to the candidates.csv file.
        candidate_id: UUID of the candidate to update.
        keep: Classification decision ('true' or 'false').
        confidence: Confidence score as string (e.g., '0.94').
        reason: Short explanation for the classification.

    Returns:
        True if update succeeded, False otherwise.
    """
    if not csv_path.exists():
        return False

    classified_at = utc_timestamp()

    try:
        with duckdb.connect() as conn:
            conn.execute(f"""
                CREATE TABLE candidates AS
                SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
            """)

            # Check if candidate exists
            result = conn.execute(
                "SELECT candidate_id FROM candidates WHERE candidate_id = ?",
                [candidate_id],
            ).fetchone()

            if result is None:
                return False

            # Update the classification fields
            conn.execute(
                """
                UPDATE candidates
                SET keep = ?,
                    confidence = ?,
                    reason = ?,
                    classified_at = ?
                WHERE candidate_id = ?
                """,
                [keep, confidence, reason, classified_at, candidate_id],
            )

            conn.execute(f"COPY candidates TO '{csv_path}' (HEADER, DELIMITER ',')")
    except duckdb.Error:
        return False
    else:
        return True


def get_candidate_text(csv_path: Path, candidate_id: str) -> str | None:
    """Get the candidate text for display purposes.

    Args:
        csv_path: Path to the candidates.csv file.
        candidate_id: UUID of the candidate.

    Returns:
        Candidate text if found, None otherwise.
    """
    if not csv_path.exists():
        return None

    query = """
        SELECT candidate_text
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE candidate_id = ?
    """
    try:
        result = duckdb.execute(query, [str(csv_path), candidate_id]).fetchone()
        if result:
            return str(result[0])
    except duckdb.Error:
        pass
    return None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for keyword classification.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Classify keyword candidates by updating the candidates CSV.",
    )
    parser.add_argument(
        "--id",
        required=True,
        dest="candidate_id",
        help="Candidate UUID to classify.",
    )
    parser.add_argument(
        "--keep",
        required=True,
        choices=["true", "false"],
        help="Classification decision - 'true' to keep, 'false' to discard.",
    )
    parser.add_argument(
        "--confidence",
        required=True,
        type=float,
        help="Confidence score between 0.0 and 1.0.",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Short explanation for the classification decision.",
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
    """Run keyword classification and update the CSV.

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error.
    """
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    csv_path = knowledge_path / "keywords" / "candidates.csv"

    if not csv_path.exists():
        print(f"Error: Candidates CSV not found: {csv_path}", file=sys.stderr)
        return 1

    # Validate confidence range
    if not 0.0 <= args.confidence <= 1.0:
        print("Error: Confidence must be between 0.0 and 1.0", file=sys.stderr)
        return 1

    # Get candidate text for display
    candidate_text = get_candidate_text(csv_path, args.candidate_id)
    if candidate_text is None:
        print(f"Error: Candidate '{args.candidate_id}' not found", file=sys.stderr)
        return 1

    # Update the classification
    success = update_candidate_classification(
        csv_path=csv_path,
        candidate_id=args.candidate_id,
        keep=args.keep,
        confidence=str(args.confidence),
        reason=args.reason,
    )

    if not success:
        print(f"Error: Failed to update candidate '{args.candidate_id}'", file=sys.stderr)
        return 1

    # Output confirmation
    print(f"Classified candidate: {args.candidate_id}")
    print(f"  Text: {candidate_text}")
    print(f"  Keep: {args.keep}")
    print(f"  Confidence: {args.confidence}")
    print(f"  Reason: {args.reason}")

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
