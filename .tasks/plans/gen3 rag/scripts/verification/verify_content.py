#!/usr/bin/env python3
"""
Content verification: find plan.md elements and match by body content in libraries.

Approach:
1. Find all declared IDs in plan.md via ([=ID]) annotations
2. For declarations, extract body and match to libraries
3. Track references via (@[+ID]) usage
"""

import re
from pathlib import Path
from difflib import SequenceMatcher


# Legal ID patterns (for ([=ID]) declarations)
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
    r'P\d+',
    r'Lean\d+',
    r'NFG\d+',
    r'Gap G\d+\.\d+',
]

# Annotation pattern for declarations: ([=ID])
ANNOTATION_PATTERN = re.compile(r'\(\[=([^\]]+)\]\)')


def extract_all_declared_ids(lines):
    """Extract every ID declared via ([=ID]) anywhere, including non-section IDs like P#."""
    declared = set()
    for line in lines:
        for match in ANNOTATION_PATTERN.finditer(line):
            declared.add(match.group(1))
    return declared


def is_legal_id(text):
    """Check if text matches a legal ID pattern."""
    for pattern in ID_PATTERNS_LEGAL:
        if re.match(f'^{pattern}$', text):
            return True
    return False


def extract_sections_by_annotation(lines):
    """Extract sections based on ([=ID]) declarations.

    Returns: {id: (header_line, body_text, line_num)}
    """
    sections = {}

    i = 0
    while i < len(lines):
        line = lines[i]
        match = ANNOTATION_PATTERN.search(line)

        if match and is_legal_id(match.group(1)):
            id_name = match.group(1)
            header_line = line
            line_num = i + 1

            # Collect body until next annotation or EOF
            body_lines = []
            i += 1
            while i < len(lines):
                next_match = ANNOTATION_PATTERN.search(lines[i])
                if next_match and is_legal_id(next_match.group(1)):
                    break
                body_lines.append(lines[i])
                i += 1

            sections[id_name] = (header_line, '\n'.join(body_lines).strip(), line_num)
        else:
            i += 1

    return sections


def find_references(lines):
    """Find all (@[+ID]) references in lines."""
    ref_pattern = re.compile(r'\(@\[\+([^\]]+)\]\)')
    references = {}  # id -> [line_nums]

    for idx, line in enumerate(lines):
        for match in ref_pattern.finditer(line):
            ref_id = match.group(1)
            if ref_id not in references:
                references[ref_id] = []
            references[ref_id].append(idx + 1)

    return references


def normalize_body(body):
    """Normalize body for comparison."""
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    return '\n'.join(lines)


def extract_label(header_line):
    """Extract label from header line (text before ([=ID]) declaration)."""
    header = re.sub(r'^#+\s*', '', header_line)
    header = re.sub(r'\s*\(\[=[^\]]+\]\).*$', '', header)
    return header.strip()


