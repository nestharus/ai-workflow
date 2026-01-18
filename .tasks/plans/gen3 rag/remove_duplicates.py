#!/usr/bin/env python3
"""
Remove identical duplicate declarations from library files.
Keeps the copy in the primary library (per libs.md), removes others.

SAFETY: Uses EXACT string matching only. Will not remove if content differs at all.

Run with --dry-run to see what would be removed without making changes.
Run without flag to actually remove duplicates.
"""

import re
import sys
from pathlib import Path


def parse_libs_md(libs_path: Path) -> dict[str, str]:
    """Parse libs.md to extract item -> primary library mapping."""
    content = libs_path.read_text(encoding='utf-8')
    assignments = {}

    lines = content.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r'^- \*\*([^*]+)\*\*:', line)
        if m:
            item_id = m.group(1).strip()
            for j in range(i+1, min(i+5, len(lines))):
                pm = re.match(r'^\s+- primary:\s*(\w+)', lines[j])
                if pm:
                    assignments[item_id] = pm.group(1)
                    break
                if re.match(r'^- \*\*', lines[j]):
                    break
        i += 1

    return assignments


def extract_id_from_header(header: str) -> str | None:
    """Extract the ID from a header line."""
    clean = re.sub(r'^#+\s+', '', header).strip()

    patterns = [
        r'^(Comp\d+)', r'^(D\d+)', r'^(Algorithm \d+)', r'^(G\d+)',
        r'^(P\d+I\d+)', r'^(P\d+C\d+)', r'^(P\d+\.\d+)', r'^(Lean\d+)',
        r'^(NFG\d+)', r'^(S\d+)', r'^(C\d+)',
    ]

    for pat in patterns:
        m = re.match(pat, clean)
        if m:
            return m.group(1)
    return None


def get_section_text(lines: list[str], start_idx: int) -> tuple[int, int, str]:
    """Get section start, end, and FULL TEXT (header + body).

    Returns the exact text that would be removed.
    """
    if start_idx >= len(lines):
        return start_idx, start_idx, ""

    first_line = lines[start_idx]
    match = re.match(r'^(#+)\s', first_line)
    if not match:
        return start_idx, start_idx, ""

    level = len(match.group(1))
    section_lines = [first_line]
    end_idx = start_idx + 1

    for i in range(start_idx + 1, len(lines)):
        line = lines[i]
        m = re.match(r'^(#+)\s', line)
        if m and len(m.group(1)) <= level:
            end_idx = i
            break
        section_lines.append(line)
        end_idx = i + 1

    # Strip trailing blank lines from section
    while section_lines and section_lines[-1].strip() == '':
        section_lines.pop()

    full_text = '\n'.join(section_lines)
    return start_idx, end_idx, full_text


def scan_library_files(libs_dir: Path) -> dict[str, list[dict]]:
    """Scan all library files for declarations."""
    declarations = {}

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
                    start, end, full_text = get_section_text(lines, i)
                    if item_id not in declarations:
                        declarations[item_id] = []
                    declarations[item_id].append({
                        'file': lib_name,
                        'filepath': lib_file,
                        'start': start,
                        'end': end,
                        'full_text': full_text,
                        'char_count': len(full_text),
                    })
                    i = end
                    continue
            i += 1

    return declarations


def remove_exact_text_from_file(filepath: Path, exact_text: str) -> bool:
    """Remove exact text from file. Returns True if found and removed."""
    content = filepath.read_text(encoding='utf-8')

    # Try to find and remove the exact text (with surrounding newlines)
    patterns_to_try = [
        f"\n\n{exact_text}\n\n",  # surrounded by blank lines
        f"\n\n{exact_text}\n",    # blank before, single after
        f"\n{exact_text}\n\n",    # single before, blank after
        f"\n{exact_text}\n",      # single newlines
        f"\n\n---\n\n{exact_text}\n\n",  # with --- separator before
        f"{exact_text}\n\n---\n\n",       # with --- separator after
    ]

    for pattern in patterns_to_try:
        if pattern in content:
            # Replace with appropriate whitespace
            replacement = "\n\n" if "\n\n" in pattern else "\n"
            new_content = content.replace(pattern, replacement, 1)
            filepath.write_text(new_content, encoding='utf-8')
            return True

    # Try without surrounding newlines as last resort
    if exact_text in content:
        new_content = content.replace(exact_text, "", 1)
        # Clean up resulting double blank lines
        while "\n\n\n" in new_content:
            new_content = new_content.replace("\n\n\n", "\n\n")
        filepath.write_text(new_content, encoding='utf-8')
        return True

    return False


def main():
    dry_run = '--dry-run' in sys.argv

    base = Path(__file__).parent
    libs_dir = base / "libraries"
    libs_md = base / "libs.md"

    print("=" * 70)
    print(f"REMOVE IDENTICAL DUPLICATES {'(DRY RUN)' if dry_run else ''}")
    print("=" * 70)

    # Parse libs.md
    assignments = parse_libs_md(libs_md)
    print(f"\nLoaded {len(assignments)} assignments from libs.md")

    # Scan library files
    declarations = scan_library_files(libs_dir)

    # Find EXACTLY identical duplicates
    to_remove = []

    for item_id, occurrences in declarations.items():
        if len(occurrences) < 2:
            continue

        # Check if ALL occurrences have EXACTLY the same text
        first_text = occurrences[0]['full_text']
        all_identical = all(occ['full_text'] == first_text for occ in occurrences)

        if not all_identical:
            # Show why we're skipping
            sizes = [f"{occ['file']}:{occ['char_count']}" for occ in occurrences]
            print(f"  SKIP {item_id}: content differs - {', '.join(sizes)}")
            continue

        # Get primary library
        primary = assignments.get(item_id)
        if not primary:
            print(f"  SKIP {item_id}: not in libs.md")
            continue

        # Check if primary file has a copy
        primary_has_copy = any(occ['file'] == primary for occ in occurrences)
        if not primary_has_copy:
            print(f"  SKIP {item_id}: primary '{primary}' doesn't have a copy!")
            continue

        # Find occurrences not in primary
        for occ in occurrences:
            if occ['file'] != primary:
                to_remove.append({
                    'item_id': item_id,
                    'file': occ['file'],
                    'filepath': occ['filepath'],
                    'full_text': occ['full_text'],
                    'char_count': occ['char_count'],
                    'primary': primary,
                })

    print(f"\nFound {len(to_remove)} duplicate sections to remove\n")

    # Group by file
    by_file = {}
    for item in to_remove:
        fp = str(item['filepath'])
        if fp not in by_file:
            by_file[fp] = []
        by_file[fp].append(item)

    # Process each file
    for filepath_str, items in sorted(by_file.items()):
        filepath = Path(filepath_str)

        print(f"\n{filepath.name}:")
        for item in items:
            print(f"  - {item['item_id']} ({item['char_count']} chars) -> keep in {item['primary']}")

        if not dry_run:
            removed = 0
            for item in items:
                if remove_exact_text_from_file(filepath, item['full_text']):
                    removed += 1
                else:
                    print(f"    WARNING: Could not find exact text for {item['item_id']}")
            print(f"  ✓ Removed {removed}/{len(items)} sections")

    print("\n" + "=" * 70)
    if dry_run:
        print("DRY RUN complete. Run without --dry-run to apply changes.")
    else:
        print(f"DONE. Attempted to remove {len(to_remove)} duplicate sections.")
    print("=" * 70)


if __name__ == "__main__":
    main()
