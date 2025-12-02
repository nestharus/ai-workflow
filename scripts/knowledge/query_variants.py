"""Query keyword variants from the variant candidates table.

This module provides utilities for querying keyword variants, finding all
variants of a specific keyword, and displaying variant relationships.

Usage:
    # List all variants
    uv run query-variants

    # Query variants for specific keyword
    uv run query-variants --keyword-id <id>

    # Filter by validation status
    uv run query-variants --validated

    # Filter by minimum similarity
    uv run query-variants --min-similarity 0.9

Args:
    --keyword-id: Filter by keyword ID.
    --validated: Show only validated variants.
    --min-similarity: Minimum similarity score (0.0-1.0).
    --limit: Maximum number of results.
    --knowledge-path: Base knowledge directory (default: .knowledge).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import duckdb

from scripts.dev.utils import REPO_ROOT


def query_variants(
    csv_path: Path,
    *,
    keyword_id: str | None = None,
    validated_only: bool = False,
    min_similarity: float | None = None,
    limit: int | None = None,
) -> list[dict[str, str]]:
    """Query variants from CSV with optional filters.

    Args:
        csv_path: Path to the variants CSV file.
        keyword_id: Filter by keyword ID.
        validated_only: Only return validated variants.
        min_similarity: Minimum similarity score.
        limit: Maximum results to return.

    Returns:
        List of variant records as dictionaries.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return []

    conditions: list[str] = []
    params: list[str | float] = [str(csv_path)]

    if keyword_id:
        conditions.append("keyword_id = ?")
        params.append(keyword_id)

    if validated_only:
        conditions.append("validated = 'true'")

    if min_similarity is not None:
        conditions.append("CAST(similarity_score AS DOUBLE) >= ?")
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
        ORDER BY similarity_score DESC
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
        description="Query keyword variants.",
    )
    parser.add_argument(
        "--keyword-id",
        dest="keyword_id",
        help="Filter by keyword ID.",
    )
    parser.add_argument(
        "--validated",
        action="store_true",
        help="Show only validated variants.",
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
        keyword_id=args.keyword_id,
        validated_only=args.validated,
        min_similarity=args.min_similarity,
        limit=args.limit,
    )

    if not variants:
        print("No variants found matching criteria.")
        return 0

    print(f"Found {len(variants)} variant(s):\n")
    for variant in variants:
        print(f"  Variant: {variant.get('variant_term', '')}")
        print(f"    Keyword ID: {variant.get('keyword_id', '')}")
        print(f"    Similarity: {variant.get('similarity_score', '')}")
        print(f"    Validated: {variant.get('validated', '')}")
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
