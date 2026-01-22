"""Compliance metrics computation for spec management.

This module provides functions to compute compliance metrics for specification
content based on tracked units. The metrics measure:

- Format compliance: How well annotations follow canonical patterns
- Annotation coverage: What percentage of structured elements have ID annotations
- ID normalization: What percentage of IDs follow canonical format

Formula Reference:
    format_compliance = compliant_units / total_units
    annotation_coverage = annotated_structured_elements / total_structured_elements
    id_normalization = canonical_ids / total_unique_ids

Edge Case Behavior:
    - Empty unit lists return 1.0 (perfect compliance by default)
    - No structured elements returns 1.0 for annotation coverage
    - No IDs returns 1.0 for ID normalization
    - Partial compliance within a unit counts as non-compliant (all-or-nothing)

Usage:
    from spec_manager.compliance import compute_compliance_metrics
    from spec_manager.core.provenance import TrackedUnit

    units = [...]  # List of TrackedUnit objects
    metrics = compute_compliance_metrics(units)

    if metrics.gate_passed():
        print("Quality gate passed!")
"""

from __future__ import annotations

import re

from spec_manager.core.annotations import AnnotationParser
from spec_manager.core.data_structures import ComplianceMetrics
from spec_manager.core.ids import IdCategory, IdValidator
from spec_manager.core.provenance import TrackedUnit, UnitType

# =============================================================================
# Module-level Singletons
# =============================================================================

# Reusable instances to avoid repeated construction
_annotation_parser = AnnotationParser()
_id_validator = IdValidator()


# =============================================================================
# Helper Functions
# =============================================================================


def _is_format_compliant(
    unit: TrackedUnit,
    parser: AnnotationParser = _annotation_parser,
    validator: IdValidator = _id_validator,
) -> bool:
    """Check if a unit's annotations follow canonical format.

    A unit is format-compliant if ALL of the following are true:
    1. All declarations in unit.declarations match ([=ID]) pattern in content
    2. All references in unit.references match (@[+ID]) or (@[=ID]) patterns
    3. All IDs are valid (match known ID patterns)
    4. Headers with IDs have proper declaration annotations

    Units without any IDs/references are considered compliant.

    Args:
        unit: The TrackedUnit to check.

    Returns:
        True if the unit is format-compliant, False otherwise.
    """
    # Extract actual annotations from content
    content_declarations = {ann.id_value for ann in parser.parse_declarations(unit.content)}
    content_references = {ann.id_value for ann in parser.parse_references(unit.content)}

    # Check 1: All declared IDs in unit.declarations should appear in content
    for decl_id in unit.declarations:
        if decl_id not in content_declarations:
            return False

    # Check 2: All references in unit.references should appear in content
    for ref_id in unit.references:
        if ref_id not in content_references:
            return False

    # Check 3: All IDs should be valid format
    all_ids = set(unit.declarations) | set(unit.references)
    for id_value in all_ids:
        if not validator.is_valid(id_value):
            return False

    # Check 4: Headers with IDs should have proper declaration
    # Check if content starts with markdown header containing an ID
    lines = unit.content.splitlines()
    if lines:
        first_line = lines[0].strip()
        if first_line.startswith("#"):
            # Use IdValidator patterns to detect ID-like patterns in headers
            for id_pattern in validator.PATTERNS:
                # Extract the regex pattern from IdPattern
                pattern = id_pattern.pattern.pattern
                match = re.search(pattern, first_line, re.IGNORECASE)
                if match:
                    # Header contains an ID-like pattern
                    # Check if there's a declaration in the header or first body line
                    header_has_decl = bool(parser.DECLARATION_PATTERN.search(first_line))
                    body_has_decl = len(lines) > 1 and bool(
                        parser.DECLARATION_PATTERN.search(lines[1])
                    )
                    if not (header_has_decl or body_has_decl):
                        return False
                    break

    return True


