r"""Stage 1: High-recall keyword candidate extraction from YAML documentation.

This module scans YAML documentation files and extracts potential keyword candidates
using spaCy's transformer-based NLP pipeline (en_core_web_trf). Candidates are
generated through multiple strategies for maximum recall:

1. Named entities (spaCy doc.ents)
2. Noun chunks (spaCy doc.noun_chunks)
3. Regex heuristics:
   - File paths (e.g., app/services/foo.py)
   - CamelCase identifiers (e.g., ElasticsearchWrapper)
   - snake_case identifiers (e.g., connection_manager)

Field-Level Provenance (per fact_redesign.md lines 1308-1327):
    The CSV schema includes field-level provenance columns for structural alignment:

    - projection_version: Identifies slicing/FieldFact/text projection rules
      (e.g., 'fieldfacts.v2'). The text processed for candidates is a synthetic
      fact-line projection, not raw YAML text.

    - source_field_path: FieldFact.field_path containing the candidate span,
      enabling tracing candidates back to specific structural fields.

    - source_scope_path: FieldFact.scope_path for grouping context (e.g., all
      fields under a constraint group share the same scope).

    - field_role: FieldFact.role (constraint/entity_ref/artifact_root/metadata),
      indicating the semantic role of the source field.

    - artifact_kind: FieldFact.artifact_kind when role==artifact_root, identifying
      the artifact type (e.g., prose, code, mermaid).

    Note: start_char/end_char refer to positions in the synthetic fact-line
    projection (per lines 1311-1312), and sentence reflects fact-line context
    with ancestor chains and field paths.

    Schema evolution is append-only: existing CSV readers selecting original
    columns remain unaffected.

Usage:
    uv run knowledge.extract-keyword-candidates \
      --path docs/development \
      --knowledge-path .knowledge

Args:
    --path: Base docs directory containing YAML files (default: docs/development).
    --knowledge-path: Base knowledge directory (default: .knowledge).
"""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import duckdb

from scripts.dev.utils import REPO_ROOT, utc_timestamp
from scripts.knowledge.compare_yaml_docs import (
    extract_field_facts,
    extract_ids_and_text,
    parse_yaml_file,
)

if TYPE_CHECKING:
    from spacy.tokens import Doc

# Current projection version for text projection contract
# Per fact_redesign.md lines 1398-1426, this identifies:
# - Element slicing rules (nested-id replacement with $ref)
# - FieldFact extraction (roles, grouping, artifact root tagging)
# - Text projection format ([ancestor > element_id] field_path = value)
PROJECTION_VERSION = "fieldfacts.v2"

# CSV columns matching specification
# Per fact_redesign.md lines 1308-1327, includes field-level provenance columns
CSV_COLUMNS = [
    "candidate_id",
    "source_file",
    "element_id",
    "sentence",
    "candidate_text",
    "start_char",
    "end_char",
    "detected_at",
    "keep",
    "confidence",
    "reason",
    "classified_at",
    "qwen_score",
    # New columns for field-level provenance (per fact_redesign.md lines 1316-1321)
    # Append-only schema evolution: existing CSV readers selecting original columns
    # remain unaffected
    "projection_version",
    "source_field_path",
    "source_scope_path",
    "field_role",
    "artifact_kind",
]


class CandidateRecord(TypedDict):
    """A keyword candidate record extracted from documentation.

    Per fact_redesign.md lines 1308-1327, records include field-level provenance
    for structural alignment back to FieldFacts.

    Note: start_char/end_char now refer to positions in the synthetic fact-line
    projection (not raw YAML), and sentence reflects fact-line context with
    ancestor chains and field paths.

    Attributes:
        candidate_id: UUID (string) for this candidate.
        source_file: Relative path to the source YAML file.
        element_id: YAML element ID where term was found.
        sentence: Source snippet containing the candidate (from fact-line projection).
        candidate_text: Extracted term/phrase.
        start_char: Character offset in fact-line projection (string for CSV).
        end_char: Character offset end in fact-line projection (string for CSV).
        detected_at: ISO 8601 timestamp when detected.
        keep: "true"/"false"/"" (populated in Stage 2).
        confidence: Stringified float (e.g., "0.93").
        reason: Free-text explanation (populated in Stage 2).
        classified_at: Timestamp or "" (populated in Stage 2).
        qwen_score: Optional stringified float (Stage 2 assist).
        projection_version: Version of text projection contract (e.g., 'fieldfacts.v2').
        source_field_path: FieldFact.field_path containing candidate span (or empty).
        source_scope_path: FieldFact.scope_path for grouping context (or empty).
        field_role: FieldFact.role (constraint/entity_ref/artifact_root/metadata, or empty).
        artifact_kind: FieldFact.artifact_kind when role==artifact_root (or empty).
    """

    candidate_id: str
    source_file: str
    element_id: str
    sentence: str
    candidate_text: str
    start_char: str
    end_char: str
    detected_at: str
    keep: str
    confidence: str
    reason: str
    classified_at: str
    qwen_score: str
    projection_version: str
    source_field_path: str
    source_scope_path: str
    field_role: str
    artifact_kind: str


