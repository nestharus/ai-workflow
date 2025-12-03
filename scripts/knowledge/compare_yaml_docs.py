"""Compare YAML documents by extracting IDs and their associated object data.

This module provides utilities for parsing YAML files and extracting ID-to-object
mappings, enabling dict-to-dict comparison of document content across different
versions or files. It compares original YAML files with their split counterparts
in subdirectories.

Per the YAML schema guidelines, `id` is the only field that may exist on elements.
It is required for root elements of sections but optional for children. The
comparison logic handles this by only tracking elements that have an `id` field.

Outputs flattened CSV files to `.knowledge/comparisons/` with columns:
source_file, id, origin_type, original_data, split_file, split_data

Usage:
    uv run knowledge.compare-yml-docs [--path <directory>] [--original-files <file> ...]

Args:
    --path: Base directory containing original and split YAML files
            (default: docs/development/).
    --original-files: Optional list of timestamped original files from
            `.knowledge/originals/` to use instead of globbing for
            `original.*.yml` files in the base path. When not provided,
            falls back to the default glob pattern.

Example:
    uv run knowledge.compare-yml-docs \
      --original-files .knowledge/originals/20251201T134735Z-api-patterns.yml
"""

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

import duckdb
import yaml

from scripts.dev.utils import REPO_ROOT


@dataclass
class ContainmentEdge:
    """Represents a parent-child containment relationship between elements.

    When a parent element contains a nested dict with its own `id` field,
    a ContainmentEdge is created to record this relationship. The nested
    child is sliced out and replaced with a reference in the parent.

    Attributes:
        parent_id: The ID of the parent element.
        child_id: The ID of the nested child element.
        field_path: The path where the child appeared (e.g., "items[2]").
        source_file: Relative path to the source YAML file.
    """

    parent_id: str
    child_id: str
    field_path: str
    source_file: str


def _is_element(obj: Any) -> bool:  # noqa: ANN401
    """Check if a value is an element (dict with string id field).

    Args:
        obj: Value to check.

    Returns:
        True if obj is a dict with a string 'id' field, False otherwise.
    """
    return isinstance(obj, dict) and isinstance(obj.get("id"), str)


def _slice_element(
    data: Any,  # noqa: ANN401
    parent_id: str,
    field_path_prefix: str,
    source_file: str,
    containment_edges: list[ContainmentEdge],
) -> Any:  # noqa: ANN401
    """Recursively slice an element, replacing nested ID-bearing dicts with refs.

    Traverses the data structure and replaces any nested dict that has its own
    string `id` field with a reference `{"$ref": "child_id"}`. For each such
    replacement, a ContainmentEdge is appended to the provided list.

    Args:
        data: The data structure to slice (part of the parent element).
        parent_id: The ID of the parent element being sliced.
        field_path_prefix: Current field path prefix (e.g., "items[0].routes").
        source_file: Relative path to the source YAML file.
        containment_edges: List to append ContainmentEdge records to.

    Returns:
        The sliced data structure with nested elements replaced by refs.
    """
    if isinstance(data, dict):
        # If this dict has its own id (and is not the root), it's a child element
        if _is_element(data) and field_path_prefix:
            child_id = data["id"]
            containment_edges.append(
                ContainmentEdge(
                    parent_id=parent_id,
                    child_id=child_id,
                    field_path=field_path_prefix,
                    source_file=source_file,
                )
            )
            return {"$ref": child_id}

        # Recursively slice dict values
        sliced: dict[str, Any] = {}
        for key, value in data.items():
            new_path = f"{field_path_prefix}.{key}" if field_path_prefix else key
            sliced[key] = _slice_element(
                value, parent_id, new_path, source_file, containment_edges
            )
        return sliced

    if isinstance(data, list):
        # Recursively slice list items
        sliced_list: list[Any] = []
        for index, item in enumerate(data):
            new_path = f"{field_path_prefix}[{index}]"
            sliced_list.append(
                _slice_element(item, parent_id, new_path, source_file, containment_edges)
            )
        return sliced_list

    # Primitives pass through unchanged
    return data


