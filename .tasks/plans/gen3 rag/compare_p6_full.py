#!/usr/bin/env python3
"""
Rigorous comparison of P6 sections - extracts full section content and compares byte-by-byte.
"""

import re
from pathlib import Path
from difflib import unified_diff

def extract_section(lines: list[str], start_idx: int, header_pattern: str) -> tuple[str, int]:
    """Extract a full section from start_idx until the next section of same or higher level."""
    section_lines = []
    header_level = len(re.match(r'^(#+)', lines[start_idx]).group(1))

    for i in range(start_idx, len(lines)):
        line = lines[i]

        # If we hit another header of same or higher level (fewer #), stop
        if i > start_idx and line.startswith('#'):
            match = re.match(r'^(#+)', line)
            if match and len(match.group(1)) <= header_level:
                break

        section_lines.append(line)

    return '\n'.join(section_lines), len(section_lines)


def find_all_sections(lines: list[str], pattern: str) -> list[tuple[int, str, str]]:
    """Find all sections matching a pattern, return (line_num, header, full_content)."""
    sections = []

    for i, line in enumerate(lines):
        if re.search(pattern, line):
            content, length = extract_section(lines, i, pattern)
            sections.append((i + 1, line.strip(), content))

    return sections


def compare_sections(name: str, integrated: list, standalone: list):
    """Compare integrated vs standalone sections."""
    print(f"\n{'='*60}")
    print(f"COMPARING: {name}")
    print(f"{'='*60}")

    if len(integrated) != len(standalone):
        print(f"COUNT MISMATCH: {len(integrated)} integrated vs {len(standalone)} standalone")
        return False

    all_identical = True

    for i, (int_sec, std_sec) in enumerate(zip(integrated, standalone)):
        int_line, int_header, int_content = int_sec
        std_line, std_header, std_content = std_sec

        # Normalize whitespace for comparison
        int_normalized = '\n'.join(line.rstrip() for line in int_content.split('\n'))
        std_normalized = '\n'.join(line.rstrip() for line in std_content.split('\n'))

        if int_normalized == std_normalized:
            print(f"\n  Section {i+1}: IDENTICAL")
            print(f"    Integrated line {int_line}: {int_header[:50]}...")
            print(f"    Standalone line {std_line}: {std_header[:50]}...")
            print(f"    Length: {len(int_content)} bytes, {int_content.count(chr(10))} lines")
        else:
            print(f"\n  Section {i+1}: DIFFERENT")
            print(f"    Integrated line {int_line}: {int_header[:50]}...")
            print(f"    Standalone line {std_line}: {std_header[:50]}...")
            print(f"    Integrated length: {len(int_content)} bytes")
            print(f"    Standalone length: {len(std_content)} bytes")

            # Show diff
            diff = list(unified_diff(
                int_content.split('\n'),
                std_content.split('\n'),
                fromfile=f'integrated (line {int_line})',
                tofile=f'standalone (line {std_line})',
                lineterm=''
            ))

            if diff:
                print(f"\n    DIFF (first 30 lines):")
                for line in diff[:30]:
                    print(f"      {line}")
                if len(diff) > 30:
                    print(f"      ... and {len(diff) - 30} more diff lines")

            all_identical = False

    return all_identical


