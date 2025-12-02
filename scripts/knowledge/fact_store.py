"""Fact store for organizing, querying, and decorating facts from extraction.

This module provides utilities for:
1. Storing extracted facts from extractions.csv into domain/pattern YAML files
2. Querying facts by domain, pattern, entity, or fact_id
3. Decorating YAML documentation with fact_ids and entity_id fields

Usage:
    # Store facts for an entity to domain/pattern YAML
    uv run knowledge.store-fact --entity "create_app" --domain "fastapi" --pattern "factory"

    # Query facts with filters
    uv run knowledge.query-facts --domain "fastapi" --pattern "factory"
    uv run knowledge.query-facts --entity "create_app"
    uv run knowledge.query-facts --fact-id <uuid>

    # Decorate YAML with fact IDs and entity ID
    uv run knowledge.decorate-yaml-with-fact-ids \
        --yaml-file docs/development/project/fastapi/project.fastapi.factory-patterns.yml \
        --element-id "factory.create_app" \
        --fact-ids <uuid1> <uuid2> \
        --entity "create_app"

Args:
    --entity: Entity name to filter/lookup.
    --domain: Domain tag for fact organization.
    --pattern: Pattern name for fact organization.
    --fact-id: Specific fact UUID to query.
    --yaml-file: YAML file to decorate.
    --element-id: Element ID within YAML to decorate.
    --fact-ids: List of fact UUIDs to add to element.
    --knowledge-path: Base knowledge directory (default: .knowledge).
    --dry-run: Show changes without modifying files.

Note:
    Running this module directly (python -m scripts.knowledge.fact_store) invokes
    the store-fact workflow. Use the [project.scripts] entrypoints for other commands:
    - uv run knowledge.store-fact
    - uv run knowledge.query-facts
    - uv run knowledge.decorate-yaml-with-fact-ids
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypedDict

import duckdb
import yaml

from scripts.dev.utils import REPO_ROOT, utc_timestamp
from scripts.knowledge.compare_yaml_docs import parse_yaml_file


class FactStoreRecord(TypedDict):
    """A fact record for the domain/pattern YAML files.

    Attributes:
        fact_id: UUID for this fact.
        entity: Entity/keyword the fact is about.
        fact_text: Extracted atomic fact about the entity.
        source_file: YAML path where fact was extracted from (relative to repo root).
        source_element_id: YAML element ID where fact was found.
        confidence: Confidence score as a float (0.0-1.0). Converted from string
            values read from CSV; invalid or empty values default to 0.0.
        extracted_at: ISO 8601 timestamp when extracted.
        domain: Domain tag for organization.
        pattern: Pattern name for organization.
    """

    fact_id: str
    entity: str
    fact_text: str
    source_file: str
    source_element_id: str
    confidence: float
    extracted_at: str
    domain: str
    pattern: str


# --- Storage Functions ---


def ensure_fact_yaml_exists(yaml_path: Path) -> None:
    """Create fact YAML file with schema if it doesn't exist.

    Args:
        yaml_path: Path to the fact YAML file.
    """
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    if not yaml_path.exists():
        initial_content = {"facts": []}
        content = yaml.dump(
            initial_content,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
        yaml_path.write_text(content, encoding="utf-8")


def store_fact_to_yaml(yaml_path: Path, fact_record: FactStoreRecord) -> int:
    """Append a fact record to the domain/pattern YAML file.

    Args:
        yaml_path: Path to the fact YAML file.
        fact_record: Fact record to append.

    Returns:
        1 on success, 0 on failure.
    """
    ensure_fact_yaml_exists(yaml_path)

    try:
        data = parse_yaml_file(yaml_path)
    except (ValueError, TypeError, yaml.YAMLError, FileNotFoundError) as exc:
        print(f"Warning: Failed to parse {yaml_path}: {exc}", file=sys.stderr)
        return 0

    if "facts" not in data or not isinstance(data["facts"], list):
        data["facts"] = []

    # Check for duplicate fact_id
    existing_ids = {fact.get("fact_id") for fact in data["facts"]}
    if fact_record["fact_id"] in existing_ids:
        return 1  # Already exists, success

    # Append the new fact
    data["facts"].append(dict(fact_record))

    try:
        content = yaml.dump(
            data,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )
        yaml_path.write_text(content, encoding="utf-8")
    except (OSError, yaml.YAMLError) as exc:
        print(f"Warning: Failed to write {yaml_path}: {exc}", file=sys.stderr)
        return 0

    return 1


def read_facts_from_csv(csv_path: Path, entity: str | None = None) -> list[dict[str, str]]:
    """Read extracted facts from extractions.csv.

    Args:
        csv_path: Path to the extractions CSV file.
        entity: Optional entity to filter by.

    Returns:
        List of fact dictionaries.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return []

    if entity:
        query = """
            SELECT fact_id, source_sentence, entity, fact_text, rewritten_sentence,
                   iteration, confidence, extracted_at
            FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
            WHERE entity = ?
            ORDER BY extracted_at, iteration
        """
        params = [str(csv_path), entity]
    else:
        query = """
            SELECT fact_id, source_sentence, entity, fact_text, rewritten_sentence,
                   iteration, confidence, extracted_at
            FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
            ORDER BY extracted_at, iteration
        """
        params = [str(csv_path)]

    try:
        result = duckdb.execute(query, params).fetchall()
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


