#!/usr/bin/env python3
"""
Find lines unique to library files (not in plan.md).
Group consecutive unique lines into regions and associate with IDs.
"""

import re
from pathlib import Path

LIBS_DIR = Path(__file__).parent.parent / "libraries"
PLAN_MD = Path(__file__).parent.parent / "plan.md"

ID_PATTERNS = [
    r'Algorithm \d+', r'Comp\d+', r'D\d+', r'G\d+', r'C\d+', r'S\d+', r'T\d+',
    r'P\d+I\d+', r'P\d+C\d+', r'P\d+\.\d+', r'Lean\d+', r'NFG\d+',
]


def is_legal_id(text):
    for pattern in ID_PATTERNS:
        if re.match(f'^{pattern}$', text):
            return True
    return False


def normalize_line(line):
    """Normalize line for comparison (strip whitespace)."""
    return line.strip()


def get_plan_lines():
    """Get all non-empty lines from plan.md as a set."""
    content = PLAN_MD.read_text()
    lines = set()
    for line in content.splitlines():
        norm = normalize_line(line)
        if norm:
            lines.add(norm)
    return lines


def find_unique_regions_with_ids(file_path, plan_lines):
    """Find regions of consecutive unique lines with their associated IDs."""
    content = file_path.read_text()
    lines = content.splitlines()

    annotation_pattern = re.compile(r'\[\(=([^\]]+)\)\]')

    # First pass: find current ID for each line
    line_ids = [None] * len(lines)
    current_id = None

    for i, line in enumerate(lines):
        match = annotation_pattern.search(line)
        if match and is_legal_id(match.group(1)):
            current_id = match.group(1)
        line_ids[i] = current_id

    # Second pass: find unique regions
    regions = []
    current_region = []
    current_start = None
    current_region_id = None

    for i, line in enumerate(lines):
        norm = normalize_line(line)

        if norm and norm not in plan_lines:
            if not current_region:
                current_start = i + 1
                current_region_id = line_ids[i]
            current_region.append((i + 1, line))
        else:
            if current_region:
                regions.append({
                    'id': current_region_id,
                    'start': current_start,
                    'end': current_region[-1][0],
                    'lines': current_region
                })
                current_region = []
                current_start = None

    if current_region:
        regions.append({
            'id': current_region_id,
            'start': current_start,
            'end': current_region[-1][0],
            'lines': current_region
        })

    return regions


def main():
    print("Loading plan.md lines...")
    plan_lines = get_plan_lines()
    print(f"Found {len(plan_lines)} unique non-empty lines in plan.md\n")

    all_regions = []

    for lib_file in sorted(LIBS_DIR.glob("*.md")):
        lib_name = lib_file.stem
        regions = find_unique_regions_with_ids(lib_file, plan_lines)

        for region in regions:
            region['library'] = lib_name
            all_regions.append(region)

    # Sort by line count (smallest first)
    all_regions.sort(key=lambda r: len(r['lines']))

    print(f"Total regions: {len(all_regions)}")
    print(f"Total unique lines: {sum(len(r['lines']) for r in all_regions)}\n")

    # Group by size
    size_1 = [r for r in all_regions if len(r['lines']) == 1]
    size_2_3 = [r for r in all_regions if 2 <= len(r['lines']) <= 3]
    size_4_plus = [r for r in all_regions if len(r['lines']) >= 4]

    print(f"1-line regions: {len(size_1)}")
    print(f"2-3 line regions: {len(size_2_3)}")
    print(f"4+ line regions: {len(size_4_plus)}\n")

    # Show 1-line regions (likely formatting/annotation diffs)
    print("=" * 70)
    print("1-LINE REGIONS (likely formatting/annotation diffs):")
    print("=" * 70)
    for r in size_1[:30]:
        line = r['lines'][0][1]
        preview = line[:60] + "..." if len(line) > 60 else line
        print(f"  {r['library']}:{r['start']} [{r['id']}]: {preview}")
    if len(size_1) > 30:
        print(f"  ... and {len(size_1) - 30} more")

    # Show 2-3 line regions
    print("\n" + "=" * 70)
    print("2-3 LINE REGIONS:")
    print("=" * 70)
    for r in size_2_3[:20]:
        print(f"\n  {r['library']}:{r['start']}-{r['end']} [{r['id']}]:")
        for ln, text in r['lines']:
            preview = text[:65] + "..." if len(text) > 65 else text
            print(f"    {ln}: {preview}")
    if len(size_2_3) > 20:
        print(f"\n  ... and {len(size_2_3) - 20} more")

    # Show 4+ line regions
    print("\n" + "=" * 70)
    print("4+ LINE REGIONS:")
    print("=" * 70)
    for r in size_4_plus:
        print(f"\n  {r['library']}:{r['start']}-{r['end']} [{r['id']}] ({len(r['lines'])} lines):")
        for ln, text in r['lines'][:3]:
            preview = text[:65] + "..." if len(text) > 65 else text
            print(f"    {ln}: {preview}")
        if len(r['lines']) > 3:
            print(f"    ... and {len(r['lines']) - 3} more lines")


if __name__ == "__main__":
    main()
