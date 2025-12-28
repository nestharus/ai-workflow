"""Stage 5: Track and resolve keyword variants using embeddings.

This module provides functionality for identifying and tracking keyword variants
(synonyms, abbreviations, alternate spellings) using embedding similarity. It
uses Qwen3-Embedding-8B to find semantically similar terms and tracks them as
variant candidates for review.

Usage:
    # Track variants for all keywords
    uv run knowledge.track-keyword-variants

    # Set similarity threshold
    uv run knowledge.track-keyword-variants --similarity-threshold 0.85

    # Apply validated variant decisions to keywords.csv and YAML files
    uv run knowledge.apply-variant-decisions

Args:
    --similarity-threshold: Minimum similarity threshold (default: 0.85).
    --model: HuggingFace model for embeddings (default: Qwen/Qwen3-Embedding-8B).
    --knowledge-path: Base knowledge directory (default: .knowledge).
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

import duckdb
import numpy as np
import yaml

from scripts.dev.utils import REPO_ROOT
from scripts.knowledge.compare_yaml_docs import parse_yaml_file

if TYPE_CHECKING:
    from transformers import PreTrainedModel, PreTrainedTokenizer

VARIANT_COLUMNS = [
    "pair_id",
    "keyword_a",
    "keyword_b",
    "similarity",
    "merge",
    "canonical",
    "reason",
    "validated",
]


class VariantRecord(TypedDict):
    """A keyword variant pair candidate record.

    Attributes:
        pair_id: Unique identifier for this variant pair.
        keyword_a: First keyword in the pair.
        keyword_b: Second keyword in the pair.
        similarity: Embedding similarity score (0.0-1.0).
        merge: Whether to merge ("true", "false", or empty).
        canonical: The chosen canonical form (or empty).
        reason: Explanation for the merge decision (or empty).
        validated: Whether this pair has been validated ("true" or empty).
    """

    pair_id: str
    keyword_a: str
    keyword_b: str
    similarity: str
    merge: str
    canonical: str
    reason: str
    validated: str


def ensure_variants_csv_exists(csv_path: Path) -> None:
    """Create variants CSV file with header if it doesn't exist.

    Args:
        csv_path: Path to the variants CSV file.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not csv_path.exists() or csv_path.stat().st_size == 0
    if needs_header:
        cols_select = ", ".join(f"'' AS {col}" for col in VARIANT_COLUMNS)
        query = f"COPY (SELECT * FROM (SELECT {cols_select}) WHERE 1=0) "
        query += f"TO '{csv_path}' (HEADER, DELIMITER ',')"
        duckdb.execute(query)


def append_variant(csv_path: Path, record: VariantRecord) -> None:
    """Append a variant record to the variants CSV.

    Args:
        csv_path: Path to the variants CSV file.
        record: Variant record to append.
    """
    conn = duckdb.connect()
    try:
        conn.execute(f"""
            CREATE TABLE variants AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """)
        placeholders = ", ".join("?" for _ in VARIANT_COLUMNS)
        values = [record[col] for col in VARIANT_COLUMNS]  # type: ignore[literal-required]
        conn.execute(f"INSERT INTO variants VALUES ({placeholders})", values)
        conn.execute(f"COPY variants TO '{csv_path}' (HEADER, DELIMITER ',')")
    finally:
        conn.close()


def is_variant_tracked(csv_path: Path, keyword_a: str, keyword_b: str) -> bool:
    """Check if a variant pair already exists (order-independent).

    Args:
        csv_path: Path to the variants CSV file.
        keyword_a: First keyword in the pair.
        keyword_b: Second keyword in the pair.

    Returns:
        True if variant pair exists (in either order), False otherwise.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return False

    query = """
        SELECT COUNT(*) as cnt
        FROM read_csv_auto(?)
        WHERE (keyword_a = ? AND keyword_b = ?)
           OR (keyword_a = ? AND keyword_b = ?)
    """
    try:
        result = duckdb.execute(
            query, [str(csv_path), keyword_a, keyword_b, keyword_b, keyword_a]
        ).fetchone()
        return result is not None and result[0] > 0
    except duckdb.Error:
        return False


def load_existing_pairs(csv_path: Path) -> set[frozenset[str]]:
    """Load all existing variant pairs into a set for fast lookup.

    Args:
        csv_path: Path to the variants CSV file.

    Returns:
        Set of frozensets, where each frozenset contains {keyword_a, keyword_b}.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return set()

    query = """
        SELECT keyword_a, keyword_b
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
    """
    try:
        result = duckdb.execute(query, [str(csv_path)]).fetchall()
        return {frozenset([row[0], row[1]]) for row in result}
    except duckdb.Error:
        return set()


