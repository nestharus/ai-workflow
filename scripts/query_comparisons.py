"""Query comparison CSV files using DuckDB with filtering and join capabilities.

This module provides CLI commands to filter and query comparison data stored in
`.knowledge/comparisons/`. Supports filtering by ID, origin type, source file,
split file, and can exclude already-resolved items by joining with the resolutions CSV.

Usage:
    uv run query-comparisons [--id <element_id>] [--origin-type <type>]
        [--source-file <path>] [--split-file <path>] [--exclude-resolved] [--pattern <name>]

Args:
    --id: Filter by element ID (optional).
    --origin-type: Filter by origin type (original, split_only, orphan) (optional).
    --source-file: Filter by source file path (optional).
    --split-file: Filter by split file path (optional).
    --exclude-resolved: Exclude already-resolved items (default: False).
    --knowledge-path: Base knowledge directory, relative to REPO_ROOT (default: .knowledge).
    --pattern: Pattern name to query (e.g., api-patterns) (optional).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import duckdb

from scripts.utils import REPO_ROOT

CSV_COLUMNS = ["source_file", "id", "origin_type", "original_text", "split_file", "split_text"]


def get_comparison_csv_paths(
    knowledge_path: Path,
    pattern: str | None = None,
) -> list[Path]:
    """Find comparison CSV files in the knowledge directory.

    Args:
        knowledge_path: Base knowledge directory path.
        pattern: Optional pattern name to filter by (e.g., 'api-patterns').

    Returns:
        List of paths to comparison CSV files.
    """
    comparisons_dir = knowledge_path / "comparisons"
    if not comparisons_dir.exists():
        return []

    if pattern:
        csv_path = comparisons_dir / f"{pattern}.csv"
        return [csv_path] if csv_path.exists() else []

    return sorted(comparisons_dir.glob("*.csv"))


def build_query(
    csv_paths: list[Path],
    element_id: str | None = None,
    origin_type: str | None = None,
    source_file: str | None = None,
    split_file: str | None = None,
    exclude_resolved: bool = False,
    resolutions_path: Path | None = None,
) -> tuple[str, list[str | Path]]:
    """Build a DuckDB SQL query based on provided filters.

    Args:
        csv_paths: List of paths to comparison CSV files.
        element_id: Optional element ID filter.
        origin_type: Optional origin type filter.
        source_file: Optional source file filter.
        split_file: Optional split file filter.
        exclude_resolved: Whether to exclude resolved items.
        resolutions_path: Path to resolutions CSV file.

    Returns:
        Tuple of (SQL query string, list of parameters).
    """
    params: list[str | Path] = []

    if len(csv_paths) == 1:
        comparisons_cte = "SELECT * FROM read_csv_auto(?, ALL_VARCHAR=TRUE)"
        params.append(str(csv_paths[0]))
    else:
        union_parts = ["SELECT * FROM read_csv_auto(?, ALL_VARCHAR=TRUE)" for _ in csv_paths]
        comparisons_cte = " UNION ALL ".join(union_parts)
        params.extend(str(p) for p in csv_paths)

    where_clauses: list[str] = []

    if element_id:
        where_clauses.append("c.id = ?")
        params.append(element_id)

    if origin_type:
        where_clauses.append("c.origin_type = ?")
        params.append(origin_type)

    if source_file:
        where_clauses.append("c.source_file = ?")
        params.append(source_file)

    if split_file:
        where_clauses.append("c.split_file = ?")
        params.append(split_file)

    if exclude_resolved and resolutions_path and resolutions_path.exists():
        resolutions_cte = """
            SELECT id, source_file, split_file
            FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        """
        params.append(str(resolutions_path))

        query = f"""
            WITH comparisons AS ({comparisons_cte}),
            resolutions AS ({resolutions_cte})
            SELECT c.*
            FROM comparisons c
            LEFT JOIN resolutions r
            ON c.id = r.id
            AND c.source_file = r.source_file
            AND c.split_file = r.split_file
        """
        where_clauses.append("r.id IS NULL")
    else:
        query = f"""
            WITH comparisons AS ({comparisons_cte})
            SELECT c.*
            FROM comparisons c
        """

    if where_clauses:
        query = f"SELECT * FROM ({query}) AS filtered WHERE {' AND '.join(where_clauses)}"

    return query, params


def format_results(rows: list[tuple[object, ...]], columns: list[str]) -> str:
    """Format query results as a readable table.

    Args:
        rows: List of result tuples.
        columns: List of column names.

    Returns:
        Formatted table string.
    """
    if not rows:
        return "No results found."

    col_widths = [len(col) for col in columns]
    for row in rows:
        for i, val in enumerate(row):
            val_str = str(val) if val is not None else ""
            val_len = min(len(val_str), 50)
            col_widths[i] = max(col_widths[i], val_len)

    header = " | ".join(col.ljust(col_widths[i]) for i, col in enumerate(columns))
    separator = "-+-".join("-" * col_widths[i] for i in range(len(columns)))

    lines = [header, separator]
    for row in rows:
        row_str = " | ".join(
            (str(val) if val is not None else "")[:50].ljust(col_widths[i])
            for i, val in enumerate(row)
        )
        lines.append(row_str)

    lines.append(f"\n{len(rows)} row(s) returned.")
    return "\n".join(lines)


def query_comparisons(
    knowledge_path: Path,
    pattern: str | None = None,
    element_id: str | None = None,
    origin_type: str | None = None,
    source_file: str | None = None,
    split_file: str | None = None,
    exclude_resolved: bool = False,
) -> tuple[list[tuple[object, ...]], list[str]]:
    """Query comparison CSV files with filters.

    Args:
        knowledge_path: Base knowledge directory path.
        pattern: Optional pattern name to filter by.
        element_id: Optional element ID filter.
        origin_type: Optional origin type filter.
        source_file: Optional source file filter.
        split_file: Optional split file filter.
        exclude_resolved: Whether to exclude resolved items.

    Returns:
        Tuple of (list of result rows, list of column names).

    Raises:
        FileNotFoundError: If no comparison CSV files are found.
        duckdb.Error: If the query fails.
    """
    csv_paths = get_comparison_csv_paths(knowledge_path, pattern)
    if not csv_paths:
        msg = f"No comparison CSV files found in {knowledge_path / 'comparisons'}"
        raise FileNotFoundError(msg)

    resolutions_path = knowledge_path / "resolutions" / "resolved.csv"

    query, params = build_query(
        csv_paths=csv_paths,
        element_id=element_id,
        origin_type=origin_type,
        source_file=source_file,
        split_file=split_file,
        exclude_resolved=exclude_resolved,
        resolutions_path=resolutions_path,
    )

    result = duckdb.execute(query, params)
    rows = result.fetchall()
    columns = [desc[0] for desc in result.description]

    return rows, columns


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for comparison querying.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Query comparison CSV files using DuckDB with filtering.",
    )
    parser.add_argument(
        "--id",
        dest="element_id",
        help="Filter by element ID.",
    )
    parser.add_argument(
        "--origin-type",
        choices=["original", "split_only", "orphan"],
        help="Filter by origin type.",
    )
    parser.add_argument(
        "--source-file",
        help="Filter by source file path.",
    )
    parser.add_argument(
        "--split-file",
        help="Filter by split file path.",
    )
    parser.add_argument(
        "--exclude-resolved",
        action="store_true",
        default=False,
        help="Exclude already-resolved items.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        help="Base knowledge directory, relative to REPO_ROOT or absolute (default: .knowledge).",
    )
    parser.add_argument(
        "--pattern",
        help="Pattern name to query (e.g., api-patterns).",
    )
    return parser.parse_args(argv)


def main() -> int:
    """Run comparison query and display results.

    Returns:
        0 on success, 1 on error.
    """
    args = parse_args()

    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    if not knowledge_path.exists():
        print(f"Error: Knowledge directory not found: {knowledge_path}", file=sys.stderr)
        return 1

    try:
        rows, columns = query_comparisons(
            knowledge_path=knowledge_path,
            pattern=args.pattern,
            element_id=args.element_id,
            origin_type=args.origin_type,
            source_file=args.source_file,
            split_file=args.split_file,
            exclude_resolved=args.exclude_resolved,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except duckdb.Error as exc:
        print(f"Error executing query: {exc}", file=sys.stderr)
        return 1

    output = format_results(rows, columns)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
