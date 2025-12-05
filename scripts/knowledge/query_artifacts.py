r"""CLI script for querying artifact manifests.

This script provides commands for querying and filtering artifact manifests
stored in `.knowledge/artifacts/`.

Usage:
    uv run knowledge.query-artifacts --artifact-kind 'diagram/*'
    uv run knowledge.query-artifacts --source-file docs/architecture/event-flow.yml \\
        --show-validation
    uv run knowledge.query-artifacts --stats
    uv run knowledge.query-artifacts --artifact-id abc123 --output-format yaml

Features:
    - Filter by artifact_id, artifact_kind pattern, source_file
    - Filter by V1 participation rule
    - Multiple output formats: json, yaml, csv, table
    - Show contributors and validation status
    - Aggregate statistics

V1 Participation Rule:
    Per fact_redesign.md lines 36-42, only artifacts with modality='text' AND
    extraction_mode='full' participate. Use --no-v1-only to include all.

See Also:
    - knowledge.detect-artifacts: Detect artifacts from YAML files
    - knowledge.validate-artifact-kinds: Validate artifact registry
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
from typing import Any

import yaml

from scripts.dev.utils import REPO_ROOT
from scripts.knowledge.artifact_manager import (
    ArtifactManifest,
    list_artifact_manifests,
)

# Module-level logger
_logger = logging.getLogger(__name__)

# Default artifacts directory
DEFAULT_ARTIFACTS_DIR = REPO_ROOT / ".knowledge" / "artifacts"


def _filter_manifests(
    manifests: list[ArtifactManifest],
    artifact_id: str | None = None,
    artifact_kind: str | None = None,
    source_file: str | None = None,
) -> list[ArtifactManifest]:
    """Filter manifests by criteria.

    Args:
        manifests: List of manifests to filter.
        artifact_id: Filter by exact artifact_id (prefix match supported).
        artifact_kind: Filter by artifact_kind pattern (wildcards supported).
        source_file: Filter by source_file path.

    Returns:
        Filtered list of manifests.
    """
    result = manifests

    if artifact_id:
        # Support prefix matching for artifact_id
        result = [m for m in result if m["artifact_id"].startswith(artifact_id)]

    if artifact_kind:
        # Support wildcard patterns for artifact_kind
        result = [m for m in result if fnmatch.fnmatch(m["artifact_kind"], artifact_kind)]

    if source_file:
        # Exact match for source_file
        result = [m for m in result if m["source"]["source_file"] == source_file]

    return result


def _format_table(
    manifests: list[ArtifactManifest],
    show_contributors: bool = False,
    show_validation: bool = False,
) -> str:
    """Format manifests as a table.

    Args:
        manifests: List of manifests to format.
        show_contributors: Include contributor count in output.
        show_validation: Include validation status in output.

    Returns:
        Formatted table string.
    """
    if not manifests:
        return "No artifacts found."

    lines: list[str] = []

    # Define columns
    columns = [
        ("ID", 12),
        ("Kind", 25),
        ("Source File", 40),
        ("Element ID", 25),
        ("Field Path", 20),
    ]

    if show_contributors:
        columns.append(("Contributors", 12))

    if show_validation:
        columns.append(("Passed", 8))

    # Header
    header = "  ".join(f"{name:<{width}}" for name, width in columns)
    lines.append(header)
    lines.append("-" * len(header))

    # Rows
    for m in manifests:
        row_values = [
            m["artifact_id"][:12],
            m["artifact_kind"][:25],
            m["source"]["source_file"][:40],
            m["source"]["source_element_id"][:25],
            m["source"]["field_path"][:20],
        ]

        if show_contributors:
            structural = len(m.get("contributors", {}).get("structural", []))
            semantic = len(m.get("contributors", {}).get("semantic", []))
            row_values.append(f"{structural}s/{semantic}m")

        if show_validation:
            validation = m.get("rendered", {}).get("validation", {})
            passed = validation.get("passed", "")
            if passed == "true":
                row_values.append("yes")
            elif passed == "false":
                row_values.append("no")
            else:
                row_values.append("-")

        row = "  ".join(
            f"{val:<{width}}" for val, (_, width) in zip(row_values, columns, strict=False)
        )
        lines.append(row)

    return "\n".join(lines)


def _format_json(
    manifests: list[ArtifactManifest],
    show_contributors: bool = False,
    show_validation: bool = False,
) -> str:
    """Format manifests as JSON.

    Args:
        manifests: List of manifests to format.
        show_contributors: Include contributors in output.
        show_validation: Include validation in output.

    Returns:
        Formatted JSON string.
    """
    output: list[dict] = []
    for m in manifests:
        item: dict = dict(m)
        if not show_contributors:
            item.pop("contributors", None)
        if not show_validation and "rendered" in item:
            item["rendered"].pop("validation", None)
        output.append(item)
    return json.dumps(output, indent=2)


def _format_yaml(
    manifests: list[ArtifactManifest],
    show_contributors: bool = False,
    show_validation: bool = False,
) -> str:
    """Format manifests as YAML.

    Args:
        manifests: List of manifests to format.
        show_contributors: Include contributors in output.
        show_validation: Include validation in output.

    Returns:
        Formatted YAML string.
    """
    output: list[dict] = []
    for m in manifests:
        item: dict = dict(m)
        if not show_contributors:
            item.pop("contributors", None)
        if not show_validation and "rendered" in item:
            item["rendered"].pop("validation", None)
        output.append(item)
    return yaml.safe_dump(output, default_flow_style=False)


def _format_csv(
    manifests: list[ArtifactManifest],
    show_contributors: bool = False,
    show_validation: bool = False,
) -> str:
    """Format manifests as CSV.

    Args:
        manifests: List of manifests to format.
        show_contributors: Include contributor counts in output.
        show_validation: Include validation status in output.

    Returns:
        Formatted CSV string.
    """
    if not manifests:
        return ""

    fieldnames = [
        "artifact_id",
        "artifact_kind",
        "artifact_format",
        "source_file",
        "source_element_id",
        "field_path",
        "render_plan_id",
        "modality",
        "extraction_mode",
    ]

    if show_contributors:
        fieldnames.extend(["structural_count", "semantic_count"])

    if show_validation:
        fieldnames.extend(["validation_passed", "validation_similarity"])

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()

    for m in manifests:
        row = {
            "artifact_id": m["artifact_id"],
            "artifact_kind": m["artifact_kind"],
            "artifact_format": m["artifact_format"],
            "source_file": m["source"]["source_file"],
            "source_element_id": m["source"]["source_element_id"],
            "field_path": m["source"]["field_path"],
            "render_plan_id": m["render_plan_id"],
            "modality": m.get("modality", "text"),
            "extraction_mode": m.get("extraction_mode", "full"),
        }

        if show_contributors:
            contributors = m.get("contributors", {})
            row["structural_count"] = str(len(contributors.get("structural", [])))
            row["semantic_count"] = str(len(contributors.get("semantic", [])))

        if show_validation:
            validation = m.get("rendered", {}).get("validation", {})
            row["validation_passed"] = validation.get("passed", "")
            row["validation_similarity"] = validation.get("similarity", "")

        writer.writerow(row)

    return buffer.getvalue()


def _compute_stats(manifests: list[ArtifactManifest]) -> dict[str, Any]:
    """Compute aggregate statistics from manifests.

    Args:
        manifests: List of manifests.

    Returns:
        Dictionary of statistics.
    """
    stats: dict[str, Any] = {
        "total": len(manifests),
        "by_kind": {},
        "by_source_file": {},
        "by_modality": {},
        "by_extraction_mode": {},
        "validation": {
            "passed": 0,
            "failed": 0,
            "not_validated": 0,
        },
    }

    for m in manifests:
        # By kind
        kind = m["artifact_kind"]
        stats["by_kind"][kind] = stats["by_kind"].get(kind, 0) + 1

        # By source file
        source = m["source"]["source_file"]
        stats["by_source_file"][source] = stats["by_source_file"].get(source, 0) + 1

        # By modality
        modality = m.get("modality", "text")
        stats["by_modality"][modality] = stats["by_modality"].get(modality, 0) + 1

        # By extraction mode
        mode = m.get("extraction_mode", "full")
        stats["by_extraction_mode"][mode] = stats["by_extraction_mode"].get(mode, 0) + 1

        # Validation status
        validation = m.get("rendered", {}).get("validation", {})
        passed = validation.get("passed", "")
        if passed == "true":
            stats["validation"]["passed"] += 1
        elif passed == "false":
            stats["validation"]["failed"] += 1
        else:
            stats["validation"]["not_validated"] += 1

    return stats


def _format_stats(stats: dict) -> str:
    """Format statistics for display.

    Args:
        stats: Statistics dictionary.

    Returns:
        Formatted string.
    """
    lines: list[str] = []

    lines.append(f"Total artifacts: {stats['total']}")
    lines.append("")

    lines.append("By artifact kind:")
    for kind, count in sorted(stats["by_kind"].items()):
        lines.append(f"  {kind}: {count}")
    lines.append("")

    lines.append("By source file:")
    for source, count in sorted(stats["by_source_file"].items()):
        lines.append(f"  {source}: {count}")
    lines.append("")

    lines.append("By modality:")
    for modality, count in sorted(stats["by_modality"].items()):
        lines.append(f"  {modality}: {count}")
    lines.append("")

    lines.append("By extraction mode:")
    for mode, count in sorted(stats["by_extraction_mode"].items()):
        lines.append(f"  {mode}: {count}")
    lines.append("")

    lines.append("Validation status:")
    lines.append(f"  passed: {stats['validation']['passed']}")
    lines.append(f"  failed: {stats['validation']['failed']}")
    lines.append(f"  not validated: {stats['validation']['not_validated']}")

    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Query artifact manifests.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    uv run knowledge.query-artifacts --artifact-kind 'diagram/*'
    uv run knowledge.query-artifacts --source-file docs/architecture/event-flow.yml \\
        --show-validation
    uv run knowledge.query-artifacts --stats
    uv run knowledge.query-artifacts --artifact-id abc123 --output-format yaml
        """,
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=DEFAULT_ARTIFACTS_DIR,
        help="Directory containing artifact manifests (default: .knowledge/artifacts).",
    )
    parser.add_argument(
        "--artifact-id",
        help="Filter by artifact_id (prefix match supported).",
    )
    parser.add_argument(
        "--artifact-kind",
        help="Filter by artifact_kind pattern (wildcards supported, e.g., 'diagram/*').",
    )
    parser.add_argument(
        "--source-file",
        help="Filter by source file path.",
    )
    parser.add_argument(
        "--v1-only",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Filter by V1 participation rule (modality=text AND extraction_mode=full).",
    )
    parser.add_argument(
        "--output-format",
        choices=["json", "yaml", "csv", "table"],
        default="table",
        help="Output format (default: table).",
    )
    parser.add_argument(
        "--show-contributors",
        action="store_true",
        help="Include contributor information in output.",
    )
    parser.add_argument(
        "--show-validation",
        action="store_true",
        help="Include validation status in output.",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show aggregate statistics instead of listing manifests.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Main entry point for artifact query CLI.

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

    # Check artifacts directory exists
    if not args.artifacts_dir.exists():
        print(f"Artifacts directory not found: {args.artifacts_dir}", file=sys.stderr)
        return 1

    # Load manifests
    try:
        manifests = list_artifact_manifests(args.artifacts_dir, filter_v1_only=args.v1_only)
    except Exception:
        _logger.exception("Failed to load manifests")
        return 1

    # Apply filters
    manifests = _filter_manifests(
        manifests,
        artifact_id=args.artifact_id,
        artifact_kind=args.artifact_kind,
        source_file=args.source_file,
    )

    # Show stats or listing
    if args.stats:
        stats = _compute_stats(manifests)
        print(_format_stats(stats))
    else:
        if args.output_format == "table":
            print(
                _format_table(
                    manifests,
                    show_contributors=args.show_contributors,
                    show_validation=args.show_validation,
                )
            )
        elif args.output_format == "json":
            print(
                _format_json(
                    manifests,
                    show_contributors=args.show_contributors,
                    show_validation=args.show_validation,
                )
            )
        elif args.output_format == "yaml":
            print(
                _format_yaml(
                    manifests,
                    show_contributors=args.show_contributors,
                    show_validation=args.show_validation,
                )
            )
        elif args.output_format == "csv":
            print(
                _format_csv(
                    manifests,
                    show_contributors=args.show_contributors,
                    show_validation=args.show_validation,
                )
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
