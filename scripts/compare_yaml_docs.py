"""Compare YAML documents by extracting IDs and their associated text content.

This module provides utilities for parsing YAML files and extracting ID-to-text
mappings, enabling comparison of document content across different versions or files.
It compares original YAML files with their split counterparts in subdirectories.

Outputs flattened CSV files to `.knowledge/comparisons/` with columns:
source_file, id, origin_type, original_text, split_file, split_text

Usage:
    uv run compare-yml-docs [--path <directory>]

Args:
    --path: Base directory containing original and split YAML files
            (default: docs/development/).
"""

import argparse
import csv
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, TypedDict

import yaml

from scripts.utils import REPO_ROOT

TEXT_FIELDS = ("text", "description", "summary", "title")
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
        Parsed argument namespace with path attribute.
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
    return parser.parse_args(argv)


class SplitEntry(TypedDict):
    """A split file's text content for a specific ID."""

    split_text: str
    source_file: str


class ComparisonEntry(TypedDict):
    """Comparison result for a single ID.

    The origin_type field indicates the source of this entry:
    - original: ID from an original.*.yml file with differing or missing split text
    - split_only: ID found in split files but not in the corresponding original
    - orphan: ID from a file in a subdirectory with no corresponding original file
    """

    source_file: str
    id: str
    source_text: str
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


def _extract_text_content(element: dict[str, YamlValue]) -> str:
    """Extract text content from a YAML element's text fields.

    Checks text fields in priority order and concatenates all non-empty
    values found.

    Args:
        element: A dictionary element from the parsed YAML structure.

    Returns:
        Concatenated text content from available text fields, or empty string.
    """
    text_parts: list[str] = []
    for field in TEXT_FIELDS:
        if field in element:
            value = element[field]
            if isinstance(value, str) and value.strip():
                text_parts.append(value.strip())
    return " | ".join(text_parts)


def extract_ids_and_text(
    data: YamlValue,
    parent_path: str = "",
) -> dict[str, str]:
    """Recursively extract IDs and their associated text from a YAML structure.

    Traverses the parsed YAML structure to find all elements with an 'id' field
    and extracts their text content from associated fields like 'text',
    'description', 'summary', or 'title'.

    Args:
        data: The parsed YAML structure (dict, list, or primitive).
        parent_path: Path string for debugging purposes (tracks traversal path).

    Returns:
        Dictionary mapping element IDs to their associated text content.
    """
    result: dict[str, str] = {}

    if isinstance(data, dict):
        if "id" in data:
            element_id = data["id"]
            if isinstance(element_id, str):
                text_content = _extract_text_content(data)
                result[element_id] = text_content

        for key, value in data.items():
            child_path = f"{parent_path}.{key}" if parent_path else key
            child_results = extract_ids_and_text(value, child_path)
            result.update(child_results)

    elif isinstance(data, list):
        for index, item in enumerate(data):
            child_path = f"{parent_path}[{index}]"
            child_results = extract_ids_and_text(item, child_path)
            result.update(child_results)

    return result


def find_originals(base_path: Path) -> list[Path]:
    """Find all original YAML files in the development directory.

    Original files are top-level files matching the pattern 'original.*.yml'.

    Args:
        base_path: Base directory to search for original files.

    Returns:
        Sorted list of paths to original YAML files.
    """
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


def pattern_from_path(path: Path) -> str:
    """Extract the pattern name from a YAML file path.

    For 'original.api-patterns.yml', returns 'api-patterns'.
    For 'python.api-patterns.yml', returns 'api-patterns'.

    Args:
        path: Path to a YAML file.

    Returns:
        The extracted pattern name.
    """
    name = path.stem
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


def get_ids_text(file_path: Path) -> dict[str, str]:
    """Extract IDs and text content from a YAML file.

    Args:
        file_path: Path to the YAML file.

    Returns:
        Dictionary mapping IDs to their text content.
    """
    data = parse_yaml_file(file_path)
    return extract_ids_and_text(data)


def aggregate_split_texts(
    split_map: dict[str, Path],
) -> dict[str, dict[str, str]]:
    """Aggregate text content from split files by ID.

    Collects text for each ID across all split files. Warns if the same ID
    has conflicting text in different split files.

    Args:
        split_map: Dictionary mapping subdirectory name to file path.

    Returns:
        Dictionary mapping ID to {relative_file_path: text_content}.
    """
    result: dict[str, dict[str, str]] = {}
    id_texts: dict[str, dict[str, str]] = {}

    for _, file_path in split_map.items():
        relative_path = file_path.relative_to(REPO_ROOT).as_posix()
        try:
            ids_text = get_ids_text(file_path)
        except Exception as exc:
            print(f"Warning: Failed to parse {relative_path}: {exc}", file=sys.stderr)
            continue

        for element_id, text in ids_text.items():
            if element_id not in result:
                result[element_id] = {}
                id_texts[element_id] = {}
            result[element_id][relative_path] = text
            id_texts[element_id][relative_path] = text

    for element_id, file_texts in id_texts.items():
        unique_texts = {t.strip() for t in file_texts.values()}
        if len(unique_texts) > 1:
            files = ", ".join(file_texts.keys())
            print(
                f"Warning: Conflicting text for ID '{element_id}' in: {files}",
                file=sys.stderr,
            )

    return result