DEVELOPMENT_DIR = REPO_ROOT / "docs" / "development"
SUBDIRS = ("python", "fastapi", "elasticsearch", "surrealdb")

# Centralized constant for the knowledge directory name to avoid duplication
KNOWLEDGE_DIR_NAME = ".knowledge"

YamlValue = str | int | float | bool | None | list["YamlValue"] | dict[str, "YamlValue"]
YamlStructure = dict[str, YamlValue] | list[YamlValue]

OriginType = Literal["original", "split_only", "orphan"]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for YAML document comparison.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace with path and original_files attributes.
    """
    parser = argparse.ArgumentParser(
        description="Compare original YAML documents with their split counterparts.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=DEVELOPMENT_DIR,
        help="Base directory containing original and split YAML files "
        "(default: docs/development/).",
    )
    parser.add_argument(
        "--original-files",
        nargs="*",
        type=Path,
        help="Optional list of timestamped original files from .knowledge/originals/ "
        "to use instead of globbing for original.*.yml files in the base path.",
    )
    return parser.parse_args(argv)


class SplitEntry(TypedDict):
    """A split file's object data for a specific ID."""

    split_data: dict[str, Any]
    source_file: str


class ComparisonEntry(TypedDict):
    """Comparison result for a single ID.

    The origin_type field indicates the source of this entry:
    - original: ID from an original.*.yml file with differing or missing split data
    - split_only: ID found in split files but not in the corresponding original
    - orphan: ID from a file in a subdirectory with no corresponding original file
    """

    source_file: str
    id: str
    source_data: dict[str, Any]
    splits: list[SplitEntry]
    origin_type: OriginType


class CompareResult(TypedDict):
    """Comparison results for a single original file."""

    original_file: str
    entries: list[ComparisonEntry]


def _validate_yaml_result(
    result: Any,  # noqa: ANN401
    file_path: Path,
) -> YamlStructure:
    """Validate that the parsed YAML result is a dict or list.

    Args:
        result: The parsed result from yaml.safe_load().
        file_path: Path to the file for error messages.

    Returns:
        The validated result as a dict or list.

    Raises:
        TypeError: If the result is not a dict or list.
    """
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        return result
    relative_path = file_path.relative_to(REPO_ROOT)
    msg = f"Unexpected YAML structure in {relative_path}: expected dict or list"
    raise TypeError(msg)


