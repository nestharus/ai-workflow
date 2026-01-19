#!/usr/bin/env python3
"""
Find all headers without standard ID patterns.
These need to be either:
1. Assigned an ID (T# for Topic, C# for Component, R# for Relation)
2. Removed/converted to body text
"""

import re
from pathlib import Path
from collections import defaultdict

# Standard ID patterns
ID_PATTERNS = [
    (r'Algorithm\s+\d+', 'Algorithm'),
    (r'P\d+I\d+', 'Invariant'),
    (r'P\d+C\d+', 'PatchClaim'),
    (r'P\d+\.\d+', 'Math'),
    (r'Lean\d+', 'Lean'),
    (r'Lean\s+\d+', 'Lean'),
    (r'(?<![P\d])C\d+', 'Claim'),  # C1, C2, etc. but not P1C1
    (r'G\d+', 'Goal'),
    (r'D\d+', 'DataStructure'),
    (r'Comp\d+', 'Component'),
    (r'S\d+', 'Statement'),
    (r'H\d+', 'Hypothesis'),
    (r'NFG\d+', 'NFG'),
    (r'REF\d+', 'Reference'),
    (r'T\d+', 'Topic'),
    (r'R\d+', 'Relation'),
]


def has_id(line: str) -> tuple[bool, str | None]:
    """Check if line has a recognized ID pattern."""
    for pattern, id_type in ID_PATTERNS:
        if re.search(pattern, line):
            return True, id_type
    return False, None


def extract_headers(content: str) -> list[tuple[int, str, int]]:
    """Extract all headers with line number and level."""
    headers = []
    for i, line in enumerate(content.split('\n'), 1):
        match = re.match(r'^(#+)\s+(.+)$', line)
        if match:
            level = len(match.group(1))
            text = match.group(2).strip()
            headers.append((i, text, level))
    return headers


def categorize_header(text: str) -> str:
    """Suggest a category for a header without ID."""
    text_lower = text.lower()

    # Proof sketches - should reference parent claim
    if 'proof' in text_lower or 'sketch' in text_lower:
        return 'PROOF_SKETCH'

    # Options/alternatives - organizational
    if text_lower.startswith('option ') or 'alternative' in text_lower:
        return 'OPTION'

    # Mode/step - procedural
    if text_lower.startswith('mode ') or text_lower.startswith('step '):
        return 'PROCEDURAL'

    # Why/how/what - explanatory
    if text_lower.startswith('why ') or text_lower.startswith('how ') or text_lower.startswith('what '):
        return 'EXPLANATORY'

    # Conceptual definitions
    if 'disentanglement' in text_lower or 'alignment' in text_lower:
        return 'CONCEPT'

    # Implementation details
    if 'implementation' in text_lower or 'detail' in text_lower:
        return 'IMPLEMENTATION'

    return 'UNKNOWN'


def main():
    base = Path(__file__).parent
    plan_path = base / "plan.md"

    content = plan_path.read_text(encoding='utf-8')
    headers = extract_headers(content)

    with_ids = []
    without_ids = []

    for line_num, text, level in headers:
        has, id_type = has_id(text)
        if has:
            with_ids.append((line_num, text, level, id_type))
        else:
            category = categorize_header(text)
            without_ids.append((line_num, text, level, category))

    print("=" * 70)
    print("HEADERS WITHOUT IDs")
    print("=" * 70)
    print(f"\nTotal headers: {len(headers)}")
    print(f"With IDs: {len(with_ids)}")
    print(f"Without IDs: {len(without_ids)}")

    # Group by category
    by_category = defaultdict(list)
    for line_num, text, level, category in without_ids:
        by_category[category].append((line_num, text, level))

    print("\n" + "=" * 70)
    print("BY CATEGORY")
    print("=" * 70)

    for category in sorted(by_category.keys()):
        items = by_category[category]
        print(f"\n## {category} ({len(items)} items)")
        for line_num, text, level in items[:10]:
            prefix = '#' * level
            print(f"  L{line_num}: {prefix} {text[:60]}")
        if len(items) > 10:
            print(f"  ... and {len(items) - 10} more")

    # Full list for processing
    print("\n" + "=" * 70)
    print("FULL LIST (for ID assignment)")
    print("=" * 70)

    for line_num, text, level, category in without_ids:
        print(f"L{line_num}|{'#'*level}|{category}|{text}")


if __name__ == "__main__":
    main()
