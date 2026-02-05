"""Entity co-occurrence graph builder (ALG-DISC-0001).

This module builds a weighted graph of entity co-occurrences from EntityTags,
enabling library discovery based on entity relationships.

Design References:
- ALG-DISC-0001: Build co-occurrence graph from entity tags
- DS-DISC-0001: WeightedGraph for entity relationships
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spec_manager.schemas.entities import EntityTag


@dataclass
class WindowPolicy:
    """Policy for co-occurrence window calculation.

    Attributes:
        same_atom_weight: Weight for entities in the same atom (highest)
        adjacent_atom_weight: Weight for entities in adjacent atoms
        same_section_weight: Weight for entities in the same section
        window_size: Number of atoms to consider as a window
    """

    same_atom_weight: float = 1.0
    adjacent_atom_weight: float = 0.5
    same_section_weight: float = 0.25
    window_size: int = 5


@dataclass
class WeightedEdge:
    """A weighted edge between two entities.

    Attributes:
        entity_a: First entity ID
        entity_b: Second entity ID
        weight: Combined co-occurrence weight
        atom_ids: Atom IDs where co-occurrence was observed
    """

    entity_a: str
    entity_b: str
    weight: float
    atom_ids: list[str] = field(default_factory=list)

    def normalized_key(self) -> tuple[str, str]:
        """Return a normalized key with entities in sorted order."""
        return tuple(sorted([self.entity_a, self.entity_b]))  # type: ignore[return-value]


@dataclass
class WeightedGraph:
    """A weighted graph of entity co-occurrences (DS-DISC-0001).

    Attributes:
        edges: Dictionary mapping entity pair to WeightedEdge
        entity_weights: Total weight per entity (sum of incident edges)
    """

    edges: dict[tuple[str, str], WeightedEdge] = field(default_factory=dict)
    entity_weights: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    def add_edge(self, entity_a: str, entity_b: str, weight: float, atom_id: str) -> None:
        """Add or update a weighted edge between entities.

        Args:
            entity_a: First entity ID
            entity_b: Second entity ID
            weight: Weight to add
            atom_id: Atom ID where co-occurrence was observed
        """
        if entity_a == entity_b:
            return  # No self-loops

        key = tuple(sorted([entity_a, entity_b]))
        if key not in self.edges:
            self.edges[key] = WeightedEdge(
                entity_a=key[0],
                entity_b=key[1],
                weight=0.0,
                atom_ids=[],
            )

        self.edges[key].weight += weight
        if atom_id not in self.edges[key].atom_ids:
            self.edges[key].atom_ids.append(atom_id)

        # Update entity weights
        self.entity_weights[entity_a] += weight
        self.entity_weights[entity_b] += weight

    def get_neighbors(self, entity_id: str) -> list[tuple[str, float]]:
        """Get neighbors of an entity with their edge weights.

        Args:
            entity_id: The entity to find neighbors for

        Returns:
            List of (neighbor_entity_id, weight) tuples
        """
        neighbors: list[tuple[str, float]] = []
        for key, edge in self.edges.items():
            if key[0] == entity_id:
                neighbors.append((key[1], edge.weight))
            elif key[1] == entity_id:
                neighbors.append((key[0], edge.weight))
        return sorted(neighbors, key=lambda x: x[1], reverse=True)

    def get_edge_weight(self, entity_a: str, entity_b: str) -> float:
        """Get the weight of an edge between two entities.

        Args:
            entity_a: First entity ID
            entity_b: Second entity ID

        Returns:
            Edge weight, or 0.0 if no edge exists
        """
        key = tuple(sorted([entity_a, entity_b]))
        edge = self.edges.get(key)
        return edge.weight if edge else 0.0

    def get_top_entities(self, n: int = 10) -> list[tuple[str, float]]:
        """Get top N entities by total incident weight.

        Args:
            n: Number of top entities to return

        Returns:
            List of (entity_id, total_weight) tuples
        """
        sorted_entities = sorted(
            self.entity_weights.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return sorted_entities[:n]


class CooccurrenceGraph:
    """Entity co-occurrence graph builder (ALG-DISC-0001).

    Builds a weighted graph from entity tags, where edge weights reflect
    co-occurrence frequency within atom windows.
    """

    def __init__(self, policy: WindowPolicy | None = None):
        """Initialize the co-occurrence graph builder.

        Args:
            policy: Window policy for co-occurrence calculation
        """
        self.policy = policy or WindowPolicy()

    def build_from_entity_tags(
        self,
        entity_tags: list["EntityTag"],
    ) -> WeightedGraph:
        """Build co-occurrence graph from entity tags (ALG-DISC-0001).

        Creates a weighted graph where entities that appear in the same
        or adjacent atoms are connected with higher weights.

        Args:
            entity_tags: List of EntityTag objects linking entities to atoms

        Returns:
            WeightedGraph with entity co-occurrences
        """
        graph = WeightedGraph()

        # Build atom -> entity mapping
        atom_to_entities: dict[str, list[str]] = defaultdict(list)
        for tag in entity_tags:
            for atom_id in tag.atom_ids:
                atom_to_entities[atom_id].append(tag.entity_id)

        # Sort atoms for window calculation
        sorted_atoms = sorted(atom_to_entities.keys())

        # Process each atom's entities for same-atom co-occurrence
        for atom_id, entity_ids in atom_to_entities.items():
            unique_entities = list(set(entity_ids))
            for i, entity_a in enumerate(unique_entities):
                for entity_b in unique_entities[i + 1 :]:
                    graph.add_edge(
                        entity_a,
                        entity_b,
                        self.policy.same_atom_weight,
                        atom_id,
                    )

        # Process adjacent atoms for window-based co-occurrence
        for i, atom_a in enumerate(sorted_atoms):
            entities_a = set(atom_to_entities[atom_a])

            # Look at atoms within window
            for j in range(i + 1, min(i + self.policy.window_size, len(sorted_atoms))):
                atom_b = sorted_atoms[j]
                entities_b = set(atom_to_entities[atom_b])

                # Weight decreases with distance
                distance = j - i
                weight = self.policy.adjacent_atom_weight / distance

                for entity_a in entities_a:
                    for entity_b in entities_b:
                        if entity_a != entity_b:
                            graph.add_edge(entity_a, entity_b, weight, atom_b)

        return graph

    def find_clusters(
        self,
        graph: WeightedGraph,
        min_cluster_size: int = 2,
        weight_threshold: float = 0.5,
    ) -> list[set[str]]:
        """Find clusters of strongly connected entities.

        Uses a simple greedy approach to find clusters based on edge weights.

        Args:
            graph: The weighted graph to cluster
            min_cluster_size: Minimum entities per cluster
            weight_threshold: Minimum edge weight to consider

        Returns:
            List of entity ID sets representing clusters
        """
        # Build adjacency list with threshold filtering
        adjacency: dict[str, set[str]] = defaultdict(set)
        for key, edge in graph.edges.items():
            if edge.weight >= weight_threshold:
                adjacency[key[0]].add(key[1])
                adjacency[key[1]].add(key[0])

        # Find connected components via BFS
        visited: set[str] = set()
        clusters: list[set[str]] = []

        for entity_id in adjacency:
            if entity_id in visited:
                continue

            # BFS to find component
            component: set[str] = set()
            queue = [entity_id]

            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue

                visited.add(current)
                component.add(current)

                for neighbor in adjacency.get(current, set()):
                    if neighbor not in visited:
                        queue.append(neighbor)

            if len(component) >= min_cluster_size:
                clusters.append(component)

        return clusters
