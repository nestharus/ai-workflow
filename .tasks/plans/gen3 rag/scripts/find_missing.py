#!/usr/bin/env python3
"""
Find all headers in plan.md that are NOT in libs.md.
"""

import re
from pathlib import Path


def get_plan_headers(content: str) -> list[tuple[int, str, str]]:
    """Get all ## and ### headers from plan.md. Returns [(line_num, level, text)]"""
    headers = []
    for i, line in enumerate(content.split('\n')):
        match = re.match(r'^(#{2,3})\s+(.+)$', line)
        if match:
            level = match.group(1)
            text = re.sub(r'\((?:@\[[=+][^\]]+\]|\[=[^\]]+\])\)', '', match.group(2)).strip()
            headers.append((i + 1, level, text))
    return headers


def get_libs_elements(content: str) -> set[str]:
    """Get all element labels from libs.md."""
    elements = set()
    for line in content.split('\n'):
        match = re.match(r'^- \(\[=([^\]]+)\]\)', line)
        if match:
            elements.add(match.group(1).strip())
    return elements


def main():
    base = Path(__file__).resolve().parents[1]
    plan_content = (base / "plan.md").read_text(encoding='utf-8')
    libs_content = (base / "libs.md").read_text(encoding='utf-8')

    plan_headers = get_plan_headers(plan_content)
    libs_elements = get_libs_elements(libs_content)

    print(f"Plan.md headers: {len(plan_headers)}")
    print(f"Libs.md elements: {len(libs_elements)}")

    # Find headers not in libs.md
    missing = []
    for line_num, level, text in plan_headers:
        # Check if this header (or a key part of it) is in libs_elements
        found = False

        # Direct match
        if text in libs_elements:
            found = True

        # Check for pattern matches (Algorithm 1, P8.7, G12, etc.)
        for elem in libs_elements:
            if elem in text or text.startswith(elem):
                found = True
                break

        if not found:
            missing.append((line_num, level, text))

    print(f"\nMissing from libs.md: {len(missing)}")
    print("\n" + "="*70)
    print("MISSING HEADERS")
    print("="*70)

    # Group by type
    section_headers = []  # Like "## P1 data structures"
    content_headers = []  # Actual content

    for line_num, level, text in missing:
        # Skip section headers (they organize content, not content themselves)
        if any(x in text.lower() for x in ['data structure', 'algorithm', 'invariant', 'claim',
                                            'proof', 'lean', 'math', 'goal', 'non-goal',
                                            'references', 'summary', 'overview']):
            section_headers.append((line_num, level, text))
        else:
            content_headers.append((line_num, level, text))

    print(f"\nSection/organizing headers (not content): {len(section_headers)}")
    print(f"Actual missing content: {len(content_headers)}")

    print("\n--- MISSING CONTENT HEADERS ---")
    for line_num, level, text in content_headers[:50]:
        print(f"  L{line_num}: {level} {text[:60]}")

    if len(content_headers) > 50:
        print(f"  ... and {len(content_headers) - 50} more")

    print("\n--- SECTION HEADERS (expected to be missing) ---")
    for line_num, level, text in section_headers[:20]:
        print(f"  L{line_num}: {level} {text[:60]}")


if __name__ == "__main__":
    main()
