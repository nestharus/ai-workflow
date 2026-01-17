#!/usr/bin/env python3
"""
Compare the two P6 sections in plan.md to determine if they are 100% identical.
"""

import re
from pathlib import Path
from difflib import unified_diff, SequenceMatcher

def find_p6_sections(content: str) -> list[tuple[int, int, str]]:
    """Find all P6 sections in the document."""
    lines = content.split('\n')
    sections = []

    # Look for P6 headers
    p6_starts = []
    for i, line in enumerate(lines):
        # Match "# P6" or "## P6" headers
        if re.match(r'^#+ P6[:\s]', line) or 'P6: Hippocampus' in line:
            p6_starts.append((i, line))

    print(f"Found {len(p6_starts)} P6 header occurrences:")
    for idx, (line_num, line) in enumerate(p6_starts):
        print(f"  {idx+1}. Line {line_num + 1}: {line[:80]}")

    return p6_starts


def extract_p6_blocks(content: str) -> dict:
    """Extract P6-related content blocks for comparison."""
    lines = content.split('\n')

    blocks = {
        'goals': [],
        'invariants': [],
        'data_structures': [],
        'math': [],
        'algorithms': [],
        'claims': [],
        'lean': []
    }

    # Find all G22-G29 occurrences (P6 goals)
    for i, line in enumerate(lines):
        if re.search(r'\bG2[2-9]\b', line):
            blocks['goals'].append((i + 1, line.strip()))

    # Find all P6I occurrences (P6 invariants)
    for i, line in enumerate(lines):
        if re.search(r'\bP6I\d', line):
            blocks['invariants'].append((i + 1, line.strip()))

    # Find all P6C occurrences (P6 claims)
    for i, line in enumerate(lines):
        if re.search(r'\bP6C\d', line):
            blocks['claims'].append((i + 1, line.strip()))

    # Find all P6.# math sections
    for i, line in enumerate(lines):
        if re.search(r'\bP6\.\d', line):
            blocks['math'].append((i + 1, line.strip()))

    # Find Algorithm 24-32 (P6 algorithms)
    for i, line in enumerate(lines):
        if re.search(r'Algorithm\s*(2[4-9]|3[0-2])\b', line):
            blocks['algorithms'].append((i + 1, line.strip()))

    return blocks


def find_standalone_p6_section(content: str) -> tuple[int, int] | None:
    """Find the standalone P6 section at the end of the document."""
    lines = content.split('\n')

    # Look for "# P6:" as a top-level header (standalone section)
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith('# P6:') or line.strip() == '# P6: Hippocampus control plane':
            start = i
            break

    if start is None:
        return None

    # Find where this section ends (next # header or EOF)
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith('# ') and not lines[i].startswith('# P6'):
            end = i
            break

    return (start, end)


def compare_content_blocks(content: str):
    """Compare P6 content to find duplicates."""
    lines = content.split('\n')

    # Find the standalone P6 section
    standalone = find_standalone_p6_section(content)

    if standalone:
        start, end = standalone
        print(f"\nStandalone P6 section found: lines {start + 1} to {end}")
        print(f"Section length: {end - start} lines")

        standalone_text = '\n'.join(lines[start:end])

        # Now find all P6 content in the integrated sections (before standalone)
        integrated_lines = lines[:start]

        # Extract specific P6 elements from both
        print("\n" + "="*60)
        print("DETAILED COMPARISON")
        print("="*60)

        # Compare goals G22-G29
        compare_pattern(lines, start, 'G2[2-9]', 'Goals G22-G29')

        # Compare P6 invariants
        compare_pattern(lines, start, 'P6I\\d', 'Invariants P6I#')

        # Compare P6 claims
        compare_pattern(lines, start, 'P6C\\d', 'Claims P6C#')

        # Compare P6 math
        compare_pattern(lines, start, 'P6\\.\\d', 'Math P6.#')

        # Compare algorithms 24-32
        compare_pattern(lines, start, 'Algorithm\\s*(2[4-9]|3[0-2])', 'Algorithms 24-32')
    else:
        print("\nNo standalone P6 section found")


def compare_pattern(lines: list, split_point: int, pattern: str, label: str):
    """Compare occurrences of a pattern before and after split point."""
    before = []
    after = []

    for i, line in enumerate(lines):
        if re.search(pattern, line):
            if i < split_point:
                before.append((i + 1, line.strip()[:100]))
            else:
                after.append((i + 1, line.strip()[:100]))

    print(f"\n{label}:")
    print(f"  Integrated section: {len(before)} occurrences")
    print(f"  Standalone section: {len(after)} occurrences")

    if before and after:
        # Check if content matches
        before_text = [b[1] for b in before]
        after_text = [a[1] for a in after]

        # Find matching lines
        matches = 0
        for bt in before_text:
            if bt in after_text:
                matches += 1

        if matches == len(before_text) == len(after_text):
            print(f"  STATUS: IDENTICAL ({matches} matches)")
        else:
            print(f"  STATUS: DIFFERENT")
            print(f"    Matches: {matches}")
            print(f"    Before unique: {len(set(before_text) - set(after_text))}")
            print(f"    After unique: {len(set(after_text) - set(before_text))}")

            # Show differences
            for bt in before_text:
                if bt not in after_text:
                    print(f"    ONLY IN INTEGRATED: {bt[:80]}")
            for at in after_text:
                if at not in before_text:
                    print(f"    ONLY IN STANDALONE: {at[:80]}")


def extract_full_section_text(lines: list, start_pattern: str, start_line: int) -> list[str]:
    """Extract full section text starting from a line matching pattern."""
    section_lines = []
    in_section = False

    for i in range(start_line, len(lines)):
        line = lines[i]
        if re.search(start_pattern, line):
            in_section = True

        if in_section:
            # Stop at next major header
            if line.startswith('## ') and not re.search(start_pattern, line):
                break
            section_lines.append(line)

    return section_lines


def main():
    plan_path = Path(__file__).parent / "plan.md"
    content = plan_path.read_text(encoding='utf-8')

    print("="*60)
    print("P6 DUPLICATION ANALYSIS")
    print("="*60)

    # Find P6 headers
    find_p6_sections(content)

    # Compare content blocks
    compare_content_blocks(content)

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    blocks = extract_p6_blocks(content)
    for category, items in blocks.items():
        if items:
            print(f"\n{category.upper()}: {len(items)} total occurrences")
            # Group by content to find exact duplicates
            by_content = {}
            for line_num, text in items:
                if text not in by_content:
                    by_content[text] = []
                by_content[text].append(line_num)

            duplicates = {k: v for k, v in by_content.items() if len(v) > 1}
            if duplicates:
                print(f"  DUPLICATES FOUND: {len(duplicates)}")
                for text, line_nums in list(duplicates.items())[:3]:
                    print(f"    Lines {line_nums}: {text[:60]}...")


if __name__ == "__main__":
    main()
