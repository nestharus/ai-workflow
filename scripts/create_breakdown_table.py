"""Generate ID breakdown tables from timestamped original YAML files.

This module automates the creation of classification tables for the granular
ID breakdown process. It parses YAML files, extracts all IDs with their text
content, and generates markdown tables with classifications.

Usage:
    uv run create-breakdown --original-file <timestamped.yml> --output <breakdown.md>

Args:
    --original-file: Path to the timestamped original YAML file.
    --output: Path for the generated markdown breakdown table.
    --auto-classify: Optional flag to apply rule-based classification.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, TypedDict

from scripts.compare_yaml_docs import (
    TEXT_FIELDS,
    YamlValue,
    parse_yaml_file,
)
from scripts.utils import REPO_ROOT

# Keywords indicating PROJECT classification
PROJECT_KEYWORDS = frozenset({
    "app/",
    "FastAPI",
    "fastapi",
    "Pydantic",
    "pydantic",
    "create_app",
    "uvicorn",
    "ORJSONResponse",
    "response_model",
    "include_in_schema",
    "BaseModel",
    "ConfigDict",
    "Field(",
})

# Keywords indicating PARK classification (structural blocks, code samples)
PARK_KEYWORDS = frozenset({
    "sample_code",
    "type_hints",
    "code_example",
})

Classification = Literal["GENERAL", "PROJECT", "MIXED→split", "PARK"]


class IdEntry(TypedDict):
    """An extracted ID entry with metadata."""

    id: str
    text: str
    section: str
    element_type: str  # "item", "table", "block", "fields", "hints"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for breakdown table generation.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Generate ID breakdown tables from timestamped original YAML files.",
    )
    parser.add_argument(
        "--original-file",
        type=Path,
        required=True,
        help="Path to the timestamped original YAML file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path for the generated markdown breakdown table.",
    )
    parser.add_argument(
        "--auto-classify",
        action="store_true",
        help="Apply rule-based classification (default: leave empty for manual review).",
    )
    return parser.parse_args(argv)


def _extract_text_content(element: dict[str, YamlValue]) -> str:
    """Extract text content from a YAML element's text fields.

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


def _determine_element_type(key: str, value: YamlValue) -> str:
    """Determine the element type based on key name and value structure.

    Args:
        key: The key name in the YAML structure.
        value: The value associated with the key.

    Returns:
        Element type: "table", "fields", "hints", "block", or "item".
    """
    key_lower = key.lower()
    if "defaults" in key_lower or "table" in key_lower:
        return "table"
    if "fields" in key_lower:
        return "fields"
    if "hints" in key_lower or "type_hint" in key_lower:
        return "hints"
    if "sample" in key_lower or "code" in key_lower or "example" in key_lower:
        return "block"
    if isinstance(value, list):
        return "table"
    return "item"


def _has_explicit_id(value: YamlValue) -> bool:
    """Check if a value (dict or list) contains an explicit 'id' field.

    Args:
        value: The value to check.

    Returns:
        True if the value or any of its items has an explicit 'id' field.
    """
    if isinstance(value, dict):
        return "id" in value
    if isinstance(value, list):
        return any(isinstance(item, dict) and "id" in item for item in value)
    return False


def _extract_from_dict(
    data: dict[str, YamlValue],
    current_section: str,
    entries: list[IdEntry],
) -> None:
    """Recursively extract IDs from a dictionary structure.

    Synthetic IDs (e.g., "(table) http_method_defaults") are only created for
    structural elements that are otherwise anonymous in the YAML - i.e., when
    the element itself does not have an explicit 'id' field and contains no
    items with 'id' fields. This avoids duplicate entries for elements that
    will be captured via their explicit IDs.

    Args:
        data: Dictionary to extract from.
        current_section: Current section name for context.
        entries: List to append extracted entries to.
    """
    # Track IDs already recorded to avoid duplicates
    recorded_ids: set[str] = {entry["id"] for entry in entries}

    # Check if this dict has an id field
    if "id" in data:
        element_id = data["id"]
        if isinstance(element_id, str):
            text_content = _extract_text_content(data)
            entries.append(
                IdEntry(
                    id=element_id,
                    text=text_content,
                    section=current_section,
                    element_type="item",
                )
            )
            recorded_ids.add(element_id)

    # Check for structural elements (tables, fields, etc.)
    # Synthetic IDs are only created for structural groups that are otherwise
    # anonymous in the YAML - when they have no explicit 'id' field and their
    # contents don't have explicit IDs that will be captured separately.
    for key, value in data.items():
        if key in ("id", "text", "description", "summary", "title", "items", "sections"):
            continue

        element_type = _determine_element_type(key, value)
        if element_type in ("table", "fields", "hints", "block"):
            # Skip synthetic ID if:
            # 1. The value has an explicit 'id' field (will be captured directly)
            # 2. The key has already been recorded
            # 3. The value contains items with explicit IDs (will be captured via recursion)
            if _has_explicit_id(value):
                continue

            synthetic_id = f"({element_type}) {key}"
            if synthetic_id in recorded_ids or key in recorded_ids:
                continue

            # Extract a summary of the structural element
            if isinstance(value, list):
                summary = f"{len(value)} items"
            elif isinstance(value, dict):
                summary = f"{len(value)} fields"
            elif isinstance(value, str):
                summary = value[:50] + "..." if len(value) > 50 else value
            else:
                summary = str(value)[:50]

            entries.append(
                IdEntry(
                    id=synthetic_id,
                    text=summary,
                    section=current_section,
                    element_type=element_type,
                )
            )
            recorded_ids.add(synthetic_id)

    # Recurse into nested structures
    for key, value in data.items():
        if key == "sections":
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        section_id = item.get("id", current_section)
                        if isinstance(section_id, str):
                            _extract_from_dict(item, section_id, entries)
        elif key == "items":
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        _extract_from_dict(item, current_section, entries)
        elif isinstance(value, dict):
            _extract_from_dict(value, current_section, entries)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _extract_from_dict(item, current_section, entries)