# Regex patterns for technical identifiers
FILE_PATH_PATTERN = re.compile(
    r"(?:^|[\s\"'`({\[])([a-zA-Z0-9_./\-]+(?:\.[a-zA-Z]{1,10}))(?=[\s\"'`)}:\],;]|$)"
)
CAMEL_CASE_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b")
SNAKE_CASE_PATTERN = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b")

# Additional patterns for technical terms
CODE_BACKTICK_PATTERN = re.compile(r"`([^`]+)`")
QUALIFIED_NAME_PATTERN = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_.]+\.[a-zA-Z_][a-zA-Z0-9_]+)\b")

# Chunking configuration for large text processing
# Maximum characters per chunk for spaCy processing (configurable)
CHUNK_THRESHOLD = 10000  # Characters above which we split into chunks
CHUNK_OVERLAP = 100  # Characters of overlap between chunks to avoid boundary issues


def split_text_into_chunks(
    text: str,
    threshold: int = CHUNK_THRESHOLD,
    overlap: int = CHUNK_OVERLAP,
) -> list[tuple[str, int]]:
    """Split text into overlapping chunks for processing large documents.

    Args:
        text: Full text to split.
        threshold: Maximum characters per chunk.
        overlap: Overlap between chunks to avoid boundary issues.

    Returns:
        List of (chunk_text, start_offset) tuples where start_offset is the
        character position in the original text where the chunk begins.
    """
    if len(text) <= threshold:
        return [(text, 0)]

    chunks: list[tuple[str, int]] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + threshold, text_len)

        # Try to break at whitespace to avoid splitting words
        if end < text_len:
            # Look for last whitespace within the chunk
            last_space = text.rfind(" ", start, end)
            if last_space > start + (threshold // 2):
                end = last_space + 1  # Include the space in this chunk

        chunk_text = text[start:end]
        chunks.append((chunk_text, start))

        # Move start for next chunk, accounting for overlap
        if end >= text_len:
            break
        start = end - overlap
        # Ensure we don't go backwards
        if start <= chunks[-1][1]:
            start = end

    return chunks


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


def append_candidates_batch(csv_path: Path, records: list[CandidateRecord]) -> None:
    """Append multiple candidate records to the CSV file efficiently.

    Uses DuckDB to read existing data, add new records in batch, and write back.

    Args:
        csv_path: Path to the CSV file.
        records: List of candidate records to append.
    """
    if not records:
        return

    conn = duckdb.connect()
    try:
        conn.execute(f"""
            CREATE TABLE candidates AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """)
        placeholders = ", ".join("?" for _ in CSV_COLUMNS)
        insert_sql = f"INSERT INTO candidates VALUES ({placeholders})"
        for record in records:
            values = [record[col] for col in CSV_COLUMNS]  # type: ignore[literal-required]
            conn.execute(insert_sql, values)
        conn.execute(f"COPY candidates TO '{csv_path}' (HEADER, DELIMITER ',')")
    finally:
        conn.close()


def get_existing_candidates(csv_path: Path) -> set[tuple[str, str, str]]:
    """Get set of existing (source_file, element_id, candidate_text) tuples.

    Args:
        csv_path: Path to the CSV file.

    Returns:
        Set of (source_file, element_id, candidate_text) tuples already tracked.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return set()

    query = """
        SELECT source_file, element_id, candidate_text
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
    """
    try:
        result = duckdb.execute(query, [str(csv_path)]).fetchall()
        return {(row[0], row[1], row[2]) for row in result}
    except duckdb.Error:
        return set()


def load_spacy_model() -> object:
    """Load spaCy transformer model.

    Returns:
        Loaded spaCy language model (spacy.Language).

    Raises:
        OSError: If model is not installed.
    """
    import spacy

    try:
        return spacy.load("en_core_web_trf")
    except OSError as exc:
        msg = (
            "spaCy model 'en_core_web_trf' not found. "
            "Install with: python -m spacy download en_core_web_trf"
        )
        raise OSError(msg) from exc


def get_sentence_context(text: str, start: int, end: int, context_chars: int = 100) -> str:
    """Extract sentence/context around a span position.

    Args:
        text: Full text content.
        start: Start character position.
        end: End character position.
        context_chars: Number of characters for context on each side.

    Returns:
        Sentence or context snippet containing the span.
    """
    # Find sentence boundaries (simple heuristic using periods)
    sent_start = text.rfind(".", 0, start)
    sent_start = sent_start + 1 if sent_start != -1 else max(0, start - context_chars)

    sent_end = text.find(".", end)
    sent_end = sent_end + 1 if sent_end != -1 else min(len(text), end + context_chars)

    return text[sent_start:sent_end].strip()


def extract_named_entities(doc: Doc, text: str) -> list[tuple[str, int, int, str]]:
    """Extract named entities from spaCy doc.

    Args:
        doc: Processed spaCy document.
        text: Original text for context extraction.

    Returns:
        List of (candidate_text, start_char, end_char, sentence) tuples.
    """
    candidates: list[tuple[str, int, int, str]] = []
    for ent in doc.ents:
        candidate_text = ent.text.strip()
        if len(candidate_text) >= 2:  # Skip single chars
            sentence = get_sentence_context(text, ent.start_char, ent.end_char)
            candidates.append((candidate_text, ent.start_char, ent.end_char, sentence))
    return candidates


def extract_noun_chunks(doc: Doc, text: str) -> list[tuple[str, int, int, str]]:
    """Extract noun chunks from spaCy doc.

    Args:
        doc: Processed spaCy document.
        text: Original text for context extraction.

    Returns:
        List of (candidate_text, start_char, end_char, sentence) tuples.
    """
    candidates: list[tuple[str, int, int, str]] = []
    for chunk in doc.noun_chunks:
        candidate_text = chunk.text.strip()
        if len(candidate_text) >= 2:  # Skip single chars
            sentence = get_sentence_context(text, chunk.start_char, chunk.end_char)
            candidates.append((candidate_text, chunk.start_char, chunk.end_char, sentence))
    return candidates


def extract_regex_candidates(text: str) -> list[tuple[str, int, int, str]]:
    """Extract candidates using regex patterns for technical terms.

    Args:
        text: Text content to scan.

    Returns:
        List of (candidate_text, start_char, end_char, sentence) tuples.
    """
    candidates: list[tuple[str, int, int, str]] = []

    # File paths (e.g., app/services/foo.py, /path/to/file)
    for match in FILE_PATH_PATTERN.finditer(text):
        candidate_text = match.group(1)
        start = match.start(1)
        end = match.end(1)
        # Filter out obvious non-paths
        valid_extensions = (".py", ".yml", ".yaml", ".json", ".md")
        if "/" in candidate_text or candidate_text.endswith(valid_extensions):
            sentence = get_sentence_context(text, start, end)
            candidates.append((candidate_text, start, end, sentence))

    # CamelCase identifiers (e.g., ElasticsearchWrapper, ConnectionManager)
    for match in CAMEL_CASE_PATTERN.finditer(text):
        candidate_text = match.group(1)
        start = match.start(1)
        end = match.end(1)
        sentence = get_sentence_context(text, start, end)
        candidates.append((candidate_text, start, end, sentence))

    # snake_case identifiers (e.g., connection_manager, get_user_by_id)
    for match in SNAKE_CASE_PATTERN.finditer(text):
        candidate_text = match.group(1)
        start = match.start(1)
        end = match.end(1)
        # Filter out very short matches
        if len(candidate_text) >= 4:
            sentence = get_sentence_context(text, start, end)
            candidates.append((candidate_text, start, end, sentence))

    # Code in backticks
    for match in CODE_BACKTICK_PATTERN.finditer(text):
        candidate_text = match.group(1).strip()
        start = match.start(1)
        end = match.end(1)
        if len(candidate_text) >= 2:
            sentence = get_sentence_context(text, start, end)
            candidates.append((candidate_text, start, end, sentence))

    # Qualified names (e.g., module.function, package.Class)
    for match in QUALIFIED_NAME_PATTERN.finditer(text):
        candidate_text = match.group(1)
        start = match.start(1)
        end = match.end(1)
        sentence = get_sentence_context(text, start, end)
        candidates.append((candidate_text, start, end, sentence))

    return candidates


def find_yaml_files(base_path: Path) -> list[Path]:
    """Find all YAML files in directory and subdirectories.

    Args:
        base_path: Base directory to search.

    Returns:
        Sorted list of YAML file paths.
    """
    yaml_files: list[Path] = []
    for pattern in ("*.yml", "*.yaml"):
        yaml_files.extend(base_path.rglob(pattern))
    return sorted(yaml_files)


def _build_offset_to_fact_mapping(
    text: str,
    facts: list[object],
) -> list[tuple[int, int, object]]:
    """Build a mapping from character offset ranges to FieldFacts.

    The text projection consists of sorted fact-lines, one per FieldFact.
    This function reconstructs which character range corresponds to which fact.

    Per fact_redesign.md lines 1478-1524, offsets in candidates.csv are relative
    to the concatenated fact-lines, and this mapping enables tracing back to
    the source FieldFact.

    Args:
        text: Full text projection (concatenated fact-lines).
        facts: List of FieldFact objects for the element.

    Returns:
        List of (start_offset, end_offset, fact) tuples, sorted by start_offset.
    """
    from scripts.knowledge.compare_yaml_docs import _fact_to_line

    # Sort facts by field_path to match how extract_ids_and_text produces text
    sorted_facts = sorted(facts, key=lambda f: f.field_path)  # type: ignore[attr-defined]

    # Build mapping by computing cumulative offsets
    mapping: list[tuple[int, int, object]] = []
    current_offset = 0

    for fact in sorted_facts:
        line = _fact_to_line(fact)  # type: ignore[arg-type]
        line_len = len(line)
        # Each line followed by newline (except possibly last)
        mapping.append((current_offset, current_offset + line_len, fact))
        current_offset += line_len + 1  # +1 for newline

    return mapping


def _find_fact_for_offset(
    offset: int,
    offset_mapping: list[tuple[int, int, object]],
) -> object | None:
    """Find the FieldFact containing a given character offset.

    Args:
        offset: Character offset in the text projection.
        offset_mapping: Mapping from (start, end, fact) as built by _build_offset_to_fact_mapping.

    Returns:
        FieldFact if offset falls within a fact's range, None otherwise.
    """
    for start, end, fact in offset_mapping:
        if start <= offset < end:
            return fact
    return None


def process_yaml_file(
    file_path: Path,
    nlp: object,
    existing: set[tuple[str, str, str]],
    timestamp: str,
) -> list[CandidateRecord]:
    """Process a single YAML file and extract candidates.

    Args:
        file_path: Path to YAML file.
        nlp: Loaded spaCy model (spacy.Language).
        existing: Set of already-tracked (source_file, element_id, candidate_text) tuples.
        timestamp: ISO timestamp for detection.

    Returns:
        List of new candidate records.
    """
    records: list[CandidateRecord] = []

    try:
        data = parse_yaml_file(file_path)
    except (ValueError, TypeError) as exc:
        print(f"Warning: Failed to parse {file_path}: {exc}", file=sys.stderr)
        return records

    # Get relative path for source_file column
    try:
        source_file = file_path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        source_file = file_path.as_posix()

    # Extract ID -> text mappings using sliced representations per the fact
    # redesign (lines 131-133 of docs/plans/fact_redesign.md). Child content
    # is excluded and replaced with $ref tokens, so candidates are extracted
    # only from the parent element's direct content.
    ids_text = extract_ids_and_text(data)

    # Extract FieldFacts for field-level provenance tracking
    # Per fact_redesign.md lines 1308-1327, candidates should include
    # source_field_path, source_scope_path, field_role, artifact_kind
    element_facts = extract_field_facts(data, source_file=source_file)

    for element_id, text in ids_text.items():
        if not text or not text.strip():
            continue

        # Build offset-to-fact mapping for this element
        facts = element_facts.get(element_id, [])
        offset_mapping = _build_offset_to_fact_mapping(text, facts)  # type: ignore[arg-type]

        # Collect all candidates from different methods
        all_candidates: list[tuple[str, int, int, str]] = []

        # Split text into chunks if needed for large documents
        chunks = split_text_into_chunks(text)

        for chunk_text, chunk_offset in chunks:
            # Process chunk with spaCy
            doc = nlp(chunk_text)  # type: ignore[operator]

            # Named entities (translate offsets back to original text)
            for cand_text, start, end, _ in extract_named_entities(doc, chunk_text):
                abs_start = start + chunk_offset
                abs_end = end + chunk_offset
                sentence = get_sentence_context(text, abs_start, abs_end)
                all_candidates.append((cand_text, abs_start, abs_end, sentence))

            # Noun chunks (translate offsets back to original text)
            for cand_text, start, end, _ in extract_noun_chunks(doc, chunk_text):
                abs_start = start + chunk_offset
                abs_end = end + chunk_offset
                sentence = get_sentence_context(text, abs_start, abs_end)
                all_candidates.append((cand_text, abs_start, abs_end, sentence))

        # Regex-based extraction operates on full text (no chunking needed)
        all_candidates.extend(extract_regex_candidates(text))

        # Deduplicate within this element (by text, start, end)
        seen: set[tuple[str, int, int]] = set()
        for candidate_text, start_char, end_char, sentence in all_candidates:
            key = (candidate_text, start_char, end_char)
            if key in seen:
                continue
            seen.add(key)

            # Check if already tracked globally
            global_key = (source_file, element_id, candidate_text)
            if global_key in existing:
                continue

            # Find the FieldFact containing this candidate's offset
            # Per fact_redesign.md lines 1478-1524, offsets are relative to
            # concatenated fact-lines
            matched_fact = _find_fact_for_offset(start_char, offset_mapping)

            # Extract provenance from matched fact (or use empty strings)
            if matched_fact is not None:
                source_field_path = getattr(matched_fact, "field_path", "")
                source_scope_path = getattr(matched_fact, "scope_path", "")
                field_role = getattr(matched_fact, "role", "")
                artifact_kind = getattr(matched_fact, "artifact_kind", "") or ""
            else:
                source_field_path = ""
                source_scope_path = ""
                field_role = ""
                artifact_kind = ""

            record = CandidateRecord(
                candidate_id=str(uuid.uuid4()),
                source_file=source_file,
                element_id=element_id,
                sentence=sentence,
                candidate_text=candidate_text,
                start_char=str(start_char),
                end_char=str(end_char),
                detected_at=timestamp,
                keep="",
                confidence="",
                reason="",
                classified_at="",
                qwen_score="",
                # New field-level provenance columns (per fact_redesign.md lines 1316-1321)
                projection_version=PROJECTION_VERSION,
                source_field_path=source_field_path,
                source_scope_path=source_scope_path,
                field_role=field_role,
                artifact_kind=artifact_kind,
            )
            records.append(record)
            existing.add(global_key)  # Track to avoid duplicates within run

    return records


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for candidate extraction.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Extract keyword candidates from YAML documentation using spaCy.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("docs/development"),
        help="Base docs directory containing YAML files (default: docs/development).",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def extract_candidates_main(args: argparse.Namespace) -> int:
    """Run candidate extraction from YAML documentation.

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error.
    """
    # Resolve paths
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    if args.path.is_absolute():
        source_path = args.path.resolve()
    else:
        source_path = (REPO_ROOT / args.path).resolve()

    if not source_path.exists():
        print(f"Error: Source directory not found: {source_path}", file=sys.stderr)
        return 1

    csv_path = knowledge_path / "keywords" / "candidates.csv"

    # Load spaCy model
    print("Loading spaCy model en_core_web_trf...")
    try:
        nlp = load_spacy_model()
    except OSError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Ensure CSV exists
    ensure_csv_exists(csv_path)

    # Get existing candidates to avoid duplicates
    existing = get_existing_candidates(csv_path)
    print(f"Found {len(existing)} existing candidates in {csv_path}")

    # Find YAML files
    yaml_files = find_yaml_files(source_path)
    print(f"Found {len(yaml_files)} YAML files in {source_path}")

    if not yaml_files:
        print("No YAML files found to process.")
        return 0

    # Process each file
    timestamp = utc_timestamp()
    all_records: list[CandidateRecord] = []
    total_files = len(yaml_files)

    for idx, yaml_file in enumerate(yaml_files, 1):
        try:
            rel_path = yaml_file.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel_path = yaml_file.as_posix()

        print(f"[{idx}/{total_files}] Processing: {rel_path}")
        records = process_yaml_file(yaml_file, nlp, existing, timestamp)
        all_records.extend(records)

    # Batch write all records
    if all_records:
        print(f"\nWriting {len(all_records)} new candidates to {csv_path}")
        append_candidates_batch(csv_path, all_records)
    else:
        print("\nNo new candidates found.")

    print(f"\nTotal: {len(all_records)} candidates extracted")
    print(f"Output: {csv_path}")

    return 0


def main() -> int:
    """Entry point for knowledge.extract-keyword-candidates command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_args()
    return extract_candidates_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
