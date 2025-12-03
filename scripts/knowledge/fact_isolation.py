"""Orchestrate fact isolation workflow with validation and reporting.

NOTE: This is the legacy sentence-level isolation path, preserved for debugging.
For production use, see `knowledge.extract-artifact-facts` which uses the
multi-agent artifact-level extraction pipeline (Hunter -> Surgeon -> Auditor).

For artifact-level extraction, use `artifact_fact_extractor.py` which writes
pass-level records directly to passes.csv with span/pass alignment.

This module wraps `fact_extraction.extract_facts_main()`, reads per-iteration
results from CSV, validates extraction completeness, and prepares for future
integration with iterative movement tracking.

The isolation workflow:
1. CLI calls `fact_extraction.extract_facts_main()` directly
2. Reads per-iteration results from `facts/extractions.csv`
3. Validates extraction completeness (entity absence, semantic similarity)
4. Prepares movement record data and writes to isolation CSV
5. Outputs detailed report with validation status

Extended Schema (per docs/plans/fact_redesign.md lines 821-824):
    Movement records now include pass_id and span_id fields:
    - pass_id: Links to passes.csv for artifact-level extraction
    - span_id: Identifies the span within the artifact
    - schema_version: 'legacy' for sentence-level, 'v2' for artifact-level

Usage:
    # Isolate facts about an entity from a sentence
    uv run knowledge.isolate-entity-facts \
      --sentence "Mount all versioned endpoints under /api/{version} using create_app in app/core/factory.py." \
      --entity "create_app"

    # Dry run (show report without storing)
    uv run knowledge.isolate-entity-facts --sentence "..." --entity "FastAPI" --dry-run

    # Specify custom knowledge path
    uv run knowledge.isolate-entity-facts --sentence "..." --entity "FastAPI" --knowledge-path .knowledge

    # Specify output CSV for isolation records
    uv run knowledge.isolate-entity-facts --sentence "..." --entity "FastAPI" --output isolation.csv

Args:
    --sentence: The sentence to extract facts from (required).
    --entity: The entity/keyword to extract facts about (required).
    --knowledge-path: Base knowledge directory (default: .knowledge).
    --dry-run: Show extracted facts without storing to CSV.
    --model: HuggingFace model for embeddings (default: Qwen/Qwen3-Embedding-0.6B).
    --output: Path to output CSV for isolation records (default: facts/isolation_records.csv).

Exit Codes:
    0: Success - extraction complete and validated
    1: Error - CLI or validation failure
    2: Partial success - facts extracted but entity still present in residual
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

import duckdb

from scripts.dev.utils import REPO_ROOT
from scripts.knowledge import fact_extraction
from scripts.knowledge.variant_resolver import (
    compute_cosine_similarity,
    embed_keywords,
    load_qwen_embedding_model,
)

if TYPE_CHECKING:
    from transformers import PreTrainedModel, PreTrainedTokenizer

# CSV columns for isolation records (extended schema per fact_redesign.md)
ISOLATION_CSV_COLUMNS = [
    "fact_id",
    "iteration",
    "entity",
    "before_sentence",
    "isolated_fact",
    "after_sentence",
    # Extended columns for artifact-level extraction
    "pass_id",
    "span_id",
    "schema_version",
]


class IterativeMovementRecord(TypedDict, total=False):
    """Movement record for tracking sentence changes per iteration.

    Core Attributes (always present):
        fact_id: UUID linking to the originating fact record.
        iteration: Iteration number (1-indexed).
        before_sentence: Sentence before this fact extraction.
        isolated_fact: The atomic fact extracted in this iteration.
        after_sentence: Sentence after this fact was removed.
        entity: The entity being extracted.

    Extended Attributes (optional, for artifact-level extraction):
        pass_id: Links to passes.csv for artifact-level extraction.
        span_id: Identifies the span within the artifact.
        schema_version: 'legacy' for sentence-level, 'v2' for artifact-level.
    """

    # Core fields (required)
    fact_id: str
    iteration: int
    before_sentence: str
    isolated_fact: str
    after_sentence: str
    entity: str
    # Extended fields (optional)
    pass_id: str
    span_id: str
    schema_version: str


class ValidationResult(TypedDict):
    """Validation result for fact isolation.

    Attributes:
        extraction_complete: Whether all facts were successfully extracted.
        entity_absent: Whether the entity is absent from residual sentence.
        information_preserved: Whether semantic similarity >= 0.95.
        semantic_similarity: The computed similarity score (0.0-1.0).
        total_facts: Total number of facts extracted.
    """

    extraction_complete: bool
    entity_absent: bool
    information_preserved: bool
    semantic_similarity: float
    total_facts: int


def read_extraction_results(
    csv_path: Path,
    source_sentence: str,
    entity: str,
) -> list[dict[str, str]]:
    """Query extraction results from CSV for a given sentence and entity.

    Uses DuckDB to read and filter facts from the extractions.csv file.

    Args:
        csv_path: Path to the extractions.csv file.
        source_sentence: Original sentence to match.
        entity: Entity to filter by.

    Returns:
        List of fact records ordered by iteration, empty if none found.

    Note:
        Logs warnings to stderr for unexpected DuckDB errors rather than
        silently swallowing them.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return []

    query = """
        SELECT fact_id, source_sentence, entity, fact_text, rewritten_sentence,
               iteration, confidence, extracted_at
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE source_sentence = ? AND entity = ?
        ORDER BY CAST(iteration AS INTEGER)
    """
    try:
        result = duckdb.execute(query, [str(csv_path), source_sentence, entity]).fetchall()
        return [
            {
                "fact_id": row[0],
                "source_sentence": row[1],
                "entity": row[2],
                "fact_text": row[3],
                "rewritten_sentence": row[4],
                "iteration": row[5],
                "confidence": row[6],
                "extracted_at": row[7],
            }
            for row in result
        ]
    except duckdb.Error as e:
        print(
            f"Warning: DuckDB error querying {csv_path}: {e}",
            file=sys.stderr,
        )
        return []


