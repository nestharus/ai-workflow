#!/usr/bin/env python3
"""
Find duplicate declarations in library files and check against libs.md assignments.

Reports:
1. Duplicate declarations (same ID in multiple files)
2. Items in wrong file (not their primary library per libs.md)
3. Items not in libs.md (serious problem)
"""

import re
from pathlib import Path
from collections import defaultdict
from difflib import SequenceMatcher


def parse_libs_md(libs_path: Path) -> dict[str, str]:
    """Parse libs.md to extract item -> primary library mapping."""
    content = libs_path.read_text(encoding='utf-8')

    # Pattern: - **ID**: description
    #   - primary: library_name
    assignments = {}

    lines = content.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]

        # Match item line: - **Comp1**: ... or - **D1**: ... or - **Algorithm 1**: ...
        m = re.match(r'^- \*\*([^*]+)\*\*:', line)
        if m:
            item_id = m.group(1).strip()
            # Look for primary in next few lines
            for j in range(i+1, min(i+5, len(lines))):
                pm = re.match(r'^\s+- primary:\s*(\w+)', lines[j])
                if pm:
                    assignments[item_id] = pm.group(1)
                    break
                # Stop if we hit another item
                if re.match(r'^- \*\*', lines[j]):
                    break
        i += 1

    return assignments


def get_section_body(lines: list[str], start_idx: int) -> tuple[str, int]:
    """Extract body from a section. Returns (body, end_idx)."""
    if start_idx >= len(lines):
        return "", start_idx

    first_line = lines[start_idx]
    match = re.match(r'^(#+)\s', first_line)
    if not match:
        return "", start_idx

    level = len(match.group(1))
    body_lines = []

    for i in range(start_idx + 1, len(lines)):
        line = lines[i]
        m = re.match(r'^(#+)\s', line)
        if m and len(m.group(1)) <= level:
            return '\n'.join(body_lines).strip(), i
        body_lines.append(line.rstrip())

    return '\n'.join(body_lines).strip(), len(lines)


def extract_id_from_header(header: str) -> str | None:
    """Extract the ID from a header line."""
    clean = re.sub(r'^#+\s+', '', header).strip()

    patterns = [
        (r'^(Comp\d+)', 'Comp'),
        (r'^(D\d+)', 'D'),
        (r'^(Algorithm \d+)', 'Algorithm'),
        (r'^(G\d+)', 'G'),
        (r'^(P\d+I\d+)', 'Invariant'),
        (r'^(P\d+C\d+)', 'Claim'),
        (r'^(P\d+\.\d+)', 'Math'),
        (r'^(Lean\d+)', 'Lean'),
        (r'^(NFG\d+)', 'NFG'),
        (r'^(S\d+)', 'Statement'),
        (r'^(C\d+)', 'Claim'),
    ]

    for pat, _ in patterns:
        m = re.match(pat, clean)
        if m:
            return m.group(1)

    return None


def scan_library_files(libs_dir: Path) -> dict[str, list[dict]]:
    """Scan all library files for declarations.

    Returns: {id: [{file, line, header, body, body_hash}, ...]}
    """
    declarations = defaultdict(list)

    for lib_file in sorted(libs_dir.glob("*.md")):
        lib_name = lib_file.stem
        content = lib_file.read_text(encoding='utf-8')
        lines = content.split('\n')

        i = 0
        while i < len(lines):
            line = lines[i]
            if re.match(r'^#{2,3}\s', line):
                item_id = extract_id_from_header(line)
                if item_id:
                    body, end_idx = get_section_body(lines, i)
                    declarations[item_id].append({
                        'file': lib_name,
                        'line': i + 1,
                        'header': line.strip(),
                        'body': body,
                        'body_len': len(body),
                    })
                    i = end_idx
                    continue
            i += 1

    return declarations