def parse_yaml_file(file_path: Path) -> YamlStructure:
    """Parse a YAML file and return its decoded structure.

    Reads the file content and parses it using PyYAML's safe_load.

    Args:
        file_path: Path to the YAML file to parse.

    Returns:
        The parsed YAML structure as a Python dict or list.

    Raises:
        yaml.YAMLError: If the file contains invalid YAML syntax.
        FileNotFoundError: If the file does not exist.
        TypeError: If the parsed result is not a dict or list.
        ValueError: If parsing fails for other reasons.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
        result = yaml.safe_load(content)
    except yaml.YAMLError:
        raise
    except FileNotFoundError:
        raise
    except Exception as exc:
        relative_path = file_path.relative_to(REPO_ROOT)
        msg = f"Failed to parse {relative_path}: {exc}"
        raise ValueError(msg) from exc
    else:
        return _validate_yaml_result(result, file_path)


def extract_ids_and_objects(
    data: YamlValue,
    parent_path: str = "",
    source_file: str = "",
) -> tuple[dict[str, dict[str, Any]], list[ContainmentEdge]]:
    """Recursively extract IDs and sliced objects from a YAML structure.

    Traverses the parsed YAML structure to find all elements with an 'id' field.
    For each element, nested ID-bearing dicts are sliced out and replaced with
    `{"$ref": "child_id"}` references. Containment edges are recorded for each
    such replacement.

    Per the YAML schema guidelines, `id` is required for root elements of sections
    but optional for children. This function only tracks elements that have an `id`
    field.

    Args:
        data: The parsed YAML structure (dict, list, or primitive).
        parent_path: Path string for debugging purposes (tracks traversal path).
        source_file: Relative path to the source file for containment edges.

    Returns:
        Tuple of (sliced_objects, containment_edges) where:
        - sliced_objects: Dict mapping element IDs to their sliced object data
          (child content excluded, replaced with $ref).
        - containment_edges: List of ContainmentEdge records for all nested
          ID-bearing dicts found.
    """
    result: dict[str, dict[str, Any]] = {}
    all_edges: list[ContainmentEdge] = []

    if isinstance(data, dict):
        if "id" in data:
            element_id = data["id"]
            if isinstance(element_id, str):
                # Slice this element: replace nested ID-bearing dicts with refs
                element_edges: list[ContainmentEdge] = []
                sliced_data = _slice_element(
                    data, element_id, "", source_file, element_edges
                )
                result[element_id] = sliced_data
                all_edges.extend(element_edges)

        for key, value in data.items():
            child_path = f"{parent_path}.{key}" if parent_path else key
            child_results, child_edges = extract_ids_and_objects(
                value, child_path, source_file
            )
            result.update(child_results)
            all_edges.extend(child_edges)

    elif isinstance(data, list):
        for index, item in enumerate(data):
            child_path = f"{parent_path}[{index}]"
            child_results, child_edges = extract_ids_and_objects(
                item, child_path, source_file
            )
            result.update(child_results)
            all_edges.extend(child_edges)

    return result, all_edges


def _format_value_for_text(value: Any) -> str:  # noqa: ANN401
    """Format a value for text projection output.

    Args:
        value: The value to format.

    Returns:
        String representation of the value for text projection.
    """
    if isinstance(value, dict):
        if "$ref" in value:
            return f"$ref:{value['$ref']}"
        # Nested dict without $ref - format as key=value pairs
        parts = [f"{k}={_format_value_for_text(v)}" for k, v in sorted(value.items())]
        return "{" + ", ".join(parts) + "}"
    if isinstance(value, list):
        formatted = [_format_value_for_text(item) for item in value]
        return "[" + ", ".join(formatted) + "]"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def extract_ids_and_text(
    data: YamlValue,
    source_file: str = "",
) -> dict[str, str]:
    """Extract IDs and text projections from sliced elements.

    Calls extract_ids_and_objects to get sliced elements, then produces a
    deterministic text projection for each element. The text projection
    flattens the sliced dict into key=value lines for scalars, key=[...]
    for lists, and key=$ref:child_id for references.

    This function is used for hashing in resolution_tracker and for
    candidate extraction context. Per the fact redesign (lines 131-133),
    the text hash is computed from the sliced representation with child
    content excluded.

    Args:
        data: The parsed YAML structure (dict, list, or primitive).
        source_file: Relative path to the source file for containment edges.

    Returns:
        Dictionary mapping element IDs to their text projection strings.
    """
    sliced_objects, _ = extract_ids_and_objects(data, source_file=source_file)
    result: dict[str, str] = {}

    for element_id, sliced_dict in sliced_objects.items():
        # Build deterministic text projection from sliced dict
        lines: list[str] = []
        for key in sorted(sliced_dict.keys()):
            value = sliced_dict[key]
            formatted = _format_value_for_text(value)
            lines.append(f"{key}={formatted}")
        result[element_id] = "\n".join(lines)

    return result


def find_originals(
    base_path: Path,
    original_files: list[Path] | None = None,
) -> list[Path]:
    """Find all original YAML files in the development directory.

    When original_files is provided, uses those files instead of globbing.
    Otherwise, finds top-level files matching the pattern 'original.*.yml'.

    Args:
        base_path: Base directory to search for original files (used for glob fallback).
        original_files: Optional list of explicit original file paths to use.
            When provided and non-empty, these files are used instead of globbing.

    Returns:
        Sorted list of paths to original YAML files.
    """
    if original_files:
        valid_files: list[Path] = []
        for file_path in original_files:
            if file_path.exists() and file_path.is_file():
                valid_files.append(file_path)
            else:
                print(
                    f"Warning: Provided original file does not exist: {file_path}",
                    file=sys.stderr,
                )
        return sorted(valid_files)

    pattern = "original.*.yml"
    return sorted(base_path.glob(pattern))


def find_all_yml(base_path: Path) -> list[Path]:
    """Find all YAML files in subdirectories of the development directory.

    Args:
        base_path: Base directory containing subdirectories to search.

    Returns:
        Sorted list of paths to all YAML files in subdirectories.
    """
    files: list[Path] = []
    for subdir in SUBDIRS:
        subdir_path = base_path / subdir
        if subdir_path.is_dir():
            files.extend(subdir_path.glob("*.yml"))
    return sorted(files)


def _strip_timestamp_prefix(name: str) -> str:
    """Strip ISO 8601 timestamp prefix from a filename stem if present.

    Handles timestamped filenames like '20251201T134735Z-api-patterns' by
    stripping the timestamp prefix up to and including the first hyphen.

    Args:
        name: Filename stem to process.

    Returns:
        The stem with timestamp prefix stripped, or original if no match.
    """
    # Match ISO 8601 basic format timestamp: YYYYMMDDTHHMMSSZ-
    match = re.match(r"^\d{8}T\d{6}Z-(.+)$", name)
    if match:
        return match.group(1)
    return name


def pattern_from_path(path: Path) -> str:
    """Extract the pattern name from a YAML file path.

    For 'original.api-patterns.yml', returns 'api-patterns'.
    For 'python.api-patterns.yml', returns 'api-patterns'.
    For '20251201T134735Z-api-patterns.yml', returns 'api-patterns'.

    Args:
        path: Path to a YAML file.

    Returns:
        The extracted pattern name.
    """
    name = path.stem

    # Handle timestamped originals: 20251201T134735Z-api-patterns -> api-patterns
    name = _strip_timestamp_prefix(name)

    if name.startswith("original."):
        return name[len("original.") :]
    parts = name.split(".", 1)
    if len(parts) == 2:
        return parts[1]
    return name


def find_mapped_splits(pattern: str, base_path: Path) -> dict[str, Path]:
    """Find all split files that match a given pattern.

    For pattern 'api-patterns', finds files like 'python.api-patterns.yml',
    'fastapi.api-patterns.yml', etc.

    Args:
        pattern: The pattern name to search for.
        base_path: Base directory containing subdirectories to search.

    Returns:
        Dictionary mapping subdirectory name to file path.
    """
    result: dict[str, Path] = {}
    for subdir in SUBDIRS:
        expected_name = f"{subdir}.{pattern}.yml"
        expected_path = base_path / subdir / expected_name
        if expected_path.is_file():
            result[subdir] = expected_path
    return result


def get_ids_objects(file_path: Path) -> dict[str, dict[str, Any]]:
    """Extract IDs and sliced object data from a YAML file.

    This is a convenience wrapper that extracts only the sliced objects dict,
    discarding containment edges. Use extract_ids_and_objects directly if
    you need the containment edges.

    Args:
        file_path: Path to the YAML file.

    Returns:
        Dictionary mapping IDs to their sliced object data (child content
        excluded, replaced with $ref).
    """
    data = parse_yaml_file(file_path)
    try:
        relative_path = file_path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        relative_path = file_path.as_posix()
    sliced_objects, _ = extract_ids_and_objects(data, source_file=relative_path)
    return sliced_objects


def aggregate_split_objects(
    split_map: dict[str, Path],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Aggregate object data from split files by ID.

    Collects the full object data for each ID across all split files. Warns if
    the same ID has conflicting data in different split files.

    Args:
        split_map: Dictionary mapping subdirectory name to file path.

    Returns:
        Dictionary mapping ID to {relative_file_path: object_data}.
    """
    result: dict[str, dict[str, dict[str, Any]]] = {}

    for _, file_path in split_map.items():
        relative_path = file_path.relative_to(REPO_ROOT).as_posix()
        try:
            ids_objects = get_ids_objects(file_path)
        except Exception as exc:
            print(f"Warning: Failed to parse {relative_path}: {exc}", file=sys.stderr)
            continue

        for element_id, obj_data in ids_objects.items():
            if element_id not in result:
                result[element_id] = {}
            result[element_id][relative_path] = obj_data

    # Check for conflicting data across split files for the same ID
    for element_id, file_objects in result.items():
        unique_data = {json.dumps(obj, sort_keys=True) for obj in file_objects.values()}
        if len(unique_data) > 1:
            files = ", ".join(file_objects.keys())
            print(
                f"Warning: Conflicting data for ID '{element_id}' in: {files}",
                file=sys.stderr,
            )

    return result


