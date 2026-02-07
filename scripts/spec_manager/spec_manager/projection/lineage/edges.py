"""Projection lineage edge data structures.

Defines the core data model for tracking how algorithmic atoms
(pin-functions) map to architectural locations through transformations.

Transformation types are drawn from the algorithmic-projection-patch
design document (Section 11) and ALGORITHM.md Phase 5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from spec_manager.schemas.pin_functions import ProjectionType


@dataclass
class ProjectionLineageEdge:
    """An edge mapping an algorithmic atom to an architectural location.

    Records lineage transformations with fine-grained ``ProjectionType``.

    Not to be confused with:
    - ``schemas.pin_functions.ImportEdge``: a pin-function-to-architecture
      mapping edge (PFUNC -> arch location with coarse projection type).
    - ``projection.lineage.import_graph.ImportEdge``: a raw Python AST
      import relationship (which file imports which name).

    Attributes:
        from_unit: Algorithmic atom ID (pin-function name or atom ID).
        to_unit: Architectural location (file:class.method or module path).
        transformation: How the atom was projected into architecture.
        confidence: 1.0 for mechanical (direct import), <1.0 for inferred.
        timestamp: When this edge was recorded.
        details: Additional metadata (e.g., wrapper function name, event topic).
        pin_id: Optional associated pin ID from projection artifacts.
    """

    from_unit: str
    to_unit: str
    transformation: ProjectionType
    confidence: float = 1.0
    timestamp: datetime = field(default_factory=datetime.now)
    details: dict[str, Any] = field(default_factory=dict)
    pin_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "from_unit": self.from_unit,
            "to_unit": self.to_unit,
            "transformation": self.transformation.value,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
            "pin_id": self.pin_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectionLineageEdge:
        """Deserialize from dictionary."""
        return cls(
            from_unit=data["from_unit"],
            to_unit=data["to_unit"],
            transformation=ProjectionType(data["transformation"]),
            confidence=data.get("confidence", 1.0),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            details=data.get("details", {}),
            pin_id=data.get("pin_id"),
        )


__all__ = [
    "ProjectionLineageEdge",
    "ProjectionType",
]
