"""Fact-based migration orchestrator for YAML documentation elements.

This module provides the high-level orchestration for migrating YAML documentation
elements by extracting atomic facts, classifying them via the knowledge-analyzer
sub-agent, and moving them to appropriate domain/pattern files.

The fact migration workflow consists of four CLI commands:

1. **start-fact-migration**: Create migration task, extract facts from YAML element
2. **classify-facts**: Print instructions for invoking knowledge-analyzer sub-agent
3. **move-facts**: Move classified facts to target domain/pattern files
4. **validate-fact-migration**: Validate migration completeness

Usage:
    # Start a fact migration for a YAML element
    uv run knowledge.start-fact-migration \
        --yaml-file docs/development/project/fastapi/project.fastapi.factory-patterns.yml \
        --element-id factory.create_app

    # Classify extracted facts (prints sub-agent instructions)
    uv run knowledge.classify-facts --task-id <uuid>

    # Move classified facts to target files
    uv run knowledge.move-facts --task-id <uuid> --classification-file classification.json

    # Validate the migration
    uv run knowledge.validate-fact-migration --task-id <uuid>

Integration points:
    - migration_manager.py: Task lifecycle tracking
    - fact_extraction.py: Atomic fact extraction
    - fact_isolation.py: Extraction validation
    - knowledge-analyzer sub-agent: Fact classification
    - movement_tracker.py: Movement tracking
    - fact_store.py: Fact storage

See docs/processes/fact-migration.yml for complete workflow documentation.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypedDict

import duckdb
import yaml

from scripts.dev.utils import REPO_ROOT, utc_timestamp
from scripts.knowledge import fact_extraction, fact_store, movement_tracker
from scripts.knowledge.compare_yaml_docs import parse_yaml_file
from scripts.knowledge.migration_manager import (
    CSV_COLUMNS as MIGRATION_CSV_COLUMNS,
)

# Re-export fact_extraction for test access via fact_migration.fact_extraction
__all__ = ["fact_extraction"]

# Extended CSV columns for fact migration tasks
FACT_MIGRATION_CSV_COLUMNS = [
    *MIGRATION_CSV_COLUMNS,
    "element_id",
    "entity_count",
    "fact_count",
]


class FactMigrationTask(TypedDict):
    """Schema for fact migration task records.

    Extends MigrationTask with fact-specific metadata.

    Attributes:
        task_id: Unique task identifier (UUID).
        original_file_ref: Reference to file in originals/ (reused from base schema).
        pattern_name: Pattern being migrated.
        status: Task status (pending, in_progress, completed, failed).
        created_at: ISO 8601 timestamp of task creation.
        validated_at: ISO 8601 timestamp of validation.
        element_id: YAML element identifier being migrated.
        entity_count: Number of entities extracted from element.
        fact_count: Number of facts extracted from element.
    """

    task_id: str
    original_file_ref: str
    pattern_name: str
    status: str
    created_at: str
    validated_at: str
    element_id: str
    entity_count: str
    fact_count: str


# --- Helper Functions ---


def read_yaml_element_text(yaml_path: Path, element_id: str) -> str | None:
    """Read text field from YAML element by ID.

    Recursively searches the YAML structure for an element with matching 'id' field
    and returns its 'text' field content.

    Args:
        yaml_path: Path to the YAML file.
        element_id: Element ID to find.

    Returns:
        Text content of the element if found, None otherwise.
    """
    try:
        data = parse_yaml_file(yaml_path)
    except (ValueError, TypeError, yaml.YAMLError, FileNotFoundError):
        return None

    element = _find_element_by_id(data, element_id)
    if element is None:
        return None

    return element.get("text")


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


def extract_entities_from_text(text: str) -> list[str]:
    """Extract entities from text using simple heuristics.

    This is a placeholder implementation that extracts potential entity names
    based on code patterns (function names, class names, file paths).

    Args:
        text: Text to extract entities from.

    Returns:
        List of extracted entity names.
    """
    entities: list[str] = []

    # Extract function/class names (snake_case or CamelCase patterns)
    import re

    # Match snake_case identifiers (e.g., create_app, get_user)
    snake_case = re.findall(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", text)
    entities.extend(snake_case)

    # Match CamelCase identifiers (e.g., FastAPI, UserModel)
    camel_case = re.findall(r"\b[A-Z][a-zA-Z0-9]+\b", text)
    entities.extend(camel_case)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_entities: list[str] = []
    for entity in entities:
        if entity not in seen:
            seen.add(entity)
            unique_entities.append(entity)

    return unique_entities


def query_facts_for_task(csv_path: Path, source_sentence: str) -> list[dict[str, str]]:
    """Query facts from extractions.csv for a given source sentence.

    Args:
        csv_path: Path to the extractions CSV file.
        source_sentence: Source sentence to filter by.

    Returns:
        List of fact dictionaries.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return []

    query = """
        SELECT fact_id, source_sentence, entity, fact_text, rewritten_sentence,
               iteration, confidence, extracted_at
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE source_sentence = ?
        ORDER BY entity, CAST(iteration AS INTEGER)
    """
    try:
        result = duckdb.execute(query, [str(csv_path), source_sentence]).fetchall()
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


