"""Schemas for evidence graph capturing relationship topology (DS-EVID-0004/5/6).

The evidence graph captures the relationship topology between atoms, evidence ranges,
and sections, enabling traceability across the spec refinement pipeline.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class NodeType(str, Enum):
    """Types of nodes in the evidence graph."""

    ATOM = "ATOM"
    EVIDENCE_RANGE = "EVIDENCE_RANGE"
    SECTION = "SECTION"
    ENTITY = "ENTITY"
    DERIVED_ELEMENT = "DERIVED_ELEMENT"
    LIBRARY = "LIBRARY"
    TASK = "TASK"
    GAP = "GAP"


class EdgeType(str, Enum):
    """Types of edges in the evidence graph."""

    SUPPORTS = "SUPPORTS"  # atom -> range, range -> section
    MENTIONS = "MENTIONS"
    DERIVES = "DERIVES"
    DEPENDS_ON = "DEPENDS_ON"
    RELATES_TO = "RELATES_TO"
    PATCHES = "PATCHES"


class EvidenceGraphNode(BaseModel):
    """A node in the evidence graph (DS-EVID-0005).

    Attributes:
        node_id: Unique identifier for the node
        node_type: Type of the node (ATOM, EVIDENCE_RANGE, SECTION, etc.)
        payload_ref: Reference to full object (typically same as node_id)
        metadata: Additional metadata for the node
    """

    node_id: str
    node_type: NodeType
    payload_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceGraphEdge(BaseModel):
    """An edge in the evidence graph (DS-EVID-0006).

    Attributes:
        edge_id: Unique identifier for the edge
        from_node_id: Source node ID
        to_node_id: Target node ID
        edge_type: Type of relationship
        evidence_atom_ids: Atom IDs providing evidence for this edge
        confidence: Confidence score (0.0-1.0)
        method: Method used to establish this edge
    """

    edge_id: str
    from_node_id: str
    to_node_id: str
    edge_type: EdgeType
    evidence_atom_ids: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    method: str | None = None


class EvidenceGraph(BaseModel):
    """The evidence graph (DS-EVID-0004).

    Captures the relationship topology between atoms, evidence ranges,
    sections, and other derived elements.

    Attributes:
        schema_version: Schema version string
        nodes: Dictionary of node_id -> EvidenceGraphNode
        edges: List of edges
    """

    schema_version: str = "1.0"
    nodes: dict[str, EvidenceGraphNode] = Field(default_factory=dict)
    edges: list[EvidenceGraphEdge] = Field(default_factory=list)

    # Internal adjacency indexes (not serialized by default)
    _adjacency_out: dict[str, list[EvidenceGraphEdge]] = {}
    _adjacency_in: dict[str, list[EvidenceGraphEdge]] = {}

    def add_node(self, node: EvidenceGraphNode) -> None:
        """Add a node to the graph.

        Args:
            node: The node to add
        """
        self.nodes[node.node_id] = node

    def add_edge(self, edge: EvidenceGraphEdge) -> None:
        """Add an edge to the graph.

        Args:
            edge: The edge to add
        """
        self.edges.append(edge)

    def reindex_adjacency(self) -> None:
        """Rebuild adjacency indexes for efficient queries."""
        self._adjacency_out = {}
        self._adjacency_in = {}

        for edge in self.edges:
            if edge.from_node_id not in self._adjacency_out:
                self._adjacency_out[edge.from_node_id] = []
            self._adjacency_out[edge.from_node_id].append(edge)

            if edge.to_node_id not in self._adjacency_in:
                self._adjacency_in[edge.to_node_id] = []
            self._adjacency_in[edge.to_node_id].append(edge)

    def get_outgoing_edges(self, node_id: str) -> list[EvidenceGraphEdge]:
        """Get all outgoing edges from a node.

        Args:
            node_id: The source node ID

        Returns:
            List of outgoing edges
        """
        return self._adjacency_out.get(node_id, [])

    def get_incoming_edges(self, node_id: str) -> list[EvidenceGraphEdge]:
        """Get all incoming edges to a node.

        Args:
            node_id: The target node ID

        Returns:
            List of incoming edges
        """
        return self._adjacency_in.get(node_id, [])

    def get_nodes_by_type(self, node_type: NodeType) -> list[EvidenceGraphNode]:
        """Get all nodes of a specific type.

        Args:
            node_type: The type of nodes to retrieve

        Returns:
            List of nodes matching the type
        """
        return [node for node in self.nodes.values() if node.node_type == node_type]
