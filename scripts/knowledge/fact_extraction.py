"""Iterative fact extraction about entities/keywords from sentences.

This module orchestrates the fact-extractor sub-agent to extract atomic facts
about a given entity from a sentence. Facts are extracted one at a time, with
the sentence rewritten after each extraction, until no facts about the entity
remain. Results are stored in `.knowledge/facts/extractions.csv`.

NOTE: This is the legacy sentence-level extraction path, preserved for debugging.
For production use, see `knowledge.extract-artifact-facts` which uses the
multi-agent artifact-level extraction pipeline (Hunter -> Surgeon -> Auditor).

The CLI first attempts to use the fact-extractor sub-agent (haiku model). If the
sub-agent succeeds, Qwen embeddings are used to re-validate the extraction results.
If the sub-agent is unavailable, the CLI falls back to inline heuristic-based
extraction which also uses Qwen embeddings for validation.

Usage:
    # Extract facts about an entity from a sentence
    uv run knowledge.extract-facts \
      --sentence "Mount all versioned endpoints under /api/{version} using create_app in app/core/factory.py." \
      --entity "create_app"

    # Specify custom knowledge path
    uv run knowledge.extract-facts --sentence "..." --entity "FastAPI" --knowledge-path .knowledge

    # Dry run (show facts without storing)
    uv run knowledge.extract-facts --sentence "..." --entity "FastAPI" --dry-run

    # Use a heavier model for higher-precision validation
    uv run knowledge.extract-facts --sentence "..." --entity "FastAPI" --model Qwen/Qwen3-Embedding-8B

Args:
    --sentence: The sentence to extract facts from (required).
    --entity: The entity/keyword to extract facts about (required).
    --knowledge-path: Base knowledge directory (default: .knowledge).
    --dry-run: Show extracted facts without storing to CSV.
    --model: HuggingFace model for embeddings (default: Qwen/Qwen3-Embedding-0.6B).
             For higher precision, use Qwen/Qwen3-Embedding-8B.

Future enhancements:
    --input-file: Batch processing from YAML/JSONL file (not yet implemented).

Extended Schema (per docs/plans/fact_redesign.md lines 849-863):
    The CSV now includes provenance columns for artifact-level extraction:
    - source_file, source_element_id, source_field_path: Source location
    - artifact_id, span_id, pass_id: Artifact extraction context
    - entity_mention, entity_id: Entity identification
    - extraction_model, rewrite_model: Models used
    - state_hash_before, state_hash_after: State tracking

    Legacy sentence-level extractions use markers:
    - pass_id = fact_id
    - span_id = 'legacy:sentence'
    - artifact_id = 'legacy:sentence:<sha256(source_sentence)>'
    - extraction_model = 'legacy'
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
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

# CSV columns for fact extraction records (extended schema per fact_redesign.md)
CSV_COLUMNS = [
    "fact_id",
    "source_sentence",
    "entity",
    "fact_text",
    "rewritten_sentence",
    "iteration",
    "confidence",
    "extracted_at",
    # Extended provenance columns (artifact-level extraction)
    "source_file",
    "source_element_id",
    "source_field_path",
    "artifact_id",
    "span_id",
    "pass_id",
    "entity_mention",
    "entity_id",
    "extraction_model",
    "rewrite_model",
    "state_hash_before",
    "state_hash_after",
]


class FactRecord(TypedDict, total=False):
    """A fact extraction record with extended provenance.

    Core Attributes (always present):
        fact_id: UUID for this fact extraction record.
        source_sentence: Original sentence before any extraction.
        entity: Entity/keyword being extracted.
        fact_text: Extracted atomic fact about the entity.
        rewritten_sentence: Sentence after this fact was removed.
        iteration: Iteration number (1-indexed, as string).
        confidence: Confidence score (0.0-1.0, as string).
        extracted_at: ISO 8601 timestamp.

    Extended Provenance Attributes (optional, for artifact-level extraction):
        source_file: YAML file path where fact originated.
        source_element_id: Element ID within YAML file.
        source_field_path: Field path within element.
        artifact_id: Artifact ID for artifact-level extraction.
        span_id: Span ID within artifact.
        pass_id: Pass ID linking to passes.csv.
        entity_mention: Entity mention as it appeared in text.
        entity_id: Resolved entity ID.
        extraction_model: Model used for extraction.
        rewrite_model: Model used for rewriting.
        state_hash_before: State hash before this extraction.
        state_hash_after: State hash after this extraction.

    Legacy sentence-level extractions use markers:
        - pass_id = fact_id
        - span_id = 'legacy:sentence'
        - artifact_id = 'legacy:sentence:<sha256(source_sentence)>'
        - extraction_model = 'legacy'
    """

    # Core fields (required)
    fact_id: str
    source_sentence: str
    entity: str
    fact_text: str
    rewritten_sentence: str
    iteration: str
    confidence: str
    extracted_at: str
    # Extended provenance fields (optional)
    source_file: str
    source_element_id: str
    source_field_path: str
    artifact_id: str
    span_id: str
    pass_id: str
    entity_mention: str
    entity_id: str
    extraction_model: str
    rewrite_model: str
    state_hash_before: str
    state_hash_after: str


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


def append_fact_batch(csv_path: Path, records: list[FactRecord]) -> None:
    """Append multiple fact records to the CSV file efficiently.

    Uses DuckDB to read existing data, add new records in batch, and write back.
    Handles extended schema by using empty strings for missing columns.
    Supports backward compatibility with old CSVs that have fewer columns.

    Args:
        csv_path: Path to the CSV file.
        records: List of fact records to append.
    """
    if not records:
        return

    conn = duckdb.connect()
    try:
        # Read existing CSV - may have old schema with fewer columns
        conn.execute(f"""
            CREATE TABLE facts_old AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """)

        # Get existing columns from the old table
        existing_cols_result = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'facts_old' ORDER BY ordinal_position"
        ).fetchall()
        existing_cols = {row[0] for row in existing_cols_result}

        # Build SELECT statement that adds missing columns with empty string defaults
        select_cols = []
        for col in CSV_COLUMNS:
            if col in existing_cols:
                select_cols.append(col)
            else:
                select_cols.append(f"'' AS {col}")

        # Create new table with full schema from old data
        select_sql = ", ".join(select_cols)
        conn.execute(f"CREATE TABLE facts AS SELECT {select_sql} FROM facts_old")

        # Insert new records
        placeholders = ", ".join("?" for _ in CSV_COLUMNS)
        insert_sql = f"INSERT INTO facts VALUES ({placeholders})"
        for record in records:
            # Use empty string for missing extended columns
            values = [record.get(col, "") for col in CSV_COLUMNS]  # type: ignore[literal-required]
            conn.execute(insert_sql, values)
        conn.execute(f"COPY facts TO '{csv_path}' (HEADER, DELIMITER ',')")
    finally:
        conn.close()


def get_existing_facts(csv_path: Path, entity: str) -> list[dict[str, str]]:
    """Query existing facts for an entity.

    Args:
        csv_path: Path to the CSV file.
        entity: Entity to query facts for.

    Returns:
        List of fact dictionaries for the entity.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return []

    query = """
        SELECT fact_id, source_sentence, entity, fact_text, rewritten_sentence,
               iteration, confidence, extracted_at
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE entity = ?
        ORDER BY extracted_at, iteration
    """
    try:
        result = duckdb.execute(query, [str(csv_path), entity]).fetchall()
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
    except duckdb.Error:
        return []


