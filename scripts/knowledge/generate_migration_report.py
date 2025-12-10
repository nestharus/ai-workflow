"""Generate YML migration review reports from comparison data.

This module generates YAML review reports for migration items that require human
review. It queries comparison CSV files using DuckDB, excludes resolved items
and identical matches, computes text similarity scores using difflib, and outputs
structured YAML reports to `.knowledge/reports/`.

Usage:
    uv run knowledge.generate-migration-report [--pattern <name>] [--knowledge-path <path>]

Args:
    --pattern: Filter by pattern name (e.g., api-patterns) (optional).
    --knowledge-path: Base knowledge directory, relative to REPO_ROOT (default: .knowledge).
"""

from __future__ import annotations

import argparse
import difflib
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

import duckdb
import yaml

from scripts.dev.utils import REPO_ROOT, utc_timestamp


class ReviewItem(TypedDict):
    """A review item for migration reports.

    Attributes:
        element_id: YAML element identifier.
        source_file: Relative path to the source file.
        source_text: Text content from the source file.
        split_file: Relative path to the split/target file.
        target_text: Text content from the target file.
        text_similarity_score: Similarity score between 0.0 and 1.0.
        requires_review: Whether this item requires human review.
        origin_type: Origin type (original only; split_only/orphan are excluded).
    """

    element_id: str
    source_file: str
    source_text: str
    split_file: str
    target_text: str
    text_similarity_score: float
    requires_review: bool
    origin_type: str


def compute_text_similarity(text1: str, text2: str) -> float:
    """Compute text similarity score using SequenceMatcher.

    Args:
        text1: First text to compare.
        text2: Second text to compare.

    Returns:
        Similarity score between 0.0 (no match) and 1.0 (identical).
    """
    return difflib.SequenceMatcher(None, text1.strip(), text2.strip()).ratio()


def _get_display_path(file_path: Path) -> str:
    """Get a display-friendly path, relative to REPO_ROOT if possible.

    Args:
        file_path: Absolute path to format.

    Returns:
        Path string relative to REPO_ROOT, or absolute path if outside repo.
    """
    try:
        return file_path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return file_path.as_posix()


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


def query_non_identical_items(
    knowledge_path: Path,
    pattern: str | None = None,
) -> dict[str, list[ReviewItem]]:
    """Query comparison items excluding resolved and identical matches.

    Args:
        knowledge_path: Base knowledge directory path.
        pattern: Optional pattern name to filter by.

    Returns:
        Dictionary mapping pattern names to lists of ReviewItem dicts.

    Raises:
        FileNotFoundError: If no comparison CSV files are found.
        duckdb.Error: If the query fails.
    """
    csv_paths = get_comparison_csv_paths(knowledge_path, pattern)
    if not csv_paths:
        msg = f"No comparison CSV files found in {knowledge_path / 'comparisons'}"
        raise FileNotFoundError(msg)

    resolutions_path = knowledge_path / "resolutions" / "resolved.csv"
    results_by_pattern: dict[str, list[ReviewItem]] = {}

    for csv_path in csv_paths:
        pattern_name = csv_path.stem
        params: list[str | Path] = [str(csv_path)]

        comparisons_cte = "SELECT * FROM read_csv_auto(?, ALL_VARCHAR=TRUE)"

        if resolutions_path.exists():
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
                WHERE r.id IS NULL
            """
        else:
            query = f"""
                WITH comparisons AS ({comparisons_cte})
                SELECT c.*
                FROM comparisons c
            """

        result = duckdb.execute(query, params)
        rows = result.fetchall()
        columns = [desc[0] for desc in result.description]

        col_idx = {col: i for i, col in enumerate(columns)}

        items: list[ReviewItem] = []
        for row in rows:
            origin_type = str(row[col_idx.get("origin_type", 2)] or "")

            # Only include rows with origin_type "original" to ensure meaningful
            # source-target comparisons. Skip split_only/orphan rows which lack
            # proper paired text content.
            if origin_type != "original":
                continue

            original_text = str(row[col_idx.get("original_text", 3)] or "")
            target_text = str(row[col_idx.get("split_text", 5)] or "")

            if original_text.strip() == target_text.strip():
                continue

            similarity_score = compute_text_similarity(original_text, target_text)

            item = ReviewItem(
                element_id=str(row[col_idx.get("id", 1)] or ""),
                source_file=str(row[col_idx.get("source_file", 0)] or ""),
                source_text=original_text,
                split_file=str(row[col_idx.get("split_file", 4)] or ""),
                target_text=target_text,
                text_similarity_score=round(similarity_score, 4),
                requires_review=similarity_score < 1.0,
                origin_type=origin_type,
            )
            items.append(item)

        if items:
            results_by_pattern[pattern_name] = items

    return results_by_pattern


def generate_yaml_report(
    items: list[ReviewItem],
    pattern: str,
    output_path: Path,
) -> None:
    """Generate a YAML review report file.

    Args:
        items: List of ReviewItem dicts to include in the report.
        pattern: Pattern name for the report.
        output_path: Path to write the YAML report.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "pattern": pattern,
        "generated_at": utc_timestamp(),
        "total_items": len(items),
        "items": items,
    }

    with output_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(report, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for migration report generation.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Generate YML migration review reports from comparison data.",
    )
    parser.add_argument(
        "--pattern",
        help="Pattern name to generate report for (e.g., api-patterns).",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        help="Base knowledge directory, relative to REPO_ROOT or absolute (default: .knowledge).",
    )
    return parser.parse_args(argv)


def main() -> int:
    """Generate migration review reports.

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
        results_by_pattern = query_non_identical_items(
            knowledge_path=knowledge_path,
            pattern=args.pattern,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except duckdb.Error as exc:
        print(f"Error executing query: {exc}", file=sys.stderr)
        return 1

    if not results_by_pattern:
        print("No items requiring review found.")
        return 0

    reports_dir = knowledge_path / "reports"
    generated_reports: list[str] = []

    for pattern_name, items in results_by_pattern.items():
        output_path = reports_dir / f"{pattern_name}-review.yml"
        generate_yaml_report(items, pattern_name, output_path)
        display_path = _get_display_path(output_path)
        generated_reports.append(display_path)
        print(f"Generated: {display_path} ({len(items)} items)")

    print(f"\n{len(generated_reports)} report(s) generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
