"""
Staging phase operations.

These operations validate and legalize incoming content before any merge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from spec_manager.core.annotations import AnnotationParser
from spec_manager.core.ids import IdValidator, IdCategory
from spec_manager.core.sections import SectionExtractor


class Severity(Enum):
    """Issue severity levels."""

    ERROR = "error"  # Must fix - violates spec
    WARNING = "warning"  # Should fix - legacy format
    INFO = "info"  # Note - might be intentional


@dataclass
class Issue:
    """A validation issue found during staging."""

    line_number: int
    line_text: str
    category: str
    message: str
    severity: Severity
    suggestion: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_number": self.line_number,
            "line_text": self.line_text[:80],
            "category": self.category,
            "message": self.message,
            "severity": self.severity.value,
            "suggestion": self.suggestion,
        }


@dataclass
class StagingResult:
    """Result of staging validation."""

    issues: list[Issue] = field(default_factory=list)
    normalized_content: str | None = None
    duplicate_declarations: list[tuple[str, int, int]] = field(default_factory=list)
    missing_declarations: list[tuple[int, str]] = field(default_factory=list)
    unannotated_references: list[tuple[int, str, str]] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.WARNING)

    @property
    def is_valid(self) -> bool:
        return self.error_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [i.to_dict() for i in self.issues],
            "duplicate_declarations": [
                {"id": d[0], "first_line": d[1], "second_line": d[2]}
                for d in self.duplicate_declarations
            ],
            "missing_declarations": [
                {"line": m[0], "header": m[1]} for m in self.missing_declarations
            ],
            "unannotated_references": [
                {"line": r[0], "id": r[1], "context": r[2]}
                for r in self.unannotated_references
            ],
        }


def lint_patterns(content: str, id_validator: IdValidator | None = None) -> list[Issue]:
    """
    Lint content for pattern violations.

    Checks:
    - Goal format and ranges
    - Invariant format (P#I# not standalone I#)
    - Claim format and ranges
    - Algorithm format
    - Lean skeleton format
    - Legacy annotation formats
    """
    if id_validator is None:
        id_validator = IdValidator()

    issues: list[Issue] = []
    lines = content.split("\n")
    current_section = ""

    for i, line in enumerate(lines):
        line_num = i + 1
        stripped = line.strip()

        # Track current section
        if stripped.startswith("# "):
            current_section = stripped[2:].lower()
        elif stripped.startswith("## "):
            current_section = stripped[3:].lower()

        # Skip empty lines and code blocks
        if not stripped or stripped.startswith("```"):
            continue

        # Check for legacy invariant format (I# without P prefix)
        if re.match(r"^#+\s*\*{0,2}I\d+\b", stripped):
            match = re.search(r"I(\d+)", stripped)
            if match:
                issues.append(
                    Issue(
                        line_number=line_num,
                        line_text=line,
                        category="invariant",
                        message=f"Legacy invariant format I{match.group(1)} - should be P#I#",
                        severity=Severity.ERROR,
                        suggestion=f"Change to P1I{match.group(1)} (assuming P1)",
                    )
                )

        # Check for P#.M# format (legacy math)
        match = re.search(r"\bP(\d+)\.M(\d+)\b", stripped)
        if match:
            issues.append(
                Issue(
                    line_number=line_num,
                    line_text=line,
                    category="math",
                    message=f"Legacy math format P{match.group(1)}.M{match.group(2)}",
                    severity=Severity.ERROR,
                    suggestion=f"Change to P{match.group(1)}.{match.group(2)}",
                )
            )

        # Check for Track A/B (legacy Lean)
        if re.match(r"^#+\s*Track\s+[A-Z]\b", stripped):
            issues.append(
                Issue(
                    line_number=line_num,
                    line_text=line,
                    category="lean",
                    message="Legacy format 'Track A/B'",
                    severity=Severity.ERROR,
                    suggestion="Change 'Track A' to 'P1 Lean 1', 'Track B' to 'P1 Lean 2'",
                )
            )

        # Check for Lean A/B (legacy)
        if re.match(r"^#+\s*Lean\s+[A-Z]\b", stripped):
            issues.append(
                Issue(
                    line_number=line_num,
                    line_text=line,
                    category="lean",
                    message="Legacy format 'Lean A/B'",
                    severity=Severity.ERROR,
                    suggestion="Change to numbered format (Lean 3, Lean 4)",
                )
            )

        # Check for legacy annotation formats
        parser = AnnotationParser()
        legacy = parser.find_legacy_patterns(line)
        for _, matched_text, format_name in legacy:
            issues.append(
                Issue(
                    line_number=line_num,
                    line_text=line,
                    category="annotation",
                    message=f"Legacy annotation format: {format_name}",
                    severity=Severity.ERROR,
                    suggestion=f"Normalize '{matched_text}' to canonical format",
                )
            )

    return issues


def check_duplicate_declarations(content: str) -> list[tuple[str, int, int]]:
    """
    Find duplicate ([=ID]) declarations.

    Returns:
        List of (id, first_line, second_line) tuples
    """
    parser = AnnotationParser()
    validator = IdValidator()

    seen: dict[str, int] = {}
    duplicates: list[tuple[str, int, int]] = []

    for annotation in parser.parse_declarations(content):
        if not validator.is_valid(annotation.id_value):
            continue

        if annotation.id_value in seen:
            duplicates.append(
                (annotation.id_value, seen[annotation.id_value], annotation.line_number)
            )
        else:
            seen[annotation.id_value] = annotation.line_number

    return duplicates


def find_missing_declarations(content: str) -> list[tuple[int, str]]:
    """
    Find markdown headers that might need ([=ID]) declarations.

    Returns:
        List of (line_number, header_text) tuples
    """
    parser = AnnotationParser()
    validator = IdValidator()

    missing: list[tuple[int, str]] = []
    lines = content.split("\n")

    # Patterns that suggest a header should have a declaration
    id_patterns = [
        r"^#+\s*Algorithm\s+\d+",
        r"^#+\s*G\d+",
        r"^#+\s*D\d+",
        r"^#+\s*P\d+I\d+",
        r"^#+\s*P\d+C\d+",
        r"^#+\s*P\d+\.\d+",
        r"^#+\s*Lean\d+",
        r"^#+\s*Comp\d+",
    ]

    for i, line in enumerate(lines):
        line_num = i + 1
        stripped = line.strip()

        # Check if line looks like it should have a declaration
        for pattern in id_patterns:
            if re.match(pattern, stripped):
                # Check if it already has a declaration
                existing = parser.extract_id_from_header(stripped)
                if not existing:
                    missing.append((line_num, stripped))
                break

    return missing


def find_unannotated_references(content: str) -> list[tuple[int, str, str]]:
    """
    Find ID references in prose that lack proper annotation.

    Returns:
        List of (line_number, id_found, context) tuples
    """
    validator = IdValidator()
    parser = AnnotationParser()

    # Get all already-annotated references
    annotated_positions: set[tuple[int, int]] = set()  # (line, column)
    for annotation in parser.parse_all(content):
        annotated_positions.add((annotation.line_number, annotation.column))

    unannotated: list[tuple[int, str, str]] = []
    lines = content.split("\n")
    in_code_block = False

    # Patterns to find ID references
    id_ref_patterns = [
        (r"\bAlgorithm\s+(\d+)\b", lambda m: f"Algorithm {m.group(1)}"),
        (r"\bG(\d+)\b", lambda m: f"G{m.group(1)}"),
        (r"\bD(\d+)\b", lambda m: f"D{m.group(1)}"),
        (r"\bP(\d+)I(\d+)\b", lambda m: f"P{m.group(1)}I{m.group(2)}"),
        (r"\bP(\d+)C(\d+)\b", lambda m: f"P{m.group(1)}C{m.group(2)}"),
        (r"\bLean(\d+)\b", lambda m: f"Lean{m.group(1)}"),
    ]

    for i, line in enumerate(lines):
        line_num = i + 1

        # Track code blocks
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue

        if in_code_block:
            continue

        # Skip headers (they use declarations, not references)
        if line.strip().startswith("#"):
            continue

        for pattern, id_builder in id_ref_patterns:
            for match in re.finditer(pattern, line):
                id_value = id_builder(match)

                # Check if this position is already annotated
                col = match.start()
                # Look for annotation around this position
                is_annotated = False
                for ac, ap in annotated_positions:
                    if ac == line_num and abs(ap - col) < 20:
                        is_annotated = True
                        break

                if not is_annotated and validator.is_valid(id_value):
                    context = line[max(0, match.start() - 20) : match.end() + 20]
                    unannotated.append((line_num, id_value, context))

    return unannotated


def normalize_annotations(content: str) -> str:
    """
    Normalize legacy annotation formats to canonical.

    Transforms:
    - [(=ID)] -> ([=ID])
    - (=[ID]) -> ([=ID])
    - (+[ID]) -> (@[+ID])
    """
    parser = AnnotationParser()
    return parser.normalize_legacy(content)


def run_staging(content: str, source_path: Path | None = None) -> StagingResult:
    """
    Run all staging validations on content.

    Args:
        content: The content to validate
        source_path: Optional source file path for reporting

    Returns:
        StagingResult with all validation findings
    """
    result = StagingResult()

    # Run linting
    result.issues.extend(lint_patterns(content))

    # Check for duplicates
    result.duplicate_declarations = check_duplicate_declarations(content)
    for id_value, first, second in result.duplicate_declarations:
        result.issues.append(
            Issue(
                line_number=second,
                line_text=f"Duplicate declaration of {id_value}",
                category="duplicate",
                message=f"ID '{id_value}' already declared on line {first}",
                severity=Severity.ERROR,
            )
        )

    # Check for missing declarations
    result.missing_declarations = find_missing_declarations(content)
    for line_num, header in result.missing_declarations:
        result.issues.append(
            Issue(
                line_number=line_num,
                line_text=header,
                category="missing_declaration",
                message="Header may need ([=ID]) declaration",
                severity=Severity.WARNING,
            )
        )

    # Check for unannotated references
    result.unannotated_references = find_unannotated_references(content)
    for line_num, id_value, context in result.unannotated_references:
        result.issues.append(
            Issue(
                line_number=line_num,
                line_text=context,
                category="unannotated_reference",
                message=f"Reference to {id_value} may need (@[+{id_value}]) annotation",
                severity=Severity.INFO,
            )
        )

    # Normalize if needed
    normalized = normalize_annotations(content)
    if normalized != content:
        result.normalized_content = normalized

    return result
