#!/usr/bin/env python3
"""
Deep content verification: compare libraries/ content against plan.md.

Checks:
1. Every section in libraries/ exists in plan.md
2. Content is unmodified (exact match)
3. Reports missing sections and modifications
"""

import re
from pathlib import Path
from difflib import unified_diff, SequenceMatcher


def extract_sections_from_library(content: str) -> list[dict]:
    """Extract sections from a library file."""
    sections = []
    lines = content.split('\n')

    current_section = None
    current_content = []
    current_start = 0

    for i, line in enumerate(lines):
        # Match section headers: ## only (not ###, which are subsections)
        if re.match(r'^##\s+\S', line) and not line.startswith('###'):
            # Save previous section
            if current_section:
                sections.append({
                    'header': current_section,
                    'content': '\n'.join(current_content).strip(),
                    'start_line': current_start
                })

            current_section = line.strip()
            current_content = [line]
            current_start = i + 1
        elif current_section:
            # Skip separator lines at the start
            if line.strip() == '---' and len(current_content) == 1:
                continue
            current_content.append(line)

    # Don't forget last section
    if current_section:
        sections.append({
            'header': current_section,
            'content': '\n'.join(current_content).strip(),
            'start_line': current_start
        })

    return sections


def find_section_in_plan(header: str, plan_lines: list[str]) -> tuple[int, str]:
    """Find a section in plan.md by header. Returns (line_num, full_content)."""
    # Normalize header for matching
    header_text = re.sub(r'^#{2,3}\s+', '', header).strip()

    # First pass: exact match
    for i, line in enumerate(plan_lines):
        if re.match(r'^#{2,3}\s', line):
            plan_header_text = re.sub(r'^#{2,3}\s+', '', line).strip()

            if header_text == plan_header_text:
                # Extract content until next header of same/higher level
                level = len(re.match(r'^(#+)', line).group(1))
                content_lines = [line]

                for j in range(i + 1, len(plan_lines)):
                    next_line = plan_lines[j]
                    match = re.match(r'^(#+)\s', next_line)
                    if match and len(match.group(1)) <= level:
                        break
                    content_lines.append(next_line)

                return i + 1, '\n'.join(content_lines).strip()

    # Second pass: fuzzy match (but avoid partial algorithm/goal matches)
    for i, line in enumerate(plan_lines):
        if re.match(r'^#{2,3}\s', line):
            plan_header_text = re.sub(r'^#{2,3}\s+', '', line).strip()

            # Avoid partial matches for numbered items
            if re.match(r'^(Algorithm|G)\s*\d+', header_text):
                # For Algorithm X or GX, require exact prefix match
                lib_prefix = re.match(r'^(Algorithm\s*\d+|G\d+)', header_text)
                plan_prefix = re.match(r'^(Algorithm\s*\d+|G\d+)', plan_header_text)
                if lib_prefix and plan_prefix and lib_prefix.group(1) != plan_prefix.group(1):
                    continue

            # Match if headers are similar enough
            if header_text in plan_header_text or plan_header_text in header_text:
                # Extract content until next header of same/higher level
                level = len(re.match(r'^(#+)', line).group(1))
                content_lines = [line]

                for j in range(i + 1, len(plan_lines)):
                    next_line = plan_lines[j]
                    match = re.match(r'^(#+)\s', next_line)
                    if match and len(match.group(1)) <= level:
                        break
                    content_lines.append(next_line)

                return i + 1, '\n'.join(content_lines).strip()

    return -1, ""


def normalize_content(content: str) -> str:
    """Normalize content for comparison (strip trailing whitespace, normalize newlines)."""
    lines = content.split('\n')
    lines = [line.rstrip() for line in lines]
    # Remove trailing empty lines
    while lines and not lines[-1]:
        lines.pop()
    return '\n'.join(lines)


def compare_content(lib_content: str, plan_content: str) -> tuple[bool, float, list[str]]:
    """Compare two content blocks. Returns (is_match, similarity, diff_lines)."""
    lib_norm = normalize_content(lib_content)
    plan_norm = normalize_content(plan_content)

    if lib_norm == plan_norm:
        return True, 1.0, []

    # Calculate similarity
    similarity = SequenceMatcher(None, lib_norm, plan_norm).ratio()

    # Generate diff
    lib_lines = lib_norm.split('\n')
    plan_lines = plan_norm.split('\n')
    diff = list(unified_diff(plan_lines, lib_lines, lineterm='', n=1))

    return False, similarity, diff


