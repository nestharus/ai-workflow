"""CLI script for artifact rendering from facts.

This script implements artifact lifecycle steps 3-5 per fact_redesign.md lines 561-569:
extract semantic facts from artifacts, render artifacts from facts, and validate
rendered vs source artifacts.

Usage:
    uv run knowledge.render-artifacts
    uv run knowledge.render-artifacts --source-file docs/architecture/event-flow.yml
    uv run knowledge.render-artifacts --artifact-kind 'diagram/*'
    uv run knowledge.render-artifacts --validate
    uv run knowledge.render-artifacts --artifact-id abc123

Workflow:
    1. Load artifact manifests from artifacts_dir (filtered by args)
    2. For each manifest, load the corresponding render plan
    3. Render artifact using render plan (text_llm or none engine)
    4. Optionally validate rendered artifact against source
    5. Update manifest with rendered path and validation results

V1 Participation Rule:
    Per fact_redesign.md lines 36-42, only artifacts with modality='text' AND
    extraction_mode='full' participate. Use --no-v1-only to include all.

See Also:
    - knowledge.detect-artifacts: Detect artifacts from YAML documentation
    - knowledge.query-artifacts: Query artifact manifests
    - knowledge.query-validations: Query validation results
"""

from __future__ import annotations

import argparse
import fnmatch
import logging
import sys
from pathlib import Path

import yaml

from scripts.dev.utils import REPO_ROOT
from scripts.knowledge.artifact_manager import (
    ArtifactManifest,
    execute_artifact_lifecycle,
    list_artifact_manifests,
    update_artifact_manifest,
)
from scripts.knowledge.artifact_renderer import render_artifact
from scripts.knowledge.artifact_validator import (
    ValidationResult,
    get_comparator_for_artifact_kind,
    validate_artifact,
    write_validation_result,
)
from scripts.knowledge.render_plan_manager import (
    get_render_plan_for_artifact_kind,
    load_render_plan,
)

# Module-level logger
_logger = logging.getLogger(__name__)

# Default directories
DEFAULT_ARTIFACTS_DIR = REPO_ROOT / ".knowledge" / "artifacts"
DEFAULT_RENDER_PLANS_DIR = DEFAULT_ARTIFACTS_DIR / "render_plans"
DEFAULT_RENDERED_DIR = DEFAULT_ARTIFACTS_DIR / "rendered"
DEFAULT_VALIDATIONS_CSV = DEFAULT_ARTIFACTS_DIR / "validations.csv"


def _filter_manifests(
    manifests: list[ArtifactManifest],
    artifact_id: str | None,
    artifact_kind_pattern: str | None,
    source_file: str | None,
) -> list[ArtifactManifest]:
    """Filter manifests by optional criteria.

    Args:
        manifests: List of manifests to filter.
        artifact_id: Optional artifact ID to match (prefix match).
        artifact_kind_pattern: Optional artifact kind glob pattern.
        source_file: Optional source file to match.

    Returns:
        Filtered list of manifests.
    """
    filtered = manifests

    if artifact_id:
        filtered = [m for m in filtered if m["artifact_id"].startswith(artifact_id)]

    if artifact_kind_pattern:
        filtered = [
            m for m in filtered if fnmatch.fnmatch(m["artifact_kind"], artifact_kind_pattern)
        ]

    if source_file:
        filtered = [m for m in filtered if m["source"]["source_file"] == source_file]

    return filtered


def _get_source_text(manifest: ArtifactManifest) -> str:
    """Get the source text for an artifact from its source file.

    Args:
        manifest: The artifact manifest.

    Returns:
        Source text, or empty string if not found.
    """
    source = manifest.get("source", {})
    source_file = source.get("source_file", "")

    if not source_file:
        return ""

    source_path = Path(source_file)
    if not source_path.is_absolute():
        source_path = REPO_ROOT / source_file

    if not source_path.exists():
        _logger.warning("Source file not found: %s", source_path)
        return ""

    try:
        content = source_path.read_text(encoding="utf-8")

        # Extract specific field if field_path is specified
        field_path = source.get("field_path", "")
        if field_path:
            try:
                data = yaml.safe_load(content)
                parts = field_path.split(".")
                for part in parts:
                    if isinstance(data, dict) and part in data:
                        data = data[part]
                    elif isinstance(data, list) and part.isdigit():
                        data = data[int(part)]
                    else:
                        content = content
                        break
                else:
                    if isinstance(data, str):
                        content = data
                    else:
                        content = yaml.safe_dump(data, default_flow_style=False, allow_unicode=True)
            except yaml.YAMLError:
                pass

    except OSError as exc:
        _logger.warning("Failed to read source file: %s", exc)
        return ""
    else:
        return content


