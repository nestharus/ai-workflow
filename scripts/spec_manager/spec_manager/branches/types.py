"""Core enums and data structures for the branch organization system.

This module defines the fundamental types used across all branch subsystems:
- Branch kinds (algorithmic, architectural, analysis)
- Atom classifications (algorithm, store, shape)
- Pin-projection descriptors and projection types
- Vertical slice definitions for component navigation
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from spec_manager.schemas.pin_functions import ProjectionType


class BranchKind(Enum):
    """Types of branches in the system."""

    ALGORITHMIC = "algorithmic"
    ARCHITECTURAL = "architectural"
    ANALYSIS = "analysis"


class AtomKind(Enum):
    """Classification of atom functions."""

    ALGORITHM = "algorithm"  # Business logic step
    STORE = "store"  # Persistent state definition
    SHAPE = "shape"  # Pure logic, no side effects


class StoreType(Enum):
    """Store persistence classification (from design doc Section 3)."""

    PERSISTED = "persisted"  # Type A: survives restart
    LONG_LIVED_EPHEMERAL = "ephemeral_long"  # Type B: in-memory across steps
    PURE_EPHEMERAL = "ephemeral_pure"  # Type C: local/temporary


class SliceOrientation(Enum):
    """Navigation direction within the branch structure."""

    HORIZONTAL = "horizontal"  # Layers within a vertical (algorithms, stores, shapes, events, ...)
    VERTICAL = "vertical"  # Components with state/lifecycle (entities)


@dataclass
class AtomDescriptor:
    """Metadata for a registered atom function.

    Attributes:
        atom_id: Unique identifier (function name or qualified name).
        kind: Whether this is an algorithm, store, or shape.
        file_path: Relative path within the atoms/ directory.
        function_name: The Python function name.
        signature: Type signature string (for contract checking).
        content_hash: SHA-256 of the function source.
        introduced_by: Which plan/patch added this atom.
        modified_by: Chain of modifications.
        store_type: If kind is STORE, the persistence classification.
        vertical_slice: Which vertical slice this atom belongs to.
    """

    atom_id: str
    kind: AtomKind
    file_path: str
    function_name: str
    signature: str
    content_hash: str
    introduced_by: str
    modified_by: list[str] = field(default_factory=list)
    store_type: StoreType | None = None
    vertical_slice: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "atom_id": self.atom_id,
            "kind": self.kind.value,
            "file_path": self.file_path,
            "function_name": self.function_name,
            "signature": self.signature,
            "content_hash": self.content_hash,
            "introduced_by": self.introduced_by,
            "modified_by": self.modified_by,
            "store_type": self.store_type.value if self.store_type else None,
            "vertical_slice": self.vertical_slice,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AtomDescriptor:
        """Deserialize from dictionary."""
        return cls(
            atom_id=data["atom_id"],
            kind=AtomKind(data["kind"]),
            file_path=data["file_path"],
            function_name=data["function_name"],
            signature=data["signature"],
            content_hash=data["content_hash"],
            introduced_by=data["introduced_by"],
            modified_by=data.get("modified_by", []),
            store_type=StoreType(data["store_type"]) if data.get("store_type") else None,
            vertical_slice=data.get("vertical_slice"),
        )


@dataclass
class PinProjection:
    """A pin mapping an atom to an architectural location.

    This is an executable bridge (design doc Section 5). The pin is the
    atom function itself. This descriptor records WHERE the atom is used
    in the architectural branch and HOW it was projected.

    Not to be confused with ``schemas.pin_functions.PinFunction``, which
    represents a code-level extracted pin-function (PFUNC-####). This
    class represents a projection mapping (PIN-####) from an atom to an
    architectural location.

    Attributes:
        pin_id: Unique pin identifier (PIN-####).
        atom_id: The atom being pinned.
        architectural_location: File:class.method in the architectural branch.
        projection_type: How the atom was projected.
        confidence: 1.0 for mechanical (import), <1.0 for inferred.
        wrapper_hash: Hash of wrapping code (for drift detection on non-pass-through).
    """

    pin_id: str
    atom_id: str
    architectural_location: str
    projection_type: ProjectionType
    confidence: float = 1.0
    wrapper_hash: str | None = None

    def __post_init__(self) -> None:
        """Validate pin_id format and confidence bounds."""
        if not re.fullmatch(r"PIN-\d{4}", self.pin_id):
            raise ValueError("pin_id must match PIN-#### format")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "pin_id": self.pin_id,
            "atom_id": self.atom_id,
            "architectural_location": self.architectural_location,
            "projection_type": self.projection_type.value,
            "confidence": self.confidence,
            "wrapper_hash": self.wrapper_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PinProjection:
        """Deserialize from dictionary."""
        return cls(
            pin_id=data["pin_id"],
            atom_id=data["atom_id"],
            architectural_location=data["architectural_location"],
            projection_type=ProjectionType(data["projection_type"]),
            confidence=data.get("confidence", 1.0),
            wrapper_hash=data.get("wrapper_hash"),
        )


@dataclass
class VerticalSlice:
    """A component vertical slice in the recursive structure.

    Attributes:
        slice_id: Unique identifier for this slice.
        name: Human-readable name.
        parent_slice_id: Parent in the recursive hierarchy (None for root).
        atom_ids: Atoms belonging to this vertical.
        store_ids: Stores owned by this vertical (store monogamy).
        children: Child vertical slices.
    """

    slice_id: str
    name: str
    parent_slice_id: str | None = None
    atom_ids: list[str] = field(default_factory=list)
    store_ids: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "slice_id": self.slice_id,
            "name": self.name,
            "parent_slice_id": self.parent_slice_id,
            "atom_ids": self.atom_ids,
            "store_ids": self.store_ids,
            "children": self.children,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VerticalSlice:
        """Deserialize from dictionary."""
        return cls(
            slice_id=data["slice_id"],
            name=data["name"],
            parent_slice_id=data.get("parent_slice_id"),
            atom_ids=data.get("atom_ids", []),
            store_ids=data.get("store_ids", []),
            children=data.get("children", []),
        )