def _is_structured_element(unit: TrackedUnit) -> bool:
    """Check if a unit is a structured element type.

    Structured elements are elements that should have ID annotations:
    - ALGORITHM
    - DATA_STRUCTURE
    - CLAIM
    - INVARIANT
    - GOAL

    Also checks content for markdown headers matching structured patterns.

    Args:
        unit: The TrackedUnit to check.

    Returns:
        True if the unit is a structured element, False otherwise.
    """
    # Check unit_type first
    structured_types = {
        UnitType.ALGORITHM,
        UnitType.DATA_STRUCTURE,
        UnitType.CLAIM,
        UnitType.INVARIANT,
        UnitType.GOAL,
    }

    if unit.unit_type in structured_types:
        return True

    # Also check content for markdown headers matching patterns
    structured_patterns = [
        r"^#{1,4}\s*Algorithm\s+\d+",
        r"^#{1,4}\s*D\d+",
        r"^#{1,4}\s*Claim\s+",
        r"^#{1,4}\s*Invariant\s+",
        r"^#{1,4}\s*Component\s+",
        r"^#{1,4}\s*Goal\s+",
    ]

    for line in unit.content.splitlines():
        line = line.strip()
        for pattern in structured_patterns:
            if re.match(pattern, line, re.IGNORECASE):
                return True

    return False


def _has_id_annotation(unit: TrackedUnit) -> bool:
    """Check if a unit has an ID declaration annotation.

    A unit has an ID annotation if:
    1. unit.declarations list is non-empty, AND
    2. At least one ([=ID]) pattern exists in unit content

    Args:
        unit: The TrackedUnit to check.

    Returns:
        True if the unit has an ID annotation, False otherwise.
    """
    if not unit.declarations:
        return False

    return any(_annotation_parser.parse_declarations(unit.content))


def _extract_unique_ids(units: list[TrackedUnit]) -> set[str]:
    """Extract all unique IDs from a list of units.

    Collects IDs from both declarations and references across all units.

    Args:
        units: List of TrackedUnit objects.

    Returns:
        Set of unique ID strings.
    """
    unique_ids: set[str] = set()

    for unit in units:
        unique_ids.update(unit.declarations)
        unique_ids.update(unit.references)

    return unique_ids


def _is_canonical_format(id_value: str) -> bool:
    """Check if an ID follows canonical (non-legacy) format.

    Canonical formats:
    - Algorithm #: "Algorithm 1" (with single space)
    - D#: "D1", "D10" (no prefix)
    - I#: "I1", "I1.2" (not P#I#)
    - C#: "C1" (not P#C#)
    - Comp#: "Comp1"
    - Lean#: "Lean1"

    Legacy (non-canonical) formats:
    - G#: Should be I#
    - P#I#: Should be I#
    - P#C#: Should be C#

    Args:
        id_value: The ID string to check.

    Returns:
        True if the ID is in canonical format, False if legacy/non-canonical.
    """
    category = _id_validator.get_category(id_value)

    # Legacy formats are NOT canonical
    if category == IdCategory.GOAL:
        # G# is legacy, should be I#
        return False

    if category == IdCategory.PATCH_INVARIANT:
        # P#I# is legacy, should be I#
        return False

    if category == IdCategory.PATCH_CLAIM:
        # P#C# is legacy, should be C#
        return False

    # Check specific canonical patterns
    canonical_patterns = {
        IdCategory.ALGORITHM: r"^Algorithm \d+$",  # Must have single space
        IdCategory.DATA_STRUCTURE: r"^D\d+$",
        IdCategory.INVARIANT: r"^I\d+(\.\d+)?$",  # I# or I#.#
        IdCategory.CLAIM: r"^C\d+$",
        IdCategory.COMPONENT: r"^Comp\d+$",
        IdCategory.LEAN: r"^Lean\d+$",
        IdCategory.STATEMENT: r"^S\d+$",
        IdCategory.TOPIC: r"^T\d+$",
        IdCategory.NON_FUNCTIONAL_GOAL: r"^NFG\d+$",
        IdCategory.GAP: r"^Gap G\d+\.\d+$",
        IdCategory.PATCH: r"^P\d+$",
        IdCategory.PATCH_SECTION: r"^P\d+\.\d+$",
    }

    if category in canonical_patterns:
        pattern = canonical_patterns[category]
        return bool(re.match(pattern, id_value))

    # Unknown category - not canonical
    # Only treat as canonical if there's an explicit pattern entry
    # For unhandled categories, return False to avoid silent acceptance
    if category == IdCategory.UNKNOWN or category not in canonical_patterns:
        return False


