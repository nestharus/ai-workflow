#!/usr/bin/env python3
"""
Build a mapping of elements to their primary libraries and line numbers.
Output: library_map.json for use by sub-agents during extraction.
"""

import re
import json
from pathlib import Path


def parse_libs_md(content: str) -> dict:
    """Parse libs.md to get element -> {primary, related, line_num}"""
    elements = {}
    lines = content.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i]

        # Match element lines: - **Label**: description [patch] (L123)
        elem_match = re.match(r'^- \*\*(.+?)\*\*.*\(L(\d+)\)', line)
        if elem_match:
            element = elem_match.group(1)
            line_num = int(elem_match.group(2))

            primary = None
            related = []

            # Get primary from next line
            if i + 1 < len(lines):
                prim_match = re.match(r'^  - primary:\s*(.+)$', lines[i + 1])
                if prim_match:
                    primary = prim_match.group(1).strip()

            # Get related from line after that
            if i + 2 < len(lines):
                rel_match = re.match(r'^  - related:\s*(.+)$', lines[i + 2])
                if rel_match:
                    related = [r.strip() for r in rel_match.group(1).split(',')]

            elements[element] = {
                "primary": primary,
                "related": related,
                "line_num": line_num
            }

        i += 1

    return elements


def group_by_library(elements: dict) -> dict:
    """Group elements by their primary library."""
    by_lib = {}
    for elem, info in elements.items():
        lib = info["primary"]
        if lib not in by_lib:
            by_lib[lib] = []
        by_lib[lib].append({
            "element": elem,
            "line_num": info["line_num"],
            "related": info["related"]
        })

    # Sort by line number within each library
    for lib in by_lib:
        by_lib[lib].sort(key=lambda x: x["line_num"])

    return by_lib


def main():
    base = Path(__file__).parent
    libs_path = base / "libs.md"
    output_path = base / "library_map.json"

    content = libs_path.read_text(encoding='utf-8')
    elements = parse_libs_md(content)

    print(f"Parsed {len(elements)} elements")

    by_lib = group_by_library(elements)

    # Save the mapping
    output = {
        "elements": elements,
        "by_library": by_lib
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)

    print(f"\nLibrary map written to {output_path}")
    print("\nElements per library:")
    for lib, elems in sorted(by_lib.items(), key=lambda x: -len(x[1])):
        print(f"  {lib}: {len(elems)}")


if __name__ == "__main__":
    main()
