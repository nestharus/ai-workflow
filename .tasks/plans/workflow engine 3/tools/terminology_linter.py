#!/usr/bin/env python3
"""Terminology linter for Workflow Engine 3 specification.

Enforces consistent use of domain-specific terminology across the specification
to prevent ambiguity and ensure clear communication.

Usage:
    # Scan directory and print violations to console
    python terminology_linter.py scan ".tasks/plans/workflow engine 3"

    # Generate markdown compliance report
    python terminology_linter.py generate-report ".tasks/plans/workflow engine 3"

    # Generate report to specific output file
    python terminology_linter.py generate-report ".tasks/plans/workflow engine 3" -o /path/to/report.md
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class TerminologyViolation:
    """Represents a single terminology violation."""

    rule_id: str
    description: str
    file_path: str
    line: int
    column: int
    text: str
    severity: str = "warn"


@dataclass
class LinterResult:
    """Collects and formats violation data for reporting."""

    violations: list[TerminologyViolation] = field(default_factory=list)
    files_scanned: int = 0
    files_with_violations: set[str] = field(default_factory=set)

    def add_violation(self, violation: TerminologyViolation) -> None:
        """Add a violation to the result set."""
        self.violations.append(violation)
        self.files_with_violations.add(violation.file_path)

    @property
    def total_violations(self) -> int:
        """Return total number of violations."""
        return len(self.violations)

    def violations_by_file(self) -> dict[str, list[TerminologyViolation]]:
        """Group violations by file path."""
        by_file: dict[str, list[TerminologyViolation]] = {}
        for v in self.violations:
            if v.file_path not in by_file:
                by_file[v.file_path] = []
            by_file[v.file_path].append(v)
        return by_file


class TerminologyRule:
    """Base class for all terminology rules."""

    rule_id: str = "TERMINO000"
    description: str = "Base terminology rule"
    severity: str = "warn"

    def check(self, content: str, file_path: str) -> list[TerminologyViolation]:
        """Check content for violations. Override in subclasses."""
        raise NotImplementedError


class RuleTERMINO001(TerminologyRule):
    """Detect bare 'workspace' usage except in allowed contexts.

    Allowed contexts:
    1. When preceded by "jj " (Jujutsu tool references)
    2. When followed by "/" (file path contexts)
    3. When part of "Workspace State Store" or "WSS"
    """

    rule_id = "TERMINO001"
    description = 'Bare "workspace" usage'
    severity = "error"

    # Pattern to find all "workspace" tokens (case-insensitive, word boundary)
    _workspace_pattern = re.compile(r"\bworkspace\b", re.IGNORECASE)

    # Pattern to detect intentional violation comments
    _intentional_violation_pattern = re.compile(
        r"<!--\s*TERMINO001:\s*intentional\s+violation",
        re.IGNORECASE
    )

    # Patterns for allowed contexts
    _jj_prefix_pattern = re.compile(r"jj\s+workspace\b", re.IGNORECASE)
    _path_suffix_pattern = re.compile(r"\bworkspace/", re.IGNORECASE)
    _wss_phrase_pattern = re.compile(
        r"Workspace\s+State\s+Store", re.IGNORECASE
    )
    _wss_abbrev_pattern = re.compile(r"\bWSS\b")
    _hyphenated_pattern = re.compile(r"Workspace-State-", re.IGNORECASE)
    _store_suffix_pattern = re.compile(r"\bworkspace\s+Store\b", re.IGNORECASE)

    def check(self, content: str, file_path: str) -> list[TerminologyViolation]:
        """Check content for bare 'workspace' violations."""
        violations: list[TerminologyViolation] = []
        lines = content.split("\n")

        for line_num, line in enumerate(lines, start=1):
            # Skip lines with intentional violation comments
            if self._has_intentional_violation_comment(line):
                continue

            # Find all workspace occurrences in this line
            for match in self._workspace_pattern.finditer(line):
                start = match.start()
                end = match.end()

                # Check if this occurrence is in an allowed context
                if self._is_allowed(line, start, end):
                    continue

                violations.append(
                    TerminologyViolation(
                        rule_id=self.rule_id,
                        description=self.description,
                        file_path=file_path,
                        line=line_num,
                        column=start + 1,
                        text=line.strip(),
                        severity=self.severity,
                    )
                )

        return violations

    def _has_intentional_violation_comment(self, line: str) -> bool:
        """Check if line contains an intentional violation comment."""
        return bool(self._intentional_violation_pattern.search(line))

    def _is_allowed(self, line: str, start: int, end: int) -> bool:
        """Check if the workspace occurrence at [start:end] is allowed."""
        # Check for "jj workspace" pattern (look back for "jj ")
        prefix_start = max(0, start - 10)
        prefix = line[prefix_start:end]
        if self._jj_prefix_pattern.search(prefix):
            return True

        # Check for "workspace/" pattern (path context)
        suffix_end = min(len(line), end + 1)
        if end < len(line) and line[end] == "/":
            return True

        # Check for "Workspace State Store" phrase
        context_start = max(0, start - 5)
        context_end = min(len(line), end + 20)
        context = line[context_start:context_end]
        if self._wss_phrase_pattern.search(context):
            return True

        # Check for "Workspace-State-" hyphenated compound
        if self._hyphenated_pattern.search(context):
            return True

        # Check for "workspace Store" pattern
        store_context = line[start : min(len(line), end + 10)]
        if self._store_suffix_pattern.match(store_context):
            return True

        return False


class TerminologyLinter:
    """Orchestrates scanning of directories and applies all rules."""

    def __init__(self) -> None:
        """Initialize linter with all registered rules."""
        self.rules: list[TerminologyRule] = [
            RuleTERMINO001(),
        ]

    def scan_file(self, file_path: Path) -> list[TerminologyViolation]:
        """Scan a single file for terminology violations."""
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)
            return []

        violations: list[TerminologyViolation] = []
        for rule in self.rules:
            violations.extend(rule.check(content, str(file_path)))

        return violations

    def scan_directory(self, directory: Path) -> LinterResult:
        """Scan all .md files in a directory recursively."""
        result = LinterResult()

        # Skip the compliance report itself to avoid self-references
        skip_files = {directory / "TERMINOLOGY_COMPLIANCE_REPORT.md"}

        md_files = [f for f in directory.rglob("*.md") if f not in skip_files]
        result.files_scanned = len(md_files)

        for md_file in md_files:
            violations = self.scan_file(md_file)
            for v in violations:
                result.add_violation(v)

        return result


def format_console_output(result: LinterResult) -> str:
    """Format linter results for console output with colors."""
    if result.total_violations == 0:
        return "\033[32m✓ No terminology violations found.\033[0m"

    lines: list[str] = []
    lines.append(
        f"\033[33m⚠ Found {result.total_violations} terminology "
        f"violation(s) in {len(result.files_with_violations)} file(s)\033[0m"
    )
    lines.append("")

    for file_path, violations in sorted(result.violations_by_file().items()):
        lines.append(f"\033[1m{file_path}\033[0m")
        for v in sorted(violations, key=lambda x: (x.line, x.column)):
            severity_color = "\033[33m" if v.severity == "warn" else "\033[31m"
            lines.append(
                f"  {severity_color}{v.rule_id}\033[0m "
                f"[{v.line}:{v.column}] {v.description}"
            )
            lines.append(f"    {v.text[:80]}{'...' if len(v.text) > 80 else ''}")
        lines.append("")

    return "\n".join(lines)


def generate_markdown_report(result: LinterResult, scanned_path: str) -> str:
    """Generate a markdown compliance report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = [
        "# Terminology Compliance Report",
        "",
        f"**Generated**: {now}",
        f"**Scanned path**: `{scanned_path}`",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Files scanned | {result.files_scanned} |",
        f"| Files with violations | {len(result.files_with_violations)} |",
        f"| Total violations | {result.total_violations} |",
        "",
    ]

    if result.total_violations == 0:
        lines.append("✅ **No terminology violations found.**")
        return "\n".join(lines)

    lines.append("## Violations by File")
    lines.append("")

    for file_path, violations in sorted(result.violations_by_file().items()):
        lines.append(f"### `{file_path}`")
        lines.append("")
        lines.append("| Line | Column | Rule | Text |")
        lines.append("|------|--------|------|------|")
        for v in sorted(violations, key=lambda x: (x.line, x.column)):
            text_preview = v.text[:60].replace("|", "\\|")
            if len(v.text) > 60:
                text_preview += "..."
            lines.append(f"| {v.line} | {v.column} | {v.rule_id} | {text_preview} |")
        lines.append("")

    lines.extend([
        "## Remediation Steps",
        "",
        "For each TERMINO001 violation:",
        "",
        "1. Determine whether the reference is to:",
        "   - The durable state store → use **WSS**",
        "   - The ephemeral execution environment → use **sandbox**",
        "   - A Jujutsu command or concept → qualify as **jj workspace**",
        "",
        "2. Replace the bare \"workspace\" token with the appropriate term",
        "",
        "3. Re-run the linter to verify compliance",
        "",
    ])

    return "\n".join(lines)


