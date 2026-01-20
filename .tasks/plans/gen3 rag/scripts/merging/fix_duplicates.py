#!/usr/bin/env python3
"""
Fix duplicates and wrong locations in library files.

RULE: Each ID must appear EXACTLY ONCE across all library files,
in its PRIMARY library as defined in libs.md.

This script:
1. Removes duplicate entries (keeps only the one in the primary library)
2. Reports IDs that need to be moved to their primary library
"""

import re
from pathlib import Path
from collections import defaultdict

# Library directory
LIBS_DIR = Path(__file__).resolve().parents[2] / "libraries"
LIBS_MD = Path(__file__).resolve().parents[2] / "libs.md"

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
        id_match = re.match(r'^- \(\[=([^\]]+)\]\)', line)
        if id_match:
            if current_id and current_primary:
                id_assignments[current_id] = current_primary
            current_id = id_match.group(1)
            current_primary = None
            continue

        primary_match = re.match(r'^\s+- primary:\s*(\w+)', line)
        if primary_match:
            current_primary = primary_match.group(1).strip()
            continue

    if current_id and current_primary:
        id_assignments[current_id] = current_primary

    return id_assignments


def is_legal_id(text):
    """Check if text matches a legal ID pattern."""
    for pattern in ID_PATTERNS:
        if re.match(f'^{pattern}$', text):
            return True
    return False


def find_section_boundaries(lines, line_num):
    """
    Find the start and end of a section starting at line_num.
    A section starts with ## or ### and ends before the next ## or ### or EOF.
    Returns (start_line, end_line) as 0-indexed line numbers.
    """
    start = line_num - 1  # Convert to 0-indexed

    # Find the end (next header or EOF)
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if re.match(r'^#{2,3}\s', line):
            break
        end += 1

    return start, end


def remove_duplicates_from_file(file_path, ids_to_remove):
    """
    Remove sections for specified IDs from a file.
    ids_to_remove is a dict: {id_name: [line_numbers]}
    """
    if not ids_to_remove:
        return 0

    content = file_path.read_text()
    lines = content.splitlines()

    # Collect all line ranges to remove
    ranges_to_remove = []

    for id_name, line_nums in ids_to_remove.items():
        for line_num in line_nums:
            start, end = find_section_boundaries(lines, line_num)
            ranges_to_remove.append((start, end, id_name, line_num))

    # Sort by start line (descending) to remove from bottom up
    ranges_to_remove.sort(key=lambda x: x[0], reverse=True)

    # Remove sections
    removed_count = 0
    for start, end, id_name, orig_line in ranges_to_remove:
        print(f"    Removing {id_name} at line {orig_line} (lines {start+1}-{end})")
        del lines[start:end]
        removed_count += 1

    # Write back
    file_path.write_text('\n'.join(lines) + '\n')

    return removed_count


def main():
    print("Parsing libs.md for primary library assignments...")
    id_primaries = parse_libs_md()
    print(f"Found {len(id_primaries)} IDs\n")

    # Find all library files
    library_files = sorted(LIBS_DIR.glob("*.md"))

    # Extract ALL ID occurrences
    all_occurrences = []  # (id_name, lib_name, line_num, file_path)

    for lib_file in library_files:
        lib_name = lib_file.stem
        content = lib_file.read_text()
        lines = content.splitlines()

        annotation_pattern = re.compile(r"\(\[=([^\]]+)\]\)")

        for line_num, line in enumerate(lines, 1):
            for match in annotation_pattern.finditer(line):
                id_name = match.group(1)
                if is_legal_id(id_name):
                    all_occurrences.append((id_name, lib_name, line_num, lib_file))

    # Group by ID
    id_occurrences = defaultdict(list)
    for id_name, lib_name, line_num, file_path in all_occurrences:
        id_occurrences[id_name].append((lib_name, line_num, file_path))

    # Determine what to remove
    # For each file, collect IDs to remove
    removals_by_file = defaultdict(lambda: defaultdict(list))

    for id_name, occurrences in id_occurrences.items():
        expected_primary = id_primaries.get(id_name, "UNKNOWN")

        # Find occurrences in primary library
        primary_occurrences = [(lib, ln, fp) for lib, ln, fp in occurrences if lib == expected_primary]
        other_occurrences = [(lib, ln, fp) for lib, ln, fp in occurrences if lib != expected_primary]

        if len(primary_occurrences) > 1:
            # Multiple in primary - keep only first
            for lib, ln, fp in primary_occurrences[1:]:
                removals_by_file[fp][id_name].append(ln)

        # Remove all non-primary occurrences
        for lib, ln, fp in other_occurrences:
            removals_by_file[fp][id_name].append(ln)

    # Count total removals
    total_removals = sum(
        sum(len(lines) for lines in ids.values())
        for ids in removals_by_file.values()
    )

    print(f"Total sections to remove: {total_removals}\n")

    if total_removals == 0:
        print("Nothing to remove!")
        return

    # Perform removals
    print("=" * 60)
    print("REMOVING DUPLICATE SECTIONS:")
    print("=" * 60)

    total_removed = 0
    for file_path, ids_to_remove in sorted(removals_by_file.items(), key=lambda x: x[0].name):
        print(f"\n{file_path.name}:")
        removed = remove_duplicates_from_file(file_path, ids_to_remove)
        total_removed += removed

    print(f"\n{'=' * 60}")
    print(f"DONE: Removed {total_removed} sections")
    print("=" * 60)


if __name__ == "__main__":
    main()