def compare_original_to_splits(
    orig_path: Path,
    split_map: dict[str, Path],
) -> list[ComparisonEntry]:
    """Compare an original file to its split files.

    Performs bidirectional comparison:
    1. For each ID in the original, checks if any split has matching text.
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
        orig_ids = get_ids_text(orig_path)
    except Exception as exc:
        print(f"Warning: Failed to parse {orig_relative}: {exc}", file=sys.stderr)
        return entries

    split_texts = aggregate_split_texts(split_map)

    for element_id, orig_text in orig_ids.items():
        orig_text_stripped = orig_text.strip()
        split_data = split_texts.get(element_id, {})

        has_exact_match = any(text.strip() == orig_text_stripped for text in split_data.values())

        if not has_exact_match:
            splits: list[SplitEntry] = [
                SplitEntry(split_text=text, source_file=file_path)
                for file_path, text in split_data.items()
            ]
            entries.append(
                ComparisonEntry(
                    source_file=orig_relative,
                    id=element_id,
                    source_text=orig_text,
                    splits=splits,
                    origin_type="original",
                )
            )

    orig_id_set = set(orig_ids.keys())
    for element_id, file_texts in split_texts.items():
        if element_id not in orig_id_set:
            for file_path, text in file_texts.items():
                entries.append(
                    ComparisonEntry(
                        source_file=file_path,
                        id=element_id,
                        source_text=text,
                        splits=[],
                        origin_type="split_only",
                    )
                )

    return entries


def compare_all(base_path: Path) -> tuple[dict[str, CompareResult], set[str]]:
    """Compare all original files to their split files.

    Also handles orphan files in subdirectories that don't have a corresponding
    original file.

    Args:
        base_path: Base directory containing original and split YAML files.

    Returns:
        Tuple of (results dict, processed patterns set).
        Results dict maps original file path to comparison results.
        Processed patterns set contains all pattern names that were compared.
    """
    results: dict[str, CompareResult] = {}
    processed_patterns: set[str] = set()

    originals = find_originals(base_path)
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
            orphan_ids = get_ids_text(orphan_path)
        except Exception as exc:
            print(
                f"Warning: Failed to parse orphan {orphan_relative}: {exc}",
                file=sys.stderr,
            )
            continue

        orphan_entries: list[ComparisonEntry] = []
        for element_id, text in orphan_ids.items():
            orphan_entries.append(
                ComparisonEntry(
                    source_file=orphan_relative,
                    id=element_id,
                    source_text=text,
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


CSV_COLUMNS = ["source_file", "id", "origin_type", "original_text", "split_file", "split_text"]


def _flatten_entry_to_rows(entry: ComparisonEntry) -> list[dict[str, str]]:
    """Flatten a ComparisonEntry into CSV rows.

    For entries with splits, creates one row per split.
    For entries without splits, creates one row with empty split columns.

    Note: The `original_text` column is populated from `source_text` for all origin
    types. For `split_only` and `orphan` entries, this represents the text from the
    split or orphan file respectively, not from an original file. Query authors
    should be aware of this semantic when filtering by origin_type.

    Args:
        entry: The comparison entry to flatten.

    Returns:
        List of dictionaries representing CSV rows.
    """
    rows: list[dict[str, str]] = []
    # Note: original_text is populated from source_text for all origin types.
    # For "original" entries, this is text from the original file.
    # For "split_only" and "orphan" entries, this is text from the split/orphan file.
    base_row = {
        "source_file": entry["source_file"],
        "id": entry["id"],
        "origin_type": entry["origin_type"],
        "original_text": entry["source_text"],
    }

    if entry["splits"]:
        for split in entry["splits"]:
            row = {
                **base_row,
                "split_file": split["source_file"],
                "split_text": split["split_text"],
            }
            rows.append(row)
    else:
        row = {**base_row, "split_file": "", "split_text": ""}
        rows.append(row)

    return rows


def write_compare_files(results: dict[str, CompareResult]) -> int:
    """Write comparison results to CSV files in .knowledge/comparisons/.

    Creates one CSV file per pattern with flattened comparison entries.
    Each row represents a (source_file, id, split_file) combination.

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
            with output_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            files_written += 1
        except OSError as exc:
            print(
                f"Warning: Failed to write {output_path}: {exc}",
                file=sys.stderr,
            )

    return files_written


def _delete_stale_comparison_csvs(
    processed_patterns: set[str],
    patterns_with_differences: set[str],
) -> int:
    """Delete comparison CSVs for patterns that no longer have differences.

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

    for pattern in patterns_to_delete:
        csv_path = comparisons_dir / f"{pattern}.csv"
        if csv_path.exists():
            try:
                csv_path.unlink()
                deleted += 1
            except OSError as exc:
                print(
                    f"Warning: Failed to delete stale CSV {csv_path}: {exc}",
                    file=sys.stderr,
                )

    return deleted


def main() -> int:
    """Run comparison and write results to CSV files.

    Deletes stale comparison CSVs for patterns that no longer have differences,
    ensuring validation does not fail due to outdated data.

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

    results, processed_patterns = compare_all(base_path)

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
