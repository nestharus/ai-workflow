"""Compare YAML documents by extracting IDs and their associated object data.

This module provides utilities for parsing YAML files and extracting ID-to-object
mappings, enabling dict-to-dict comparison of document content across different
versions or files. It compares original YAML files with their split counterparts
in subdirectories.

Per the YAML schema guidelines, `id` is the only field that may exist on elements.
It is required for root elements of sections but optional for children. The
comparison logic handles this by only tracking elements that have an `id` field.

Outputs flattened CSV files to `.knowledge/comparisons/` with columns:
source_file, id, origin_type, original_data, split_file, split_data

Usage:
    uv run knowledge.compare-yml-docs [--path <directory>] [--original-files <file> ...]

Args:
    --path: Base directory containing original and split YAML files
            (default: docs/development/).
    --original-files: Optional list of timestamped original files from
            `.knowledge/originals/` to use instead of globbing for
            `original.*.yml` files in the base path. When not provided,
            falls back to the default glob pattern.

Example:
    uv run knowledge.compare-yml-docs \\
      --original-files .knowledge/originals/20251201T134735Z-api-patterns.yml

FieldFact Extraction:
    Produces field-level facts from sliced YAML elements with role assignment
    (constraint/entity_ref/artifact_root/metadata), constraint grouping via
    group_key/group_id, and deterministic text projection. FieldFacts are the
    foundation for artifact detection (subsequent phase) and entity resolution.
    See docs/plans/fact_redesign.md lines 143-279 for specification.

Artifact Layer:
    The Artifact dataclass bridges structural FieldFacts and semantic fact extraction.
    Artifacts are irreducible, user-facing views rendered from facts—not edited directly.
    Editing occurs by changing underlying facts and re-rendering. The artifact layer
    enables extract→render→compare validation loops for dense integrated documentation
    (paragraphs, code blocks, tables). See docs/plans/fact_redesign.md lines 282-569
    for specification.

Projection Versioning:
    The text projection contract is versioned as 'fieldfacts.v2'. This identifies:
    - Element slicing: nested id-bearing dicts replaced with {"$ref": "<child_id>"}
    - FieldFact extraction: including roles, grouping, and artifact root tagging
    - Text projection format: "[ancestor > element_id] field_path = value"

    Version bump triggers (per fact_redesign.md lines 1398-1426):
    - Changes to slicing rules or $ref representation
    - Changes to FieldFact structure (fields, role rules, grouping)
    - Changes to text projection format or ordering

    The projection_version MUST be recorded in:
    - resolved.csv (resolution_tracker.py)
    - candidates.csv (candidate_extraction.py)
    - Artifact manifests and graph ingestion outputs

Key Functions:
    - extract_ids_and_text: Canonical fact-line projection for hashing/NLP
    - compute_element_content_hash: Structural hash independent of text formatting
    - _index_elements: Build element context map with ancestor tracking
    - _fact_to_line: Format FieldFact as text line with ancestor chain
"""

import argparse
import hashlib
import json
import logging
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypedDict

import duckdb
import yaml

from scripts.dev.utils import REPO_ROOT

# Module-level logger
_logger = logging.getLogger(__name__)

# Module-level cache for artifact kind registry
_artifact_registry_cache: list[dict[str, Any]] | None = None


@dataclass
class ContainmentEdge:
    """Represents a parent-child containment relationship between elements.

    When a parent element contains a nested dict with its own `id` field,
    a ContainmentEdge is created to record this relationship. The nested
    child is sliced out and replaced with a reference in the parent.

    Attributes:
        parent_id: The ID of the parent element.
        child_id: The ID of the nested child element.
        field_path: The path where the child appeared (e.g., "items[2]").
        source_file: Relative path to the source YAML file.
    """

    parent_id: str
    child_id: str
    field_path: str
    source_file: str


@dataclass
class ElementContext:
    """Context information for an element within YAML structure.

    Captures the element's position in the document hierarchy including its
    YAML path and ancestor chain. Used by _index_elements to build a mapping
    for text projection with ancestor tracking.

    Per fact_redesign.md lines 1082-1086, this enables:
    - Ancestor chain construction for fact-line formatting
    - YAML path recording for structural context
    - Element lookup by ID for text projection

    Attributes:
        id: The element's unique identifier.
        obj: The raw dict object from YAML.
        path: YAML path to the element (e.g., "sections[0].items[2]").
        ancestors: List of ancestor element IDs, outermost to nearest.
    """

    id: str
    obj: dict[str, Any]
    path: str
    ancestors: list[str]


# Type aliases for FieldFact value_kind and role
ValueKind = Literal[
    "scalar-str",
    "scalar-num",
    "scalar-bool",
    "scalar-null",
    "ref",
    "list-scalar",
    "list-object",
    "object",
]
FieldRole = Literal["constraint", "entity_ref", "artifact_root", "metadata"]
ArtifactLocator = Literal["inline", "reference"]


@dataclass
class FieldFact:
    """Represents a field-level fact extracted from a sliced YAML element.

    FieldFacts capture field-level metadata including role assignment
    (constraint/entity_ref/artifact_root/metadata), constraint grouping via
    group_key/group_id, and all necessary context for deterministic text
    projection and downstream processing.

    Per the fact redesign specification (docs/plans/fact_redesign.md lines 180-202),
    FieldFacts form the canonical structural representation that enables:
    - Artifact detection (via role == artifact_root)
    - Entity resolution (via role == entity_ref and $ref values)
    - Constraint grouping (via group_key/group_id)
    - Semantic fact extraction

    Attributes:
        element_id: The ID of the element this fact belongs to.
        field_path: Full path from element root (e.g., "raises[0].status_code").
        key: Last segment of field_path (e.g., "status_code").
        scope_path: Prefix of field_path (e.g., "raises[0]").
        value: The normalized leaf value, or a $ref dict.
        value_kind: Classification of the value type.
        ancestors: List of ancestor element IDs (outermost to nearest).
        source_file: Relative path to the source YAML file.
        role: Semantic role of this field (constraint/entity_ref/artifact_root/metadata).
        artifact_kind: Open-ended artifact kind (set when role == artifact_root).
        artifact_format: MIME type for artifact (set when role == artifact_root).
        artifact_locator: How artifact content is located (inline/reference).
        artifact_uri: URI when artifact_locator == reference.
        group_key: Explicit semantic grouping key for constraint grouping.
        group_id: SHA-256 hash of group_key for stable identity.
    """

    element_id: str
    field_path: str
    key: str
    scope_path: str
    value: Any  # noqa: ANN401
    value_kind: ValueKind
    ancestors: list[str] = field(default_factory=list)
    source_file: str = ""
    role: FieldRole = "constraint"
    artifact_kind: str | None = None
    artifact_format: str | None = None
    artifact_locator: ArtifactLocator | None = None
    artifact_uri: str | None = None
    group_key: str = ""
    group_id: str = ""


# Metadata keys per fact_redesign.md lines 210-235
METADATA_KEYS = frozenset(
    {"doc_id", "id", "version_hint", "kind", "index", "category", "domain"}
)


def _determine_value_kind(value: Any) -> ValueKind:  # noqa: ANN401
    """Determine the value_kind for a given value.

    Classifies values into one of the ValueKind enum values based on their type.

    Args:
        value: The value to classify.

    Returns:
        The appropriate ValueKind enum value.
    """
    # Check for $ref dict first (entity reference)
    if isinstance(value, dict):
        if "$ref" in value and isinstance(value["$ref"], str):
            return "ref"
        return "object"

    # Check for None
    if value is None:
        return "scalar-null"

    # Check for bool before numeric (bool is subclass of int in Python)
    if isinstance(value, bool):
        return "scalar-bool"

    # Check for numeric types
    if isinstance(value, (int, float)):
        return "scalar-num"

    # Check for string
    if isinstance(value, str):
        return "scalar-str"

    # Check for list
    if isinstance(value, list):
        # Determine if list contains scalars or objects
        if not value:
            return "list-scalar"  # Empty list treated as scalar list
        for item in value:
            if isinstance(item, (dict, list)):
                return "list-object"
        return "list-scalar"

    # Fallback to scalar-str for any other types
    return "scalar-str"