def compute_pairwise_similarity(
    texts: list[str],
    model: PreTrainedModel,
    tokenizer: PreTrainedTokenizer,
) -> float:
    """Compute cosine similarity between two texts.

    Uses the shared embedding utilities from variant_resolver.

    Args:
        texts: List of exactly two texts to compare.
        model: Loaded Qwen model.
        tokenizer: Loaded Qwen tokenizer.

    Returns:
        Cosine similarity score (0.0-1.0).
    """
    if len(texts) != 2:
        return 0.0

    # Compute embeddings using shared utility
    embeddings = embed_keywords(texts, model, tokenizer, batch_size=2)

    # Compute pairwise similarity matrix
    similarity_matrix = compute_cosine_similarity(embeddings)

    # Return the similarity between the two texts (off-diagonal element)
    return float(similarity_matrix[0, 1])


def validate_fact_extraction(
    original: str,
    facts: list[str],
    residual: str,
    model: PreTrainedModel,
    tokenizer: PreTrainedTokenizer,
) -> tuple[float, bool]:
    """Validate semantic similarity between original and extracted facts + residual.

    Args:
        original: Original sentence before extraction.
        facts: List of extracted fact texts.
        residual: Residual sentence after all extractions.
        model: Loaded Qwen model.
        tokenizer: Loaded Qwen tokenizer.

    Returns:
        Tuple of (similarity_score, information_preserved).
    """
    # Combine facts and residual into reconstructed meaning
    combined_parts = facts + [residual] if residual.strip() else facts
    reconstructed = " ".join(combined_parts)

    # Compute similarity using shared utility
    similarity = compute_pairwise_similarity([original, reconstructed], model, tokenizer)

    # Information is preserved if similarity >= 0.95
    information_preserved = similarity >= 0.95

    return similarity, information_preserved


