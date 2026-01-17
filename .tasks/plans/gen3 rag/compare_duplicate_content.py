#!/usr/bin/env python3
"""
Compare full content under duplicate headers to determine:
1. TRUE DUPLICATES: Same header + same content -> safe to remove one
2. FALSE DUPLICATES: Same header + different content -> need to rename headers

This is the safe approach before any removal.
"""

import re
from pathlib import Path
from collections import defaultdict
from difflib import SequenceMatcher


def extract_sections(lines: list[str]) -> list[dict]:
    """Extract all sections with their full content."""
    sections = []
    current_section = None

    for i, line in enumerate(lines):
        match = re.match(r'^(#+)\s+(.+)$', line)
        if match:
            # Save previous section
            if current_section:
                current_section['end_line'] = i
                current_section['content'] = '\n'.join(lines[current_section['start_line']:i])
                sections.append(current_section)

            # Start new section
            level = len(match.group(1))
            header_text = match.group(2).strip()
            current_section = {
                'line_num': i + 1,
                'start_line': i,
                'level': level,
                'header': header_text,
                'full_header': line.strip(),
            }

    # Don't forget last section
    if current_section:
        current_section['end_line'] = len(lines)
        current_section['content'] = '\n'.join(lines[current_section['start_line']:])
        sections.append(current_section)

    return sections


def get_section_until_same_level(lines: list[str], start_idx: int, level: int) -> str:
    """Get content from start until next header of same or higher level."""
    content_lines = [lines[start_idx]]

    for i in range(start_idx + 1, len(lines)):
        line = lines[i]
        match = re.match(r'^(#+)\s', line)
        if match and len(match.group(1)) <= level:
            break
        content_lines.append(line)

    return '\n'.join(content_lines)


def normalize_content(content: str) -> str:
    """Normalize content for comparison (strip whitespace, normalize newlines)."""
    lines = content.split('\n')
    # Strip trailing whitespace from each line, remove empty lines at start/end
    lines = [line.rstrip() for line in lines]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return '\n'.join(lines)


def similarity(s1: str, s2: str) -> float:
    """Calculate similarity ratio between two strings."""
    return SequenceMatcher(None, s1, s2).ratio()


def main():
    plan_path = Path(__file__).parent / "plan.md"
    content = plan_path.read_text(encoding='utf-8')
    lines = content.split('\n')

    print("="*70)
    print("DUPLICATE CONTENT ANALYSIS")
    print("="*70)

    # Find all headers and group by text
    header_groups = defaultdict(list)

    for i, line in enumerate(lines):
        match = re.match(r'^(#+)\s+(.+)$', line)
        if match:
            level = len(match.group(1))
            header_text = match.group(2).strip()

            # Get full content under this header
            section_content = get_section_until_same_level(lines, i, level)

            header_groups[header_text].append({
                'line': i + 1,
                'level': level,
                'content': section_content,
                'content_normalized': normalize_content(section_content),
                'content_lines': section_content.count('\n') + 1
            })

    # Find duplicates
    duplicates = {k: v for k, v in header_groups.items() if len(v) > 1}

    print(f"\nTotal duplicate header groups: {len(duplicates)}")

    true_duplicates = []
    false_duplicates = []

    for header, occurrences in sorted(duplicates.items()):
        print(f"\n{'='*70}")
        print(f"HEADER: '{header[:60]}{'...' if len(header) > 60 else ''}'")
        print(f"Occurrences: {len(occurrences)}")
        print("="*70)

        # Compare all pairs
        all_identical = True
        for i, occ1 in enumerate(occurrences):
            for j, occ2 in enumerate(occurrences):
                if i >= j:
                    continue

                sim = similarity(occ1['content_normalized'], occ2['content_normalized'])
                identical = sim > 0.99  # Allow tiny whitespace differences

                print(f"\n  Comparing line {occ1['line']} ({occ1['content_lines']} lines) vs line {occ2['line']} ({occ2['content_lines']} lines)")
                print(f"  Similarity: {sim*100:.1f}%")

                if identical:
                    print(f"  VERDICT: TRUE DUPLICATE - content is identical")
                else:
                    print(f"  VERDICT: FALSE DUPLICATE - content differs!")
                    all_identical = False

                    # Show a snippet of the difference
                    if occ1['content_lines'] != occ2['content_lines']:
                        print(f"    Line count differs: {occ1['content_lines']} vs {occ2['content_lines']}")

                    # Show first differing line
                    lines1 = occ1['content_normalized'].split('\n')
                    lines2 = occ2['content_normalized'].split('\n')
                    for k, (l1, l2) in enumerate(zip(lines1[:20], lines2[:20])):
                        if l1 != l2:
                            print(f"    First diff at relative line {k+1}:")
                            print(f"      A: {l1[:60]}")
                            print(f"      B: {l2[:60]}")
                            break

        if all_identical:
            true_duplicates.append({
                'header': header,
                'keep_line': occurrences[0]['line'],
                'remove_lines': [o['line'] for o in occurrences[1:]],
                'lines_saveable': sum(o['content_lines'] for o in occurrences[1:])
            })
        else:
            false_duplicates.append({
                'header': header,
                'occurrences': [(o['line'], o['content_lines']) for o in occurrences]
            })

    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)

    print(f"\nTRUE DUPLICATES (safe to remove): {len(true_duplicates)}")
    total_saveable = 0
    for td in true_duplicates:
        print(f"  '{td['header'][:50]}' - keep line {td['keep_line']}, remove lines {td['remove_lines']} ({td['lines_saveable']} lines)")
        total_saveable += td['lines_saveable']
    print(f"\n  Total lines saveable: {total_saveable}")

    print(f"\nFALSE DUPLICATES (need header rename): {len(false_duplicates)}")
    for fd in false_duplicates:
        print(f"  '{fd['header'][:50]}' at lines {fd['occurrences']}")

    # Generate action plan
    print("\n" + "="*70)
    print("ACTION PLAN")
    print("="*70)

    if true_duplicates:
        print("\n1. REMOVE these duplicate blocks (content is identical):")
        for td in true_duplicates:
            for line in td['remove_lines']:
                print(f"   - Line {line}: {td['header'][:50]}")

    if false_duplicates:
        print("\n2. RENAME these headers to be unique (content differs):")
        for fd in false_duplicates:
            print(f"   - '{fd['header'][:40]}' needs unique names at lines {[o[0] for o in fd['occurrences']]}")


if __name__ == "__main__":
    main()
