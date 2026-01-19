#!/usr/bin/env python3
"""
Investigate Additional Elements and Structures from libs.md:
- Find them in plan.md by label matching
- Detect ID changes (e.g., converted to T# topics)
- Report what happened to each item
"""

import re
from pathlib import Path
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass
class Entry:
    id: str
    label: str
    category: str
    line: int


def parse_libs_md(filepath: Path) -> list[Entry]:
    """Parse libs.md by category sections."""
    entries = []
    content = filepath.read_text(encoding='utf-8')
    lines = content.split('\n')

    current_category = None
    current_subcategory = None

    for line_num, line in enumerate(lines, 1):
        # Check for main category: ## Category (count)
        cat_match = re.match(r'^##\s+(.+?)\s*\(\d+\)\s*$', line)
        if cat_match:
            current_category = cat_match.group(1).strip()
            current_subcategory = None
            continue

        # Check for subcategory: ### Subcategory (count)
        subcat_match = re.match(r'^###\s+(.+?)\s*\(\d+\)\s*$', line)
        if subcat_match:
            current_subcategory = subcat_match.group(1).strip()
            continue

        # Check for top-level list item (not indented)
        if not line.startswith('- '):
            continue

        if current_category is None:
            continue

        # Extract: - **content** (L###) or - **ID**: Label (L###)
        # The content inside ** ** could be the full item or ID: Label
        item_match = re.match(r'^-\s+\*\*(.+?)\*\*\s*(.*)$', line)
        if item_match:
            bold_content = item_match.group(1).strip()
            rest = item_match.group(2).strip()

            # Remove (L###) from rest
            rest = re.sub(r'\s*\(L\d+\)\s*', '', rest).strip()

            # Check if bold_content contains : separator (ID: Label)
            if ':' in bold_content and not bold_content.startswith('Spec'):
                parts = bold_content.split(':', 1)
                id_part = parts[0].strip()
                label = parts[1].strip() if len(parts) > 1 else ''
            else:
                # The whole bold content is the "ID" (actually the full item name)
                id_part = bold_content
                label = rest if rest else bold_content

            # Remove [P#] annotations from label
            label = re.sub(r'\s*\[P\d+\]\s*', '', label)

            # Use subcategory if available, else main category
            cat = f"{current_category}/{current_subcategory}" if current_subcategory else current_category

            entries.append(Entry(
                id=id_part,
                label=label,
                category=cat,
                line=line_num
            ))

    return entries


def parse_plan_headers(filepath: Path) -> list[Entry]:
    """Parse plan.md headers."""
    entries = []
    content = filepath.read_text(encoding='utf-8')
    lines = content.split('\n')

    for line_num, line in enumerate(lines, 1):
        if not line.strip().startswith('#'):
            continue

        clean = re.sub(r'^#+\s*', '', line)
        clean = re.sub(r'\s*\([=+@]\[[^\]]+\]\)\s*', ' ', clean).strip()

        if ':' in clean:
            parts = clean.split(':', 1)
            id_part = parts[0].strip()
            label = parts[1].strip() if len(parts) > 1 else ''
        else:
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


def normalize_label(label: str) -> str:
    """Normalize label for comparison."""
    # Remove common suffixes and prefixes
    label = label.lower().strip()
    label = re.sub(r'\s*\[p\d+\]\s*', '', label)
    label = re.sub(r'\s*\(.*?\)\s*$', '', label)
    label = re.sub(r'[^\w\s]', ' ', label)
    label = ' '.join(label.split())
    return label


