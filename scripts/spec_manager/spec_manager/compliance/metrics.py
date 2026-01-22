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

import logging
import re

from ..core.annotations import AnnotationParser
from ..core.data_structures import ComplianceMetrics
from ..core.ids import IdCategory, IdValidator
from ..core.provenance import TrackedUnit, UnitType

# =============================================================================
# Module-level Singletons
# =============================================================================

# Reusable instances to avoid repeated construction
_annotation_parser = AnnotationParser()
_id_validator = IdValidator()
_logger = logging.getLogger(__name__)


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
        parser: AnnotationParser instance to use for parsing content.
        validator: IdValidator instance to use for ID validation.

    Returns:
        True if the unit is format-compliant, False otherwise.
    """
    try:
        # Validate unit has required attributes
        if (
            not hasattr(unit, "content")
            or not hasattr(unit, "declarations")
            or not hasattr(unit, "references")
        ):
            _logger.warning(
                "Unit missing required attributes (content, declarations, or references)"
            )
            return False

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
        # Parse markdown header to extract ID and verify matching ([=ID]) declaration
        lines = unit.content.splitlines()
        if lines:
            first_line = lines[0].strip()
            if first_line.startswith("#"):
                # Strip leading # characters and whitespace to get header text
                header_text = first_line.lstrip("#").strip()

                # Try to extract an ID from the header text
                # Patterns for various ID types in headers (allowing title suffixes)
                header_id_patterns = [
                    (r"Algorithm\s+(\d+)", IdCategory.ALGORITHM, "Algorithm {}"),
                    (r"D(\d+)", IdCategory.DATA_STRUCTURE, "D{}"),
                    (r"Claim\s+(\d+)", IdCategory.CLAIM, "C{}"),
                    (r"Invariant\s+(\d+)", IdCategory.INVARIANT, "I{}"),
                    (r"Goal\s+G?(\d+(?:\.\d+)?)", IdCategory.GOAL, "G{}"),
                    (r"I(\d+(?:\.\d+)?)", IdCategory.INVARIANT, "I{}"),
                    (r"G(\d+(?:\.\d+)?)", IdCategory.GOAL, "G{}"),
                    (r"C(\d+)", IdCategory.CLAIM, "C{}"),
                    (r"Comp(\d+)", IdCategory.COMPONENT, "Comp{}"),
                    (r"Lean(\d+)", IdCategory.LEAN, "Lean{}"),
                ]

                header_id = None
                for pattern, _, template in header_id_patterns:
                    match = re.search(pattern, header_text, re.IGNORECASE)
                    if match:
                        # Extract the ID from header
                        if "{}" in template:
                            # Single component pattern
                            header_id = template.format(match.group(1))
                        else:
                            # Complex pattern like P{}I{}
                            parts = match.groups()
                            if len(parts) == 2:
                                header_id = template.format(*parts)
                            else:
                                header_id = template.format(match.group(1))
                        break

                # If we found an ID in the header, check for matching declaration
                if header_id:
                    # Check if header line contains ([=ID]) for this header_id
                    header_decl_pattern = rf"\(\[=\s*{re.escape(header_id)}\s*\]\)"
                    if re.search(header_decl_pattern, first_line):
                        # Header has the declaration - compliant
                        pass
                    # Check if first body line has the declaration
                    elif len(lines) > 1:
                        if not re.search(header_decl_pattern, lines[1]):
                            return False
                    else:
                        # Header has ID but no declaration in header or body line
                        return False

        return True

    except Exception as e:
        _logger.warning(f"Error checking format compliance for unit: {e}")
        return False


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
    try:
        # Validate unit has required attributes
        if not hasattr(unit, "unit_type") or not hasattr(unit, "content"):
            _logger.warning("Unit missing required attributes (unit_type or content)")
            return False

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
        # Loosened patterns to align with plan - don't require digits for type detection
        # Allow optional separators/titles (e.g., "## Algorithm:", "## Claim - ...")
        structured_patterns = [
            r"^#{1,4}\s*Algorithm\b",  # Algorithm with or without digits
            r"^#{1,4}\s*D\d+",  # D# (data structures)
            r"^#{1,4}\s*Claim\b",  # Claim with optional punctuation/title
            r"^#{1,4}\s*Invariant\b",  # Invariant with optional punctuation/title
            r"^#{1,4}\s*Component\b",  # Component with optional punctuation/title
            r"^#{1,4}\s*Goal\b",  # Goal with optional punctuation/title
        ]

        for line in unit.content.splitlines():
            line = line.strip()
            for pattern in structured_patterns:
                if re.match(pattern, line, re.IGNORECASE):
                    return True

        return False

    except Exception as e:
        _logger.warning(f"Error checking if unit is structured element: {e}")
        return False


def _has_id_annotation(
    unit: TrackedUnit,
    parser: AnnotationParser = _annotation_parser,
    validator: IdValidator = _id_validator,
) -> bool:
    """Check if a unit has an ID declaration annotation.

    A unit has an ID annotation if:
    1. unit.declarations list is non-empty, AND
    2. At least one ([=ID]) pattern exists in unit content
    3. The declared ID is in unit.declarations (intersection check)
    4. The ID matches the element type/category

    Args:
        unit: The TrackedUnit to check.
        parser: AnnotationParser instance to use.
        validator: IdValidator instance to use.

    Returns:
        True if the unit has an ID annotation, False otherwise.
    """
    try:
        # Validate unit has required attributes
        if (
            not hasattr(unit, "declarations")
            or not hasattr(unit, "content")
            or not hasattr(unit, "unit_type")
        ):
            _logger.warning(
                "Unit missing required attributes (declarations, content, or unit_type)"
            )
            return False

        if not unit.declarations:
            return False

        # Parse declarations from content
        content_decls = list(parser.parse_declarations(unit.content))
        if not content_decls:
            return False

        # Check that at least one declared ID is in unit.declarations
        content_decl_ids = {ann.id_value for ann in content_decls}
        if not content_decl_ids.intersection(unit.declarations):
            return False

        # Verify that at least one ID matches the element type
        # e.g., Algorithm -> "Algorithm #", D1 -> data structure, etc.
        for decl_id in content_decl_ids.intersection(unit.declarations):
            category = validator.get_category(decl_id)

            # Match ID category to unit_type
            if category == IdCategory.ALGORITHM and unit.unit_type == UnitType.ALGORITHM:
                return True
            if category == IdCategory.DATA_STRUCTURE and unit.unit_type == UnitType.DATA_STRUCTURE:
                return True
            if category == IdCategory.CLAIM and unit.unit_type == UnitType.CLAIM:
                return True
            if category == IdCategory.INVARIANT and unit.unit_type == UnitType.INVARIANT:
                return True
            if category == IdCategory.GOAL and unit.unit_type == UnitType.GOAL:
                return True
            # GOAL units can be represented as I# (canonical format)
            if category == IdCategory.INVARIANT and unit.unit_type == UnitType.GOAL:
                return True
            if category == IdCategory.PATCH_INVARIANT and unit.unit_type == UnitType.INVARIANT:
                return True
            if category == IdCategory.PATCH_CLAIM and unit.unit_type == UnitType.CLAIM:
                return True

            # If unit_type is not set, infer from header text
            if unit.unit_type == UnitType.UNKNOWN:
                lines = unit.content.splitlines()
                if lines:
                    first_line = lines[0].strip()
                    if first_line.startswith("#"):
                        header_text = first_line.lstrip("#").strip().lower()

                        # Match header to ID category
                        if category == IdCategory.ALGORITHM and header_text.startswith("algorithm"):
                            return True
                        if category == IdCategory.DATA_STRUCTURE and re.match(
                            r"^d\d+", header_text
                        ):
                            return True
                        if category == IdCategory.CLAIM and header_text.startswith("claim"):
                            return True
                        if category == IdCategory.INVARIANT and header_text.startswith("invariant"):
                            return True
                        if category == IdCategory.GOAL and header_text.startswith("goal"):
                            return True
                        # GOAL headers can have I# declarations (canonical format)
                        if category == IdCategory.INVARIANT and header_text.startswith("goal"):
                            return True
                        if category == IdCategory.PATCH_INVARIANT and (
                            header_text.startswith("invariant") or header_text.startswith("p")
                        ):
                            return True
                        if category == IdCategory.PATCH_CLAIM and (
                            header_text.startswith("claim") or header_text.startswith("p")
                        ):
                            return True

        return False

    except Exception as e:
        _logger.warning(f"Error checking ID annotation for unit: {e}")
        return False


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
    # Validate input
    if units is None:
        _logger.warning("units parameter is None, treating as empty list")
        return 1.0

    if not isinstance(units, list):
        _logger.error(f"units must be a list, got {type(units).__name__}")
        return 1.0

    if not units:
        return 1.0

    try:
        compliant_count = sum(1 for unit in units if _is_format_compliant(unit))
        return compliant_count / len(units)
    except Exception:
        _logger.exception("Error computing format compliance:")
        return 1.0


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
    # Validate input
    if units is None:
        _logger.warning("units parameter is None, treating as empty list")
        return 1.0

    if not isinstance(units, list):
        _logger.error(f"units must be a list, got {type(units).__name__}")
        return 1.0

    if not units:
        return 1.0

    try:
        structured_units = [unit for unit in units if _is_structured_element(unit)]

        if not structured_units:
            return 1.0

        annotated_count = sum(1 for unit in structured_units if _has_id_annotation(unit))
        return annotated_count / len(structured_units)
    except Exception:
        _logger.exception("Error computing annotation coverage:")
        return 1.0


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
    # Validate input
    if units is None:
        _logger.warning("units parameter is None, treating as empty list")
        return 1.0

    if not isinstance(units, list):
        _logger.error(f"units must be a list, got {type(units).__name__}")
        return 1.0

    if not units:
        return 1.0

    try:
        unique_ids = _extract_unique_ids(units)

        if not unique_ids:
            return 1.0

        canonical_count = sum(1 for id_value in unique_ids if _is_canonical_format(id_value))
        return canonical_count / len(unique_ids)
    except Exception:
        _logger.exception("Error computing ID normalization:")
        return 1.0


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
    # Validate input
    if units is None:
        _logger.warning("units parameter is None, treating as empty list")
        units = []

    if not isinstance(units, list):
        _logger.error(f"units must be a list, got {type(units).__name__}")
        raise TypeError(f"units must be a list, got {type(units).__name__}")

    try:
        format_compliance = compute_format_compliance(units)
        annotation_coverage = compute_annotation_coverage(units)
        id_normalization = compute_id_normalization(units)

        return ComplianceMetrics(
            format_compliance=format_compliance,
            annotation_coverage=annotation_coverage,
            id_normalization=id_normalization,
            gate_threshold=gate_threshold,
        )
    except Exception:
        _logger.exception("Error computing compliance metrics:")
        # Return default metrics on error
        return ComplianceMetrics(
            format_compliance=1.0,
            annotation_coverage=1.0,
            id_normalization=1.0,
            gate_threshold=gate_threshold,
        )