def _render_manifest(
    manifest: ArtifactManifest,
    artifacts_dir: Path,
    render_plans_dir: Path,
    rendered_dir: Path,
    do_validate: bool,
    validations_csv: Path,
) -> tuple[bool, bool, ValidationResult | None]:
    """Render a single artifact manifest.

    Args:
        manifest: The artifact manifest to render.
        artifacts_dir: Base artifacts directory.
        render_plans_dir: Render plans directory.
        rendered_dir: Output directory for rendered artifacts.
        do_validate: Whether to validate after rendering.
        validations_csv: Path to validations CSV file.

    Returns:
        Tuple of (render_success, validation_passed, validation_result).
    """
    artifact_id = manifest["artifact_id"]
    artifact_kind = manifest["artifact_kind"]
    render_plan_id = manifest.get("render_plan_id", "")

    # Load render plan
    render_plan = None
    if render_plan_id:
        try:
            render_plan = load_render_plan(render_plan_id, render_plans_dir)
        except (FileNotFoundError, ValueError) as exc:
            _logger.warning(
                "Failed to load render plan '%s' for artifact %s: %s",
                render_plan_id,
                artifact_id[:12],
                exc,
            )

    # Fall back to finding plan by artifact_kind
    if render_plan is None:
        render_plan = get_render_plan_for_artifact_kind(artifact_kind, render_plans_dir)

    if render_plan is None:
        _logger.warning(
            "No render plan found for artifact %s (kind=%s)",
            artifact_id[:12],
            artifact_kind,
        )
        return False, False, None

    # Render artifact
    try:
        rendered_path = render_artifact(
            manifest,
            render_plan,
            artifacts_dir,
            rendered_dir,
        )
        _logger.info(
            "Rendered artifact %s to %s",
            artifact_id[:12],
            rendered_path,
        )
    except (OSError, ValueError) as exc:
        _logger.warning(
            "Failed to render artifact %s: %s",
            artifact_id[:12],
            exc,
        )
        return False, False, None

    # Update manifest with rendered path
    try:
        update_artifact_manifest(
            artifact_id,
            {"rendered": {"path": str(rendered_path)}},
            artifacts_dir,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        _logger.warning(
            "Failed to update manifest for artifact %s: %s",
            artifact_id[:12],
            exc,
        )

    # Validate if requested
    validation_result = None
    validation_passed = True

    if do_validate:
        source_text = _get_source_text(manifest)
        if source_text:
            comparator = get_comparator_for_artifact_kind(artifact_kind)
            try:
                validation_result = validate_artifact(
                    manifest,
                    rendered_path,
                    source_text,
                    comparator,
                )
                validation_passed = validation_result.passed

                # Write validation result to CSV
                write_validation_result(validation_result, validations_csv)

                # Update manifest with validation results
                update_artifact_manifest(
                    artifact_id,
                    {
                        "rendered": {
                            "validation": {
                                "last_validated_at": validation_result.validated_at,
                                "similarity": f"{validation_result.similarity_score:.4f}",
                                "passed": str(validation_result.passed).lower(),
                                "notes": validation_result.mismatch_summary,
                            }
                        }
                    },
                    artifacts_dir,
                )

                _logger.info(
                    "Validated artifact %s: similarity=%.2f, passed=%s",
                    artifact_id[:12],
                    validation_result.similarity_score,
                    validation_result.passed,
                )
            except (FileNotFoundError, ValueError) as exc:
                _logger.warning(
                    "Failed to validate artifact %s: %s",
                    artifact_id[:12],
                    exc,
                )
                validation_passed = False
        else:
            _logger.warning(
                "No source text found for artifact %s, skipping validation",
                artifact_id[:12],
            )

    return True, validation_passed, validation_result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Render artifacts from facts using render plans.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Default: Use full lifecycle orchestration (semantic fact extraction,
    # LLM rendering, embedding-based validation)
    uv run knowledge.render-artifacts
    uv run knowledge.render-artifacts --source-file docs/architecture/event-flow.yml
    uv run knowledge.render-artifacts --artifact-kind 'diagram/*'
    uv run knowledge.render-artifacts --artifact-id abc123

    # Legacy mode: Use _render_manifest() without lifecycle orchestration
    uv run knowledge.render-artifacts --legacy-mode
    uv run knowledge.render-artifacts --legacy-mode --validate
        """,
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=DEFAULT_ARTIFACTS_DIR,
        help="Directory for artifact manifests (default: .knowledge/artifacts).",
    )
    parser.add_argument(
        "--render-plans-dir",
        type=Path,
        default=DEFAULT_RENDER_PLANS_DIR,
        help="Directory for render plans (default: .knowledge/artifacts/render_plans).",
    )
    parser.add_argument(
        "--rendered-dir",
        type=Path,
        default=DEFAULT_RENDERED_DIR,
        help="Output directory for rendered artifacts (default: .knowledge/artifacts/rendered).",
    )
    parser.add_argument(
        "--validations-csv",
        type=Path,
        default=DEFAULT_VALIDATIONS_CSV,
        help="Path to validations CSV file (default: .knowledge/artifacts/validations.csv).",
    )
    parser.add_argument(
        "--artifact-id",
        type=str,
        default=None,
        help="Filter by artifact ID (prefix match).",
    )
    parser.add_argument(
        "--artifact-kind",
        type=str,
        default=None,
        help="Filter by artifact kind pattern (glob pattern, e.g., 'diagram/*').",
    )
    parser.add_argument(
        "--source-file",
        type=str,
        default=None,
        help="Filter by source file path.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        default=False,
        help="Validate rendered artifacts against source after rendering.",
    )
    parser.add_argument(
        "--v1-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Apply V1 participation rule (modality=text AND extraction_mode=full). Default: True.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    parser.add_argument(
        "--legacy-mode",
        action="store_true",
        default=False,
        help="Use legacy _render_manifest() instead of execute_artifact_lifecycle(). "
        "Default behavior uses full lifecycle orchestration including semantic fact "
        "extraction, LLM rendering, and embedding-based validation.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=REPO_ROOT / ".knowledge",
        help="Path to knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Main entry point for artifact rendering CLI.

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

    # Load manifests
    manifests = list_artifact_manifests(args.artifacts_dir, filter_v1_only=args.v1_only)

    if not manifests:
        _logger.info("No artifact manifests found in %s", args.artifacts_dir)
        print("No artifact manifests found.")
        return 0

    # Filter manifests
    filtered_manifests = _filter_manifests(
        manifests,
        args.artifact_id,
        args.artifact_kind,
        args.source_file,
    )

    if not filtered_manifests:
        _logger.info("No manifests match the specified filters")
        print("No manifests match the specified filters.")
        return 0

    _logger.info("Rendering %d artifact(s)...", len(filtered_manifests))

    # Render each manifest
    render_success_count = 0
    render_failed_count = 0
    validation_passed_count = 0
    validation_failed_count = 0

    for manifest in filtered_manifests:
        artifact_id = manifest["artifact_id"]

        if args.legacy_mode:
            # Use legacy rendering logic (for backward compatibility)
            render_success, validation_passed, _ = _render_manifest(
                manifest,
                args.artifacts_dir,
                args.render_plans_dir,
                args.rendered_dir,
                args.validate,
                args.validations_csv,
            )

            if render_success:
                render_success_count += 1
                if args.validate:
                    if validation_passed:
                        validation_passed_count += 1
                    else:
                        validation_failed_count += 1
            else:
                render_failed_count += 1
        else:
            # Default: Use full lifecycle orchestration
            try:
                rendered_path, validation_result = execute_artifact_lifecycle(
                    artifact_id,
                    args.artifacts_dir,
                    args.rendered_dir,
                    args.validations_csv,
                    args.knowledge_path,
                )

                if rendered_path is not None:
                    render_success_count += 1
                    if validation_result is not None:
                        if validation_result.passed:
                            validation_passed_count += 1
                        else:
                            validation_failed_count += 1
                else:
                    # Skipped (non-V1) or failed
                    if (
                        manifest.get("modality") != "text"
                        or manifest.get("extraction_mode") != "full"
                    ):
                        _logger.info("Skipped non-V1 artifact: %s", artifact_id[:12])
                    else:
                        render_failed_count += 1
            except Exception as exc:
                _logger.warning("Lifecycle failed for %s: %s", artifact_id[:12], exc)
                render_failed_count += 1

    # Print summary
    print("\nRendering Summary:")
    print(f"  Total manifests: {len(filtered_manifests)}")
    print(f"  Rendered successfully: {render_success_count}")
    print(f"  Render failed: {render_failed_count}")

    if args.validate or not args.legacy_mode:
        print("\nValidation Summary:")
        print(f"  Validation passed: {validation_passed_count}")
        print(f"  Validation failed: {validation_failed_count}")

    return 0 if render_failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
