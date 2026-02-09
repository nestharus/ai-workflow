"""Co-occurrence graph builder for entity clustering (ALG-DISC-0001).

Builds a weighted co-occurrence graph from entity tags, where edges
represent how frequently two entities appear together in the same
or nearby atoms. Supports cluster detection for library discovery.

Design References:
- ALG-DISC-0001: CooccurrenceGraph
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from spec_manager.schemas.entities import EntityTag


@dataclass
class WeightedEdge:
    """A weighted edge between two entities.

    Attributes:
        entity_a: First entity ID
        entity_b: Second entity ID
        weight: Accumulated co-occurrence weight
        atom_ids: Set of atom IDs where co-occurrence was observed
    """

    entity_a: str
    entity_b: str
    weight: float = 0.0
    atom_ids: set[str] = field(default_factory=set)

    def normalized_key(self) -> tuple[str, str]:
        """Get a normalized (sorted) key for this edge.

        Returns:
            Tuple of (smaller_id, larger_id)
        """
        return tuple(sorted([self.entity_a, self.entity_b]))  # type: ignore[return-value]


class WeightedGraph:
    """Weighted undirected graph for entity co-occurrence.

    Edges are stored with normalized (sorted) keys to ensure
    (A, B) and (B, A) are the same edge.
    """

    def __init__(self) -> None:
        self.edges: dict[tuple[str, str], WeightedEdge] = {}
        self.entity_weights: dict[str, float] = defaultdict(float)

    def add_edge(self, entity_a: str, entity_b: str, weight: float, atom_id: str) -> None:
        """Add or accumulate an edge between two entities.

        Self-loops are silently ignored. Edge keys are normalized
        so that (A, B) and (B, A) map to the same edge.

        Args:
            entity_a: First entity ID
            entity_b: Second entity ID
            weight: Weight to add
            atom_id: Atom ID where co-occurrence was observed
        """
        if entity_a == entity_b:
            return

        key = tuple(sorted([entity_a, entity_b]))
        key_typed: tuple[str, str] = key  # type: ignore[assignment]

        if key_typed in self.edges:
            self.edges[key_typed].weight += weight
            self.edges[key_typed].atom_ids.add(atom_id)
        else:
            self.edges[key_typed] = WeightedEdge(
                entity_a=key_typed[0],
                entity_b=key_typed[1],
                weight=weight,
                atom_ids={atom_id},
            )

        self.entity_weights[entity_a] += weight
        self.entity_weights[entity_b] += weight

    def get_neighbors(self, entity_id: str) -> list[tuple[str, float]]:
        """Get neighbors of an entity sorted by weight descending.

        Args:
            entity_id: The entity to look up neighbors for

        Returns:
            List of (neighbor_id, weight) tuples sorted by weight descending
        """
        neighbors: list[tuple[str, float]] = []
        for key, edge in self.edges.items():
            if entity_id in key:
                other = key[1] if key[0] == entity_id else key[0]
                neighbors.append((other, edge.weight))
        neighbors.sort(key=lambda x: x[1], reverse=True)
        return neighbors

    def get_edge_weight(self, entity_a: str, entity_b: str) -> float:
        """Get the weight of an edge between two entities.

        Args:
            entity_a: First entity ID
            entity_b: Second entity ID

        Returns:
            Edge weight, or 0.0 if no edge exists
        """
        key = tuple(sorted([entity_a, entity_b]))
        key_typed: tuple[str, str] = key  # type: ignore[assignment]
        edge = self.edges.get(key_typed)
        return edge.weight if edge else 0.0

    def get_top_entities(self, n: int) -> list[tuple[str, float]]:
        """Get top N entities by total weight.

        Args:
            n: Number of entities to return

        Returns:
            List of (entity_id, total_weight) tuples sorted by weight descending
        """
        sorted_entities = sorted(
            self.entity_weights.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return sorted_entities[:n]


@dataclass
class WindowPolicy:
    """Configuration for co-occurrence weight calculation.

    Attributes:
        same_atom_weight: Weight for entities in the same atom
        adjacent_atom_weight: Weight for entities in adjacent atoms
        same_section_weight: Weight for entities in the same section
        window_size: Number of atoms in the adjacency window
    """

    same_atom_weight: float = 1.0
    adjacent_atom_weight: float = 0.5
    same_section_weight: float = 0.25
    window_size: int = 5


class CooccurrenceGraph:
    """Builder for entity co-occurrence graphs (ALG-DISC-0001).

    Constructs a WeightedGraph from EntityTag data, using a WindowPolicy
    to determine edge weights based on proximity.
    """

    def __init__(self, policy: WindowPolicy | None = None) -> None:
        self.policy = policy or WindowPolicy()

    def build_from_entity_tags(self, tags: list[EntityTag]) -> WeightedGraph:
        """Build a co-occurrence graph from entity tags.

        Entities that share the same atom get full weight.
        Entities in adjacent atoms get reduced weight.

        Args:
            tags: List of EntityTag objects

        Returns:
            WeightedGraph with co-occurrence edges
        """
        graph = WeightedGraph()

        # Build atom -> entity mapping
        atom_to_entities: dict[str, list[str]] = defaultdict(list)
        for tag in tags:
            for atom_id in tag.atom_ids:
                atom_to_entities[atom_id].append(tag.entity_id)

        # Same-atom co-occurrence
        for atom_id, entities in atom_to_entities.items():
            for i in range(len(entities)):
                for j in range(i + 1, len(entities)):
                    graph.add_edge(
                        entities[i],
                        entities[j],
                        self.policy.same_atom_weight,
                        atom_id,
                    )

        # Adjacent-atom co-occurrence
        sorted_atoms = sorted(atom_to_entities.keys())
        for i in range(len(sorted_atoms)):
            for j in range(i + 1, min(i + self.policy.window_size, len(sorted_atoms))):
                atom_a = sorted_atoms[i]
                atom_b = sorted_atoms[j]
                entities_a = atom_to_entities[atom_a]
                entities_b = atom_to_entities[atom_b]

                # Weight decreases with distance
                distance = j - i
                weight = self.policy.adjacent_atom_weight / distance

                for ent_a in entities_a:
                    for ent_b in entities_b:
                        if ent_a != ent_b:
                            # Use a synthetic atom ID for adjacent co-occurrence
                            graph.add_edge(ent_a, ent_b, weight, f"{atom_a}~{atom_b}")

        return graph

    def find_clusters(
        self,
        graph: WeightedGraph,
        min_cluster_size: int = 2,
        weight_threshold: float = 0.5,
    ) -> list[set[str]]:
        """Find clusters (connected components) in the graph.

        Only edges meeting the weight threshold are considered.
        Only clusters meeting the minimum size are returned.

        Args:
            graph: The WeightedGraph to cluster
            min_cluster_size: Minimum number of entities in a cluster
            weight_threshold: Minimum edge weight to consider

        Returns:
            List of entity ID sets forming clusters
        """
        # Build adjacency from edges above threshold
        adjacency: dict[str, set[str]] = defaultdict(set)
        for key, edge in graph.edges.items():
            if edge.weight >= weight_threshold:
                adjacency[key[0]].add(key[1])
                adjacency[key[1]].add(key[0])

        # Find connected components via BFS
        visited: set[str] = set()
        clusters: list[set[str]] = []

        for entity in adjacency:
            if entity in visited:
                continue
            component: set[str] = set()
            queue = [entity]
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
