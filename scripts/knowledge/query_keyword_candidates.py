"""Query and filter keyword candidates from the candidates CSV.

This module provides utilities for querying the extracted keyword candidates,
filtering by various criteria, and displaying results for review.

Usage:
    # List all candidates
    uv run query-keyword-candidates

    # Filter by extraction method
    uv run query-keyword-candidates --method noun_phrase

    # Filter by source file
    uv run query-keyword-candidates --source docs/architecture/

    # Filter by minimum confidence
    uv run query-keyword-candidates --min-confidence 0.8

Args:
    --method: Filter by extraction method (noun_phrase, named_entity, technical_term).
    --source: Filter by source file path prefix.
    --min-confidence: Minimum confidence score (0.0-1.0).
    --unclassified: Show only unclassified candidates.
    --limit: Maximum number of results to display.
    --knowledge-path: Base knowledge directory (default: .knowledge).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import duckdb

from scripts.dev.utils import REPO_ROOT


def query_candidates(
    csv_path: Path,
    *,
    method: str | None = None,
    source_prefix: str | None = None,
    min_confidence: float | None = None,
    limit: int | None = None,
) -> list[dict[str, str]]:
    """Query candidates from CSV with optional filters.

    Args:
        csv_path: Path to the candidates CSV file.
        method: Filter by extraction method.
        source_prefix: Filter by source file path prefix.
        min_confidence: Minimum confidence score.
        limit: Maximum results to return.

    Returns:
        List of candidate records as dictionaries.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return []

    conditions: list[str] = []
    params: list[str | float] = [str(csv_path)]

    if method:
        conditions.append("extraction_method = ?")
        params.append(method)

    if source_prefix:
        conditions.append("source_file LIKE ?")
        params.append(f"{source_prefix}%")

    if min_confidence is not None:
        conditions.append("CAST(confidence_score AS DOUBLE) >= ?")
        params.append(min_confidence)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    limit_clause = ""
    if limit:
        limit_clause = f"LIMIT {limit}"

    query = f"""
        SELECT *
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        {where_clause}
        ORDER BY extracted_at DESC
        {limit_clause}
    """

    try:
        conn = duckdb.connect()
        result = conn.execute(query, params)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        conn.close()
        return [dict(zip(columns, row, strict=False)) for row in rows]
    except duckdb.Error:
        return []


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for candidate querying.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Query and filter keyword candidates.",
    )
    parser.add_argument(
        "--method",
        choices=["noun_phrase", "named_entity", "technical_term"],
        help="Filter by extraction method.",
    )
    parser.add_argument(
        "--source",
        help="Filter by source file path prefix.",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        dest="min_confidence",
        help="Minimum confidence score (0.0-1.0).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of results to display.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def query_candidates_main(args: argparse.Namespace) -> int:
    """Run candidate query and display results.

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

    candidates = query_candidates(
        csv_path,
        method=args.method,
        source_prefix=args.source,
        min_confidence=args.min_confidence,
        limit=args.limit,
    )

    if not candidates:
        print("No candidates found matching criteria.")
        return 0

    print(f"Found {len(candidates)} candidate(s):\n")
    for candidate in candidates:
        print(f"  Term: {candidate.get('term', '')}")
        print(f"    Source: {candidate.get('source_file', '')}")
        print(f"    Method: {candidate.get('extraction_method', '')}")
        print(f"    Confidence: {candidate.get('confidence_score', '')}")
        print()

    return 0


def main() -> int:
    """Entry point for query-keyword-candidates command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_args()
    return query_candidates_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
