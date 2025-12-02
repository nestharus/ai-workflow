"""Apply classified keywords back to YAML documentation files and maintain keyword index.

This module provides utilities for:
1. Reading kept keyword candidates from candidates.csv (where keep='true')
2. Merging keywords into YAML elements as a `keywords:` list
3. Maintaining a global keyword index in `.knowledge/keywords/keywords.csv`

Usage:
    # Apply all kept keywords to YAML files and update index
    uv run knowledge.apply-keywords-to-yaml

    # Specify custom knowledge path
    uv run knowledge.apply-keywords-to-yaml --knowledge-path .knowledge

    # Dry run (show changes without applying)
    uv run knowledge.apply-keywords-to-yaml --dry-run

Args:
    --knowledge-path: Base knowledge directory (default: .knowledge).
    --dry-run: Show changes without modifying files.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypedDict

import duckdb
import yaml

from scripts.dev.utils import REPO_ROOT, utc_timestamp
from scripts.knowledge.compare_yaml_docs import parse_yaml_file
from scripts.knowledge.keyword_schema import KEYWORD_COLUMNS


class ReadCandidatesError(Exception):
    """Raised when reading candidates.csv fails due to DuckDB or CSV errors."""


class KeywordRecord(TypedDict):
    """A keyword record for the keywords.csv index.

    Attributes:
        keyword: Canonical term (string).
        source_file: YAML path (relative to repo root).
        element_id: YAML element ID where keyword was found.
        snippet: Optional sentence or short excerpt.
        first_detected: ISO 8601 timestamp when first detected.
        last_updated: ISO 8601 timestamp when last updated.
    """

    keyword: str
    source_file: str
    element_id: str
    snippet: str
    first_detected: str
    last_updated: str


class KeptCandidate(TypedDict):
    """A kept candidate from candidates.csv with keep='true'.

    Attributes:
        source_file: Relative path to the source YAML file.
        element_id: YAML element ID where term was found.
        candidate_text: Extracted term/phrase (the keyword).
        sentence: Source snippet containing the candidate.
    """

    source_file: str
    element_id: str
    candidate_text: str
    sentence: str


def ensure_keywords_csv_exists(csv_path: Path) -> None:
    """Create keywords CSV file with header row if it doesn't exist or is empty.

    Uses DuckDB to create an empty CSV with proper headers.

    Args:
        csv_path: Path to the keywords CSV file.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not csv_path.exists() or csv_path.stat().st_size == 0
    if needs_header:
        cols_select = ", ".join(f"'' AS {col}" for col in KEYWORD_COLUMNS)
        query = f"COPY (SELECT * FROM (SELECT {cols_select}) WHERE 1=0) "
        query += f"TO '{csv_path}' (HEADER, DELIMITER ',')"
        duckdb.execute(query)


def read_kept_candidates(candidates_csv: Path) -> list[KeptCandidate]:
    """Read kept candidates from candidates.csv where keep='true'.

    Args:
        candidates_csv: Path to the candidates CSV file.

    Returns:
        List of kept candidate records with source_file, element_id,
        candidate_text, and sentence fields.

    Raises:
        ReadCandidatesError: If DuckDB fails to read or parse the CSV file.
    """
    if not candidates_csv.exists() or candidates_csv.stat().st_size == 0:
        return []

    query = """
        SELECT source_file, element_id, candidate_text, sentence
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE keep = 'true'
    """
    try:
        with duckdb.connect() as conn:
            result = conn.execute(query, [str(candidates_csv)])
            rows = result.fetchall()
    except duckdb.Error as exc:
        msg = f"Failed to read candidates from {candidates_csv}: {exc}"
        print(f"Error: {msg}", file=sys.stderr)
        raise ReadCandidatesError(msg) from exc

    candidates: list[KeptCandidate] = []
    for row in rows:
        candidates.append(
            KeptCandidate(
                source_file=row[0],
                element_id=row[1],
                candidate_text=row[2],
                sentence=row[3],
            )
        )
    return candidates


def group_keywords_by_element(
    candidates: list[KeptCandidate],
) -> dict[tuple[str, str], list[KeptCandidate]]:
    """Group kept candidates by (source_file, element_id).

    Args:
        candidates: List of kept candidate records.

    Returns:
        Dictionary mapping (source_file, element_id) to list of candidates
        for that element.
    """
    grouped: dict[tuple[str, str], list[KeptCandidate]] = defaultdict(list)
    for candidate in candidates:
        key = (candidate["source_file"], candidate["element_id"])
        grouped[key].append(candidate)
    return dict(grouped)


