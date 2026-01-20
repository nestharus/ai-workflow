#!/usr/bin/env python3
"""
Compare IDs between libs.md and plan.md.

libs.md format:
- ([=ID])
  - primary: <library>
  - related: <libraries...>
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


def categorize_id(item_id: str) -> str:
    """Assign a simple category based on ID prefix."""
    if item_id.startswith("Algorithm"):
        return "algorithm"
    if item_id.startswith("Comp"):
        return "component"
    if item_id.startswith("D"):
        return "data_structure"
    if item_id.startswith("G"):
        return "goal"
    if re.match(r"^P\\d+I", item_id):
        return "invariant"
    if re.match(r"^P\\d+C", item_id):
        return "claim"
    if re.match(r"^P\\d+\\.", item_id):
        return "patch_section"
    if item_id.startswith("Lean"):
        return "lean"
    if item_id.startswith("NFG"):
        return "nfg"
    if item_id.startswith("S"):
        return "statement"
    if item_id.startswith("T"):
        return "topic"
    if item_id.startswith("C"):
        return "claim"
    return "other"


def parse_libs_md(filepath: Path) -> list[Entry]:
    """Parse libs.md ID entries."""
    entries = []
    content = filepath.read_text(encoding='utf-8')
    lines = content.split('\n')

    for line_num, line in enumerate(lines, 1):
        item_match = re.match(r'^-\s+\(\[=([^\]]+)\]\)', line)
        if item_match:
            id_part = item_match.group(1).strip()
            entries.append(
                Entry(
                    id=id_part,
                    label="",
                    category=categorize_id(id_part),
                    line=line_num,
                )
            )

    return entries


def parse_plan_headers(filepath: Path) -> list[Entry]:
    """Parse plan.md headers and extract ID + label."""
    entries = []
    content = filepath.read_text(encoding='utf-8')
    lines = content.split('\n')

    for line_num, line in enumerate(lines, 1):
        if not line.strip().startswith('#'):
            continue

        # Remove # prefix and any annotations like ([=P1]) or (@[=P1])
        clean = re.sub(r'^#+\s*', '', line)
        clean = re.sub(r'\s*\((?:@\[[=+][^\]]+\]|\[=[^\]]+\])\)\s*', ' ', clean).strip()

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
    base = Path(__file__).resolve().parents[1]
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
