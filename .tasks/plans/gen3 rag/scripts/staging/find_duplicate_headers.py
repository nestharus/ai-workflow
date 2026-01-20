#!/usr/bin/env python3
"""
Find all duplicate headers in plan.md to enable unique header tracking.
Also validates headers against pattern_spec.md formats.
"""

import re
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class Header:
    line_num: int
    level: int  # Number of #
    text: str   # Full header text
    normalized: str  # Normalized for comparison


def extract_headers(content: str) -> list[Header]:
    """Extract all markdown headers from content."""
    headers = []
    lines = content.split('\n')

    for i, line in enumerate(lines):
        match = re.match(r'^(#+)\s+(.+)$', line)
        if match:
            level = len(match.group(1))
            text = match.group(2).strip()
            # Normalize: lowercase, remove special chars for comparison
            normalized = re.sub(r'[^a-z0-9\s]', '', text.lower()).strip()
            normalized = re.sub(r'\s+', ' ', normalized)

            headers.append(Header(
                line_num=i + 1,
                level=level,
                text=text,
                normalized=normalized
            ))

    return headers


def find_duplicates(headers: list[Header]) -> dict[str, list[Header]]:
    """Find headers that appear more than once."""
    by_text = defaultdict(list)

    for h in headers:
        # Group by exact text match
        by_text[h.text].append(h)

    # Filter to only duplicates
    return {k: v for k, v in by_text.items() if len(v) > 1}


def find_near_duplicates(headers: list[Header]) -> dict[str, list[Header]]:
    """Find headers that are similar but not identical."""
    by_normalized = defaultdict(list)

    for h in headers:
        by_normalized[h.normalized].append(h)

    # Filter to groups with different exact text but same normalized
    near_dupes = {}
    for norm, group in by_normalized.items():
        if len(group) > 1:
            texts = set(h.text for h in group)
            if len(texts) > 1:  # Different exact texts
                near_dupes[norm] = group

    return near_dupes


def validate_patterns(headers: list[Header]) -> dict[str, list[Header]]:
    """Check headers against expected patterns from pattern_spec.md."""
    issues = defaultdict(list)

    # Expected patterns
    patterns = {
        'goal': r'^G\d+',
        'invariant': r'^P\d+I\d+|^I\d+\s',
        'claim': r'^P\d+C\d+',
        'math_section': r'^P\d+\.\d+',
        'algorithm': r'^Algorithm\s+\d+',
        'data_structure': r'^[A-Z][a-zA-Z]+$',
        'gap': r'^Gap\s+G\d+\.\d+',
        'dragon': r'^D\d+',
        'lean': r'^Lean\s+\d+',
    }

    for h in headers:
        text = h.text.strip('*').strip()

        # Check for malformed patterns

        # P1 legacy invariants (should be P1I#)
        if re.match(r'^I\d+\s', text) and h.level >= 3:
            issues['legacy_invariant'].append(h)

        # Algorithm with wrong format
        if 'algorithm' in text.lower() and not re.match(r'^Algorithm\s+\d+', text, re.I):
            issues['malformed_algorithm'].append(h)

        # P#.# in wrong context (could be math or algorithm)
        if re.match(r'^P\d+\.\d+\s', text):
            # This is ambiguous - could be math section or algorithm
            issues['ambiguous_p_section'].append(h)

        # Lean with wrong format
        if 'lean' in text.lower() and not re.match(r'^Lean\s+\d+', text, re.I):
            if 'track' in text.lower():
                issues['legacy_lean'].append(h)

    return dict(issues)


def main():
    plan_path = Path(__file__).resolve().parents[2] / "plan.md"
    content = plan_path.read_text(encoding='utf-8')

    headers = extract_headers(content)

    print("="*70)
    print("DUPLICATE HEADER ANALYSIS")
    print("="*70)
    print(f"\nTotal headers found: {len(headers)}")

    # Exact duplicates
    duplicates = find_duplicates(headers)

    print(f"\n{'='*70}")
    print(f"EXACT DUPLICATES: {len(duplicates)} groups")
    print("="*70)

    for text, group in sorted(duplicates.items(), key=lambda x: -len(x[1])):
        print(f"\n  '{text[:60]}{'...' if len(text) > 60 else ''}'")
        print(f"  Appears {len(group)} times at lines: {[h.line_num for h in group]}")
        for h in group:
            print(f"    Line {h.line_num:5d}: {'#' * h.level} {h.text[:50]}")

    # Near duplicates
    near_dupes = find_near_duplicates(headers)

    print(f"\n{'='*70}")
    print(f"NEAR DUPLICATES (same normalized, different text): {len(near_dupes)} groups")
    print("="*70)

    for norm, group in sorted(near_dupes.items()):
        print(f"\n  Normalized: '{norm[:50]}'")
        for h in group:
            print(f"    Line {h.line_num:5d}: {'#' * h.level} {h.text[:60]}")

    # Pattern issues
    issues = validate_patterns(headers)

    print(f"\n{'='*70}")
    print(f"PATTERN ISSUES: {sum(len(v) for v in issues.values())} total")
    print("="*70)

    for issue_type, group in issues.items():
        print(f"\n  {issue_type}: {len(group)} occurrences")
        for h in group[:5]:  # Show first 5
            print(f"    Line {h.line_num:5d}: {h.text[:60]}")
        if len(group) > 5:
            print(f"    ... and {len(group) - 5} more")

    # Summary for normalization
    print(f"\n{'='*70}")
    print("NORMALIZATION NEEDED")
    print("="*70)

    total_issues = len(duplicates) + len(near_dupes) + sum(len(v) for v in issues.values())
    print(f"\n  Exact duplicate groups: {len(duplicates)}")
    print(f"  Near duplicate groups: {len(near_dupes)}")
    print(f"  Pattern issues: {sum(len(v) for v in issues.values())}")
    print(f"\n  TOTAL ISSUES TO FIX: {total_issues}")

    # Output list of all duplicates for sub-agent
    print(f"\n{'='*70}")
    print("DUPLICATE LINES TO NORMALIZE (for sub-agent)")
    print("="*70)

    all_dupe_lines = set()
    for group in duplicates.values():
        for h in group[1:]:  # Skip first occurrence
            all_dupe_lines.add(h.line_num)

    for group in near_dupes.values():
        for h in group:
            all_dupe_lines.add(h.line_num)

    print(f"\nLines needing attention: {sorted(all_dupe_lines)}")

    return duplicates, near_dupes, issues


if __name__ == "__main__":
    main()
