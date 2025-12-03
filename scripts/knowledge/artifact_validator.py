"""Artifact validation logic for the knowledge graph system.

This module provides functions for validating rendered artifacts against source
artifacts per fact_redesign.md lines 948-967. Validation uses comparators
specific to artifact type.

Validation Comparators:
    - normalized_text: Embedding-based semantic similarity via Qwen3 (0.8 threshold)
    - normalized_rows_by_discriminator: Row comparison for tables
    - structure_and_leaf_text: Structural equality for nested hierarchies
    - normalized_diff: Formatting-insensitive diff for code blocks

Current Implementation Status:
    - Implemented: ValidationResult dataclass, CSV writing, hash computation,
      embedding-based semantic similarity via Qwen3 embeddings
    - Deferred to Task 9: Entity resolution (per fact_redesign_plan.md)
"""

from __future__ import annotations

import csv
import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml

if TYPE_CHECKING:
    from scripts.knowledge.artifact_manager import ArtifactManifest

# Module-level logger
_logger = logging.getLogger(__name__)

# Valid validation comparators
ValidComparator = Literal[
    "normalized_text",
    "normalized_rows_by_discriminator",
    "structure_and_leaf_text",
    "normalized_diff",
    "exact_normalized",
]

# CSV header columns
CSV_COLUMNS = [
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


@dataclass
class ValidationResult:
    """Validation result for a rendered artifact.

    Per fact_redesign.md lines 948-967, validation results track:
    - Identity of the artifact and source
    - Hashes for change detection
    - Similarity score and pass/fail status
    - Mismatch details for debugging
    """

    validation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    artifact_id: str = ""
    source_file: str = ""
    source_element_id: str = ""
    field_path: str = ""
    render_plan_id: str = ""
    projection_version: str = ""
    source_hash: str = ""
    rendered_hash: str = ""
    similarity_score: float = 0.0
    passed: bool = False
    mismatch_summary: str = ""
    validated_at: str = field(
        default_factory=lambda: datetime.now(tz=timezone.utc).isoformat()
    )


def _compute_hash(text: str) -> str:
    """Compute SHA-256 hash of text.

    Args:
        text: Text to hash.

    Returns:
        Hex-encoded SHA-256 hash.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace in text for comparison.

    Trims leading/trailing whitespace, normalizes newlines, and collapses
    multiple spaces.

    Args:
        text: Text to normalize.

    Returns:
        Normalized text.
    """
    # Normalize newlines
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Strip leading/trailing whitespace
    text = text.strip()
    # Collapse multiple spaces
    text = re.sub(r" +", " ", text)
    # Collapse multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _validate_normalized_text(
    source: str,
    rendered: str,
    similarity_threshold: float = 0.8,
) -> tuple[float, bool, str]:
    """Validate using embedding-based semantic similarity.

    Uses Qwen3 embeddings to compute cosine similarity between source and
    rendered text. Falls back to character-level comparison if embeddings
    are unavailable.

    Args:
        source: Source artifact text.
        rendered: Rendered artifact text.
        similarity_threshold: Minimum similarity for passing (default 0.8).

    Returns:
        Tuple of (similarity_score, passed, mismatch_summary).
    """
    # Normalize both texts
    source_normalized = _normalize_whitespace(source)
    rendered_normalized = _normalize_whitespace(rendered)

    # Fast path for identical text
    if source_normalized == rendered_normalized:
        return 1.0, True, ""

    # Handle empty cases
    if not source_normalized and not rendered_normalized:
        return 1.0, True, ""
    if not source_normalized or not rendered_normalized:
        return 0.0, False, "One of source or rendered is empty"

    # Try embedding-based semantic similarity
    try:
        from scripts.knowledge.variant_resolver import (
            compute_cosine_similarity,
            embed_keywords,
            load_qwen_embedding_model,
        )

        model, tokenizer = load_qwen_embedding_model()

        # Embed source and rendered texts
        embeddings = embed_keywords([source_normalized, rendered_normalized], model, tokenizer)

        # Compute cosine similarity (single value for 2 texts)
        similarity_matrix = compute_cosine_similarity(
            embeddings[:1], embeddings[1:]
        )
        similarity = float(similarity_matrix[0, 0])

        passed = similarity >= similarity_threshold

        mismatch_summary = ""
        if not passed:
            source_len = len(source_normalized)
            rendered_len = len(rendered_normalized)
            mismatch_summary = (
                f"Semantic similarity {similarity:.2%} below threshold {similarity_threshold:.0%}. "
                f"Source: {source_len} chars, Rendered: {rendered_len} chars."
            )

        _logger.debug(
            "Embedding-based validation: similarity=%.4f, passed=%s",
            similarity,
            passed,
        )
        return similarity, passed, mismatch_summary

    except ImportError as e:
        _logger.warning(
            "Qwen embeddings not available, falling back to character comparison: %s", e
        )
    except Exception as e:
        _logger.warning(
            "Embedding computation failed, falling back to character comparison: %s", e
        )

    # Fallback to character-level similarity
    source_chars = set(source_normalized)
    rendered_chars = set(rendered_normalized)
    intersection = source_chars & rendered_chars
    union = source_chars | rendered_chars

    if not union:
        return 0.0, False, "Both source and rendered are empty"

    similarity = len(intersection) / len(union)
    passed = similarity >= similarity_threshold

    mismatch_summary = ""
    if not passed:
        source_len = len(source_normalized)
        rendered_len = len(rendered_normalized)
        mismatch_summary = (
            f"Text similarity {similarity:.2%} (character fallback). "
            f"Source: {source_len} chars, Rendered: {rendered_len} chars."
        )

    return similarity, passed, mismatch_summary


