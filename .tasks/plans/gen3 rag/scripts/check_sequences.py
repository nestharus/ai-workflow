#!/usr/bin/env python3
"""
Check header sequences for duplicates and holes.

Header types:
- Algorithm #
- G# (goals)
- P#I# (invariants)
- P#C# (claims)
- P#.# (math sections)
- Lean # or P# Lean #

Also compares content to distinguish:
- TRUE DUPLICATE: same ID, same content (can remove one)
- CONFLICT: same ID, different content (need to resolve)
"""

import re
from pathlib import Path
from collections import defaultdict
from difflib import SequenceMatcher


def get_section_content(lines: list[str], start_idx: int) -> str:
    """Get section content from start until next header of same/higher level."""
    if start_idx >= len(lines):
        return ""

    first_line = lines[start_idx]
    match = re.match(r'^(#+)', first_line)
    if not match:
        # Not a header, just return the line
        return first_line

    level = len(match.group(1))
    content_lines = [first_line]

    for i in range(start_idx + 1, len(lines)):
        line = lines[i]
        m = re.match(r'^(#+)\s', line)
        if m and len(m.group(1)) <= level:
            break
        content_lines.append(line)

    return '\n'.join(line.rstrip() for line in content_lines)


def extract_sequences(lines: list[str]) -> dict[str, list[tuple[int, int, str, str]]]:
    """Extract all numbered headers. Returns {type: [(number, line_num, header, content), ...]}"""
    sequences = defaultdict(list)

    for i, line in enumerate(lines):
        line_num = i + 1

        # Algorithm #
        # Distinguish base algorithms (##) from delta algorithms (###)
        match = re.search(r'\bAlgorithm\s+(\d+)\b', line)
        if match and re.match(r'^#{1,3}\s', line):
            num = int(match.group(1))
            content = get_section_content(lines, i)
            # Check if this is a delta (### level within P# algorithms section)
            level_match = re.match(r'^(#+)', line)
            is_delta = level_match and len(level_match.group(1)) == 3
            key = 'Algorithm Delta' if is_delta else 'Algorithm'
            sequences[key].append((num, line_num, line.strip()[:70], content))

        # G# (goals) - various formats
        # Handle sub-gaps like G2.1, G9.3 separately from main goals
        match = re.search(r'\bG(\d+)\b', line)
        if match:
            is_header = re.match(r'^#{1,3}\s', line)
            is_gap = 'Gap G' in line

            if is_header:
                num = int(match.group(1))
                content = get_section_content(lines, i) if is_header else line

                # Check for sub-gap pattern (G#.#)
                sub_match = re.search(r'\bG(\d+)\.(\d+)\b', line)
                if sub_match and is_gap:
                    # This is a sub-gap like G2.1, G9.3 - track by parent.sub
                    parent = int(sub_match.group(1))
                    sub = int(sub_match.group(2))
                    key = f'Gap G{parent} Sub'
                    sequences[key].append((sub, line_num, line.strip()[:70], content))
                elif is_gap:
                    key = 'Gap'
                    sequences[key].append((num, line_num, line.strip()[:70], content))
                else:
                    key = 'Goal'
                    sequences[key].append((num, line_num, line.strip()[:70], content))

        # P#I# (invariants)
        match = re.search(r'\bP(\d+)I(\d+)\b', line)
        if match and re.match(r'^#{1,3}\s', line):
            patch = int(match.group(1))
            inv = int(match.group(2))
            content = get_section_content(lines, i)
            sequences[f'P{patch} Invariant'].append((inv, line_num, line.strip()[:70], content))

        # P#C# (claims) - track statements and proof sketches separately
        match = re.search(r'\bP(\d+)C(\d+)\b', line)
        if match:
            is_header = re.match(r'^#{1,3}\s', line)
            is_inline = re.match(r'^P\d+C\d+\.', line.strip())
            is_proof_sketch = 'proof sketch' in line.lower()

            if is_header and is_proof_sketch:
                # This is a proof sketch header, track separately
                # Handle combined proofs like "P1C2 and P1C3 proof sketch"
                patch = int(match.group(1))
                content = get_section_content(lines, i)

                # Find all claims mentioned in this proof sketch header
                all_claims = re.findall(r'P\d+C(\d+)', line)
                for claim_str in all_claims:
                    claim = int(claim_str)
                    sequences[f'P{patch} Proof'].append((claim, line_num, line.strip()[:70], content))
            elif is_header or is_inline:
                patch = int(match.group(1))
                claim = int(match.group(2))
                content = get_section_content(lines, i) if is_header else line
                sequences[f'P{patch} Claim'].append((claim, line_num, line.strip()[:70], content))

        # P#.# (math sections)
        match = re.search(r'\bP(\d+)\.(\d+)\b', line)
        if match and re.match(r'^#{1,3}\s', line):
            patch = int(match.group(1))
            sect = int(match.group(2))
            content = get_section_content(lines, i)
            sequences[f'P{patch} Math'].append((sect, line_num, line.strip()[:70], content))

        # Lean - multiple formats:
        # - "### P1 Lean 1" -> P1 Lean sequence
        # - "### Lean 3: description" -> global Lean sequence
        # - "### Lean: description" -> unnumbered Lean (skip for sequence check)
        lean_match = re.match(r'^#{1,3}\s+(?:P(\d+)\s+)?Lean\s+(\d+)', line)
        if lean_match:
            patch = lean_match.group(1)
            num = int(lean_match.group(2))
            content = get_section_content(lines, i)
            key = f'P{patch} Lean' if patch else 'Lean'
            sequences[key].append((num, line_num, line.strip()[:70], content))

    return sequences


