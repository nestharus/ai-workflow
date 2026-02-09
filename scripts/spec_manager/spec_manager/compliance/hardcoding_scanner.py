"""No-hardcoding policy scanner for spec manager code.

This module provides a scanner that detects hardcoded phrases/regex used to
parse raw spec text, which violates CON-0003 (no keyword inference) and
CON-0004 (only system stamps allowed).

The scanner runs in report-only mode (warnings, not errors) to flag potential
violations without blocking builds.

Prohibited Patterns (CON-0003):
    1. Scanning raw spec text for keywords like "must/shall" to infer requirements
    2. Regex matching headings like "##" to infer sections as primary logic
    3. Fixed lists of "banned libraries" derived from content semantics

Allowed Patterns (CON-0004):
    1. System stamps and IDs (ATOM/SEC/EVID/LIB/REQ/...)
    2. JSON schemas and explicit output formats
    3. Projection pins and markers owned by the system

Public API:
    HardcodingFinding: A potential hardcoding policy violation
    scan_for_hardcoding_violations: Scan Python files for violations
    scan_file_for_hardcoding_violations: Scan a single file

Usage:
    from spec_manager.compliance.hardcoding_scanner import (
        scan_for_hardcoding_violations,
    )

    findings = scan_for_hardcoding_violations([Path("module.py")])
    for finding in findings:
        print(f"{finding.file}:{finding.line}: {finding.message}")
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spec_manager.core.code_analysis import analyze_source

# =============================================================================
# Finding Data Structure
# =============================================================================


@dataclass
class HardcodingFinding:
    """A potential hardcoding policy violation.

    Attributes:
        severity: Severity level ("warning" for report-only mode).
        file: File path where the violation was found.
        line: Line number of the violation.
        pattern_type: Type of pattern detected.
        message: Human-readable description of the violation.
        code_snippet: The code that triggered the finding.
    """

    severity: str
    file: str
    line: int
    pattern_type: str
    message: str
    code_snippet: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "pattern_type": self.pattern_type,
            "message": self.message,
            "code_snippet": self.code_snippet,
        }


# =============================================================================
# Detection Patterns
# =============================================================================

# Patterns that suggest semantic inference from raw text (CON-0003 violations)
# These detect code that scans for keywords to infer meaning

KEYWORD_INFERENCE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Searching for "must", "shall", "should", "required" as strings in code
    # This suggests inferring requirements from keywords
    (
        re.compile(
            r"""["'](must|shall|should|required|mandatory)["']\s*(in|==)""",
            re.IGNORECASE,
        ),
        "Keyword inference: scanning for requirement keywords in text",
    ),
    # if "must" in line or similar patterns
    (
        re.compile(
            r"""if\s+["'](must|shall|should|required)["']\s+in\s+""",
            re.IGNORECASE,
        ),
        "Keyword inference: using requirement keywords to detect requirements",
    ),
    # Patterns like: "must" in text.lower() or "must" in line.lower()
    (
        re.compile(
            r"""["'](must|shall|should|required)["']\s+in\s+\w+\.lower\(\)""",
            re.IGNORECASE,
        ),
        "Keyword inference: scanning for requirement keywords with case-insensitive check",
    ),
]

# Patterns that suggest heading-based section inference
# These detect code that parses markdown headings to infer structure

HEADING_PARSE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # re.search/match/findall with markdown heading patterns
    (
        re.compile(
            r"""re\.(search|match|findall)\s*\([^)]*["'][^"']*\^?#{1,4}""",
        ),
        "Heading parsing: regex matching markdown headings to infer sections",
    ),
    # Pattern matching for "## Section" style headings as regex patterns
    (
        re.compile(
            r"""r["']\^?#{1,4}\\s""",
        ),
        "Heading parsing: hardcoded heading level pattern",
    ),
]

# Patterns that suggest fixed semantic lists (banned libraries, etc.)
# These detect hardcoded lists derived from content meaning

SEMANTIC_LIST_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Lists of "banned" or "prohibited" items
    (
        re.compile(
            r"""(BANNED|PROHIBITED|FORBIDDEN|BLOCKED)_\w+\s*=\s*[\[\{]""",
            re.IGNORECASE,
        ),
        "Semantic list: hardcoded list of prohibited items",
    ),
    # Lists of requirement/constraint keywords
    (
        re.compile(
            r"""(REQUIREMENT|CONSTRAINT|MUST|SHALL)_KEYWORDS\s*=\s*[\[\{]""",
            re.IGNORECASE,
        ),
        "Semantic list: hardcoded list of requirement keywords",
    ),
]

# Allowlist patterns - these are OK even if they match detection patterns
# System stamps and IDs (CON-0004 allows these)

