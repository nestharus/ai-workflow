"""Validate keyword variant pair candidates.

This module provides functionality for validating keyword variant pair candidates,
recording merge decisions with canonical form selection and reasoning.

Usage:
    # Validate a variant pair (merge decision)
    uv run knowledge.validate-variant --id <pair_id> --merge true \\
        --canonical "connection management" \\
        --reason "Component name vs concept; treat concept as canonical."

    # Reject a merge (keep keywords separate)
    uv run knowledge.validate-variant --id <pair_id> --merge false \\
        --canonical "" \\
        --reason "Distinct concepts: authentication verifies, authorization grants."

Args:
    --id: Pair ID to validate (required).
    --merge: Merge decision - "true" or "false" (required).
    --canonical: The chosen canonical form (required, empty string for no merge).
    --reason: Explanation for the merge decision (required).
    --knowledge-path: Base knowledge directory (default: .knowledge).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import duckdb

from scripts.dev.utils import REPO_ROOT


def get_variant_by_id(csv_path: Path, pair_id: str) -> dict[str, str] | None:
    """Retrieve a variant pair record by ID.

    Args:
        csv_path: Path to the variants CSV file.
        pair_id: ID of the pair to retrieve.

    Returns:
        Variant pair record as dictionary, or None if not found.
    """
    if not csv_path.exists():
        return None

    query = """
        SELECT *
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE pair_id = ?
    """
    try:
        conn = duckdb.connect()
        result = conn.execute(query, [str(csv_path), pair_id])
        columns = [desc[0] for desc in result.description]
        row = result.fetchone()
        conn.close()
        if row:
            # Convert None values to empty strings to preserve consistency with CSV format
            return {col: (val if val is not None else "") for col, val in zip(columns, row, strict=False)}
    except duckdb.Error:
        pass
    return None


def update_variant_validation(
    csv_path: Path,
    pair_id: str,
    *,
    merge: str,
    canonical: str,
    reason: str,
) -> bool:
    """Update validation status for a variant pair.

    Args:
        csv_path: Path to the variants CSV file.
        pair_id: ID of the pair to update.
        merge: Merge decision ("true" or "false").
        canonical: The chosen canonical form.
        reason: Explanation for the decision.

    Returns:
        True if update succeeded, False otherwise.
    """
    if not csv_path.exists():
        return False

    try:
        conn = duckdb.connect()
        conn.execute(f"""
            CREATE TABLE variants AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """)
        conn.execute(
            """
            UPDATE variants
            SET merge = ?, canonical = ?, reason = ?, validated = 'true'
            WHERE pair_id = ?
            """,
            [merge, canonical, reason, pair_id],
        )
        conn.execute(f"COPY variants TO '{csv_path}' (HEADER, DELIMITER ',')")
        conn.close()
    except duckdb.Error:
        return False
    else:
        return True


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for variant validation.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Validate keyword variant pair candidates.",
    )
    parser.add_argument(
        "--id",
        dest="pair_id",
        required=True,
        help="Pair ID to validate.",
    )
    parser.add_argument(
        "--merge",
        required=True,
        choices=["true", "false"],
        help="Merge decision: 'true' to merge, 'false' to keep separate.",
    )
    parser.add_argument(
        "--canonical",
        required=True,
        help="The chosen canonical form (empty string if not merging).",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Explanation for the merge decision.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def validate_variant_main(args: argparse.Namespace) -> int:
    """Run variant validation.

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

    variant = get_variant_by_id(csv_path, args.pair_id)
    if not variant:
        print(f"Error: Pair with ID '{args.pair_id}' not found", file=sys.stderr)
        return 1

    if update_variant_validation(
        csv_path,
        args.pair_id,
        merge=args.merge,
        canonical=args.canonical,
        reason=args.reason,
    ):
        keyword_a = variant.get("keyword_a", "")
        keyword_b = variant.get("keyword_b", "")
        print(f"Validated pair '{args.pair_id}'")
        print(f"  Keywords: '{keyword_a}' / '{keyword_b}'")
        print(f"  Merge: {args.merge}")
        if args.merge == "true":
            print(f"  Canonical: '{args.canonical}'")
        print(f"  Reason: {args.reason}")
        return 0

    print("Error: Failed to update variant pair", file=sys.stderr)
    return 1


def main() -> int:
    """Entry point for knowledge.validate-variant command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_args()
    return validate_variant_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
