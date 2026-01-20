#!/usr/bin/env python3
"""
Move items from wrong files to their correct library per libs.md.

Extracts section content from source file, adds to destination file, removes from source.
"""

import re
from pathlib import Path


def parse_libs_md(libs_path: Path) -> dict[str, str]:
    """Parse libs.md to extract item -> primary library mapping."""
    content = libs_path.read_text(encoding='utf-8')
    assignments = {}

    current_id = None
    current_primary = None

    for line in content.split('\n'):
        id_match = re.match(r'^- \(\[=([^\]]+)\]\)', line)
        if id_match:
            if current_id and current_primary:
                assignments[current_id] = current_primary
            current_id = id_match.group(1).strip()
            current_primary = None
            continue

        primary_match = re.match(r'^\s+- primary:\s*(\w+)', line)
        if primary_match:
            current_primary = primary_match.group(1).strip()

    if current_id and current_primary:
        assignments[current_id] = current_primary

    return assignments


def extract_id_from_header(header: str) -> str | None:
    """Extract the ID from a header line."""
    clean = re.sub(r'^#+\s+', '', header).strip()

    patterns = [
        r'^(Comp\d+)', r'^(D\d+)', r'^(Algorithm \d+)', r'^(G\d+)',
        r'^(P\d+I\d+)', r'^(P\d+C\d+)', r'^(P\d+\.\d+)', r'^(Lean\d+)',
        r'^(NFG\d+)', r'^(S\d+)', r'^(C\d+)', r'^(P6C\d+)', r'^(P9I\d+)',
    ]

    for pat in patterns:
        m = re.match(pat, clean)
        if m:
            return m.group(1)
    return None


def get_section_text(lines: list[str], start_idx: int) -> tuple[int, int, str]:
    """Get section start, end, and FULL TEXT (header + body)."""
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

    # Strip trailing blank lines
    while section_lines and section_lines[-1].strip() == '':
        section_lines.pop()

    return start_idx, end_idx, '\n'.join(section_lines)


def scan_library_file(lib_file: Path) -> dict[str, dict]:
    """Scan a library file for declarations."""
    declarations = {}
    content = lib_file.read_text(encoding='utf-8')
    lines = content.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r'^#{2,3}\s', line):
            item_id = extract_id_from_header(line)
            if item_id:
                start, end, full_text = get_section_text(lines, i)
                declarations[item_id] = {
                    'start': start,
                    'end': end,
                    'full_text': full_text,
                    'header': line.strip(),
                }
                i = end
                continue
        i += 1

    return declarations


def remove_section_from_file(filepath: Path, full_text: str) -> bool:
    """Remove a section from a file."""
    content = filepath.read_text(encoding='utf-8')

    # Try various patterns
    patterns = [
        f"\n\n{full_text}\n\n",
        f"\n\n{full_text}\n",
        f"\n{full_text}\n\n",
        f"\n{full_text}\n",
        f"\n\n---\n\n{full_text}\n\n",
        f"{full_text}\n\n---\n\n",
    ]

    for pattern in patterns:
        if pattern in content:
            replacement = "\n\n" if "\n\n" in pattern else "\n"
            new_content = content.replace(pattern, replacement, 1)
            while "\n\n\n" in new_content:
                new_content = new_content.replace("\n\n\n", "\n\n")
            filepath.write_text(new_content, encoding='utf-8')
            return True

    if full_text in content:
        new_content = content.replace(full_text, "", 1)
        while "\n\n\n" in new_content:
            new_content = new_content.replace("\n\n\n", "\n\n")
        filepath.write_text(new_content, encoding='utf-8')
        return True

    return False


def add_section_to_file(filepath: Path, full_text: str, item_id: str) -> bool:
    """Add a section to a file in appropriate location."""
    content = filepath.read_text(encoding='utf-8')

    # Find a good insertion point - after similar items or at end
    # For now, append before the last line or at end
    if content.strip():
        new_content = content.rstrip() + "\n\n---\n\n" + full_text + "\n"
    else:
        new_content = full_text + "\n"

    filepath.write_text(new_content, encoding='utf-8')
    return True


def main():
    import sys
    dry_run = '--dry-run' in sys.argv

    base = Path(__file__).parent
    libs_dir = base / "libraries"
    libs_md = base / "libs.md"

    print("=" * 70)
    print(f"MOVE ITEMS TO CORRECT LIBRARIES {'(DRY RUN)' if dry_run else ''}")
    print("=" * 70)

    # Parse libs.md for assignments
    assignments = parse_libs_md(libs_md)
    print(f"\nLoaded {len(assignments)} assignments from libs.md")

    # Scan all library files
    lib_contents = {}
    for lib_file in sorted(libs_dir.glob("*.md")):
        lib_name = lib_file.stem
        lib_contents[lib_name] = {
            'path': lib_file,
            'items': scan_library_file(lib_file),
        }

    # Find items in wrong files
    to_move = []
    for lib_name, lib_data in lib_contents.items():
        for item_id, item_data in lib_data['items'].items():
            if item_id in assignments:
                expected = assignments[item_id]
                if lib_name != expected:
                    to_move.append({
                        'item_id': item_id,
                        'current_file': lib_name,
                        'expected_file': expected,
                        'full_text': item_data['full_text'],
                        'header': item_data['header'],
                    })

    print(f"Found {len(to_move)} items in wrong files\n")

    # Group by destination
    by_dest = {}
    for item in to_move:
        dest = item['expected_file']
        if dest not in by_dest:
            by_dest[dest] = []
        by_dest[dest].append(item)

    # Process moves
    moved = 0
    failed = 0

    for dest, items in sorted(by_dest.items()):
        dest_path = libs_dir / f"{dest}.md"
        if not dest_path.exists():
            print(f"\nWARNING: Destination {dest}.md does not exist!")
            continue

        print(f"\n→ Moving to {dest}.md:")
        for item in items:
            src_path = libs_dir / f"{item['current_file']}.md"
            print(f"  - {item['item_id']} from {item['current_file']}")

            if not dry_run:
                # Add to destination first
                if add_section_to_file(dest_path, item['full_text'], item['item_id']):
                    # Then remove from source
                    if remove_section_from_file(src_path, item['full_text']):
                        moved += 1
                    else:
                        print(f"    WARNING: Could not remove from source")
                        failed += 1
                else:
                    print(f"    WARNING: Could not add to destination")
                    failed += 1
            else:
                moved += 1

    print("\n" + "=" * 70)
    if dry_run:
        print(f"DRY RUN: Would move {moved} items")
    else:
        print(f"Moved {moved} items, {failed} failed")
    print("=" * 70)


if __name__ == "__main__":
    main()
