"""Query keyword variant pairs from the variant candidates table.

This module provides utilities for querying keyword variant pairs, finding
unvalidated pairs for review, and displaying variant relationships.

Usage:
    # List all variant pairs
    uv run knowledge.query-variants

    # Query unvalidated pairs (for sub-agent review)
    uv run knowledge.query-variants --unvalidated --format json

    # Filter by validation status
    uv run knowledge.query-variants --validated

    # Filter by minimum similarity
    uv run knowledge.query-variants --min-similarity 0.9

    # Output as JSON
    uv run knowledge.query-variants --format json --limit 50

Args:
    --unvalidated: Show only unvalidated pairs (validated is empty or null).
    --validated: Show only validated pairs.
    --min-similarity: Minimum similarity score (0.0-1.0).
    --limit: Maximum number of results.
    --format: Output format ("text" or "json").
    --knowledge-path: Base knowledge directory (default: .knowledge).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import duckdb

from scripts.dev.utils import REPO_ROOT


def query_variants(
    csv_path: Path,
    *,
    unvalidated_only: bool = False,
    validated_only: bool = False,
    min_similarity: float | None = None,
    limit: int | None = None,
) -> list[dict[str, str]]:
    """Query variant pairs from CSV with optional filters.

    Args:
        csv_path: Path to the variants CSV file.
        unvalidated_only: Only return unvalidated pairs.
        validated_only: Only return validated pairs.
        min_similarity: Minimum similarity score.
        limit: Maximum results to return.

    Returns:
        List of variant pair records as dictionaries.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return []

    conditions: list[str] = []
    params: list[str | float] = [str(csv_path)]

    if unvalidated_only:
        conditions.append("(validated IS NULL OR validated = '')")

    if validated_only:
        conditions.append("validated = 'true'")

    if min_similarity is not None:
        conditions.append("CAST(similarity AS DOUBLE) >= ?")
        params.append(min_similarity)

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
        ORDER BY similarity DESC
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
    """Parse command-line arguments for variant querying.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Query keyword variant pairs.",
    )
    parser.add_argument(
        "--unvalidated",
        action="store_true",
        help="Show only unvalidated pairs.",
    )
    parser.add_argument(
        "--validated",
        action="store_true",
        help="Show only validated pairs.",
    )
    parser.add_argument(
        "--min-similarity",
        type=float,
        dest="min_similarity",
        help="Minimum similarity score (0.0-1.0).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of results.",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        dest="output_format",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def query_variants_main(args: argparse.Namespace) -> int:
    """Run variant query and display results.

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error.
    """
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    csv_path = knowledge_path / "keywords" / "variant_candidates.csv"

    if not csv_path.exists():
        print(f"Error: Variants CSV not found: {csv_path}", file=sys.stderr)
        return 1

    variants = query_variants(
        csv_path,
        unvalidated_only=args.unvalidated,
        validated_only=args.validated,
        min_similarity=args.min_similarity,
        limit=args.limit,
    )

    if not variants:
        if args.output_format == "json":
            print("[]")
        else:
            print("No variant pairs found matching criteria.")
        return 0

    if args.output_format == "json":
        print(json.dumps(variants, indent=2))
    else:
        print(f"Found {len(variants)} variant pair(s):\n")
        for variant in variants:
            print(f"  Pair ID: {variant.get('pair_id', '')}")
            print(f"    Keyword A: {variant.get('keyword_a', '')}")
            print(f"    Keyword B: {variant.get('keyword_b', '')}")
            print(f"    Similarity: {variant.get('similarity', '')}")
            merge = variant.get("merge", "")
            if merge:
                print(f"    Merge: {merge}")
                print(f"    Canonical: {variant.get('canonical', '')}")
                print(f"    Reason: {variant.get('reason', '')}")
            print(f"    Validated: {variant.get('validated', '') or 'no'}")
            print()

    return 0


def main() -> int:
    """Entry point for query-variants command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_args()
    return query_variants_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