def _parse_confidence(value: str) -> float:
    """Parse confidence value from string to float.

    Args:
        value: String confidence value from CSV (may be empty or invalid).

    Returns:
        Float confidence score, defaulting to 0.0 for empty or invalid values.
    """
    if not value or not value.strip():
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def organize_facts_by_domain_pattern(
    facts: list[dict[str, str]],
    domain: str,
    pattern: str,
    source_file: str = "",
    source_element_id: str = "",
) -> list[FactStoreRecord]:
    """Convert extracted facts to store records with domain/pattern metadata.

    Args:
        facts: List of fact dictionaries from extractions.csv.
        domain: Domain tag for organization.
        pattern: Pattern name for organization.
        source_file: Source YAML file path (optional).
        source_element_id: Source element ID (optional).

    Returns:
        List of FactStoreRecord objects.
    """
    records: list[FactStoreRecord] = []
    for fact in facts:
        record = FactStoreRecord(
            fact_id=fact["fact_id"],
            entity=fact["entity"],
            fact_text=fact["fact_text"],
            source_file=source_file,
            source_element_id=source_element_id,
            confidence=_parse_confidence(fact.get("confidence", "")),
            extracted_at=fact["extracted_at"],
            domain=domain,
            pattern=pattern,
        )
        records.append(record)
    return records


# --- Query Functions ---


def list_fact_files(facts_dir: Path) -> list[Path]:
    """List all domain.pattern.facts.yml files in the facts directory.

    Args:
        facts_dir: Path to the facts directory.

    Returns:
        List of fact file paths.
    """
    if not facts_dir.exists():
        return []
    return sorted(facts_dir.glob("*.facts.yml"))


def query_facts_from_yaml(
    facts_dir: Path,
    domain: str | None = None,
    pattern: str | None = None,
    entity: str | None = None,
) -> list[dict[str, Any]]:
    """Query facts from YAML files with optional filters.

    Args:
        facts_dir: Path to the facts directory.
        domain: Optional domain to filter by.
        pattern: Optional pattern to filter by.
        entity: Optional entity to filter by.

    Returns:
        List of matching fact dictionaries.
    """
    results: list[dict[str, Any]] = []

    fact_files = list_fact_files(facts_dir)
    for fact_file in fact_files:
        # Parse filename: domain.pattern.facts.yml
        filename = fact_file.stem  # e.g., "fastapi.factory.facts"
        parts = filename.rsplit(".facts", 1)[0].split(".", 1)
        if len(parts) != 2:
            continue
        file_domain, file_pattern = parts

        # Filter by domain/pattern from filename
        if domain and file_domain != domain:
            continue
        if pattern and file_pattern != pattern:
            continue

        try:
            data = parse_yaml_file(fact_file)
        except (ValueError, TypeError, yaml.YAMLError, FileNotFoundError):
            continue

        facts = data.get("facts", [])
        if not isinstance(facts, list):
            continue

        for fact in facts:
            # Filter by entity within file
            if entity and fact.get("entity") != entity:
                continue
            results.append(fact)

    return results


