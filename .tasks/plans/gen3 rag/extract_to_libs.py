#!/usr/bin/env python3
"""
Extract missing content from plan.md to library files based on library_map.json.
"""

import re
import json
from pathlib import Path


def get_section_content(lines: list[str], start_idx: int) -> str:
    """Extract section content from start until next header of same/higher level."""
    if start_idx >= len(lines):
        return ""

    first_line = lines[start_idx]
    match = re.match(r'^(#+)', first_line)
    if not match:
        return first_line

    level = len(match.group(1))
    content_lines = [first_line]

    for i in range(start_idx + 1, len(lines)):
        line = lines[i]
        m = re.match(r'^(#+)\s', line)
        if m and len(m.group(1)) <= level:
            break
        content_lines.append(line)

    return '\n'.join(line.rstrip() for line in content_lines)


def find_header_line(lines: list[str], element: str) -> int:
    """Find the line number of an element header in plan.md."""
    for i, line in enumerate(lines):
        # Match headers
        if re.match(r'^#{2,3}\s', line):
            header_text = re.sub(r'^#+\s+', '', line).strip()
            if header_text == element or element in header_text:
                return i
        # Match bold items like **G22 ...**
        if line.strip().startswith('**') and element in line:
            return i
    return -1


def get_existing_sections(lib_content: str) -> set[str]:
    """Get headers already in a library file."""
    sections = set()
    for line in lib_content.split('\n'):
        if re.match(r'^#{2,3}\s', line):
            header_text = re.sub(r'^#+\s+', '', line).strip()
            sections.add(header_text)
        elif line.strip().startswith('**'):
            match = re.match(r'^\*\*(.+?)\*\*', line.strip())
            if match:
                sections.add(match.group(1))
    return sections


def main():
    base = Path(__file__).parent
    plan_path = base / "plan.md"
    libs_dir = base / "libraries"
    map_path = base / "library_map.json"

    # Load plan.md
    plan_content = plan_path.read_text(encoding='utf-8')
    plan_lines = plan_content.split('\n')

    # Load library map
    with open(map_path) as f:
        lib_map = json.load(f)

    by_library = lib_map["by_library"]

    print("Extracting missing content to libraries...")
    print("=" * 60)

    total_added = 0

    for lib_name, elements in sorted(by_library.items()):
        lib_file = libs_dir / f"{lib_name}.md"

        if not lib_file.exists():
            print(f"\n{lib_name}: Creating new library file")
            lib_content = f"# {lib_name.title()} Library\n\n---\n\n"
        else:
            lib_content = lib_file.read_text(encoding='utf-8')

        existing = get_existing_sections(lib_content)
        added = 0

        for elem_info in elements:
            element = elem_info["element"]
            line_num = elem_info["line_num"]

            # Check if already in library
            found = element in existing
            if not found:
                for ex in existing:
                    if element in ex or ex in element:
                        found = True
                        break

            if found:
                continue

            # Find in plan.md and extract content
            plan_idx = line_num - 1  # Convert to 0-indexed
            if plan_idx >= len(plan_lines):
                continue

            section = get_section_content(plan_lines, plan_idx)
            if not section or len(section) < 10:
                continue

            # Append to library
            lib_content = lib_content.rstrip() + "\n\n---\n\n" + section + "\n"
            added += 1

        if added > 0:
            lib_file.write_text(lib_content, encoding='utf-8')
            print(f"{lib_name}: Added {added} sections")
            total_added += added
        else:
            print(f"{lib_name}: No new sections")

    print("\n" + "=" * 60)
    print(f"Total sections added: {total_added}")


if __name__ == "__main__":
    main()