def load_qwen_embedding_model(
    model_name: str,
) -> tuple[PreTrainedModel, PreTrainedTokenizer]:
    """Load Qwen embedding model and tokenizer.

    Args:
        model_name: HuggingFace model name (e.g., "Qwen/Qwen3-Embedding-8B").

    Returns:
        Tuple of (model, tokenizer).
    """
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)  # type: ignore[no-untyped-call]
    model = AutoModel.from_pretrained(model_name, trust_remote_code=True)
    model.eval()
    return model, tokenizer


def embed_keywords(
    keywords: list[str],
    model: PreTrainedModel,
    tokenizer: PreTrainedTokenizer,
    batch_size: int = 32,
) -> np.ndarray:
    """Compute embeddings for keywords using Qwen model.

    Uses mean pooling over the last hidden state as recommended for Qwen embeddings.
    Handles both CPU and GPU tensors by moving to CPU before NumPy conversion.

    Args:
        keywords: List of keywords to embed.
        model: Loaded Qwen model.
        tokenizer: Loaded Qwen tokenizer.
        batch_size: Number of keywords to process at once.

    Returns:
        NumPy array of shape (len(keywords), embedding_dim).
    """
    import torch

    all_embeddings = []

    for i in range(0, len(keywords), batch_size):
        batch = keywords[i : i + batch_size]
        inputs = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )

        with torch.no_grad():
            outputs = model(**inputs)
            # Mean pooling over sequence length (ignoring padding)
            attention_mask = inputs["attention_mask"]
            hidden_states = outputs.last_hidden_state
            mask_expanded = attention_mask.unsqueeze(-1).expand(hidden_states.size())
            sum_embeddings = torch.sum(hidden_states * mask_expanded, dim=1)
            sum_mask = torch.clamp(mask_expanded.sum(dim=1), min=1e-9)
            # Move to CPU before converting to NumPy (handles GPU tensors)
            batch_embeddings = (sum_embeddings / sum_mask).cpu().numpy()

        all_embeddings.append(batch_embeddings)

    return np.vstack(all_embeddings)


def compute_cosine_similarity(embeddings: np.ndarray) -> np.ndarray:
    """Compute pairwise cosine similarity matrix.

    Args:
        embeddings: NumPy array of shape (n_samples, embedding_dim).

    Returns:
        NumPy array of shape (n_samples, n_samples) with similarity scores.
    """
    # Normalize embeddings to unit vectors
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normalized = embeddings / np.maximum(norms, 1e-9)
    # Cosine similarity = dot product of normalized vectors
    result: np.ndarray = np.dot(normalized, normalized.T)
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for variant tracking.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Track and resolve keyword variants using embeddings.",
    )
    parser.add_argument(
        "--threshold",
        "--similarity-threshold",
        type=float,
        default=0.85,
        dest="threshold",
        help="Minimum similarity threshold (default: 0.85).",
    )
    parser.add_argument(
        "--model",
        default="Qwen/Qwen3-Embedding-8B",
        help="HuggingFace model for embeddings (default: Qwen/Qwen3-Embedding-8B).",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def track_variants_main(args: argparse.Namespace) -> int:
    """Run variant tracking using Qwen embeddings.

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error.
    """
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    keywords_csv = knowledge_path / "keywords" / "keywords.csv"
    variants_csv = knowledge_path / "keywords" / "variant_candidates.csv"

    if not keywords_csv.exists():
        print(f"Error: Keywords CSV not found: {keywords_csv}", file=sys.stderr)
        return 1

    print(f"Model: {args.model}")
    print(f"Threshold: {args.threshold}")
    print(f"Keywords: {keywords_csv}")
    print(f"Variants: {variants_csv}")

    # Read distinct keywords from keywords.csv
    query = f"SELECT DISTINCT keyword FROM read_csv_auto('{keywords_csv}', ALL_VARCHAR=TRUE)"
    try:
        result = duckdb.execute(query).fetchall()
        keywords = [row[0] for row in result if row[0]]
    except duckdb.Error as e:
        print(f"Error reading keywords: {e}", file=sys.stderr)
        return 1

    if not keywords:
        print("No keywords found in keywords.csv")
        return 0

    print(f"Found {len(keywords)} distinct keywords")

    # Load embedding model
    print(f"Loading model {args.model}...")
    try:
        model, tokenizer = load_qwen_embedding_model(args.model)
    except Exception as e:
        print(f"Error loading model: {e}", file=sys.stderr)
        return 1

    # Compute embeddings
    print("Computing embeddings...")
    embeddings = embed_keywords(keywords, model, tokenizer)

    # Compute pairwise similarity
    print("Computing similarity matrix...")
    similarity_matrix = compute_cosine_similarity(embeddings)

    # Ensure variants CSV exists
    ensure_variants_csv_exists(variants_csv)

    # Load existing pairs into memory for fast lookup (avoids O(n^2) CSV reads)
    print("Loading existing variant pairs...")
    existing_pairs = load_existing_pairs(variants_csv)
    print(f"Found {len(existing_pairs)} existing pair(s)")

    # Find similar pairs above threshold
    pairs_found = 0
    pairs_new = 0
    new_records: list[VariantRecord] = []

    for i in range(len(keywords)):
        for j in range(i + 1, len(keywords)):
            sim = similarity_matrix[i, j]
            if sim >= args.threshold:
                pairs_found += 1
                keyword_a = keywords[i]
                keyword_b = keywords[j]

                # Check if already tracked using in-memory set
                pair_key = frozenset([keyword_a, keyword_b])
                if pair_key not in existing_pairs:
                    record = VariantRecord(
                        pair_id=str(uuid.uuid4()),
                        keyword_a=keyword_a,
                        keyword_b=keyword_b,
                        similarity=f"{sim:.4f}",
                        merge="",
                        canonical="",
                        reason="",
                        validated="",
                    )
                    new_records.append(record)
                    existing_pairs.add(pair_key)  # Track for deduplication
                    pairs_new += 1

    # Batch append new records to CSV
    for record in new_records:
        append_variant(variants_csv, record)

    print(f"Found {pairs_found} similar pairs above threshold {args.threshold}")
    print(f"Added {pairs_new} new pairs to {variants_csv}")

    return 0


def parse_apply_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for applying variant decisions.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Apply validated variant decisions to keywords.csv and YAML files.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show changes without applying them.",
    )
    return parser.parse_args(argv)