def compare_original_to_splits(
    orig_path: Path,
    split_map: dict[str, Path],
) -> list[ComparisonEntry]:
    """Compare an original file to its split files using dict equality.

    Performs bidirectional comparison:
    1. For each ID in the original, checks if any split has matching data (dict == dict).
    2. For IDs in splits not in the original, adds them as extras.

    Args:
        orig_path: Path to the original YAML file.
        split_map: Dictionary mapping subdirectory name to split file path.

    Returns:
        List of comparison entries for non-matching IDs.
    """
    entries: list[ComparisonEntry] = []
    orig_relative = orig_path.relative_to(REPO_ROOT).as_posix()

    try:
        orig_ids = get_ids_objects(orig_path)
    except Exception as exc:
        print(f"Warning: Failed to parse {orig_relative}: {exc}", file=sys.stderr)
        return entries

    split_objects = aggregate_split_objects(split_map)

    for element_id, orig_data in orig_ids.items():
        split_data = split_objects.get(element_id, {})

        # Dict-to-dict comparison for exact match
        has_exact_match = any(obj == orig_data for obj in split_data.values())

        if not has_exact_match:
            splits: list[SplitEntry] = [
                SplitEntry(split_data=obj, source_file=file_path)
                for file_path, obj in split_data.items()
            ]
            entries.append(
                ComparisonEntry(
                    source_file=orig_relative,
                    id=element_id,
                    source_data=orig_data,
                    splits=splits,
                    origin_type="original",
                )
            )

    orig_id_set = set(orig_ids.keys())
    for element_id, file_objects in split_objects.items():
        if element_id not in orig_id_set:
            for file_path, obj in file_objects.items():
                entries.append(
                    ComparisonEntry(
                        source_file=file_path,
                        id=element_id,
                        source_data=obj,
                        splits=[],
                        origin_type="split_only",
                    )
                )

    return entries