class FactExtractorError(Exception):
    """Error raised when the fact-extractor sub-agent fails."""


def invoke_fact_extractor(sentence: str, entity: str) -> dict:
    """Invoke the fact-extractor sub-agent via subprocess.

    This function invokes the Claude sub-agent (using haiku model for cost-efficiency)
    to perform the actual fact extraction. The agent outputs JSON to stdout which is
    parsed and returned.

    Args:
        sentence: The sentence to extract facts from.
        entity: The entity/keyword to extract facts about.

    Returns:
        Parsed JSON output from the agent.

    Raises:
        FactExtractorError: If the sub-agent invocation fails or returns invalid JSON.
    """
    # Build the prompt for the sub-agent following the contract in fact-extractor.md
    # Simple format that the agent expects
    prompt = f'Extract facts about entity "{entity}" from sentence: "{sentence}"'

    # Invoke the sub-agent using claude CLI with haiku model for cost-efficiency
    try:
        result = subprocess.run(
            [
                "claude",
                "--agent",
                "fact-extractor",
                "--model",
                "haiku",
                "--print",
                "--prompt",
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=REPO_ROOT,
        )
    except subprocess.TimeoutExpired as e:
        raise FactExtractorError(f"Sub-agent timed out after 120 seconds: {e}") from e
    except FileNotFoundError as e:
        raise FactExtractorError(f"Claude CLI not found: {e}") from e
    except subprocess.SubprocessError as e:
        raise FactExtractorError(f"Sub-agent invocation failed: {e}") from e

    if result.returncode != 0:
        raise FactExtractorError(
            f"Sub-agent returned non-zero exit code {result.returncode}: {result.stderr}"
        )

    # Parse JSON output from stdout
    stdout = result.stdout.strip()
    if not stdout:
        raise FactExtractorError("Sub-agent returned empty output")

    # Try to find JSON in the output (agent might include other text)
    json_start = stdout.find("{")
    json_end = stdout.rfind("}") + 1
    if json_start == -1 or json_end == 0:
        raise FactExtractorError(f"No JSON found in sub-agent output: {stdout[:200]}")

    json_str = stdout[json_start:json_end]

    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise FactExtractorError(f"Invalid JSON in sub-agent output: {e}") from e

    # Validate required fields match the documented contract
    required_fields = ["entity", "original_sentence", "facts", "residual_sentence", "validation"]
    missing_fields = [f for f in required_fields if f not in parsed]
    if missing_fields:
        raise FactExtractorError(f"Missing required fields in output: {missing_fields}")

    return parsed


def extract_facts_inline(
    sentence: str,
    entity: str,
    model: PreTrainedModel,
    tokenizer: PreTrainedTokenizer,
) -> dict:
    """Extract facts about an entity from a sentence (inline implementation).

    This is a best-effort fallback implementation when the sub-agent is not available.
    It performs simple fact extraction based on sentence structure using heuristics.

    Note: This inline extraction may not fully eliminate all entity-related facts from
    the residual sentence. Check the 'extraction_complete' field in the result to
    determine if extraction was successful.

    Args:
        sentence: The sentence to extract facts from.
        entity: The entity/keyword to extract facts about.
        model: Loaded Qwen model for validation.
        tokenizer: Loaded Qwen tokenizer.

    Returns:
        Dictionary with extraction results including 'extraction_complete' flag.
    """
    facts: list[dict[str, str | float]] = []
    current_sentence = sentence
    iteration = 0
    max_iterations = 10

    while entity.lower() in current_sentence.lower() and iteration < max_iterations:
        iteration += 1

        # Simple heuristic: find clauses containing the entity
        # This is a simplified version; the full agent would use spaCy dependency parsing

        # Look for patterns like "entity in path" or "using entity"
        entity_lower = entity.lower()
        sentence_lower = current_sentence.lower()

        # Find entity position
        entity_pos = sentence_lower.find(entity_lower)
        if entity_pos == -1:
            break

        # Try to extract a fact based on surrounding context
        fact_text = None
        rewritten = None

        # Pattern: "entity in path" (location constraint)
        if " in " in sentence_lower[entity_pos:]:
            in_pos = sentence_lower.find(" in ", entity_pos)
            if in_pos != -1:
                # Find the end of the path (next punctuation or end)
                end_pos = len(current_sentence)
                for punct in [".", ",", " using", " and", " or"]:
                    punct_pos = current_sentence.lower().find(punct, in_pos + 4)
                    if punct_pos != -1 and punct_pos < end_pos:
                        end_pos = punct_pos

                path_part = current_sentence[in_pos + 4 : end_pos].strip()
                if path_part and "/" in path_part:
                    fact_text = f"{entity} is located in {path_part}"
                    # Remove this part from the sentence
                    rewritten = current_sentence[:in_pos] + current_sentence[end_pos:]
                    rewritten = rewritten.replace("  ", " ").strip()
                    if rewritten.endswith(" ."):
                        rewritten = rewritten[:-2] + "."

        # Pattern: "using entity" (usage constraint)
        if fact_text is None and "using " + entity_lower in sentence_lower:
            using_pos = sentence_lower.find("using " + entity_lower)
            if using_pos != -1:
                # Get the context before "using"
                before_using = current_sentence[:using_pos].strip()
                if before_using:
                    action = (
                        before_using.split()[-3:]
                        if len(before_using.split()) >= 3
                        else before_using.split()
                    )
                    action_text = " ".join(action)
                    fact_text = f"{entity} is used to {action_text.lower()}"
                    # Remove "using entity" from sentence
                    after_entity = current_sentence[using_pos + len("using " + entity) :]
                    rewritten = current_sentence[:using_pos].strip()
                    if after_entity.strip():
                        rewritten += after_entity
                    rewritten = rewritten.replace("  ", " ").strip()

        if fact_text and rewritten:
            # Validate this extraction
            test_similarity, _ = validate_fact_extraction(
                current_sentence,
                [fact_text],
                rewritten,
                model,
                tokenizer,
            )
            confidence = min(0.99, test_similarity)

            # Store fact with its rewritten_sentence (per-iteration)
            facts.append(
                {
                    "fact": fact_text,
                    "confidence": confidence,
                    "rewritten_sentence": rewritten,
                }
            )
            current_sentence = rewritten
        else:
            # Can't extract more facts with simple heuristics
            break

    # Check if extraction is complete (entity no longer present)
    entity_absent = entity.lower() not in current_sentence.lower()

    # Final validation
    fact_texts = [str(f["fact"]) for f in facts]
    similarity, information_preserved = validate_fact_extraction(
        sentence,
        fact_texts,
        current_sentence,
        model,
        tokenizer,
    )

    return {
        "entity": entity,
        "original_sentence": sentence,
        "facts": facts,
        "residual_sentence": current_sentence,
        "total_iterations": len(facts),
        "extraction_complete": entity_absent,
        "validation": {
            "semantic_similarity": similarity,
            "entity_absent": entity_absent,
            "information_preserved": information_preserved,
        },
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for fact extraction.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Extract facts about an entity from a sentence.",
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
    return parser.parse_args(argv)


def extract_facts_main(args: argparse.Namespace) -> int:
    """Run fact extraction from a sentence.

    The extraction flow:
    1. Attempt sub-agent invocation first (no Qwen model needed yet)
    2. If sub-agent succeeds, load Qwen model to re-validate results
    3. If sub-agent fails, load Qwen model and use inline extraction

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error, 2 on incomplete extraction.
    """
    # Resolve paths
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    csv_path = knowledge_path / "facts" / "extractions.csv"

    print(f"Extracting facts about '{args.entity}' from sentence...")
    print(f'Sentence: "{args.sentence}"')
    print()

    # Try to invoke the sub-agent first (before loading Qwen model)
    result = None
    use_inline = False

    try:
        print("Invoking fact-extractor sub-agent...")
        result = invoke_fact_extractor(args.sentence, args.entity)
        print("Sub-agent extraction complete.")
    except FactExtractorError as e:
        print(f"Sub-agent unavailable: {e}", file=sys.stderr)
        use_inline = True

    # Load Qwen model lazily - only when needed for validation or inline extraction
    print(f"Loading embedding model {args.model} for validation...")
    try:
        model, tokenizer = load_qwen_embedding_model(args.model)
    except Exception as e:
        print(f"Error loading model: {e}", file=sys.stderr)
        return 1

    # Fall back to inline extraction if sub-agent failed
    if use_inline:
        print("Using inline extraction (best-effort heuristics)...")
        result = extract_facts_inline(args.sentence, args.entity, model, tokenizer)
    else:
        # Sub-agent succeeded: re-validate results using Qwen embeddings
        print("Re-validating sub-agent results with Qwen embeddings...")
        facts = result.get("facts", [])
        residual = result.get("residual_sentence", "")
        fact_texts = [str(f.get("fact", "")) for f in facts]

        similarity, information_preserved = validate_fact_extraction(
            args.sentence,
            fact_texts,
            residual,
            model,
            tokenizer,
        )

        # Check entity absence
        entity_absent = args.entity.lower() not in residual.lower()

        # Update validation with locally computed values
        result["validation"] = {
            "semantic_similarity": similarity,
            "entity_absent": entity_absent,
            "information_preserved": information_preserved,
        }
        result["extraction_complete"] = entity_absent

    # Display results
    facts = result.get("facts", [])
    residual = result.get("residual_sentence", "")
    validation = result.get("validation", {})
    extraction_complete = result.get("extraction_complete", validation.get("entity_absent", False))

    if not facts:
        print(f"No facts about '{args.entity}' could be extracted from the sentence.")
        return 0

    for i, fact_info in enumerate(facts, 1):
        fact_text = fact_info.get("fact", "")
        confidence = fact_info.get("confidence", 0.0)
        rewritten = fact_info.get("rewritten_sentence", "")
        print(f"Iteration {i}:")
        print(f'  Fact: "{fact_text}"')
        print(f"  Confidence: {confidence:.2f}")
        if rewritten:
            print(f'  Rewritten: "{rewritten}"')
        print()

    print("Extraction complete:")
    print(f"  Total facts: {len(facts)}")
    print(f'  Residual: "{residual}"')
    print(f"  Semantic similarity: {validation.get('semantic_similarity', 0):.2f}")
    print(f"  Entity absent: {'Yes' if validation.get('entity_absent') else 'No'}")
    print(f"  Information preserved: {'Yes' if validation.get('information_preserved') else 'No'}")
    print(f"  Extraction complete: {'Yes' if extraction_complete else 'No (best-effort)'}")
    print()

    # Warn if validation failed
    if not validation.get("information_preserved"):
        print(
            "WARNING: Semantic similarity < 0.95. Some information may have been lost.",
            file=sys.stderr,
        )

    if not extraction_complete:
        print(
            f"WARNING: Entity '{args.entity}' is still present in the residual sentence.",
            file=sys.stderr,
        )
        print(
            "NOTE: Inline extraction is best-effort and may not fully extract all entity facts.",
            file=sys.stderr,
        )

    # Store to CSV unless dry run
    if args.dry_run:
        print("(dry run - no changes made)")
        # Return 2 for incomplete extraction even in dry run
        return 0 if extraction_complete else 2

    # Ensure CSV exists
    ensure_csv_exists(csv_path)

    # Create fact records with per-iteration rewritten_sentence
    timestamp = utc_timestamp()
    records: list[FactRecord] = []

    # Compute artifact_id for legacy sentence-level extraction
    sentence_hash = hashlib.sha256(args.sentence.encode("utf-8")).hexdigest()[:16]
    legacy_artifact_id = f"legacy:sentence:{sentence_hash}"

    for i, fact_info in enumerate(facts, 1):
        # Use per-iteration rewritten_sentence from the fact
        rewritten_sentence = fact_info.get("rewritten_sentence", "")
        # Fall back to residual for last iteration if not provided
        if not rewritten_sentence and i == len(facts):
            rewritten_sentence = residual

        fact_id = str(uuid.uuid4())
        record = FactRecord(
            fact_id=fact_id,
            source_sentence=args.sentence,
            entity=args.entity,
            fact_text=str(fact_info.get("fact", "")),
            rewritten_sentence=rewritten_sentence,
            iteration=str(i),
            confidence=f"{fact_info.get('confidence', 0.0):.4f}",
            extracted_at=timestamp,
            # Extended provenance fields with legacy markers
            source_file="",
            source_element_id="",
            source_field_path="",
            artifact_id=legacy_artifact_id,
            span_id="legacy:sentence",
            pass_id=fact_id,  # Use fact_id as pass_id for legacy
            entity_mention=args.entity,
            entity_id=args.entity,
            extraction_model="legacy",
            rewrite_model="legacy",
            state_hash_before="",
            state_hash_after="",
        )
        records.append(record)

    # Batch append to CSV
    append_fact_batch(csv_path, records)
    print(f"Stored {len(records)} fact(s) to {csv_path}")

    # Return 2 for incomplete extraction to signal partial success
    return 0 if extraction_complete else 2


def main() -> int:
    """Entry point for knowledge.extract-facts command.

    Returns:
        Exit code: 0 on success, 1 on error, 2 on incomplete extraction.
    """
    args = parse_args()
    return extract_facts_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
