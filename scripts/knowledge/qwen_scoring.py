"""Score keyword candidates using Qwen embedding models.

This module provides optional scoring functionality using Qwen embedding and
reranker models from HuggingFace. It can score candidates based on semantic
relevance and contextual fit.

Usage:
    # Score all unscored candidates
    uv run score-candidates-with-qwen

    # Score specific candidates
    uv run score-candidates-with-qwen --ids <id1> <id2>

    # Use specific model
    uv run score-candidates-with-qwen --model Qwen/Qwen3-Embedding-0.6B

Args:
    --ids: Specific candidate IDs to score.
    --model: HuggingFace model to use for scoring.
    --batch-size: Batch size for inference (default: 32).
    --knowledge-path: Base knowledge directory (default: .knowledge).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import duckdb

from scripts.dev.utils import REPO_ROOT


def get_unscored_candidates(csv_path: Path) -> list[dict[str, str]]:
    """Get candidates that haven't been scored yet.

    Args:
        csv_path: Path to the candidates CSV file.

    Returns:
        List of unscored candidate records.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return []

    query = """
        SELECT *
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE confidence_score = '' OR confidence_score IS NULL
    """
    try:
        conn = duckdb.connect()
        result = conn.execute(query, [str(csv_path)])
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        conn.close()
        return [dict(zip(columns, row, strict=False)) for row in rows]
    except duckdb.Error:
        return []


def update_candidate_score(csv_path: Path, candidate_id: str, score: float) -> bool:
    """Update the confidence score for a candidate.

    Args:
        csv_path: Path to the candidates CSV file.
        candidate_id: ID of the candidate to update.
        score: New confidence score (0.0-1.0).

    Returns:
        True if update succeeded, False otherwise.
    """
    if not csv_path.exists():
        return False

    try:
        conn = duckdb.connect()
        conn.execute(f"""
            CREATE TABLE candidates AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """)
        conn.execute(
            "UPDATE candidates SET confidence_score = ? WHERE candidate_id = ?",
            [str(score), candidate_id],
        )
        conn.execute(f"COPY candidates TO '{csv_path}' (HEADER, DELIMITER ',')")
        conn.close()
        return True
    except duckdb.Error:
        return False


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for Qwen scoring.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Score keyword candidates using Qwen embedding models.",
    )
    parser.add_argument(
        "--ids",
        nargs="+",
        help="Specific candidate IDs to score.",
    )
    parser.add_argument(
        "--model",
        default="Qwen/Qwen3-Embedding-0.6B",
        help="HuggingFace model to use for scoring.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        dest="batch_size",
        help="Batch size for inference (default: 32).",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def score_candidates_main(args: argparse.Namespace) -> int:
    """Run Qwen-based candidate scoring.

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error.
    """
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    candidates_csv = knowledge_path / "keywords" / "candidates.csv"

    if not candidates_csv.exists():
        print(f"Error: Candidates CSV not found: {candidates_csv}", file=sys.stderr)
        return 1

    print(f"Model: {args.model}")
    print(f"Batch size: {args.batch_size}")
    print(f"Candidates: {candidates_csv}")

    # Placeholder for actual scoring logic (Phase 2)
    print("Qwen scoring not yet implemented (Phase 2).")

    return 0


def main() -> int:
    """Entry point for score-candidates-with-qwen command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_args()
    return score_candidates_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