def compare_all(
    base_path: Path,
    original_files: list[Path] | None = None,
) -> tuple[dict[str, CompareResult], set[str]]:
    """Compare all original files to their split files.

    Also handles orphan files in subdirectories that don't have a corresponding
    original file.

    Args:
        base_path: Base directory containing original and split YAML files.
        original_files: Optional list of explicit original file paths to use.
            When provided, these files are used instead of globbing for
            original.*.yml files in the base path.

    Returns:
        Tuple of (results dict, processed patterns set).
        Results dict maps original file path to comparison results.
        Processed patterns set contains all pattern names that were compared.
    """
    results: dict[str, CompareResult] = {}
    processed_patterns: set[str] = set()

    originals = find_originals(base_path, original_files)
    for orig_path in originals:
        pattern = pattern_from_path(orig_path)
        processed_patterns.add(pattern)

        split_map = find_mapped_splits(pattern, base_path)
        entries = compare_original_to_splits(orig_path, split_map)

        orig_relative = orig_path.relative_to(REPO_ROOT).as_posix()
        if entries:
            results[orig_relative] = CompareResult(
                original_file=orig_relative,
                entries=entries,
            )

    all_yml = find_all_yml(base_path)
    orphan_paths: list[Path] = []

    for yml_path in all_yml:
        pattern = pattern_from_path(yml_path)
        if pattern not in processed_patterns:
            orphan_paths.append(yml_path)

    for orphan_path in orphan_paths:
        orphan_relative = orphan_path.relative_to(REPO_ROOT).as_posix()
        try:
            orphan_ids = get_ids_objects(orphan_path)
        except Exception as exc:
            print(
                f"Warning: Failed to parse orphan {orphan_relative}: {exc}",
                file=sys.stderr,
            )
            continue

        orphan_entries: list[ComparisonEntry] = []
        for element_id, obj_data in orphan_ids.items():
            orphan_entries.append(
                ComparisonEntry(
                    source_file=orphan_relative,
                    id=element_id,
                    source_data=obj_data,
                    splits=[],
                    origin_type="orphan",
                )
            )

        if orphan_entries:
            results[orphan_relative] = CompareResult(
                original_file=orphan_relative,
                entries=orphan_entries,
            )

    return results, processed_patterns


