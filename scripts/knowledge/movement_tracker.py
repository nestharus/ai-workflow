"""Track information movements between files during migrations.

This module provides utilities for recording information movements from source
files to target files during documentation migrations. It tracks the source/target
locations, reasons for the move, coverage descriptions, and before/after sentence
context for validation purposes.

Movement records link to resolution records via `element_id` to track the complete
lifecycle of information changes during migrations.

Additionally, this module supports iterative sentence-level fact movements during
fact extraction, tracking per-iteration sentence changes with semantic similarity
validation using Qwen embeddings.

Usage:
    # File-level movement tracking
    uv run knowledge.record-movement --id <element_id> --source-file <path> --target-file <path> \
        --reason "..." --coverage "..." --before-text "..." --after-text-source "..." \
        --target-before "..." --target-after "..."

    # Legacy sentence-level movement tracking
    uv run knowledge.record-iterative-movement --fact-id <uuid> --before "..." --fact "..." \
        --after "..."

    # Artifact-level movement tracking (with pass/span/artifact IDs)
    uv run knowledge.record-iterative-movement --fact-id <uuid> --before "..." --fact "..." \
        --after "..." --pass-id <pass_uuid> --span-id <span_id> --artifact-id <artifact_id>

    # Query iterative movements
    uv run knowledge.query-iterative-movements --entity "create_app"
    uv run knowledge.query-iterative-movements --fact-id <uuid>

Args:
    --id: Element identifier being moved (links to comparisons/resolutions).
    --source-file: Path to the source file where information originated.
    --target-file: Path to the target file where information was moved.
    --reason: Explanation of why the information was moved.
    --coverage: Description of what information is being covered/moved.
    --before-text: Original sentence in source file before the move.
    --after-text-source: Sentence in source file after information was removed.
    --target-before: Sentence in target file before information was added.
    --target-after: Sentence in target file after information was added.
    --knowledge-path: Base knowledge directory (default: .knowledge).
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import duckdb

from scripts.dev.utils import REPO_ROOT, utc_timestamp
from scripts.knowledge.variant_resolver import (
    compute_cosine_similarity,
    embed_keywords,
    load_qwen_embedding_model,
)

if TYPE_CHECKING:
    from transformers import PreTrainedModel, PreTrainedTokenizer

CSV_COLUMNS = [
    "movement_id",
    "element_id",
    "source_file",
    "target_file",
    "reason",
    "coverage_description",
    "before_sentence",
    "after_sentence_source",
    "target_before_sentence",
    "target_after_sentence",
    "moved_at",
]

ITERATIVE_CSV_COLUMNS = [
    "iteration_id",
    "fact_id",
    "source_sentence",
    "isolated_fact",
    "residual_sentence",
    "similarity_score",
    "reason",
    "moved_at",
    # Extended columns for artifact-level extraction (pass/span model)
    "pass_id",
    "span_id",
    "artifact_id",
    "schema_version",
]


class MovementRecord(TypedDict):
    """A movement record for tracking information movements between files.

    Attributes:
        movement_id: Unique UUID for this movement record.
        element_id: YAML element identifier being moved.
        source_file: Relative path to the source file where information originated.
        target_file: Relative path to the target file where information was moved.
        reason: Explanation of why the information was moved.
        coverage_description: Description of what information is being covered/moved.
        before_sentence: Original sentence in source file before the move.
        after_sentence_source: Sentence in source file after information was removed.
        target_before_sentence: Sentence in target file before information was added.
        target_after_sentence: Sentence in target file after information was added.
        moved_at: ISO 8601 basic format timestamp of the movement.
    """

    movement_id: str
    element_id: str
    source_file: str
    target_file: str
    reason: str
    coverage_description: str
    before_sentence: str
    after_sentence_source: str
    target_before_sentence: str
    target_after_sentence: str
    moved_at: str


class IterativeMovementRecord(TypedDict, total=False):
    """A record for tracking iterative sentence/span-level fact movements.

    Tracks per-iteration sentence/span changes during fact extraction, linking to
    fact records via fact_id for traceability. Includes semantic similarity
    validation score computed using Qwen embeddings.

    Extended for artifact-level extraction to support the pass/span model where
    movements are tracked per-pass with span context.

    Attributes:
        iteration_id: Unique UUID for this iteration record.
        fact_id: Links to fact record in facts/extractions.csv.
        source_sentence: Sentence/span text before this fact extraction.
        isolated_fact: The atomic fact extracted in this iteration.
        residual_sentence: Sentence/span text after this fact was removed.
        similarity_score: Cosine similarity between source and (fact + residual), 0.0-1.0.
        reason: Explanation for this movement (typically "Fact extraction").
        moved_at: ISO 8601 basic format timestamp (YYYYMMDDTHHMMSSZ, UTC).
        pass_id: Links to pass record in facts/passes.csv (artifact-level extraction).
        span_id: Identifier for the span within the artifact being processed.
        artifact_id: Identifier for the artifact being processed.
        schema_version: Schema version for backward compatibility (default: "1.0").
    """

    # Required base fields
    iteration_id: str
    fact_id: str
    source_sentence: str
    isolated_fact: str
    residual_sentence: str
    similarity_score: str
    reason: str
    moved_at: str
    # Extended fields for artifact-level extraction (optional for backward compat)
    pass_id: str
    span_id: str
    artifact_id: str
    schema_version: str


def ensure_csv_exists(csv_path: Path) -> None:
    """Create CSV file with header row if it doesn't exist or is empty.

    Uses DuckDB to create an empty CSV with proper headers.

    Args:
        csv_path: Path to the CSV file.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not csv_path.exists() or csv_path.stat().st_size == 0
    if needs_header:
        cols_select = ", ".join(f"'' AS {col}" for col in CSV_COLUMNS)
        query = f"COPY (SELECT * FROM (SELECT {cols_select}) WHERE 1=0) "
        query += f"TO '{csv_path}' (HEADER, DELIMITER ',')"
        duckdb.execute(query)


