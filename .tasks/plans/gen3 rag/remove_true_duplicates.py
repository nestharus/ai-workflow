#!/usr/bin/env python3
"""
Remove true duplicates from plan.md.

Rules:
1. Keep first occurrence (has correct ### hierarchy)
2. Remove second occurrence
3. For LaTeX differences: keep the \(...\) version, remove (...) version
4. Track exactly what was removed for verification
"""

import re
from pathlib import Path
from dataclasses import dataclass


@dataclass
class DuplicateToRemove:
    header: str
    keep_line: int
    remove_line: int
    remove_end_line: int  # Line where this section ends
    reason: str


def get_section_end(lines: list[str], start_idx: int, level: int) -> int:
    """Find where a section ends (next header of same or higher level)."""
    for i in range(start_idx + 1, len(lines)):
        match = re.match(r'^(#+)\s', lines[i])
        if match and len(match.group(1)) <= level:
            return i
    return len(lines)


def find_duplicates_to_remove(lines: list[str]) -> list[DuplicateToRemove]:
    """Identify all duplicate sections to remove."""
    duplicates = []

    # Map of header text -> list of (line_idx, level)
    headers = {}
    for i, line in enumerate(lines):
        match = re.match(r'^(#+)\s+(.+)$', line)
        if match:
            level = len(match.group(1))
            text = match.group(2).strip()
            if text not in headers:
                headers[text] = []
            headers[text].append((i, level))

    # True duplicates to remove (from previous analysis)
    # These are sections where content is identical except for header level/whitespace
    true_duplicate_headers = [
        # P6 standalone block duplicates (keep integrated at lower line numbers)
        "AdapterCandidate",
        "Algorithm 24: Hippocampal workspace session",
        "Algorithm 25: Two-stage commit from neocortex to hippocampus",
        "Algorithm 26: Curriculum ingestion controller",
        "Algorithm 27: Cold solve and re-rooting",
        "Algorithm 28: Surprise budget and provenance override",
        "Algorithm 29: Connectivity guard and bridge repair",
        "Algorithm 30: Grammar sandbox and promotion",
        "Algorithm 31: Adapter lifecycle and drift management",
        "Algorithm 32: Diagnostics-driven inquiry planning",
        "CommitRecord",
        "ConnectivityState",
        "CurriculumStage",
        "GrammarRuleCandidate",
        "HippocampalWorkspace",
        "InquiryTask",
        "NeocortexProposal",
        "SurpriseBudget",
        "Lean 1: Event-sourced isolation",
        "P6 Lean skeletons",
        "P6 algorithms",
        "P6 data structures",
        "P6 invariants",
        "P6C1 Workspace isolation",
        "P6C3 Safe reclamation",
        "P6C4 Surprise budget prevents calcification by construction",
        "P6C5 Grammar promotion controls error",
        # P10 duplicates
        "P10 data structures",
        "Workspace",
        "WorkspaceEvent",
        "WorkspaceGraph",
        "Capsule",
        "WorkspaceMessage",
        "ReconcileRecord",
        "WorkspaceCommitEnvelope",
        # P10 algorithm duplicates (keep ### version, remove ## version)
        "Algorithm 53: OPEN_WORKSPACE",
        "Algorithm 54: CLOSE_WORKSPACE_CASCADE (structured lifetime)",
        "Algorithm 55: SPAWN_CHILD (fork-join)",
        "Algorithm 56: EXPORT_CAPSULE",
        "Algorithm 57: IMPORT_CAPSULE (idempotent)",
        "Algorithm 58: MESSAGE_SEND",
        "Algorithm 59: RECONCILE_CHILD_TO_PARENT",
        "Algorithm 60: COMMIT_TO_INGEST (no LLM diffs)",
        "Algorithm 61: OVERLAP_SIGNATURE (structure + content)",
        "Algorithm 62: OVERLAP_DETECT",
        "Algorithm 63: OSCILLATION_SIGNAL",
        "Algorithm 64: WORKSPACE_GC",
        # P9 math duplicates (keep ### version)
        "P9.1 Discrete manifold (robust gated field)",
        "P9.2 Local tangent frames (projection basis)",
        "P9.3 Discrete parallel transport via connection Laplacian (sketch)",
        "P9.4 Vector-diffusion distance (optional)",
        "P9.5 Field blending (control, not topology)",
    ]

    # LaTeX duplicates - keep the \(...\) version (usually the second one in standalone P6)
    # But we're removing the standalone P6 block, so this is handled by keeping first
    latex_keep_second = [
        "P6 proofs and proof obligations",
        "P6C2 Snapshot consistency",
        "P6C6 Adapter rollout is safe under canary plus rollback",
    ]

    for header_text in true_duplicate_headers:
        if header_text in headers and len(headers[header_text]) >= 2:
            occurrences = headers[header_text]
            # Keep first (lower line number), remove second
            keep_idx, keep_level = occurrences[0]
            remove_idx, remove_level = occurrences[1]

            remove_end = get_section_end(lines, remove_idx, remove_level)

            duplicates.append(DuplicateToRemove(
                header=header_text,
                keep_line=keep_idx + 1,
                remove_line=remove_idx + 1,
                remove_end_line=remove_end,
                reason="true_duplicate"
            ))

    # For LaTeX duplicates, we need special handling
    # The first occurrence has (...) LaTeX, second has \(...\)
    # We want to keep \(...\) but it's in the standalone P6 block we're removing
    # Solution: After removing duplicates, we'll need to fix LaTeX in kept sections
    for header_text in latex_keep_second:
        if header_text in headers and len(headers[header_text]) >= 2:
            occurrences = headers[header_text]
            keep_idx, keep_level = occurrences[0]
            remove_idx, remove_level = occurrences[1]

            remove_end = get_section_end(lines, remove_idx, remove_level)

            duplicates.append(DuplicateToRemove(
                header=header_text,
                keep_line=keep_idx + 1,
                remove_line=remove_idx + 1,
                remove_end_line=remove_end,
                reason="latex_duplicate_fix_kept"
            ))

    # Sort by remove_line descending so we remove from end first (preserves line numbers)
    duplicates.sort(key=lambda d: d.remove_line, reverse=True)

    return duplicates


