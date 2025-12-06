"""Artifact manifest CRUD operations for the knowledge graph system.

This module provides functions for creating, reading, updating, and deleting
artifact manifests stored in `.knowledge/artifacts/`. Per fact_redesign.md
lines 481-521, artifact manifests define:
- Identity of the artifact (artifact_id, type)
- Provenance of the source artifact blob
- The complete set of contributing facts (structural FieldFacts + semantic facts)
- The render plan to use
- Validation status

Manifest Schema:
    artifact_id: Stable identifier (sha256 hash)
    artifact_kind: Registry kind identifier
    artifact_format: MIME type
    source: Provenance dict with source_file, source_element_id, field_path,
            source_locator, source_uri
    render_plan_id: Identifier for the deterministic render procedure
    projection_version: Ties to FieldFact projection version
    modality: Reserved schema hook (text/image/audio/video/other)
    extraction_mode: Reserved schema hook (full/incremental/query_only)
    contributors: Dict with structural (list[dict]) and semantic (list[dict])
    entities: List of resolved entity references
    rendered: Dict with path and validation results

V1 Participation Rule:
    Per fact_redesign.md lines 36-42, only artifacts with modality='text' AND
    extraction_mode='full' participate in current extraction/rendering pipelines.
    Other combinations are representable but bypassed.

Artifact Lifecycle Integration:
    Per fact_redesign.md lines 561-569, manifest CRUD supports:
    1) Detect artifact roots and assign metadata (handled by compare_yaml_docs)
    2) Create/update Artifact Manifest (create_artifact_manifest, update_artifact_manifest)
    3) Extract semantic facts (execute_artifact_lifecycle via artifact_fact_extractor)
    4) Render artifact from facts (execute_artifact_lifecycle via artifact_renderer)
    5) Validate rendered vs source (execute_artifact_lifecycle via artifact_validator)
    6) Persist validation results (execute_artifact_lifecycle, set_validation_result)

    Deferred to Task 9: Entity resolution (per fact_redesign_plan.md)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

import yaml

if TYPE_CHECKING:
    from scripts.knowledge.artifact_validator import ValidationResult
    from scripts.knowledge.compare_yaml_docs import Artifact

# Module-level logger
_logger = logging.getLogger(__name__)


class SourceInfo(TypedDict):
    """Source provenance information for an artifact."""

    source_file: str
    source_element_id: str
    field_path: str
    source_locator: str
    source_uri: str | None


class ValidationInfo(TypedDict):
    """Validation result information for an artifact."""

    last_validated_at: str
    similarity: str
    passed: str
    notes: str


class RenderedInfo(TypedDict):
    """Rendered artifact information."""

    path: str
    validation: ValidationInfo


class ContributorFact(TypedDict, total=False):
    """A structural or semantic contributor fact reference."""

    element_id: str
    field_path: str
    fact_id: str


class EntityRef(TypedDict, total=False):
    """A resolved entity reference."""

    entity_id: str
    keyword: str


class ContributorsInfo(TypedDict):
    """Contributors information for an artifact."""

    structural: list[ContributorFact]
    semantic: list[ContributorFact]


class ArtifactManifest(TypedDict):
    """Complete artifact manifest structure per fact_redesign.md lines 481-521."""

    artifact_id: str
    artifact_kind: str
    artifact_format: str
    source: SourceInfo
    render_plan_id: str
    projection_version: str
    modality: str
    extraction_mode: str
    contributors: ContributorsInfo
    entities: list[EntityRef]
    rendered: RenderedInfo


def _create_empty_validation() -> ValidationInfo:
    """Create an empty validation info structure."""
    return ValidationInfo(
        last_validated_at="",
        similarity="",
        passed="",
        notes="",
    )


def _create_empty_rendered() -> RenderedInfo:
    """Create an empty rendered info structure."""
    return RenderedInfo(
        path="",
        validation=_create_empty_validation(),
    )


def _create_empty_contributors() -> ContributorsInfo:
    """Create an empty contributors info structure."""
    return ContributorsInfo(
        structural=[],
        semantic=[],
    )


def _get_manifest_path(artifact_id: str, artifacts_dir: Path) -> Path:
    """Get the path for an artifact manifest file.

    Args:
        artifact_id: The artifact identifier.
        artifacts_dir: Base artifacts directory.

    Returns:
        Path to the manifest YAML file.
    """
    return artifacts_dir / f"{artifact_id}.yml"


def artifact_to_manifest(artifact: Artifact) -> ArtifactManifest:
    """Convert an Artifact dataclass to an ArtifactManifest dict.

    Creates a manifest with empty/placeholder fields for contributors,
    entities, rendered, and validation until semantic extraction and
    rendering phases are implemented.

    Args:
        artifact: The Artifact object to convert.

    Returns:
        ArtifactManifest dict ready for YAML serialization.
    """
    source = SourceInfo(
        source_file=artifact.source_file,
        source_element_id=artifact.source_element_id,
        field_path=artifact.field_path,
        source_locator=artifact.source_locator,
        source_uri=artifact.source_uri,
    )

    return ArtifactManifest(
        artifact_id=artifact.artifact_id,
        artifact_kind=artifact.artifact_kind,
        artifact_format=artifact.artifact_format,
        source=source,
        render_plan_id=artifact.render_plan_id,
        projection_version=artifact.projection_version,
        modality=artifact.modality,
        extraction_mode=artifact.extraction_mode,
        contributors=_create_empty_contributors(),
        entities=[],
        rendered=_create_empty_rendered(),
    )


def create_artifact_manifest(artifact: Artifact, output_dir: Path) -> Path:
    """Create an artifact manifest YAML file.

    Per fact_redesign.md lines 481-521, creates a manifest at
    `.knowledge/artifacts/<artifact_id>.yml` with the initial structure.
    Contributors, entities, rendered, and validation fields are initially
    empty/placeholder until semantic extraction and rendering phases.

    Args:
        artifact: The Artifact object to create a manifest for.
        output_dir: Base artifacts directory (e.g., .knowledge/artifacts).

    Returns:
        Path to the created manifest file.

    Raises:
        OSError: If creating the manifest file fails.
        RuntimeError: If YAML serialization fails.
    """
    manifest = artifact_to_manifest(artifact)
    output_path = _get_manifest_path(artifact.artifact_id, output_dir)

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        yaml_content = yaml.safe_dump(
            dict(manifest),
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        output_path.write_text(yaml_content, encoding="utf-8")
        _logger.info("Created artifact manifest: %s", output_path)
    except yaml.YAMLError as exc:
        msg = f"Failed to serialize artifact manifest: {exc}"
        raise RuntimeError(msg) from exc
    except OSError:
        _logger.exception("Failed to create artifact manifest: %s", output_path)
        raise
    else:
        return output_path


def load_artifact_manifest(artifact_id: str, artifacts_dir: Path) -> ArtifactManifest:
    """Load an artifact manifest from YAML file.

    Args:
        artifact_id: The artifact identifier.
        artifacts_dir: Base artifacts directory.

    Returns:
        The loaded ArtifactManifest.

    Raises:
        FileNotFoundError: If the manifest file doesn't exist.
        ValueError: If the manifest YAML is invalid or missing required fields.
    """
    manifest_path = _get_manifest_path(artifact_id, artifacts_dir)

    if not manifest_path.exists():
        msg = f"Artifact manifest not found: {manifest_path}"
        raise FileNotFoundError(msg)

    try:
        content = manifest_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML in artifact manifest {manifest_path}: {exc}"
        raise ValueError(msg) from exc

    if not isinstance(data, dict):
        msg = f"Artifact manifest must be a dict: {manifest_path}"
        raise TypeError(msg)

    # Validate required fields
    required_fields = {
        "artifact_id",
        "artifact_kind",
        "artifact_format",
        "source",
        "render_plan_id",
        "projection_version",
    }
    missing = required_fields - set(data.keys())
    if missing:
        msg = f"Artifact manifest missing required fields {missing}: {manifest_path}"
        raise ValueError(msg)

    # Add defaults for optional fields
    if "modality" not in data:
        data["modality"] = "text"
    if "extraction_mode" not in data:
        data["extraction_mode"] = "full"
    if "contributors" not in data:
        data["contributors"] = _create_empty_contributors()
    if "entities" not in data:
        data["entities"] = []
    if "rendered" not in data:
        data["rendered"] = _create_empty_rendered()

    return ArtifactManifest(**data)  # type: ignore[typeddict-item, no-any-return]


def update_artifact_manifest(
    artifact_id: str,
    updates: dict[str, Any],
    artifacts_dir: Path,
) -> None:
    """Update an artifact manifest with new values.

    Loads the existing manifest, merges updates, and writes back.
    Supports deep updates for nested fields like 'contributors', 'entities',
    'rendered', and 'rendered.validation'.

    Args:
        artifact_id: The artifact identifier.
        updates: Dictionary of updates to merge.
        artifacts_dir: Base artifacts directory.

    Raises:
        FileNotFoundError: If the manifest file doesn't exist.
        ValueError: If the manifest YAML is invalid.
        RuntimeError: If YAML serialization fails.
    """
    manifest = load_artifact_manifest(artifact_id, artifacts_dir)
    manifest_path = _get_manifest_path(artifact_id, artifacts_dir)

    # Deep merge updates into manifest
    manifest_dict: dict[str, Any] = dict(manifest)

    for key, value in updates.items():
        if (
            key in manifest_dict
            and isinstance(manifest_dict[key], dict)
            and isinstance(value, dict)
        ):
            # Deep merge for nested dicts
            manifest_dict[key].update(value)
        else:
            manifest_dict[key] = value

    try:
        yaml_content = yaml.safe_dump(
            manifest_dict,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        manifest_path.write_text(yaml_content, encoding="utf-8")
        _logger.info("Updated artifact manifest: %s", manifest_path)
    except yaml.YAMLError as exc:
        msg = f"Failed to serialize updated artifact manifest: {exc}"
        raise RuntimeError(msg) from exc


def list_artifact_manifests(
    artifacts_dir: Path,
    filter_v1_only: bool = True,
) -> list[ArtifactManifest]:
    """List all artifact manifests in the artifacts directory.

    Per fact_redesign.md lines 36-42, optionally filters by V1 participation
    rule: only artifacts with modality='text' AND extraction_mode='full'.

    Args:
        artifacts_dir: Base artifacts directory.
        filter_v1_only: If True, only return manifests matching V1 rule.

    Returns:
        List of ArtifactManifest objects.
    """
    if not artifacts_dir.exists():
        return []

    manifests: list[ArtifactManifest] = []

    for manifest_path in sorted(artifacts_dir.glob("*.yml")):
        # Skip the kinds.yml registry file
        if manifest_path.name == "kinds.yml":
            continue

        try:
            artifact_id = manifest_path.stem
            manifest = load_artifact_manifest(artifact_id, artifacts_dir)

            # Apply V1 filter
            if filter_v1_only:
                modality = manifest.get("modality", "text")
                extraction_mode = manifest.get("extraction_mode", "full")
                if modality != "text" or extraction_mode != "full":
                    _logger.debug(
                        "Skipping non-V1 manifest: %s (modality=%s, extraction_mode=%s)",
                        artifact_id,
                        modality,
                        extraction_mode,
                    )
                    continue

            manifests.append(manifest)
        except (FileNotFoundError, ValueError) as exc:
            _logger.warning("Skipping invalid manifest %s: %s", manifest_path, exc)
            continue

    return manifests


def delete_artifact_manifest(artifact_id: str, artifacts_dir: Path) -> None:
    """Delete an artifact manifest file.

    Args:
        artifact_id: The artifact identifier.
        artifacts_dir: Base artifacts directory.

    Raises:
        FileNotFoundError: If the manifest file doesn't exist.
        OSError: If deleting the file fails.
    """
    manifest_path = _get_manifest_path(artifact_id, artifacts_dir)

    if not manifest_path.exists():
        msg = f"Artifact manifest not found: {manifest_path}"
        raise FileNotFoundError(msg)

    manifest_path.unlink()
    _logger.info("Deleted artifact manifest: %s", manifest_path)


def get_manifests_by_source_file(
    source_file: str,
    artifacts_dir: Path,
    filter_v1_only: bool = True,
) -> list[ArtifactManifest]:
    """Get all artifact manifests for a specific source file.

    Args:
        source_file: The source file path to filter by.
        artifacts_dir: Base artifacts directory.
        filter_v1_only: If True, only return manifests matching V1 rule.

    Returns:
        List of ArtifactManifest objects from the specified source file.
    """
    all_manifests = list_artifact_manifests(artifacts_dir, filter_v1_only)
    return [m for m in all_manifests if m["source"]["source_file"] == source_file]


def get_manifests_by_kind(
    artifact_kind_pattern: str,
    artifacts_dir: Path,
    filter_v1_only: bool = True,
) -> list[ArtifactManifest]:
    """Get all artifact manifests matching an artifact_kind pattern.

    Supports wildcard patterns:
    - "prose/*" matches prose/paragraph, prose/code-block, etc.
    - "diagram/mermaid.*" matches diagram/mermaid.sequence, diagram/mermaid.flowchart
    - Exact match if no wildcards present

    Args:
        artifact_kind_pattern: The artifact kind pattern to match.
        artifacts_dir: Base artifacts directory.
        filter_v1_only: If True, only return manifests matching V1 rule.

    Returns:
        List of ArtifactManifest objects matching the pattern.
    """
    import fnmatch

    all_manifests = list_artifact_manifests(artifacts_dir, filter_v1_only)
    return [m for m in all_manifests if fnmatch.fnmatch(m["artifact_kind"], artifact_kind_pattern)]


def set_validation_result(
    artifact_id: str,
    artifacts_dir: Path,
    similarity: str,
    passed: bool,
    notes: str = "",
) -> None:
    """Set the validation result for an artifact manifest.

    Convenience function for updating the rendered.validation section
    of an artifact manifest with validation results.

    Args:
        artifact_id: The artifact identifier.
        artifacts_dir: Base artifacts directory.
        similarity: Similarity score (e.g., "0.95", "1.0").
        passed: Whether validation passed.
        notes: Optional notes about the validation.

    Raises:
        FileNotFoundError: If the manifest file doesn't exist.
        ValueError: If the manifest is invalid.
    """
    timestamp = datetime.now(tz=UTC).isoformat()
    updates = {
        "rendered": {
            "validation": {
                "last_validated_at": timestamp,
                "similarity": similarity,
                "passed": str(passed).lower(),
                "notes": notes,
            }
        }
    }
    update_artifact_manifest(artifact_id, updates, artifacts_dir)


def execute_artifact_lifecycle(
    artifact_id: str,
    artifacts_dir: Path,
    rendered_dir: Path,
    validations_csv: Path,
    knowledge_path: Path,
) -> tuple[Path | None, ValidationResult | None]:
    """Execute the full artifact lifecycle for a single artifact.

    Orchestrates semantic fact extraction, rendering, and validation per
    fact_redesign.md lines 561-569. Only processes V1 artifacts (modality=text
    AND extraction_mode=full).

    Lifecycle steps:
    1. Load artifact manifest
    2. Check V1 participation rule (skip if not V1)
    3. Extract semantic facts (if artifact_fact_extractor available)
    4. Load render plan
    5. Render artifact from facts
    6. Load source text for validation
    7. Validate rendered vs source using appropriate comparator
    8. Persist validation result to CSV
    9. Update manifest with validation status
    10. Return (rendered_path, ValidationResult)

    Args:
        artifact_id: The artifact identifier.
        artifacts_dir: Base artifacts directory (e.g., .knowledge/artifacts).
        rendered_dir: Directory for rendered artifacts (e.g., .knowledge/artifacts/rendered).
        validations_csv: Path to the validations CSV file.
        knowledge_path: Path to knowledge directory (e.g., .knowledge).

    Returns:
        Tuple of (rendered_path, ValidationResult) if successful, or (None, None)
        if artifact is skipped or lifecycle fails.

    Raises:
        FileNotFoundError: If the manifest file doesn't exist.
        ValueError: If the manifest is invalid or render plan not found.
    """
    # Import lazily to avoid circular imports
    from scripts.knowledge.artifact_renderer import render_artifact
    from scripts.knowledge.artifact_validator import (
        get_comparator_for_artifact_kind,
        validate_artifact,
        write_validation_result,
    )
    from scripts.knowledge.render_plan_manager import load_render_plan

    # Step 1: Load manifest
    manifest = load_artifact_manifest(artifact_id, artifacts_dir)
    _logger.info("Loaded manifest for artifact: %s", artifact_id)

    # Step 2: Check V1 participation rule
    modality = manifest.get("modality", "text")
    extraction_mode = manifest.get("extraction_mode", "full")
    if modality != "text" or extraction_mode != "full":
        _logger.info(
            "Skipping non-V1 artifact %s (modality=%s, extraction_mode=%s)",
            artifact_id,
            modality,
            extraction_mode,
        )
        return None, None

    # Step 3: Extract semantic facts (optional - may not have extractor)
    try:
        from scripts.knowledge.artifact_fact_extractor import extract_artifact_facts

        extract_artifact_facts(artifact_id, knowledge_path)
        _logger.info("Extracted semantic facts for artifact: %s", artifact_id)
    except ImportError:
        _logger.debug("artifact_fact_extractor not available, skipping fact extraction")
    except Exception as e:
        _logger.warning("Fact extraction failed for %s: %s", artifact_id, e)

    # Step 4: Load render plan
    render_plan_id = manifest.get("render_plan_id", "")
    if not render_plan_id:
        _logger.warning("No render_plan_id in manifest: %s", artifact_id)
        return None, None

    render_plans_dir = artifacts_dir.parent / "render_plans"
    if not render_plans_dir.exists():
        render_plans_dir = artifacts_dir / "render_plans"

    try:
        render_plan = load_render_plan(render_plan_id, render_plans_dir)
        _logger.debug("Loaded render plan: %s", render_plan_id)
    except FileNotFoundError:
        _logger.warning("Render plan not found: %s", render_plan_id)
        return None, None

    # Step 5: Render artifact
    try:
        rendered_path = render_artifact(manifest, render_plan, artifacts_dir, rendered_dir)
        _logger.info("Rendered artifact to: %s", rendered_path)
    except Exception:
        _logger.exception("Rendering failed for %s", artifact_id)
        return None, None

    # Step 6: Load source text for validation
    source = manifest.get("source", {})
    source_file = source.get("source_file", "")
    if not source_file:
        _logger.warning("No source_file in manifest: %s", artifact_id)
        return rendered_path, None

    # Resolve source file path
    repo_root = artifacts_dir.parent.parent
    source_path = Path(source_file)
    if not source_path.is_absolute():
        source_path = repo_root / source_file

    if not source_path.exists():
        _logger.warning("Source file not found: %s", source_path)
        return rendered_path, None

    try:
        source_text = source_path.read_text(encoding="utf-8")

        # Extract specific field if field_path is specified
        field_path = source.get("field_path", "")
        if field_path:
            import yaml as yaml_lib

            try:
                data = yaml_lib.safe_load(source_text)
                parts = field_path.split(".")
                for part in parts:
                    if isinstance(data, dict) and part in data:
                        data = data[part]
                    elif isinstance(data, list) and part.isdigit():
                        data = data[int(part)]
                    else:
                        break
                if isinstance(data, str):
                    source_text = data
                else:
                    source_text = yaml_lib.safe_dump(
                        data, default_flow_style=False, allow_unicode=True
                    )
            except yaml_lib.YAMLError:
                pass  # Use full content
    except OSError as e:
        _logger.warning("Failed to read source file: %s", e)
        return rendered_path, None

    # Step 7: Validate rendered vs source
    artifact_kind = manifest.get("artifact_kind", "prose/paragraph")
    comparator = get_comparator_for_artifact_kind(artifact_kind)

    try:
        result = validate_artifact(manifest, rendered_path, source_text, comparator)
        _logger.info(
            "Validation result for %s: similarity=%.2f, passed=%s",
            artifact_id,
            result.similarity_score,
            result.passed,
        )
    except Exception:
        _logger.exception("Validation failed for %s", artifact_id)
        return rendered_path, None

    # Step 8: Persist validation result to CSV
    try:
        write_validation_result(result, validations_csv)
        _logger.debug("Wrote validation result to: %s", validations_csv)
    except OSError as e:
        _logger.warning("Failed to write validation result: %s", e)

    # Step 9: Update manifest with validation status
    try:
        set_validation_result(
            artifact_id,
            artifacts_dir,
            str(result.similarity_score),
            result.passed,
            result.mismatch_summary,
        )
    except Exception as e:
        _logger.warning("Failed to update manifest validation: %s", e)

    # Step 10: Return results
    return rendered_path, result