def find_label_matches(libs_entry: Entry, plan_entries: list[Entry], threshold: float = 0.7) -> list[tuple[Entry, float]]:
    """Find plan.md entries that match a libs.md label."""
    matches = []
    libs_label = normalize_label(libs_entry.label)
    # Also try the ID as a label (for items like "ObservationRecord" where ID is the name)
    libs_id_as_label = normalize_label(libs_entry.id)

    if not libs_label and not libs_id_as_label:
        return matches

    for plan_entry in plan_entries:
        plan_label = normalize_label(plan_entry.label)
        if not plan_label:
            continue

        # Check both libs label and libs ID against plan label
        for search_label in [libs_label, libs_id_as_label]:
            if not search_label:
                continue

            # Exact match
            if search_label == plan_label:
                matches.append((plan_entry, 1.0))
                continue

            # Fuzzy match
            ratio = SequenceMatcher(None, search_label, plan_label).ratio()
            if ratio >= threshold:
                matches.append((plan_entry, ratio))

            # Check if label is contained
            if search_label in plan_label or plan_label in search_label:
                if (plan_entry, 1.0) not in matches:
                    matches.append((plan_entry, 0.9))

    # Deduplicate
    seen = set()
    unique = []
    for entry, score in matches:
        if entry.id not in seen:
            seen.add(entry.id)
            unique.append((entry, score))

    return sorted(unique, key=lambda x: -x[1])


def search_label_in_file(label: str, filepath: Path) -> list[tuple[int, str, str]]:
    """Search for a label anywhere in the file, return (line_num, line, id_if_header)."""
    results = []
    content = filepath.read_text(encoding='utf-8')
    lines = content.split('\n')

    search_term = label.lower()

    for line_num, line in enumerate(lines, 1):
        if search_term in line.lower():
            # Check if this is a header line
            if line.strip().startswith('#'):
                # Try to extract ID from header
                clean = re.sub(r'^#+\s*', '', line)
                clean = re.sub(r'\s*\([=+@]\[[^\]]+\]\)\s*', ' ', clean).strip()

                # Extract ID (first word or before colon)
                if ':' in clean:
                    id_part = clean.split(':', 1)[0].strip()
                else:
                    parts = clean.split(None, 1)
                    id_part = parts[0] if parts else ''

                results.append((line_num, line.strip(), id_part))
            else:
                results.append((line_num, line.strip()[:80], None))

    return results