def fix_latex_in_section(lines: list[str], start_idx: int, end_idx: int) -> int:
    """Fix LaTeX formatting from (...) to \(...\) in a section. Returns count of fixes."""
    fixes = 0
    # Pattern: (X) where X contains LaTeX-like content but isn't already \(X\)
    # Look for patterns like (G^{(e)}) and convert to \(G^{(e)}\)
    latex_pattern = re.compile(r'(?<!\\)\(([A-Za-z_^{}\\]+(?:\{[^}]+\})?)\)(?!\))')

    for i in range(start_idx, min(end_idx, len(lines))):
        line = lines[i]
        # Only fix lines that look like they have math content
        if '^{' in line or '_{' in line or '\\' in line:
            # More targeted: fix specific patterns we know are wrong
            # (G^{(e)}) -> \(G^{(e)}\)
            # (f) -> \(f\) when in math context
            new_line = line
            new_line = re.sub(r'\(G\^\{[^}]+\}\)', lambda m: '\\' + m.group(0)[:-1] + '\\)', new_line)
            new_line = re.sub(r'(?<!\w)\(([a-z])\)(?!\w)', r'\\(\1\\)', new_line)  # single letter math
            if new_line != line:
                lines[i] = new_line
                fixes += 1

    return fixes


def main():
    base = Path(__file__).parent
    plan_path = base / "plan.md"

    # Read current content
    content = plan_path.read_text(encoding='utf-8')
    lines = content.split('\n')

    print("="*70)
    print("REMOVING TRUE DUPLICATES")
    print("="*70)
    print(f"\nOriginal line count: {len(lines)}")

    # Find duplicates to remove
    duplicates = find_duplicates_to_remove(lines)

    print(f"\nDuplicates to remove: {len(duplicates)}")

    # Track sections to fix LaTeX in
    latex_fix_sections = []

    # Remove duplicates (from end to preserve line numbers)
    total_removed = 0
    for dup in duplicates:
        start = dup.remove_line - 1
        end = dup.remove_end_line

        # Verify we're removing the right thing
        if start < len(lines):
            print(f"\nRemoving: {dup.header}")
            print(f"  Lines {dup.remove_line}-{dup.remove_end_line} ({end - start} lines)")
            print(f"  Keeping: line {dup.keep_line}")
            print(f"  First line: {lines[start][:60]}...")

            if dup.reason == "latex_duplicate_fix_kept":
                # Remember to fix LaTeX in the kept section
                latex_fix_sections.append((dup.keep_line - 1, dup.header))

            # Remove the lines
            del lines[start:end]
            total_removed += (end - start)

    print(f"\n{'='*70}")
    print(f"Total lines removed: {total_removed}")
    print(f"New line count: {len(lines)}")

    # Fix LaTeX in kept sections
    if latex_fix_sections:
        print(f"\n{'='*70}")
        print("FIXING LATEX IN KEPT SECTIONS")
        print("="*70)

        # Re-find section boundaries after removal
        for start_idx, header in latex_fix_sections:
            # Find current position of this header
            for i, line in enumerate(lines):
                if header in line and line.strip().startswith('#'):
                    match = re.match(r'^(#+)', line)
                    if match:
                        level = len(match.group(1))
                        end_idx = get_section_end(lines, i, level)
                        fixes = fix_latex_in_section(lines, i, end_idx)
                        print(f"  Fixed {fixes} LaTeX patterns in '{header}'")
                    break

    # Write back
    new_content = '\n'.join(lines)
    plan_path.write_text(new_content, encoding='utf-8')

    print(f"\n{'='*70}")
    print("COMPLETE")
    print("="*70)
    print(f"\nFile saved. Removed {total_removed} lines.")
    print(f"Original: 6026 lines -> New: {len(lines)} lines")

    # Create a removal log
    log_path = base / "removal_log.txt"
    with open(log_path, 'w') as f:
        f.write("TRUE DUPLICATE REMOVAL LOG\n")
        f.write("="*70 + "\n\n")
        for dup in sorted(duplicates, key=lambda d: d.remove_line):
            f.write(f"Header: {dup.header}\n")
            f.write(f"  Kept: line {dup.keep_line}\n")
            f.write(f"  Removed: lines {dup.remove_line}-{dup.remove_end_line}\n")
            f.write(f"  Reason: {dup.reason}\n\n")

    print(f"Removal log written to: {log_path}")


if __name__ == "__main__":
    main()