def get_fact_by_id(facts_dir: Path, fact_id: str) -> dict[str, Any] | None:
    """Retrieve a specific fact by UUID.

    Args:
        facts_dir: Path to the facts directory.
        fact_id: Fact UUID to find.

    Returns:
        Fact dictionary if found, None otherwise.
    """
    fact_files = list_fact_files(facts_dir)
    for fact_file in fact_files:
        try:
            data = parse_yaml_file(fact_file)
        except (ValueError, TypeError, yaml.YAMLError, FileNotFoundError):
            continue

        facts = data.get("facts", [])
        if not isinstance(facts, list):
            continue

        for fact in facts:
            if fact.get("fact_id") == fact_id:
                return fact

    return None


# --- Decoration Functions ---


def get_entity_id_from_variants(variants_csv: Path, entity: str) -> str | None:
    """Look up entity_id from variant_candidates.csv using canonical keyword.

    The entity_id is the pair_id from variant resolution where the entity
    appears as either keyword_a or keyword_b with merge='true' and
    validated='true'.

    Args:
        variants_csv: Path to variant_candidates.csv.
        entity: Entity name to look up.

    Returns:
        Entity ID (pair_id) if found, None otherwise.
    """
    if not variants_csv.exists() or variants_csv.stat().st_size == 0:
        return None

    query = """
        SELECT pair_id
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE (keyword_a = ? OR keyword_b = ?)
          AND merge = 'true'
          AND validated = 'true'
        LIMIT 1
    """
    try:
        result = duckdb.execute(query, [str(variants_csv), entity, entity]).fetchone()
        if result:
            return result[0]
    except duckdb.Error:
        pass
    return None


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


