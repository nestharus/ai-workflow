"""CLI script for querying artifact validation results.

This script provides commands for querying and filtering validation results
stored in `.knowledge/artifacts/validations.csv`.

Usage:
    uv run knowledge.query-validations
    uv run knowledge.query-validations --artifact-id abc123
    uv run knowledge.query-validations --passed false
    uv run knowledge.query-validations --min-similarity 0.9
    uv run knowledge.query-validations --stats
    uv run knowledge.query-validations --output-format json

Features:
    - Filter by artifact_id, artifact_kind, source_file
    - Filter by passed status and minimum similarity score
    - Multiple output formats: json, yaml, csv, table
    - Aggregate statistics

See Also:
    - knowledge.render-artifacts: Render artifacts and generate validations
    - knowledge.query-artifacts: Query artifact manifests
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import logging
import sys
from io import StringIO
from pathlib import Path

import yaml

from scripts.dev.utils import REPO_ROOT
from scripts.knowledge.artifact_validator import (
    ValidationResult,
    load_validation_results,
)

# Module-level logger
_logger = logging.getLogger(__name__)

# Default paths
DEFAULT_VALIDATIONS_CSV = REPO_ROOT / ".knowledge" / "artifacts" / "validations.csv"


def _filter_validations(
    validations: list[ValidationResult],
    artifact_id: str | None = None,
    artifact_kind: str | None = None,
    source_file: str | None = None,
    passed: bool | None = None,
    min_similarity: float | None = None,
) -> list[ValidationResult]:
    """Filter validations by criteria.

    Args:
        validations: List of validation results.
        artifact_id: Filter by artifact_id (prefix match).
        artifact_kind: Filter by artifact_kind pattern (wildcards supported).
        source_file: Filter by source file path.
        passed: Filter by passed status.
        min_similarity: Filter by minimum similarity score.

    Returns:
        Filtered list of validation results.
    """
    result = validations

    if artifact_id:
        result = [v for v in result if v.artifact_id.startswith(artifact_id)]

    if artifact_kind:
        # Note: render_plan_id often contains artifact_kind information
        result = [v for v in result if fnmatch.fnmatch(v.render_plan_id, artifact_kind)]

    if source_file:
        result = [v for v in result if v.source_file == source_file]

    if passed is not None:
        result = [v for v in result if v.passed == passed]

    if min_similarity is not None:
        result = [v for v in result if v.similarity_score >= min_similarity]

    return result


def _format_table(validations: list[ValidationResult]) -> str:
    """Format validations as a table.

    Args:
        validations: List of validation results.

    Returns:
        Formatted table string.
    """
    if not validations:
        return "No validation results found."

    lines: list[str] = []

    # Define columns
    columns = [
        ("Validation ID", 12),
        ("Artifact ID", 12),
        ("Source File", 40),
        ("Passed", 8),
        ("Similarity", 10),
        ("Validated At", 20),
    ]

    # Header
    header = "  ".join(f"{name:<{width}}" for name, width in columns)
    lines.append(header)
    lines.append("-" * len(header))

    # Rows
    for v in validations:
        row_values = [
            v.validation_id[:12],
            v.artifact_id[:12],
            v.source_file[:40] if v.source_file else "-",
            "yes" if v.passed else "no",
            f"{v.similarity_score:.4f}",
            v.validated_at[:20] if v.validated_at else "-",
        ]

        row = "  ".join(
            f"{val:<{width}}" for val, (_, width) in zip(row_values, columns, strict=False)
        )
        lines.append(row)

    return "\n".join(lines)


def _format_json(validations: list[ValidationResult]) -> str:
    """Format validations as JSON.

    Args:
        validations: List of validation results.

    Returns:
        Formatted JSON string.
    """
    output = []
    for v in validations:
        output.append(
            {
                "validation_id": v.validation_id,
                "artifact_id": v.artifact_id,
                "source_file": v.source_file,
                "source_element_id": v.source_element_id,
                "field_path": v.field_path,
                "render_plan_id": v.render_plan_id,
                "projection_version": v.projection_version,
                "source_hash": v.source_hash,
                "rendered_hash": v.rendered_hash,
                "similarity_score": v.similarity_score,
                "passed": v.passed,
                "mismatch_summary": v.mismatch_summary,
                "validated_at": v.validated_at,
            }
        )
    return json.dumps(output, indent=2)


def _format_yaml(validations: list[ValidationResult]) -> str:
    """Format validations as YAML.

    Args:
        validations: List of validation results.

    Returns:
        Formatted YAML string.
    """
    output = []
    for v in validations:
        output.append(
            {
                "validation_id": v.validation_id,
                "artifact_id": v.artifact_id,
                "source_file": v.source_file,
                "source_element_id": v.source_element_id,
                "field_path": v.field_path,
                "render_plan_id": v.render_plan_id,
                "projection_version": v.projection_version,
                "source_hash": v.source_hash,
                "rendered_hash": v.rendered_hash,
                "similarity_score": v.similarity_score,
                "passed": v.passed,
                "mismatch_summary": v.mismatch_summary,
                "validated_at": v.validated_at,
            }
        )
    return yaml.safe_dump(output, default_flow_style=False)


def _format_csv(validations: list[ValidationResult]) -> str:
    """Format validations as CSV.

    Args:
        validations: List of validation results.

    Returns:
        Formatted CSV string.
    """
    if not validations:
        return ""

    fieldnames = [
        "validation_id",
        "artifact_id",
        "source_file",
        "source_element_id",
        "field_path",
        "render_plan_id",
        "projection_version",
        "source_hash",
        "rendered_hash",
        "similarity_score",
        "passed",
        "mismatch_summary",
        "validated_at",
    ]

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()

    for v in validations:
        writer.writerow(
            {
                "validation_id": v.validation_id,
                "artifact_id": v.artifact_id,
                "source_file": v.source_file,
                "source_element_id": v.source_element_id,
                "field_path": v.field_path,
                "render_plan_id": v.render_plan_id,
                "projection_version": v.projection_version,
                "source_hash": v.source_hash,
                "rendered_hash": v.rendered_hash,
                "similarity_score": f"{v.similarity_score:.4f}",
                "passed": str(v.passed).lower(),
                "mismatch_summary": v.mismatch_summary,
                "validated_at": v.validated_at,
            }
        )

    return buffer.getvalue()


def _compute_stats(validations: list[ValidationResult]) -> dict:
    """Compute aggregate statistics from validations.

    Args:
        validations: List of validation results.

    Returns:
        Dictionary of statistics.
    """
    stats: dict = {
        "total": len(validations),
        "passed": 0,
        "failed": 0,
        "avg_similarity": 0.0,
        "by_render_plan": {},
        "by_source_file": {},
        "similarity_distribution": {
            "0.0-0.5": 0,
            "0.5-0.8": 0,
            "0.8-0.9": 0,
            "0.9-1.0": 0,
            "1.0": 0,
        },
    }

    if not validations:
        return stats

    total_similarity = 0.0

    for v in validations:
        # Passed/failed counts
        if v.passed:
            stats["passed"] += 1
        else:
            stats["failed"] += 1

        # Similarity
        total_similarity += v.similarity_score

        # Similarity distribution
        if v.similarity_score == 1.0:
            stats["similarity_distribution"]["1.0"] += 1
        elif v.similarity_score >= 0.9:
            stats["similarity_distribution"]["0.9-1.0"] += 1
        elif v.similarity_score >= 0.8:
            stats["similarity_distribution"]["0.8-0.9"] += 1
        elif v.similarity_score >= 0.5:
            stats["similarity_distribution"]["0.5-0.8"] += 1
        else:
            stats["similarity_distribution"]["0.0-0.5"] += 1

        # By render plan
        plan = v.render_plan_id or "unknown"
        if plan not in stats["by_render_plan"]:
            stats["by_render_plan"][plan] = {"count": 0, "passed": 0, "total_similarity": 0.0}
        stats["by_render_plan"][plan]["count"] += 1
        if v.passed:
            stats["by_render_plan"][plan]["passed"] += 1
        stats["by_render_plan"][plan]["total_similarity"] += v.similarity_score

        # By source file
        source = v.source_file or "unknown"
        if source not in stats["by_source_file"]:
            stats["by_source_file"][source] = {"count": 0, "passed": 0}
        stats["by_source_file"][source]["count"] += 1
        if v.passed:
            stats["by_source_file"][source]["passed"] += 1

    # Average similarity
    stats["avg_similarity"] = total_similarity / len(validations)

    # Compute average similarity per render plan
    for plan_stats in stats["by_render_plan"].values():
        plan_stats["avg_similarity"] = plan_stats["total_similarity"] / plan_stats["count"]
        del plan_stats["total_similarity"]

    return stats


def _format_stats(stats: dict) -> str:
    """Format statistics for display.

    Args:
        stats: Statistics dictionary.

    Returns:
        Formatted string.
    """
    lines: list[str] = []

    lines.append(f"Total validations: {stats['total']}")
    lines.append(f"Passed: {stats['passed']}")
    lines.append(f"Failed: {stats['failed']}")
    if stats["total"] > 0:
        pass_rate = stats["passed"] / stats["total"] * 100
        lines.append(f"Pass rate: {pass_rate:.1f}%")
    lines.append(f"Average similarity: {stats['avg_similarity']:.4f}")
    lines.append("")

    lines.append("Similarity distribution:")
    for bucket, count in stats["similarity_distribution"].items():
        lines.append(f"  {bucket}: {count}")
    lines.append("")

    if stats["by_render_plan"]:
        lines.append("By render plan:")
        for plan, plan_stats in sorted(stats["by_render_plan"].items()):
            lines.append(
                f"  {plan}: {plan_stats['count']} "
                f"(passed: {plan_stats['passed']}, avg sim: {plan_stats['avg_similarity']:.4f})"
            )
        lines.append("")

    if stats["by_source_file"]:
        lines.append("By source file:")
        for source, source_stats in sorted(stats["by_source_file"].items()):
            pass_rate = source_stats["passed"] / source_stats["count"] * 100
            lines.append(f"  {source}: {source_stats['count']} (pass rate: {pass_rate:.1f}%)")

    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Query artifact validation results.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    uv run knowledge.query-validations
    uv run knowledge.query-validations --artifact-id abc123
    uv run knowledge.query-validations --passed false
    uv run knowledge.query-validations --min-similarity 0.9
    uv run knowledge.query-validations --stats
    uv run knowledge.query-validations --output-format json
        """,
    )
    parser.add_argument(
        "--validations-csv",
        type=Path,
        default=DEFAULT_VALIDATIONS_CSV,
        help="Path to validations CSV file (default: .knowledge/artifacts/validations.csv).",
    )
    parser.add_argument(
        "--artifact-id",
        help="Filter by artifact_id (prefix match supported).",
    )
    parser.add_argument(
        "--artifact-kind",
        help="Filter by artifact_kind pattern in render_plan_id (wildcards supported).",
    )
    parser.add_argument(
        "--source-file",
        help="Filter by source file path.",
    )
    parser.add_argument(
        "--passed",
        choices=["true", "false"],
        help="Filter by passed status.",
    )
    parser.add_argument(
        "--min-similarity",
        type=float,
        help="Filter by minimum similarity score (0.0-1.0).",
    )
    parser.add_argument(
        "--output-format",
        choices=["json", "yaml", "csv", "table"],
        default="table",
        help="Output format (default: table).",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show aggregate statistics instead of listing results.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Main entry point for validation query CLI.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        0 on success, 1 on error.
    """
    args = parse_args(argv)

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    # Check validations file exists
    if not args.validations_csv.exists():
        print("No validation results found.")
        return 0

    # Load validations
    try:
        validations = load_validation_results(args.validations_csv)
    except Exception as exc:
        _logger.error("Failed to load validations: %s", exc)
        return 1

    if not validations:
        print("No validation results found.")
        return 0

    # Parse passed filter
    passed_filter = None
    if args.passed:
        passed_filter = args.passed == "true"

    # Apply filters
    validations = _filter_validations(
        validations,
        artifact_id=args.artifact_id,
        artifact_kind=args.artifact_kind,
        source_file=args.source_file,
        passed=passed_filter,
        min_similarity=args.min_similarity,
    )

    # Show stats or listing
    if args.stats:
        stats = _compute_stats(validations)
        print(_format_stats(stats))
    else:
        if args.output_format == "table":
            print(_format_table(validations))
        elif args.output_format == "json":
            print(_format_json(validations))
        elif args.output_format == "yaml":
            print(_format_yaml(validations))
        elif args.output_format == "csv":
            print(_format_csv(validations))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
