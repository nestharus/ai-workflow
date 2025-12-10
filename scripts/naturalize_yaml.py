#!/usr/bin/env python3
"""Apply YAML naturalization transformations to documentation files.

Transformations:
1. Remove ALL type fields (type: text, rule, step, note, example, code, definition, anti_pattern)
2. Rename `text:` to semantic field names based on original type
3. Rename `items:` to semantic collection names (rules:, anti_patterns:, notes:)
4. Add missing IDs to objects without them
5. Keep `items:` if mixed content or unclear semantics
"""

import re
import sys
import uuid
from pathlib import Path
from typing import Any


def generate_id(context_prefix: str, index: int) -> str:
    """Generate a unique ID for an item."""
    return f"{context_prefix}.{index}"


def process_yaml_file(file_path: Path) -> tuple[bool, dict[str, Any]]:
    """Process a single YAML file.

    Returns:
        Tuple of (changed, stats) where stats contains:
        - types_removed: count of type fields removed
        - text_renamed: dict of {old_type: count}
        - items_renamed: count of items → semantic renames
        - ids_added: count of IDs added
    """
    content = file_path.read_text(encoding="utf-8")
    original = content
    lines_initial = content.split("\n")
    lines: list[str | None] = list(lines_initial)

    stats: dict[str, Any] = {
        "types_removed": 0,
        "text_renamed": {},
        "items_renamed": 0,
        "ids_added": 0,
    }

    result = []
    i = 0

    while i < len(lines):
        line = lines[i]
        if line is None:
            i += 1
            continue

        # Pattern 1: Remove type fields
        type_match = re.match(
            r"^(\s*)type:\s*(text|rule|step|note|example|code|definition|anti_pattern|pattern)\s*$",
            line,
        )
        if type_match:
            indent = type_match.group(1)
            type_value = type_match.group(2)

            # Look ahead to find the text: field  and rename it
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                if next_line is None:
                    j += 1
                    continue

                # Check if we've moved to a new item/section
                if re.match(r"^\s*-\s+", next_line) or not next_line.startswith(indent):
                    break

                # Look for text: field
                text_match = re.match(r"^(\s*)text:\s*(.*)$", next_line)
                if text_match:
                    text_indent = text_match.group(1)
                    text_value = text_match.group(2)

                    # Rename text: → semantic field based on type
                    new_field = type_value if type_value != "text" else "note"
                    result.append(f"{text_indent}{new_field}: {text_value}")

                    stats["text_renamed"][type_value] = stats["text_renamed"].get(type_value, 0) + 1

                    # Skip the type: line and continue from after text:
                    lines[j] = None  # Mark for removal
                    stats["types_removed"] += 1
                    i = j + 1
                    break

                j += 1
            else:
                # No text: field found, just remove type:
                stats["types_removed"] += 1
                i += 1

            continue

        # Pattern 2: Rename items: to semantic names
        items_match = re.match(r"^(\s*)items:\s*$", line)
        if items_match:
            indent = items_match.group(1)

            # Look back to find context (section title, category)
            context = None
            for k in range(i - 1, max(0, i - 10), -1):
                prev_line = lines[k]
                if prev_line is None:
                    continue
                category_match = re.match(r"^\s*category:\s*(.+)$", prev_line)
                if category_match:
                    context = category_match.group(1).strip()
                    break
                title_match = re.match(r"^\s*title:\s*(.+)$", prev_line)
                if title_match:
                    context = title_match.group(1).strip().lower()
                    break

            # Determine semantic name
            semantic_name = None
            if context:
                if "anti" in context.lower() or "warning" in context.lower():
                    semantic_name = "anti_patterns"
                elif "rule" in context.lower() or "standard" in context.lower():
                    semantic_name = "rules"
                elif "note" in context.lower():
                    semantic_name = "notes"
                elif "step" in context.lower():
                    semantic_name = "steps"
                elif "example" in context.lower():
                    semantic_name = "examples"

            if semantic_name:
                result.append(f"{indent}{semantic_name}:")
                stats["items_renamed"] += 1
                i += 1
                continue

        # Pattern 3: Add missing IDs
        item_start_match = re.match(r"^(\s*)-\s+(?!id:)(\w+):\s*(.*)$", line)
        if item_start_match:
            indent = item_start_match.group(1)

            # Check if the next line has an id field
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                if next_line is not None and not re.match(r"^\s*id:\s*\S+", next_line):
                    # No ID found, add one
                    # Try to find parent section ID
                    parent_id = "item"
                    for k in range(i - 1, max(0, i - 20), -1):
                        prev_line = lines[k]
                        if prev_line is not None:
                            id_match = re.match(r"^\s*id:\s*(\S+)", prev_line)
                            if id_match:
                                parent_id = id_match.group(1)
                                break

                    # Generate ID
                    new_id = f"{parent_id}.{uuid.uuid4().hex[:8]}"
                    result.append(line)
                    result.append(f"{indent}  id: {new_id}")
                    stats["ids_added"] += 1
                    i += 1
                    continue

        # Skip lines marked for removal (check if line wasn't modified)
        if line is not None and lines[i] is not None:
            result.append(line)
        elif line is not None:
            # Line was marked for removal, skip it
            pass

        i += 1

    new_content = "\n".join(result)

    if new_content != original:
        file_path.write_text(new_content, encoding="utf-8")
        return True, stats

    return False, stats


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python naturalize_yaml.py <file1.yml> [file2.yml ...]")
        return 1

    total_stats: dict[str, Any] = {
        "types_removed": 0,
        "text_renamed": {},
        "items_renamed": 0,
        "ids_added": 0,
        "files_changed": 0,
    }

    for file_path_str in sys.argv[1:]:
        file_path = Path(file_path_str)

        if not file_path.exists():
            print(f"Error: File not found: {file_path}", file=sys.stderr)
            continue

        try:
            changed, stats = process_yaml_file(file_path)

            if changed:
                total_stats["files_changed"] += 1
                total_stats["types_removed"] += stats["types_removed"]
                total_stats["items_renamed"] += stats["items_renamed"]
                total_stats["ids_added"] += stats["ids_added"]

                for type_val, count in stats["text_renamed"].items():
                    total_stats["text_renamed"][type_val] = (
                        total_stats["text_renamed"].get(type_val, 0) + count
                    )

                # Report per file
                print(f"\n## File: {file_path}")
                print(f"- Removed {stats['types_removed']} type fields")

                if stats["text_renamed"]:
                    text_renames = ", ".join(f"{k}: {v}" for k, v in stats["text_renamed"].items())
                    print(f"- Renamed text → semantic ({text_renames})")

                if stats["items_renamed"]:
                    print(f"- items → collection renames: {stats['items_renamed']}")

                if stats["ids_added"]:
                    print(f"- IDs added: {stats['ids_added']}")

        except Exception as e:
            print(f"Error processing {file_path}: {e}", file=sys.stderr)
            import traceback

            traceback.print_exc()

    print("\n\n=== Total Summary ===")
    print(f"Files changed: {total_stats['files_changed']}")
    print(f"Total type fields removed: {total_stats['types_removed']}")
    print(f"Total text→semantic renames: {sum(total_stats['text_renamed'].values())}")
    print(f"Total items→collection renames: {total_stats['items_renamed']}")
    print(f"Total IDs added: {total_stats['ids_added']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