def _validate_normalized_rows_by_discriminator(
    source: str,
    rendered: str,
    discriminator: str = "method",
) -> tuple[float, bool, str]:
    """Validate table by comparing rows grouped by discriminator.

    Parses Markdown tables and compares rows by their discriminator field.

    Args:
        source: Source table text (Markdown).
        rendered: Rendered table text (Markdown).
        discriminator: Column name to use as discriminator.

    Returns:
        Tuple of (similarity_score, passed, mismatch_summary).
    """
    def parse_markdown_table(text: str) -> tuple[list[str], list[dict[str, str]]]:
        """Parse Markdown table into headers and rows."""
        lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
        if len(lines) < 2:
            return [], []

        # Parse header
        header_line = lines[0]
        headers = [h.strip() for h in header_line.strip("|").split("|")]

        # Skip separator line
        rows: list[dict[str, str]] = []
        for line in lines[2:]:
            if not line or line.startswith("|-"):
                continue
            values = [v.strip() for v in line.strip("|").split("|")]
            if len(values) == len(headers):
                rows.append(dict(zip(headers, values)))

        return headers, rows

    source_headers, source_rows = parse_markdown_table(source)
    rendered_headers, rendered_rows = parse_markdown_table(rendered)

    # Check headers match
    if source_headers != rendered_headers:
        return 0.0, False, f"Headers mismatch: {source_headers} vs {rendered_headers}"

    # Group rows by discriminator
    def group_by_discriminator(
        rows: list[dict[str, str]],
    ) -> dict[str, dict[str, str]]:
        return {row.get(discriminator, ""): row for row in rows if discriminator in row}

    source_grouped = group_by_discriminator(source_rows)
    rendered_grouped = group_by_discriminator(rendered_rows)

    # Compare row sets
    source_keys = set(source_grouped.keys())
    rendered_keys = set(rendered_grouped.keys())

    missing = source_keys - rendered_keys
    extra = rendered_keys - source_keys

    if missing or extra:
        mismatches = []
        if missing:
            mismatches.append(f"Missing rows: {missing}")
        if extra:
            mismatches.append(f"Extra rows: {extra}")
        return 0.0, False, "; ".join(mismatches)

    # Compare row values
    differences: list[str] = []
    for key in source_keys:
        if source_grouped[key] != rendered_grouped[key]:
            differences.append(f"Row '{key}' differs")

    if differences:
        similarity = 1.0 - (len(differences) / len(source_keys))
        return similarity, False, "; ".join(differences)

    return 1.0, True, ""


