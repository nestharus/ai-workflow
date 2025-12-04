"""Passes table manager for artifact-level extraction.

This module manages the `.knowledge/facts/passes.csv` table that records each
Hunter -> Surgeon commit during artifact-level semantic fact extraction.

Each pass represents one extraction iteration where facts were removed from a span.

CSV Schema:
    pass_id: Unique UUID for this pass
    artifact_id: ID of the artifact being processed
    entity_id: Resolved entity ID
    entity_mention: Entity mention text as it appeared
    span_id: ID of the span that was rewritten
    span_before: Span text before rewrite
    span_after: Span text after rewrite
    facts_removed: JSON array of facts removed in this pass
    similarity_score: Qwen3 validation score (score_drop)
    status: Pass status ('success', 'failure', 'skipped')
    failure_reason: Explanation if status != 'success'
    created_at: ISO 8601 timestamp

Usage:
    from scripts.knowledge.passes_manager import append_pass, query_passes

    # Append a pass record
    append_pass(csv_path, PassRecord(...))

    # Query passes
    passes = query_passes(csv_path, artifact_id="artifact_123")

References:
    - docs/plans/fact_redesign.md lines 865-876
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TypedDict

import duckdb

PASSES_CSV_COLUMNS = [
    "pass_id",
    "artifact_id",
    "entity_id",
    "entity_mention",
    "span_id",
    "chunk_id",
    "span_before",
    "span_after",
    "facts_removed",
    "similarity_score",
    "status",
    "failure_reason",
    "created_at",
]


class PassRecord(TypedDict):
    """A pass record for the passes CSV.

    Attributes:
        pass_id: Unique UUID for this pass.
        artifact_id: ID of the artifact being processed.
        entity_id: Resolved entity ID.
        entity_mention: Entity mention text.
        span_id: ID of the span that was rewritten.
        chunk_id: Unique chunk ID combining artifact, pass, and span info.
        span_before: Span text before rewrite.
        span_after: Span text after rewrite.
        facts_removed: JSON array of facts removed.
        similarity_score: Qwen3 validation score (as string).
        status: Pass status ('success', 'failure', 'skipped').
        failure_reason: Explanation if status != 'success'.
        created_at: ISO 8601 timestamp.
    """

    pass_id: str
    artifact_id: str
    entity_id: str
    entity_mention: str
    span_id: str
    chunk_id: str
    span_before: str
    span_after: str
    facts_removed: str
    similarity_score: str
    status: str
    failure_reason: str
    created_at: str


def ensure_passes_csv_exists(csv_path: Path) -> None:
    """Create passes CSV file with header if it doesn't exist.

    Args:
        csv_path: Path to the passes CSV file.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not csv_path.exists() or csv_path.stat().st_size == 0
    if needs_header:
        cols_select = ", ".join(f"'' AS {col}" for col in PASSES_CSV_COLUMNS)
        query = f"COPY (SELECT * FROM (SELECT {cols_select}) WHERE 1=0) "
        query += f"TO '{csv_path}' (HEADER, DELIMITER ',')"
        duckdb.execute(query)


def append_pass(csv_path: Path, record: PassRecord) -> None:
    """Append a pass record to the passes CSV.

    Args:
        csv_path: Path to the passes CSV file.
        record: Pass record to append.
    """
    ensure_passes_csv_exists(csv_path)

    conn = duckdb.connect()
    try:
        conn.execute(f"""
            CREATE TABLE passes AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """)
        placeholders = ", ".join("?" for _ in PASSES_CSV_COLUMNS)
        values = [record[col] for col in PASSES_CSV_COLUMNS]  # type: ignore[literal-required]
        conn.execute(f"INSERT INTO passes VALUES ({placeholders})", values)
        conn.execute(f"COPY passes TO '{csv_path}' (HEADER, DELIMITER ',')")
    finally:
        conn.close()