def _get_compare_output_path(source_path: str) -> Path:
    """Determine the output path for a comparison CSV file.

    Extracts the pattern name from the source path and returns a path under
    `.knowledge/comparisons/<pattern-name>.csv`.

    Args:
        source_path: The relative source file path.

    Returns:
        Path where the comparison CSV file should be written.
    """
    source = Path(source_path)
    pattern = pattern_from_path(source)
    comparisons_dir = REPO_ROOT / KNOWLEDGE_DIR_NAME / "comparisons"
    return comparisons_dir / f"{pattern}.csv"


CSV_COLUMNS = ["source_file", "id", "origin_type", "original_data", "split_file", "split_data"]


def _flatten_entry_to_rows(entry: ComparisonEntry) -> list[dict[str, str]]:
    """Flatten a ComparisonEntry into CSV rows.

    For entries with splits, creates one row per split.
    For entries without splits, creates one row with empty split columns.

    Note: The `original_data` column is populated from `source_data` (JSON-serialized)
    for all origin types. For `split_only` and `orphan` entries, this represents the
    data from the split or orphan file respectively, not from an original file. Query
    authors should be aware of this semantic when filtering by origin_type.

    Args:
        entry: The comparison entry to flatten.

    Returns:
        List of dictionaries representing CSV rows.
    """
    rows: list[dict[str, str]] = []
    # Serialize source_data as JSON for CSV storage
    source_data_json = json.dumps(entry["source_data"], sort_keys=True)
    base_row = {
        "source_file": entry["source_file"],
        "id": entry["id"],
        "origin_type": entry["origin_type"],
        "original_data": source_data_json,
    }

    if entry["splits"]:
        for split in entry["splits"]:
            split_data_json = json.dumps(split["split_data"], sort_keys=True)
            row = {
                **base_row,
                "split_file": split["source_file"],
                "split_data": split_data_json,
            }
            rows.append(row)
    else:
        row = {**base_row, "split_file": "", "split_data": ""}
        rows.append(row)

    return rows


def write_compare_files(results: dict[str, CompareResult]) -> int:
    """Write comparison results to CSV files in .knowledge/comparisons/.

    Creates one CSV file per pattern with flattened comparison entries.
    Each row represents a (source_file, id, split_file) combination.
    Uses DuckDB to write CSV files.

    Note: Comparison CSVs are regenerated on each run and older data is intentionally
    discarded. This design ensures the CSV always reflects the current state of the
    YAML files being compared, rather than accumulating stale historical data.

    Args:
        results: Dictionary mapping file paths to comparison results.

    Returns:
        Number of CSV files written.
    """
    pattern_rows: dict[str, list[dict[str, str]]] = {}

    for source_path, compare_result in results.items():
        output_path = _get_compare_output_path(source_path)
        pattern_name = output_path.stem

        if pattern_name not in pattern_rows:
            pattern_rows[pattern_name] = []

        for entry in compare_result["entries"]:
            pattern_rows[pattern_name].extend(_flatten_entry_to_rows(entry))

    files_written = 0
    comparisons_dir = REPO_ROOT / KNOWLEDGE_DIR_NAME / "comparisons"

    for pattern_name, rows in pattern_rows.items():
        output_path = comparisons_dir / f"{pattern_name}.csv"

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            conn = duckdb.connect()
            try:
                columns_def = ", ".join(f"{col} VARCHAR" for col in CSV_COLUMNS)
                conn.execute(f"CREATE TABLE comparisons ({columns_def})")
                if rows:
                    placeholders = ", ".join("?" for _ in CSV_COLUMNS)
                    insert_sql = f"INSERT INTO comparisons VALUES ({placeholders})"
                    for row in rows:
                        values = [row.get(col, "") for col in CSV_COLUMNS]
                        conn.execute(insert_sql, values)
                copy_sql = f"COPY comparisons TO '{output_path}' (HEADER, DELIMITER ',')"
                conn.execute(copy_sql)
            finally:
                conn.close()
            files_written += 1
        except (OSError, duckdb.Error) as exc:
            print(
                f"Warning: Failed to write {output_path}: {exc}",
                file=sys.stderr,
            )

    return files_written


