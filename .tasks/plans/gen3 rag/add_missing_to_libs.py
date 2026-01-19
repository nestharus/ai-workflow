#!/usr/bin/env python3
"""
Add missing IDs from plan.md to their correct library files.
Determines library assignment based on ID prefix patterns.
"""

import re
from pathlib import Path

# Legal ID patterns
ID_PATTERNS_LEGAL = [
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

ANNOTATION_PATTERN = re.compile(r'\[\(=([^\]]+)\)\]')

# Library assignments based on ID prefix/pattern
# This maps ID patterns to their primary library
LIB_ASSIGNMENTS = {
    # P8 -> patterns (pattern-related)
    r'^P8\.\d+$': 'patterns',
    r'^P8I\d+$': 'patterns',
    r'^P8C\d+$': 'patterns',
    # T -> verification (test/theorem)
    r'^T\d+$': 'verification',
    # Comp -> workspace (components)
    r'^Comp\d+$': 'workspace',
    # G22, G23 -> check existing patterns
    r'^G22$': 'exploration',
    r'^G23$': 'exploration',
    # Algorithm 2, 21, 22 -> check plan context
    r'^Algorithm 2$': 'field',
    r'^Algorithm 21$': 'workspace',
    r'^Algorithm 22$': 'workspace',
    # P5 -> ingestion (grammar/parsing)
    r'^P5C\d+$': 'ingestion',
    r'^P5I\d+$': 'ingestion',
    # P2I6 -> field
    r'^P2I\d+$': 'field',
}


def is_legal_id(text):
    for pattern in ID_PATTERNS_LEGAL:
        if re.match(f'^{pattern}$', text):
            return True
    return False


def get_library_for_id(id_name):
    """Determine which library an ID belongs to."""
    for pattern, lib in LIB_ASSIGNMENTS.items():
        if re.match(pattern, id_name):
            return lib
    return None


def extract_sections_by_annotation(lines):
    """Extract sections based on [(=ID)] annotations."""
    sections = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        match = ANNOTATION_PATTERN.search(line)
        if match and is_legal_id(match.group(1)):
            id_name = match.group(1)
            header_line = line
            body_lines = []
            i += 1
            while i < len(lines):
                next_match = ANNOTATION_PATTERN.search(lines[i])
                if next_match and is_legal_id(next_match.group(1)):
                    break
                body_lines.append(lines[i])
                i += 1
            sections[id_name] = (header_line, '\n'.join(body_lines))
        else:
            i += 1
    return sections


def main():
    base = Path(__file__).parent
    plan_path = base / "plan.md"
    libs_dir = base / "libraries"

    # Read plan.md
    plan_content = plan_path.read_text(encoding='utf-8')
    plan_lines = plan_content.split('\n')
    plan_sections = extract_sections_by_annotation(plan_lines)
    print(f"Found {len(plan_sections)} sections in plan.md")

    # Get all library sections
    library_ids = set()
    for lib_file in libs_dir.glob("*.md"):
        content = lib_file.read_text(encoding='utf-8')
        lines = content.split('\n')
        sections = extract_sections_by_annotation(lines)
        library_ids.update(sections.keys())

    print(f"Found {len(library_ids)} sections in libraries")

    # Find missing
    missing = set(plan_sections.keys()) - library_ids
    print(f"\nMissing in libraries: {len(missing)}")

    # Group by target library
    by_library = {}
    unknown = []
    for id_name in sorted(missing):
        lib = get_library_for_id(id_name)
        if lib:
            if lib not in by_library:
                by_library[lib] = []
            by_library[lib].append(id_name)
        else:
            unknown.append(id_name)

    if unknown:
        print(f"\nUnknown library assignment for: {unknown}")

    # Add to each library
    for lib_name, ids in sorted(by_library.items()):
        lib_file = libs_dir / f"{lib_name}.md"
        if not lib_file.exists():
            print(f"Library {lib_name}.md does not exist, skipping {ids}")
            continue

        content = lib_file.read_text(encoding='utf-8')

        # Add each missing section at the end
        additions = []
        for id_name in ids:
            header, body = plan_sections[id_name]
            section = f"\n{header}\n{body}"
            additions.append(section)
            print(f"  Adding {id_name} to {lib_name}.md")

        if additions:
            new_content = content.rstrip() + '\n' + '\n'.join(additions) + '\n'
            lib_file.write_text(new_content, encoding='utf-8')
            print(f"{lib_name}.md: added {len(ids)} sections")

    print(f"\nTotal added: {sum(len(ids) for ids in by_library.values())}")


if __name__ == "__main__":
    main()