def compare_content(content1: str, content2: str) -> tuple[str, float]:
    """Compare two content blocks. Returns (status, similarity)."""
    # Normalize: remove header line differences, compare body
    lines1 = content1.split('\n')[1:]  # Skip header
    lines2 = content2.split('\n')[1:]

    body1 = '\n'.join(lines1).strip()
    body2 = '\n'.join(lines2).strip()

    if body1 == body2:
        return 'DUPLICATE', 1.0

    similarity = SequenceMatcher(None, body1, body2).ratio()

    if similarity > 0.95:
        return 'NEAR_DUPLICATE', similarity
    elif similarity > 0.5:
        return 'PARTIAL_OVERLAP', similarity
    else:
        return 'CONFLICT', similarity


def analyze_sequence(name: str, items: list[tuple[int, int, str, str]]) -> dict:
    """Analyze a sequence for duplicates and holes."""
    # Sort by number
    sorted_items = sorted(items, key=lambda x: x[0])

    duplicates = []
    conflicts = []
    holes = []

    # Find duplicates/conflicts
    by_num = defaultdict(list)
    for num, line, header, content in sorted_items:
        by_num[num].append((line, header, content))

    for num, occurrences in by_num.items():
        if len(occurrences) > 1:
            # Compare content to determine duplicate vs conflict
            first_content = occurrences[0][2]
            all_same = True
            comparisons = []

            for j in range(1, len(occurrences)):
                status, sim = compare_content(first_content, occurrences[j][2])
                comparisons.append((occurrences[j], status, sim))
                if status not in ['DUPLICATE', 'NEAR_DUPLICATE']:
                    all_same = False

            entry = {
                'number': num,
                'occurrences': [(occ[0], occ[1]) for occ in occurrences],
                'comparisons': comparisons,
                'is_true_duplicate': all_same
            }

            if all_same:
                duplicates.append(entry)
            else:
                conflicts.append(entry)

    # Find holes (only for sequences that should be consecutive)
    # Skip hole detection for Algorithm and Algorithm Delta - they're added in patches
    skip_hole_check = name in ['Algorithm', 'Algorithm Delta'] or name.startswith('Gap')

    if sorted_items and not skip_hole_check:
        nums = sorted(set(item[0] for item in sorted_items))
        if len(nums) >= 3:
            min_num = nums[0]
            max_num = nums[-1]

            # Only check holes if the density is high (>50% filled)
            density = len(nums) / (max_num - min_num + 1)
            if max_num - min_num < 100 and density > 0.5:
                expected = set(range(min_num, max_num + 1))
                actual = set(nums)
                missing = expected - actual
                if missing:
                    holes = sorted(missing)

    return {
        'name': name,
        'count': len(items),
        'range': f"{sorted_items[0][0]}-{sorted_items[-1][0]}" if sorted_items else "N/A",
        'duplicates': duplicates,
        'conflicts': conflicts,
        'holes': holes,
        'items': sorted_items
    }


