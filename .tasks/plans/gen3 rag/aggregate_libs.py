#!/usr/bin/env python3
"""
Aggregate elements by library to see library shapes.
Shows which elements belong to each library.
"""

import re
from pathlib import Path
from collections import defaultdict

LEGAL_LIBRARIES = [
    "foundation", "graph", "field", "storage", "ingestion", "embedding",
    "patterns", "uncertainty", "exploration", "workspace", "deployment", "verification"
]


def aggregate_by_library(content: str) -> dict[str, list[tuple[str, str]]]:
    """Aggregate elements by library. Returns {library: [(element, category), ...]}"""
    by_library = defaultdict(list)
    lines = content.split('\n')

    current_category = ""

    i = 0
    while i < len(lines):
        line = lines[i]

        # Track category sections (e.g., "## Invariants (15)", "## Maths (41)")
        cat_match = re.match(r'^## (\w+) \(\d+\)', line)
        if cat_match:
            cat_name = cat_match.group(1).lower()
            # Normalize: Invariants->invariant, Maths->math, etc.
            if cat_name.endswith('s'):
                cat_name = cat_name[:-1]
            if cat_name == 'math':
                cat_name = 'math'
            current_category = cat_name

        # Match root elements
        elem_match = re.match(r'^- \*\*(.+?)\*\*', line)
        if elem_match:
            element = elem_match.group(1)

            # Get labels from next line
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                label_match = re.match(r'^  - (.+)$', next_line)
                if label_match and not label_match.group(1).startswith('<!--'):
                    labels = [l.strip() for l in label_match.group(1).split(',')]
                    for lib in labels:
                        if lib in LEGAL_LIBRARIES:
                            by_library[lib].append((element, current_category))

        i += 1

    return by_library


def main():
    libs_path = Path(__file__).parent / "libs.md"
    content = libs_path.read_text(encoding='utf-8')

    by_library = aggregate_by_library(content)

    print("=" * 70)
    print("LIBRARY SHAPES - Elements aggregated by library")
    print("=" * 70)

    for lib in LEGAL_LIBRARIES:
        elements = by_library.get(lib, [])
        print(f"\n{'=' * 70}")
        print(f"{lib.upper()} ({len(elements)} elements)")
        print("=" * 70)

        # Group by category within library
        by_cat = defaultdict(list)
        for elem, cat in elements:
            by_cat[cat].append(elem)

        for cat in ["invariant", "claim", "structure", "algorithm", "math", "lean"]:
            if cat in by_cat:
                print(f"\n  {cat.title()}s ({len(by_cat[cat])}):")
                for elem in by_cat[cat]:
                    print(f"    - {elem}")

    # Show multi-library elements (appear in 4+ libraries)
    print(f"\n{'=' * 70}")
    print("MULTI-LIBRARY ELEMENTS (4+ libraries)")
    print("=" * 70)

    element_libs = defaultdict(set)
    for lib, elements in by_library.items():
        for elem, cat in elements:
            element_libs[elem].add(lib)

    multi = [(elem, libs) for elem, libs in element_libs.items() if len(libs) >= 4]
    multi.sort(key=lambda x: -len(x[1]))

    for elem, libs in multi[:30]:
        print(f"  {elem}: {', '.join(sorted(libs))}")


if __name__ == "__main__":
    main()