def _load_artifact_registry(
    knowledge_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Load the artifact kind registry from YAML.

    Caches the registry in a module-level variable to avoid repeated file reads.
    Returns an empty list if the registry file doesn't exist (graceful degradation).

    Args:
        knowledge_path: Base knowledge directory path. If None, uses REPO_ROOT/.knowledge.

    Returns:
        List of artifact kind entries, or empty list if registry unavailable.
    """
    global _artifact_registry_cache  # noqa: PLW0603

    if _artifact_registry_cache is not None:
        return _artifact_registry_cache

    if knowledge_path is None:
        knowledge_path = REPO_ROOT / KNOWLEDGE_DIR_NAME

    registry_path = knowledge_path / "artifacts" / "kinds.yml"
    if not registry_path.exists():
        _artifact_registry_cache = []
        return _artifact_registry_cache

    try:
        content = registry_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
    except (yaml.YAMLError, OSError) as exc:
        _logger.warning("Failed to load artifact registry: %s", exc)
        _artifact_registry_cache = []
        return _artifact_registry_cache

    if not isinstance(data, dict):
        _logger.warning("Artifact registry must be a YAML mapping with 'kinds' key")
        _artifact_registry_cache = []
        return _artifact_registry_cache

    kinds = data.get("kinds", [])
    if not isinstance(kinds, list):
        _logger.warning("'kinds' in artifact registry must be a list")
        _artifact_registry_cache = []
        return _artifact_registry_cache

    _artifact_registry_cache = kinds
    return _artifact_registry_cache


def _clear_artifact_registry_cache() -> None:
    """Clear the artifact registry cache for testing purposes."""
    global _artifact_registry_cache  # noqa: PLW0603
    _artifact_registry_cache = None


def _match_root_path(field_path: str, root_path_pattern: str) -> bool:
    """Check if a field path matches a root_path pattern.

    Supports two matching modes:
    1. Exact match: sections[*].items[*].text matches sections[0].items[2].text
    2. Container match: sections[*].http_method_defaults matches any field under that path
       (e.g., sections[0].http_method_defaults, sections[0].http_method_defaults[0].method)

    Container matching is triggered when the pattern points to a container field
    (list or dict), allowing artifact roots to be defined at the container level
    while detection still works for leaf fields within that container.

    Args:
        field_path: The actual field path (e.g., "sections[0].http_method_defaults[0].method").
        root_path_pattern: The pattern to match (e.g., "sections[*].http_method_defaults").

    Returns:
        True if the field path matches the pattern (exact or prefix match).
    """
    # Convert pattern to regex
    # Replace [*] with [\d+] for matching any index
    # Escape dots for regex
    regex_pattern = root_path_pattern.replace("[*]", r"\[\d+\]")
    regex_pattern = regex_pattern.replace(".", r"\.")

    # First try exact match
    exact_regex = f"^{regex_pattern}$"
    if re.match(exact_regex, field_path):
        return True

    # Then try prefix match (for container-level roots)
    # Allow the field_path to extend beyond the pattern with . or [
    prefix_regex = f"^{regex_pattern}(?:[.\\[]|$)"
    return bool(re.match(prefix_regex, field_path))


def _check_sibling_constraints(
    parent_data: dict[str, Any] | None,
    sibling_constraints: list[dict[str, Any]],
) -> bool:
    """Check if parent data satisfies sibling constraints.

    Args:
        parent_data: The parent dict containing sibling fields.
        sibling_constraints: List of constraint definitions with key and operator.

    Returns:
        True if all constraints are satisfied.
    """
    if not parent_data or not sibling_constraints:
        return True

    for constraint in sibling_constraints:
        if not isinstance(constraint, dict):
            continue

        key = constraint.get("key")
        if not key or key not in parent_data:
            return False

        sibling_value = parent_data.get(key)

        # Check equals operator
        if "equals" in constraint:
            if sibling_value != constraint["equals"]:
                return False

        # Check matches operator (regex)
        if "matches" in constraint:
            try:
                if not re.match(constraint["matches"], str(sibling_value)):
                    return False
            except re.error:
                return False

        # Check starts_with operator
        if "starts_with" in constraint:
            if not str(sibling_value).startswith(constraint["starts_with"]):
                return False

        # Check ends_with operator
        if "ends_with" in constraint:
            if not str(sibling_value).endswith(constraint["ends_with"]):
                return False

    return True


def _check_content_sniff(
    value: Any,  # noqa: ANN401
    content_sniff: dict[str, Any],
) -> bool:
    """Check if value content matches sniffing rules.

    Args:
        value: The field value to check.
        content_sniff: Content sniffing rules (starts_with_any, matches, etc.).

    Returns:
        True if content matches sniffing rules.
    """
    if not content_sniff or not isinstance(value, str):
        return True if not content_sniff else False

    # Check starts_with_any
    starts_with_any = content_sniff.get("starts_with_any", [])
    if starts_with_any:
        if not any(value.startswith(prefix) for prefix in starts_with_any):
            return False

    # Check ends_with_any
    ends_with_any = content_sniff.get("ends_with_any", [])
    if ends_with_any:
        if not any(value.endswith(suffix) for suffix in ends_with_any):
            return False

    # Check matches (regex)
    matches = content_sniff.get("matches")
    if matches:
        try:
            if not re.search(matches, value):
                return False
        except re.error:
            return False

    return True


@dataclass
class ArtifactMatch:
    """Result of matching a field against artifact kind registry.

    Attributes:
        kind_id: The matched artifact kind ID.
        artifact_format: MIME type for the artifact.
    """

    kind_id: str
    artifact_format: str | None


def _is_artifact_root(
    key: str,
    value_kind: ValueKind,
    field_path: str,
    parent_data: dict[str, Any] | None = None,
    value: Any = None,  # noqa: ANN401
    registry_cache: list[dict[str, Any]] | None = None,
) -> ArtifactMatch | None:
    """Determine if a field is an artifact root using the Artifact Kind Registry.

    Per fact_redesign.md lines 221-229, artifact roots are discovered by deterministic
    rules based on:
    - field_path / key name (e.g., text/description/summary)
    - sibling + parent structure (e.g., objects with type: code)
    - content sniffing (e.g., Mermaid preambles like sequenceDiagram)

    Args:
        key: The field key name.
        value_kind: The classified value kind.
        field_path: Full path from element root.
        parent_data: Parent dict for sibling inspection (optional).
        value: The actual field value for content sniffing (optional).
        registry_cache: Optional registry cache for testing.

    Returns:
        ArtifactMatch if the field is an artifact root, None otherwise.
    """
    registry = registry_cache if registry_cache is not None else _load_artifact_registry()

    if not registry:
        return None

    for kind in registry:
        if not isinstance(kind, dict):
            continue

        kind_id = kind.get("kind_id")
        if not kind_id:
            continue

        pattern = kind.get("structure_pattern", {})
        if not isinstance(pattern, dict):
            continue

        # Check root_path match
        root_path = pattern.get("root_path")
        if root_path and not _match_root_path(field_path, root_path):
            continue

        # Check sibling constraints
        sibling_constraints = pattern.get("sibling_constraints", [])
        if sibling_constraints and not _check_sibling_constraints(parent_data, sibling_constraints):
            continue

        # Check content sniff
        content_sniff = pattern.get("content_sniff", {})
        if content_sniff and not _check_content_sniff(value, content_sniff):
            continue

        # If we get here, all checks passed - this is an artifact root
        rendering = kind.get("rendering_contract", {})
        artifact_format = rendering.get("output_mime") if isinstance(rendering, dict) else None

        return ArtifactMatch(kind_id=kind_id, artifact_format=artifact_format)

    return None


@dataclass
class RoleAssignment:
    """Result of role assignment including artifact metadata.

    Attributes:
        role: The assigned FieldRole.
        artifact_kind: Artifact kind ID if role == artifact_root.
        artifact_format: MIME type if role == artifact_root.
    """

    role: FieldRole
    artifact_kind: str | None = None
    artifact_format: str | None = None


# Type aliases for Artifact fields per fact_redesign.md lines 296-323
SourceLocator = Literal["inline", "reference"]
RenderEngine = Literal["text_llm", "none"]
Modality = Literal["text", "image", "audio", "video", "other"]
ExtractionMode = Literal["full", "incremental", "query_only"]


def _compute_artifact_id(
    source_file: str,
    element_id: str,
    field_path: str,
    artifact_kind: str,
) -> str:
    """Compute a stable artifact ID as SHA-256 hash.

    Per fact_redesign.md lines 297-298, artifact_id is computed as:
    sha256(f"{source_file}:{element_id}:{field_path}:{artifact_kind}")

    Args:
        source_file: Relative path to the source YAML file.
        element_id: The ID of the source element.
        field_path: The artifact root field path within the element.
        artifact_kind: The artifact kind identifier.

    Returns:
        SHA-256 hash of the concatenated string.
    """
    concat = f"{source_file}:{element_id}:{field_path}:{artifact_kind}"
    return hashlib.sha256(concat.encode("utf-8")).hexdigest()


@dataclass
class Artifact:
    """Represents an artifact bridging structural FieldFacts and semantic extraction.

    Per fact_redesign.md lines 282-323, an Artifact is an irreducible, user-facing
    view rendered from a collection of facts. Artifacts are not edited directly—
    editing occurs by changing underlying facts and re-rendering.

    Artifacts exist because:
    - Documentation fields (paragraphs, code blocks, tables) are dense integrated facts
    - Users consume integrated views, not atomized facts
    - Validation requires a closed loop: extract facts → re-render → compare

    Attributes:
        artifact_id: Stable identifier (sha256 of source_file:element_id:field_path:kind).
        artifact_kind: Registry kind identifier (e.g., prose/paragraph, diagram/mermaid.sequence).
        artifact_format: MIME type for textual artifacts (e.g., text/markdown, text/x-mermaid).
        source_file: Relative path to the source YAML file.
        source_element_id: The ID of the source element.
        field_path: The artifact root field path within the element.
        source_locator: How artifact content is located (inline/reference).
        source_uri: URI when source_locator == reference (optional).
        render_engine: Renderer to use (text_llm/none).
        render_plan_id: Identifier for the deterministic render procedure.
        projection_version: Ties to the FieldFact projection version.
        modality: Reserved schema hook (text/image/audio/video/other), defaults to text.
        extraction_mode: Reserved schema hook (full/incremental/query_only), defaults to full.
    """

    artifact_id: str
    artifact_kind: str
    artifact_format: str
    source_file: str
    source_element_id: str
    field_path: str
    source_locator: SourceLocator
    source_uri: str | None
    render_engine: RenderEngine
    render_plan_id: str
    projection_version: str
    modality: Modality = "text"
    extraction_mode: ExtractionMode = "full"


def _get_render_engine_for_kind(artifact_kind: str) -> RenderEngine:
    """Determine the render engine based on artifact kind.

    Per fact_redesign.md lines 311-312, render_engine determines how artifacts
    are rendered. Default is 'text_llm' for prose/code/diagram kinds, 'none'
    for schema/data kinds that are tracked but not re-rendered.

    Args:
        artifact_kind: The artifact kind identifier.

    Returns:
        The appropriate render engine.
    """
    # Schema and data kinds are tracked but not re-rendered
    if artifact_kind.startswith("schema/") or artifact_kind.startswith("data/"):
        return "none"
    # Default to text_llm for prose, code, diagram, table kinds
    return "text_llm"


def _get_render_plan_id_from_registry(
    artifact_kind: str,
    registry_cache: list[dict[str, Any]] | None = None,
) -> str:
    """Get the render_plan_id from the artifact registry for a given kind.

    Args:
        artifact_kind: The artifact kind identifier.
        registry_cache: Optional registry cache for testing.

    Returns:
        The render_plan_id from the registry, or a default placeholder.
    """
    registry = registry_cache if registry_cache is not None else _load_artifact_registry()

    for kind in registry:
        if not isinstance(kind, dict):
            continue
        if kind.get("kind_id") == artifact_kind:
            rendering = kind.get("rendering_contract", {})
            if isinstance(rendering, dict):
                plan_id = rendering.get("render_plan_id")
                if plan_id:
                    return str(plan_id)
            break

    # Default render_plan_id based on artifact_kind pattern
    # Convert kind_id to render_plan format: diagram/mermaid.sequence -> diagram.mermaid.sequence.v1
    safe_kind = artifact_kind.replace("/", ".").replace("-", "_")
    return f"{safe_kind}.v1"


def _get_modality_and_extraction_mode_from_registry(
    artifact_kind: str,
    registry_cache: list[dict[str, Any]] | None = None,
) -> tuple[Modality, ExtractionMode]:
    """Get modality and extraction_mode from the artifact registry for a given kind.

    Per fact_redesign.md lines 367-368, these are optional metadata fields in the
    registry with defaults: modality='text', extraction_mode='full'.

    Args:
        artifact_kind: The artifact kind identifier.
        registry_cache: Optional registry cache for testing.

    Returns:
        Tuple of (modality, extraction_mode) from the registry, or defaults.
    """
    registry = registry_cache if registry_cache is not None else _load_artifact_registry()

    for kind in registry:
        if not isinstance(kind, dict):
            continue
        if kind.get("kind_id") == artifact_kind:
            # Get modality with default to 'text'
            raw_modality = kind.get("modality", "text")
            if raw_modality in ("text", "image", "audio", "video", "other"):
                modality: Modality = raw_modality  # type: ignore[assignment]
            else:
                modality = "text"

            # Get extraction_mode with default to 'full'
            raw_mode = kind.get("extraction_mode", "full")
            if raw_mode in ("full", "incremental", "query_only"):
                extraction_mode: ExtractionMode = raw_mode  # type: ignore[assignment]
            else:
                extraction_mode = "full"

            return modality, extraction_mode

    # Defaults when kind not found in registry
    return "text", "full"


def detect_artifacts_from_field_facts(
    field_facts: dict[str, list[FieldFact]],
    source_file: str,
    registry_cache: list[dict[str, Any]] | None = None,
    v1_only: bool = True,
) -> list[Artifact]:
    """Detect artifacts from FieldFacts with role='artifact_root'.

    Per fact_redesign.md lines 561-569, this implements artifact lifecycle step 1:
    detect artifact roots and assign artifact_kind, artifact_format, render_engine,
    and render_plan_id.

    V1 participation rule (lines 36-42): Only artifacts with modality='text' AND
    extraction_mode='full' participate in current extraction/rendering pipelines.

    Args:
        field_facts: Dictionary mapping element_id to list of FieldFacts.
        source_file: Relative path to the source YAML file.
        registry_cache: Optional registry cache for testing.
        v1_only: If True, skip artifacts that don't match V1 participation rule.

    Returns:
        List of Artifact objects detected from artifact root FieldFacts.
    """
    artifacts: list[Artifact] = []

    for element_id, facts in field_facts.items():
        for fact in facts:
            if fact.role != "artifact_root":
                continue

            if not fact.artifact_kind:
                _logger.warning(
                    "FieldFact with role=artifact_root missing artifact_kind: "
                    "element_id=%s, field_path=%s",
                    element_id,
                    fact.field_path,
                )
                continue

            # Determine artifact properties
            artifact_kind = fact.artifact_kind
            artifact_format = fact.artifact_format or "text/plain"

            # Get source_locator from FieldFact
            source_locator: SourceLocator = fact.artifact_locator or "inline"
            source_uri = fact.artifact_uri

            # Validate source_uri requirement
            if source_locator == "reference" and not source_uri:
                _logger.warning(
                    "Artifact with source_locator=reference missing source_uri: "
                    "element_id=%s, field_path=%s",
                    element_id,
                    fact.field_path,
                )
                continue

            # Get render properties
            render_engine = _get_render_engine_for_kind(artifact_kind)
            render_plan_id = _get_render_plan_id_from_registry(artifact_kind, registry_cache)

            # Compute stable artifact_id
            artifact_id = _compute_artifact_id(
                source_file, element_id, fact.field_path, artifact_kind
            )

            # Get modality and extraction_mode from registry (defaults to text/full)
            modality, extraction_mode = _get_modality_and_extraction_mode_from_registry(
                artifact_kind, registry_cache
            )

            # Apply V1 participation rule
            if v1_only and (modality != "text" or extraction_mode != "full"):
                _logger.debug(
                    "Skipping non-V1 artifact: element_id=%s, field_path=%s, "
                    "modality=%s, extraction_mode=%s",
                    element_id,
                    fact.field_path,
                    modality,
                    extraction_mode,
                )
                continue

            artifact = Artifact(
                artifact_id=artifact_id,
                artifact_kind=artifact_kind,
                artifact_format=artifact_format,
                source_file=source_file,
                source_element_id=element_id,
                field_path=fact.field_path,
                source_locator=source_locator,
                source_uri=source_uri,
                render_engine=render_engine,
                render_plan_id=render_plan_id,
                projection_version="fieldfacts.v2",
                modality=modality,
                extraction_mode=extraction_mode,
            )
            artifacts.append(artifact)

    return artifacts


def _assign_role(
    key: str,
    value_kind: ValueKind,
    field_path: str,
    parent_data: dict[str, Any] | None = None,
    value: Any = None,  # noqa: ANN401
    registry_cache: list[dict[str, Any]] | None = None,
) -> RoleAssignment:
    """Assign a semantic role to a field based on deterministic rules.

    Role assignment follows the rules in fact_redesign.md lines 210-235:
    1. If value_kind == "ref" -> role = entity_ref
    2. If key in metadata keys -> role = metadata
    3. If field is artifact root -> role = artifact_root
    4. Otherwise -> role = constraint

    Args:
        key: The field key name.
        value_kind: The classified value kind.
        field_path: Full path from element root.
        parent_data: Parent dict for context (optional).
        value: The actual field value for content sniffing (optional).
        registry_cache: Optional registry cache for testing.

    Returns:
        RoleAssignment with role and optional artifact metadata.
    """
    # Rule 1: $ref values are entity references
    if value_kind == "ref":
        return RoleAssignment(role="entity_ref")

    # Rule 2: Known metadata keys
    if key in METADATA_KEYS:
        return RoleAssignment(role="metadata")

    # Rule 3: Artifact root detection using registry
    artifact_match = _is_artifact_root(
        key, value_kind, field_path, parent_data, value, registry_cache
    )
    if artifact_match:
        return RoleAssignment(
            role="artifact_root",
            artifact_kind=artifact_match.kind_id,
            artifact_format=artifact_match.artifact_format,
        )

    # Rule 4: Default to constraint
    return RoleAssignment(role="constraint")


# Regex pattern for list index in field path (e.g., [0], [1], [123])
_LIST_INDEX_PATTERN = re.compile(r"\[(\d+)\]")


def _compute_group_key(
    scope_path: str,
    field_path: str,
    parent_data: dict[str, Any] | None = None,
) -> str:
    """Compute the semantic grouping key for a field.

    Per fact_redesign.md lines 236-260, fields are grouped into semantic units:
    - Default grouping: group_key = scope_path
    - Discriminator-based grouping for known patterns:
      - http_method_defaults[*] uses discriminator "method"
      - sample_code uses discriminator "language" (optional)

    Args:
        scope_path: The scope path (prefix of field_path).
        field_path: Full path from element root.
        parent_data: Parent dict containing discriminator fields.

    Returns:
        The computed group_key string.
    """
    # Extract container name from scope_path for discriminator matching
    # e.g., "http_method_defaults[0]" -> "http_method_defaults"
    container_name = _LIST_INDEX_PATTERN.sub("", scope_path).rstrip(".")

    # Check for http_method_defaults discriminator pattern
    # Example: docs/development/general/general.rest.api-patterns.yml lines 61-94
    if container_name == "http_method_defaults" and parent_data is not None:
        method = parent_data.get("method")
        if method is not None:
            return f"http_method_defaults::method={method}"

    # Check for sample_code discriminator pattern
    # Example: docs/development/general/general.python.docstrings-guide.yml lines 58-71
    if container_name == "sample_code" and parent_data is not None:
        language = parent_data.get("language")
        if language is not None:
            return f"sample_code::language={language}"

    # Default: use scope_path as group_key
    return scope_path if scope_path else "<root>"


def _compute_group_id(group_key: str) -> str:
    """Compute the group_id as SHA-256 hash of group_key.

    Args:
        group_key: The semantic grouping key.

    Returns:
        SHA-256 hash of the group_key.
    """
    return hashlib.sha256(group_key.encode("utf-8")).hexdigest()


def _iter_field_facts(
    element_id: str,
    sliced_data: dict[str, Any],
    ancestors: list[str],
    source_file: str,
) -> list[FieldFact]:
    """Extract FieldFacts from a sliced element.

    Traverses the sliced element data and emits a FieldFact for each scalar
    or ref value encountered. Nested dicts without IDs are recursed into.
    List indices are included in field_path as [0], [1], etc.

    Per fact_redesign.md lines 261-272:
    - Skip root "id" field to avoid self-reference
    - For dicts-without-id, recurse
    - For lists, recurse with indices in path
    - When hitting a scalar or ref, emit a FieldFact
    - Stop recursion at $ref values (treat as leaf)

    Args:
        element_id: The ID of the element being processed.
        sliced_data: The sliced dict data (nested IDs replaced with $refs).
        ancestors: List of ancestor element IDs.
        source_file: Relative path to source YAML file.

    Returns:
        List of FieldFact instances extracted from the element.
    """
    facts: list[FieldFact] = []

    def _is_scalar(value: Any) -> bool:  # noqa: ANN401
        """Check if value is a scalar (not dict or list)."""
        return isinstance(value, (str, int, float, bool)) or value is None

    def _walk(
        node: Any,  # noqa: ANN401
        path: str,
        container_dict: dict[str, Any] | None = None,
    ) -> None:
        """Recursively walk the data structure and emit FieldFacts.

        Args:
            node: Current node being walked.
            path: Current field path from element root.
            container_dict: The immediate container dict for discriminator lookup.
                For fields within a dict, this is the dict itself (e.g., the
                http_method_defaults item dict containing "method" discriminator).
        """
        if isinstance(node, dict):
            # Check if this is a $ref (treat as leaf, emit entity_ref)
            if "$ref" in node and isinstance(node["$ref"], str):
                # This is handled by the parent call when the key is encountered
                return

            for key, value in node.items():
                # Skip root id field to avoid self-reference
                if key == "id" and not path:
                    continue

                child_path = f"{path}.{key}" if path else key

                # Determine if value is a leaf (scalar or $ref)
                if _is_scalar(value):
                    # Emit scalar FieldFact
                    # For fields within this dict, use `node` as container_dict
                    # so _compute_group_key can access discriminator fields
                    scope_path, _, _ = child_path.rpartition(".")
                    value_kind = _determine_value_kind(value)
                    role_assignment = _assign_role(key, value_kind, child_path, node, value)
                    group_key = _compute_group_key(scope_path, child_path, node)
                    group_id = _compute_group_id(group_key)

                    # Populate artifact metadata for artifact roots
                    artifact_locator: ArtifactLocator | None = None
                    if role_assignment.role == "artifact_root":
                        artifact_locator = "inline"

                    facts.append(
                        FieldFact(
                            element_id=element_id,
                            field_path=child_path,
                            key=key,
                            scope_path=scope_path,
                            value=value,
                            value_kind=value_kind,
                            ancestors=list(ancestors),
                            source_file=source_file,
                            role=role_assignment.role,
                            artifact_kind=role_assignment.artifact_kind,
                            artifact_format=role_assignment.artifact_format,
                            artifact_locator=artifact_locator,
                            artifact_uri=None,
                            group_key=group_key,
                            group_id=group_id,
                        )
                    )
                elif isinstance(value, dict):
                    # Check if it's a $ref
                    if "$ref" in value and isinstance(value["$ref"], str):
                        # Emit entity_ref FieldFact for $ref
                        scope_path, _, _ = child_path.rpartition(".")
                        value_kind: ValueKind = "ref"
                        role_assignment = _assign_role(key, value_kind, child_path, node, value)
                        group_key = _compute_group_key(scope_path, child_path, node)
                        group_id = _compute_group_id(group_key)

                        facts.append(
                            FieldFact(
                                element_id=element_id,
                                field_path=child_path,
                                key=key,
                                scope_path=scope_path,
                                value=value,
                                value_kind=value_kind,
                                ancestors=list(ancestors),
                                source_file=source_file,
                                role=role_assignment.role,
                                artifact_kind=None,
                                artifact_format=None,
                                artifact_locator=None,
                                artifact_uri=None,
                                group_key=group_key,
                                group_id=group_id,
                            )
                        )
                    else:
                        # Recurse into nested dict (no id)
                        # Pass `value` as container_dict so its fields can use it
                        _walk(value, child_path, value)
                elif isinstance(value, list):
                    # Handle list - recurse with indices
                    for idx, item in enumerate(value):
                        item_path = f"{child_path}[{idx}]"
                        if _is_scalar(item):
                            # Emit scalar list item FieldFact
                            # For scalars in a list, use node as container
                            value_kind = _determine_value_kind(item)
                            role_assignment = _assign_role(
                                str(idx), value_kind, item_path, node, item
                            )
                            group_key = _compute_group_key(child_path, item_path, node)
                            group_id = _compute_group_id(group_key)

                            # Populate artifact metadata for artifact roots
                            item_artifact_locator: ArtifactLocator | None = None
                            if role_assignment.role == "artifact_root":
                                item_artifact_locator = "inline"

                            facts.append(
                                FieldFact(
                                    element_id=element_id,
                                    field_path=item_path,
                                    key=str(idx),
                                    scope_path=child_path,
                                    value=item,
                                    value_kind=value_kind,
                                    ancestors=list(ancestors),
                                    source_file=source_file,
                                    role=role_assignment.role,
                                    artifact_kind=role_assignment.artifact_kind,
                                    artifact_format=role_assignment.artifact_format,
                                    artifact_locator=item_artifact_locator,
                                    artifact_uri=None,
                                    group_key=group_key,
                                    group_id=group_id,
                                )
                            )
                        elif isinstance(item, dict):
                            # Check if it's a $ref - emit as entity_ref, don't recurse
                            if "$ref" in item and isinstance(item["$ref"], str):
                                value_kind = _determine_value_kind(item)
                                role_assignment = _assign_role(
                                    str(idx), value_kind, item_path, node, item
                                )
                                group_key = _compute_group_key(
                                    child_path, item_path, node
                                )
                                group_id = _compute_group_id(group_key)

                                facts.append(
                                    FieldFact(
                                        element_id=element_id,
                                        field_path=item_path,
                                        key=str(idx),
                                        scope_path=child_path,
                                        value=item,
                                        value_kind=value_kind,
                                        ancestors=list(ancestors),
                                        source_file=source_file,
                                        role=role_assignment.role,
                                        artifact_kind=None,
                                        artifact_format=None,
                                        artifact_locator=None,
                                        artifact_uri=None,
                                        group_key=group_key,
                                        group_id=group_id,
                                    )
                                )
                            else:
                                # Recurse into list item dict (not a $ref)
                                # Pass `item` as container_dict for discriminator lookup
                                # This allows http_method_defaults[0].method to access
                                # the item dict's "method" field
                                _walk(item, item_path, item)
                        elif isinstance(item, list):
                            # Nested list - recurse
                            _walk(item, item_path, container_dict)

        elif isinstance(node, list):
            # Handle top-level list (unusual but possible)
            for idx, item in enumerate(node):
                item_path = f"{path}[{idx}]" if path else f"[{idx}]"
                if _is_scalar(item):
                    value_kind = _determine_value_kind(item)
                    role_assignment = _assign_role(
                        str(idx), value_kind, item_path, container_dict, item
                    )
                    group_key = _compute_group_key(path, item_path, container_dict)
                    group_id = _compute_group_id(group_key)

                    # Populate artifact metadata for artifact roots
                    top_artifact_locator: ArtifactLocator | None = None
                    if role_assignment.role == "artifact_root":
                        top_artifact_locator = "inline"

                    facts.append(
                        FieldFact(
                            element_id=element_id,
                            field_path=item_path,
                            key=str(idx),
                            scope_path=path,
                            value=item,
                            value_kind=value_kind,
                            ancestors=list(ancestors),
                            source_file=source_file,
                            role=role_assignment.role,
                            artifact_kind=role_assignment.artifact_kind,
                            artifact_format=role_assignment.artifact_format,
                            artifact_locator=top_artifact_locator,
                            artifact_uri=None,
                            group_key=group_key,
                            group_id=group_id,
                        )
                    )
                elif isinstance(item, dict):
                    # Recurse into list item dict, passing item as container
                    _walk(item, item_path, item)
                else:
                    _walk(item, item_path, container_dict)

    _walk(sliced_data, "", None)
    return facts


def _build_ancestors_map(
    edges: list[ContainmentEdge],
) -> dict[str, list[str]]:
    """Build a map from element_id to list of ancestor element IDs.

    Traverses containment edges to compute the ancestor chain for each element,
    ordered from outermost (root) to nearest (immediate parent).

    Args:
        edges: List of ContainmentEdge instances from extract_ids_and_objects.

    Returns:
        Dictionary mapping element_id to list of ancestor IDs (outermost first).
    """
    # Build parent lookup: child_id -> parent_id
    parent_lookup: dict[str, str] = {}
    for edge in edges:
        parent_lookup[edge.child_id] = edge.parent_id

    # Compute ancestors for each element
    ancestors_map: dict[str, list[str]] = {}

    def get_ancestors(element_id: str) -> list[str]:
        """Recursively build ancestor list for an element."""
        if element_id in ancestors_map:
            return ancestors_map[element_id]

        parent_id = parent_lookup.get(element_id)
        if parent_id is None:
            # No parent - this is a root element
            ancestors_map[element_id] = []
            return []

        # Get parent's ancestors and append parent
        parent_ancestors = get_ancestors(parent_id)
        ancestors = parent_ancestors + [parent_id]
        ancestors_map[element_id] = ancestors
        return ancestors

    # Populate ancestors for all children
    for edge in edges:
        get_ancestors(edge.child_id)

    return ancestors_map


def _index_elements(
    data: YamlValue,
    path: str = "",
    ancestor_ids: list[str] | None = None,
) -> dict[str, ElementContext]:
    """Recursively build id→ElementContext map with ancestor tracking.

    Traverses dicts/lists, detects elements (dicts with string `id`), accumulates
    ancestor IDs, and records YAML paths. This enables text projection with
    ancestor chain formatting.

    Per fact_redesign.md lines 1088-1120, this produces the mapping needed for:
    - Ancestor chain construction in _fact_to_line
    - Element lookup by ID for text projection
    - YAML path context for structural tracing

    Args:
        data: The parsed YAML structure (dict, list, or primitive).
        path: Current YAML path (e.g., "sections[0].items[2]").
        ancestor_ids: List of ancestor element IDs accumulated so far.

    Returns:
        Dictionary mapping element_id to ElementContext.
    """
    if ancestor_ids is None:
        ancestor_ids = []

    result: dict[str, ElementContext] = {}

    if isinstance(data, dict):
        element_id = data.get("id")
        if isinstance(element_id, str):
            ctx = ElementContext(
                id=element_id,
                obj=data,
                path=path or "$",
                ancestors=list(ancestor_ids),
            )
            result[element_id] = ctx
            # Update ancestor list for children
            ancestor_ids = ancestor_ids + [element_id]

        for key, value in data.items():
            child_path = f"{path}.{key}" if path else key
            result.update(_index_elements(value, child_path, ancestor_ids))

    elif isinstance(data, list):
        for idx, item in enumerate(data):
            child_path = f"{path}[{idx}]" if path else f"[{idx}]"
            result.update(_index_elements(item, child_path, ancestor_ids))

    return result


def extract_field_facts(
    data: Any,  # noqa: ANN401
    source_file: str = "",
) -> dict[str, list[FieldFact]]:
    """Extract FieldFacts from parsed YAML data.

    This is the primary API for downstream consumers that need structured
    field-level access (e.g., artifact detection, entity resolution).

    Calls extract_ids_and_objects to get sliced elements and containment edges,
    then extracts FieldFacts from each element with proper ancestor tracking.

    Per fact_redesign.md lines 273-279, this produces the canonical field-level
    representation that is:
    - Aware of field names
    - Anchored in element ID
    - Can reconstruct constraint groups (via group_key/group_id)
    - Distinguishes role (constraint vs entity_ref vs artifact_root vs metadata)
    - Tracks ancestor chain from containment edges

    Args:
        data: The parsed YAML structure (dict, list, or primitive).
        source_file: Relative path to the source file.

    Returns:
        Dictionary mapping element_id to list of FieldFacts.
    """
    sliced_objects, edges = extract_ids_and_objects(data, source_file=source_file)
    result: dict[str, list[FieldFact]] = {}

    # Build ancestor map from containment edges
    ancestors_map = _build_ancestors_map(edges)

    for element_id, sliced_dict in sliced_objects.items():
        ancestors = ancestors_map.get(element_id, [])
        facts = _iter_field_facts(
            element_id=element_id,
            sliced_data=sliced_dict,
            ancestors=ancestors,
            source_file=source_file,
        )
        result[element_id] = facts

    return result


def _is_element(obj: Any) -> bool:  # noqa: ANN401
    """Check if a value is an element (dict with string id field).

    Args:
        obj: Value to check.

    Returns:
        True if obj is a dict with a string 'id' field, False otherwise.
    """
    return isinstance(obj, dict) and isinstance(obj.get("id"), str)


def _slice_element(
    data: Any,  # noqa: ANN401
    parent_id: str,
    field_path_prefix: str,
    source_file: str,
    containment_edges: list[ContainmentEdge],
) -> Any:  # noqa: ANN401
    """Recursively slice an element, replacing nested ID-bearing dicts with refs.

    Traverses the data structure and replaces any nested dict that has its own
    string `id` field with a reference `{"$ref": "child_id"}`. For each such
    replacement, a ContainmentEdge is appended to the provided list.

    Args:
        data: The data structure to slice (part of the parent element).
        parent_id: The ID of the parent element being sliced.
        field_path_prefix: Current field path prefix (e.g., "items[0].routes").
        source_file: Relative path to the source YAML file.
        containment_edges: List to append ContainmentEdge records to.

    Returns:
        The sliced data structure with nested elements replaced by refs.
    """
    if isinstance(data, dict):
        # If this dict has its own id (and is not the root), it's a child element
        if _is_element(data) and field_path_prefix:
            child_id = data["id"]
            containment_edges.append(
                ContainmentEdge(
                    parent_id=parent_id,
                    child_id=child_id,
                    field_path=field_path_prefix,
                    source_file=source_file,
                )
            )
            return {"$ref": child_id}

        # Recursively slice dict values
        sliced: dict[str, Any] = {}
        for key, value in data.items():
            new_path = f"{field_path_prefix}.{key}" if field_path_prefix else key
            sliced[key] = _slice_element(
                value, parent_id, new_path, source_file, containment_edges
            )
        return sliced

    if isinstance(data, list):
        # Recursively slice list items
        sliced_list: list[Any] = []
        for index, item in enumerate(data):
            new_path = f"{field_path_prefix}[{index}]"
            sliced_list.append(
                _slice_element(item, parent_id, new_path, source_file, containment_edges)
            )
        return sliced_list

    # Primitives pass through unchanged
    return data


DEVELOPMENT_DIR = REPO_ROOT / "docs" / "development"
SUBDIRS = ("python", "fastapi", "elasticsearch", "surrealdb")

# Centralized constant for the knowledge directory name to avoid duplication
KNOWLEDGE_DIR_NAME = ".knowledge"

YamlValue = str | int | float | bool | None | list["YamlValue"] | dict[str, "YamlValue"]
YamlStructure = dict[str, YamlValue] | list[YamlValue]

OriginType = Literal["original", "split_only", "orphan"]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for YAML document comparison.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace with path and original_files attributes.
    """
    parser = argparse.ArgumentParser(
        description="Compare original YAML documents with their split counterparts.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=DEVELOPMENT_DIR,
        help="Base directory containing original and split YAML files "
        "(default: docs/development/).",
    )
    parser.add_argument(
        "--original-files",
        nargs="*",
        type=Path,
        help="Optional list of timestamped original files from .knowledge/originals/ "
        "to use instead of globbing for original.*.yml files in the base path.",
    )
    return parser.parse_args(argv)


class SplitEntry(TypedDict):
    """A split file's object data for a specific ID."""

    split_data: dict[str, Any]
    source_file: str


class ComparisonEntry(TypedDict):
    """Comparison result for a single ID.

    The origin_type field indicates the source of this entry:
    - original: ID from an original.*.yml file with differing or missing split data
    - split_only: ID found in split files but not in the corresponding original
    - orphan: ID from a file in a subdirectory with no corresponding original file
    """

    source_file: str
    id: str
    source_data: dict[str, Any]
    splits: list[SplitEntry]
    origin_type: OriginType


class CompareResult(TypedDict):
    """Comparison results for a single original file."""

    original_file: str
    entries: list[ComparisonEntry]


def _validate_yaml_result(
    result: Any,  # noqa: ANN401
    file_path: Path,
) -> YamlStructure:
    """Validate that the parsed YAML result is a dict or list.

    Args:
        result: The parsed result from yaml.safe_load().
        file_path: Path to the file for error messages.

    Returns:
        The validated result as a dict or list.

    Raises:
        TypeError: If the result is not a dict or list.
    """
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        return result
    relative_path = file_path.relative_to(REPO_ROOT)
    msg = f"Unexpected YAML structure in {relative_path}: expected dict or list"
    raise TypeError(msg)


def parse_yaml_file(file_path: Path) -> YamlStructure:
    """Parse a YAML file and return its decoded structure.

    Reads the file content and parses it using PyYAML's safe_load.

    Args:
        file_path: Path to the YAML file to parse.

    Returns:
        The parsed YAML structure as a Python dict or list.

    Raises:
        yaml.YAMLError: If the file contains invalid YAML syntax.
        FileNotFoundError: If the file does not exist.
        TypeError: If the parsed result is not a dict or list.
        ValueError: If parsing fails for other reasons.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
        result = yaml.safe_load(content)
    except yaml.YAMLError:
        raise
    except FileNotFoundError:
        raise
    except Exception as exc:
        relative_path = file_path.relative_to(REPO_ROOT)
        msg = f"Failed to parse {relative_path}: {exc}"
        raise ValueError(msg) from exc
    else:
        return _validate_yaml_result(result, file_path)


def extract_ids_and_objects(
    data: YamlValue,
    parent_path: str = "",
    source_file: str = "",
) -> tuple[dict[str, dict[str, Any]], list[ContainmentEdge]]:
    """Recursively extract IDs and sliced objects from a YAML structure.

    Traverses the parsed YAML structure to find all elements with an 'id' field.
    For each element, nested ID-bearing dicts are sliced out and replaced with
    `{"$ref": "child_id"}` references. Containment edges are recorded for each
    such replacement.

    Per the YAML schema guidelines, `id` is required for root elements of sections
    but optional for children. This function only tracks elements that have an `id`
    field.

    Args:
        data: The parsed YAML structure (dict, list, or primitive).
        parent_path: Path string for debugging purposes (tracks traversal path).
        source_file: Relative path to the source file for containment edges.

    Returns:
        Tuple of (sliced_objects, containment_edges) where:
        - sliced_objects: Dict mapping element IDs to their sliced object data
          (child content excluded, replaced with $ref).
        - containment_edges: List of ContainmentEdge records for all nested
          ID-bearing dicts found.
    """
    result: dict[str, dict[str, Any]] = {}
    all_edges: list[ContainmentEdge] = []

    if isinstance(data, dict):
        if "id" in data:
            element_id = data["id"]
            if isinstance(element_id, str):
                # Slice this element: replace nested ID-bearing dicts with refs
                element_edges: list[ContainmentEdge] = []
                sliced_data = _slice_element(
                    data, element_id, "", source_file, element_edges
                )
                result[element_id] = sliced_data
                all_edges.extend(element_edges)

        for key, value in data.items():
            child_path = f"{parent_path}.{key}" if parent_path else key
            child_results, child_edges = extract_ids_and_objects(
                value, child_path, source_file
            )
            result.update(child_results)
            all_edges.extend(child_edges)

    elif isinstance(data, list):
        for index, item in enumerate(data):
            child_path = f"{parent_path}[{index}]"
            child_results, child_edges = extract_ids_and_objects(
                item, child_path, source_file
            )
            result.update(child_results)
            all_edges.extend(child_edges)

    return result, all_edges


def _format_value_for_text(value: Any) -> str:  # noqa: ANN401
    """Format a value for text projection output.

    Args:
        value: The value to format.

    Returns:
        String representation of the value for text projection.
    """
    if isinstance(value, dict):
        if "$ref" in value:
            return f"$ref:{value['$ref']}"
        # Nested dict without $ref - format as key=value pairs
        parts = [f"{k}={_format_value_for_text(v)}" for k, v in sorted(value.items())]
        return "{" + ", ".join(parts) + "}"
    if isinstance(value, list):
        formatted = [_format_value_for_text(item) for item in value]
        return "[" + ", ".join(formatted) + "]"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _fact_to_line(fact: FieldFact) -> str:
    """Format a FieldFact as a text line with ancestor chain.

    Constructs a canonical fact-line representation that includes:
    - Ancestor chain and element_id in brackets
    - Full field_path
    - Normalized value (scalars as strings, refs as $ref:child_id)

    Per fact_redesign.md lines 1224-1231, this format enables:
    - Structural context in text (ancestor elements)
    - Field names as part of the text (for NLP extraction)
    - $ref tokens for nested element relationships

    Args:
        fact: The FieldFact to format.

    Returns:
        Formatted string: "[ancestor > element_id] field_path = value"
    """
    # Build ancestor chain: "ancestor1 > ancestor2 > element_id"
    if fact.ancestors:
        chain = " > ".join(fact.ancestors + [fact.element_id])
    else:
        chain = fact.element_id

    # Format value: $ref:child_id for refs, otherwise str(value)
    if isinstance(fact.value, dict) and "$ref" in fact.value:
        value_str = f"$ref:{fact.value['$ref']}"
    else:
        value_str = _format_value_for_text(fact.value)

    return f"[{chain}] {fact.field_path} = {value_str}"


def extract_ids_and_text(
    data: YamlValue,
    source_file: str = "",
) -> dict[str, str]:
    """Extract IDs and synthetic fact-line text projections from FieldFacts.

    Uses the FieldFact pipeline to produce a deterministic text projection for
    each element. Each line encodes structural context:
    - Ancestor chain and element_id in brackets
    - Full field_path (field names as part of the text)
    - Normalized value ($ref:child_id for nested elements)

    This function is used for hashing in resolution_tracker and for
    candidate extraction context. Per the fact redesign (lines 1233-1258),
    the text projection is derived from the sliced representation with child
    content replaced by $ref tokens.

    The FieldFact-based approach ensures:
    - Field names are literally in the text (for NLP extraction)
    - Ancestor elements provide structural context
    - Nested entities appear only as $ref tokens, not inlined

    Projection version: fieldfacts.v2

    Args:
        data: The parsed YAML structure (dict, list, or primitive).
        source_file: Relative path to the source file for containment edges.

    Returns:
        Dictionary mapping element IDs to their synthetic fact-line text.
    """
    sliced_objects, edges = extract_ids_and_objects(data, source_file=source_file)
    result: dict[str, str] = {}

    # Build ancestor map from containment edges
    ancestors_map = _build_ancestors_map(edges)

    for element_id, sliced_dict in sliced_objects.items():
        # Extract FieldFacts for this element
        ancestors = ancestors_map.get(element_id, [])
        facts = _iter_field_facts(
            element_id=element_id,
            sliced_data=sliced_dict,
            ancestors=ancestors,
            source_file=source_file,
        )

        # Format each fact as a fact-line with ancestor chain
        lines = [_fact_to_line(f) for f in facts]
        # Sort by field_path for deterministic ordering
        lines.sort()
        result[element_id] = "\n".join(lines)

    return result


def compute_element_content_hash(
    data: YamlValue,
    element_id: str,
    source_file: str = "",
) -> str:
    """Compute SHA-256 hash of canonical FieldFact payload for an element.

    Provides a structural hash independent of text formatting. The hash is
    computed from a JSON serialization of FieldFact payloads (field_path,
    value_kind, value), sorted by field_path for determinism.

    Per fact_redesign.md lines 1446-1469, this enables:
    - Stable content hashes that don't change with text projection formatting
    - Hash changes when field values/names change
    - Hash independence from nested element internals (due to $ref replacement)

    Args:
        data: The parsed YAML structure containing the element.
        element_id: The ID of the element to hash.
        source_file: Relative path to the source file for containment edges.

    Returns:
        SHA-256 hex digest of the canonical FieldFact payload.

    Raises:
        KeyError: If element_id is not found in the data.
    """
    sliced_objects, edges = extract_ids_and_objects(data, source_file=source_file)

    if element_id not in sliced_objects:
        msg = f"Element '{element_id}' not found in data"
        raise KeyError(msg)

    sliced_dict = sliced_objects[element_id]

    # Build ancestor map from containment edges
    ancestors_map = _build_ancestors_map(edges)
    ancestors = ancestors_map.get(element_id, [])

    # Extract FieldFacts
    facts = _iter_field_facts(
        element_id=element_id,
        sliced_data=sliced_dict,
        ancestors=ancestors,
        source_file=source_file,
    )

    # Build canonical payload: sorted list of (field_path, value_kind, value)
    payload = [
        {
            "field_path": f.field_path,
            "value_kind": f.value_kind,
            "value": f.value,
        }
        for f in sorted(facts, key=lambda f: f.field_path)
    ]

    # JSON serialize with sort_keys for determinism
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def find_originals(
    base_path: Path,
    original_files: list[Path] | None = None,
) -> list[Path]:
    """Find all original YAML files in the development directory.

    When original_files is provided, uses those files instead of globbing.
    Otherwise, finds top-level files matching the pattern 'original.*.yml'.

    Args:
        base_path: Base directory to search for original files (used for glob fallback).
        original_files: Optional list of explicit original file paths to use.
            When provided and non-empty, these files are used instead of globbing.

    Returns:
        Sorted list of paths to original YAML files.
    """
    if original_files:
        valid_files: list[Path] = []
        for file_path in original_files:
            if file_path.exists() and file_path.is_file():
                valid_files.append(file_path)
            else:
                print(
                    f"Warning: Provided original file does not exist: {file_path}",
                    file=sys.stderr,
                )
        return sorted(valid_files)

    pattern = "original.*.yml"
    return sorted(base_path.glob(pattern))


def find_all_yml(base_path: Path) -> list[Path]:
    """Find all YAML files in subdirectories of the development directory.

    Args:
        base_path: Base directory containing subdirectories to search.

    Returns:
        Sorted list of paths to all YAML files in subdirectories.
    """
    files: list[Path] = []
    for subdir in SUBDIRS:
        subdir_path = base_path / subdir
        if subdir_path.is_dir():
            files.extend(subdir_path.glob("*.yml"))
    return sorted(files)


def _strip_timestamp_prefix(name: str) -> str:
    """Strip ISO 8601 timestamp prefix from a filename stem if present.

    Handles timestamped filenames like '20251201T134735Z-api-patterns' by
    stripping the timestamp prefix up to and including the first hyphen.

    Args:
        name: Filename stem to process.

    Returns:
        The stem with timestamp prefix stripped, or original if no match.
    """
    # Match ISO 8601 basic format timestamp: YYYYMMDDTHHMMSSZ-
    match = re.match(r"^\d{8}T\d{6}Z-(.+)$", name)
    if match:
        return match.group(1)
    return name


def pattern_from_path(path: Path) -> str:
    """Extract the pattern name from a YAML file path.

    For 'original.api-patterns.yml', returns 'api-patterns'.
    For 'python.api-patterns.yml', returns 'api-patterns'.
    For '20251201T134735Z-api-patterns.yml', returns 'api-patterns'.

    Args:
        path: Path to a YAML file.

    Returns:
        The extracted pattern name.
    """
    name = path.stem

    # Handle timestamped originals: 20251201T134735Z-api-patterns -> api-patterns
    name = _strip_timestamp_prefix(name)

    if name.startswith("original."):
        return name[len("original.") :]
    parts = name.split(".", 1)
    if len(parts) == 2:
        return parts[1]
    return name


def find_mapped_splits(pattern: str, base_path: Path) -> dict[str, Path]:
    """Find all split files that match a given pattern.

    For pattern 'api-patterns', finds files like 'python.api-patterns.yml',
    'fastapi.api-patterns.yml', etc.

    Args:
        pattern: The pattern name to search for.
        base_path: Base directory containing subdirectories to search.

    Returns:
        Dictionary mapping subdirectory name to file path.
    """
    result: dict[str, Path] = {}
    for subdir in SUBDIRS:
        expected_name = f"{subdir}.{pattern}.yml"
        expected_path = base_path / subdir / expected_name
        if expected_path.is_file():
            result[subdir] = expected_path
    return result


def get_ids_objects(file_path: Path) -> dict[str, dict[str, Any]]:
    """Extract IDs and sliced object data from a YAML file.

    This is a convenience wrapper that extracts only the sliced objects dict,
    discarding containment edges. Use extract_ids_and_objects directly if
    you need the containment edges.

    Args:
        file_path: Path to the YAML file.

    Returns:
        Dictionary mapping IDs to their sliced object data (child content
        excluded, replaced with $ref).
    """
    data = parse_yaml_file(file_path)
    try:
        relative_path = file_path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        relative_path = file_path.as_posix()
    sliced_objects, _ = extract_ids_and_objects(data, source_file=relative_path)
    return sliced_objects


def aggregate_split_objects(
    split_map: dict[str, Path],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Aggregate object data from split files by ID.

    Collects the full object data for each ID across all split files. Warns if
    the same ID has conflicting data in different split files.

    Args:
        split_map: Dictionary mapping subdirectory name to file path.

    Returns:
        Dictionary mapping ID to {relative_file_path: object_data}.
    """
    result: dict[str, dict[str, dict[str, Any]]] = {}

    for _, file_path in split_map.items():
        relative_path = file_path.relative_to(REPO_ROOT).as_posix()
        try:
            ids_objects = get_ids_objects(file_path)
        except Exception as exc:
            print(f"Warning: Failed to parse {relative_path}: {exc}", file=sys.stderr)
            continue

        for element_id, obj_data in ids_objects.items():
            if element_id not in result:
                result[element_id] = {}
            result[element_id][relative_path] = obj_data

    # Check for conflicting data across split files for the same ID
    for element_id, file_objects in result.items():
        unique_data = {json.dumps(obj, sort_keys=True) for obj in file_objects.values()}
        if len(unique_data) > 1:
            files = ", ".join(file_objects.keys())
            print(
                f"Warning: Conflicting data for ID '{element_id}' in: {files}",
                file=sys.stderr,
            )

    return result


def compare_original_to_splits(
    orig_path: Path,
    split_map: dict[str, Path],
) -> list[ComparisonEntry]:
    """Compare an original file to its split files using dict equality.

    Performs bidirectional comparison:
    1. For each ID in the original, checks if any split has matching data (dict == dict).
    2. For IDs in splits not in the original, adds them as extras.

    Args:
        orig_path: Path to the original YAML file.
        split_map: Dictionary mapping subdirectory name to split file path.

    Returns:
        List of comparison entries for non-matching IDs.
    """
    entries: list[ComparisonEntry] = []
    orig_relative = orig_path.relative_to(REPO_ROOT).as_posix()

    try:
        orig_ids = get_ids_objects(orig_path)
    except Exception as exc:
        print(f"Warning: Failed to parse {orig_relative}: {exc}", file=sys.stderr)
        return entries

    split_objects = aggregate_split_objects(split_map)

    for element_id, orig_data in orig_ids.items():
        split_data = split_objects.get(element_id, {})

        # Dict-to-dict comparison for exact match
        has_exact_match = any(obj == orig_data for obj in split_data.values())

        if not has_exact_match:
            splits: list[SplitEntry] = [
                SplitEntry(split_data=obj, source_file=file_path)
                for file_path, obj in split_data.items()
            ]
            entries.append(
                ComparisonEntry(
                    source_file=orig_relative,
                    id=element_id,
                    source_data=orig_data,
                    splits=splits,
                    origin_type="original",
                )
            )

    orig_id_set = set(orig_ids.keys())
    for element_id, file_objects in split_objects.items():
        if element_id not in orig_id_set:
            for file_path, obj in file_objects.items():
                entries.append(
                    ComparisonEntry(
                        source_file=file_path,
                        id=element_id,
                        source_data=obj,
                        splits=[],
                        origin_type="split_only",
                    )
                )

    return entries


def compare_all(
    base_path: Path,
    original_files: list[Path] | None = None,
) -> tuple[dict[str, CompareResult], set[str]]:
    """Compare all original files to their split files.

    Also handles orphan files in subdirectories that don't have a corresponding
    original file.

    Args:
        base_path: Base directory containing original and split YAML files.
        original_files: Optional list of explicit original file paths to use.
            When provided, these files are used instead of globbing for
            original.*.yml files in the base path.

    Returns:
        Tuple of (results dict, processed patterns set).
        Results dict maps original file path to comparison results.
        Processed patterns set contains all pattern names that were compared.
    """
    results: dict[str, CompareResult] = {}
    processed_patterns: set[str] = set()

    originals = find_originals(base_path, original_files)
    for orig_path in originals:
        pattern = pattern_from_path(orig_path)
        processed_patterns.add(pattern)

        split_map = find_mapped_splits(pattern, base_path)
        entries = compare_original_to_splits(orig_path, split_map)

        orig_relative = orig_path.relative_to(REPO_ROOT).as_posix()
        if entries:
            results[orig_relative] = CompareResult(
                original_file=orig_relative,
                entries=entries,
            )

    all_yml = find_all_yml(base_path)
    orphan_paths: list[Path] = []

    for yml_path in all_yml:
        pattern = pattern_from_path(yml_path)
        if pattern not in processed_patterns:
            orphan_paths.append(yml_path)

    for orphan_path in orphan_paths:
        orphan_relative = orphan_path.relative_to(REPO_ROOT).as_posix()
        try:
            orphan_ids = get_ids_objects(orphan_path)
        except Exception as exc:
            print(
                f"Warning: Failed to parse orphan {orphan_relative}: {exc}",
                file=sys.stderr,
            )
            continue

        orphan_entries: list[ComparisonEntry] = []
        for element_id, obj_data in orphan_ids.items():
            orphan_entries.append(
                ComparisonEntry(
                    source_file=orphan_relative,
                    id=element_id,
                    source_data=obj_data,
                    splits=[],
                    origin_type="orphan",
                )
            )

        if orphan_entries:
            results[orphan_relative] = CompareResult(
                original_file=orphan_relative,
                entries=orphan_entries,
            )

    return results, processed_patterns


def _get_compare_output_path(source_path: str) -> Path:
    """Determine the output path for a comparison CSV file.

    Extracts the pattern name from the source path and returns a path under
    `.knowledge/comparisons/<pattern-name>.csv`.

    Args:
        source_path: The relative source file path.

    Returns:
        Path where the comparison CSV file should be written.
    """
    source = Path(source_path)
    pattern = pattern_from_path(source)
    comparisons_dir = REPO_ROOT / KNOWLEDGE_DIR_NAME / "comparisons"
    return comparisons_dir / f"{pattern}.csv"


CSV_COLUMNS = ["source_file", "id", "origin_type", "original_data", "split_file", "split_data"]


def _flatten_entry_to_rows(entry: ComparisonEntry) -> list[dict[str, str]]:
    """Flatten a ComparisonEntry into CSV rows.

    For entries with splits, creates one row per split.
    For entries without splits, creates one row with empty split columns.

    Note: The `original_data` column is populated from `source_data` (JSON-serialized)
    for all origin types. For `split_only` and `orphan` entries, this represents the
    data from the split or orphan file respectively, not from an original file. Query
    authors should be aware of this semantic when filtering by origin_type.

    Args:
        entry: The comparison entry to flatten.

    Returns:
        List of dictionaries representing CSV rows.
    """
    rows: list[dict[str, str]] = []
    # Serialize source_data as JSON for CSV storage
    source_data_json = json.dumps(entry["source_data"], sort_keys=True)
    base_row = {
        "source_file": entry["source_file"],
        "id": entry["id"],
        "origin_type": entry["origin_type"],
        "original_data": source_data_json,
    }

    if entry["splits"]:
        for split in entry["splits"]:
            split_data_json = json.dumps(split["split_data"], sort_keys=True)
            row = {
                **base_row,
                "split_file": split["source_file"],
                "split_data": split_data_json,
            }
            rows.append(row)
    else:
        row = {**base_row, "split_file": "", "split_data": ""}
        rows.append(row)

    return rows


def write_compare_files(results: dict[str, CompareResult]) -> int:
    """Write comparison results to CSV files in .knowledge/comparisons/.

    Creates one CSV file per pattern with flattened comparison entries.
    Each row represents a (source_file, id, split_file) combination.
    Uses DuckDB to write CSV files.

    Note: Comparison CSVs are regenerated on each run and older data is intentionally
    discarded. This design ensures the CSV always reflects the current state of the
    YAML files being compared, rather than accumulating stale historical data.

    Args:
        results: Dictionary mapping file paths to comparison results.

    Returns:
        Number of CSV files written.
    """
    pattern_rows: dict[str, list[dict[str, str]]] = {}

    for source_path, compare_result in results.items():
        output_path = _get_compare_output_path(source_path)
        pattern_name = output_path.stem

        if pattern_name not in pattern_rows:
            pattern_rows[pattern_name] = []

        for entry in compare_result["entries"]:
            pattern_rows[pattern_name].extend(_flatten_entry_to_rows(entry))

    files_written = 0
    comparisons_dir = REPO_ROOT / KNOWLEDGE_DIR_NAME / "comparisons"

    for pattern_name, rows in pattern_rows.items():
        output_path = comparisons_dir / f"{pattern_name}.csv"

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            conn = duckdb.connect()
            try:
                columns_def = ", ".join(f"{col} VARCHAR" for col in CSV_COLUMNS)
                conn.execute(f"CREATE TABLE comparisons ({columns_def})")
                if rows:
                    placeholders = ", ".join("?" for _ in CSV_COLUMNS)
                    insert_sql = f"INSERT INTO comparisons VALUES ({placeholders})"
                    for row in rows:
                        values = [row.get(col, "") for col in CSV_COLUMNS]
                        conn.execute(insert_sql, values)
                copy_sql = f"COPY comparisons TO '{output_path}' (HEADER, DELIMITER ',')"
                conn.execute(copy_sql)
            finally:
                conn.close()
            files_written += 1
        except (OSError, duckdb.Error) as exc:
            print(
                f"Warning: Failed to write {output_path}: {exc}",
                file=sys.stderr,
            )

    return files_written


CONTAINMENT_EDGE_COLUMNS = ["parent_id", "child_id", "field_path", "source_file"]


def write_containment_edges(
    edges: list[ContainmentEdge],
    knowledge_path: Path | None = None,
) -> int:
    """Write containment edges to CSV file in .knowledge/graph/.

    Creates or replaces the containment_edges.csv file with the provided edges.
    Deduplicates edges by (source_file, parent_id, child_id, field_path) before
    writing.

    Args:
        edges: List of ContainmentEdge records to write.
        knowledge_path: Base knowledge directory path. If None, uses REPO_ROOT.

    Returns:
        Number of edges written.

    Raises:
        RuntimeError: If writing to DuckDB or filesystem fails.
    """
    if knowledge_path is None:
        knowledge_path = REPO_ROOT / KNOWLEDGE_DIR_NAME

    graph_dir = knowledge_path / "graph"
    output_path = graph_dir / "containment_edges.csv"

    # Deduplicate edges by (source_file, parent_id, child_id, field_path)
    seen: set[tuple[str, str, str, str]] = set()
    unique_edges: list[ContainmentEdge] = []
    for edge in edges:
        key = (edge.source_file, edge.parent_id, edge.child_id, edge.field_path)
        if key not in seen:
            seen.add(key)
            unique_edges.append(edge)

    try:
        graph_dir.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect()
        try:
            columns_def = ", ".join(f"{col} VARCHAR" for col in CONTAINMENT_EDGE_COLUMNS)
            conn.execute(f"CREATE TABLE containment_edges ({columns_def})")
            if unique_edges:
                placeholders = ", ".join("?" for _ in CONTAINMENT_EDGE_COLUMNS)
                insert_sql = f"INSERT INTO containment_edges VALUES ({placeholders})"
                for edge in unique_edges:
                    values = [
                        edge.parent_id,
                        edge.child_id,
                        edge.field_path,
                        edge.source_file,
                    ]
                    conn.execute(insert_sql, values)
            copy_sql = f"COPY containment_edges TO '{output_path}' (HEADER, DELIMITER ',')"
            conn.execute(copy_sql)
        finally:
            conn.close()
        return len(unique_edges)
    except (OSError, duckdb.Error) as exc:
        msg = f"Failed to write containment edges to {output_path}: {exc}"
        raise RuntimeError(msg) from exc


def _get_logical_pattern_from_csv(csv_path: Path) -> str:
    """Extract the logical pattern name from a comparison CSV filename.

    Handles both legacy filenames (e.g., 'api-patterns.csv') and
    timestamp-prefixed filenames (e.g., '20251201T134735Z-api-patterns.csv').

    Args:
        csv_path: Path to a comparison CSV file.

    Returns:
        The logical pattern name with any timestamp prefix stripped.
    """
    return _strip_timestamp_prefix(csv_path.stem)


def _delete_stale_comparison_csvs(
    processed_patterns: set[str],
    patterns_with_differences: set[str],
) -> int:
    """Delete comparison CSVs for patterns that no longer have differences.

    Handles both legacy CSV filenames (e.g., 'api-patterns.csv') and
    timestamp-prefixed filenames (e.g., '20251201T134735Z-api-patterns.csv')
    by normalizing to logical pattern names before comparison.

    Args:
        processed_patterns: All patterns that were compared in this run.
        patterns_with_differences: Patterns that have current differences.

    Returns:
        Number of stale CSV files deleted.
    """
    comparisons_dir = REPO_ROOT / KNOWLEDGE_DIR_NAME / "comparisons"
    if not comparisons_dir.exists():
        return 0

    deleted = 0
    patterns_to_delete = processed_patterns - patterns_with_differences

    # Scan all CSV files and delete those whose logical pattern has no differences
    for csv_path in comparisons_dir.glob("*.csv"):
        logical_pattern = _get_logical_pattern_from_csv(csv_path)

        # Only delete if the logical pattern was processed and has no differences
        if logical_pattern in patterns_to_delete:
            try:
                csv_path.unlink()
                deleted += 1
            except OSError as exc:
                print(
                    f"Warning: Failed to delete stale CSV {csv_path}: {exc}",
                    file=sys.stderr,
                )

    return deleted


def _collect_containment_edges_from_files(file_paths: list[Path]) -> list[ContainmentEdge]:
    """Collect containment edges from a list of YAML files.

    Args:
        file_paths: List of YAML file paths to process.

    Returns:
        List of all containment edges from all files.
    """
    all_edges: list[ContainmentEdge] = []
    for file_path in file_paths:
        try:
            relative_path = file_path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            relative_path = file_path.as_posix()
        try:
            data = parse_yaml_file(file_path)
            _, edges = extract_ids_and_objects(data, source_file=relative_path)
            all_edges.extend(edges)
        except Exception:
            # Silently skip files that can't be parsed
            continue
    return all_edges


def main() -> int:
    """Run comparison and write results to CSV files.

    Deletes stale comparison CSVs for patterns that no longer have differences,
    ensuring validation does not fail due to outdated data. Supports the
    --original-files parameter to specify timestamped originals from
    .knowledge/originals/ instead of globbing for original.*.yml files.

    Also collects and writes containment edges from all processed YAML files
    to .knowledge/graph/containment_edges.csv.

    Returns:
        0 if no differences found, 1 if differences exist.
    """
    args = parse_args()
    base_path = args.path.resolve()

    if not base_path.exists() or not base_path.is_dir():
        print(
            f"Error: Specified path '{base_path}' does not exist or is not a directory.",
            file=sys.stderr,
        )
        return 1

    original_files: list[Path] | None = None
    if args.original_files:
        original_files = [
            (REPO_ROOT / f).resolve() if not f.is_absolute() else f.resolve()
            for f in args.original_files
        ]

    results, processed_patterns = compare_all(base_path, original_files)

    # Collect containment edges from all YAML files
    all_yml_files: list[Path] = []
    originals = find_originals(base_path, original_files)
    all_yml_files.extend(originals)
    all_yml_files.extend(find_all_yml(base_path))
    containment_edges = _collect_containment_edges_from_files(all_yml_files)

    # Write containment edges
    if containment_edges:
        try:
            edge_count = write_containment_edges(containment_edges)
            if edge_count > 0:
                print(f"Wrote {edge_count} containment edge(s) to {KNOWLEDGE_DIR_NAME}/graph/")
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    patterns_with_differences: set[str] = set()
    for source_path in results:
        output_path = _get_compare_output_path(source_path)
        patterns_with_differences.add(output_path.stem)

    deleted = _delete_stale_comparison_csvs(processed_patterns, patterns_with_differences)
    if deleted > 0:
        print(f"Deleted {deleted} stale CSV file(s) with no current differences.")

    if results:
        count = write_compare_files(results)
        print(f"Wrote {count} CSV file(s) to {KNOWLEDGE_DIR_NAME}/comparisons/")
        return 1

    print("No differences found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
