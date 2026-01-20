#!/usr/bin/env python3
"""
Lint plan.md against pattern_spec.md canonical formats.

Checks for violations of the canonical label formats and reports them.
"""

import re
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from enum import Enum


class Severity(Enum):
    ERROR = "ERROR"      # Must fix - violates spec
    WARNING = "WARNING"  # Should fix - legacy format
    INFO = "INFO"        # Note - might be intentional


@dataclass
class Violation:
    line_num: int
    line_text: str
    category: str
    message: str
    severity: Severity
    suggestion: Optional[str] = None


def lint_plan(content: str) -> list[Violation]:
    """Lint plan.md content against pattern_spec.md."""
    violations = []
    lines = content.split('\n')

    # Track current section for context
    current_section = ""

    for i, line in enumerate(lines):
        line_num = i + 1
        stripped = line.strip()

        # Update current section
        if stripped.startswith('# '):
            current_section = stripped[2:].lower()
        elif stripped.startswith('## '):
            current_section = stripped[3:].lower()

        # Skip empty lines and code blocks
        if not stripped or stripped.startswith('```'):
            continue

        # Check for various violations
        violations.extend(check_goals(line_num, line, stripped))
        violations.extend(check_invariants(line_num, line, stripped))
        violations.extend(check_claims(line_num, line, stripped))
        violations.extend(check_math_sections(line_num, line, stripped))
        violations.extend(check_algorithms(line_num, line, stripped, current_section))
        violations.extend(check_lean_skeletons(line_num, line, stripped))
        violations.extend(check_legacy_formats(line_num, line, stripped))

    return violations


def check_goals(line_num: int, line: str, stripped: str) -> list[Violation]:
    """Check goal format: should be G# (G1-G50)."""
    violations = []

    # Look for goal-like patterns
    match = re.search(r'\bG(\d+)\b', stripped)
    if match:
        num = int(match.group(1))
        if num < 1 or num > 50:
            violations.append(Violation(
                line_num=line_num,
                line_text=line[:80],
                category="goal",
                message=f"Goal G{num} out of expected range (G1-G50)",
                severity=Severity.WARNING
            ))

    return violations


def check_invariants(line_num: int, line: str, stripped: str) -> list[Violation]:
    """Check invariant format: should be P#I# (not standalone I#)."""
    violations = []

    # Check for legacy I# format without P prefix
    if re.match(r'^#+\s*\*{0,2}I\d+\b', stripped):
        match = re.search(r'I(\d+)', stripped)
        if match:
            violations.append(Violation(
                line_num=line_num,
                line_text=line[:80],
                category="invariant",
                message=f"Legacy invariant format I{match.group(1)} - should be P#I#",
                severity=Severity.ERROR,
                suggestion=f"Change to P1I{match.group(1)} (assuming P1)"
            ))

    # Check for correct P#I# format
    match = re.search(r'\bP(\d+)I(\d+)\b', stripped)
    if match:
        patch_num = int(match.group(1))
        inv_num = int(match.group(2))
        valid_patches = [1, 4, 6, 7, 9, 10]
        if patch_num not in valid_patches:
            violations.append(Violation(
                line_num=line_num,
                line_text=line[:80],
                category="invariant",
                message=f"P{patch_num}I{inv_num} - patch {patch_num} doesn't have invariants in spec",
                severity=Severity.WARNING
            ))

    return violations


def check_claims(line_num: int, line: str, stripped: str) -> list[Violation]:
    """Check claim format: should be P#C#."""
    violations = []

    match = re.search(r'\bP(\d+)C(\d+)\b', stripped)
    if match:
        patch_num = int(match.group(1))
        claim_num = int(match.group(2))

        # Valid claim ranges per patch
        valid_ranges = {
            1: (1, 5),
            2: (1, 5),
            4: (1, 5),
            5: (1, 4),
            6: (1, 6),
            7: (1, 5),
        }

        if patch_num in valid_ranges:
            min_c, max_c = valid_ranges[patch_num]
            if claim_num < min_c or claim_num > max_c:
                violations.append(Violation(
                    line_num=line_num,
                    line_text=line[:80],
                    category="claim",
                    message=f"P{patch_num}C{claim_num} out of range (expected C{min_c}-C{max_c})",
                    severity=Severity.WARNING
                ))

    return violations


def check_math_sections(line_num: int, line: str, stripped: str) -> list[Violation]:
    """Check math section format: should be P#.# (not P#.M#)."""
    violations = []

    # Check for P#.M# format (legacy P10)
    match = re.search(r'\bP(\d+)\.M(\d+)\b', stripped)
    if match:
        violations.append(Violation(
            line_num=line_num,
            line_text=line[:80],
            category="math",
            message=f"Legacy math format P{match.group(1)}.M{match.group(2)} - should be P{match.group(1)}.{match.group(2)}",
            severity=Severity.ERROR,
            suggestion=f"Change to P{match.group(1)}.{match.group(2)}"
        ))

    return violations


