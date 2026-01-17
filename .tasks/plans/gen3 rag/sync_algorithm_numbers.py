#!/usr/bin/env python3
"""
Synchronize algorithm numbers between plan.md and library files.
plan.md is the source of truth.
"""

import re
from pathlib import Path
from typing import Dict, List, Tuple

# Mappings of incorrect library numbers to correct plan.md numbers
# Based on title matching
CORRECTIONS = {
    "Robust Field Solve via IRLS": {"old": 7, "new": 65},
    "Apply deltas after snapshot": {"old": 8, "new": 66},
    "Publish epoch with RCU semantics": {"old": 9, "new": 67},
    "Global Consolidation": {"old": 6, "new": 9},
}

def extract_plan_algorithms(plan_path: Path) -> Dict[str, int]:
    """Extract all algorithms from plan.md with their numbers."""
    algorithms = {}
    with open(plan_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Match patterns like "### Algorithm 65: Robust Field Solve via IRLS"
    pattern = r'^###?\s+Algorithm\s+(\d+):?\s*(.+?)(?:\s*\(.*?\))?$'
    for match in re.finditer(pattern, content, re.MULTILINE):
        num = int(match.group(1))
        title = match.group(2).strip()
        # Clean up title
        title = re.sub(r'\s*—\s*', ' — ', title)
        algorithms[title] = num

    return algorithms

def find_mismatches(library_dir: Path, plan_algorithms: Dict[str, int]) -> List[Tuple[Path, str, int, int]]:
    """Find all algorithm number mismatches in library files."""
    mismatches = []

    for lib_file in library_dir.glob("*.md"):
        with open(lib_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find all algorithm declarations
        pattern = r'^###?\s+Algorithm\s+(\d+):?\s*(.+?)(?:\s*\(.*?\))?$'
        for match in re.finditer(pattern, content, re.MULTILINE):
            lib_num = int(match.group(1))
            title = match.group(2).strip()
            # Clean up title
            title = re.sub(r'\s*—\s*', ' — ', title)

            # Check if this title exists in plan.md with a different number
            if title in plan_algorithms:
                plan_num = plan_algorithms[title]
                if lib_num != plan_num:
                    mismatches.append((lib_file, title, lib_num, plan_num))

    return mismatches

def update_library_file(lib_path: Path, title: str, old_num: int, new_num: int) -> int:
    """Update algorithm number in a library file and all references to it."""
    with open(lib_path, 'r', encoding='utf-8') as f:
        content = f.read()

    changes = 0

    # 1. Update the header declaration
    # Match both "### Algorithm 7:" and "## Algorithm 7:"
    header_pattern = rf'^(###?\s+Algorithm\s+){old_num}(:?\s*{re.escape(title)})'
    new_content = re.sub(
        header_pattern,
        rf'\g<1>{new_num}\g<2>',
        content,
        flags=re.MULTILINE
    )
    if new_content != content:
        changes += 1
        content = new_content

    # 2. Update references like "Algorithm 7 (Robust Field Solve"
    ref_pattern = rf'\bAlgorithm\s+{old_num}\s+\({re.escape(title[:20])}'
    if re.search(ref_pattern, content):
        new_content = re.sub(
            rf'\bAlgorithm\s+{old_num}\b',
            f'Algorithm {new_num}',
            content
        )
        if new_content != content:
            changes += content.count(f'Algorithm {old_num}') - new_content.count(f'Algorithm {old_num}')
            content = new_content

    # Write back if changed
    if changes > 0:
        with open(lib_path, 'w', encoding='utf-8') as f:
            f.write(content)

    return changes

def main():
    base_dir = Path("/mnt/c/Users/xteam/IdeaProjects/ai-workflow/.tasks/plans/gen3 rag")
    plan_path = base_dir / "plan.md"
    library_dir = base_dir / "libraries"

    print("=" * 80)
    print("ALGORITHM NUMBER SYNCHRONIZATION")
    print("=" * 80)
    print()

    # Extract all algorithms from plan.md
    print("1. Extracting algorithms from plan.md...")
    plan_algorithms = extract_plan_algorithms(plan_path)
    print(f"   Found {len(plan_algorithms)} algorithms in plan.md")
    print()

    # Find mismatches
    print("2. Finding mismatches in library files...")
    mismatches = find_mismatches(library_dir, plan_algorithms)

    if not mismatches:
        print("   No mismatches found!")
        return

    print(f"   Found {len(mismatches)} mismatches:")
    print()
    for lib_file, title, lib_num, plan_num in mismatches:
        print(f"   - {lib_file.name}: '{title}'")
        print(f"     Library has: Algorithm {lib_num}")
        print(f"     Plan.md has: Algorithm {plan_num}")
        print()

    # Apply corrections
    print("3. Applying corrections...")
    print()
    total_changes = 0

    for lib_file, title, old_num, new_num in mismatches:
        print(f"   Updating {lib_file.name}:")
        print(f"   - Algorithm {old_num} → {new_num}: {title}")

        changes = update_library_file(lib_file, title, old_num, new_num)
        total_changes += changes

        print(f"     Made {changes} change(s)")
        print()

    print("=" * 80)
    print(f"SUMMARY: {total_changes} total changes across {len(set(m[0] for m in mismatches))} files")
    print("=" * 80)

if __name__ == "__main__":
    main()
