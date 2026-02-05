"""Evidence field linting for EVID-only compliance (CON-0021, ALG-COMP-0005).

This module implements ALG-COMP-0005: ScanForForbiddenOutputSignatures.

Evidence fields in L1 artifacts must contain only EVID-format references.
Free-text fields may trigger warnings for derived artifact path references.

CON-0021 Enforcement:
- HARD ERROR: evidence fields with non-EVID values
- WARNING: free-text with derived artifact references (runs/, views/, etc.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.schemas.evidence_ranges import EVIDENCE_ID_PATTERN

# Per CON-0021: Evidence fields must be EVID-* only
EVID_FIELD_PATTERN = re.compile(r"^EVID-F\d{4}-R\d{4}-L\d+-L\d+$")

# Derived artifact tokens to warn on (per CON-0021)
DERIVED_ARTIFACT_PATTERNS = [
    re.compile(r"runs/"),
    re.compile(r"views/"),
    re.compile(r"spec_snapshot/"),
    re.compile(r"\.json$"),
    re.compile(r"\.yaml$"),
]

# Legacy citation patterns that are forbidden in evidence fields
LEGACY_CITATION_PATTERNS = [
    re.compile(r"\[F\d{4}::[^\]]+\]"),  # [F####::SECTION]
    re.compile(r"\[spec_snapshot/[^\]]+\]"),  # [spec_snapshot/...::...]
    re.compile(r"\[LIB-\d{4}::[^\]]+\]"),  # [LIB-####::...]
]

# Known evidence field names in artifacts
EVIDENCE_FIELD_NAMES = frozenset(
    {
        "evidence",
        "evidence_id",
        "evidence_ids",
        "evidence_sources",
        "evidence_refs",
        "evidence_references",
        "citations",
        "source_evidence",
        "supporting_evidence",
    }
)


@dataclass
class LintResult:
    """Result of linting an artifact.

    Attributes:
        errors: List of hard error messages (EVID-only violations)
        warnings: List of warning messages (derived artifact refs in free text)
        passed: True if no errors (warnings are OK)
    """

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Returns True if there are no errors."""
        return len(self.errors) == 0


def is_evidence_field(field_name: str) -> bool:
    """Check if a field name is an evidence field.

    Args:
        field_name: Name of the field to check

    Returns:
        True if this is a known evidence field name
    """
    normalized = field_name.lower().strip()
    return normalized in EVIDENCE_FIELD_NAMES


def validate_evid_value(value: str) -> bool:
    """Validate that a value is a valid EVID reference.

    Args:
        value: Value to validate

    Returns:
        True if valid EVID format
    """
    return EVID_FIELD_PATTERN.fullmatch(value.strip()) is not None


def scan_evidence_fields(
    artifact: dict[str, Any],
    allowlist: dict[str, list[str]] | None = None,
) -> tuple[list[str], list[str]]:
    """Scan artifact for evidence field violations (ALG-COMP-0005).

    Args:
        artifact: Artifact dictionary to scan
        allowlist: Optional mapping of field_name -> allowed non-EVID values

    Returns:
        Tuple of (errors, warnings) per CON-0021:
        - errors: evidence fields with non-EVID values (hard error)
        - warnings: free-text with derived artifact references
    """
    errors: list[str] = []
    warnings: list[str] = []
    allowlist = allowlist or {}

    def _scan_value(
        value: Any,
        path: str,
        in_evidence_field: bool = False,
        parent_field: str | None = None,
    ) -> None:
        """Recursively scan a value for violations."""
        if isinstance(value, str):
            if in_evidence_field:
                # Check allowlist for both exact path and parent field name
                allowed = allowlist.get(path, [])
                if parent_field and parent_field in allowlist:
                    allowed = allowed + allowlist[parent_field]
                _check_evidence_value(value, path, errors, allowed)
            else:
                _check_freetext_value(value, path, warnings)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                item_path = f"{path}[{i}]"
                _scan_value(item, item_path, in_evidence_field, parent_field=path)
        elif isinstance(value, dict):
            for key, val in value.items():
                field_path = f"{path}.{key}" if path else key
                is_evidence = is_evidence_field(key)
                _scan_value(val, field_path, is_evidence, parent_field=key if is_evidence else parent_field)

    _scan_value(artifact, "")
    return errors, warnings


