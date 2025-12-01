"""Rebuild GENERAL and PROJECT YAML files from a breakdown table.

This module automates the file rebuilding step of the granular ID breakdown
process. It parses a markdown breakdown table to extract classifications,
then rebuilds GENERAL and PROJECT YAML files with appropriate content.

For MIXED→split items, the module supports explicit per-ID text variants via:
1. Additional columns in the breakdown table (GENERAL Text, PROJECT Text)
2. An optional companion mapping file (--variants-file)

When explicit variants are provided, they are used directly. Otherwise,
regex-based stripping is applied as a fallback for GENERAL text.

Usage:
    uv run rebuild-from-breakdown --breakdown-table <breakdown.md> \
        --original-file <timestamped.yml> \
        --general-output <general.yml> \
        --project-output <project.yml> \
        [--variants-file <variants.yml>]

Args:
    --breakdown-table: Path to the markdown breakdown table.
    --original-file: Path to the timestamped original YAML file.
    --general-output: Path for the rebuilt GENERAL YAML file.
    --project-output: Path for the rebuilt PROJECT YAML file.
    --variants-file: Optional YAML file with explicit GENERAL/PROJECT text variants.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, TypedDict

import yaml

from scripts.compare_yaml_docs import YamlValue, parse_yaml_file
from scripts.utils import REPO_ROOT

Classification = Literal["GENERAL", "PROJECT", "MIXED→split", "PARK"]


class ClassificationEntry(TypedDict, total=False):
    """Classification entry with optional explicit text variants."""

    classification: Classification
    general_text: str | None  # Explicit GENERAL text variant for MIXED→split
    project_text: str | None  # Explicit PROJECT text variant for MIXED→split


# PROJECT-related patterns to strip from GENERAL text
PROJECT_PATTERNS = [
    r"\s*in\s+app/[^\s,;.]+",
    r"\s*via\s+app/[^\s,;.]+",
    r"\s*using\s+app/[^\s,;.]+",
    r"\s*from\s+app/[^\s,;.]+",
    r"\s*\(app/[^)]+\)",
    r"\s*FastAPI\s+",
    r"\s*Pydantic\s+",
    r"\s*create_app\s*",
    r"\s*response_model\s*",
    r"\s*include_in_schema\s*=\s*\w+",
    r"\s*ORJSONResponse\s*",
]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for file rebuilding.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Rebuild GENERAL and PROJECT YAML files from a breakdown table.",
    )
    parser.add_argument(
        "--breakdown-table",
        type=Path,
        required=True,
        help="Path to the markdown breakdown table.",
    )
    parser.add_argument(
        "--original-file",
        type=Path,
        required=True,
        help="Path to the timestamped original YAML file.",
    )
    parser.add_argument(
        "--general-output",
        type=Path,
        required=True,
        help="Path for the rebuilt GENERAL YAML file.",
    )
    parser.add_argument(
        "--project-output",
        type=Path,
        required=True,
        help="Path for the rebuilt PROJECT YAML file.",
    )
    parser.add_argument(
        "--variants-file",
        type=Path,
        help="Optional YAML file with explicit GENERAL/PROJECT text variants per ID.",
    )
    return parser.parse_args(argv)


def _parse_table_line(line: str) -> list[str] | None:
    """Parse a markdown table line by splitting on pipe characters.

    Uses tolerant parsing that splits on `|`, trims whitespace, and ignores
    leading/trailing empty entries from the pipe delimiters.

    Args:
        line: A line from the markdown file.

    Returns:
        List of column values if valid table row, None otherwise.
    """
    # Must contain at least one pipe to be a table row
    if "|" not in line:
        return None

    # Split on pipe and strip whitespace from each part
    parts = [p.strip() for p in line.split("|")]

    # Remove empty first and last entries caused by leading/trailing pipes
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]

    return parts if parts else None


def _is_separator_row(columns: list[str]) -> bool:
    """Check if a row is a markdown table separator (contains only dashes)."""
    return all(col.replace("-", "").replace(":", "").strip() == "" for col in columns)


def parse_breakdown_table(table_path: Path) -> dict[str, ClassificationEntry]:
    """Parse markdown table to extract classifications and optional text variants per ID.

    Supports two table formats:
    1. Basic (5 columns): | ID | Original Text Summary | Classification | Rationale |
       Target |
    2. Extended (7 columns): | ID | Original Text | Classification | Rationale |
       Target | GENERAL Text | PROJECT Text |

    Uses tolerant parsing that splits on `|` rather than strict regex matching.

    Args:
        table_path: Path to the markdown breakdown table.

    Returns:
        Dictionary mapping element IDs to ClassificationEntry with classification
        and optional explicit text variants.
    """
    content = table_path.read_text(encoding="utf-8")
    classifications: dict[str, ClassificationEntry] = {}

    parsed_count = 0
    skipped_count = 0
    header_indices: dict[str, int] = {}

    for line_num, line in enumerate(content.split("\n"), 1):
        columns = _parse_table_line(line)

        if columns is None:
            continue

        # Need at least 5 columns for basic format
        if len(columns) < 5:
            # Check if it looks like a table row but has wrong column count
            if "|" in line and not line.strip().startswith("#"):
                skipped_count += 1
                print(
                    f"Warning: Line {line_num} looks like a table row but has "
                    f"{len(columns)} columns (expected >= 5), skipping.",
                    file=sys.stderr,
                )
            continue

        # Check for separator row
        if _is_separator_row(columns):
            continue

        # Check for header row and capture column indices
        if columns[0].upper() == "ID" or columns[0] == "ID":
            # Map column names to indices for flexible parsing
            for idx, col_name in enumerate(columns):
                header_indices[col_name.upper().strip()] = idx
            continue

        # Skip rows where classification column contains header text
        classification_idx = header_indices.get("CLASSIFICATION", 2)
        if classification_idx < len(columns):
            classification = columns[classification_idx].strip()
            if classification.upper() in ("CLASSIFICATION", ""):
                continue
        else:
            continue

        # Extract element ID
        id_idx = header_indices.get("ID", 0)
        element_id = columns[id_idx].strip() if id_idx < len(columns) else ""

        if not element_id:
            continue

        # Handle structural elements with parentheses prefix
        # e.g., "(table) http_method_defaults" -> "http_method_defaults"
        if element_id.startswith("("):
            paren_match = re.match(r"^\([^)]+\)\s*(.+)$", element_id)
            if paren_match:
                element_id = paren_match.group(1).strip()

        # Validate classification
        valid_classifications = ("GENERAL", "PROJECT", "MIXED→split", "PARK")
        if classification not in valid_classifications:
            skipped_count += 1
            continue

        # Create entry with classification
        entry: ClassificationEntry = {
            "classification": classification,  # type: ignore[typeddict-item]
            "general_text": None,
            "project_text": None,
        }

        # Check for extended format with explicit text variants
        general_text_idx = header_indices.get("GENERAL TEXT")
        project_text_idx = header_indices.get("PROJECT TEXT")

        if general_text_idx is not None and general_text_idx < len(columns):
            general_text = columns[general_text_idx].strip()
            if general_text and general_text != "-":
                entry["general_text"] = general_text

        if project_text_idx is not None and project_text_idx < len(columns):
            project_text = columns[project_text_idx].strip()
            if project_text and project_text != "-":
                entry["project_text"] = project_text

        classifications[element_id] = entry
        parsed_count += 1

    if skipped_count > 0:
        print(
            f"Note: Parsed {parsed_count} rows, skipped {skipped_count} malformed rows.",
            file=sys.stderr,
        )

    return classifications


def load_variants_file(variants_path: Path) -> dict[str, ClassificationEntry]:
    """Load explicit text variants from a companion YAML file.

    The variants file should have the structure:
    ```yaml
    element_id:
      general_text: "Protocol-only text..."
      project_text: "Implementation-specific text..."
    another_id:
      general_text: "..."
      project_text: "..."
    ```

    Args:
        variants_path: Path to the variants YAML file.

    Returns:
        Dictionary mapping element IDs to their text variants.
    """
    if not variants_path.exists():
        return {}

    try:
        content = variants_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
    except Exception as exc:
        print(f"Warning: Failed to load variants file: {exc}", file=sys.stderr)
        return {}

    if not isinstance(data, dict):
        return {}

    variants: dict[str, ClassificationEntry] = {}
    for element_id, variant_data in data.items():
        if not isinstance(element_id, str) or not isinstance(variant_data, dict):
            continue

        entry: ClassificationEntry = {
            "classification": "MIXED→split",  # Variants imply MIXED→split
            "general_text": None,
            "project_text": None,
        }

        if "general_text" in variant_data and isinstance(variant_data["general_text"], str):
            entry["general_text"] = variant_data["general_text"]
        if "project_text" in variant_data and isinstance(variant_data["project_text"], str):
            entry["project_text"] = variant_data["project_text"]

        if entry["general_text"] or entry["project_text"]:
            variants[element_id] = entry

    return variants


def merge_variants(
    classifications: dict[str, ClassificationEntry],
    variants: dict[str, ClassificationEntry],
) -> dict[str, ClassificationEntry]:
    """Merge explicit variants from variants file into classifications.

    Variants from the variants file take precedence over table-parsed variants.

    Args:
        classifications: Classifications parsed from breakdown table.
        variants: Explicit variants from variants file.

    Returns:
        Merged classifications with variants applied.
    """
    for element_id, variant_entry in variants.items():
        if element_id in classifications:
            # Update existing entry with variant texts
            if variant_entry.get("general_text"):
                classifications[element_id]["general_text"] = variant_entry["general_text"]
            if variant_entry.get("project_text"):
                classifications[element_id]["project_text"] = variant_entry["project_text"]
        else:
            # Add new entry if not in classifications
            classifications[element_id] = variant_entry

    return classifications


def strip_project_refs(text: str) -> str:
    """Strip PROJECT-specific references from text for GENERAL file.

    Args:
        text: Original text content.

    Returns:
        Text with PROJECT references removed.
    """
    result = text
    for pattern in PROJECT_PATTERNS:
        result = re.sub(pattern, " ", result, flags=re.IGNORECASE)

    # Clean up extra whitespace
    result = re.sub(r"\s+", " ", result).strip()

    return result


def _process_item(
    item: dict[str, YamlValue],
    classifications: dict[str, ClassificationEntry],
    target: Literal["GENERAL", "PROJECT"],
) -> dict[str, YamlValue] | None:
    """Process a single item based on its classification.

    For MIXED→split items, uses explicit text variants when available.
    Falls back to regex-based stripping for GENERAL text when no explicit
    variant is provided.

    Args:
        item: The YAML item to process.
        classifications: Classification mapping with optional text variants.
        target: Target file type (GENERAL or PROJECT).

    Returns:
        Processed item or None if it should be excluded.
    """
    element_id = item.get("id")
    if not isinstance(element_id, str):
        return None

    entry = classifications.get(element_id)

    # If no classification found, include in both (conservative)
    if entry is None:
        return dict(item)

    classification = entry.get("classification")

    # PARK items are excluded from both
    if classification == "PARK":
        return None

    # GENERAL items only go to GENERAL file
    if classification == "GENERAL" and target != "GENERAL":
        return None

    # PROJECT items only go to PROJECT file
    if classification == "PROJECT" and target != "PROJECT":
        return None

    # MIXED→split items go to both with text transformation
    if classification == "MIXED→split":
        processed = dict(item)

        if target == "GENERAL":
            # Use explicit GENERAL variant if available, otherwise strip PROJECT refs
            explicit_general = entry.get("general_text")
            if explicit_general:
                # Apply explicit variant to the primary text field
                for field in ("text", "description", "summary"):
                    if field in processed and isinstance(processed[field], str):
                        processed[field] = explicit_general
                        break  # Only replace the first text field found
            else:
                # Fallback: strip PROJECT references from text fields
                for field in ("text", "description", "summary"):
                    if field in processed and isinstance(processed[field], str):
                        processed[field] = strip_project_refs(processed[field])  # type: ignore[arg-type]

        elif target == "PROJECT":
            # Use explicit PROJECT variant if available
            explicit_project = entry.get("project_text")
            if explicit_project:
                for field in ("text", "description", "summary"):
                    if field in processed and isinstance(processed[field], str):
                        processed[field] = explicit_project
                        break  # Only replace the first text field found
            # If no explicit PROJECT variant, keep original text

        return processed

    return dict(item)


def _process_items_list(
    items: list[YamlValue],
    classifications: dict[str, ClassificationEntry],
    target: Literal["GENERAL", "PROJECT"],
) -> list[dict[str, YamlValue]]:
    """Process a list of items based on classifications.

    Args:
        items: List of YAML items.
        classifications: Classification mapping with optional text variants.
        target: Target file type.

    Returns:
        Filtered and processed list of items.
    """
    result: list[dict[str, YamlValue]] = []
    for item in items:
        if isinstance(item, dict):
            processed = _process_item(item, classifications, target)
            if processed is not None:
                result.append(processed)
    return result


def _process_section(
    section: dict[str, YamlValue],
    classifications: dict[str, ClassificationEntry],
    target: Literal["GENERAL", "PROJECT"],
) -> dict[str, YamlValue] | None:
    """Process a section based on item classifications.

    Args:
        section: The YAML section to process.
        classifications: Classification mapping with optional text variants.
        target: Target file type.

    Returns:
        Processed section or None if empty.
    """
    result: dict[str, YamlValue] = {}

    for key, value in section.items():
        if key == "items" and isinstance(value, list):
            processed_items = _process_items_list(value, classifications, target)
            if processed_items:
                result[key] = processed_items  # type: ignore[assignment]
        elif key in ("id", "title", "description", "summary"):
            result[key] = value
        else:
            # Handle structural fields based on classification
            field_entry = classifications.get(key)
            field_classification = field_entry.get("classification") if field_entry else None
            if field_classification == "PARK":
                continue
            if field_classification == "PROJECT" and target == "GENERAL":
                continue
            if field_classification == "GENERAL" and target == "PROJECT":
                continue
            result[key] = value

    # Only return section if it has items or is meaningful
    if result.get("items"):
        return result
    if not any(key for key in result if key not in ("id", "title", "description", "summary")):
        return None
    return result


def rebuild_file(
    original_data: dict[str, YamlValue],
    classifications: dict[str, ClassificationEntry],
    target: Literal["GENERAL", "PROJECT"],
    output_path: Path,
) -> dict[str, YamlValue]:
    """Rebuild a YAML file based on classifications.

    Args:
        original_data: Original YAML data structure.
        classifications: Classification mapping with optional text variants.
        target: Target file type (GENERAL or PROJECT).
        output_path: Output path for doc_id derivation.

    Returns:
        Rebuilt YAML data structure.
    """
    result: dict[str, YamlValue] = {}

    # Update metadata
    original_doc_id = original_data.get("doc_id", "")
    if isinstance(original_doc_id, str):
        # Derive new doc_id based on target
        # e.g., "project.rest.api-patterns" -> "general.rest.api-patterns" or vice versa
        if target == "GENERAL":
            new_doc_id = re.sub(r"^project\.", "general.", original_doc_id)
            if new_doc_id == original_doc_id:
                new_doc_id = f"general.{original_doc_id}"
        else:
            new_doc_id = re.sub(r"^general\.", "project.", original_doc_id)
            if new_doc_id == original_doc_id:
                new_doc_id = f"project.{original_doc_id}"
        result["doc_id"] = new_doc_id
    else:
        result["doc_id"] = output_path.stem

    # Copy and update scope
    if target == "GENERAL":
        result["scope"] = "Protocol-level REST/HTTP rules independent of framework or language"
    else:
        result["scope"] = "FastAPI/Pydantic-specific implementation wiring and app/* references"

    # Handle primary_runtime_references
    if target == "PROJECT":
        # Keep or add runtime references
        refs = original_data.get("primary_runtime_references", [])
        if isinstance(refs, list):
            result["primary_runtime_references"] = refs
        else:
            result["primary_runtime_references"] = []
    # For GENERAL, omit primary_runtime_references

    # Process sections
    sections = original_data.get("sections", [])
    if isinstance(sections, list):
        processed_sections: list[dict[str, YamlValue]] = []
        for section in sections:
            if isinstance(section, dict):
                processed = _process_section(section, classifications, target)
                if processed is not None:
                    processed_sections.append(processed)
        if processed_sections:
            result["sections"] = processed_sections  # type: ignore[assignment]

    # Copy other top-level fields that aren't sections or metadata
    for key, value in original_data.items():
        if key in result:
            continue
        if key in ("doc_id", "scope", "primary_runtime_references", "sections"):
            continue
        # Check if this field should be included based on classification
        field_entry = classifications.get(key)
        field_classification = field_entry.get("classification") if field_entry else None
        if field_classification == "PARK":
            continue
        if field_classification == "PROJECT" and target == "GENERAL":
            continue
        if field_classification == "GENERAL" and target == "PROJECT":
            continue
        result[key] = value

    return result


def write_yaml_file(data: dict[str, YamlValue], output_path: Path) -> None:
    """Write YAML data to a file with proper formatting.

    Args:
        data: YAML data to write.
        output_path: Destination file path.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            data,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=100,
        )