def query_passes(
    csv_path: Path,
    artifact_id: str | None = None,
    entity_id: str | None = None,
) -> list[dict[str, str]]:
    """Query passes from the CSV file.

    Args:
        csv_path: Path to the passes CSV file.
        artifact_id: Optional artifact ID to filter by.
        entity_id: Optional entity ID to filter by.

    Returns:
        List of pass records as dictionaries.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return []

    try:
        if artifact_id and entity_id:
            query = """
                SELECT * FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
                WHERE artifact_id = ? AND entity_id = ?
                ORDER BY created_at
            """
            result = duckdb.execute(query, [str(csv_path), artifact_id, entity_id]).fetchall()
        elif artifact_id:
            query = """
                SELECT * FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
                WHERE artifact_id = ?
                ORDER BY created_at
            """
            result = duckdb.execute(query, [str(csv_path), artifact_id]).fetchall()
        elif entity_id:
            query = """
                SELECT * FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
                WHERE entity_id = ?
                ORDER BY created_at
            """
            result = duckdb.execute(query, [str(csv_path), entity_id]).fetchall()
        else:
            query = """
                SELECT * FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
                ORDER BY created_at
            """
            result = duckdb.execute(query, [str(csv_path)]).fetchall()

        return [{col: row[i] for i, col in enumerate(PASSES_CSV_COLUMNS)} for row in result]
    except duckdb.Error as e:
        print(f"Error querying passes from {csv_path}: {e}", file=sys.stderr)
        return []


def get_pass_by_id(csv_path: Path, pass_id: str) -> dict[str, str] | None:
    """Get a specific pass by ID.

    Args:
        csv_path: Path to the passes CSV file.
        pass_id: Pass UUID to find.

    Returns:
        Pass record if found, None otherwise.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return None

    query = """
        SELECT * FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE pass_id = ?
        LIMIT 1
    """
    try:
        result = duckdb.execute(query, [str(csv_path), pass_id]).fetchone()
        if result:
            return {col: result[i] for i, col in enumerate(PASSES_CSV_COLUMNS)}
    except duckdb.Error as e:
        print(f"Error querying pass {pass_id}: {e}", file=sys.stderr)

    return None


def count_passes(csv_path: Path, artifact_id: str | None = None) -> int:
    """Count passes in the CSV file.

    Args:
        csv_path: Path to the passes CSV file.
        artifact_id: Optional artifact ID to filter by.

    Returns:
        Number of passes.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return 0

    try:
        if artifact_id:
            query = """
                SELECT COUNT(*) FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
                WHERE artifact_id = ?
            """
            result = duckdb.execute(query, [str(csv_path), artifact_id]).fetchone()
        else:
            query = "SELECT COUNT(*) FROM read_csv_auto(?, ALL_VARCHAR=TRUE)"
            result = duckdb.execute(query, [str(csv_path)]).fetchone()

        return result[0] if result else 0
    except duckdb.Error:
        return 0


def backfill_legacy_passes(
    csv_path: Path,
    extractions_csv: Path,
) -> int:
    """Backfill passes from legacy sentence-level extractions.

    Creates one pass row per legacy fact extraction record.

    Args:
        csv_path: Path to the passes CSV file.
        extractions_csv: Path to legacy extractions.csv.

    Returns:
        Number of passes backfilled.
    """
    if not extractions_csv.exists() or extractions_csv.stat().st_size == 0:
        return 0

    ensure_passes_csv_exists(csv_path)

    # Read legacy extractions
    query = """
        SELECT fact_id, source_sentence, entity, fact_text, rewritten_sentence,
               confidence, extracted_at
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
    """
    try:
        result = duckdb.execute(query, [str(extractions_csv)]).fetchall()
    except duckdb.Error:
        return 0

    count = 0
    for row in result:
        (
            fact_id,
            source_sentence,
            entity,
            fact_text,
            rewritten_sentence,
            confidence,
            extracted_at,
        ) = row

        # Create pass record from legacy data
        import hashlib
        import json

        artifact_id = f"legacy:sentence:{hashlib.sha256(source_sentence.encode()).hexdigest()[:16]}"

        record = PassRecord(
            pass_id=fact_id,  # Use fact_id as pass_id
            artifact_id=artifact_id,
            entity_id=entity,
            entity_mention=entity,
            span_id="legacy:sentence",
            chunk_id=f"{artifact_id}:legacy:{fact_id[:8]}",
            span_before=source_sentence,
            span_after=rewritten_sentence,
            facts_removed=json.dumps([fact_text]),
            similarity_score=confidence,
            status="legacy_backfill",
            failure_reason="",
            created_at=extracted_at,
        )

        # Check if already exists
        existing = get_pass_by_id(csv_path, fact_id)
        if not existing:
            append_pass(csv_path, record)
            count += 1

    return count