def cmd_scan(args: argparse.Namespace) -> int:
    """Execute the scan command."""
    path = Path(args.path)
    if not path.exists():
        print(f"Error: Path does not exist: {path}", file=sys.stderr)
        return 1

    linter = TerminologyLinter()

    if path.is_file():
        violations = linter.scan_file(path)
        result = LinterResult()
        result.files_scanned = 1
        for v in violations:
            result.add_violation(v)
    else:
        result = linter.scan_directory(path)

    print(format_console_output(result))

    # Return non-zero exit code if violations found
    return 1 if result.total_violations > 0 else 0


def cmd_generate_report(args: argparse.Namespace) -> int:
    """Execute the generate-report command."""
    path = Path(args.path)
    if not path.exists():
        print(f"Error: Path does not exist: {path}", file=sys.stderr)
        return 1

    linter = TerminologyLinter()

    if path.is_file():
        violations = linter.scan_file(path)
        result = LinterResult()
        result.files_scanned = 1
        for v in violations:
            result.add_violation(v)
        output_dir = path.parent
    else:
        result = linter.scan_directory(path)
        output_dir = path

    report = generate_markdown_report(result, str(path))

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = output_dir / "TERMINOLOGY_COMPLIANCE_REPORT.md"

    output_path.write_text(report, encoding="utf-8")
    print(f"Report written to: {output_path}")

    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Terminology linter for Workflow Engine 3 specification"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan command
    scan_parser = subparsers.add_parser(
        "scan", help="Scan directory and print violations to console"
    )
    scan_parser.add_argument("path", help="Path to scan (file or directory)")
    scan_parser.set_defaults(func=cmd_scan)

    # generate-report command
    report_parser = subparsers.add_parser(
        "generate-report", help="Generate markdown compliance report"
    )
    report_parser.add_argument("path", help="Path to scan (file or directory)")
    report_parser.add_argument(
        "-o", "--output", help="Output file path (default: TERMINOLOGY_COMPLIANCE_REPORT.md in scanned directory)"
    )
    report_parser.set_defaults(func=cmd_generate_report)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