def extract_all_ids(data: dict[str, YamlValue] | list[YamlValue]) -> list[IdEntry]:
    """Extract all IDs and their metadata from a YAML structure.

    Args:
        data: Parsed YAML data structure.

    Returns:
        List of IdEntry objects with extracted IDs and metadata.
    """
    entries: list[IdEntry] = []

    if isinstance(data, dict):
        # Get the document's top-level id if present
        doc_id = data.get("doc_id", data.get("id", "root"))
        if isinstance(doc_id, str):
            _extract_from_dict(data, doc_id, entries)
        else:
            _extract_from_dict(data, "root", entries)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                _extract_from_dict(item, "root", entries)

    return entries


def classify_id(entry: IdEntry) -> tuple[Classification, str]:
    """Apply rule-based classification to an ID entry.

    Args:
        entry: The ID entry to classify.

    Returns:
        Tuple of (classification, rationale).
    """
    text = entry["text"]
    element_id = entry["id"]

    # Check for PARK classification
    if entry["element_type"] in ("block", "hints"):
        return "PARK", "Structural block (code/type hints)"

    for keyword in PARK_KEYWORDS:
        if keyword in element_id.lower():
            return "PARK", f"Structural element ({keyword})"

    # Check for PROJECT-only keywords
    project_matches: list[str] = []
    for keyword in PROJECT_KEYWORDS:
        if keyword in text:
            project_matches.append(keyword)

    # Check for GENERAL indicators (no project references)
    has_project_refs = len(project_matches) > 0

    # Detect protocol-level content
    protocol_patterns = [
        r"\bHTTP\b",
        r"\bREST\b",
        r"\bAPI\b",
        r"\bGET\b",
        r"\bPOST\b",
        r"\bPUT\b",
        r"\bPATCH\b",
        r"\bDELETE\b",
        r"\bstatus\s*code",
        r"\b\d{3}\b",  # HTTP status codes
        r"/api/",
        r"Content-Type",
        r"Accept-Encoding",
        r"header",
        r"endpoint",
        r"resource",
        r"URL",
        r"path",
        r"versioning",
        r"deprecation",
    ]

    has_protocol_content = any(re.search(p, text, re.IGNORECASE) for p in protocol_patterns)

    if has_project_refs and has_protocol_content:
        return "MIXED→split", f"Both protocol and framework refs ({', '.join(project_matches[:2])})"
    if has_project_refs:
        return "PROJECT", f"Framework-specific ({', '.join(project_matches[:2])})"
    if has_protocol_content:
        return "GENERAL", "Pure protocol/principle rule"

    # Default to GENERAL for items without clear indicators
    return "GENERAL", "No framework references detected"