CONTAINMENT_EDGE_COLUMNS = ["parent_id", "child_id", "field_path", "source_file"]


def write_containment_edges(
    edges: list[ContainmentEdge],
    knowledge_path: Path | None = None,
) -> int:
    """Write containment edges to CSV file in .knowledge/graph/.

    Creates or replaces the containment_edges.csv file with the provided edges.
    Deduplicates edges by (source_file, parent_id, child_id, field_path) before
    writing.

    Args:
        edges: List of ContainmentEdge records to write.
        knowledge_path: Base knowledge directory path. If None, uses REPO_ROOT.

    Returns:
        Number of edges written.

    Raises:
        RuntimeError: If writing to DuckDB or filesystem fails.
    """
    if knowledge_path is None:
        knowledge_path = REPO_ROOT / KNOWLEDGE_DIR_NAME

    graph_dir = knowledge_path / "graph"
    output_path = graph_dir / "containment_edges.csv"

    # Deduplicate edges by (source_file, parent_id, child_id, field_path)
    seen: set[tuple[str, str, str, str]] = set()
    unique_edges: list[ContainmentEdge] = []
    for edge in edges:
        key = (edge.source_file, edge.parent_id, edge.child_id, edge.field_path)
        if key not in seen:
            seen.add(key)
            unique_edges.append(edge)

    try:
        graph_dir.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect()
        try:
            columns_def = ", ".join(f"{col} VARCHAR" for col in CONTAINMENT_EDGE_COLUMNS)
            conn.execute(f"CREATE TABLE containment_edges ({columns_def})")
            if unique_edges:
                placeholders = ", ".join("?" for _ in CONTAINMENT_EDGE_COLUMNS)
                insert_sql = f"INSERT INTO containment_edges VALUES ({placeholders})"
                for edge in unique_edges:
                    values = [
                        edge.parent_id,
                        edge.child_id,
                        edge.field_path,
                        edge.source_file,
                    ]
                    conn.execute(insert_sql, values)
            copy_sql = f"COPY containment_edges TO '{output_path}' (HEADER, DELIMITER ',')"
            conn.execute(copy_sql)
        finally:
            conn.close()
        return len(unique_edges)
    except (OSError, duckdb.Error) as exc:
        msg = f"Failed to write containment edges to {output_path}: {exc}"
        raise RuntimeError(msg) from exc


def _get_logical_pattern_from_csv(csv_path: Path) -> str:
    """Extract the logical pattern name from a comparison CSV filename.

    Handles both legacy filenames (e.g., 'api-patterns.csv') and
    timestamp-prefixed filenames (e.g., '20251201T134735Z-api-patterns.csv').

    Args:
        csv_path: Path to a comparison CSV file.

    Returns:
        The logical pattern name with any timestamp prefix stripped.
    """
    return _strip_timestamp_prefix(csv_path.stem)