def append_movement(csv_path: Path, record: MovementRecord) -> None:
    """Append a movement record to the CSV file.

    Uses DuckDB to read existing data, add the new record, and write back.

    Args:
        csv_path: Path to the CSV file.
        record: Movement record to append.
    """
    conn = duckdb.connect()
    try:
        create_query = f"""
            CREATE TABLE movements AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """
        conn.execute(create_query)
        placeholders = ", ".join("?" for _ in CSV_COLUMNS)
        values = [record[col] for col in CSV_COLUMNS]  # type: ignore[literal-required]
        conn.execute(f"INSERT INTO movements VALUES ({placeholders})", values)
        conn.execute(f"COPY movements TO '{csv_path}' (HEADER, DELIMITER ',')")
    finally:
        conn.close()


def ensure_iterative_csv_exists(csv_path: Path) -> None:
    """Create iterative movements CSV file with header row if it doesn't exist.

    Uses DuckDB to create an empty CSV with proper headers for iterative
    sentence-level movement tracking.

    Args:
        csv_path: Path to the iterative movements CSV file.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not csv_path.exists() or csv_path.stat().st_size == 0
    if needs_header:
        cols_select = ", ".join(f"'' AS {col}" for col in ITERATIVE_CSV_COLUMNS)
        query = f"COPY (SELECT * FROM (SELECT {cols_select}) WHERE 1=0) "
        query += f"TO '{csv_path}' (HEADER, DELIMITER ',')"
        duckdb.execute(query)


def compute_similarity_score(
    before: str,
    fact: str,
    after: str,
    model: PreTrainedModel,
    tokenizer: PreTrainedTokenizer,
) -> float:
    """Compute semantic similarity between original sentence and reconstructed.

    Validates that the original sentence can be reconstructed from the extracted
    fact and residual sentence by computing cosine similarity of their embeddings.

    Args:
        before: Original sentence before fact extraction.
        fact: The atomic fact extracted from the sentence.
        after: Residual sentence after fact was removed.
        model: Loaded Qwen model for embeddings.
        tokenizer: Loaded Qwen tokenizer.

    Returns:
        Cosine similarity score between 0.0 and 1.0.
    """
    # Reconstruct sentence from fact and residual
    reconstructed = f"{fact} {after}".strip() if after.strip() else fact

    # Compute embeddings using shared utility
    embeddings = embed_keywords([before, reconstructed], model, tokenizer, batch_size=2)

    # Compute pairwise similarity matrix
    similarity_matrix = compute_cosine_similarity(embeddings)

    # Return off-diagonal element (similarity between the two texts)
    return float(similarity_matrix[0, 1])


def append_iterative_movement(csv_path: Path, record: IterativeMovementRecord) -> None:
    """Append an iterative movement record to the CSV file.

    Uses DuckDB to read existing data, add the new record, and write back.
    Handles extended schema with defaults for backward compatibility.

    Args:
        csv_path: Path to the iterative movements CSV file.
        record: Iterative movement record to append.
    """
    conn = duckdb.connect()
    try:
        conn.execute(f"""
            CREATE TABLE iterative_movements AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """)
        placeholders = ", ".join("?" for _ in ITERATIVE_CSV_COLUMNS)
        # Handle extended schema with defaults for backward compatibility
        values = [
            record.get("iteration_id", ""),
            record.get("fact_id", ""),
            record.get("source_sentence", ""),
            record.get("isolated_fact", ""),
            record.get("residual_sentence", ""),
            record.get("similarity_score", ""),
            record.get("reason", ""),
            record.get("moved_at", ""),
            record.get("pass_id", "legacy:sentence"),
            record.get("span_id", "legacy:sentence"),
            record.get("artifact_id", ""),
            record.get("schema_version", "1.0"),
        ]
        conn.execute(f"INSERT INTO iterative_movements VALUES ({placeholders})", values)
        conn.execute(f"COPY iterative_movements TO '{csv_path}' (HEADER, DELIMITER ',')")
    finally:
        conn.close()


def query_iterative_movements(
    csv_path: Path,
    entity: str | None = None,
    fact_id: str | None = None,
) -> list[dict[str, str]]:
    """Query iterative movements by entity or fact_id.

    Returns all movements if no filters provided. DuckDB errors are logged to
    stderr and an empty list is returned to allow graceful degradation.

    Args:
        csv_path: Path to the iterative movements CSV file.
        entity: Optional entity to search for in source_sentence (case-insensitive).
        fact_id: Optional fact_id to filter by exact match.

    Returns:
        List of matching movement records as dictionaries. Returns empty list
        if file is empty, doesn't exist, or if a DuckDB error occurs (with error
        logged to stderr).
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return []

    try:
        if fact_id:
            query = """
                SELECT * FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
                WHERE fact_id = ?
                ORDER BY moved_at
            """
            result = duckdb.execute(query, [str(csv_path), fact_id]).fetchall()
        elif entity:
            query = """
                SELECT * FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
                WHERE LOWER(source_sentence) LIKE LOWER('%' || ? || '%')
                ORDER BY moved_at
            """
            result = duckdb.execute(query, [str(csv_path), entity]).fetchall()
        else:
            query = """
                SELECT * FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
                ORDER BY moved_at
            """
            result = duckdb.execute(query, [str(csv_path)]).fetchall()

        return [
            {
                "iteration_id": row[0],
                "fact_id": row[1],
                "source_sentence": row[2],
                "isolated_fact": row[3],
                "residual_sentence": row[4],
                "similarity_score": row[5],
                "reason": row[6],
                "moved_at": row[7],
                # Extended columns (may be empty for legacy records)
                "pass_id": row[8] if len(row) > 8 else "",
                "span_id": row[9] if len(row) > 9 else "",
                "artifact_id": row[10] if len(row) > 10 else "",
                "schema_version": row[11] if len(row) > 11 else "1.0",
            }
            for row in result
        ]
    except duckdb.Error as e:
        print(
            f"Error querying iterative movements from {csv_path}: {e}",
            file=sys.stderr,
        )
        return []


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for movement tracking.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Track information movements between files during migrations.",
    )
    parser.add_argument(
        "--id",
        required=True,
        help="Element identifier being moved (links to comparisons/resolutions).",
    )
    parser.add_argument(
        "--source-file",
        type=Path,
        required=True,
        help="Path to the source file where information originated.",
    )
    parser.add_argument(
        "--target-file",
        type=Path,
        required=True,
        help="Path to the target file where information was moved.",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Explanation of why the information was moved.",
    )
    parser.add_argument(
        "--coverage",
        required=True,
        help="Description of what information is being covered/moved.",
    )
    parser.add_argument(
        "--before-text",
        required=True,
        help="Original sentence in source file before the move.",
    )
    parser.add_argument(
        "--after-text-source",
        required=True,
        help="Sentence in source file after information was removed.",
    )
    parser.add_argument(
        "--target-before",
        required=True,
        help="Sentence in target file before information was added.",
    )
    parser.add_argument(
        "--target-after",
        required=True,
        help="Sentence in target file after information was added.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        help="Base knowledge directory, relative to REPO_ROOT or absolute (default: .knowledge).",
    )
    return parser.parse_args(argv)