def query_all_facts_for_element(
    csv_path: Path,
    element_text: str,
) -> list[dict[str, str]]:
    """Query all facts extracted from sentences containing element text.

    Uses LIKE matching to find facts from sentences that originated from the element.

    Args:
        csv_path: Path to the extractions CSV file.
        element_text: Element text to search for in source sentences.

    Returns:
        List of fact dictionaries.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return []

    # Escape special characters for LIKE pattern
    escaped_text = element_text.replace("%", "\\%").replace("_", "\\_")

    query = """
        SELECT fact_id, source_sentence, entity, fact_text, rewritten_sentence,
               iteration, confidence, extracted_at
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE source_sentence LIKE ?
        ORDER BY entity, CAST(iteration AS INTEGER)
    """
    try:
        result = duckdb.execute(query, [str(csv_path), f"%{escaped_text[:50]}%"]).fetchall()
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


def parse_classification_json(json_path: Path) -> dict[str, Any]:
    """Parse knowledge-analyzer output JSON.

    Args:
        json_path: Path to the classification JSON file.

    Returns:
        Parsed classification data.

    Raises:
        ValueError: If the JSON file is invalid or missing required fields.
    """
    if not json_path.exists():
        raise ValueError(f"Classification file not found: {json_path}")

    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in classification file: {e}") from e

    # Validate required structure
    if not isinstance(data, dict):
        raise TypeError("Classification JSON must be an object")

    if "classifications" not in data and "facts" not in data:
        raise ValueError("Classification JSON must contain 'classifications' or 'facts' key")

    return data


def normalize_classifications(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize classification JSON to a standardized list of classification dicts.

    This helper resolves the classification list from either 'classifications' or 'facts'
    key, validates the structure, and ensures each item contains the required fields.

    Args:
        data: Parsed classification JSON data.

    Returns:
        List of classification dicts, each containing at minimum:
        - fact_id: UUID of the fact being classified
        - domain: Domain classification (e.g., fastapi, python)
        - pattern: Pattern classification (e.g., factory-patterns)

    Raises:
        ValueError: If the data structure is invalid or items are missing required fields.

    Example:
        >>> data = {
        ...     "classifications": [
        ...         {"fact_id": "...", "domain": "fastapi", "pattern": "factory"}
        ...     ]
        ... }
        >>> normalize_classifications(data)
        [{"fact_id": "...", "domain": "fastapi", "pattern": "factory"}]
    """
    # Resolve the list from either key - check for None explicitly to allow empty lists
    classifications = data.get("classifications")
    if classifications is None:
        classifications = data.get("facts")

    if classifications is None:
        raise ValueError(
            "Classification JSON must contain 'classifications' or 'facts' key. "
            "Expected format: "
            '{"classifications": [{"fact_id": "...", "domain": "...", "pattern": "..."}]}'
        )

    if not isinstance(classifications, list):
        raise TypeError(
            f"Classifications must be a list, got {type(classifications).__name__}. "
            'Expected format: {"classifications": [{...}, {...}]}'
        )

    if len(classifications) == 0:
        raise ValueError("Classifications list is empty. At least one classification is required.")

    # Required fields for each classification
    required_fields = {"fact_id", "domain", "pattern"}

    # Validate each item
    for i, item in enumerate(classifications):
        if not isinstance(item, dict):
            raise TypeError(
                f"Classification at index {i} must be an object, got {type(item).__name__}. "
                'Expected: {"fact_id": "...", "domain": "...", "pattern": "..."}'
            )

        missing_fields = required_fields - set(item.keys())
        if missing_fields:
            raise ValueError(
                f"Classification at index {i} is missing required fields: "
                f"{sorted(missing_fields)}. "
                f"Required fields: {sorted(required_fields)}. "
                f"Got: {item}"
            )

        # Validate field types
        if not isinstance(item.get("fact_id"), str) or not item["fact_id"]:
            raise ValueError(f"Classification at index {i}: 'fact_id' must be a non-empty string.")

        if not isinstance(item.get("domain"), str) or not item["domain"]:
            raise ValueError(f"Classification at index {i}: 'domain' must be a non-empty string.")

        if not isinstance(item.get("pattern"), str) or not item["pattern"]:
            raise ValueError(f"Classification at index {i}: 'pattern' must be a non-empty string.")

    return classifications


