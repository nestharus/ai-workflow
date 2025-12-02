"""Apply classified keywords back to YAML documentation files.

This module provides utilities for applying classified keywords to YAML
documentation files, adding keyword metadata to elements where the terms
were originally extracted.

Usage:
    # Apply all keywords to YAML files
    uv run apply-keywords-to-yaml

    # Apply keywords to specific directory
    uv run apply-keywords-to-yaml --target docs/architecture/

    # Dry run (show changes without applying)
    uv run apply-keywords-to-yaml --dry-run

Args:
    --target: Target directory for keyword application (default: docs/).
    --dry-run: Show changes without modifying files.
    --knowledge-path: Base knowledge directory (default: .knowledge).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import duckdb

from scripts.dev.utils import REPO_ROOT


def get_keywords_for_file(keywords_csv: Path, source_file: str) -> list[dict[str, str]]:
    """Get all keywords that originated from a specific source file.

    Args:
        keywords_csv: Path to the keywords CSV file.
        source_file: Source file path to filter by.

    Returns:
        List of keyword records for the source file.
    """
    if not keywords_csv.exists() or keywords_csv.stat().st_size == 0:
        return []

    query = """
        SELECT *
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE source_file = ?
    """
    try:
        conn = duckdb.connect()
        result = conn.execute(query, [str(keywords_csv), source_file])
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        conn.close()
        return [dict(zip(columns, row, strict=False)) for row in rows]
    except duckdb.Error:
        return []


def get_all_keywords(keywords_csv: Path) -> list[dict[str, str]]:
    """Get all classified keywords.

    Args:
        keywords_csv: Path to the keywords CSV file.

    Returns:
        List of all keyword records.
    """
    if not keywords_csv.exists() or keywords_csv.stat().st_size == 0:
        return []

    query = """
        SELECT *
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        ORDER BY category, subcategory, term
    """
    try:
        conn = duckdb.connect()
        result = conn.execute(query, [str(keywords_csv)])
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        conn.close()
        return [dict(zip(columns, row, strict=False)) for row in rows]
    except duckdb.Error:
        return []


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for keyword application.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Apply classified keywords to YAML documentation files.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("docs"),
        help="Target directory for keyword application (default: docs/).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Show changes without modifying files.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def apply_keywords_main(args: argparse.Namespace) -> int:
    """Run keyword application to YAML files.

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error.
    """
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    if args.target.is_absolute():
        target_path = args.target.resolve()
    else:
        target_path = (REPO_ROOT / args.target).resolve()

    keywords_csv = knowledge_path / "keywords" / "keywords.csv"

    if not keywords_csv.exists():
        print(f"Error: Keywords CSV not found: {keywords_csv}", file=sys.stderr)
        return 1

    if not target_path.exists():
        print(f"Error: Target directory not found: {target_path}", file=sys.stderr)
        return 1

    keywords = get_all_keywords(keywords_csv)
    if not keywords:
        print("No keywords found to apply.")
        return 0

    print(f"Found {len(keywords)} keyword(s) to apply")
    print(f"Target: {target_path}")
    if args.dry_run:
        print("(dry run - no changes will be made)")

    # Placeholder for actual application logic (Phase 3)
    print("Keyword application not yet implemented (Phase 3).")

    return 0


def main_apply() -> int:
    """Entry point for apply-keywords-to-yaml command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_args()
    return apply_keywords_main(args)


if __name__ == "__main__":
    raise SystemExit(main_apply())