def _validate_structure_and_leaf_text(
    source: str,
    rendered: str,
) -> tuple[float, bool, str]:
    """Validate by comparing YAML structure and leaf values.

    Parses YAML and compares tree structure and leaf node text equality.

    Args:
        source: Source YAML text.
        rendered: Rendered YAML text.

    Returns:
        Tuple of (similarity_score, passed, mismatch_summary).
    """
    try:
        source_data = yaml.safe_load(source)
        rendered_data = yaml.safe_load(rendered)
    except yaml.YAMLError as exc:
        return 0.0, False, f"YAML parse error: {exc}"

    def compare_structure(s: object, r: object, path: str = "") -> list[str]:
        """Recursively compare structure and values."""
        differences: list[str] = []

        if type(s) != type(r):
            differences.append(f"{path}: type mismatch ({type(s).__name__} vs {type(r).__name__})")
            return differences

        if isinstance(s, dict):
            s_keys = set(s.keys())
            r_keys = set(r.keys())
            missing = s_keys - r_keys
            extra = r_keys - s_keys

            if missing:
                differences.append(f"{path}: missing keys {missing}")
            if extra:
                differences.append(f"{path}: extra keys {extra}")

            for key in s_keys & r_keys:
                key_path = f"{path}.{key}" if path else key
                differences.extend(compare_structure(s[key], r[key], key_path))

        elif isinstance(s, list):
            if len(s) != len(r):
                differences.append(f"{path}: length mismatch ({len(s)} vs {len(r)})")
            else:
                for i, (s_item, r_item) in enumerate(zip(s, r)):
                    item_path = f"{path}[{i}]"
                    differences.extend(compare_structure(s_item, r_item, item_path))

        elif s != r:
            differences.append(f"{path}: value mismatch ('{s}' vs '{r}')")

        return differences

    differences = compare_structure(source_data, rendered_data)

    if not differences:
        return 1.0, True, ""

    # Calculate similarity based on number of differences
    # This is a rough estimate - full implementation would count nodes
    similarity = max(0.0, 1.0 - (len(differences) * 0.1))
    return similarity, False, "; ".join(differences[:5])  # Limit to 5 diffs


def _validate_exact_normalized(
    source: str,
    rendered: str,
) -> tuple[float, bool, str]:
    """Validate using exact match after whitespace normalization.

    For diagrams and other content where exact structural match is required.
    Normalizes whitespace before comparison but requires exact equality.

    Args:
        source: Source artifact text.
        rendered: Rendered artifact text.

    Returns:
        Tuple of (similarity_score, passed, mismatch_summary).
    """
    source_normalized = _normalize_whitespace(source)
    rendered_normalized = _normalize_whitespace(rendered)

    if source_normalized == rendered_normalized:
        return 1.0, True, ""

    # Calculate basic similarity for reporting
    source_chars = set(source_normalized)
    rendered_chars = set(rendered_normalized)
    union = source_chars | rendered_chars

    if not union:
        similarity = 0.0
    else:
        intersection = source_chars & rendered_chars
        similarity = len(intersection) / len(union)

    # Exact match required - 1.0 or fail
    source_len = len(source_normalized)
    rendered_len = len(rendered_normalized)
    mismatch_summary = (
        f"Exact match required. Similarity {similarity:.2%}. "
        f"Source: {source_len} chars, Rendered: {rendered_len} chars."
    )

    return similarity, False, mismatch_summary