def compute_semantic_similarity(
    original: str,
    reconstructed: str,
    model: PreTrainedModel,
    tokenizer: PreTrainedTokenizer,
) -> float:
    """Compute cosine similarity between original and reconstructed sentences.

    Uses Qwen embeddings to compute semantic similarity.

    Args:
        original: Original sentence before extraction.
        reconstructed: Reconstructed sentence (facts + residual joined).
        model: Loaded Qwen embedding model.
        tokenizer: Loaded Qwen tokenizer.

    Returns:
        Cosine similarity score (0.0-1.0).
    """
    texts = [original, reconstructed]
    embeddings = embed_keywords(texts, model, tokenizer, batch_size=2)
    similarity_matrix = compute_cosine_similarity(embeddings)
    return float(similarity_matrix[0, 1])


def validate_isolation(
    facts: list[dict[str, str]],
    residual: str,
    entity: str,
    original_sentence: str,
    model: PreTrainedModel | None = None,
    tokenizer: PreTrainedTokenizer | None = None,
) -> ValidationResult:
    """Validate that fact isolation was successful.

    Checks that the entity is absent from the residual sentence and computes
    semantic similarity between the original sentence and the reconstruction
    of all extracted facts plus the final residual.

    Args:
        facts: List of extracted fact records.
        residual: Residual sentence after all extractions.
        entity: The entity that was extracted.
        original_sentence: The original sentence before any extraction.
        model: Loaded Qwen embedding model for similarity computation.
        tokenizer: Loaded Qwen tokenizer.

    Returns:
        ValidationResult with extraction_complete, entity_absent,
        information_preserved, semantic_similarity, and total_facts.
    """
    # Check entity absence from residual sentence
    entity_absent = entity.lower() not in residual.lower()

    # Compute semantic similarity between original and reconstructed sentence
    semantic_similarity = 0.0
    information_preserved = False

    if facts and model is not None and tokenizer is not None:
        # Reconstruct sentence from facts and residual
        fact_texts = [fact.get("fact_text", "") for fact in facts]
        reconstructed = ". ".join(fact_texts + [residual]) if residual else ". ".join(fact_texts)

        # Compute similarity
        semantic_similarity = compute_semantic_similarity(
            original_sentence,
            reconstructed,
            model,
            tokenizer,
        )
        information_preserved = semantic_similarity >= 0.95
    elif not facts:
        # No facts extracted - information not preserved
        information_preserved = False
        semantic_similarity = 0.0

    # Extraction is complete if entity is absent and we extracted at least one fact
    extraction_complete = entity_absent and len(facts) > 0 and information_preserved

    return ValidationResult(
        extraction_complete=extraction_complete,
        entity_absent=entity_absent,
        information_preserved=information_preserved,
        semantic_similarity=semantic_similarity,
        total_facts=len(facts),
    )