def truncate_text(text: str, max_length: int = 50) -> str:
    """Truncate text to a maximum length with ellipsis.

    Args:
        text: Text to truncate.
        max_length: Maximum length before truncation.

    Returns:
        Truncated text with ellipsis if needed.
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def generate_markdown_table(
    entries: list[IdEntry],
    original_file: Path,
    auto_classify: bool,
) -> str:
    """Generate markdown breakdown table from extracted entries.

    Args:
        entries: List of extracted ID entries.
        original_file: Path to the original YAML file.
        auto_classify: Whether to apply auto-classification.

    Returns:
        Formatted markdown string.
    """
    lines: list[str] = []

    # Header
    lines.append("# ID Breakdown Table")
    lines.append("")
    lines.append(
        f"This table classifies EVERY ID and element from the original timestamped file"
    )
    lines.append(f"`{original_file.as_posix()}`.")
    lines.append("")

    # Classification legend
    lines.append("### Classification Legend")
    lines.append("")
    lines.append("* **GENERAL**: Pure REST/HTTP protocol rules (no lang/framework/app references)")
    lines.append("* **PROJECT**: Concrete wiring with app/* paths, FastAPI/Pydantic specifics")
    lines.append("* **MIXED→split**: Original text contains both; split into GENERAL rule + PROJECT wiring")
    lines.append("* **PARK**: Content belongs in another module (e.g., general.python for Pydantic)")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Group entries by section
    sections: dict[str, list[IdEntry]] = {}
    for entry in entries:
        section = entry["section"]
        if section not in sections:
            sections[section] = []
        sections[section].append(entry)

    # Track classification counts
    counts: dict[Classification, int] = {
        "GENERAL": 0,
        "PROJECT": 0,
        "MIXED→split": 0,
        "PARK": 0,
    }

    # Generate tables for each section
    section_num = 1
    for section_name, section_entries in sections.items():
        lines.append(f"### Section {section_num}: {section_name}")
        lines.append("")
        lines.append("| ID | Original Text Summary | Classification | Rationale | Target |")
        lines.append("|----|----------------------|----------------|-----------|--------|")

        for entry in section_entries:
            entry_id = entry["id"]
            text_summary = truncate_text(entry["text"])

            if auto_classify:
                classification, rationale = classify_id(entry)
                counts[classification] += 1

                # Determine target based on classification
                if classification == "GENERAL":
                    target = "GENERAL"
                elif classification == "PROJECT":
                    target = "PROJECT"
                elif classification == "MIXED→split":
                    target = "Both"
                else:  # PARK
                    target = "N/A"
            else:
                classification = ""
                rationale = ""
                target = ""

            lines.append(f"| {entry_id} | {text_summary} | {classification} | {rationale} | {target} |")

        lines.append("")
        section_num += 1

    # Summary counts
    lines.append("---")
    lines.append("")
    lines.append("### Summary Counts")
    lines.append("")
    lines.append("| Classification | Count | Notes |")
    lines.append("|----------------|-------|-------|")

    if auto_classify:
        lines.append(
            f"| GENERAL only | {counts['GENERAL']} | Pure protocol/principle rules (only in GENERAL) |"
        )
        lines.append(
            f"| PROJECT only | {counts['PROJECT']} | App wiring, FastAPI/Pydantic specifics (only in PROJECT) |"
        )
        lines.append(
            f"| MIXED→split | {counts['MIXED→split']} | Split to both files with appropriate text variants |"
        )
        lines.append(
            f"| PARK | {counts['PARK']} | Structural blocks to be moved elsewhere |"
        )
    else:
        lines.append("| GENERAL only | - | Pure protocol/principle rules (only in GENERAL) |")
        lines.append("| PROJECT only | - | App wiring, FastAPI/Pydantic specifics (only in PROJECT) |")
        lines.append("| MIXED→split | - | Split to both files with appropriate text variants |")
        lines.append("| PARK | - | Structural blocks to be moved elsewhere |")

    lines.append("")
    total = len(entries)
    lines.append(f"**Total IDs: {total}**")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    """Run breakdown table generation.

    Returns:
        0 on success, 1 on error.
    """
    args = parse_args()

    # Resolve paths
    original_file = args.original_file
    if not original_file.is_absolute():
        original_file = (REPO_ROOT / original_file).resolve()
    else:
        original_file = original_file.resolve()

    output_path = args.output
    if not output_path.is_absolute():
        output_path = (REPO_ROOT / output_path).resolve()
    else:
        output_path = output_path.resolve()

    # Validate original file exists
    if not original_file.exists():
        print(f"Error: Original file not found: {original_file}", file=sys.stderr)
        return 1

    # Parse YAML and extract IDs
    try:
        data = parse_yaml_file(original_file)
    except Exception as exc:
        print(f"Error parsing YAML file: {exc}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        print("Error: Expected YAML file to contain a dictionary at the root.", file=sys.stderr)
        return 1

    entries = extract_all_ids(data)

    if not entries:
        print("Warning: No IDs found in the YAML file.", file=sys.stderr)

    # Generate relative path for display
    try:
        display_path = original_file.relative_to(REPO_ROOT)
    except ValueError:
        display_path = original_file

    # Generate markdown
    markdown = generate_markdown_table(entries, display_path, args.auto_classify)

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")

    print(f"Generated breakdown table with {len(entries)} IDs: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
