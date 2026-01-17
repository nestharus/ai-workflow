#!/usr/bin/env python3
"""
Content verification: find plan.md elements and match by body content in libraries.

Approach:
1. Find all IDs in plan.md (Algorithm 1, G6, P1I1, etc.)
2. Classify each as declaration (in header) or reference (in body)
3. For declarations, extract body and match to libraries
4. Track line coverage - report untouched non-blank lines
"""

import re
from pathlib import Path
from difflib import SequenceMatcher


# ID patterns to look for
ID_PATTERNS = [
    (r'Algorithm\s+\d+', 'Algorithm'),
    (r'P\d+I\d+', 'Invariant'),
    (r'P\d+C\d+', 'PatchClaim'),
    (r'C\d+', 'Claim'),          # General claims C1, C2, etc.
    (r'P\d+\.\d+', 'Math'),
    (r'P\d+\s+Lean\s+\d+', 'Lean'),
    (r'Lean\d+', 'Lean'),        # Lean1, Lean2, etc. (no space)
    (r'Lean\s+\d+', 'Lean'),     # Lean 1, Lean 2, etc. (with space)
    (r'G\d+\.\d+', 'Gap'),       # G0.1, G1.1, G2.1, G9.1, etc.
    (r'G\d+', 'Goal'),
    (r'Gap\s+G\d+', 'Gap'),
    (r'S\d+', 'Statement'),      # Problem statements
    (r'D\d+', 'DataStructure'),  # Data structures
    (r'Comp\d+', 'Component'),   # Components
    (r'H\d+', 'Hypothesis'),     # Hypotheses (future)
    (r'NFG\d+', 'NFG'),          # Non-functional goals
    (r'REF\d+', 'Reference'),    # References/bibliography
]


def extract_all_ids(text: str) -> list[tuple[str, str]]:
    """Extract all IDs from text with their type."""
    ids = []
    for pattern, id_type in ID_PATTERNS:
        for match in re.finditer(pattern, text):
            ids.append((match.group(), id_type))
    return ids


def is_header_line(line: str) -> bool:
    """Check if line is a markdown header."""
    return bool(re.match(r'^#{1,4}\s', line))


def find_id_in_line(line: str) -> tuple[str, str] | None:
    """Find the first ID in a line, return (id, type) or None."""
    for pattern, id_type in ID_PATTERNS:
        m = re.search(pattern, line)
        if m:
            return (m.group(), id_type)
    return None


def scan_declarations_and_references(lines: list[str]) -> tuple[dict, dict]:
    """Scan all lines for IDs, classify as declarations or references.

    Returns:
        declarations: {id: (line_idx, header_text)}
        references: {id: [line_idx, ...]}
    """
    declarations = {}  # id -> (line_idx, header_text)
    references = {}    # id -> [line_idx, ...]

    for idx, line in enumerate(lines):
        # Find all IDs in this line
        for pattern, id_type in ID_PATTERNS:
            for match in re.finditer(pattern, line):
                id_str = match.group()

                if is_header_line(line):
                    # This is a declaration
                    if id_str not in declarations:
                        declarations[id_str] = (idx, line.strip())
                else:
                    # This is a reference
                    if id_str not in references:
                        references[id_str] = []
                    references[id_str].append(idx)

    return declarations, references


def get_section_body(lines: list[str], start_idx: int) -> tuple[str, str, int, list[int]]:
    """Extract header and body from a section.

    Returns: (header, body, line_count, line_indices)
    """
    if start_idx >= len(lines):
        return "", "", 0, []

    first_line = lines[start_idx]
    match = re.match(r'^(#+)\s', first_line)
    if not match:
        return "", "", 0, []

    level = len(match.group(1))
    header = first_line.strip()
    body_lines = []
    line_indices = [start_idx]  # Include header line

    for i in range(start_idx + 1, len(lines)):
        line = lines[i]
        m = re.match(r'^(#+)\s', line)
        if m and len(m.group(1)) <= level:
            break
        body_lines.append(line.rstrip())
        line_indices.append(i)

    # Normalize body
    body = '\n'.join(body_lines).strip()

    return header, body, len(body_lines) + 1, line_indices