def prepare_movement_records(
    facts: list[dict[str, str]],
    source_sentence: str,
    entity: str,
) -> list[IterativeMovementRecord]:
    """Prepare movement record data structures for each iteration.

    For each fact extraction iteration, creates a movement record that tracks
    the before/after state of the sentence. These records include the fact_id
    for linking back to the originating fact record.

    Legacy sentence-level records use markers:
    - pass_id = fact_id
    - span_id = 'legacy:sentence'
    - schema_version = 'legacy'

    Args:
        facts: List of extracted fact records ordered by iteration.
        source_sentence: Original sentence before any extraction.
        entity: The entity being extracted.

    Returns:
        List of IterativeMovementRecord structures with fact_id linkage.
    """
    records: list[IterativeMovementRecord] = []
    current_sentence = source_sentence

    for fact in facts:
        fact_id = fact.get("fact_id", "")
        iteration = int(fact.get("iteration", "0"))
        fact_text = fact.get("fact_text", "")
        rewritten = fact.get("rewritten_sentence", "")

        record = IterativeMovementRecord(
            fact_id=fact_id,
            iteration=iteration,
            before_sentence=current_sentence,
            isolated_fact=fact_text,
            after_sentence=rewritten,
            entity=entity,
            # Extended fields with legacy markers
            pass_id=fact_id,  # Use fact_id as pass_id for legacy
            span_id="legacy:sentence",
            schema_version="legacy",
        )
        records.append(record)

        # Update current sentence for next iteration
        current_sentence = rewritten

    return records


def write_isolation_records(csv_path: Path, records: list[IterativeMovementRecord]) -> None:
    """Write isolation records to CSV file.

    Uses DuckDB to efficiently write records to CSV. Handles extended schema
    by using empty strings for missing columns.

    Args:
        csv_path: Path to output CSV file.
        records: List of isolation records to write.
    """
    if not records:
        return

    csv_path.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect()
    try:
        # Create table with columns
        cols_def = ", ".join(f"{col} VARCHAR" for col in ISOLATION_CSV_COLUMNS)
        conn.execute(f"CREATE TABLE isolation_records ({cols_def})")

        # Insert records
        placeholders = ", ".join("?" for _ in ISOLATION_CSV_COLUMNS)
        insert_sql = f"INSERT INTO isolation_records VALUES ({placeholders})"
        for record in records:
            values = [
                record.get("fact_id", ""),
                str(record.get("iteration", 0)),
                record.get("entity", ""),
                record.get("before_sentence", ""),
                record.get("isolated_fact", ""),
                record.get("after_sentence", ""),
                # Extended columns with defaults
                record.get("pass_id", ""),
                record.get("span_id", ""),
                record.get("schema_version", "legacy"),
            ]
            conn.execute(insert_sql, values)

        # Write to CSV
        conn.execute(f"COPY isolation_records TO '{csv_path}' (HEADER, DELIMITER ',')")
    finally:
        conn.close()


def _create_args_namespace(**kwargs: Any) -> argparse.Namespace:
    """Create an argparse.Namespace with the specified keyword arguments.

    Args:
        **kwargs: Key-value pairs to set as namespace attributes.

    Returns:
        Namespace object with the specified attributes.
    """
    return argparse.Namespace(**kwargs)


