"""Lightweight weighted graph with signal-typed edges for adjacency analysis.

No external graph library is needed. The graph operations (union, connected
components, edge weighting) use straightforward adjacency-list algorithms.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SignalType(Enum):
    """Types of adjacency signals between nodes."""

    CALL = "call"
    REFERENCE = "reference"
    STORE_TOUCH = "store_touch"
    CO_OCCURRENCE = "co_occurrence"
    EVENT = "event"


@dataclass(frozen=True)
class EdgeSignal:
    """A single signal contributing to an edge."""

    signal_type: SignalType
    weight: float
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_type": self.signal_type.value,
            "weight": self.weight,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EdgeSignal:
        return cls(
            signal_type=SignalType(data["signal_type"]),
            weight=data["weight"],
            details=data.get("details", {}),
        )


@dataclass
class Edge:
    """A weighted edge between two nodes, potentially with multiple signals."""

    source: str
    target: str
    signals: list[EdgeSignal] = field(default_factory=list)

    @property
    def total_weight(self) -> float:
        return sum(s.weight for s in self.signals)

    def add_signal(self, signal: EdgeSignal) -> None:
        self.signals.append(signal)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "signals": [s.to_dict() for s in self.signals],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Edge:
        return cls(
            source=data["source"],
            target=data["target"],
            signals=[EdgeSignal.from_dict(s) for s in data.get("signals", [])],
        )


@dataclass
class NodeInfo:
    """Metadata about a graph node."""

    node_id: str
    node_type: str  # "algorithm", "function", "handler", "store", etc.
    file_path: str | None = None
    line_number: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "node_id": self.node_id,
            "node_type": self.node_type,
        }
        if self.file_path is not None:
            result["file_path"] = self.file_path
        if self.line_number is not None:
            result["line_number"] = self.line_number
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NodeInfo:
        return cls(
            node_id=data["node_id"],
            node_type=data["node_type"],
            file_path=data.get("file_path"),
            line_number=data.get("line_number"),
            metadata=data.get("metadata", {}),
        )


def _merge_unique_values(*values: Any) -> list[Any]:
    merged: list[Any] = []
    for value in values:
        if value is None:
            continue
        entries = value if isinstance(value, list) else [value]
        for entry in entries:
            if entry not in merged:
                merged.append(entry)
    return merged


def _merge_node_info(existing: NodeInfo, incoming: NodeInfo) -> NodeInfo:
    merged_metadata: dict[str, Any] = dict(existing.metadata)

    for key, incoming_value in incoming.metadata.items():
        if key not in merged_metadata:
            merged_metadata[key] = incoming_value
            continue
        existing_value = merged_metadata[key]
        if existing_value == incoming_value:
            continue
        merged_metadata[key] = _merge_unique_values(existing_value, incoming_value)

    merged_node_type = existing.node_type
    if existing.node_type == "unknown" and incoming.node_type != "unknown":
        merged_node_type = incoming.node_type
    elif incoming.node_type != "unknown" and incoming.node_type != existing.node_type:
        merged_metadata["node_type_conflicts"] = _merge_unique_values(
            merged_metadata.get("node_type_conflicts"),
            existing.node_type,
            incoming.node_type,
        )

    merged_file_path = existing.file_path or incoming.file_path
    if (
        existing.file_path is not None
        and incoming.file_path is not None
        and existing.file_path != incoming.file_path
    ):
        merged_metadata["file_path_conflicts"] = _merge_unique_values(
            merged_metadata.get("file_path_conflicts"),
            existing.file_path,
            incoming.file_path,
        )

    merged_line_number = (
        existing.line_number if existing.line_number is not None else incoming.line_number
    )
    if (
        existing.line_number is not None
        and incoming.line_number is not None
        and existing.line_number != incoming.line_number
    ):
        merged_metadata["line_number_conflicts"] = _merge_unique_values(
            merged_metadata.get("line_number_conflicts"),
            existing.line_number,
            incoming.line_number,
        )

    return NodeInfo(
        node_id=existing.node_id,
        node_type=merged_node_type,
        file_path=merged_file_path,
        line_number=merged_line_number,
        metadata=merged_metadata,
    )


class AdjacencyGraph:
    """Lightweight weighted directed graph with signal-typed edges.

    Nodes are string IDs (algorithm names, function names, etc.).
    Edges carry one or more EdgeSignal instances.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, NodeInfo] = {}
        self._adj: dict[str, dict[str, Edge]] = {}  # source -> {target -> Edge}

    def add_node(self, node_id: str, info: NodeInfo | None = None) -> None:
        """Add a node to the graph. If it already exists, update info if provided."""
        if info is not None and info.node_id != node_id:
            raise ValueError(
                f"Node ID mismatch: add_node called with node_id='{node_id}' "
                f"but NodeInfo.node_id='{info.node_id}'.",
            )

        if node_id not in self._nodes:
            self._nodes[node_id] = info or NodeInfo(node_id=node_id, node_type="unknown")
            self._adj.setdefault(node_id, {})
        elif info is not None:
            self._nodes[node_id] = _merge_node_info(self._nodes[node_id], info)

    def add_edge(self, source: str, target: str, signal: EdgeSignal) -> None:
        """Add or augment an edge. If edge exists, appends signal."""
        # Ensure both nodes exist
        self.add_node(source)
        self.add_node(target)

        if target in self._adj.get(source, {}):
            self._adj[source][target].add_signal(signal)
        else:
            self._adj.setdefault(source, {})[target] = Edge(
                source=source, target=target, signals=[signal]
            )

    def get_edge(self, source: str, target: str) -> Edge | None:
        """Get the edge from source to target, or None if not found."""
        return self._adj.get(source, {}).get(target)

    def neighbors(self, node_id: str) -> list[tuple[str, Edge]]:
        """Outgoing neighbors with their edges."""
        return list(self._adj.get(node_id, {}).items())

    def all_neighbors(self, node_id: str) -> list[tuple[str, Edge]]:
        """Both incoming and outgoing neighbors (undirected view)."""
        result: dict[str, Edge] = {}
        # Outgoing
        for target, edge in self._adj.get(node_id, {}).items():
            result[target] = edge
        # Incoming
        for source, targets in self._adj.items():
            if node_id in targets and source != node_id and source not in result:
                result[source] = targets[node_id]
        return list(result.items())

    def nodes(self) -> list[str]:
        """Return all node IDs."""
        return list(self._nodes.keys())

    def node_info(self, node_id: str) -> NodeInfo | None:
        """Get the NodeInfo for a node, or None if not found."""
        return self._nodes.get(node_id)

    def edges(self) -> list[Edge]:
        """Return all edges in the graph."""
        all_edges: list[Edge] = []
        for targets in self._adj.values():
            all_edges.extend(targets.values())
        return all_edges

    def connected_components(self) -> list[set[str]]:
        """Undirected connected components via BFS."""
        visited: set[str] = set()
        components: list[set[str]] = []

        for node in self._nodes:
            if node in visited:
                continue
            component: set[str] = set()
            queue: deque[str] = deque([node])
            while queue:
                current = queue.popleft()
                if current in visited:
                    continue
                visited.add(current)
                component.add(current)
                # Traverse outgoing edges
                for neighbor, _ in self.neighbors(current):
                    if neighbor not in visited:
                        queue.append(neighbor)
                # Traverse incoming edges (undirected view)
                for source, targets in self._adj.items():
                    if current in targets and source not in visited:
                        queue.append(source)
            if component:
                components.append(component)

        return components

    def subgraph(self, node_ids: set[str]) -> AdjacencyGraph:
        """Extract induced subgraph containing only the specified nodes."""
        result = AdjacencyGraph()
        for node_id in node_ids:
            if node_id in self._nodes:
                result.add_node(node_id, self._nodes[node_id])
        for source in node_ids:
            for target, edge in self._adj.get(source, {}).items():
                if target in node_ids:
                    for signal in edge.signals:
                        result.add_edge(source, target, signal)
        return result

    def union(self, other: AdjacencyGraph) -> AdjacencyGraph:
        """Merge two graphs. Overlapping edges get signals combined."""
        result = AdjacencyGraph()
        # Add all nodes from self
        for node_id, info in self._nodes.items():
            result.add_node(node_id, info)
        # Add all nodes from other
        for node_id, info in other._nodes.items():
            result.add_node(node_id, info)
        # Add all edges from self
        for edge in self.edges():
            for signal in edge.signals:
                result.add_edge(edge.source, edge.target, signal)
        # Add all edges from other
        for edge in other.edges():
            for signal in edge.signals:
                result.add_edge(edge.source, edge.target, signal)
        return result

    def filter_by_signal_type(self, signal_types: set[SignalType]) -> AdjacencyGraph:
        """Return subgraph containing only edges with specified signal types."""
        result = AdjacencyGraph()
        # Add all nodes
        for node_id, info in self._nodes.items():
            result.add_node(node_id, info)
        # Add only edges with matching signal types
        for edge in self.edges():
            matching_signals = [s for s in edge.signals if s.signal_type in signal_types]
            for signal in matching_signals:
                result.add_edge(edge.source, edge.target, signal)
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize the graph to a dictionary."""
        return {
            "nodes": {nid: info.to_dict() for nid, info in self._nodes.items()},
            "edges": [edge.to_dict() for edge in self.edges()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdjacencyGraph:
        """Deserialize a graph from a dictionary."""
        graph = cls()
        for node_id, info_data in data.get("nodes", {}).items():
            graph.add_node(node_id, NodeInfo.from_dict(info_data))
        for edge_data in data.get("edges", []):
            edge = Edge.from_dict(edge_data)
            for signal in edge.signals:
                graph.add_edge(edge.source, edge.target, signal)
        return graph
