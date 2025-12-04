#!/usr/bin/env python3
"""Apply YAML naturalization transformations to documentation files.

Transformations:
1. Remove all 'type:' fields
2. Rename 'text:' to semantic field based on type (rule:, note:, anti_pattern:, pattern:, reference:)
3. Rename 'items:' to semantic collection name (rules:, notes:, anti_patterns:, patterns:, references:)
4. Keep items: if mixed content types
"""

import re
from collections import Counter
from pathlib import Path


def naturalize_yaml_file(file_path: Path) -> dict[str, int]:
    """Apply naturalization transformations to a YAML file."""
    content = file_path.read_text()
    original_content = content

    stats = {"types_removed": 0, "fields_renamed": 0, "collections_renamed": 0}

    # First pass: Analyze section content types to determine if we should rename items:
    for section_match in re.finditer(
        r"( +)- id: [^\n]+\n(?:.*?(?=\n\1- id:|\n(?!\1  )|\Z))", content, re.DOTALL
    ):
        section_text = section_match.group(0)
        indent = section_match.group(1)

        # Find items: block in this section
        items_match = re.search(
            rf"{indent}  (items|rules|notes|patterns|anti_patterns|references):\n((?:{indent}    .*\n?)*)",
            section_text,
        )
        if not items_match:
            continue

        current_field_name = items_match.group(1)
        items_block = items_match.group(2)

        # Skip if already renamed
        if current_field_name != "items":
            continue

        # Count types in this items block
        type_counts = Counter(re.findall(r"type: (\w+)", items_block))

        # Determine if we should rename items: to a semantic collection
        if len(type_counts) == 1:
            # Single type - rename to plural semantic name
            single_type = list(type_counts.keys())[0]
            semantic_collection = {
                "rule": "rules",
                "note": "notes",
                "pattern": "patterns",
                "anti_pattern": "anti_patterns",
                "reference": "references",
                "warning": "warnings",
            }.get(single_type, "items")

            if semantic_collection != "items":
                # Rename items: to semantic collection
                old_items_line = f"{indent}  items:\n"
                new_items_line = f"{indent}  {semantic_collection}:\n"
                content = content.replace(
                    section_text, section_text.replace(old_items_line, new_items_line, 1)
                )
                stats["collections_renamed"] += 1

    # Second pass: Transform type: text: pairs to semantic fields
    # Handle items that may have title: between type: and text:
    def replace_type_text_with_title(match):
        full_indent = match.group(1)
        item_id = match.group(2)
        type_value = match.group(3)
        title_part = match.group(4)  # May be empty
        text_content = match.group(5)

        semantic_field = {
            "rule": "rule",
            "note": "note",
            "pattern": "pattern",
            "anti_pattern": "anti_pattern",
            "reference": "reference",
            "warning": "warning",
        }.get(type_value, "text")

        stats["types_removed"] += 1
        if semantic_field != "text":
            stats["fields_renamed"] += 1

        result = f"{full_indent}- id: {item_id}\n"
        if title_part:
            result += title_part
        result += f"{full_indent}  {semantic_field}: {text_content}"
        return result

    # Pattern to match: "- id: X\n  type: Y\n  [title: T\n]  text: Z"
    content = re.sub(
        r"(\s+)- id: ([^\n]+)\n\1  type: (\w+)\n(\1  title: [^\n]+\n)?\1  text: (.+)",
        replace_type_text_with_title,
        content,
    )

    if content != original_content:
        file_path.write_text(content)
        return stats
    return {"types_removed": 0, "fields_renamed": 0, "collections_renamed": 0}


def main():
    """Process all unprocessed YAML files."""
    processed_files = {
        "docs/development/general/general.rest.api-patterns.yml",
        "docs/development/project/project.fastapi.middleware-patterns.yml",
        "docs/development/project/project.python.architectural-patterns.yml",
        "docs/development/project/project.fastapi.exception-patterns.yml",
        "docs/development/project/project.python.settings-patterns.yml",
        "docs/development/project/project.fastapi.router-patterns.yml",
        "docs/development/project/project.python.repository-patterns.yml",
        "docs/processes/information-migration.yml",
        "docs/development/project/project.fastapi.factory-patterns.yml",
        "docs/development/project/project.fastapi.dependency-patterns.yml",
        "docs/development/project/project.python.connection-pooling-patterns.yml",
        "docs/development/project/project.python.service-patterns.yml",
        "docs/processes/fact-migration.yml",
        "docs/development/project/project.python.dependency-patterns.yml",
        "docs/development/project/project.python.middleware-patterns.yml",
        "docs/development/project/project.python.exception-patterns.yml",
        "docs/development/project/project.fastapi.api-patterns.yml",
    }

    repo_root = Path("/mnt/c/Users/xteam/IdeaProjects/ai-workflow")
    docs_dir = repo_root / "docs"

    # Find all YAML files
    yaml_files = list(docs_dir.rglob("*.yml"))

    results = []
    for yaml_file in sorted(yaml_files):
        rel_path = str(yaml_file.relative_to(repo_root))

        if rel_path in processed_files:
            continue

        if (
            "plans" in rel_path
            or "MODULE-DEFINITIONS" in rel_path
            or "domain-definitions" in rel_path
        ):
            continue

        stats = naturalize_yaml_file(yaml_file)
        if sum(stats.values()) > 0:
            results.append((rel_path, stats))
            print(
                f"{rel_path}: removed {stats['types_removed']} types, "
                f"renamed {stats['fields_renamed']} fields, "
                f"renamed {stats['collections_renamed']} collections"
            )

    print(f"\nProcessed {len(results)} files")


if __name__ == "__main__":
    main()
