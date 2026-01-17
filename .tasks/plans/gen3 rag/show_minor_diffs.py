#!/usr/bin/env python3
"""
Show the exact differences in "true duplicates" that are 99-100% similar.
"""

import re
from pathlib import Path
from difflib import unified_diff, SequenceMatcher


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


def main():
    plan_path = Path(__file__).parent / "plan.md"
    content = plan_path.read_text(encoding='utf-8')
    lines = content.split('\n')

    # Pairs to check (from the 99.x% matches)
    pairs_to_check = [
        ("Algorithm 32: Diagnostics-driven inquiry planning", 3544, 5887, 99.3),
        ("Algorithm 53: OPEN_WORKSPACE", 3768, 4208, 99.8),
        ("Algorithm 54: CLOSE_WORKSPACE_CASCADE", 3781, 4221, 99.8),
        ("Algorithm 55: SPAWN_CHILD", 3793, 4233, 99.9),
        ("Algorithm 56: EXPORT_CAPSULE", 3811, 4251, 99.8),
        ("Algorithm 57: IMPORT_CAPSULE", 3823, 4263, 99.9),
        ("Algorithm 58: MESSAGE_SEND", 3847, 4287, 99.7),
        ("Algorithm 59: RECONCILE_CHILD_TO_PARENT", 3856, 4296, 99.9),
        ("Algorithm 60: COMMIT_TO_INGEST", 3868, 4308, 99.8),
        ("Algorithm 61: OVERLAP_SIGNATURE", 3878, 4318, 99.9),
        ("Algorithm 62: OVERLAP_DETECT", 3889, 4329, 99.8),
        ("Algorithm 63: OSCILLATION_SIGNAL", 3901, 4341, 99.9),
        ("Algorithm 64: WORKSPACE_GC", 3916, 4356, 99.1),
        ("P10 data structures", 1371, 1794, 99.9),
        ("P6 Lean skeletons", 5028, 5953, 99.6),
        ("P6 algorithms", 3388, 5731, 99.9),
        ("P6 invariants", 577, 5513, 99.6),
        ("P6 proofs and proof obligations", 4570, 5903, 99.7),
        ("P6C2 Snapshot consistency", 4581, 5914, 99.2),
        ("P9.2 Local tangent frames", 2563, 2731, 99.3),
        ("P9.4 Vector-diffusion distance", 2598, 2766, 99.2),
        ("P9.5 Field blending", 2606, 2774, 99.3),
        ("WorkspaceCommitEnvelope", 1516, 1939, 99.3),
        ("Lean 1: Event-sourced isolation", 5030, 5955, 100.0),  # Check this one too
    ]

    print("="*80)
    print("DETAILED DIFF ANALYSIS FOR 'TRUE DUPLICATES' WITH <100% SIMILARITY")
    print("="*80)

    for name, line1, line2, sim in pairs_to_check:
        # Find the actual lines
        idx1 = line1 - 1
        idx2 = line2 - 1

        # Get header level
        match1 = re.match(r'^(#+)', lines[idx1])
        match2 = re.match(r'^(#+)', lines[idx2])

        if not match1 or not match2:
            print(f"\nSkipping {name} - couldn't find headers")
            continue

        level1 = len(match1.group(1))
        level2 = len(match2.group(1))

        content1 = get_section_until_same_level(lines, idx1, level1)
        content2 = get_section_until_same_level(lines, idx2, level2)

        # Normalize for comparison
        lines1 = [l.rstrip() for l in content1.split('\n')]
        lines2 = [l.rstrip() for l in content2.split('\n')]

        # Remove empty lines at end
        while lines1 and not lines1[-1].strip():
            lines1.pop()
        while lines2 and not lines2[-1].strip():
            lines2.pop()

        # Check if truly identical after normalization
        if lines1 == lines2:
            print(f"\n{name} (lines {line1} vs {line2}): IDENTICAL after whitespace normalization")
            continue

        # Show the diff
        print(f"\n{'='*80}")
        print(f"{name}")
        print(f"Lines {line1} vs {line2} | Similarity: {sim}%")
        print("="*80)

        diff = list(unified_diff(lines1, lines2, lineterm='', n=1))

        if not diff:
            print("No diff (identical after normalization)")
        else:
            # Show only the actual changes
            for line in diff:
                if line.startswith('---') or line.startswith('+++'):
                    continue
                if line.startswith('@@'):
                    print(f"\n{line}")
                elif line.startswith('-'):
                    print(f"  FIRST:  {line[1:][:70]}")
                elif line.startswith('+'):
                    print(f"  SECOND: {line[1:][:70]}")

        # Summarize the type of difference
        diff_types = set()
        for i, (l1, l2) in enumerate(zip(lines1, lines2)):
            if l1 != l2:
                # Check what kind of difference
                if l1.startswith('#') and l2.startswith('#'):
                    if l1.lstrip('#').strip() == l2.lstrip('#').strip():
                        diff_types.add("header_level")
                    else:
                        diff_types.add("header_text")
                elif l1.strip() == '' or l2.strip() == '':
                    diff_types.add("whitespace")
                elif l1.strip() == '---' or l2.strip() == '---':
                    diff_types.add("separator")
                elif '```' in l1 or '```' in l2:
                    diff_types.add("code_fence")
                else:
                    diff_types.add("content")

        if len(lines1) != len(lines2):
            diff_types.add(f"line_count ({len(lines1)} vs {len(lines2)})")

        print(f"\nDifference types: {', '.join(diff_types) if diff_types else 'none'}")


if __name__ == "__main__":
    main()
