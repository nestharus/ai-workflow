#!/usr/bin/env python3
"""
Compare IDs between libs.md and plan.md:
1. Parse libs.md by category sections (## Category (count))
2. Extract ID and label from list items: - **ID**: Label (L###)
3. Compare with plan.md headers
4. Report missing entries and label mismatches
"""

import re
from pathlib import Path
from dataclasses import dataclass


@dataclass
class Entry:
    id: str
    label: str
    category: str
    line: int


def parse_libs_md(filepath: Path) -> list[Entry]:
    """Parse libs.md by category sections and extract entries."""
    entries = []
    content = filepath.read_text(encoding='utf-8')
    lines = content.split('\n')

    current_category = None

    for line_num, line in enumerate(lines, 1):
        # Check for category header: ## Category (count)
        cat_match = re.match(r'^##\s+(.+?)\s*\(\d+\)\s*$', line)
        if cat_match:
            current_category = cat_match.group(1).strip()
            continue

        # Check for top-level list item: - **ID**: Label (L###)
        # Must start with "- " (not "  - " which is nested)
        if not line.startswith('- '):
            continue

        if current_category is None:
            continue

        # Extract: - **ID**: Label (L###) or - **ID** (L###)
        # Pattern: - **ID**: Label (L###)  or  - **ID** Label (L###)
        item_match = re.match(r'^-\s+\*\*(.+?)\*\*:?\s*(.+?)?\s*(?:\(L\d+\))?\s*$', line)
        if item_match:
            id_part = item_match.group(1).strip()
            label_part = item_match.group(2)
            label = label_part.strip() if label_part else ''

            # Clean up label - remove trailing (L###) if still present
            label = re.sub(r'\s*\(L\d+\)\s*$', '', label)

            entries.append(Entry(
                id=id_part,
                label=label,
                category=current_category,
                line=line_num
            ))

    return entries


def parse_plan_headers(filepath: Path) -> list[Entry]:
    """Parse plan.md headers and extract ID + label."""
    entries = []
    content = filepath.read_text(encoding='utf-8')
    lines = content.split('\n')

    for line_num, line in enumerate(lines, 1):
        if not line.strip().startswith('#'):
            continue

        # Remove # prefix and any annotations like (=[P1])
        clean = re.sub(r'^#+\s*', '', line)
        clean = re.sub(r'\s*\([=+@]\[[^\]]+\]\)\s*', ' ', clean).strip()

        # Try to extract ID and label
        # Patterns: "ID Label", "ID: Label", "ID - Label"

        # Try colon separator first
        if ':' in clean:
            parts = clean.split(':', 1)
            id_part = parts[0].strip()
            label = parts[1].strip() if len(parts) > 1 else ''
        else:
            # Split on first space
            parts = clean.split(None, 1)
            id_part = parts[0].strip() if parts else clean
            label = parts[1].strip() if len(parts) > 1 else ''

        if id_part:
            entries.append(Entry(
                id=id_part,
                label=label,
                category='header',
                line=line_num
            ))

    return entries


def main():
    base = Path(__file__).parent
    plan_path = base / "plan.md"
    libs_path = base / "libs.md"

    libs_entries = parse_libs_md(libs_path)
    plan_entries = parse_plan_headers(plan_path)

    print("=" * 70)
    print("ID COMPARISON: libs.md vs plan.md")
    print("=" * 70)

    print(f"\nlibs.md entries: {len(libs_entries)}")
    print(f"plan.md headers: {len(plan_entries)}")

    # Build lookup dicts
    libs_by_id = {e.id: e for e in libs_entries}
    plan_by_id = {e.id: e for e in plan_entries}

    # Find differences
    libs_ids = set(libs_by_id.keys())
    plan_ids = set(plan_by_id.keys())

    in_libs_not_plan = libs_ids - plan_ids
    in_plan_not_libs = plan_ids - libs_ids
    in_both = libs_ids & plan_ids

    print(f"\nIn both: {len(in_both)}")
    print(f"In libs.md only: {len(in_libs_not_plan)}")
    print(f"In plan.md only: {len(in_plan_not_libs)}")

    # Check for label mismatches
    label_mismatches = []
    for id_str in in_both:
        libs_entry = libs_by_id[id_str]
        plan_entry = plan_by_id[id_str]
        if libs_entry.label and plan_entry.label:
            # Normalize for comparison
            libs_label = libs_entry.label.lower().strip()
            plan_label = plan_entry.label.lower().strip()
            if libs_label != plan_label:
                label_mismatches.append((id_str, libs_entry.label, plan_entry.label))

    if in_libs_not_plan:
        print(f"\n{'='*70}")
        print(f"IN LIBS.MD BUT NOT IN PLAN.MD ({len(in_libs_not_plan)})")
        print("=" * 70)
        for id_str in sorted(in_libs_not_plan):
            e = libs_by_id[id_str]
            print(f"  [{e.category}] {e.id}: {e.label}")

    if in_plan_not_libs:
        print(f"\n{'='*70}")
        print(f"IN PLAN.MD BUT NOT IN LIBS.MD ({len(in_plan_not_libs)})")
        print("=" * 70)
        for id_str in sorted(in_plan_not_libs)[:50]:
            e = plan_by_id[id_str]
            print(f"  L{e.line}: {e.id}: {e.label[:50]}")
        if len(in_plan_not_libs) > 50:
            print(f"  ... and {len(in_plan_not_libs) - 50} more")

    if label_mismatches:
        print(f"\n{'='*70}")
        print(f"LABEL MISMATCHES ({len(label_mismatches)})")
        print("=" * 70)
        for id_str, libs_label, plan_label in label_mismatches[:30]:
            print(f"  {id_str}:")
            print(f"    libs: {libs_label[:50]}")
            print(f"    plan: {plan_label[:50]}")
        if len(label_mismatches) > 30:
            print(f"  ... and {len(label_mismatches) - 30} more")

    # Summary by category
    print(f"\n{'='*70}")
    print("LIBS.MD ENTRIES BY CATEGORY")
    print("=" * 70)
    from collections import Counter
    cat_counts = Counter(e.category for e in libs_entries)
    for cat, count in sorted(cat_counts.items()):
        print(f"  {cat}: {count}")


if __name__ == "__main__":
    main()