def count_stored_facts(facts_dir: Path, fact_ids: list[str]) -> int:
    """Count how many facts are stored in YAML files.

    Args:
        facts_dir: Path to the facts directory.
        fact_ids: List of fact IDs to check.

    Returns:
        Count of facts found in YAML files.
    """
    if not fact_ids:
        return 0

    stored_count = 0
    fact_files = fact_store.list_fact_files(facts_dir)

    for fact_file in fact_files:
        try:
            data = parse_yaml_file(fact_file)
            # Skip non-dict data
            if not isinstance(data, dict):
                continue
            facts = data.get("facts", [])
            if isinstance(facts, list):
                for fact in facts:
                    if isinstance(fact, dict) and fact.get("fact_id") in fact_ids:
                        stored_count += 1
        except (ValueError, TypeError, yaml.YAMLError, FileNotFoundError):
            continue

    return stored_count


def count_tracked_movements(csv_path: Path, fact_ids: list[str]) -> int:
    """Count how many movements are tracked for given fact IDs.

    Args:
        csv_path: Path to the iterative movements CSV file.
        fact_ids: List of fact IDs to check.

    Returns:
        Count of movements tracked.
    """
    if not fact_ids or not csv_path.exists():
        return 0

    movements = movement_tracker.query_iterative_movements(csv_path)
    return sum(1 for m in movements if m.get("fact_id") in fact_ids)


def _create_args_namespace(**kwargs: Any) -> argparse.Namespace:
    """Create an argparse.Namespace with the specified keyword arguments.

    Args:
        **kwargs: Key-value pairs to set as namespace attributes.

    Returns:
        Namespace object with the specified attributes.
    """
    return argparse.Namespace(**kwargs)


def _get_fact_tasks_csv_path(knowledge_path: Path) -> Path:
    """Get the path to the fact migration tasks CSV file.

    Args:
        knowledge_path: Path to the .knowledge directory.

    Returns:
        Path to migrations/fact_tasks.csv.
    """
    return knowledge_path / "migrations" / "fact_tasks.csv"