def check_algorithms(line_num: int, line: str, stripped: str, current_section: str) -> list[Violation]:
    """Check algorithm format: should be 'Algorithm #'."""
    violations = []

    # Check for correct Algorithm # format
    match = re.match(r'^#+\s*(Algorithm\s+(\d+))', stripped)
    if match:
        alg_num = int(match.group(2))
        if alg_num < 1 or alg_num > 67:
            violations.append(Violation(
                line_num=line_num,
                line_text=line[:80],
                category="algorithm",
                message=f"Algorithm {alg_num} out of expected range (1-67)",
                severity=Severity.WARNING
            ))

    # Check for legacy P#.# algorithm format (only in algorithm sections)
    # Note: P8 uses P8.1-P8.10 as conceptual section headers, not algorithms
    if 'algorithm' in current_section:
        match = re.match(r'^#+\s*P(\d+)\.(\d+)\s+\w', stripped)
        if match:
            patch_num = int(match.group(1))
            # P8 sections are conceptual headers, not algorithms
            if patch_num != 8:
                violations.append(Violation(
                    line_num=line_num,
                    line_text=line[:80],
                    category="algorithm",
                    message=f"Legacy algorithm format P{match.group(1)}.{match.group(2)} - should be 'Algorithm #'",
                    severity=Severity.ERROR,
                    suggestion="Use 'Algorithm #' format with global sequential number"
                ))

    return violations


def check_lean_skeletons(line_num: int, line: str, stripped: str) -> list[Violation]:
    """Check Lean skeleton format: should be 'P# Lean #' or 'Lean #: description'."""
    violations = []

    # Check for Track A/B (legacy P1)
    if re.match(r'^#+\s*Track\s+[A-Z]\b', stripped):
        violations.append(Violation(
            line_num=line_num,
            line_text=line[:80],
            category="lean",
            message="Legacy format 'Track A/B' - should be 'P1 Lean #'",
            severity=Severity.ERROR,
            suggestion="Change 'Track A' to 'P1 Lean 1', 'Track B' to 'P1 Lean 2'"
        ))

    # Check for Lean A/B (legacy P2)
    if re.match(r'^#+\s*Lean\s+[A-Z]\b', stripped):
        violations.append(Violation(
            line_num=line_num,
            line_text=line[:80],
            category="lean",
            message="Legacy format 'Lean A/B' - should be 'P2 Lean #'",
            severity=Severity.ERROR,
            suggestion="Change 'Lean A' to 'Lean 3', 'Lean B' to 'Lean 4'"
        ))

    # Check for Lean without patch prefix (unless it has description after colon)
    match = re.match(r'^#+\s*Lean\s+(\d+)\s*$', stripped)
    if match:
        violations.append(Violation(
            line_num=line_num,
            line_text=line[:80],
            category="lean",
            message=f"Lean {match.group(1)} missing patch prefix - should be 'P# Lean #'",
            severity=Severity.WARNING,
            suggestion="Add patch prefix, e.g., 'P5 Lean 1'"
        ))

    return violations


def check_legacy_formats(line_num: int, line: str, stripped: str) -> list[Violation]:
    """Check for any remaining legacy formats."""
    violations = []

    # Check for parenthetical LaTeX that should be escaped: (G^{...}) instead of \(G^{...}\)
    # Skip lines that:
    # - Already have proper \( or \[ escaping
    # - Start with LaTeX commands (inside display math blocks)
    # - Are clearly LaTeX content (start with backslash after whitespace)
    if '\\(' not in stripped and '\\[' not in stripped:
        # Skip lines that start with LaTeX (likely inside display math)
        if not re.match(r'^\s*\\', stripped):
            if re.search(r'(?<!\\)\([A-Za-z]\^\{', stripped):
                violations.append(Violation(
                    line_num=line_num,
                    line_text=line[:80],
                    category="latex",
                    message="Unescaped LaTeX math - use \\(...\\) instead of (...)",
                    severity=Severity.WARNING,
                    suggestion="Change (G^{...}) to \\(G^{...}\\)"
                ))

    # Check for P8 sections that might be misformatted (P8.# instead of section headers)
    if re.match(r'^#+\s*P8\.\d+\s', stripped) and 'algorithm' not in stripped.lower():
        # P8 uses numbered sections, not P8.# math format
        pass  # This is actually correct for P8

    return violations


def print_report(violations: list[Violation]):
    """Print a formatted violation report."""
    print("=" * 70)
    print("PATTERN SPEC LINT REPORT")
    print("=" * 70)

    if not violations:
        print("\n✓ No violations found! plan.md conforms to pattern_spec.md")
        return

    # Group by severity
    errors = [v for v in violations if v.severity == Severity.ERROR]
    warnings = [v for v in violations if v.severity == Severity.WARNING]
    infos = [v for v in violations if v.severity == Severity.INFO]

    print(f"\nTotal violations: {len(violations)}")
    print(f"  Errors: {len(errors)}")
    print(f"  Warnings: {len(warnings)}")
    print(f"  Info: {len(infos)}")

    # Group by category
    by_category = {}
    for v in violations:
        if v.category not in by_category:
            by_category[v.category] = []
        by_category[v.category].append(v)

    for category, cat_violations in sorted(by_category.items()):
        print(f"\n{'=' * 70}")
        print(f"{category.upper()} ({len(cat_violations)} issues)")
        print("=" * 70)

        for v in cat_violations:
            severity_icon = "❌" if v.severity == Severity.ERROR else "⚠️" if v.severity == Severity.WARNING else "ℹ️"
            print(f"\n{severity_icon} Line {v.line_num}: {v.message}")
            print(f"   {v.line_text}...")
            if v.suggestion:
                print(f"   💡 Suggestion: {v.suggestion}")


def main():
    plan_path = Path(__file__).resolve().parents[2] / "plan.md"

    if not plan_path.exists():
        print(f"Error: {plan_path} not found")
        return 1

    content = plan_path.read_text(encoding='utf-8')
    violations = lint_plan(content)
    print_report(violations)

    # Return exit code
    errors = [v for v in violations if v.severity == Severity.ERROR]
    return 1 if errors else 0


if __name__ == "__main__":
    exit(main())