def main() -> int:
    """Run movement tracking and record results.

    Returns:
        0 on success, 1 on error.
    """
    args = parse_args()

    source_file = (REPO_ROOT / args.source_file).resolve()
    target_file = (REPO_ROOT / args.target_file).resolve()

    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    if not source_file.exists():
        print(f"Error: Source file not found: {source_file}", file=sys.stderr)
        return 1

    if not target_file.exists():
        print(f"Error: Target file not found: {target_file}", file=sys.stderr)
        return 1

    if not source_file.is_relative_to(REPO_ROOT):
        print(f"Error: Source file must be within repository: {source_file}", file=sys.stderr)
        return 1

    if not target_file.is_relative_to(REPO_ROOT):
        print(f"Error: Target file must be within repository: {target_file}", file=sys.stderr)
        return 1

    source_file_rel = source_file.relative_to(REPO_ROOT).as_posix()
    target_file_rel = target_file.relative_to(REPO_ROOT).as_posix()

    movement_id = str(uuid.uuid4())
    moved_at = utc_timestamp()

    record = MovementRecord(
        movement_id=movement_id,
        element_id=args.id,
        source_file=source_file_rel,
        target_file=target_file_rel,
        reason=args.reason,
        coverage_description=args.coverage,
        before_sentence=args.before_text,
        after_sentence_source=args.after_text_source,
        target_before_sentence=args.target_before,
        target_after_sentence=args.target_after,
        moved_at=moved_at,
    )

    csv_path = knowledge_path / "movements" / "movements.csv"
    ensure_csv_exists(csv_path)
    append_movement(csv_path, record)

    print(f"Movement recorded with ID: {movement_id}")
    return 0