def isolate_entity_facts_main(args: argparse.Namespace) -> int:
    """Run fact isolation orchestration.

    Main orchestration function that:
    1. Calls fact_extraction.extract_facts_main() directly
    2. Reads extraction results from CSV
    3. Validates isolation completeness with semantic similarity
    4. Prepares movement records and writes to output CSV
    5. Outputs detailed report

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error, 2 on incomplete extraction.
    """
    # Resolve knowledge path
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    csv_path = knowledge_path / "facts" / "extractions.csv"

    # Resolve output path
    if args.output is None:
        output_path = knowledge_path / "facts" / "isolation_records.csv"
    elif args.output.is_absolute():
        output_path = args.output.resolve()
    else:
        output_path = (REPO_ROOT / args.output).resolve()

    print("Fact Isolation Report")
    print("=" * 50)
    print(f"Entity: {args.entity}")
    print(f"Original sentence: \"{args.sentence}\"")
    print()

    # Step 1: Call fact_extraction.extract_facts_main() directly
    print("Step 1: Running fact extraction...")
    print("-" * 30)

    extraction_args = _create_args_namespace(
        sentence=args.sentence,
        entity=args.entity,
        knowledge_path=args.knowledge_path,
        dry_run=args.dry_run,
        model=args.model,
    )

    extraction_result = fact_extraction.extract_facts_main(extraction_args)

    if extraction_result == 1:
        print("\nError: Fact extraction failed.", file=sys.stderr)
        return 1

    print()
    print("-" * 30)

    # In dry-run mode, short-circuit after extraction and return success
    if args.dry_run:
        print("\nStep 2: Reading extraction results...")
        print("(dry run - skipping CSV read)")
        print("\nStep 3: Validating isolation...")
        print("(dry run - skipping validation)")
        print("\nStep 4: Preparing movement records...")
        print("(dry run - skipping output)")
        print()
        print("=" * 50)
        print("Status: Success (dry run)")
        return 0

    # Step 2: Read extraction results from CSV
    print("\nStep 2: Reading extraction results...")

    facts = read_extraction_results(csv_path, args.sentence, args.entity)

    if not facts:
        print("No facts found in CSV for this sentence/entity combination.")
        residual = args.sentence
    else:
        # Get residual from last fact's rewritten_sentence
        residual = facts[-1].get("rewritten_sentence", "")

    # Step 3: Validate isolation with semantic similarity
    print("\nStep 3: Validating isolation...")

    # Load embedding model for semantic similarity computation
    model = None
    tokenizer = None
    if facts:
        print(f"Loading embedding model {args.model} for validation...")
        try:
            model, tokenizer = load_qwen_embedding_model(args.model)
        except Exception as e:
            print(f"Warning: Could not load embedding model: {e}", file=sys.stderr)

    validation = validate_isolation(
        facts,
        residual,
        args.entity,
        args.sentence,
        model,
        tokenizer,
    )

    print("\nExtraction Results:")
    for fact in facts:
        iteration = fact.get("iteration", "?")
        fact_text = fact.get("fact_text", "")
        print(f"  Iteration {iteration}: \"{fact_text}\"")

    if residual:
        print(f"  Residual: \"{residual}\"")
    else:
        print("  Residual: (empty)")

    print()
    print("Validation:")
    status_entity = "+" if validation["entity_absent"] else "x"
    status_info = "+" if validation["information_preserved"] else "x"
    status_complete = "+" if validation["extraction_complete"] else "x"

    print(f"  [{status_entity}] Entity absent from residual")
    print(f"  [{status_info}] Information preserved (similarity: {validation['semantic_similarity']:.2f})")
    print(f"  [{status_complete}] Extraction complete")

    # Step 4: Prepare movement records and write to CSV
    print("\nStep 4: Preparing movement records...")

    movement_records = prepare_movement_records(facts, args.sentence, args.entity)

    print(f"\nMovement Records Prepared: {len(movement_records)}")

    # Write to output CSV
    if movement_records:
        write_isolation_records(output_path, movement_records)
        print(f"Isolation records written to: {output_path}")

        print()
        print("Movement Record Summary:")
        for record in movement_records:
            before_display = record["before_sentence"][:60]
            after_display = record["after_sentence"][:60]
            print(f"  Iteration {record['iteration']} (fact_id: {record['fact_id'][:8]}...):")
            print(f"    Before: \"{before_display}...\"")
            print(f"    Fact: \"{record['isolated_fact']}\"")
            print(f"    After: \"{after_display}...\"")

    print()
    print("=" * 50)

    # Return appropriate exit code
    if extraction_result == 2 or not validation["extraction_complete"]:
        print("Status: Partial success (entity still present in residual)")
        return 2

    print("Status: Success")
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for fact isolation.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Orchestrate fact isolation with validation and reporting.",
    )
    parser.add_argument(
        "--sentence",
        required=True,
        help="The sentence to extract facts from.",
    )
    parser.add_argument(
        "--entity",
        required=True,
        help="The entity/keyword to extract facts about.",
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
        dest="dry_run",
        help="Show extracted facts without storing to CSV.",
    )
    parser.add_argument(
        "--model",
        default="Qwen/Qwen3-Embedding-0.6B",
        help=(
            "HuggingFace model for embeddings (default: Qwen/Qwen3-Embedding-0.6B). "
            "For higher precision, use Qwen/Qwen3-Embedding-8B."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Path to output CSV for isolation records "
            "(default: <knowledge-path>/facts/isolation_records.csv)."
        ),
    )
    return parser.parse_args(argv)


def main() -> int:
    """Entry point for knowledge.isolate-entity-facts command.

    Returns:
        Exit code: 0 on success, 1 on error, 2 on incomplete extraction.
    """
    args = parse_args()
    return isolate_entity_facts_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