def _find_element_by_id(
    data: Any,  # noqa: ANN401
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


def apply_keywords_to_yaml_file(
    file_path: Path,
    element_keywords: dict[str, list[str]],
    *,
    dry_run: bool = False,
) -> tuple[int, list[str], set[str]]:
    """Apply keywords to elements in a single YAML file.

    Loads the YAML file, finds each element by ID, merges the keywords list,
    and writes the file back.

    Args:
        file_path: Absolute path to the YAML file.
        element_keywords: Mapping of element_id to list of keywords to add.
        dry_run: If True, don't write changes, just report what would change.

    Returns:
        Tuple of (count of elements updated, list of update descriptions,
        set of successfully updated element IDs). The set will be empty if
        the YAML file could not be parsed or written.
    """
    updates: list[str] = []
    updated_count = 0
    updated_element_ids: set[str] = set()

    try:
        data = parse_yaml_file(file_path)
    except (ValueError, TypeError, yaml.YAMLError, FileNotFoundError) as exc:
        msg = f"Warning: Failed to parse {file_path}: {exc}"
        print(msg, file=sys.stderr)
        return 0, [], set()

    modified = False
    for element_id, keywords in element_keywords.items():
        element = _find_element_by_id(data, element_id)
        if element is None:
            updates.append(f"  - Element '{element_id}' not found in {file_path.name}")
            continue

        # Get existing keywords if any
        existing_keywords: list[str] = element.get("keywords", [])
        if not isinstance(existing_keywords, list):
            existing_keywords = []

        # Merge new keywords (deduplicate, preserve order)
        existing_set = set(existing_keywords)
        new_keywords = [kw for kw in keywords if kw not in existing_set]

        if new_keywords:
            merged = existing_keywords + new_keywords
            element["keywords"] = sorted(set(merged))  # Sort for consistency
            modified = True
            updated_count += 1
            updated_element_ids.add(element_id)
            updates.append(f"  + Element '{element_id}': added {len(new_keywords)} keyword(s)")

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
            # Write failed, so no elements were actually updated
            return 0, [], set()

    return updated_count, updates, updated_element_ids


def upsert_keywords_csv(
    keywords_csv: Path,
    records: list[KeywordRecord],
) -> int:
    """Upsert keyword records into keywords.csv.

    For each (keyword, source_file, element_id) combination:
    - If already present, update last_updated timestamp
    - If not present, insert new row

    Args:
        keywords_csv: Path to the keywords CSV file.
        records: List of keyword records to upsert.

    Returns:
        Number of records upserted (new + updated).
    """
    if not records:
        return 0

    ensure_keywords_csv_exists(keywords_csv)

    with duckdb.connect() as conn:
        # Load existing data into a table
        conn.execute(f"""
            CREATE TABLE keywords AS
            SELECT * FROM read_csv_auto('{keywords_csv}', ALL_VARCHAR=TRUE)
        """)

        upserted = 0
        for record in records:
            # Check if record exists
            check_query = """
                SELECT COUNT(*) FROM keywords
                WHERE keyword = ? AND source_file = ? AND element_id = ?
            """
            result = conn.execute(
                check_query,
                [record["keyword"], record["source_file"], record["element_id"]],
            ).fetchone()

            exists = result is not None and result[0] > 0

            if exists:
                # Update last_updated and snippet
                update_query = """
                    UPDATE keywords
                    SET last_updated = ?, snippet = ?
                    WHERE keyword = ? AND source_file = ? AND element_id = ?
                """
                conn.execute(
                    update_query,
                    [
                        record["last_updated"],
                        record["snippet"],
                        record["keyword"],
                        record["source_file"],
                        record["element_id"],
                    ],
                )
            else:
                # Insert new record
                placeholders = ", ".join("?" for _ in KEYWORD_COLUMNS)
                insert_sql = f"INSERT INTO keywords VALUES ({placeholders})"
                values = [
                    record["keyword"],
                    record["source_file"],
                    record["element_id"],
                    record["snippet"],
                    record["first_detected"],
                    record["last_updated"],
                ]
                conn.execute(insert_sql, values)

            upserted += 1

        # Write back to CSV
        conn.execute(f"COPY keywords TO '{keywords_csv}' (HEADER, DELIMITER ',')")
        return upserted


def get_keywords_for_file(
    keywords_csv: Path,
    source_file: str,
) -> list[dict[str, str]]:
    """Get all keywords that originated from a specific source file.

    Args:
        keywords_csv: Path to the keywords CSV file.
        source_file: Source file path to filter by.

    Returns:
        List of keyword records for the source file.
    """
    if not keywords_csv.exists() or keywords_csv.stat().st_size == 0:
        return []

    query = """
        SELECT *
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE source_file = ?
    """
    try:
        with duckdb.connect() as conn:
            result = conn.execute(query, [str(keywords_csv), source_file])
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            return [dict(zip(columns, row, strict=False)) for row in rows]
    except duckdb.Error:
        return []


def get_all_keywords(keywords_csv: Path) -> list[dict[str, str]]:
    """Get all classified keywords.

    Args:
        keywords_csv: Path to the keywords CSV file.

    Returns:
        List of all keyword records.
    """
    if not keywords_csv.exists() or keywords_csv.stat().st_size == 0:
        return []

    query = """
        SELECT *
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        ORDER BY keyword, source_file, element_id
    """
    try:
        with duckdb.connect() as conn:
            result = conn.execute(query, [str(keywords_csv)])
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            return [dict(zip(columns, row, strict=False)) for row in rows]
    except duckdb.Error:
        return []


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for keyword application.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Apply classified keywords to YAML documentation files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Show changes without modifying files.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def apply_keywords_main(args: argparse.Namespace) -> int:
    """Run keyword application to YAML files and update keyword index.

    Workflow:
    1. Read kept candidates from candidates.csv (keep='true')
    2. Group by (source_file, element_id)
    3. For each source file, merge keywords into YAML elements
    4. Upsert keyword occurrences into keywords.csv (only for successfully updated elements)

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error.
    """
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    candidates_csv = knowledge_path / "keywords" / "candidates.csv"
    keywords_csv = knowledge_path / "keywords" / "keywords.csv"

    if not candidates_csv.exists():
        print(f"Error: Candidates CSV not found: {candidates_csv}", file=sys.stderr)
        return 1

    # Step 1: Read kept candidates
    print(f"Reading kept candidates from {candidates_csv}...")
    try:
        kept_candidates = read_kept_candidates(candidates_csv)
    except ReadCandidatesError:
        # Error already logged by read_kept_candidates
        return 1

    if not kept_candidates:
        print("No kept candidates found (keep='true').")
        return 0

    print(f"Found {len(kept_candidates)} kept candidate(s)")

    if args.dry_run:
        print("(dry run - no changes will be made)")

    # Step 2: Group by (source_file, element_id)
    grouped = group_keywords_by_element(kept_candidates)
    print(f"Grouped into {len(grouped)} element(s) across files")

    # Step 3: Group by source_file for YAML processing
    files_to_update: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for (source_file, element_id), candidates in grouped.items():
        for candidate in candidates:
            keyword = candidate["candidate_text"]
            files_to_update[source_file][element_id].append(keyword)

    # Step 4: Apply keywords to each YAML file
    timestamp = utc_timestamp()
    total_elements_updated = 0
    keyword_records: list[KeywordRecord] = []

    print("\nApplying keywords to YAML files:")
    for source_file, element_keywords in files_to_update.items():
        file_path = REPO_ROOT / source_file
        if not file_path.exists():
            print(f"  Warning: File not found: {source_file}", file=sys.stderr)
            continue

        print(f"\n  {source_file}:")
        updated_count, updates, updated_element_ids = apply_keywords_to_yaml_file(
            file_path,
            element_keywords,
            dry_run=args.dry_run,
        )
        total_elements_updated += updated_count

        for update in updates:
            print(update)

        # Build keyword records ONLY for successfully updated elements
        # Skip entirely if the file had parse/write errors (updated_element_ids is empty)
        for element_id, keywords in element_keywords.items():
            # Only index keywords for elements that were actually updated
            if element_id not in updated_element_ids:
                continue

            # Get sentence snippet from candidates
            element_candidates = grouped.get((source_file, element_id), [])
            for keyword in keywords:
                # Find matching candidate to get sentence
                snippet = ""
                for candidate in element_candidates:
                    if candidate["candidate_text"] == keyword:
                        snippet = candidate["sentence"]
                        break

                keyword_records.append(
                    KeywordRecord(
                        keyword=keyword,
                        source_file=source_file,
                        element_id=element_id,
                        snippet=snippet,
                        first_detected=timestamp,
                        last_updated=timestamp,
                    )
                )

    # Step 5: Update keywords.csv index
    if not args.dry_run and keyword_records:
        print(f"\nUpdating keyword index: {keywords_csv}")
        upserted = upsert_keywords_csv(keywords_csv, keyword_records)
        print(f"Upserted {upserted} keyword record(s)")

    print("\nSummary:")
    print(f"  Elements updated: {total_elements_updated}")
    print(f"  Keywords indexed: {len(keyword_records)}")

    return 0


def main_apply() -> int:
    """Entry point for apply-keywords-to-yaml command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_args()
    return apply_keywords_main(args)


if __name__ == "__main__":
    raise SystemExit(main_apply())
