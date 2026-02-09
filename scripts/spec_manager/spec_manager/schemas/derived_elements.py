"""DerivedElement schema compliant with DS-SPEC-0001.

This module defines the DerivedElement and RelationEdge schemas used in
spec building to represent requirements, flows, invariants, decisions,
algorithms, data structures, notes, and gaps.

Design References:
- DS-SPEC-0001: DerivedElement schema
- DS-SPEC-0004: RelationEdge schema
- CON-0005: Evidence citations required
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Element ID patterns for different kinds
# Format: {KIND}-LIB-{lib_seq:04d}-{seq:04d} (or 2-digit seq for FLOW)
# e.g., REQ-LIB-0001-0001, FLOW-LIB-0002-01, ALG-LIB-0001-0001
_ELEMENT_ID_PATTERN = re.compile(
    r"^(?:"
    r"REQ-LIB-\d{4}-\d{4}|"  # Requirements
    r"FLOW-LIB-\d{4}-\d{2}|"  # Flows (2-digit sequence)
    r"INV-LIB-\d{4}-\d{4}|"  # Invariants
    r"DEC-LIB-\d{4}-\d{4}|"  # Decisions
    r"DTL-LIB-\d{4}-\d{4}|"  # Details
    r"CON-LIB-\d{4}-\d{4}|"  # Constraints
    r"ANL-LIB-\d{4}-\d{4}|"  # Analyses
    r"OVW-LIB-\d{4}-\d{4}|"  # Overviews
    r"ALG-LIB-\d{4}-\d{4}|"  # Algorithms
    r"DS-LIB-\d{4}-\d{4}|"  # Data Structures
    r"NOTE-LIB-\d{4}-\d{4}|"  # Notes
    r"GAP-LIB-\d{4}-\d{4}"  # Gaps
    r")$"
)

# Library ID pattern
_LIB_ID_PATTERN = re.compile(r"^LIB-\d{4}$")

# Derived element kinds
DerivedElementKind = Literal[
    "REQ",
    "FLOW",
    "INV",
    "DEC",
    "DTL",
    "CON",
    "ANL",
    "OVW",
    "ALG",
    "DS",
    "NOTE",
    "GAP",
]

# Element status states
ElementStatus = Literal["DRAFT", "ACTIVE", "NON_AUTHORITATIVE", "QUARANTINED", "DEPRECATED"]

# Relation types between elements
RelationType = Literal["DEPENDS_ON", "REFINES", "CONTRADICTS", "OVERLAPS", "IMPLEMENTS"]


class RelationEdge(BaseModel):
    """A relation between two derived elements (DS-SPEC-0004).

    Represents typed relationships between elements such as dependencies,
    refinements, contradictions, and implementations.

    Attributes:
        from_id: Source element ID
        to_id: Target element ID
        relation_type: Type of relationship
        evidence_atom_ids: Atom IDs providing evidence for this relation
        confidence: Confidence score (0.0-1.0)
    """

    from_id: str
    to_id: str
    relation_type: RelationType
    evidence_atom_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("from_id", "to_id")
    @classmethod
    def validate_element_id(cls, value: str) -> str:
        """Validate element ID format."""
        if not _ELEMENT_ID_PATTERN.fullmatch(value):
            raise ValueError(f"Element ID must match pattern {{KIND}}-LIB-####-####, got: {value}")
        return value


class DerivedElement(BaseModel):
    """A derived specification element (DS-SPEC-0001).

    Represents a requirement, flow, invariant, decision, algorithm,
    data structure, note, or gap derived from evidence.

    CON-0005 Compliance: evidence_atom_ids MUST be non-empty to ensure
    every derived element has traceable evidence grounding.

    Attributes:
        elem_id: Unique element identifier ({KIND}-LIB-{lib_seq:04d}-{seq:04d})
        kind: Element type (REQ, FLOW, INV, DEC, ALG, DS, NOTE, GAP)
        lib_id: Library this element belongs to
        title: Short title for the element
        body: Full content/description
        evidence_atom_ids: REQUIRED list of atom IDs providing evidence
        confidence: Confidence score (0.0-1.0)
        status: Element lifecycle status
        derived_from_elem_ids: Parent elements this was derived from
        relations: Relationships to other elements
    """

    elem_id: str
    kind: DerivedElementKind
    lib_id: str
    title: str
    body: str
    evidence_atom_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    status: ElementStatus = "DRAFT"
    derived_from_elem_ids: list[str] = Field(default_factory=list)
    relations: list[RelationEdge] = Field(default_factory=list)

    @field_validator("elem_id")
    @classmethod
    def validate_elem_id(cls, value: str) -> str:
        """Validate element ID format."""
        if not _ELEMENT_ID_PATTERN.fullmatch(value):
            raise ValueError(
                f"elem_id must match pattern {{KIND}}-LIB-####-#### "
                f"(e.g., DTL-LIB-0001-0001), got: {value}"
            )
        return value

    @field_validator("lib_id")
    @classmethod
    def validate_lib_id(cls, value: str) -> str:
        """Validate library ID format."""
        if not _LIB_ID_PATTERN.fullmatch(value):
            raise ValueError(f"lib_id must match LIB-#### format, got: {value}")
        return value

    @model_validator(mode="after")
    def validate_evidence_grounding(self) -> DerivedElement:
        """Validate evidence grounding (CON-0005).

        Every derived element must cite at least one evidence atom to ensure
        traceability back to source material.
        """
        if not self.evidence_atom_ids:
            raise ValueError(
                "DerivedElement must cite at least one evidence atom (CON-0005 compliance)"
            )
        return self

    @model_validator(mode="after")
    def validate_kind_matches_elem_id(self) -> DerivedElement:
        """Validate that kind matches the elem_id prefix."""
        prefix = self.elem_id.split("-")[0]
        if prefix != self.kind:
            raise ValueError(f"elem_id prefix '{prefix}' does not match kind '{self.kind}'")
        return self


def allocate_element_id(
    kind: DerivedElementKind,
    lib_id: str,
    existing_ids: set[str],
) -> str:
    """Allocate a new element ID for the given kind and library.

    Args:
        kind: Element kind (REQ, FLOW, etc.)
        lib_id: Library ID (LIB-####)
        existing_ids: Set of already allocated element IDs

    Returns:
        A new unique element ID in {KIND}-LIB-####-#### format
    """
    if not _LIB_ID_PATTERN.fullmatch(lib_id):
        raise ValueError(f"Invalid lib_id format: {lib_id}")

    # Extract lib sequence from lib_id (e.g., "0001" from "LIB-0001")
    lib_seq = lib_id.split("-")[1]

    # FLOW uses 2-digit sequence, all other kinds use 4-digit
    seq_width = 2 if kind == "FLOW" else 4

    # Find max sequence for this kind+lib combination
    prefix = f"{kind}-LIB-{lib_seq}-"
    max_seq = 0

    for eid in existing_ids:
        if eid.startswith(prefix):
            try:
                seq = int(eid.split("-")[-1])
                max_seq = max(max_seq, seq)
            except ValueError:
                continue

    return f"{kind}-LIB-{lib_seq}-{max_seq + 1:0{seq_width}d}"


def validate_element_references(
    element: DerivedElement,
    valid_elem_ids: set[str],
) -> list[str]:
    """Validate that all element references in derived_from and relations exist.

    Args:
        element: The element to validate
        valid_elem_ids: Set of valid element IDs

    Returns:
        List of validation error messages (empty if valid)
    """
    errors: list[str] = []

    for parent_id in element.derived_from_elem_ids:
        if parent_id not in valid_elem_ids:
            errors.append(f"Element {element.elem_id} references unknown parent: {parent_id}")

    for relation in element.relations:
        if relation.from_id not in valid_elem_ids and relation.from_id != element.elem_id:
            errors.append(
                f"Element {element.elem_id} relation references unknown from_id: {relation.from_id}"
            )
        if relation.to_id not in valid_elem_ids and relation.to_id != element.elem_id:
            errors.append(
                f"Element {element.elem_id} relation references unknown to_id: {relation.to_id}"
            )

    return errors
