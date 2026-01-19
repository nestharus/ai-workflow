#!/usr/bin/env python3
"""
Verify library IDs match plan.md - compare sections by [(=ID)] annotations.
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


def extract_sections_by_annotation(file_path):
    """Extract sections based on [(=ID)] annotations."""
    content = file_path.read_text()
    lines = content.splitlines()

    sections = {}  # id -> (header_line, body_text, line_num)
    annotation_pattern = re.compile(r'\[\(=([^\]]+)\)\]')

    i = 0
    while i < len(lines):
        line = lines[i]
        match = annotation_pattern.search(line)

        if match and is_legal_id(match.group(1)):
            id_name = match.group(1)
            header_line = line
            line_num = i + 1

            # Collect body until next annotation or EOF
            body_lines = []
            i += 1
            while i < len(lines):
                next_match = annotation_pattern.search(lines[i])
                if next_match and is_legal_id(next_match.group(1)):
                    break
                body_lines.append(lines[i])
                i += 1

            sections[id_name] = (header_line, '\n'.join(body_lines).strip(), line_num)
        else:
            i += 1

    return sections


def normalize_body(body):
    """Normalize body for comparison."""
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    return '\n'.join(lines)


def extract_label(header_line):
    """Extract label from header line (text before [(=ID)] annotation)."""
    # Remove markdown prefix (##, ###, ####)
    header = re.sub(r'^#+\s*', '', header_line)
    # Remove ID annotation and everything after
    header = re.sub(r'\s*\[\(=[^\]]+\)\].*$', '', header)
    return header.strip()


def main():
    print("Extracting sections from plan.md...")
    plan_sections = extract_sections_by_annotation(PLAN_MD)
    print(f"Found {len(plan_sections)} sections in plan.md\n")

    # Extract from all library files
    library_sections = {}

    for lib_file in sorted(LIBS_DIR.glob("*.md")):
        lib_name = lib_file.stem
        sections = extract_sections_by_annotation(lib_file)
        for id_name, (header, body, line_num) in sections.items():
            library_sections[id_name] = (header, body, lib_name, line_num)

    print(f"Found {len(library_sections)} sections in library files\n")

    # Compare labels and bodies
    label_mismatches = []
    body_mismatches = []
    missing_in_plan = []
    missing_in_libraries = []

    for id_name, (lib_header, lib_body, lib_name, line_num) in sorted(library_sections.items()):
        if id_name not in plan_sections:
            missing_in_plan.append((id_name, lib_name))
            continue

        plan_header, plan_body, plan_line = plan_sections[id_name]

        # Compare labels
        lib_label = extract_label(lib_header)
        plan_label = extract_label(plan_header)
        if lib_label != plan_label:
            label_mismatches.append((id_name, lib_name, lib_label, plan_label))

        # Compare bodies
        lib_body_norm = normalize_body(lib_body)
        plan_body_norm = normalize_body(plan_body)

        if lib_body_norm != plan_body_norm:
            body_mismatches.append((id_name, lib_name, len(lib_body_norm), len(plan_body_norm)))

    for id_name in plan_sections:
        if id_name not in library_sections:
            missing_in_libraries.append(id_name)

    # Report
    print("=" * 70)
    print("LABEL MISMATCHES:")
    print("=" * 70)
    if label_mismatches:
        for id_name, lib_name, lib_label, plan_label in label_mismatches:
            print(f"\n  {id_name} ({lib_name}):")
            print(f"    Library: {lib_label}")
            print(f"    Plan:    {plan_label}")
    else:
        print("  None - all labels match!")

    print("\n" + "=" * 70)
    print("BODY MISMATCHES:")
    print("=" * 70)
    if body_mismatches:
        for id_name, lib_name, lib_len, plan_len in body_mismatches:
            print(f"  {id_name} ({lib_name}): library={lib_len} chars, plan={plan_len} chars")
    else:
        print("  None - all bodies match!")

    print("\n" + "=" * 70)
    print("MISSING IN PLAN:")
    print("=" * 70)
    if missing_in_plan:
        for id_name, lib_name in missing_in_plan:
            print(f"  {id_name} ({lib_name})")
    else:
        print("  None")

    print("\n" + "=" * 70)
    print("MISSING IN LIBRARIES:")
    print("=" * 70)
    if missing_in_libraries:
        for id_name in missing_in_libraries:
            print(f"  {id_name}")
    else:
        print("  None")

    print("\n" + "=" * 70)
    print("SUMMARY:")
    print("=" * 70)
    print(f"  Plan sections: {len(plan_sections)}")
    print(f"  Library sections: {len(library_sections)}")
    print(f"  Label mismatches: {len(label_mismatches)}")
    print(f"  Body mismatches: {len(body_mismatches)}")
    print(f"  Missing in plan: {len(missing_in_plan)}")
    print(f"  Missing in libraries: {len(missing_in_libraries)}")


if __name__ == "__main__":
    main()