ALLOWLIST_PATTERNS: list[re.Pattern[str]] = [
    # System ID patterns (ATOM-####, SEC-####, LIB-####, etc.)
    re.compile(r"""["'](ATOM|SEC|EVID|LIB|REQ|F|GAP)-\d"""),
    # Schema validation patterns
    re.compile(r"""["']\$schema["']"""),
    # JSON field names
    re.compile(r"""["'](atom_id|elem_id|lib_id|file_uid|rev_id)["']"""),
    # Test file patterns (tests are allowed to use these)
    # Match only actual test files, not temp directories with "test_" in path
    re.compile(r"""(?:^|[/\\])test_[^/\\]*\.py$|_test\.py$|conftest\.py$"""),
]


# =============================================================================
# Scanner Functions
# =============================================================================


def _is_allowlisted(line: str, file_path: str) -> bool:
    """Check if a line or file is allowlisted.

    Args:
        line: The line of code to check.
        file_path: The file path.

    Returns:
        True if the line/file is allowlisted, False otherwise.
    """
    return any(pattern.search(line) or pattern.search(file_path) for pattern in ALLOWLIST_PATTERNS)


def scan_file_for_hardcoding_violations(
    file_path: Path,
    allowlist: dict[str, list[str]] | None = None,
) -> list[HardcodingFinding]:
    """Scan a single Python file for hardcoding policy violations.

    Args:
        file_path: Path to the Python file to scan.
        allowlist: Optional dict mapping pattern_type to list of allowed patterns.

    Returns:
        List of HardcodingFinding objects for any violations found.
    """
    findings: list[HardcodingFinding] = []

    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return findings

    lines = content.splitlines()
    file_str = str(file_path)

    # Analyze source to get comment line numbers (language-agnostic)
    analysis = analyze_source(content, filepath=file_str)
    comment_lines = {comment.line for comment in analysis.comments}

    # Custom allowlist patterns
    custom_allowlist = allowlist or {}

    for line_no, line in enumerate(lines, start=1):
        # Skip comments (language-agnostic via LLM analysis)
        if line_no in comment_lines:
            continue

        # Skip allowlisted lines/files
        if _is_allowlisted(line, file_str):
            continue

        # Check keyword inference patterns
        for pattern, message in KEYWORD_INFERENCE_PATTERNS:
            if pattern.search(line):
                pattern_type = "keyword_inference"
                if pattern_type in custom_allowlist and any(
                    p in line for p in custom_allowlist[pattern_type]
                ):
                    continue
                findings.append(
                    HardcodingFinding(
                        severity="warning",
                        file=file_str,
                        line=line_no,
                        pattern_type=pattern_type,
                        message=message,
                        code_snippet=line.strip()[:200],
                    )
                )

        # Check heading parse patterns
        for pattern, message in HEADING_PARSE_PATTERNS:
            if pattern.search(line):
                pattern_type = "heading_parse"
                if pattern_type in custom_allowlist and any(
                    p in line for p in custom_allowlist[pattern_type]
                ):
                    continue
                findings.append(
                    HardcodingFinding(
                        severity="warning",
                        file=file_str,
                        line=line_no,
                        pattern_type=pattern_type,
                        message=message,
                        code_snippet=line.strip()[:200],
                    )
                )

        # Check semantic list patterns
        for pattern, message in SEMANTIC_LIST_PATTERNS:
            if pattern.search(line):
                pattern_type = "semantic_list"
                if pattern_type in custom_allowlist and any(
                    p in line for p in custom_allowlist[pattern_type]
                ):
                    continue
                findings.append(
                    HardcodingFinding(
                        severity="warning",
                        file=file_str,
                        line=line_no,
                        pattern_type=pattern_type,
                        message=message,
                        code_snippet=line.strip()[:200],
                    )
                )

    return findings


def scan_for_hardcoding_violations(
    source_paths: list[Path],
    allowlist: dict[str, list[str]] | None = None,
) -> list[HardcodingFinding]:
    """Scan Python source files for hardcoding policy violations.

    This function scans multiple Python files and collects all hardcoding
    policy violations. It runs in report-only mode (warnings only).

    Args:
        source_paths: List of Python file paths to scan.
        allowlist: Optional dict mapping pattern_type to list of allowed patterns.
            Example: {"keyword_inference": ["test_", "mock_"]}

    Returns:
        List of HardcodingFinding objects for all violations found.

    Example:
        >>> findings = scan_for_hardcoding_violations([Path("module.py")])
        >>> for f in findings:
        ...     print(f"[{f.severity}] {f.file}:{f.line}: {f.message}")
    """
    findings: list[HardcodingFinding] = []

    for path in source_paths:
        if not path.exists():
            continue
        if not path.is_file():
            continue
        if path.suffix != ".py":
            continue

        file_findings = scan_file_for_hardcoding_violations(path, allowlist)
        findings.extend(file_findings)

    return findings