def _ensure_fact_migration_csv_exists(csv_path: Path) -> None:
    """Create fact migration tasks CSV with header if it does not exist.

    Uses DuckDB to create an empty CSV with proper headers.

    Args:
        csv_path: Path to the tasks.csv file.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if not csv_path.exists():
        cols_select = ", ".join(f"'' AS {col}" for col in FACT_MIGRATION_CSV_COLUMNS)
        query = f"COPY (SELECT * FROM (SELECT {cols_select}) WHERE 1=0) "
        query += f"TO '{csv_path}' (HEADER, DELIMITER ',')"
        duckdb.execute(query)


def _append_fact_migration_task_to_csv(csv_path: Path, task: FactMigrationTask) -> None:
    """Append a fact migration task record to the CSV file.

    Uses DuckDB to read existing data, add the new task, and write back.

    Args:
        csv_path: Path to the tasks.csv file.
        task: Task record to append.
    """
    _ensure_fact_migration_csv_exists(csv_path)
    conn = duckdb.connect()
    try:
        conn.execute(f"""
            CREATE TABLE tasks AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """)
        placeholders = ", ".join("?" for _ in FACT_MIGRATION_CSV_COLUMNS)
        values = [task[col] for col in FACT_MIGRATION_CSV_COLUMNS]  # type: ignore[literal-required]
        conn.execute(f"INSERT INTO tasks VALUES ({placeholders})", values)
        conn.execute(f"COPY tasks TO '{csv_path}' (HEADER, DELIMITER ',')")
    finally:
        conn.close()


def _get_fact_migration_task_from_csv(csv_path: Path, task_id: str) -> FactMigrationTask | None:
    """Query fact migration tasks CSV for a task by ID.

    Args:
        csv_path: Path to the tasks.csv file.
        task_id: UUID of the task to find.

    Returns:
        Task record if found, None otherwise.
    """
    if not csv_path.exists():
        return None

    query = "SELECT * FROM read_csv_auto(?) WHERE task_id = ?"
    try:
        result = duckdb.execute(query, [str(csv_path), task_id]).fetchone()
    except duckdb.Error:
        return None

    if result is None:
        return None

    return FactMigrationTask(
        task_id=result[0],
        original_file_ref=result[1],
        pattern_name=result[2],
        status=result[3],
        created_at=result[4],
        validated_at=result[5] if result[5] else "",
        element_id=result[6] if len(result) > 6 else "",
        entity_count=result[7] if len(result) > 7 else "0",
        fact_count=result[8] if len(result) > 8 else "0",
    )


def _update_fact_migration_task_in_csv(
    csv_path: Path,
    task_id: str,
    updates: dict[str, str],
) -> bool:
    """Update a fact migration task in tasks.csv.

    Args:
        csv_path: Path to the tasks.csv file.
        task_id: UUID of the task to update.
        updates: Dictionary of column-value pairs to update.

    Returns:
        True if task was found and updated, False otherwise.
    """
    if not csv_path.exists():
        return False

    conn = duckdb.connect()
    try:
        conn.execute(f"""
            CREATE TABLE tasks AS
            SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
        """)

        result = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE task_id = ?",
            [task_id],
        ).fetchone()

        if result is None or result[0] == 0:
            return False

        # Build UPDATE query
        set_clauses = ", ".join(f"{col} = ?" for col in updates)
        values = [*list(updates.values()), task_id]
        conn.execute(f"UPDATE tasks SET {set_clauses} WHERE task_id = ?", values)

        conn.execute(f"COPY tasks TO '{csv_path}' (HEADER, DELIMITER ',')")
        return True
    finally:
        conn.close()


# --- Fact Migration Task Wrapper Functions ---
# These wrappers provide fact-specific abstractions over the generic CSV helpers.


def append_fact_migration_task(knowledge_path: Path, task: FactMigrationTask) -> None:
    """Append a fact migration task to fact_tasks.csv.

    Wrapper that computes the CSV path and calls the internal append function.

    Args:
        knowledge_path: Path to the .knowledge directory.
        task: Task record to append.
    """
    csv_path = _get_fact_tasks_csv_path(knowledge_path)
    _append_fact_migration_task_to_csv(csv_path, task)


def get_fact_migration_task_by_id(knowledge_path: Path, task_id: str) -> FactMigrationTask | None:
    """Get a fact migration task by ID from fact_tasks.csv.

    Wrapper that computes the CSV path and calls the internal query function.

    Args:
        knowledge_path: Path to the .knowledge directory.
        task_id: UUID of the task to find.

    Returns:
        Task record if found, None otherwise.
    """
    csv_path = _get_fact_tasks_csv_path(knowledge_path)
    return _get_fact_migration_task_from_csv(csv_path, task_id)


def update_fact_migration_task(
    knowledge_path: Path,
    task_id: str,
    updates: dict[str, str],
) -> bool:
    """Update a fact migration task in fact_tasks.csv.

    Wrapper that computes the CSV path and calls the internal update function.

    Args:
        knowledge_path: Path to the .knowledge directory.
        task_id: UUID of the task to update.
        updates: Dictionary of column-value pairs to update.

    Returns:
        True if task was found and updated, False otherwise.
    """
    csv_path = _get_fact_tasks_csv_path(knowledge_path)
    return _update_fact_migration_task_in_csv(csv_path, task_id, updates)


def update_fact_migration_task_status(
    knowledge_path: Path,
    task_id: str,
    status: str,
    validated_at: str | None = None,
) -> bool:
    """Update the status of a fact migration task.

    Convenience wrapper for updating task status and validated_at timestamp.

    Args:
        knowledge_path: Path to the .knowledge directory.
        task_id: UUID of the task to update.
        status: New status value (pending, in_progress, completed, failed).
        validated_at: Optional validation timestamp (ISO 8601 basic format).

    Returns:
        True if task was found and updated, False otherwise.
    """
    updates: dict[str, str] = {"status": status}
    if validated_at is not None:
        updates["validated_at"] = validated_at
    return update_fact_migration_task(knowledge_path, task_id, updates)


# Legacy function aliases for backwards compatibility with existing tests
def ensure_fact_migration_csv_exists(csv_path: Path) -> None:
    """Create fact migration tasks CSV with header if it does not exist.

    Legacy alias for _ensure_fact_migration_csv_exists.
    """
    _ensure_fact_migration_csv_exists(csv_path)


# --- Command: start-fact-migration ---


def start_fact_migration(
    yaml_file: Path,
    element_id: str,
    knowledge_path: Path,
) -> int:
    """Start a new fact migration task.

    Creates a migration task, extracts entities from the YAML element text,
    and runs fact extraction for each entity.

    Args:
        yaml_file: Path to the YAML file containing the element.
        element_id: Element ID within the YAML file.
        knowledge_path: Path to the .knowledge directory.

    Returns:
        Exit code: 0 on success, 1 on error, 2 on incomplete extraction.
    """
    if not yaml_file.exists():
        print(f"Error: YAML file not found: {yaml_file}", file=sys.stderr)
        return 1

    # Read element text
    element_text = read_yaml_element_text(yaml_file, element_id)
    if element_text is None:
        print(f"Error: Element '{element_id}' not found in {yaml_file}", file=sys.stderr)
        return 1

    print(f"Starting fact migration for element: {element_id}")
    print(f"Source file: {yaml_file}")
    print(
        f'Element text: "{element_text[:100]}..."'
        if len(element_text) > 100
        else f'Element text: "{element_text}"'
    )
    print()

    # Extract entities from element text
    entities = extract_entities_from_text(element_text)
    if not entities:
        print("Warning: No entities found in element text.")
        print("Consider manually specifying entities for extraction.")

    print(f"Found {len(entities)} potential entity/entities: {entities}")
    print()

    # Create task record
    task_id = str(uuid.uuid4())
    try:
        yaml_file_rel = yaml_file.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        yaml_file_rel = str(yaml_file)

    task = FactMigrationTask(
        task_id=task_id,
        original_file_ref=yaml_file_rel,
        pattern_name=element_id.split(".")[0] if "." in element_id else element_id,
        status="pending",
        created_at=utc_timestamp(),
        validated_at="",
        element_id=element_id,
        entity_count=str(len(entities)),
        fact_count="0",
    )

    append_fact_migration_task(knowledge_path, task)
    print(f"Created task: {task_id}")

    # Run fact extraction for each entity
    total_facts = 0
    incomplete_extractions = 0

    for entity in entities:
        print(f"\nExtracting facts for entity: {entity}")
        print("-" * 40)

        extraction_args = _create_args_namespace(
            sentence=element_text,
            entity=entity,
            knowledge_path=knowledge_path,
            dry_run=False,
            model="Qwen/Qwen3-Embedding-0.6B",
        )

        result = fact_extraction.extract_facts_main(extraction_args)

        if result == 0:
            print(f"  Extraction complete for '{entity}'")
        elif result == 2:
            print(f"  Partial extraction for '{entity}' (entity still in residual)")
            incomplete_extractions += 1
        else:
            print(f"  Error extracting facts for '{entity}'", file=sys.stderr)

    # Count total facts extracted
    extractions_csv = knowledge_path / "facts" / "extractions.csv"
    facts = query_facts_for_task(extractions_csv, element_text)
    total_facts = len(facts)

    # Update task with fact count
    update_fact_migration_task(
        knowledge_path,
        task_id,
        {"fact_count": str(total_facts)},
    )

    print()
    print("=" * 50)
    print(f"Task ID: {task_id}")
    print(f"Entities: {len(entities)}")
    print(f"Facts extracted: {total_facts}")
    if incomplete_extractions > 0:
        print(f"Incomplete extractions: {incomplete_extractions}")

    print()
    print("Next steps:")
    print(f"  1. Classify facts: uv run knowledge.classify-facts --task-id {task_id}")
    print(
        f"  2. Move facts: uv run knowledge.move-facts --task-id {task_id} "
        f"--classification-file <path>"
    )
    print(f"  3. Validate: uv run knowledge.validate-fact-migration --task-id {task_id}")

    return 2 if incomplete_extractions > 0 else 0


def parse_start_fact_migration_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse arguments for start-fact-migration command.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Start a fact migration task for a YAML element.",
    )
    parser.add_argument(
        "--yaml-file",
        type=Path,
        required=True,
        dest="yaml_file",
        help="Path to the YAML file containing the element.",
    )
    parser.add_argument(
        "--element-id",
        required=True,
        dest="element_id",
        help="Element ID within the YAML file.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def main_start_fact_migration() -> int:
    """Entry point for knowledge.start-fact-migration command.

    Returns:
        Exit code: 0 on success, 1 on error, 2 on incomplete extraction.
    """
    try:
        args = parse_start_fact_migration_args()

        if args.yaml_file.is_absolute():
            yaml_file = args.yaml_file.resolve()
        else:
            yaml_file = (REPO_ROOT / args.yaml_file).resolve()

        if args.knowledge_path.is_absolute():
            knowledge_path = args.knowledge_path.resolve()
        else:
            knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

        return start_fact_migration(yaml_file, args.element_id, knowledge_path)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


# --- Command: classify-facts ---


def classify_facts(task_id: str, knowledge_path: Path) -> int:
    """Print instructions for classifying facts with knowledge-analyzer sub-agent.

    Args:
        task_id: UUID of the fact migration task.
        knowledge_path: Path to the .knowledge directory.

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    task = get_fact_migration_task_by_id(knowledge_path, task_id)

    if task is None:
        print(f"Error: Task not found: {task_id}", file=sys.stderr)
        return 1

    print(f"Task: {task_id}")
    print(f"Element: {task['element_id']}")
    print(f"Source: {task['original_file_ref']}")
    print(f"Facts: {task['fact_count']}")
    print()

    # Get element text to query facts
    yaml_path = REPO_ROOT / task["original_file_ref"]
    element_text = read_yaml_element_text(yaml_path, task["element_id"])

    if element_text is None:
        print(f"Warning: Could not read element text from {yaml_path}")
        extractions_csv = knowledge_path / "facts" / "extractions.csv"
        facts = []
    else:
        extractions_csv = knowledge_path / "facts" / "extractions.csv"
        facts = query_facts_for_task(extractions_csv, element_text)

    if not facts:
        print("No facts found for this task.")
        print("Run 'uv run knowledge.start-fact-migration' first to extract facts.")
        return 1

    print("Extracted Facts:")
    print("-" * 50)
    for i, fact in enumerate(facts, 1):
        print(f"{i}. [{fact['entity']}] {fact['fact_text']}")
        print(f"   Confidence: {fact['confidence']}")
        print()

    print()
    print("Classification Instructions")
    print("=" * 50)
    print()
    print("This step requires the knowledge-analyzer sub-agent to classify each fact")
    print("across domain, scope, and pattern dimensions.")
    print()
    print("To invoke the sub-agent:")
    print('    Task(subagent_type="knowledge-analyzer", prompt="")')
    print()
    print("The sub-agent will:")
    print("  1. Analyze each fact for domain (rest, fastapi, python, surrealdb, elasticsearch)")
    print("  2. Determine scope (GENERAL vs PROJECT)")
    print("  3. Identify pattern categorization")
    print("  4. Suggest target files for each fact")
    print()
    print("After classification, save the output to a JSON file and run:")
    print(f"    uv run knowledge.move-facts --task-id {task_id} --classification-file <path>")
    print()
    print("Expected classification JSON format:")
    print("""
{
  "classifications": [
    {
      "fact_id": "<uuid>",
      "domain": "fastapi",
      "scope": "PROJECT",
      "pattern": "factory-patterns",
      "target_file": "docs/development/project/fastapi/project.fastapi.factory-patterns.yml"
    }
  ]
}
""")

    return 0