def main():
    base = Path(__file__).parent
    libraries_dir = base / "libraries"
    plan_path = base / "plan.md"

    # Read plan.md
    plan_content = plan_path.read_text(encoding='utf-8')
    plan_lines = plan_content.split('\n')

    print("=" * 70)
    print("DEEP CONTENT VERIFICATION")
    print("=" * 70)

    total_sections = 0
    exact_matches = 0
    close_matches = 0  # >95% similar
    modifications = []
    missing_in_plan = []

    # Process each library file
    for lib_file in sorted(libraries_dir.glob("*.md")):
        lib_content = lib_file.read_text(encoding='utf-8')
        sections = extract_sections_from_library(lib_content)

        print(f"\n{lib_file.name}: {len(sections)} sections")

        for section in sections:
            total_sections += 1
            header = section['header']
            lib_sect_content = section['content']

            # Skip library header/description
            if header.startswith('# ') and 'Library' in header:
                total_sections -= 1
                continue

            # Find in plan.md
            plan_line, plan_sect_content = find_section_in_plan(header, plan_lines)

            if plan_line == -1:
                missing_in_plan.append({
                    'library': lib_file.name,
                    'header': header,
                    'lib_line': section['start_line']
                })
                continue

            # Compare content
            is_match, similarity, diff = compare_content(lib_sect_content, plan_sect_content)

            if is_match:
                exact_matches += 1
            elif similarity > 0.95:
                close_matches += 1
                modifications.append({
                    'library': lib_file.name,
                    'header': header,
                    'plan_line': plan_line,
                    'similarity': similarity,
                    'diff': diff[:20],  # First 20 diff lines
                    'type': 'minor'
                })
            else:
                modifications.append({
                    'library': lib_file.name,
                    'header': header,
                    'plan_line': plan_line,
                    'similarity': similarity,
                    'diff': diff[:30],
                    'type': 'major'
                })

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"\nTotal sections checked: {total_sections}")
    print(f"Exact matches: {exact_matches} ({100*exact_matches/total_sections:.1f}%)")
    print(f"Close matches (>95%): {close_matches}")
    print(f"Modifications: {len(modifications)}")
    print(f"Missing in plan.md: {len(missing_in_plan)}")

    # Report modifications
    if modifications:
        print("\n" + "=" * 70)
        print("MODIFICATIONS DETECTED")
        print("=" * 70)

        major = [m for m in modifications if m['type'] == 'major']
        minor = [m for m in modifications if m['type'] == 'minor']

        if major:
            print(f"\n--- MAJOR MODIFICATIONS ({len(major)}) ---")
            for mod in major[:10]:
                print(f"\n  {mod['library']}: {mod['header'][:50]}")
                print(f"  Plan line: {mod['plan_line']}, Similarity: {mod['similarity']*100:.1f}%")
                print("  Diff preview:")
                for line in mod['diff'][:5]:
                    if line.startswith('-'):
                        print(f"    PLAN: {line[1:][:60]}")
                    elif line.startswith('+'):
                        print(f"    LIB:  {line[1:][:60]}")

        if minor:
            print(f"\n--- MINOR MODIFICATIONS ({len(minor)}) ---")
            for mod in minor[:10]:
                print(f"  {mod['library']}: {mod['header'][:50]} ({mod['similarity']*100:.1f}%)")

    # Report missing
    if missing_in_plan:
        print("\n" + "=" * 70)
        print("SECTIONS IN LIBRARIES BUT NOT FOUND IN PLAN.MD")
        print("=" * 70)
        for miss in missing_in_plan[:20]:
            print(f"  {miss['library']}: {miss['header'][:60]}")
        if len(missing_in_plan) > 20:
            print(f"  ... and {len(missing_in_plan) - 20} more")

    # Check for sections in plan.md not in libraries
    print("\n" + "=" * 70)
    print("CHECKING FOR SECTIONS IN PLAN.MD NOT IN LIBRARIES")
    print("=" * 70)

    # Get all headers from libraries
    all_lib_headers = set()
    for lib_file in libraries_dir.glob("*.md"):
        lib_content = lib_file.read_text(encoding='utf-8')
        for section in extract_sections_from_library(lib_content):
            header_text = re.sub(r'^#{2,3}\s+', '', section['header']).strip()
            all_lib_headers.add(header_text)

    # Find plan headers not in libraries
    missing_from_libs = []
    for i, line in enumerate(plan_lines):
        if re.match(r'^#{2,3}\s+\S', line):
            header_text = re.sub(r'^#{2,3}\s+', '', line).strip()

            # Skip section organizers
            if any(x in header_text.lower() for x in ['data structure', 'algorithm', 'invariant',
                   'claim', 'proof', 'lean', 'math', 'goal', 'reference']):
                continue

            # Check if in libraries
            found = header_text in all_lib_headers
            for lib_h in all_lib_headers:
                if header_text in lib_h or lib_h in header_text:
                    found = True
                    break

            if not found:
                missing_from_libs.append((i + 1, header_text))

    if missing_from_libs:
        print(f"\nSections in plan.md not found in libraries: {len(missing_from_libs)}")
        for line_num, header in missing_from_libs[:30]:
            print(f"  L{line_num}: {header[:60]}")
        if len(missing_from_libs) > 30:
            print(f"  ... and {len(missing_from_libs) - 30} more")
    else:
        print("\nAll plan.md sections accounted for in libraries!")

    return 0 if not modifications and not missing_in_plan else 1


if __name__ == "__main__":
    exit(main())