def main():
    base = Path(__file__).resolve().parents[1]
    plan_path = base / "plan.md"

    content = plan_path.read_text(encoding='utf-8')
    lines = content.split('\n')
    sequences = extract_sequences(lines)

    print("=" * 70)
    print("SEQUENCE ANALYSIS")
    print("=" * 70)

    all_issues = []

    for name in sorted(sequences.keys()):
        items = sequences[name]
        analysis = analyze_sequence(name, items)

        has_issues = analysis['duplicates'] or analysis['conflicts'] or analysis['holes']
        status = "ISSUES" if has_issues else "OK"

        print(f"\n{name}: {analysis['count']} items, range {analysis['range']} [{status}]")

        if analysis['duplicates']:
            print(f"  TRUE DUPLICATES (same content, can remove):")
            for dup in analysis['duplicates']:
                print(f"    #{dup['number']} appears {len(dup['occurrences'])} times:")
                for line, header in dup['occurrences']:
                    print(f"      L{line}: {header[:55]}")

        if analysis['conflicts']:
            print(f"  CONFLICTS (different content, need resolution):")
            for conf in analysis['conflicts']:
                print(f"    #{conf['number']} - {len(conf['occurrences'])} versions:")
                for line, header in conf['occurrences']:
                    print(f"      L{line}: {header[:55]}")
                for occ, status, sim in conf['comparisons']:
                    print(f"        vs L{occ[0]}: {status} ({sim*100:.0f}% similar)")

        if analysis['holes']:
            print(f"  HOLES (missing numbers): {analysis['holes']}")

        if has_issues:
            all_issues.append(analysis)

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    total_dups = sum(len(a['duplicates']) for a in all_issues)
    total_conflicts = sum(len(a['conflicts']) for a in all_issues)
    total_holes = sum(len(a['holes']) for a in all_issues)

    print(f"\nTrue duplicates (can remove): {total_dups}")
    print(f"Conflicts (need resolution): {total_conflicts}")
    print(f"Holes (missing numbers): {total_holes}")

    if all_issues:
        print("\n" + "=" * 70)
        print("ACTION ITEMS")
        print("=" * 70)

        for analysis in all_issues:
            if analysis['duplicates']:
                for dup in analysis['duplicates']:
                    keep = dup['occurrences'][0]
                    remove = dup['occurrences'][1:]
                    print(f"\n{analysis['name']} #{dup['number']}: REMOVE duplicates")
                    print(f"  Keep: L{keep[0]}")
                    for r in remove:
                        print(f"  Remove: L{r[0]}")

            if analysis['conflicts']:
                for conf in analysis['conflicts']:
                    print(f"\n{analysis['name']} #{conf['number']}: RESOLVE conflict")
                    for line, header in conf['occurrences']:
                        print(f"  Version at L{line}: {header[:50]}")

            if analysis['holes']:
                print(f"\n{analysis['name']}: CHECK for missing {analysis['holes']}")

    return 0 if not all_issues else 1


if __name__ == "__main__":
    exit(main())
