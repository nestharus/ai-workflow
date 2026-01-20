#!/usr/bin/env python3
"""
Gap detection script for Gen3 RAG patch application tracking.

Compares labels in applied.md against labels in patch files to detect
which labels have not yet been applied.

Usage:
    python check_gaps.py <patch_file>
    python check_gaps.py p1.md
    python check_gaps.py --all  # Check all patches
"""

import re
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Set, Dict, List, Optional


@dataclass
class Label:
    """Represents a labeled entry in a patch file."""
    category: str  # goal, invariant, claim, math, algorithm, gap, dragon, lean, data_structure
    raw_label: str  # Original label text
    normalized: str  # Normalized for comparison
    line_num: int
    context: str  # Surrounding text for verification


# Regex patterns for extracting labels
PATTERNS = {
    'goal': [
        r'^#+\s*\*{0,2}(G\d+)',   # ## G6, ### **G17**
    ],
    'invariant': [
        r'^\*{0,2}(P\d+I\d+)',    # P4I1, **P6I2**
        r'^#+\s*\*{0,2}(P\d+I\d+)',
    ],
    'claim': [
        r'^\*{0,2}(P\d+C\d+)',    # P1C1, P5C3
        r'^#+\s*\*{0,2}(P\d+C\d+)',
    ],
    'math': [
        r'^#+\s*(P\d+\.\d+)',     # ## P1.1, ## P6.3
    ],
    'algorithm': [
        r'^#+\s*(Algorithm\s*\d+)',  # ## Algorithm 6
    ],
    'gap': [
        r'^#+\s*(Gap\s+G\d+\.\d+)',  # ### Gap G2.1
    ],
    'dragon': [
        r'\|(D\d+)\|',              # |D1| in table
    ],
    'lean': [
        r'^#+\s*(Lean\s*\d+)',       # ## Lean 1
    ],
    'data_structure': [
        r'^##\s+([A-Z][a-zA-Z]+(?:Record|State|Belief|View|Graph|Event|Seed|Token|Budget|Workspace|Message|Capsule|Manifest|Fingerprint)?)\s*$',
    ],
}


def normalize_label(raw: str) -> str:
    """Normalize a label for comparison."""
    # Remove whitespace, asterisks, and normalize case
    normalized = raw.strip().replace('*', '').replace('#', '').strip()
    # Normalize "Algorithm 6" to "Algorithm6"
    normalized = re.sub(r'Algorithm\s+', 'Algorithm', normalized)
    # Normalize "Lean 1" to "Lean1"
    normalized = re.sub(r'Lean\s+', 'Lean', normalized)
    # Normalize "Gap G2.1" to "GapG2.1"
    normalized = re.sub(r'Gap\s+', 'Gap', normalized)
    return normalized


def extract_labels(file_path: Path) -> List[Label]:
    """Extract all labels from a patch file."""
    labels = []
    content = file_path.read_text(encoding='utf-8')
    lines = content.split('\n')

    # Track which section we're in for context
    current_section = ""

    for i, line in enumerate(lines):
        line_num = i + 1

        # Update current section
        if line.startswith('# '):
            current_section = line[2:].strip()

        # Try each pattern category
        for category, pattern_list in PATTERNS.items():
            for pattern in pattern_list:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    raw_label = match.group(1)

                    # Skip false positives
                    if category == 'data_structure':
                        # Skip common words that aren't data structures
                        if raw_label.lower() in {'the', 'this', 'that', 'when', 'where', 'what', 'patch', 'scope', 'notes'}:
                            continue

                    labels.append(Label(
                        category=category,
                        raw_label=raw_label,
                        normalized=normalize_label(raw_label),
                        line_num=line_num,
                        context=line[:80]
                    ))
                    break  # Only match one pattern per line per category

    return labels


def extract_applied_labels(applied_path: Path) -> Set[str]:
    """Extract the set of already-applied labels from applied.md."""
    if not applied_path.exists():
        return set()

    applied = set()
    content = applied_path.read_text(encoding='utf-8')

    # Parse applied.md format: each line is "- [x] LABEL: description" or similar
    for line in content.split('\n'):
        # Match checkbox format: - [x] G6, - [x] P1C1, etc.
        match = re.search(r'-\s*\[x\]\s*(\S+)', line, re.IGNORECASE)
        if match:
            applied.add(normalize_label(match.group(1)))

        # Also match simple format: - G6 (applied)
        match = re.search(r'^-\s+(\S+)\s*(?:\(applied\))?', line)
        if match:
            label = match.group(1)
            if any(re.match(p, label) for patterns in PATTERNS.values() for p in patterns):
                applied.add(normalize_label(label))

    return applied


def find_gaps(patch_path: Path, applied_path: Path) -> Dict[str, List[Label]]:
    """Find labels in patch that are not in applied."""
    patch_labels = extract_labels(patch_path)
    applied_labels = extract_applied_labels(applied_path)

    gaps = {}
    for label in patch_labels:
        if label.normalized not in applied_labels:
            if label.category not in gaps:
                gaps[label.category] = []
            gaps[label.category].append(label)

    return gaps


def print_report(patch_name: str, gaps: Dict[str, List[Label]], total_labels: int, applied_count: int):
    """Print a formatted report of gaps."""
    print(f"\n{'='*60}")
    print(f"Gap Report: {patch_name}")
    print(f"{'='*60}")
    print(f"Total labels in patch: {total_labels}")
    print(f"Already applied: {applied_count}")
    print(f"Gaps remaining: {total_labels - applied_count}")
    print()

    if not gaps:
        print("All labels have been applied!")
        return

    for category, labels in sorted(gaps.items()):
        print(f"\n## {category.upper()} ({len(labels)} missing)")
        print("-" * 40)
        for label in labels:
            print(f"  Line {label.line_num:4d}: {label.raw_label}")
            if label.context:
                print(f"           {label.context[:60]}...")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python check_gaps.py <patch_file>")
        print("       python check_gaps.py --all")
        sys.exit(1)

    base_dir = Path(__file__).resolve().parents[1]
    patch_dir = base_dir / "patches"
    applied_path = base_dir / "applied.md"

    if sys.argv[1] == "--all":
        # Check all patch files
        patch_files = sorted(patch_dir.glob("p*.md"))
    else:
        patch_arg = Path(sys.argv[1])
        if not patch_arg.is_absolute():
            patch_arg = patch_dir / patch_arg
        patch_files = [patch_arg]

    for patch_path in patch_files:
        if not patch_path.exists():
            print(f"Error: {patch_path} not found")
            continue

        all_labels = extract_labels(patch_path)
        applied_labels = extract_applied_labels(applied_path)
        gaps = find_gaps(patch_path, applied_path)

        applied_count = len([l for l in all_labels if l.normalized in applied_labels])
        print_report(patch_path.name, gaps, len(all_labels), applied_count)

    # Return labels as JSON for programmatic use
    if len(patch_files) == 1:
        gaps = find_gaps(patch_files[0], applied_path)
        missing = []
        for category, labels in gaps.items():
            for label in labels:
                missing.append(label.normalized)
        return missing

    return []


if __name__ == "__main__":
    main()
