#!/usr/bin/env python3
"""
Detect duplicates and conflicts in library files.

RULE: Each ID must appear EXACTLY ONCE across all library files,
in its PRIMARY library as defined in libs.md.
"""

import re
from pathlib import Path
from collections import defaultdict, Counter

# Library directory
LIBS_DIR = Path(__file__).parent.parent / "libraries"
LIBS_MD = Path(__file__).parent.parent / "libs.md"

# Legal ID patterns
ID_PATTERNS = [
    r'Algorithm \d+',
    r'Comp\d+',
    r'D\d+',
    r'G\d+',
    r'C\d+',
    r'S\d+',
    r'T\d+',
    r'P\d+I\d+',
    r'P\d+C\d+',
    r'P\d+\.\d+',
    r'Lean\d+',
    r'NFG\d+',
]


def parse_libs_md():
    """Parse libs.md to get expected primary library for each ID."""
    id_assignments = {}

    content = LIBS_MD.read_text()
    lines = content.splitlines()

    current_id = None
    current_primary = None

    for line in lines:
        # Match ID declaration
        id_match = re.match(r'^- \(\[=([^\]]+)\]\)', line)
        if id_match:
            # Save previous entry
            if current_id and current_primary:
                id_assignments[current_id] = current_primary
            # Start new entry
            current_id = id_match.group(1)
            current_primary = None
            continue

        # Match primary
        primary_match = re.match(r'^\s+- primary:\s*(\w+)', line)
        if primary_match:
            current_primary = primary_match.group(1).strip()
            continue

    # Save last entry
    if current_id and current_primary:
        id_assignments[current_id] = current_primary

    return id_assignments


def extract_ids_with_locations(file_path):
    """Extract all IDs with their line numbers from a library file."""
    content = file_path.read_text()
    lines = content.splitlines()

    ids_with_lines = []
    annotation_pattern = re.compile(r"\(\[=([^\]]+)\]\)")

    for line_num, line in enumerate(lines, 1):
        for match in annotation_pattern.finditer(line):
            id_name = match.group(1)
            # Validate it's a legal ID
            for pattern in ID_PATTERNS:
                if re.match(f'^{pattern}$', id_name):
                    ids_with_lines.append((id_name, line_num))
                    break

    return ids_with_lines


def main():
    # Parse libs.md for expected primary assignments
    print("Parsing libs.md for expected library assignments...")
    id_primaries = parse_libs_md()
    print(f"Found {len(id_primaries)} IDs in libs.md\n")

    # Find all library files
    library_files = sorted(LIBS_DIR.glob("*.md"))
    print(f"Found {len(library_files)} library files\n")

    # Extract ALL ID occurrences from all library files
    all_occurrences = []  # (id_name, lib_name, line_num)

    for lib_file in library_files:
        lib_name = lib_file.stem
        ids_with_lines = extract_ids_with_locations(lib_file)
        for id_name, line_num in ids_with_lines:
            all_occurrences.append((id_name, lib_name, line_num))

    # Group by ID
    id_occurrences = defaultdict(list)  # id -> [(lib_name, line_num), ...]
    for id_name, lib_name, line_num in all_occurrences:
        id_occurrences[id_name].append((lib_name, line_num))

    # Count total occurrences
    print("=" * 70)
    print("DUPLICATE IDs (appearing more than once across all library files):")
    print("=" * 70)

    duplicates = []
    for id_name, occurrences in sorted(id_occurrences.items()):
        if len(occurrences) > 1:
            expected_primary = id_primaries.get(id_name, "UNKNOWN")
            duplicates.append((id_name, occurrences, expected_primary))

    if duplicates:
        for id_name, occurrences, expected_primary in duplicates:
            print(f"\n  {id_name} (should be in: {expected_primary})")
            print(f"    Found {len(occurrences)} times:")
            for lib_name, line_num in occurrences:
                marker = " <-- KEEP" if lib_name == expected_primary else " <-- REMOVE"
                print(f"      - {lib_name}.md:{line_num}{marker}")
    else:
        print("  None found - all IDs appear exactly once!")

    # Find IDs in wrong library (not in primary)
    print("\n" + "=" * 70)
    print("IDs IN WRONG LIBRARY (not in their primary library):")
    print("=" * 70)

    wrong_location = []
    for id_name, expected_primary in sorted(id_primaries.items()):
        occurrences = id_occurrences.get(id_name, [])
        libs_found = [loc[0] for loc in occurrences]

        if expected_primary not in libs_found:
            wrong_location.append((id_name, expected_primary, occurrences))

    if wrong_location:
        for id_name, expected_primary, occurrences in wrong_location:
            print(f"\n  {id_name}")
            print(f"    Expected in: {expected_primary}")
            if occurrences:
                print(f"    Found in: {[f'{loc[0]}.md:{loc[1]}' for loc in occurrences]}")
            else:
                print(f"    Found in: NOWHERE (missing)")
    else:
        print("  None - all IDs are in their primary library!")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY:")
    print("=" * 70)
    print(f"  Total IDs in libs.md: {len(id_primaries)}")
    print(f"  Total unique IDs in library files: {len(id_occurrences)}")
    print(f"  Total ID occurrences: {len(all_occurrences)}")
    print(f"  IDs with duplicates: {len(duplicates)}")
    print(f"  IDs in wrong library: {len(wrong_location)}")

    # Calculate entries to remove
    entries_to_remove = len(all_occurrences) - len(id_occurrences)
    print(f"  Entries to remove (to achieve 1 per ID): {entries_to_remove}")


if __name__ == "__main__":
    main()