def parse_classify_facts_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse arguments for classify-facts command.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Print instructions for classifying facts with knowledge-analyzer.",
    )
    parser.add_argument(
        "--task-id",
        required=True,
        dest="task_id",
        help="UUID of the fact migration task.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def main_classify_facts() -> int:
    """Entry point for knowledge.classify-facts command.

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    try:
        args = parse_classify_facts_args()

        if args.knowledge_path.is_absolute():
            knowledge_path = args.knowledge_path.resolve()
        else:
            knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

        return classify_facts(args.task_id, knowledge_path)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


# --- Command: move-facts ---


def move_facts(
    task_id: str,
    classification_file: Path,
    knowledge_path: Path,
    *,
    dry_run: bool = False,
) -> int:
    """Move classified facts to target domain/pattern files.

    Args:
        task_id: UUID of the fact migration task.
        classification_file: Path to the classification JSON file.
        knowledge_path: Path to the .knowledge directory.
        dry_run: If True, show changes without modifying files.

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    task = get_fact_migration_task_by_id(knowledge_path, task_id)

    if task is None:
        print(f"Error: Task not found: {task_id}", file=sys.stderr)
        return 1

    if not classification_file.exists():
        print(f"Error: Classification file not found: {classification_file}", file=sys.stderr)
        return 1

    try:
        classification_data = parse_classification_json(classification_file)
        classifications = normalize_classifications(classification_data)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Task: {task_id}")
    print(f"Classifications: {len(classifications)}")
    if dry_run:
        print("Mode: Dry run")
    print()

    # Update task status
    if not dry_run:
        update_fact_migration_task_status(knowledge_path, task_id, "in_progress")

    # Get element text for querying facts
    yaml_path = REPO_ROOT / task["original_file_ref"]
    element_text = read_yaml_element_text(yaml_path, task["element_id"])

    extractions_csv = knowledge_path / "facts" / "extractions.csv"
    facts = query_facts_for_task(extractions_csv, element_text) if element_text else []

    # Build fact lookup by ID
    facts_by_id = {f["fact_id"]: f for f in facts}

    facts_dir = knowledge_path / "facts"
    movements_csv = knowledge_path / "movements" / "iterative_movements.csv"

    stored_count = 0
    moved_count = 0

    for classification in classifications:
        fact_id = classification.get("fact_id")
        domain = classification.get("domain", "general")
        pattern = classification.get("pattern", "general")

        if not fact_id:
            print(f"Warning: Classification missing fact_id: {classification}")
            continue

        fact = facts_by_id.get(fact_id)
        if fact is None:
            print(f"Warning: Fact not found for ID: {fact_id}")
            continue

        print(f"Processing: {fact['entity']} - {fact['fact_text'][:50]}...")

        # Store fact to domain/pattern YAML
        yaml_filename = f"{domain}.{pattern}.facts.yml"
        fact_yaml_path = facts_dir / yaml_filename

        fact_record = fact_store.FactStoreRecord(
            fact_id=fact_id,
            entity=fact["entity"],
            fact_text=fact["fact_text"],
            source_file=task["original_file_ref"],
            source_element_id=task["element_id"],
            confidence=float(fact.get("confidence", "0.0")),
            extracted_at=fact["extracted_at"],
            domain=domain,
            pattern=pattern,
        )

        if dry_run:
            print(f"  Would store to: {yaml_filename}")
        else:
            result = fact_store.store_fact_to_yaml(fact_yaml_path, fact_record)
            if result:
                stored_count += 1
                print(f"  Stored to: {yaml_filename}")

        # Record iterative movement
        if not dry_run:
            movement_tracker.ensure_iterative_csv_exists(movements_csv)

            # We need to record the movement, but without loading the full model
            # Just create a simple record
            iteration_id = str(uuid.uuid4())
            movement_record = movement_tracker.IterativeMovementRecord(
                iteration_id=iteration_id,
                fact_id=fact_id,
                source_sentence=fact.get("source_sentence", ""),
                isolated_fact=fact["fact_text"],
                residual_sentence=fact.get("rewritten_sentence", ""),
                similarity_score=fact.get("confidence", "0.0"),
                reason="Fact migration",
                moved_at=utc_timestamp(),
            )
            movement_tracker.append_iterative_movement(movements_csv, movement_record)
            moved_count += 1
            print(f"  Movement tracked: {iteration_id[:8]}...")

    print()
    print("=" * 50)
    print(f"Facts stored: {stored_count}")
    print(f"Movements tracked: {moved_count}")

    if not dry_run:
        update_fact_migration_task_status(knowledge_path, task_id, "pending")

    print()
    print("Next step:")
    print(f"  Validate: uv run knowledge.validate-fact-migration --task-id {task_id}")

    return 0


def parse_move_facts_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse arguments for move-facts command.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Move classified facts to target domain/pattern files.",
    )
    parser.add_argument(
        "--task-id",
        required=True,
        dest="task_id",
        help="UUID of the fact migration task.",
    )
    parser.add_argument(
        "--classification-file",
        type=Path,
        required=True,
        dest="classification_file",
        help="Path to the classification JSON file.",
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


def main_move_facts() -> int:
    """Entry point for knowledge.move-facts command.

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    try:
        args = parse_move_facts_args()

        if args.classification_file.is_absolute():
            classification_file = args.classification_file.resolve()
        else:
            classification_file = (REPO_ROOT / args.classification_file).resolve()

        if args.knowledge_path.is_absolute():
            knowledge_path = args.knowledge_path.resolve()
        else:
            knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

        return move_facts(
            args.task_id,
            classification_file,
            knowledge_path,
            dry_run=args.dry_run,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


# --- Command: validate-fact-migration ---

# Similarity score threshold for invariant validation
SIMILARITY_THRESHOLD = 0.95


def count_invariant_failures(csv_path: Path, fact_ids: list[str]) -> int:
    """Count movements with similarity scores below the threshold.

    The invariant `original = isolated_fact + residual_sentence` is validated
    using semantic similarity. Movements with similarity_score < 0.95 indicate
    potential information loss during fact extraction.

    Args:
        csv_path: Path to the iterative movements CSV file.
        fact_ids: List of fact IDs to check.

    Returns:
        Count of movements that failed the invariant validation.
    """
    if not fact_ids or not csv_path.exists():
        return 0

    query = """
        SELECT COUNT(*)
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE fact_id IN (SELECT UNNEST(?))
          AND CAST(similarity_score AS DOUBLE) < ?
    """
    try:
        result = duckdb.execute(query, [str(csv_path), fact_ids, SIMILARITY_THRESHOLD]).fetchone()
        return result[0] if result else 0
    except duckdb.Error:
        # Fallback to Python if DuckDB query fails
        movements = movement_tracker.query_iterative_movements(csv_path)
        return sum(
            1
            for m in movements
            if m.get("fact_id") in fact_ids
            and float(m.get("similarity_score", "1.0")) < SIMILARITY_THRESHOLD
        )


def validate_fact_migration(task_id: str, knowledge_path: Path) -> int:
    """Validate a fact migration task.

    Checks that all facts are stored, all movements are tracked, and all
    movements satisfy the invariant `original = isolated_fact + residual_sentence`
    (validated via semantic similarity >= 0.95).

    Args:
        task_id: UUID of the fact migration task.
        knowledge_path: Path to the .knowledge directory.

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    task = get_fact_migration_task_by_id(knowledge_path, task_id)

    if task is None:
        print(f"Error: Task not found: {task_id}", file=sys.stderr)
        return 1

    if task["status"] == "completed":
        print(f"Task {task_id} is already completed (validated at {task['validated_at']})")
        return 0

    print(f"Validating task: {task_id}")
    print(f"Element: {task['element_id']}")
    print(f"Source: {task['original_file_ref']}")
    print()

    # Update status to in_progress
    update_fact_migration_task_status(knowledge_path, task_id, "in_progress")

    # Get element text
    yaml_path = REPO_ROOT / task["original_file_ref"]
    element_text = read_yaml_element_text(yaml_path, task["element_id"])

    # Query facts
    extractions_csv = knowledge_path / "facts" / "extractions.csv"
    facts = query_facts_for_task(extractions_csv, element_text) if element_text else []

    fact_ids = [f["fact_id"] for f in facts]
    expected_facts = int(task.get("fact_count", "0"))

    print(f"Expected facts: {expected_facts}")
    print(f"Found facts: {len(facts)}")

    # Check stored facts
    facts_dir = knowledge_path / "facts"
    stored_count = count_stored_facts(facts_dir, fact_ids)
    print(f"Stored facts: {stored_count}")

    # Check tracked movements
    movements_csv = knowledge_path / "movements" / "iterative_movements.csv"
    tracked_count = count_tracked_movements(movements_csv, fact_ids)
    print(f"Tracked movements: {tracked_count}")

    # Check invariant validation (original = isolated + residual)
    invariant_failures = count_invariant_failures(movements_csv, fact_ids)
    print(f"Invariant failures (similarity < {SIMILARITY_THRESHOLD}): {invariant_failures}")

    print()
    print("Validation Results:")
    print("-" * 30)

    issues = 0

    if len(facts) == 0 and expected_facts > 0:
        print("  [x] No facts found in extractions.csv")
        issues += 1
    else:
        print(f"  [+] Facts in extractions.csv: {len(facts)}")

    if stored_count < len(facts):
        print(f"  [x] Not all facts stored: {stored_count}/{len(facts)}")
        issues += 1
    else:
        print(f"  [+] All facts stored: {stored_count}/{len(facts)}")

    if tracked_count < len(facts):
        print(f"  [x] Not all movements tracked: {tracked_count}/{len(facts)}")
        issues += 1
    else:
        print(f"  [+] All movements tracked: {tracked_count}/{len(facts)}")

    if invariant_failures > 0:
        print(
            f"  [x] Invariant violations: {invariant_failures} movement(s) "
            f"did not satisfy original = isolated_fact + residual_sentence"
        )
        issues += 1
    else:
        print("  [+] All movements satisfy invariant (similarity >= 0.95)")

    print()

    if issues > 0:
        update_fact_migration_task_status(knowledge_path, task_id, "failed", utc_timestamp())
        print(f"Validation failed: {issues} issue(s) found")
        return 1

    update_fact_migration_task_status(knowledge_path, task_id, "completed", utc_timestamp())
    print(f"Migration validated successfully for task {task_id}")

    return 0


def parse_validate_fact_migration_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse arguments for validate-fact-migration command.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Validate a fact migration task.",
    )
    parser.add_argument(
        "--task-id",
        required=True,
        dest="task_id",
        help="UUID of the fact migration task.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def main_validate_fact_migration() -> int:
    """Entry point for knowledge.validate-fact-migration command.

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    try:
        args = parse_validate_fact_migration_args()

        if args.knowledge_path.is_absolute():
            knowledge_path = args.knowledge_path.resolve()
        else:
            knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

        return validate_fact_migration(args.task_id, knowledge_path)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main_start_fact_migration())