def _validate_normalized_diff(
    source: str,
    rendered: str,
    preserve_code_verbatim: bool = True,
) -> tuple[float, bool, str]:
    """Validate using formatting-insensitive diff.

    For prose with code blocks, ensures code blocks are preserved verbatim
    while allowing formatting flexibility in prose sections.

    Args:
        source: Source text.
        rendered: Rendered text.
        preserve_code_verbatim: If True, code blocks must match exactly.

    Returns:
        Tuple of (similarity_score, passed, mismatch_summary).
    """
    # Extract code blocks
    code_block_pattern = r"```[\w]*\n(.*?)```"

    source_code_blocks = re.findall(code_block_pattern, source, re.DOTALL)
    rendered_code_blocks = re.findall(code_block_pattern, rendered, re.DOTALL)

    # Check code blocks match if required
    if preserve_code_verbatim:
        if len(source_code_blocks) != len(rendered_code_blocks):
            return 0.0, False, (
                f"Code block count mismatch: {len(source_code_blocks)} vs {len(rendered_code_blocks)}"
            )

        for i, (src_code, rnd_code) in enumerate(
            zip(source_code_blocks, rendered_code_blocks)
        ):
            if src_code.strip() != rnd_code.strip():
                return 0.0, False, f"Code block {i} differs"

    # Remove code blocks for prose comparison
    source_prose = re.sub(code_block_pattern, "", source, flags=re.DOTALL)
    rendered_prose = re.sub(code_block_pattern, "", rendered, flags=re.DOTALL)

    # Use normalized text comparison for prose
    return _validate_normalized_text(source_prose, rendered_prose)


def validate_artifact(
    manifest: ArtifactManifest,
    rendered_path: Path,
    source_text: str,
    validation_comparator: ValidComparator,
    discriminator: str = "method",
) -> ValidationResult:
    """Validate a rendered artifact against source.

    Main validation function that applies the appropriate comparator based
    on artifact type.

    Args:
        manifest: The artifact manifest.
        rendered_path: Path to the rendered artifact file.
        source_text: Source artifact text.
        validation_comparator: Which comparator to use.
        discriminator: Discriminator field for table comparison.

    Returns:
        ValidationResult with similarity score and pass/fail status.

    Raises:
        FileNotFoundError: If rendered file doesn't exist.
        ValueError: If comparator is unsupported.
    """
    artifact_id = manifest["artifact_id"]
    source = manifest.get("source", {})

    _logger.info(
        "Validating artifact %s with comparator %s",
        artifact_id,
        validation_comparator,
    )

    # Read rendered text
    if not rendered_path.exists():
        msg = f"Rendered artifact not found: {rendered_path}"
        raise FileNotFoundError(msg)

    rendered_text = rendered_path.read_text(encoding="utf-8")

    # Compute hashes
    source_hash = _compute_hash(source_text)
    rendered_hash = _compute_hash(rendered_text)

    # Apply appropriate comparator
    if validation_comparator == "normalized_text":
        similarity, passed, mismatch = _validate_normalized_text(
            source_text, rendered_text
        )
    elif validation_comparator == "normalized_rows_by_discriminator":
        similarity, passed, mismatch = _validate_normalized_rows_by_discriminator(
            source_text, rendered_text, discriminator
        )
    elif validation_comparator == "structure_and_leaf_text":
        similarity, passed, mismatch = _validate_structure_and_leaf_text(
            source_text, rendered_text
        )
    elif validation_comparator == "normalized_diff":
        similarity, passed, mismatch = _validate_normalized_diff(
            source_text, rendered_text
        )
    elif validation_comparator == "exact_normalized":
        similarity, passed, mismatch = _validate_exact_normalized(
            source_text, rendered_text
        )
    else:
        msg = f"Unsupported validation comparator: {validation_comparator}"
        raise ValueError(msg)

    result = ValidationResult(
        artifact_id=artifact_id,
        source_file=source.get("source_file", ""),
        source_element_id=source.get("source_element_id", ""),
        field_path=source.get("field_path", ""),
        render_plan_id=manifest.get("render_plan_id", ""),
        projection_version=manifest.get("projection_version", ""),
        source_hash=source_hash,
        rendered_hash=rendered_hash,
        similarity_score=similarity,
        passed=passed,
        mismatch_summary=mismatch,
    )

    _logger.info(
        "Validation result for %s: similarity=%.2f, passed=%s",
        artifact_id,
        similarity,
        passed,
    )

    return result