def parse_record_iterative_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for recording iterative movements.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Record an iterative sentence/span-level fact movement with validation.",
    )
    parser.add_argument(
        "--fact-id",
        required=True,
        dest="fact_id",
        help="UUID linking to fact record in facts/extractions.csv.",
    )
    parser.add_argument(
        "--before",
        required=True,
        help="Original sentence/span before fact extraction.",
    )
    parser.add_argument(
        "--fact",
        required=True,
        help="The atomic fact extracted from the sentence/span.",
    )
    parser.add_argument(
        "--after",
        required=True,
        help="Residual sentence/span after fact was removed.",
    )
    parser.add_argument(
        "--reason",
        default="Fact extraction",
        help="Explanation for this movement (default: 'Fact extraction').",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    parser.add_argument(
        "--model",
        default="Qwen/Qwen3-Embedding-0.6B",
        help="HuggingFace model for embeddings (default: Qwen/Qwen3-Embedding-0.6B).",
    )
    # Extended arguments for artifact-level extraction
    parser.add_argument(
        "--pass-id",
        dest="pass_id",
        help="Pass ID linking to facts/passes.csv (artifact-level extraction).",
    )
    parser.add_argument(
        "--span-id",
        dest="span_id",
        help="Span ID within the artifact being processed.",
    )
    parser.add_argument(
        "--artifact-id",
        dest="artifact_id",
        help="Artifact ID being processed.",
    )
    return parser.parse_args(argv)


def record_iterative_movement_main(args: argparse.Namespace) -> int:
    """Record an iterative sentence/span-level fact movement with validation.

    Loads Qwen model to compute similarity score, validates semantic similarity,
    and records the movement to the iterative movements CSV. The record is always
    persisted for debugging purposes, but a non-zero exit code indicates validation
    failure when similarity is below the required threshold.

    Supports both legacy sentence-level extraction (with auto-generated markers)
    and artifact-level extraction (with explicit --pass-id, --span-id, --artifact-id).

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success (similarity >= 0.95).
        1 on error (model loading failure, file I/O error).
        2 on validation failure (similarity < 0.95, record still persisted).
    """
    import hashlib

    # Resolve knowledge path
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    csv_path = knowledge_path / "movements" / "iterative_movements.csv"

    # Load Qwen model for similarity validation
    print(f"Loading embedding model {args.model}...")
    try:
        model, tokenizer = load_qwen_embedding_model(args.model)
    except Exception as e:
        print(f"Error loading model: {e}", file=sys.stderr)
        return 1

    # Compute similarity score
    similarity = compute_similarity_score(args.before, args.fact, args.after, model, tokenizer)

    # Create record
    iteration_id = str(uuid.uuid4())
    moved_at = utc_timestamp()

    # Use CLI-provided values if available, otherwise fall back to legacy markers
    if getattr(args, "pass_id", None) and getattr(args, "span_id", None) and getattr(args, "artifact_id", None):
        # Artifact-level extraction with explicit IDs
        pass_id = args.pass_id
        span_id = args.span_id
        artifact_id = args.artifact_id
    else:
        # Legacy sentence-level extraction with auto-generated markers
        sentence_hash = hashlib.sha256(args.before.encode()).hexdigest()[:16]
        pass_id = args.fact_id  # Use fact_id as pass_id for legacy
        span_id = "legacy:sentence"
        artifact_id = f"legacy:sentence:{sentence_hash}"

    record = IterativeMovementRecord(
        iteration_id=iteration_id,
        fact_id=args.fact_id,
        source_sentence=args.before,
        isolated_fact=args.fact,
        residual_sentence=args.after,
        similarity_score=f"{similarity:.4f}",
        reason=args.reason,
        moved_at=moved_at,
        pass_id=pass_id,
        span_id=span_id,
        artifact_id=artifact_id,
        schema_version="1.0",
    )

    # Ensure CSV exists and append record (always persist for debugging)
    ensure_iterative_csv_exists(csv_path)
    append_iterative_movement(csv_path, record)

    print(f"Iterative movement recorded with ID: {iteration_id}")
    print(f"Similarity score: {similarity:.4f}")

    # Validate similarity threshold - return non-zero if validation fails
    if similarity < 0.95:
        print(
            f"VALIDATION FAILED: Low similarity score ({similarity:.4f} < 0.95). "
            "Some information may have been lost.",
            file=sys.stderr,
        )
        return 2

    return 0


def parse_query_iterative_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for querying iterative movements.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Query iterative sentence-level fact movements.",
    )
    parser.add_argument(
        "--entity",
        help="Entity to search for in source_sentence (case-insensitive).",
    )
    parser.add_argument(
        "--fact-id",
        dest="fact_id",
        help="Fact ID to filter by exact match.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show full extraction chain details (source, fact, residual sentences).",
    )
    return parser.parse_args(argv)