def _find_element_by_id(
    data: Any,
    target_id: str,
) -> dict[str, Any] | None:
    """Recursively find a YAML element by its 'id' field.

    Args:
        data: The parsed YAML structure (dict, list, or primitive).
        target_id: The element ID to find.

    Returns:
        The element dict if found, None otherwise.
    """
    if isinstance(data, dict):
        if data.get("id") == target_id:
            return data
        for value in data.values():
            result = _find_element_by_id(value, target_id)
            if result is not None:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _find_element_by_id(item, target_id)
            if result is not None:
                return result
    return None


def apply_variants_to_yaml_file(
    file_path: Path,
    mapping: dict[str, str],
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Apply variant mappings to keywords in a YAML file.

    Replaces any keyword list entries that appear as keys in the mapping
    with their canonical values.

    Args:
        file_path: Absolute path to the YAML file.
        mapping: Mapping of old_keyword -> canonical.
        dry_run: If True, don't write changes, just report what would change.

    Returns:
        Tuple of (count of replacements made, list of update descriptions).
    """
    updates: list[str] = []
    replacements = 0

    try:
        data = parse_yaml_file(file_path)
    except (ValueError, TypeError, yaml.YAMLError, FileNotFoundError) as exc:
        msg = f"Warning: Failed to parse {file_path}: {exc}"
        print(msg, file=sys.stderr)
        return 0, []

    modified = False

    def process_element(elem: Any) -> None:
        """Recursively process elements to replace keywords."""
        nonlocal modified, replacements

        if isinstance(elem, dict):
            # Check for keywords list in this element
            keywords = elem.get("keywords")
            if isinstance(keywords, list):
                new_keywords = []
                for kw in keywords:
                    if kw in mapping:
                        canonical = mapping[kw]
                        new_keywords.append(canonical)
                        updates.append(f"  '{kw}' -> '{canonical}'")
                        replacements += 1
                        modified = True
                    else:
                        new_keywords.append(kw)
                # Deduplicate and sort
                elem["keywords"] = sorted(set(new_keywords))

            # Recurse into nested structures
            for value in elem.values():
                process_element(value)
        elif isinstance(elem, list):
            for item in elem:
                process_element(item)

    process_element(data)

    if modified and not dry_run:
        try:
            content = yaml.dump(
                data,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
                width=120,
            )
            file_path.write_text(content, encoding="utf-8")
        except (OSError, yaml.YAMLError) as exc:
            msg = f"Warning: Failed to write {file_path}: {exc}"
            print(msg, file=sys.stderr)
            return 0, []

    return replacements, updates


def get_yaml_files_with_keywords(keywords_csv: Path) -> set[str]:
    """Get all source files that have keywords.

    Args:
        keywords_csv: Path to keywords.csv.

    Returns:
        Set of source file paths.
    """
    if not keywords_csv.exists() or keywords_csv.stat().st_size == 0:
        return set()

    query = """
        SELECT DISTINCT source_file
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
    """
    try:
        result = duckdb.execute(query, [str(keywords_csv)]).fetchall()
        return {row[0] for row in result if row[0]}
    except duckdb.Error:
        return set()


def apply_variant_decisions(
    keywords_csv: Path,
    variants_csv: Path,
    *,
    dry_run: bool = False,
) -> dict[str, str]:
    """Apply validated merge decisions to keywords.csv.

    Reads variant_candidates.csv for validated merges (merge='true', validated='true'),
    builds a mapping from old keywords to canonical forms, and updates keywords.csv.

    Args:
        keywords_csv: Path to keywords.csv file.
        variants_csv: Path to variant_candidates.csv file.
        dry_run: If True, return mapping without applying changes.

    Returns:
        Dictionary mapping old keywords to their canonical forms.
    """
    if not variants_csv.exists():
        return {}

    # Read validated merge decisions
    query = """
        SELECT keyword_a, keyword_b, canonical
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE merge = 'true' AND validated = 'true'
    """
    try:
        result = duckdb.execute(query, [str(variants_csv)]).fetchall()
    except duckdb.Error:
        return {}

    # Build mapping: old_keyword -> canonical
    mapping: dict[str, str] = {}
    for keyword_a, keyword_b, canonical in result:
        if canonical:
            # Map both keywords to canonical, except the canonical itself
            if keyword_a != canonical:
                mapping[keyword_a] = canonical
            if keyword_b != canonical:
                mapping[keyword_b] = canonical

    if not mapping:
        return {}

    if dry_run:
        return mapping

    # Apply updates to keywords.csv
    if not keywords_csv.exists():
        return mapping

    conn = duckdb.connect()
    try:
        conn.execute(f"""
            CREATE TABLE keywords AS
            SELECT * FROM read_csv_auto('{keywords_csv}', ALL_VARCHAR=TRUE)
        """)

        for old_keyword, canonical in mapping.items():
            conn.execute(
                "UPDATE keywords SET keyword = ? WHERE keyword = ?",
                [canonical, old_keyword],
            )

        conn.execute(f"COPY keywords TO '{keywords_csv}' (HEADER, DELIMITER ',')")
    finally:
        conn.close()

    return mapping


def apply_variant_decisions_to_yaml(
    keywords_csv: Path,
    mapping: dict[str, str],
    *,
    dry_run: bool = False,
) -> int:
    """Apply variant mappings to all YAML files that have keywords.

    Args:
        keywords_csv: Path to keywords.csv (used to find source files).
        mapping: Mapping of old_keyword -> canonical.
        dry_run: If True, don't write changes.

    Returns:
        Total number of keyword replacements made across all files.
    """
    source_files = get_yaml_files_with_keywords(keywords_csv)
    if not source_files:
        return 0

    total_replacements = 0
    print("\nApplying variant decisions to YAML files:")

    for source_file in sorted(source_files):
        file_path = REPO_ROOT / source_file
        if not file_path.exists():
            continue

        replacements, updates = apply_variants_to_yaml_file(file_path, mapping, dry_run=dry_run)

        if replacements > 0:
            print(f"\n  {source_file}:")
            for update in updates:
                print(update)
            total_replacements += replacements

    return total_replacements


def apply_variant_decisions_main(args: argparse.Namespace) -> int:
    """Run apply variant decisions.

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error.
    """
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    keywords_csv = knowledge_path / "keywords" / "keywords.csv"
    variants_csv = knowledge_path / "keywords" / "variant_candidates.csv"

    if not keywords_csv.exists():
        print(f"Error: Keywords CSV not found: {keywords_csv}", file=sys.stderr)
        return 1

    if not variants_csv.exists():
        print(f"Error: Variants CSV not found: {variants_csv}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("(dry run - no changes will be made)")

    # Get mapping first (for dry_run we still need it for reporting)
    mapping = apply_variant_decisions(
        keywords_csv,
        variants_csv,
        dry_run=args.dry_run,
    )

    if not mapping:
        print("No validated merge decisions to apply.")
        return 0

    if args.dry_run:
        print("Dry run - changes that would be applied to keywords.csv:")
    else:
        print(f"Applied {len(mapping)} keyword replacements to keywords.csv:")

    for old, canonical in sorted(mapping.items()):
        print(f"  '{old}' -> '{canonical}'")

    # Also apply to YAML files
    yaml_replacements = apply_variant_decisions_to_yaml(
        keywords_csv,
        mapping,
        dry_run=args.dry_run,
    )

    if yaml_replacements > 0:
        if args.dry_run:
            print(f"\nWould make {yaml_replacements} replacement(s) in YAML files")
        else:
            print(f"\nMade {yaml_replacements} replacement(s) in YAML files")
    else:
        print("\nNo YAML keyword replacements needed")

    return 0


def main_track() -> int:
    """Entry point for track-keyword-variants command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_args()
    return track_variants_main(args)


def main_apply() -> int:
    """Entry point for apply-variant-decisions command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_apply_args()
    return apply_variant_decisions_main(args)


if __name__ == "__main__":
    raise SystemExit(main_track())