def compare_bodies(body1: str, body2: str) -> float:
    """Compare two bodies, return similarity ratio."""
    if not body1 and not body2:
        return 1.0
    if not body1 or not body2:
        return 0.0
    return SequenceMatcher(None, body1[:1000], body2[:1000]).ratio()


def main():
    base = Path(__file__).parent
    libs_dir = base / "libraries"
    libs_md = base / "libs.md"

    print("=" * 70)
    print("DUPLICATE AND ASSIGNMENT ANALYSIS")
    print("=" * 70)

    # Parse libs.md
    assignments = parse_libs_md(libs_md)
    print(f"\nLoaded {len(assignments)} assignments from libs.md")

    # Scan library files
    declarations = scan_library_files(libs_dir)
    total_decls = sum(len(v) for v in declarations.values())
    print(f"Found {total_decls} declarations across {len(declarations)} unique IDs")

    # Find duplicates
    duplicates = {k: v for k, v in declarations.items() if len(v) > 1}
    print(f"\nDuplicates: {len(duplicates)} IDs appear in multiple files")

    # Analyze duplicates
    identical_dupes = []
    different_dupes = []

    for item_id, occurrences in sorted(duplicates.items()):
        # Compare bodies
        bodies_same = True
        for i in range(1, len(occurrences)):
            sim = compare_bodies(occurrences[0]['body'], occurrences[i]['body'])
            if sim < 0.95:
                bodies_same = False
                break

        if bodies_same:
            identical_dupes.append((item_id, occurrences))
        else:
            different_dupes.append((item_id, occurrences))

    # Check assignments
    wrong_file = []
    not_in_libs = []

    for item_id, occurrences in declarations.items():
        if item_id in assignments:
            primary = assignments[item_id]
            for occ in occurrences:
                if occ['file'] != primary:
                    wrong_file.append((item_id, occ['file'], primary))
        else:
            not_in_libs.append((item_id, [o['file'] for o in occurrences]))

    # Report
    print("\n" + "=" * 70)
    print(f"IDENTICAL DUPLICATES - {len(identical_dupes)} IDs (same content, can safely dedupe)")
    print("=" * 70)
    for item_id, occs in identical_dupes[:30]:
        files = [f"{o['file']}:{o['line']}" for o in occs]
        primary = assignments.get(item_id, "NOT IN LIBS.MD")
        print(f"  {item_id}: {', '.join(files)} -> primary: {primary}")
    if len(identical_dupes) > 30:
        print(f"  ... and {len(identical_dupes) - 30} more")

    print("\n" + "=" * 70)
    print(f"DIFFERENT DUPLICATES - {len(different_dupes)} IDs (content differs!)")
    print("=" * 70)
    for item_id, occs in different_dupes[:30]:
        primary = assignments.get(item_id, "NOT IN LIBS.MD")
        print(f"  {item_id}: primary={primary}")
        for o in occs:
            print(f"    - {o['file']}:{o['line']} ({o['body_len']} chars)")

    print("\n" + "=" * 70)
    print(f"NOT IN LIBS.MD - {len(not_in_libs)} IDs (SERIOUS)")
    print("=" * 70)
    for item_id, files in sorted(not_in_libs)[:50]:
        print(f"  {item_id}: {', '.join(files)}")
    if len(not_in_libs) > 50:
        print(f"  ... and {len(not_in_libs) - 50} more")

    print("\n" + "=" * 70)
    print(f"IN WRONG FILE - {len(wrong_file)} occurrences")
    print("=" * 70)
    for item_id, actual, expected in sorted(wrong_file)[:50]:
        print(f"  {item_id}: in {actual}, should be in {expected}")
    if len(wrong_file) > 50:
        print(f"  ... and {len(wrong_file) - 50} more")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total unique IDs: {len(declarations)}")
    print(f"Identical duplicates: {len(identical_dupes)}")
    print(f"Different duplicates: {len(different_dupes)}")
    print(f"Not in libs.md: {len(not_in_libs)}")
    print(f"In wrong file: {len(wrong_file)}")


if __name__ == "__main__":
    main()
