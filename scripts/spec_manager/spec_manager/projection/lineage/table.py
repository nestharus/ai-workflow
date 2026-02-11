"""Projection lineage table with query support.

Provides a queryable collection of ProjectionLineageEdge entries
with forward trace (atom -> arch locations), backward trace
(arch location -> atoms), and filtering by transformation type
and confidence threshold.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from spec_manager.projection.lineage.edges import ProjectionLineageEdge
from spec_manager.schemas.pin_functions import ProjectionType


class ProjectionLineageTable:
    """Collection of projection lineage edges with query support.

    Provides forward trace (atom -> arch locations), backward trace
    (arch location -> atoms), and filtering by transformation type
    and confidence threshold.
    """

    def __init__(self) -> None:
        self.edges: list[ProjectionLineageEdge] = []
        self._by_from: dict[str, list[ProjectionLineageEdge]] = defaultdict(list)
        self._by_to: dict[str, list[ProjectionLineageEdge]] = defaultdict(list)
        self._by_transformation: dict[ProjectionType, list[ProjectionLineageEdge]] = defaultdict(
            list
        )

    # --- Mutation ---

    def add_edge(
        self,
        from_unit: str,
        to_unit: str,
        transformation: ProjectionType,
        confidence: float = 1.0,
        details: dict[str, Any] | None = None,
        pin_id: str | None = None,
    ) -> ProjectionLineageEdge:
        """Add a new edge to the table and update all indexes.

        Args:
            from_unit: Algorithmic atom ID.
            to_unit: Architectural location.
            transformation: How the atom was projected.
            confidence: Confidence score (0.0-1.0).
            details: Additional metadata.
            pin_id: Optional pin ID.

        Returns:
            The created ProjectionLineageEdge.
        """
        edge = ProjectionLineageEdge(
            from_unit=from_unit,
            to_unit=to_unit,
            transformation=transformation,
            confidence=confidence,
            details=details or {},
            pin_id=pin_id,
        )
        self.edges.append(edge)
        self._by_from[from_unit].append(edge)
        self._by_to[to_unit].append(edge)
        self._by_transformation[transformation].append(edge)
        return edge

    def remove_edges_for(self, unit_id: str) -> int:
        """Remove all edges involving a unit (as either from or to).

        Args:
            unit_id: The unit ID to remove edges for.

        Returns:
            Number of edges removed.
        """
        to_remove = [e for e in self.edges if e.from_unit == unit_id or e.to_unit == unit_id]
        removed_count = len(to_remove)

        for edge in to_remove:
            self.edges.remove(edge)
            # Clean up from-index
            if edge in self._by_from.get(edge.from_unit, []):
                self._by_from[edge.from_unit].remove(edge)
            # Clean up to-index
            if edge in self._by_to.get(edge.to_unit, []):
                self._by_to[edge.to_unit].remove(edge)
            # Clean up transformation index
            if edge in self._by_transformation.get(edge.transformation, []):
                self._by_transformation[edge.transformation].remove(edge)

        return removed_count

    # --- Forward trace: atom -> arch locations ---

    def trace_forward(
        self,
        from_unit: str,
        min_confidence: float = 0.0,
    ) -> list[ProjectionLineageEdge]:
        """Trace forward from an atom to all architectural locations.

        Args:
            from_unit: Atom ID to trace from.
            min_confidence: Minimum confidence threshold.

        Returns:
            List of edges originating from the atom.
        """
        edges = self._by_from.get(from_unit, [])
        if min_confidence > 0.0:
            return [e for e in edges if e.confidence >= min_confidence]
        return list(edges)

    # --- Backward trace: arch location -> atoms ---

    def trace_backward(
        self,
        to_unit: str,
        min_confidence: float = 0.0,
    ) -> list[ProjectionLineageEdge]:
        """Trace backward from an architectural location to source atoms.

        Args:
            to_unit: Architectural location to trace back from.
            min_confidence: Minimum confidence threshold.

        Returns:
            List of edges targeting the location.
        """
        edges = self._by_to.get(to_unit, [])
        if min_confidence > 0.0:
            return [e for e in edges if e.confidence >= min_confidence]
        return list(edges)

    # --- Filter by transformation ---

    def edges_by_transformation(
        self,
        transformation: ProjectionType,
    ) -> list[ProjectionLineageEdge]:
        """Get all edges with a specific transformation type.

        Args:
            transformation: The transformation type to filter by.

        Returns:
            List of edges with the given transformation.
        """
        return list(self._by_transformation.get(transformation, []))

    # --- Find orphans ---

    def find_orphan_atoms(self, known_atoms: set[str]) -> set[str]:
        """Find atoms that are known but have no forward edges.

        Args:
            known_atoms: Set of known atom IDs.

        Returns:
            Set of atom IDs with no forward edges in the table.
        """
        atoms_with_edges = {e.from_unit for e in self.edges if e.from_unit}
        return known_atoms - atoms_with_edges

    def find_orphan_arch_locations(self, known_locations: set[str]) -> set[str]:
        """Find architectural locations with no backward edges.

        Args:
            known_locations: Set of known architectural location IDs.

        Returns:
            Set of location IDs with no backward edges in the table.
        """
        locations_with_edges = {e.to_unit for e in self.edges}
        return known_locations - locations_with_edges

    # --- Find introductions (no source atom) ---

    def find_introductions(self) -> list[ProjectionLineageEdge]:
        """Find edges representing architectural introductions (no source atom).

        Returns:
            List of edges with INTRODUCTION transformation type.
        """
        return self.edges_by_transformation(ProjectionType.INTRODUCTION)

    # --- Serialization ---

    def to_dict(self) -> list[dict[str, Any]]:
        """Serialize to a list of edge dictionaries."""
        return [e.to_dict() for e in self.edges]

    @classmethod
    def from_dict(cls, data: list[dict[str, Any]]) -> ProjectionLineageTable:
        """Deserialize from a list of edge dictionaries.

        Args:
            data: List of serialized edge dictionaries.

        Returns:
            Reconstructed ProjectionLineageTable with indexes.
        """
        table = cls()
        for edge_data in data:
            edge = ProjectionLineageEdge.from_dict(edge_data)
            table.edges.append(edge)
            table._by_from[edge.from_unit].append(edge)
            table._by_to[edge.to_unit].append(edge)
            table._by_transformation[edge.transformation].append(edge)
        return table


__all__ = [
    "ProjectionLineageTable",
]
