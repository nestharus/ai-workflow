"""Validate keyword variant candidates.

This module provides functionality for validating keyword variant candidates,
marking them as confirmed variants or rejecting false positives.

Usage:
    # Validate a variant
    uv run validate-variant --id <variant_id> --accept

    # Reject a variant
    uv run validate-variant --id <variant_id> --reject

    # Mark as canonical form
    uv run validate-variant --id <variant_id> --accept --canonical

Args:
    --id: Variant ID to validate.
    --accept: Accept the variant as valid.
    --reject: Reject the variant as invalid.
    --canonical: Mark this variant as the canonical form.
    --knowledge-path: Base knowledge directory (default: .knowledge).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import duckdb

from scripts.dev.utils import REPO_ROOT


def get_variant_by_id(csv_path: Path, variant_id: str) -> dict[str, str] | None:
    """Retrieve a variant record by ID.

    Args:
        csv_path: Path to the variants CSV file.
        variant_id: ID of the variant to retrieve.

    Returns:
        Variant record as dictionary, or None if not found.
    """
    if not csv_path.exists():
        return None

    query = """
        SELECT *
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE variant_id = ?
    """
    try:
        conn = duckdb.connect()
        result = conn.execute(query, [str(csv_path), variant_id])
        columns = [desc[0] for desc in result.description]
        row = result.fetchone()
        conn.close()
        if row:
            return dict(zip(columns, row, strict=False))
    except duckdb.Error:
        pass
    return None


def update_variant_validation(
    csv_path: Path,
    variant_id: str,
    *,
    validated: bool,
    is_canonical: bool = False,
) -> bool:
    """Update validation status for a variant.

    Args:
        csv_path: Path to the variants CSV file.
        variant_id: ID of the variant to update.
        validated: Whether the variant is validated.
        is_canonical: Whether this is the canonical form.

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
            SET validated = ?, is_canonical = ?
            WHERE variant_id = ?
            """,
            ["true" if validated else "false", "true" if is_canonical else "false", variant_id],
        )
        conn.execute(f"COPY variants TO '{csv_path}' (HEADER, DELIMITER ',')")
        conn.close()
        return True
    except duckdb.Error:
        return False


def delete_variant(csv_path: Path, variant_id: str) -> bool:
    """Delete a variant record (for rejections).

    Args:
        csv_path: Path to the variants CSV file.
        variant_id: ID of the variant to delete.

    Returns:
        True if deletion succeeded, False otherwise.
    """
    if not csv_path.exists():
        return False

    try:
        conn = duckdb.connect()
        conn.execute(f"""
            CREATE TABLE variants AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """)
        conn.execute("DELETE FROM variants WHERE variant_id = ?", [variant_id])
        conn.execute(f"COPY variants TO '{csv_path}' (HEADER, DELIMITER ',')")
        conn.close()
        return True
    except duckdb.Error:
        return False


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for variant validation.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Validate keyword variant candidates.",
    )
    parser.add_argument(
        "--id",
        dest="variant_id",
        required=True,
        help="Variant ID to validate.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--accept",
        action="store_true",
        help="Accept the variant as valid.",
    )
    group.add_argument(
        "--reject",
        action="store_true",
        help="Reject the variant as invalid.",
    )
    parser.add_argument(
        "--canonical",
        action="store_true",
        help="Mark this variant as the canonical form.",
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

    variant = get_variant_by_id(csv_path, args.variant_id)
    if not variant:
        print(f"Error: Variant with ID '{args.variant_id}' not found", file=sys.stderr)
        return 1

    if args.reject:
        if delete_variant(csv_path, args.variant_id):
            print(f"Rejected and removed variant '{args.variant_id}'")
            print(f"  Term: {variant.get('variant_term', '')}")
            return 0
        print("Error: Failed to delete variant", file=sys.stderr)
        return 1

    if args.accept:
        if update_variant_validation(
            csv_path,
            args.variant_id,
            validated=True,
            is_canonical=args.canonical,
        ):
            print(f"Validated variant '{args.variant_id}'")
            print(f"  Term: {variant.get('variant_term', '')}")
            print(f"  Canonical: {args.canonical}")
            return 0
        print("Error: Failed to update variant", file=sys.stderr)
        return 1

    return 0


def main() -> int:
    """Entry point for validate-variant command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_args()
    return validate_variant_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
