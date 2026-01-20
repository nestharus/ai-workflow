#!/usr/bin/env python3
"""
Find items in library files that are not in libs.md.
Outputs each missing item with its location and content summary for assignment.
"""

import re
from pathlib import Path


def parse_libs_md(libs_path: Path) -> set[str]:
    """Parse libs.md to get all assigned item IDs."""
    content = libs_path.read_text(encoding='utf-8')

    assigned = set()
    for m in re.finditer(r'^- \(\[=([^\]]+)\]\)', content, re.MULTILINE):
        assigned.add(m.group(1).strip())

    return assigned


def extract_id_from_header(header: str) -> str | None:
    """Extract the ID from a header line."""
    clean = re.sub(r'^#+\s+', '', header).strip()

    patterns = [
        r'^(Comp\d+)',
        r'^(D\d+)',
        r'^(Algorithm \d+)',
        r'^(G\d+)',
        r'^(P\d+I\d+)',
        r'^(P\d+C\d+)',
        r'^(P\d+\.\d+)',
        r'^(Lean\d+)',
        r'^(NFG\d+)',
        r'^(S\d+)',
        r'^(C\d+)',
        r'^(P\d+I\d+)',
    ]

    for pat in patterns:
        m = re.match(pat, clean)
        if m:
            return m.group(1)

    return None


def get_section_body(lines: list[str], start_idx: int, max_lines: int = 20) -> str:
    """Extract first N lines of body from a section."""
    if start_idx >= len(lines):
        return ""

    first_line = lines[start_idx]
    match = re.match(r'^(#+)\s', first_line)
    if not match:
        return ""

    level = len(match.group(1))
    body_lines = []

    for i in range(start_idx + 1, min(start_idx + 1 + max_lines, len(lines))):
        line = lines[i]
        m = re.match(r'^(#+)\s', line)
        if m and len(m.group(1)) <= level:
            break
        body_lines.append(line.rstrip())

    return '\n'.join(body_lines).strip()


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
                    body = get_section_body(lines, i)
                    if item_id not in declarations:
                        declarations[item_id] = []
                    declarations[item_id].append({
                        'file': lib_name,
                        'line': i + 1,
                        'header': line.strip(),
                        'body_preview': body[:300] if body else "(empty)",
                    })
            i += 1

    return declarations


def categorize_id(item_id: str) -> str:
    """Categorize an ID for grouping."""
    if item_id.startswith('Algorithm'):
        return 'Algorithms'
    elif item_id.startswith('Comp'):
        return 'Components'
    elif item_id.startswith('D'):
        return 'Data Structures'
    elif item_id.startswith('G'):
        return 'Goals'
    elif re.match(r'^P\d+I', item_id):
        return 'Invariants'
    elif re.match(r'^P\d+C', item_id):
        return 'Claims'
    elif re.match(r'^P\d+\.', item_id):
        return 'Math'
    elif item_id.startswith('Lean'):
        return 'Lean'
    elif item_id.startswith('NFG'):
        return 'Non-functional Goals'
    elif item_id.startswith('S'):
        return 'Statements'
    elif item_id.startswith('C'):
        return 'Claims'
    else:
        return 'Other'


def main():
    base = Path(__file__).resolve().parents[2]
    libs_dir = base / "libraries"
    libs_md = base / "libs.md"

    # Get assigned items
    assigned = parse_libs_md(libs_md)
    print(f"Found {len(assigned)} items already in libs.md\n")

    # Scan library files
    declarations = scan_library_files(libs_dir)

    # Find missing
    missing = {}
    for item_id, occurrences in declarations.items():
        if item_id not in assigned:
            missing[item_id] = occurrences

    print(f"Found {len(missing)} items NOT in libs.md\n")
    print("=" * 70)

    # Group by category
    by_category = {}
    for item_id, occs in missing.items():
        cat = categorize_id(item_id)
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append((item_id, occs))

    # Output grouped by category
    for category in sorted(by_category.keys()):
        items = sorted(by_category[category], key=lambda x: x[0])
        print(f"\n## {category} ({len(items)} missing)\n")

        for item_id, occs in items:
            files = [f"{o['file']}" for o in occs]
            print(f"### {item_id}")
            print(f"Currently in: {', '.join(files)}")
            print(f"Header: {occs[0]['header']}")
            print(f"Preview: {occs[0]['body_preview'][:200]}...")
            print()


if __name__ == "__main__":
    main()