def extract_id_from_header(header: str) -> str:
    """Extract the ID portion from a header for matching.

    Examples:
    - "## Algorithm 1: Streaming ingestion" -> "Algorithm 1"
    - "### P1I1 Evidence permanence" -> "P1I1"
    - "## G22 Hippocampus workspace" -> "G22"
    """
    clean = re.sub(r'^#+\s+', '', header).strip()

    # Try various ID patterns
    patterns = [
        r'^(Algorithm\s+\d+)',           # Algorithm 1, Algorithm 52
        r'^(P\d+I\d+)',                   # P1I1, P9I6
        r'^(P\d+C\d+)',                   # P1C1, P6C5
        r'^(P\d+\.\d+)',                  # P1.1, P9.5
        r'^(P\d+\s+Lean\s+\d+)',          # P5 Lean 1
        r'^(Lean\s+\d+)',                 # Lean 1
        r'^(G\d+)',                       # G22, G6
        r'^(Gap\s+G\d+)',                 # Gap G2
    ]

    for pat in patterns:
        m = re.match(pat, clean)
        if m:
            return m.group(1)

    # No ID pattern - use first 30 chars as identifier
    return clean[:30]


def find_section_header_for_line(lib_lines: list[str], line_idx: int) -> int:
    """Find the section header that contains a given line."""
    # Walk backwards to find the header
    for i in range(line_idx, -1, -1):
        if re.match(r'^#{2,3}\s', lib_lines[i]):
            return i
    return -1


def find_content_in_libraries(body: str, lib_lines: list[str], min_match_len: int = 50) -> list[tuple[int, float]]:
    """Find where body content appears in libraries.

    Returns list of (header_line_idx, similarity) tuples.
    """
    if len(body) < min_match_len:
        return []

    # Take first significant chunk of body (skip empty lines)
    body_chunk = body[:500].strip()
    if not body_chunk:
        return []

    matches = []

    # Search for body content in libraries
    lib_text = '\n'.join(lib_lines)

    # Try to find exact substring match first
    pos = lib_text.find(body_chunk[:100])
    if pos != -1:
        # Find line number where match starts
        line_idx = lib_text[:pos].count('\n')
        # Back up to find the section header
        header_idx = find_section_header_for_line(lib_lines, line_idx)
        if header_idx >= 0:
            matches.append((header_idx, 1.0))
            return matches

    # Fall back to fuzzy matching on sections
    i = 0
    while i < len(lib_lines):
        line = lib_lines[i]
        if re.match(r'^#{2,3}\s', line):
            _, lib_body, lib_len, _ = get_section_body(lib_lines, i)
            if lib_body:
                # Compare first 500 chars of bodies
                sim = SequenceMatcher(None, body_chunk, lib_body[:500]).ratio()
                if sim > 0.5:
                    matches.append((i, sim))
            i += max(1, lib_len)
        else:
            i += 1

    return sorted(matches, key=lambda x: -x[1])


