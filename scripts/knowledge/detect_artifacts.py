r"""CLI script for artifact detection from YAML documentation files.

This script implements artifact lifecycle step 1 per fact_redesign.md lines 561-569:
detect artifact roots and assign artifact_kind, artifact_format, render_engine,
and render_plan_id.

Usage:
    uv run knowledge.detect-artifacts --source-files 'docs/development/**/*.yml'
    uv run knowledge.detect-artifacts --source-files docs/architecture/event-flow.yml \\
        --output-format json
    uv run knowledge.detect-artifacts --source-files docs/**/*.yml --no-create-manifests

Workflow:
    1. For each source file, call extract_field_facts to get FieldFacts
    2. Call detect_artifacts_from_field_facts to detect artifacts
    3. Optionally create manifest files in artifacts_dir
    4. Output summary and optionally detailed artifact list

V1 Participation Rule:
    Per fact_redesign.md lines 36-42, only artifacts with modality='text' AND
    extraction_mode='full' participate. Use --no-v1-only to include all.

See Also:
    - knowledge.validate-artifact-kinds: Validate artifact registry integrity
    - knowledge.query-artifacts: Query artifact manifests
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

import yaml

from scripts.dev.utils import REPO_ROOT
from scripts.knowledge.artifact_manager import create_artifact_manifest
from scripts.knowledge.compare_yaml_docs import (
    Artifact,
    detect_artifacts_from_field_facts,
    extract_field_facts,
    parse_yaml_file,
)

# Module-level logger
_logger = logging.getLogger(__name__)

# Default artifacts directory
DEFAULT_ARTIFACTS_DIR = REPO_ROOT / ".knowledge" / "artifacts"


def _expand_source_files(patterns: list[str]) -> list[Path]:
    """Expand glob patterns to list of existing YAML files.

    Args:
        patterns: List of file paths or glob patterns.

    Returns:
        Sorted list of unique file paths.
    """
    files: set[Path] = set()
    for pattern in patterns:
        # Check if it's a glob pattern
        if "*" in pattern or "?" in pattern:
            # Use glob to expand
            matches = glob.glob(pattern, recursive=True)
            for match in matches:
                path = Path(match)
                if path.is_file() and path.suffix in (".yml", ".yaml"):
                    files.add(path.resolve())
        else:
            # Direct file path
            path = Path(pattern)
            if not path.is_absolute():
                path = REPO_ROOT / path
            if path.is_file():
                files.add(path.resolve())
            else:
                _logger.warning("File not found: %s", pattern)

    return sorted(files)


def _get_relative_path(path: Path) -> str:
    """Get the relative path from REPO_ROOT.

    Args:
        path: Absolute path.

    Returns:
        Relative path as POSIX string.
    """
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _detect_from_file(
    file_path: Path,
    artifacts_dir: Path,
    create_manifests: bool,
    v1_only: bool,
) -> tuple[list[Artifact], int, int]:
    """Detect artifacts from a single YAML file.

    Args:
        file_path: Path to the YAML file.
        artifacts_dir: Directory for artifact manifests.
        create_manifests: Whether to create manifest files.
        v1_only: Whether to apply V1 participation rule.

    Returns:
        Tuple of (detected artifacts, manifests created count, skipped by V1 count).
    """
    relative_path = _get_relative_path(file_path)

    try:
        data = parse_yaml_file(file_path)
    except Exception as exc:
        _logger.warning("Failed to parse %s: %s", relative_path, exc)
        return [], 0, 0

    # Extract FieldFacts
    field_facts = extract_field_facts(data, source_file=relative_path)

    # Count artifact_root FieldFacts before V1 filtering
    total_roots = sum(
        1 for facts in field_facts.values() for fact in facts if fact.role == "artifact_root"
    )

    # Detect artifacts (applies V1 filter internally)
    artifacts = detect_artifacts_from_field_facts(
        field_facts,
        source_file=relative_path,
        v1_only=v1_only,
    )

    skipped_by_v1 = total_roots - len(artifacts) if v1_only else 0

    # Optionally create manifests
    manifests_created = 0
    if create_manifests and artifacts:
        for artifact in artifacts:
            try:
                create_artifact_manifest(artifact, artifacts_dir)
                manifests_created += 1
                _logger.info(
                    "Created manifest for artifact: %s (%s) at %s",
                    artifact.artifact_id[:12],
                    artifact.artifact_kind,
                    f"{artifact.source_file}:{artifact.field_path}",
                )
            except (OSError, RuntimeError) as exc:
                _logger.warning(
                    "Failed to create manifest for artifact %s: %s",
                    artifact.artifact_id[:12],
                    exc,
                )

    return artifacts, manifests_created, skipped_by_v1


def _format_output(
    artifacts: list[Artifact],
    output_format: str,
) -> str:
    """Format artifacts for output.

    Args:
        artifacts: List of detected artifacts.
        output_format: Output format (json, yaml, csv).

    Returns:
        Formatted output string.
    """
    if not artifacts:
        return ""

    artifact_dicts = [asdict(a) for a in artifacts]

    if output_format == "json":
        return json.dumps(artifact_dicts, indent=2)

    if output_format == "yaml":
        return yaml.safe_dump(artifact_dicts, default_flow_style=False)

    if output_format == "csv":
        # Flatten to CSV with key columns
        fieldnames = [
            "artifact_id",
            "artifact_kind",
            "artifact_format",
            "source_file",
            "source_element_id",
            "field_path",
            "render_plan_id",
        ]
        from io import StringIO

        buffer = StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for a in artifact_dicts:
            writer.writerow(a)
        return buffer.getvalue()

    return ""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Detect artifacts from YAML documentation files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    uv run knowledge.detect-artifacts --source-files 'docs/development/**/*.yml'
    uv run knowledge.detect-artifacts --source-files docs/architecture/event-flow.yml \\
        --output-format json
    uv run knowledge.detect-artifacts --source-files docs/**/*.yml \\
        --no-create-manifests
        """,
    )
    parser.add_argument(
        "--source-files",
        nargs="+",
        required=True,
        help="List of YAML file paths or glob patterns to scan for artifacts.",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=DEFAULT_ARTIFACTS_DIR,
        help="Directory for artifact manifests (default: .knowledge/artifacts).",
    )
    parser.add_argument(
        "--create-manifests",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Create manifest files for detected artifacts (default: True).",
    )
    parser.add_argument(
        "--v1-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Apply V1 participation rule (modality=text AND extraction_mode=full). Default: True.",
    )
    parser.add_argument(
        "--output-format",
        choices=["json", "yaml", "csv", "none"],
        default="none",
        help="Output format for listing detected artifacts (default: none).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Main entry point for artifact detection CLI.

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

    # Expand source file patterns
    source_files = _expand_source_files(args.source_files)
    if not source_files:
        _logger.error("No source files found matching patterns: %s", args.source_files)
        return 1

    _logger.info("Scanning %d source file(s) for artifacts...", len(source_files))

    # Detect artifacts from all files
    all_artifacts: list[Artifact] = []
    total_manifests_created = 0
    total_skipped_by_v1 = 0
    files_processed = 0

    for file_path in source_files:
        artifacts, manifests_created, skipped_by_v1 = _detect_from_file(
            file_path,
            args.artifacts_dir,
            args.create_manifests,
            args.v1_only,
        )
        all_artifacts.extend(artifacts)
        total_manifests_created += manifests_created
        total_skipped_by_v1 += skipped_by_v1
        files_processed += 1

    # Print summary
    print(f"Files processed: {files_processed}")
    print(f"Artifacts detected: {len(all_artifacts)}")
    if args.create_manifests:
        print(f"Manifests created: {total_manifests_created}")
    if args.v1_only and total_skipped_by_v1 > 0:
        print(f"Skipped by V1 rule: {total_skipped_by_v1}")

    # Group by artifact_kind for summary
    kinds_count: dict[str, int] = {}
    for artifact in all_artifacts:
        kinds_count[artifact.artifact_kind] = kinds_count.get(artifact.artifact_kind, 0) + 1

    if kinds_count:
        print("\nArtifacts by kind:")
        for kind, count in sorted(kinds_count.items()):
            print(f"  {kind}: {count}")

    # Output detailed list if requested
    if args.output_format != "none" and all_artifacts:
        output = _format_output(all_artifacts, args.output_format)
        if output:
            print(f"\n{output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