def write_validation_result(
    result: ValidationResult,
    validations_csv_path: Path,
) -> None:
    """Append validation result to CSV file.

    Creates the CSV file with headers if it doesn't exist.

    Args:
        result: The ValidationResult to write.
        validations_csv_path: Path to the validations CSV file.
    """
    file_exists = validations_csv_path.exists()

    # Ensure parent directory exists
    validations_csv_path.parent.mkdir(parents=True, exist_ok=True)

    with validations_csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)

        if not file_exists:
            writer.writeheader()

        writer.writerow({
            "validation_id": result.validation_id,
            "artifact_id": result.artifact_id,
            "source_file": result.source_file,
            "source_element_id": result.source_element_id,
            "field_path": result.field_path,
            "render_plan_id": result.render_plan_id,
            "projection_version": result.projection_version,
            "source_hash": result.source_hash,
            "rendered_hash": result.rendered_hash,
            "similarity_score": f"{result.similarity_score:.4f}",
            "passed": str(result.passed).lower(),
            "mismatch_summary": result.mismatch_summary,
            "validated_at": result.validated_at,
        })

    _logger.debug("Wrote validation result %s to %s", result.validation_id, validations_csv_path)


def load_validation_results(
    validations_csv_path: Path,
) -> list[ValidationResult]:
    """Load validation results from CSV file.

    Args:
        validations_csv_path: Path to the validations CSV file.

    Returns:
        List of ValidationResult objects.

    Raises:
        FileNotFoundError: If the CSV file doesn't exist.
    """
    if not validations_csv_path.exists():
        return []

    results: list[ValidationResult] = []

    with validations_csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            results.append(ValidationResult(
                validation_id=row.get("validation_id", ""),
                artifact_id=row.get("artifact_id", ""),
                source_file=row.get("source_file", ""),
                source_element_id=row.get("source_element_id", ""),
                field_path=row.get("field_path", ""),
                render_plan_id=row.get("render_plan_id", ""),
                projection_version=row.get("projection_version", ""),
                source_hash=row.get("source_hash", ""),
                rendered_hash=row.get("rendered_hash", ""),
                similarity_score=float(row.get("similarity_score", "0.0")),
                passed=row.get("passed", "false").lower() == "true",
                mismatch_summary=row.get("mismatch_summary", ""),
                validated_at=row.get("validated_at", ""),
            ))

    return results


def get_comparator_for_artifact_kind(artifact_kind: str) -> ValidComparator:
    """Get the appropriate validation comparator for an artifact kind.

    Maps artifact kinds to their validation comparators per fact_redesign.md
    lines 948-967.

    Comparator mapping rules:
    - prose/paragraph: normalized_text (semantic similarity with 0.8 threshold)
    - prose/code-block: normalized_diff (exact code blocks, flexible prose)
    - table/*: normalized_rows_by_discriminator (row-by-row comparison)
    - schema/*: structure_and_leaf_text (structural tree equality)
    - diagram/*: exact_normalized (exact match after whitespace normalization)
    - Default: normalized_text

    Args:
        artifact_kind: The artifact kind.

    Returns:
        The validation comparator to use.
    """
    # Mapping based on artifact kind categories
    if artifact_kind.startswith("prose/paragraph"):
        return "normalized_text"
    if artifact_kind.startswith("prose/code-block"):
        return "normalized_diff"
    if artifact_kind.startswith("table/"):
        return "normalized_rows_by_discriminator"
    if artifact_kind.startswith("schema/"):
        return "structure_and_leaf_text"
    if artifact_kind.startswith("diagram/"):
        # Diagrams (e.g., Mermaid) require exact structural match
        return "exact_normalized"

    # Default to normalized_text
    return "normalized_text"
