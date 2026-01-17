#!/usr/bin/env python3
"""
Verify that removed lines were actually duplicates, not unique content.
Compare plan.md.backup to plan.md and show what was removed.
"""

from pathlib import Path
from difflib import unified_diff, SequenceMatcher
import re


def get_removed_blocks(backup_lines: list[str], current_lines: list[str]) -> list[tuple[int, int, list[str]]]:
    """Find contiguous blocks that were removed."""
    # Use SequenceMatcher to find matching blocks
    matcher = SequenceMatcher(None, backup_lines, current_lines)

    removed_blocks = []
    backup_idx = 0

    for match in matcher.get_matching_blocks():
        # Lines before this match in backup that aren't in current = removed
        if match.a > backup_idx:
            removed = backup_lines[backup_idx:match.a]
            if removed:
                removed_blocks.append((backup_idx + 1, match.a, removed))
        backup_idx = match.a + match.size

    return removed_blocks


def find_content_in_current(removed_block: list[str], current_lines: list[str]) -> list[tuple[int, str, float]]:
    """Check if removed content exists elsewhere in current file."""
    matches = []

    # Look for significant lines (headers, definitions)
    for line in removed_block:
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith('```'):
            continue

        # Check if this exact line exists in current
        for i, curr_line in enumerate(current_lines):
            if curr_line.strip() == line_stripped:
                matches.append((i + 1, line_stripped[:60], 1.0))
                break

    return matches


def main():
    base = Path(__file__).parent
    backup_path = base / "plan.md.backup"
    current_path = base / "plan.md"

    if not backup_path.exists():
        print("ERROR: plan.md.backup not found")
        return

    backup_content = backup_path.read_text(encoding='utf-8')
    current_content = current_path.read_text(encoding='utf-8')

    backup_lines = backup_content.split('\n')
    current_lines = current_content.split('\n')

    print("="*70)
    print("REMOVAL VERIFICATION")
    print("="*70)
    print(f"\nBackup lines: {len(backup_lines)}")
    print(f"Current lines: {len(current_lines)}")
    print(f"Removed: {len(backup_lines) - len(current_lines)} lines")

    # Find removed blocks
    removed_blocks = get_removed_blocks(backup_lines, current_lines)

    print(f"\nRemoved blocks found: {len(removed_blocks)}")

    total_verified_duplicates = 0
    total_unique_removed = 0

    for i, (start, end, block) in enumerate(removed_blocks):
        block_size = len(block)
        print(f"\n{'='*70}")
        print(f"REMOVED BLOCK {i+1}: Lines {start}-{end} ({block_size} lines)")
        print("="*70)

        # Show first and last few lines of the block
        print("\nFirst 10 lines of removed block:")
        for j, line in enumerate(block[:10]):
            print(f"  {start+j:5d}: {line[:80]}")
        if block_size > 20:
            print(f"  ... ({block_size - 20} more lines) ...")
        if block_size > 10:
            print("\nLast 10 lines of removed block:")
            for j, line in enumerate(block[-10:]):
                print(f"  {end-10+j:5d}: {line[:80]}")

        # Check if this content exists in current file
        # Sample headers and key lines
        headers_in_block = [line for line in block if line.strip().startswith('#')]

        print(f"\nHeaders in removed block ({len(headers_in_block)}):")
        verified_headers = 0
        for header in headers_in_block[:20]:
            header_text = header.strip()
            # Check if similar header exists in current
            found_in_current = False
            for curr_line in current_lines:
                curr_stripped = curr_line.strip()
                if curr_stripped.startswith('#'):
                    # Compare header content (after #s)
                    curr_header_text = re.sub(r'^#+\s*', '', curr_stripped)
                    block_header_text = re.sub(r'^#+\s*', '', header_text)
                    if curr_header_text == block_header_text:
                        found_in_current = True
                        verified_headers += 1
                        break

            status = "KEPT (duplicate verified)" if found_in_current else "UNIQUE (removed)"
            print(f"  {status}: {header_text[:60]}")

        if len(headers_in_block) > 20:
            print(f"  ... and {len(headers_in_block) - 20} more headers")

        # Summary for this block
        if len(headers_in_block) > 0:
            dup_pct = (verified_headers / len(headers_in_block)) * 100
            print(f"\n  Block summary: {verified_headers}/{len(headers_in_block)} headers ({dup_pct:.1f}%) have matching content in current file")
            if dup_pct < 90:
                print(f"  WARNING: {100-dup_pct:.1f}% of headers may be unique content!")
                total_unique_removed += len(headers_in_block) - verified_headers
            else:
                total_verified_duplicates += verified_headers

    # Final summary
    print("\n" + "="*70)
    print("FINAL SUMMARY")
    print("="*70)
    print(f"\nTotal lines removed: {len(backup_lines) - len(current_lines)}")
    print(f"Removed blocks: {len(removed_blocks)}")
    print(f"Headers verified as duplicates: {total_verified_duplicates}")
    print(f"Headers potentially unique: {total_unique_removed}")

    if total_unique_removed > 0:
        print(f"\n*** WARNING: {total_unique_removed} headers may have been unique content! ***")
        print("Consider restoring from backup and reviewing more carefully.")
    else:
        print("\n*** All removed content appears to be duplicates. ***")


if __name__ == "__main__":
    main()
