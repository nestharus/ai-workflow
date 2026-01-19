#!/usr/bin/env python3
"""
Show minor differences between plan.md and library files for exact/close matches.
Uses annotation-based splitting [(=ID)] to determine section boundaries.
"""

import re
from pathlib import Path
from difflib import unified_diff, SequenceMatcher


# Legal ID patterns (for [(=ID)] annotations)
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

# Annotation pattern for declarations
ANNOTATION_PATTERN = re.compile(r'\[\(=([^\]]+)\)\]')


def is_legal_id(text):
    """Check if text matches a legal ID pattern."""
    for pattern in ID_PATTERNS_LEGAL:
        if re.match(f'^{pattern}$', text):
            return True
    return False


def extract_sections_by_annotation(lines):
    """Extract sections based on [(=ID)] annotations.

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


def normalize_body(body):
    """Normalize body for comparison."""
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    return '\n'.join(lines)


def main():
    base = Path(__file__).parent
    plan_path = base / "plan.md"
    libs_dir = base / "libraries"

    # Read plan.md
    plan_content = plan_path.read_text(encoding='utf-8')
    plan_lines = plan_content.split('\n')

    # Extract sections from plan.md
    print("Extracting sections from plan.md...")
    plan_sections = extract_sections_by_annotation(plan_lines)
    print(f"Found {len(plan_sections)} sections in plan.md\n")

    # Extract from all library files
    library_sections = {}
    for lib_file in sorted(libs_dir.glob("*.md")):
        lib_name = lib_file.stem
        content = lib_file.read_text(encoding='utf-8')
        lines = content.split('\n')
        sections = extract_sections_by_annotation(lines)
        for id_name, (header, body, line_num) in sections.items():
            library_sections[id_name] = (header, body, lib_name, line_num)

    print(f"Found {len(library_sections)} sections in library files\n")

    # Find matches and categorize by similarity
    exact_matches = []
    close_matches = []
    partial_matches = []

    for id_name, (lib_header, lib_body, lib_name, lib_line) in sorted(library_sections.items()):
        if id_name not in plan_sections:
            continue

        plan_header, plan_body, plan_line = plan_sections[id_name]

        lib_body_norm = normalize_body(lib_body)
        plan_body_norm = normalize_body(plan_body)

        if lib_body_norm == plan_body_norm:
            exact_matches.append((id_name, lib_name, 100.0, plan_line, lib_line))
        elif lib_body_norm and plan_body_norm:
            sim = SequenceMatcher(None, plan_body_norm, lib_body_norm).ratio()
            if sim > 0.95:
                exact_matches.append((id_name, lib_name, sim * 100, plan_line, lib_line))
            elif sim > 0.80:
                close_matches.append((id_name, lib_name, sim * 100, plan_line, lib_line,
                                     plan_header, plan_body, lib_header, lib_body))
            elif sim > 0.50:
                partial_matches.append((id_name, lib_name, sim * 100, plan_line, lib_line,
                                       plan_header, plan_body, lib_header, lib_body))

    print("=" * 80)
    print("MINOR DIFF ANALYSIS: plan.md vs libraries (annotation-based)")
    print("=" * 80)

    print(f"\n--- Summary ---")
    print(f"Exact matches (>95%): {len(exact_matches)}")
    print(f"Close matches (80-95%): {len(close_matches)}")
    print(f"Partial matches (50-80%): {len(partial_matches)}")

    # Show exact matches that aren't 100%
    near_exact = [(id_name, lib, sim, pl, ll) for id_name, lib, sim, pl, ll in exact_matches if sim < 100]
    if near_exact:
        print(f"\n{'=' * 80}")
        print("NEAR-EXACT MATCHES (95-100%) - Minor differences:")
        print("=" * 80)
        for id_name, lib_name, sim, plan_line, lib_line in near_exact:
            print(f"\n  {id_name} ({lib_name}): {sim:.1f}%")
            print(f"    plan.md line {plan_line}, library line {lib_line}")

            # Get the actual bodies to show diff
            plan_header, plan_body, _ = plan_sections[id_name]
            lib_header, lib_body, _, _ = library_sections[id_name]

            plan_lines_list = [l.rstrip() for l in plan_body.split('\n')]
            lib_lines_list = [l.rstrip() for l in lib_body.split('\n')]

            # Show unified diff
            diff = list(unified_diff(plan_lines_list, lib_lines_list,
                                    fromfile='plan.md', tofile=f'{lib_name}.md',
                                    lineterm='', n=1))
            if diff:
                for line in diff[2:]:  # Skip --- and +++ lines
                    if line.startswith('@@'):
                        print(f"    {line}")
                    elif line.startswith('-'):
                        print(f"      PLAN: {line[1:][:60]}")
                    elif line.startswith('+'):
                        print(f"      LIB:  {line[1:][:60]}")

    # Show close matches
    if close_matches:
        print(f"\n{'=' * 80}")
        print("CLOSE MATCHES (80-95%) - Need review:")
        print("=" * 80)
        for id_name, lib_name, sim, plan_line, lib_line, plan_header, plan_body, lib_header, lib_body in close_matches:
            print(f"\n  {id_name} ({lib_name}): {sim:.1f}%")
            print(f"    plan.md line {plan_line}, library line {lib_line}")

            plan_lines_list = [l.rstrip() for l in plan_body.split('\n')]
            lib_lines_list = [l.rstrip() for l in lib_body.split('\n')]

            diff = list(unified_diff(plan_lines_list, lib_lines_list,
                                    fromfile='plan.md', tofile=f'{lib_name}.md',
                                    lineterm='', n=1))
            if diff:
                diff_count = 0
                for line in diff[2:]:
                    if line.startswith('@@'):
                        print(f"    {line}")
                    elif line.startswith('-'):
                        print(f"      PLAN: {line[1:][:70]}")
                        diff_count += 1
                    elif line.startswith('+'):
                        print(f"      LIB:  {line[1:][:70]}")
                        diff_count += 1
                    if diff_count > 20:  # Limit output
                        print(f"      ... (truncated)")
                        break

    # Show partial matches
    if partial_matches:
        print(f"\n{'=' * 80}")
        print("PARTIAL MATCHES (50-80%) - Significant differences:")
        print("=" * 80)
        for id_name, lib_name, sim, plan_line, lib_line, plan_header, plan_body, lib_header, lib_body in partial_matches[:10]:
            print(f"\n  {id_name} ({lib_name}): {sim:.1f}%")
            print(f"    plan.md: {len(plan_body)} chars, library: {len(lib_body)} chars")

    print(f"\n{'=' * 80}")
    print("RECOMMENDATIONS:")
    print("=" * 80)
    if near_exact:
        print(f"  - {len(near_exact)} near-exact matches: likely whitespace/formatting - sync from plan.md")
    if close_matches:
        print(f"  - {len(close_matches)} close matches: review diffs, sync from plan.md if appropriate")
    if partial_matches:
        print(f"  - {len(partial_matches)} partial matches: significant differences need investigation")


if __name__ == "__main__":
    main()