def main() -> int:
    """Run file rebuilding from breakdown table.

    Returns:
        0 on success, 1 on error.
    """
    args = parse_args()

    # Resolve paths
    breakdown_table = args.breakdown_table
    if not breakdown_table.is_absolute():
        breakdown_table = (REPO_ROOT / breakdown_table).resolve()

    original_file = args.original_file
    if not original_file.is_absolute():
        original_file = (REPO_ROOT / original_file).resolve()

    general_output = args.general_output
    if not general_output.is_absolute():
        general_output = (REPO_ROOT / general_output).resolve()

    project_output = args.project_output
    if not project_output.is_absolute():
        project_output = (REPO_ROOT / project_output).resolve()

    variants_file: Path | None = None
    if args.variants_file:
        variants_file = args.variants_file
        if not variants_file.is_absolute():
            variants_file = (REPO_ROOT / variants_file).resolve()

    # Validate inputs exist
    if not breakdown_table.exists():
        print(f"Error: Breakdown table not found: {breakdown_table}", file=sys.stderr)
        return 1

    if not original_file.exists():
        print(f"Error: Original file not found: {original_file}", file=sys.stderr)
        return 1

    # Parse breakdown table
    classifications = parse_breakdown_table(breakdown_table)
    if not classifications:
        print("Warning: No classifications found in breakdown table.", file=sys.stderr)

    print(f"Loaded {len(classifications)} classifications from breakdown table.")

    # Load and merge variants file if provided
    if variants_file and variants_file.exists():
        variants = load_variants_file(variants_file)
        if variants:
            classifications = merge_variants(classifications, variants)
            print(f"Merged {len(variants)} explicit text variants from variants file.")

    # Count explicit variants
    explicit_variant_count = sum(
        1
        for entry in classifications.values()
        if entry.get("general_text") or entry.get("project_text")
    )
    if explicit_variant_count > 0:
        print(f"Using {explicit_variant_count} explicit text variant(s) for MIXED→split items.")

    # Parse original YAML
    try:
        original_data = parse_yaml_file(original_file)
    except Exception as exc:
        print(f"Error parsing YAML file: {exc}", file=sys.stderr)
        return 1

    if not isinstance(original_data, dict):
        print("Error: Expected YAML file to contain a dictionary at the root.", file=sys.stderr)
        return 1

    # Rebuild GENERAL file
    general_data = rebuild_file(original_data, classifications, "GENERAL", general_output)
    write_yaml_file(general_data, general_output)
    print(f"Wrote GENERAL file: {general_output}")

    # Rebuild PROJECT file
    project_data = rebuild_file(original_data, classifications, "PROJECT", project_output)
    write_yaml_file(project_data, project_output)
    print(f"Wrote PROJECT file: {project_output}")

    # Summary
    general_count = sum(
        1
        for entry in classifications.values()
        if entry.get("classification") in ("GENERAL", "MIXED→split")
    )
    project_count = sum(
        1
        for entry in classifications.values()
        if entry.get("classification") in ("PROJECT", "MIXED→split")
    )
    mixed_count = sum(
        1 for entry in classifications.values() if entry.get("classification") == "MIXED→split"
    )
    parked_count = sum(
        1 for entry in classifications.values() if entry.get("classification") == "PARK"
    )

    print("\nSummary:")
    print(f"  GENERAL items: {general_count}")
    print(f"  PROJECT items: {project_count}")
    print(f"  MIXED→split items: {mixed_count}")
    print(f"  PARK items (excluded): {parked_count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