def main():
    base = Path(__file__).parent
    plan_path = base / "plan.md"
    libs_dir = base / "libraries"

    # Read plan.md
    plan_content = plan_path.read_text(encoding='utf-8')
    plan_lines = plan_content.split('\n')

    # Read all library files
    all_lib_lines = []
    lib_file_info = []  # [(filename, start_line, end_line), ...]

    for lib_file in sorted(libs_dir.glob("*.md")):
        content = lib_file.read_text(encoding='utf-8')
        lines = content.split('\n')
        start = len(all_lib_lines)
        all_lib_lines.extend(lines)
        lib_file_info.append((lib_file.name, start, len(all_lib_lines)))

    print("=" * 70)
    print("CONTENT VERIFICATION: plan.md vs libraries/ (ID-based)")
    print("=" * 70)

    # Scan for declarations and references
    plan_decls, plan_refs = scan_declarations_and_references(plan_lines)
    lib_decls, lib_refs = scan_declarations_and_references(all_lib_lines)

    print(f"\nPlan declarations: {len(plan_decls)}")
    print(f"Plan references: {len(plan_refs)} unique IDs")
    print(f"Library declarations: {len(lib_decls)}")

    # Track line coverage
    touched_lines = set()

    # Match declarations by ID and compare bodies
    exact_matches = 0
    close_matches = 0
    partial_matches = 0
    mismatches = []
    plan_only = []  # Declarations in plan but not in libs
    lib_only = []   # Declarations in libs but not in plan

    for id_str, (plan_idx, plan_header) in plan_decls.items():
        # Get plan body
        _, plan_body, plan_len, plan_line_indices = get_section_body(plan_lines, plan_idx)
        touched_lines.update(plan_line_indices)

        if id_str in lib_decls:
            lib_idx, lib_header = lib_decls[id_str]
            _, lib_body, _, _ = get_section_body(all_lib_lines, lib_idx)

            # Compare bodies
            if plan_body and lib_body:
                sim = SequenceMatcher(None, plan_body, lib_body).ratio()

                if sim > 0.95:
                    exact_matches += 1
                elif sim > 0.80:
                    close_matches += 1
                elif sim > 0.50:
                    partial_matches += 1
                    mismatches.append({
                        'line': plan_idx + 1,
                        'id': id_str,
                        'similarity': sim,
                        'plan_len': len(plan_body),
                        'lib_len': len(lib_body),
                        'type': 'partial'
                    })
                else:
                    mismatches.append({
                        'line': plan_idx + 1,
                        'id': id_str,
                        'similarity': sim,
                        'plan_len': len(plan_body),
                        'lib_len': len(lib_body),
                        'type': 'mismatch'
                    })
            elif plan_body and not lib_body:
                plan_only.append({
                    'line': plan_idx + 1,
                    'id': id_str,
                    'header': plan_header[:60],
                    'reason': 'empty lib body'
                })
            else:
                exact_matches += 1  # Both empty or lib has content
        else:
            plan_only.append({
                'line': plan_idx + 1,
                'id': id_str,
                'header': plan_header[:60],
                'reason': 'not in libs'
            })

    # Find lib-only declarations
    for id_str, (lib_idx, lib_header) in lib_decls.items():
        if id_str not in plan_decls:
            lib_only.append({
                'line': lib_idx + 1,
                'id': id_str,
                'header': lib_header[:60]
            })

    # Find references without declarations
    orphan_refs = []
    for id_str, ref_lines in plan_refs.items():
        if id_str not in plan_decls and id_str not in lib_decls:
            orphan_refs.append({
                'id': id_str,
                'ref_count': len(ref_lines),
                'first_line': ref_lines[0] + 1
            })

    # Summary
    total_decls = len(plan_decls)
    matched = exact_matches + close_matches + partial_matches
    print(f"\n--- ID Match Results ---")
    print(f"Exact matches (>95%): {exact_matches}")
    print(f"Close matches (80-95%): {close_matches}")
    print(f"Partial matches (50-80%): {partial_matches}")
    print(f"Mismatches (<50%): {len([m for m in mismatches if m['type'] == 'mismatch'])}")
    print(f"Plan-only declarations: {len(plan_only)}")
    print(f"Lib-only declarations: {len(lib_only)}")
    print(f"Orphan references: {len(orphan_refs)}")

    if mismatches:
        print("\n" + "=" * 70)
        print(f"CONTENT DIFFERENCES - {len(mismatches)} IDs")
        print("=" * 70)
        for m in sorted(mismatches, key=lambda x: x['similarity'])[:20]:
            print(f"  L{m['line']}: {m['id']} ({m['similarity']*100:.0f}%) - plan:{m['plan_len']} lib:{m['lib_len']} chars")

    if plan_only:
        print("\n" + "=" * 70)
        print(f"PLAN-ONLY DECLARATIONS - {len(plan_only)} IDs not in libraries")
        print("=" * 70)
        for p in plan_only[:30]:
            print(f"  L{p['line']}: {p['id']} - {p['header']} ({p['reason']})")

    if lib_only:
        print("\n" + "=" * 70)
        print(f"LIB-ONLY DECLARATIONS - {len(lib_only)} IDs not in plan")
        print("=" * 70)
        for l in lib_only[:20]:
            print(f"  L{l['line']}: {l['id']} - {l['header']}")

    if orphan_refs:
        print("\n" + "=" * 70)
        print(f"ORPHAN REFERENCES - {len(orphan_refs)} IDs referenced but never declared")
        print("=" * 70)
        for o in orphan_refs[:20]:
            print(f"  {o['id']} - {o['ref_count']} refs, first at L{o['first_line']}")

    # Find untouched non-blank lines
    untouched = []
    for idx, line in enumerate(plan_lines):
        if idx not in touched_lines:
            stripped = line.strip()
            # Skip blank lines, horizontal rules, and top-level # headers
            if stripped and stripped != '---' and not stripped.startswith('# '):
                untouched.append((idx + 1, stripped[:80]))

    if untouched:
        print("\n" + "=" * 70)
        print(f"UNTOUCHED LINES - {len(untouched)} non-blank lines never processed")
        print("=" * 70)
        for line_num, content in untouched[:50]:
            print(f"  L{line_num}: {content}")
        if len(untouched) > 50:
            print(f"  ... and {len(untouched) - 50} more")
    else:
        print("\n✓ All non-blank lines were processed")

    total_ok = exact_matches + close_matches
    print("\n" + "=" * 70)
    print(f"RESULT: {total_ok}/{total_decls} exact/close ({100*total_ok/total_decls:.1f}%)")
    print(f"Line coverage: {len(touched_lines)}/{len(plan_lines)} lines touched")
    print("=" * 70)

    return 0 if len(plan_only) == 0 and len([m for m in mismatches if m['type'] == 'mismatch']) == 0 else 1


if __name__ == "__main__":
    exit(main())