def main():
    plan_path = Path(__file__).parent / "plan.md"
    content = plan_path.read_text(encoding='utf-8')
    lines = content.split('\n')

    # Find the standalone P6 section start
    standalone_start = None
    for i, line in enumerate(lines):
        if line.strip() == '# P6: Hippocampus control plane':
            standalone_start = i
            break

    if standalone_start is None:
        print("No standalone P6 section found")
        return

    print(f"Standalone P6 section starts at line {standalone_start + 1}")
    print(f"Document has {len(lines)} total lines")

    # Split lines into integrated (before standalone) and standalone sections
    integrated_lines = lines[:standalone_start]
    standalone_lines = lines[standalone_start:]

    print(f"\nIntegrated section: lines 1-{standalone_start}")
    print(f"Standalone section: lines {standalone_start + 1}-{len(lines)}")

    # Compare each P6 subsection
    results = {}

    # P6 goals (G22-G29)
    print("\n" + "="*60)
    print("ANALYZING P6 GOALS (G22-G29)")
    print("="*60)

    int_goals = []
    std_goals = []

    for pattern in [r'^\*\*G2[2-9]']:
        for i, line in enumerate(integrated_lines):
            if re.search(pattern, line):
                # Extract until next goal or section
                end = i + 1
                while end < len(integrated_lines) and not re.match(r'^\*\*G\d|^##', integrated_lines[end]):
                    end += 1
                content = '\n'.join(integrated_lines[i:end])
                int_goals.append((i + 1, line.strip()[:60], content))

        for i, line in enumerate(standalone_lines):
            if re.search(pattern, line):
                end = i + 1
                while end < len(standalone_lines) and not re.match(r'^\*\*G\d|^##', standalone_lines[end]):
                    end += 1
                content = '\n'.join(standalone_lines[i:end])
                std_goals.append((i + standalone_start + 1, line.strip()[:60], content))

    results['goals'] = compare_sections("P6 Goals", int_goals, std_goals)

    # P6 invariants
    int_inv = find_all_sections(integrated_lines, r'^## P6 invariants')
    std_inv = find_all_sections(standalone_lines, r'^## P6 invariants')
    # Adjust line numbers for standalone
    std_inv = [(ln + standalone_start, h, c) for ln, h, c in std_inv]
    results['invariants'] = compare_sections("P6 Invariants Section", int_inv, std_inv)

    # P6 data structures
    int_ds = find_all_sections(integrated_lines, r'^## P6 data structures')
    std_ds = find_all_sections(standalone_lines, r'^## P6 data structures')
    std_ds = [(ln + standalone_start, h, c) for ln, h, c in std_ds]
    results['data_structures'] = compare_sections("P6 Data Structures Section", int_ds, std_ds)

    # P6 math
    int_math = find_all_sections(integrated_lines, r'^## P6 math')
    std_math = find_all_sections(standalone_lines, r'^## P6 math')
    std_math = [(ln + standalone_start, h, c) for ln, h, c in std_math]
    results['math'] = compare_sections("P6 Math Section", int_math, std_math)

    # P6 algorithms
    int_alg = find_all_sections(integrated_lines, r'^## P6 algorithms')
    std_alg = find_all_sections(standalone_lines, r'^## P6 algorithms')
    std_alg = [(ln + standalone_start, h, c) for ln, h, c in std_alg]
    results['algorithms'] = compare_sections("P6 Algorithms Section", int_alg, std_alg)

    # P6 proofs
    int_proofs = find_all_sections(integrated_lines, r'^## P6 proofs')
    std_proofs = find_all_sections(standalone_lines, r'^## P6 proofs')
    std_proofs = [(ln + standalone_start, h, c) for ln, h, c in std_proofs]
    results['proofs'] = compare_sections("P6 Proofs Section", int_proofs, std_proofs)

    # P6 Lean
    int_lean = find_all_sections(integrated_lines, r'^## P6 Lean')
    std_lean = find_all_sections(standalone_lines, r'^## P6 Lean')
    std_lean = [(ln + standalone_start, h, c) for ln, h, c in std_lean]
    results['lean'] = compare_sections("P6 Lean Section", int_lean, std_lean)

    # Final summary
    print("\n" + "="*60)
    print("FINAL VERDICT")
    print("="*60)

    all_identical = all(results.values())

    for section, identical in results.items():
        status = "IDENTICAL" if identical else "DIFFERENT"
        print(f"  {section}: {status}")

    print(f"\nOVERALL: {'100% IDENTICAL - SAFE TO REMOVE STANDALONE' if all_identical else 'DIFFERENCES FOUND - DO NOT REMOVE'}")


if __name__ == "__main__":
    main()