def main():
    base = Path(__file__).parent
    plan_path = base / "plan.md"
    libs_path = base / "libs.md"

    libs_entries = parse_libs_md(libs_path)
    plan_entries = parse_plan_headers(plan_path)

    # Debug: show some sample entries
    print("=" * 80)
    print("DEBUG: Sample libs.md entries (Additional Elements)")
    print("=" * 80)
    count = 0
    for e in libs_entries:
        if 'Additional Elements' in e.category and count < 15:
            print(f"  [{e.category}] ID: '{e.id}' Label: '{e.label[:50]}'")
            count += 1

    print("\n" + "=" * 80)
    print("DEBUG: Sample plan.md T entries")
    print("=" * 80)
    for e in plan_entries:
        if e.id.startswith('T') and e.id[1:].isdigit():
            print(f"  ID: '{e.id}' Label: '{e.label}'")

    # Filter to Additional Elements and Structures (including subcategories)
    target_entries = [e for e in libs_entries if 'Additional Elements' in e.category or 'Structures' in e.category]

    # Build plan lookup
    plan_by_id = {e.id: e for e in plan_entries}

    print("=" * 80)
    print("INVESTIGATING ADDITIONAL ELEMENTS AND STRUCTURES")
    print("=" * 80)
    print(f"\nTotal entries to investigate: {len(target_entries)}")

    # Categorize results
    found_exact_id = []      # ID exists in plan.md
    found_by_label = []      # Different ID but same/similar label
    not_found = []           # Can't find in plan.md

    for entry in target_entries:
        if entry.id in plan_by_id:
            found_exact_id.append((entry, plan_by_id[entry.id]))
        else:
            matches = find_label_matches(entry, plan_entries)
            if matches:
                found_by_label.append((entry, matches[0]))
            else:
                not_found.append(entry)

    # Report
    print(f"\n{'='*80}")
    print(f"FOUND BY EXACT ID ({len(found_exact_id)})")
    print("=" * 80)
    for libs_e, plan_e in found_exact_id[:20]:
        print(f"  [{libs_e.category}] {libs_e.id}")
    if len(found_exact_id) > 20:
        print(f"  ... and {len(found_exact_id) - 20} more")

    print(f"\n{'='*80}")
    print(f"FOUND BY LABEL MATCH - DIFFERENT ID ({len(found_by_label)})")
    print("=" * 80)
    for libs_e, (plan_e, score) in found_by_label[:50]:
        print(f"  [{libs_e.category}] libs: {libs_e.id}: {libs_e.label[:40]}")
        print(f"               plan: {plan_e.id}: {plan_e.label[:40]} ({score:.0%})")
        print()
    if len(found_by_label) > 50:
        print(f"  ... and {len(found_by_label) - 50} more")

    print(f"\n{'='*80}")
    print(f"NOT FOUND - DEEP SEARCH ({len(not_found)})")
    print("=" * 80)

    found_in_headers = []
    found_in_body = []
    truly_not_found = []

    for entry in not_found:
        # Search for the ID (e.g., "ObservationRecord") in plan.md
        search_term = entry.id
        results = search_label_in_file(search_term, plan_path)

        header_matches = [r for r in results if r[2] is not None]
        body_matches = [r for r in results if r[2] is None]

        if header_matches:
            found_in_headers.append((entry, header_matches))
        elif body_matches:
            found_in_body.append((entry, body_matches[:3]))
        else:
            truly_not_found.append(entry)

    print(f"\n  FOUND IN HEADERS ({len(found_in_headers)}):")
    for entry, matches in found_in_headers[:30]:
        print(f"    [{entry.category}] {entry.id}")
        for line_num, line, id_part in matches[:2]:
            print(f"      L{line_num}: {id_part} - {line[:60]}")
    if len(found_in_headers) > 30:
        print(f"    ... and {len(found_in_headers) - 30} more")

    print(f"\n  FOUND IN BODY ONLY ({len(found_in_body)}):")
    for entry, matches in found_in_body[:20]:
        print(f"    [{entry.category}] {entry.id}")
        for line_num, line, _ in matches[:1]:
            print(f"      L{line_num}: {line[:60]}")
    if len(found_in_body) > 20:
        print(f"    ... and {len(found_in_body) - 20} more")

    print(f"\n  TRULY NOT FOUND ({len(truly_not_found)}):")

    # Categorize: organizational (numbered, "math", "goals", "components") vs meaningful
    organizational = []
    meaningful = []

    org_patterns = [r'^\d+\.', r'math$', r'goals$', r'components$', r'claim set$',
                    r'proof skeletons$', r'non-functionals$', r'non-goals$', r'targets$',
                    r'strategies$', r'Bottom line$', r'resolved by']

    for entry in truly_not_found:
        text = f"{entry.id} {entry.label}".lower()
        is_org = any(re.search(pat, text, re.I) for pat in org_patterns)
        if is_org:
            organizational.append(entry)
        else:
            meaningful.append(entry)

    print(f"\n    ORGANIZATIONAL (can remove): {len(organizational)}")
    for entry in organizational:
        print(f"      {entry.id}: {entry.label[:40]}")

    print(f"\n    MEANINGFUL (need AI investigation): {len(meaningful)}")
    for entry in meaningful:
        print(f"      {entry.id}: {entry.label[:40]}")

    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print("=" * 80)
    print(f"Found by exact ID: {len(found_exact_id)}")
    print(f"Found by label (ID changed): {len(found_by_label)}")
    print(f"Not found: {len(not_found)}")

    # Group label matches by new ID pattern
    print(f"\n{'='*80}")
    print("ID CHANGES DETECTED")
    print("=" * 80)
    id_changes = {}
    for libs_e, (plan_e, score) in found_by_label:
        old_id = libs_e.id
        new_id = plan_e.id
        # Extract ID pattern
        old_pattern = re.match(r'^([A-Za-z]+)', old_id)
        new_pattern = re.match(r'^([A-Za-z]+)', new_id)
        if old_pattern and new_pattern:
            change = f"{old_pattern.group(1)} -> {new_pattern.group(1)}"
            if change not in id_changes:
                id_changes[change] = []
            id_changes[change].append((libs_e, plan_e, score))

    for change, items in sorted(id_changes.items()):
        print(f"\n{change} ({len(items)} items):")
        for libs_e, plan_e, score in items[:5]:
            print(f"  {libs_e.id} -> {plan_e.id}: {libs_e.label[:30]}")
        if len(items) > 5:
            print(f"  ... and {len(items) - 5} more")


if __name__ == "__main__":
    main()