def decorate_yaml_with_fact_ids(
    yaml_path: Path,
    element_id: str,
    fact_ids: list[str],
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Add fact_ids list to a YAML element.

    Args:
        yaml_path: Path to the YAML file.
        element_id: Element ID to decorate.
        fact_ids: List of fact UUIDs to add.
        dry_run: If True, don't write changes.

    Returns:
        Tuple of (number of new IDs added, list of update descriptions).
        Returns 0 when no new IDs were added (all already exist or element not found).
    """
    updates: list[str] = []

    try:
        data = parse_yaml_file(yaml_path)
    except (ValueError, TypeError, yaml.YAMLError, FileNotFoundError) as exc:
        msg = f"Warning: Failed to parse {yaml_path}: {exc}"
        print(msg, file=sys.stderr)
        return 0, []

    element = _find_element_by_id(data, element_id)
    if element is None:
        updates.append(f"  - Element '{element_id}' not found in {yaml_path.name}")
        return 0, updates

    # Get existing fact_ids if any
    existing_fact_ids: list[str] = element.get("fact_ids", [])
    if not isinstance(existing_fact_ids, list):
        existing_fact_ids = []

    # Merge new fact_ids (deduplicate, preserve order)
    existing_set = set(existing_fact_ids)
    new_fact_ids = [fid for fid in fact_ids if fid not in existing_set]

    if not new_fact_ids:
        updates.append(f"  = Element '{element_id}': no new fact IDs to add (all already exist)")
        return 0, updates

    merged = existing_fact_ids + new_fact_ids
    element["fact_ids"] = merged
    updates.append(f"  + Element '{element_id}': added {len(new_fact_ids)} fact ID(s)")

    if not dry_run:
        try:
            content = yaml.dump(
                data,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
                width=120,
            )
            yaml_path.write_text(content, encoding="utf-8")
        except (OSError, yaml.YAMLError) as exc:
            msg = f"Warning: Failed to write {yaml_path}: {exc}"
            print(msg, file=sys.stderr)
            return 0, []

    return len(new_fact_ids), updates


def decorate_yaml_with_entity_id(
    yaml_path: Path,
    element_id: str,
    entity: str,
    entity_id: str,
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Add entity_id to a YAML element.

    Args:
        yaml_path: Path to the YAML file.
        element_id: Element ID to decorate.
        entity: Entity name for logging.
        entity_id: Entity UUID from variant resolution.
        dry_run: If True, don't write changes.

    Returns:
        Tuple of (1 on success, 0 on failure) and list of update descriptions.
    """
    updates: list[str] = []

    try:
        data = parse_yaml_file(yaml_path)
    except (ValueError, TypeError, yaml.YAMLError, FileNotFoundError) as exc:
        msg = f"Warning: Failed to parse {yaml_path}: {exc}"
        print(msg, file=sys.stderr)
        return 0, []

    element = _find_element_by_id(data, element_id)
    if element is None:
        updates.append(f"  - Element '{element_id}' not found in {yaml_path.name}")
        return 0, updates

    existing_entity_id = element.get("entity_id")
    if existing_entity_id == entity_id:
        return 1, updates  # Already set

    element["entity_id"] = entity_id
    updates.append(f"  + Element '{element_id}': set entity_id for '{entity}'")

    if not dry_run:
        try:
            content = yaml.dump(
                data,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
                width=120,
            )
            yaml_path.write_text(content, encoding="utf-8")
        except (OSError, yaml.YAMLError) as exc:
            msg = f"Warning: Failed to write {yaml_path}: {exc}"
            print(msg, file=sys.stderr)
            return 0, []

    return 1, updates


# --- CLI Entry Points ---


def parse_store_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for store-fact command.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Store extracted facts to domain/pattern YAML files.",
    )
    parser.add_argument(
        "--entity",
        required=True,
        help="Entity to filter facts for.",
    )
    parser.add_argument(
        "--domain",
        required=True,
        help="Domain tag for fact organization.",
    )
    parser.add_argument(
        "--pattern",
        required=True,
        help="Pattern name for fact organization.",
    )
    parser.add_argument(
        "--source-file",
        default="",
        dest="source_file",
        help="Source YAML file path (optional).",
    )
    parser.add_argument(
        "--source-element-id",
        default="",
        dest="source_element_id",
        help="Source element ID (optional).",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def store_fact_main(args: argparse.Namespace) -> int:
    """Run store-fact command.

    Reads facts from extractions.csv, filters by entity, and stores
    to domain/pattern YAML file.

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error.
    """
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    extractions_csv = knowledge_path / "facts" / "extractions.csv"
    facts_dir = knowledge_path / "facts"

    if not extractions_csv.exists():
        print(f"Error: Extractions CSV not found: {extractions_csv}", file=sys.stderr)
        return 1

    # Read facts for entity
    print(f"Reading facts for entity '{args.entity}' from {extractions_csv}...")
    facts = read_facts_from_csv(extractions_csv, entity=args.entity)

    if not facts:
        print(f"No facts found for entity '{args.entity}'.")
        return 0

    print(f"Found {len(facts)} fact(s)")

    # Organize facts with domain/pattern metadata
    records = organize_facts_by_domain_pattern(
        facts,
        domain=args.domain,
        pattern=args.pattern,
        source_file=args.source_file,
        source_element_id=args.source_element_id,
    )

    # Store to YAML
    yaml_filename = f"{args.domain}.{args.pattern}.facts.yml"
    yaml_path = facts_dir / yaml_filename

    print(f"Storing {len(records)} fact(s) to {yaml_path}...")
    stored_count = 0
    for record in records:
        stored_count += store_fact_to_yaml(yaml_path, record)

    print(f"Stored {stored_count} fact(s) to {yaml_filename}")
    return 0


def parse_query_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for query-facts command.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Query facts with optional filters.",
    )
    parser.add_argument(
        "--domain",
        help="Filter by domain.",
    )
    parser.add_argument(
        "--pattern",
        help="Filter by pattern.",
    )
    parser.add_argument(
        "--entity",
        help="Filter by entity.",
    )
    parser.add_argument(
        "--fact-id",
        dest="fact_id",
        help="Query specific fact by UUID.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def query_facts_main(args: argparse.Namespace) -> int:
    """Run query-facts command.

    Queries facts from YAML files with optional filters.

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error.
    """
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    facts_dir = knowledge_path / "facts"

    # Query by fact_id takes precedence
    if args.fact_id:
        fact = get_fact_by_id(facts_dir, args.fact_id)
        if fact:
            print(f"Fact ID: {fact.get('fact_id')}")
            print(f"  Entity: {fact.get('entity')}")
            print(f"  Fact: {fact.get('fact_text')}")
            print(f"  Domain: {fact.get('domain')}")
            print(f"  Pattern: {fact.get('pattern')}")
            print(f"  Confidence: {fact.get('confidence')}")
            print(f"  Source: {fact.get('source_file')}")
            print(f"  Element: {fact.get('source_element_id')}")
            print(f"  Extracted: {fact.get('extracted_at')}")
        else:
            print(f"Fact not found: {args.fact_id}")
        return 0

    # Query with filters
    facts = query_facts_from_yaml(
        facts_dir,
        domain=args.domain,
        pattern=args.pattern,
        entity=args.entity,
    )

    if not facts:
        print("No facts found matching filters.")
        return 0

    print(f"Found {len(facts)} fact(s):\n")
    for i, fact in enumerate(facts, 1):
        print(f"{i}. [{fact.get('entity')}] {fact.get('fact_text')}")
        print(f"   Domain: {fact.get('domain')}, Pattern: {fact.get('pattern')}")
        print(f"   Confidence: {fact.get('confidence')}")
        print()

    return 0


def parse_decorate_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for decorate command.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Decorate YAML elements with fact IDs and entity ID.",
    )
    parser.add_argument(
        "--yaml-file",
        type=Path,
        required=True,
        dest="yaml_file",
        help="YAML file to decorate.",
    )
    parser.add_argument(
        "--element-id",
        required=True,
        dest="element_id",
        help="Element ID within YAML to decorate.",
    )
    parser.add_argument(
        "--fact-ids",
        nargs="*",
        default=[],
        dest="fact_ids",
        help="List of fact UUIDs to add.",
    )
    parser.add_argument(
        "--entity",
        help="Entity name for entity_id lookup from variant resolution.",
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
        help="Show changes without modifying files.",
    )
    return parser.parse_args(argv)