def _delete_stale_comparison_csvs(
    processed_patterns: set[str],
    patterns_with_differences: set[str],
) -> int:
    """Delete comparison CSVs for patterns that no longer have differences.

    Handles both legacy CSV filenames (e.g., 'api-patterns.csv') and
    timestamp-prefixed filenames (e.g., '20251201T134735Z-api-patterns.csv')
    by normalizing to logical pattern names before comparison.

    Args:
        processed_patterns: All patterns that were compared in this run.
        patterns_with_differences: Patterns that have current differences.

    Returns:
        Number of stale CSV files deleted.
    """
    comparisons_dir = REPO_ROOT / KNOWLEDGE_DIR_NAME / "comparisons"
    if not comparisons_dir.exists():
        return 0

    deleted = 0
    patterns_to_delete = processed_patterns - patterns_with_differences

    # Scan all CSV files and delete those whose logical pattern has no differences
    for csv_path in comparisons_dir.glob("*.csv"):
        logical_pattern = _get_logical_pattern_from_csv(csv_path)

        # Only delete if the logical pattern was processed and has no differences
        if logical_pattern in patterns_to_delete:
            try:
                csv_path.unlink()
                deleted += 1
            except OSError as exc:
                print(
                    f"Warning: Failed to delete stale CSV {csv_path}: {exc}",
                    file=sys.stderr,
                )

    return deleted


def _collect_containment_edges_from_files(file_paths: list[Path]) -> list[ContainmentEdge]:
    """Collect containment edges from a list of YAML files.

    Args:
        file_paths: List of YAML file paths to process.

    Returns:
        List of all containment edges from all files.
    """
    all_edges: list[ContainmentEdge] = []
    for file_path in file_paths:
        try:
            relative_path = file_path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            relative_path = file_path.as_posix()
        try:
            data = parse_yaml_file(file_path)
            _, edges = extract_ids_and_objects(data, source_file=relative_path)
            all_edges.extend(edges)
        except Exception:
            # Silently skip files that can't be parsed
            continue
    return all_edges


def main() -> int:
    """Run comparison and write results to CSV files.

    Deletes stale comparison CSVs for patterns that no longer have differences,
    ensuring validation does not fail due to outdated data. Supports the
    --original-files parameter to specify timestamped originals from
    .knowledge/originals/ instead of globbing for original.*.yml files.

    Also collects and writes containment edges from all processed YAML files
    to .knowledge/graph/containment_edges.csv.

    Returns:
        0 if no differences found, 1 if differences exist.
    """
    args = parse_args()
    base_path = args.path.resolve()

    if not base_path.exists() or not base_path.is_dir():
        print(
            f"Error: Specified path '{base_path}' does not exist or is not a directory.",
            file=sys.stderr,
        )
        return 1

    original_files: list[Path] | None = None
    if args.original_files:
        original_files = [
            (REPO_ROOT / f).resolve() if not f.is_absolute() else f.resolve()
            for f in args.original_files
        ]

    results, processed_patterns = compare_all(base_path, original_files)

    # Collect containment edges from all YAML files
    all_yml_files: list[Path] = []
    originals = find_originals(base_path, original_files)
    all_yml_files.extend(originals)
    all_yml_files.extend(find_all_yml(base_path))
    containment_edges = _collect_containment_edges_from_files(all_yml_files)

    # Write containment edges
    if containment_edges:
        try:
            edge_count = write_containment_edges(containment_edges)
            if edge_count > 0:
                print(f"Wrote {edge_count} containment edge(s) to {KNOWLEDGE_DIR_NAME}/graph/")
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    patterns_with_differences: set[str] = set()
    for source_path in results:
        output_path = _get_compare_output_path(source_path)
        patterns_with_differences.add(output_path.stem)

    deleted = _delete_stale_comparison_csvs(processed_patterns, patterns_with_differences)
    if deleted > 0:
        print(f"Deleted {deleted} stale CSV file(s) with no current differences.")

    if results:
        count = write_compare_files(results)
        print(f"Wrote {count} CSV file(s) to {KNOWLEDGE_DIR_NAME}/comparisons/")
        return 1

    print("No differences found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