# =============================================================================
# Main Compliance Functions
# =============================================================================


def compute_format_compliance(units: list[TrackedUnit]) -> float:
    """Compute format compliance score for a list of units.

    Format compliance measures what percentage of units follow canonical
    annotation patterns. A unit is compliant if all its annotations use
    canonical syntax: ([=ID]) for declarations, (@[+ID]) for related refs,
    (@[=ID]) for labeled refs.

    Formula: compliant_count / total_count

    Args:
        units: List of TrackedUnit objects to analyze.

    Returns:
        Float in range [0.0, 1.0]. Returns 1.0 for empty list.

    Example:
        >>> units = [unit1, unit2, unit3]
        >>> score = compute_format_compliance(units)
        >>> print(f"Format compliance: {score:.1%}")
    """
    if not units:
        return 1.0

    compliant_count = sum(1 for unit in units if _is_format_compliant(unit))
    return compliant_count / len(units)


def compute_annotation_coverage(units: list[TrackedUnit]) -> float:
    """Compute annotation coverage score for a list of units.

    Annotation coverage measures what percentage of structured elements
    have proper ID annotations. Structured elements include: Algorithm,
    Data Structure, Claim, Invariant, and Goal types.

    Formula: annotated_structured_count / total_structured_count

    Args:
        units: List of TrackedUnit objects to analyze.

    Returns:
        Float in range [0.0, 1.0]. Returns 1.0 if no structured elements.

    Example:
        >>> units = [unit1, unit2, unit3]
        >>> score = compute_annotation_coverage(units)
        >>> print(f"Annotation coverage: {score:.1%}")
    """
    if not units:
        return 1.0

    structured_units = [unit for unit in units if _is_structured_element(unit)]

    if not structured_units:
        return 1.0

    annotated_count = sum(1 for unit in structured_units if _has_id_annotation(unit))
    return annotated_count / len(structured_units)


def compute_id_normalization(units: list[TrackedUnit]) -> float:
    """Compute ID normalization score for a list of units.

    ID normalization measures what percentage of unique IDs follow
    canonical format. Legacy formats (G#, P#I#, P#C#) are counted as
    non-canonical.

    Formula: canonical_count / total_unique_ids

    Args:
        units: List of TrackedUnit objects to analyze.

    Returns:
        Float in range [0.0, 1.0]. Returns 1.0 if no IDs found.

    Example:
        >>> units = [unit1, unit2, unit3]
        >>> score = compute_id_normalization(units)
        >>> print(f"ID normalization: {score:.1%}")
    """
    if not units:
        return 1.0

    unique_ids = _extract_unique_ids(units)

    if not unique_ids:
        return 1.0

    canonical_count = sum(1 for id_value in unique_ids if _is_canonical_format(id_value))
    return canonical_count / len(unique_ids)


def compute_compliance_metrics(
    units: list[TrackedUnit],
    gate_threshold: float = 0.85,
) -> ComplianceMetrics:
    """Compute all compliance metrics and return a ComplianceMetrics object.

    This is the main entry point for compliance analysis. It computes:
    - Format compliance: How well annotations follow canonical patterns
    - Annotation coverage: What percentage of structured elements have IDs
    - ID normalization: What percentage of IDs follow canonical format

    Args:
        units: List of TrackedUnit objects to analyze.
        gate_threshold: Minimum threshold for passing quality gate (default 0.85).

    Returns:
        ComplianceMetrics object with all computed scores.

    Example:
        >>> units = [unit1, unit2, unit3]
        >>> metrics = compute_compliance_metrics(units)
        >>> if metrics.gate_passed():
        ...     print("Quality gate passed!")
        >>> print(f"Format: {metrics.format_compliance:.1%}")
        >>> print(f"Coverage: {metrics.annotation_coverage:.1%}")
        >>> print(f"Normalization: {metrics.id_normalization:.1%}")
    """
    format_compliance = compute_format_compliance(units)
    annotation_coverage = compute_annotation_coverage(units)
    id_normalization = compute_id_normalization(units)

    return ComplianceMetrics(
        format_compliance=format_compliance,
        annotation_coverage=annotation_coverage,
        id_normalization=id_normalization,
        gate_threshold=gate_threshold,
    )