def _check_evidence_value(
    value: str,
    path: str,
    errors: list[str],
    allowed_values: list[str],
) -> None:
    """Check an evidence field value for violations."""
    value = value.strip()
    if not value:
        return

    # Check if explicitly allowed
    if value in allowed_values:
        return

    # Check if valid EVID format
    if validate_evid_value(value):
        return

    # Check for legacy citation patterns
    for pattern in LEGACY_CITATION_PATTERNS:
        if pattern.search(value):
            errors.append(
                f"{path}: Legacy citation format in evidence field: '{value}'"
            )
            return

    # Generic non-EVID value
    errors.append(f"{path}: Non-EVID value in evidence field: '{value}'")


def _check_freetext_value(value: str, path: str, warnings: list[str]) -> None:
    """Check a free-text field value for derived artifact warnings."""
    for pattern in DERIVED_ARTIFACT_PATTERNS:
        if pattern.search(value):
            warnings.append(
                f"{path}: Derived artifact reference in free text: '{value[:100]}...'"
                if len(value) > 100
                else f"{path}: Derived artifact reference in free text: '{value}'"
            )
            break


def lint_l1_artifact(
    artifact_path: Path,
    artifact_type: str = "generic",
) -> LintResult:
    """Lint an L1 artifact file for EVID-only compliance.

    Args:
        artifact_path: Path to the artifact file (JSON or markdown)
        artifact_type: Type of artifact for context-specific checks

    Returns:
        LintResult with errors and warnings
    """
    import json

    result = LintResult()

    if not artifact_path.exists():
        result.errors.append(f"Artifact file not found: {artifact_path}")
        return result

    try:
        content = artifact_path.read_text(encoding="utf-8")
    except OSError as e:
        result.errors.append(f"Failed to read artifact: {e}")
        return result

    # Handle JSON artifacts
    if artifact_path.suffix == ".json":
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            result.errors.append(f"Invalid JSON: {e}")
            return result

        errors, warnings = scan_evidence_fields(data)
        result.errors.extend(errors)
        result.warnings.extend(warnings)

    # Handle markdown artifacts
    elif artifact_path.suffix == ".md":
        result.errors.extend(_lint_markdown_evidence(content))
        result.warnings.extend(_lint_markdown_derived_refs(content))

    return result


def _lint_markdown_evidence(content: str) -> list[str]:
    """Lint markdown content for evidence field violations."""
    errors: list[str] = []

    # Look for evidence patterns in markdown
    # Pattern: **Evidence:** or Evidence: followed by citation
    evidence_pattern = re.compile(
        r"(?:^|\n)\s*\*?\*?Evidence\*?\*?:\s*(.+?)(?=\n|$)", re.IGNORECASE
    )

    for match in evidence_pattern.finditer(content):
        evidence_text = match.group(1).strip()
        # Extract citations from the evidence text
        citations = re.findall(r"\[[^\]]+\]", evidence_text)
        for citation in citations:
            inner = citation[1:-1]  # Remove brackets
            if not EVIDENCE_ID_PATTERN.fullmatch(inner):
                # Check if it's a legacy pattern
                is_legacy = any(p.search(citation) for p in LEGACY_CITATION_PATTERNS)
                if is_legacy or not inner.startswith("EVID-"):
                    errors.append(
                        f"Non-EVID citation in evidence field: {citation}"
                    )

    return errors


def _lint_markdown_derived_refs(content: str) -> list[str]:
    """Lint markdown content for derived artifact warnings."""
    warnings: list[str] = []

    for line_no, line in enumerate(content.splitlines(), start=1):
        for pattern in DERIVED_ARTIFACT_PATTERNS:
            if pattern.search(line):
                warnings.append(
                    f"Line {line_no}: Derived artifact reference: '{line.strip()[:80]}'"
                )
                break

    return warnings


def scan_for_forbidden_output_signatures(
    text: str,
    context: str = "unknown",
) -> tuple[list[str], list[str]]:
    """Scan text for forbidden output signatures (ALG-COMP-0005).

    This is a convenience function for scanning arbitrary text for
    CON-0021 violations without structured field context.

    Args:
        text: Text to scan
        context: Context description for error messages

    Returns:
        Tuple of (errors, warnings)
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Check for legacy citations that should be EVID
    for pattern in LEGACY_CITATION_PATTERNS:
        for match in pattern.finditer(text):
            errors.append(
                f"{context}: Legacy citation found (should be EVID): {match.group(0)}"
            )

    # Check for derived artifact references
    for pattern in DERIVED_ARTIFACT_PATTERNS:
        for match in pattern.finditer(text):
            # Get surrounding context
            start = max(0, match.start() - 20)
            end = min(len(text), match.end() + 20)
            context_text = text[start:end].replace("\n", " ")
            warnings.append(
                f"{context}: Derived artifact reference: '...{context_text}...'"
            )

    return errors, warnings