def _truncate(text: str, max_length: int = 50) -> str:
    """Truncate text to max_length, adding ellipsis if truncated.

    Args:
        text: Text to truncate.
        max_length: Maximum length including ellipsis.

    Returns:
        Truncated text with ellipsis if longer than max_length.
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def query_iterative_movements_main(args: argparse.Namespace) -> int:
    """Query iterative movements and display results in tabular format.

    In default mode, shows a compact view with truncated sentences. Use --verbose
    to see full extraction chain details including complete source, fact, and
    residual sentences.

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error.
    """
    # Validate at least one filter
    if not args.entity and not args.fact_id:
        print("Error: At least one of --entity or --fact-id is required.", file=sys.stderr)
        return 1

    # Resolve knowledge path
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    csv_path = knowledge_path / "movements" / "iterative_movements.csv"

    if not csv_path.exists():
        print(f"Error: Iterative movements CSV not found: {csv_path}", file=sys.stderr)
        return 1

    # Query movements
    results = query_iterative_movements(csv_path, entity=args.entity, fact_id=args.fact_id)

    if not results:
        print("No matching iterative movements found.")
        return 0

    verbose = getattr(args, "verbose", False)

    if verbose:
        # Verbose mode: show full extraction chain details
        for i, record in enumerate(results):
            if i > 0:
                print()
            print(f"--- Record {i + 1} ---")
            print(f"iteration_id:      {record['iteration_id']}")
            print(f"fact_id:           {record['fact_id']}")
            print(f"similarity_score:  {record['similarity_score']}")
            print(f"reason:            {record['reason']}")
            print(f"moved_at:          {record['moved_at']}")
            print(f"source_sentence:   {record['source_sentence']}")
            print(f"isolated_fact:     {record['isolated_fact']}")
            print(f"residual_sentence: {record['residual_sentence']}")
    else:
        # Compact mode: truncated table with key fields
        print(
            f"{'iteration_id':<40} {'similarity':<12} "
            f"{'source_sentence':<52} {'isolated_fact':<52}"
        )
        print("-" * 160)
        for record in results:
            print(
                f"{record['iteration_id']:<40} "
                f"{record['similarity_score']:<12} "
                f"{_truncate(record['source_sentence']):<52} "
                f"{_truncate(record['isolated_fact']):<52}"
            )

    print(f"\nTotal: {len(results)} record(s)")
    return 0


def main_record_iterative() -> int:
    """Entry point for knowledge.record-iterative-movement command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_record_iterative_args()
    return record_iterative_movement_main(args)


def main_query_iterative() -> int:
    """Entry point for knowledge.query-iterative-movements command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_query_iterative_args()
    return query_iterative_movements_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