def decorate_yaml_main(args: argparse.Namespace) -> int:
    """Run decorate-yaml-with-fact-ids command.

    Decorates YAML elements with fact_ids and/or entity_id.

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error.
    """
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    # Resolve YAML file path
    if args.yaml_file.is_absolute():
        yaml_path = args.yaml_file.resolve()
    else:
        yaml_path = (REPO_ROOT / args.yaml_file).resolve()

    if not yaml_path.exists():
        print(f"Error: YAML file not found: {yaml_path}", file=sys.stderr)
        return 1

    if not args.fact_ids and not args.entity:
        print("Error: At least one of --fact-ids or --entity must be provided.", file=sys.stderr)
        return 1

    if args.dry_run:
        print("(dry run - no changes will be made)")

    all_updates: list[str] = []
    fact_ids_added = 0
    entity_id_added = False
    has_failure = False

    # Decorate with fact_ids
    if args.fact_ids:
        print(f"Decorating '{args.element_id}' with {len(args.fact_ids)} fact ID(s)...")
        added_count, updates = decorate_yaml_with_fact_ids(
            yaml_path,
            args.element_id,
            args.fact_ids,
            dry_run=args.dry_run,
        )
        all_updates.extend(updates)
        fact_ids_added = added_count
        # Check if element was not found (failure case)
        if any("not found" in u for u in updates):
            has_failure = True

    # Decorate with entity_id from variant resolution
    if args.entity:
        variants_csv = knowledge_path / "keywords" / "variant_candidates.csv"
        entity_id = get_entity_id_from_variants(variants_csv, args.entity)

        if entity_id:
            print(f"Found entity_id '{entity_id}' for entity '{args.entity}'")
            result, updates = decorate_yaml_with_entity_id(
                yaml_path,
                args.element_id,
                args.entity,
                entity_id,
                dry_run=args.dry_run,
            )
            all_updates.extend(updates)
            if result == 0:
                # Check if element was not found (failure case)
                if any("not found" in u for u in updates):
                    has_failure = True
            else:
                entity_id_added = True
        else:
            print(f"No entity_id found for entity '{args.entity}' in variant resolution.")

    # Print all updates
    if all_updates:
        print("\nUpdates:")
        for update in all_updates:
            print(update)

    if has_failure:
        print("\nSome decorations failed. Check warnings above.", file=sys.stderr)
        return 1

    entity_msg = " and entity ID" if entity_id_added else ""
    print(f"\nDecorated element '{args.element_id}' with {fact_ids_added} new fact ID(s){entity_msg}")

    return 0


def main_store() -> int:
    """Entry point for knowledge.store-fact command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_store_args()
    return store_fact_main(args)


def main_query() -> int:
    """Entry point for knowledge.query-facts command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_query_args()
    return query_facts_main(args)


def main_decorate() -> int:
    """Entry point for knowledge.decorate-yaml-with-fact-ids command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_decorate_args()
    return decorate_yaml_main(args)


if __name__ == "__main__":
    raise SystemExit(main_store())