def main():
    base = Path(__file__).resolve().parents[2]
    plan_path = base / "plan.md"
    libs_dir = base / "libraries"

    # Read plan.md
    plan_content = plan_path.read_text(encoding='utf-8')
    plan_lines = plan_content.split('\n')

    # Extract sections from plan.md using declaration-based splitting
    print("Extracting sections from plan.md...")
    plan_sections = extract_sections_by_annotation(plan_lines)
    plan_declared_ids = extract_all_declared_ids(plan_lines)
    print(f"Found {len(plan_sections)} sections in plan.md\n")

    # Extract from all library files
    library_sections = {}
    library_declared_ids = set()
    for lib_file in sorted(libs_dir.glob("*.md")):
        lib_name = lib_file.stem
        content = lib_file.read_text(encoding='utf-8')
        lines = content.split('\n')
        library_declared_ids |= extract_all_declared_ids(lines)
        sections = extract_sections_by_annotation(lines)
        for id_name, (header, body, line_num) in sections.items():
            library_sections[id_name] = (header, body, lib_name, line_num)

    print(f"Found {len(library_sections)} sections in library files\n")

    # Find references in plan and libraries
    plan_refs = find_references(plan_lines)
    lib_refs = {}
    for lib_file in sorted(libs_dir.glob("*.md")):
        content = lib_file.read_text(encoding='utf-8')
        lines = content.split('\n')
        refs = find_references(lines)
        for ref_id, line_nums in refs.items():
            if ref_id not in lib_refs:
                lib_refs[ref_id] = []
            lib_refs[ref_id].extend([(lib_file.stem, ln) for ln in line_nums])

    print("=" * 70)
    print("CONTENT VERIFICATION: plan.md vs libraries/ (annotation-based)")
    print("=" * 70)

    # Compare bodies
    exact_matches = 0
    close_matches = 0
    partial_matches = 0
    mismatches = []
    missing_in_plan = []
    missing_in_libraries = []

    for id_name, (lib_header, lib_body, lib_name, line_num) in sorted(library_sections.items()):
        if id_name not in plan_sections:
            missing_in_plan.append((id_name, lib_name))
            continue

        plan_header, plan_body, plan_line = plan_sections[id_name]

        # Compare bodies
        lib_body_norm = normalize_body(lib_body)
        plan_body_norm = normalize_body(plan_body)

        if lib_body_norm == plan_body_norm:
            exact_matches += 1
        elif lib_body_norm and plan_body_norm:
            sim = SequenceMatcher(None, plan_body_norm, lib_body_norm).ratio()
            if sim > 0.95:
                exact_matches += 1
            elif sim > 0.80:
                close_matches += 1
            elif sim > 0.50:
                partial_matches += 1
                mismatches.append({
                    'id': id_name,
                    'lib': lib_name,
                    'similarity': sim,
                    'plan_len': len(plan_body_norm),
                    'lib_len': len(lib_body_norm),
                    'type': 'partial'
                })
            else:
                mismatches.append({
                    'id': id_name,
                    'lib': lib_name,
                    'similarity': sim,
                    'plan_len': len(plan_body_norm),
                    'lib_len': len(lib_body_norm),
                    'type': 'mismatch'
                })
        elif plan_body_norm and not lib_body_norm:
            mismatches.append({
                'id': id_name,
                'lib': lib_name,
                'similarity': 0,
                'plan_len': len(plan_body_norm),
                'lib_len': 0,
                'type': 'empty_lib'
            })
        else:
            exact_matches += 1

    for id_name in plan_sections:
        if id_name not in library_sections:
            missing_in_libraries.append(id_name)

    # Find orphan references: referenced IDs must be declared somewhere via ([=ID])
    all_declared = plan_declared_ids | library_declared_ids
    orphan_refs = []
    for ref_id, locations in {**plan_refs, **lib_refs}.items():
        if ref_id not in all_declared:
            orphan_refs.append((ref_id, len(locations) if isinstance(locations, list) else locations))

    # Report
    print(f"\n--- ID Match Results ---")
    print(f"Exact matches (>95%): {exact_matches}")
    print(f"Close matches (80-95%): {close_matches}")
    print(f"Partial matches (50-80%): {partial_matches}")
    print(f"Mismatches (<50% or empty): {len([m for m in mismatches if m['type'] in ('mismatch', 'empty_lib')])}")
    print(f"Missing in plan: {len(missing_in_plan)}")
    print(f"Missing in libraries: {len(missing_in_libraries)}")
    print(f"Orphan references: {len(orphan_refs)}")

    if mismatches:
        print("\n" + "=" * 70)
        print(f"CONTENT DIFFERENCES - {len(mismatches)} IDs")
        print("=" * 70)
        for m in sorted(mismatches, key=lambda x: x['similarity'])[:30]:
            print(f"  {m['id']} ({m['lib']}): {m['similarity']*100:.0f}% - plan:{m['plan_len']} lib:{m['lib_len']} chars")

    if missing_in_libraries:
        print("\n" + "=" * 70)
        print(f"MISSING IN LIBRARIES - {len(missing_in_libraries)} IDs")
        print("=" * 70)
        for id_name in missing_in_libraries[:50]:
            print(f"  {id_name}")
        if len(missing_in_libraries) > 50:
            print(f"  ... and {len(missing_in_libraries) - 50} more")

    if missing_in_plan:
        print("\n" + "=" * 70)
        print(f"MISSING IN PLAN - {len(missing_in_plan)} IDs")
        print("=" * 70)
        for id_name, lib_name in missing_in_plan[:20]:
            print(f"  {id_name} ({lib_name})")

    if orphan_refs:
        print("\n" + "=" * 70)
        print(f"ORPHAN REFERENCES - {len(orphan_refs)} IDs referenced but never declared")
        print("=" * 70)
        for ref_id, count in orphan_refs[:20]:
            print(f"  {ref_id} - {count} refs")

    print("\n" + "=" * 70)
    print("SUMMARY:")
    print("=" * 70)
    print(f"  Plan sections: {len(plan_sections)}")
    print(f"  Library sections: {len(library_sections)}")
    print(f"  Exact/close matches: {exact_matches + close_matches}")
    print(f"  Mismatches: {len(mismatches)}")
    print(f"  Missing in libraries: {len(missing_in_libraries)}")
    print(f"  Missing in plan: {len(missing_in_plan)}")
    print(f"  Orphan references: {len(orphan_refs)}")

    return 0 if len(missing_in_libraries) == 0 and len(mismatches) == 0 else 1


if __name__ == "__main__":
    exit(main())
