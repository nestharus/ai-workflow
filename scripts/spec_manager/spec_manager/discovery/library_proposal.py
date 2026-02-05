"""Library candidate proposal from entity graphs (ALG-DISC-0002).

This module proposes library candidates from entity co-occurrence graph
clusters using LLM assistance for naming and description.

Design References:
- ALG-DISC-0002: ProposeLibraryCandidates
- DS-DISC-0002: LibraryCandidate schema
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from spec_manager.schemas.entities import EntitiesArtifact, Entity

from spec_manager.discovery.cooccurrence import CooccurrenceGraph, WeightedGraph


class LLMClient(Protocol):
    """Protocol for LLM client interface."""

    def complete(self, prompt: str) -> str:
        """Complete a prompt and return the response text."""
        ...


@dataclass
class LibraryCandidate:
    """A library candidate proposed from entity clustering (DS-DISC-0002).

    Attributes:
        proposed_name: Suggested name for the library
        description: Description of the library's purpose
        seed_entity_ids: Entity IDs that seed this library
        seed_atom_ids: Atom IDs where the seed entities appear
        confidence: Confidence score (0.0-1.0)
        stability_key: Key for stable ID allocation
    """

    proposed_name: str
    description: str
    seed_entity_ids: list[str] = field(default_factory=list)
    seed_atom_ids: list[str] = field(default_factory=list)
    confidence: float = 0.5
    stability_key: str = ""

    def __post_init__(self) -> None:
        """Generate stability key if not provided."""
        if not self.stability_key:
            # Stability key is derived from sorted seed entity IDs
            self.stability_key = "|".join(sorted(self.seed_entity_ids))


class LibraryProposer:
    """Proposes library candidates from entity graphs (ALG-DISC-0002).

    Uses entity co-occurrence clusters to propose library candidates,
    optionally using LLM for naming and description.
    """

    def __init__(self, llm_client: LLMClient | None = None):
        """Initialize the library proposer.

        Args:
            llm_client: Optional LLM client for enhanced naming
        """
        self._llm = llm_client

    def propose_from_graph(
        self,
        graph: WeightedGraph,
        entities_artifact: "EntitiesArtifact",
        min_cluster_size: int = 2,
        weight_threshold: float = 0.5,
    ) -> list[LibraryCandidate]:
        """Propose library candidates from entity graph clusters.

        Args:
            graph: Weighted co-occurrence graph
            entities_artifact: Entity artifact with entity definitions
            min_cluster_size: Minimum entities per cluster
            weight_threshold: Minimum edge weight for clustering

        Returns:
            List of LibraryCandidate objects
        """
        # Find clusters using co-occurrence graph
        cooccurrence = CooccurrenceGraph()
        clusters = cooccurrence.find_clusters(
            graph,
            min_cluster_size=min_cluster_size,
            weight_threshold=weight_threshold,
        )

        candidates: list[LibraryCandidate] = []
        for cluster_entities in clusters:
            # Get entity objects for this cluster
            entity_objs: list[Entity] = []
            for entity_id in cluster_entities:
                entity = entities_artifact.get_entity_by_id(entity_id)
                if entity:
                    entity_objs.append(entity)

            if not entity_objs:
                continue

            # Collect atom IDs from entities in cluster
            seed_atom_ids: list[str] = []
            for entity in entity_objs:
                atom_ids = entities_artifact.get_atom_ids_for_entity(entity.entity_id)
                seed_atom_ids.extend(atom_ids)
            seed_atom_ids = list(set(seed_atom_ids))  # Deduplicate

            # Generate name and description
            if self._llm:
                name, description = self._llm_generate_library_info(entity_objs)
            else:
                name, description = self._heuristic_generate_library_info(entity_objs)

            # Calculate confidence based on cluster properties
            confidence = self._calculate_confidence(graph, cluster_entities)

            candidates.append(
                LibraryCandidate(
                    proposed_name=name,
                    description=description,
                    seed_entity_ids=sorted(cluster_entities),
                    seed_atom_ids=sorted(seed_atom_ids),
                    confidence=confidence,
                )
            )

        return candidates

    def _heuristic_generate_library_info(
        self, entities: list["Entity"]
    ) -> tuple[str, str]:
        """Generate library name and description using heuristics.

        Args:
            entities: List of entities in the cluster

        Returns:
            Tuple of (name, description)
        """
        # Use most common entity kind
        kind_counts: dict[str, int] = {}
        for entity in entities:
            kind_counts[entity.kind.value] = kind_counts.get(entity.kind.value, 0) + 1

        dominant_kind = max(kind_counts, key=lambda k: kind_counts[k])

        # Use first entity's name as base (simplified approach)
        entity_names = [e.name for e in entities]
        base_name = entity_names[0] if entity_names else "Unknown"

        # Find common prefix if any
        if len(entity_names) > 1:
            common_prefix = self._find_common_prefix(entity_names)
            if len(common_prefix) >= 3:
                base_name = common_prefix.rstrip("_- ")

        name = f"{base_name}_{dominant_kind.lower()}"
        description = f"Library containing {len(entities)} {dominant_kind.lower()} entities"

        return name, description

    def _llm_generate_library_info(
        self, entities: list["Entity"]
    ) -> tuple[str, str]:
        """Generate library name and description using LLM.

        Args:
            entities: List of entities in the cluster

        Returns:
            Tuple of (name, description)
        """
        if not self._llm:
            return self._heuristic_generate_library_info(entities)

        entity_info = [
            f"- {e.name} ({e.kind.value}): {e.description or 'no description'}"
            for e in entities[:10]  # Limit for context
        ]

        prompt = f"""Based on these related entities, suggest a concise library name and description.

Entities:
{chr(10).join(entity_info)}

Respond with ONLY two lines:
NAME: <single_word_name>
DESC: <one sentence description>"""

        try:
            response = self._llm.complete(prompt)
            lines = response.strip().split("\n")

            name = "unnamed_library"
            description = "Library from entity clustering"

            for line in lines:
                if line.startswith("NAME:"):
                    name = line[5:].strip().lower().replace(" ", "_")
                elif line.startswith("DESC:"):
                    description = line[5:].strip()

            return name, description
        except Exception:
            return self._heuristic_generate_library_info(entities)

    def _calculate_confidence(
        self, graph: WeightedGraph, cluster_entities: set[str]
    ) -> float:
        """Calculate confidence score for a cluster.

        Based on:
        - Internal connectivity (edges within cluster)
        - Average edge weight

        Args:
            graph: The weighted graph
            cluster_entities: Set of entity IDs in the cluster

        Returns:
            Confidence score (0.0-1.0)
        """
        if len(cluster_entities) < 2:
            return 0.3

        # Calculate internal edge metrics
        internal_edges = 0
        total_weight = 0.0
        possible_edges = len(cluster_entities) * (len(cluster_entities) - 1) / 2

        for key, edge in graph.edges.items():
            if key[0] in cluster_entities and key[1] in cluster_entities:
                internal_edges += 1
                total_weight += edge.weight

        if possible_edges == 0:
            return 0.3

        # Density metric (0-1)
        density = internal_edges / possible_edges

        # Average weight metric (normalized)
        avg_weight = total_weight / internal_edges if internal_edges > 0 else 0
        weight_score = min(avg_weight / 2.0, 1.0)  # Normalize assuming max weight ~2

        # Combined score
        confidence = 0.4 * density + 0.4 * weight_score + 0.2 * min(len(cluster_entities) / 10, 1.0)
        return min(max(confidence, 0.1), 0.95)

    @staticmethod
    def _find_common_prefix(strings: list[str]) -> str:
        """Find common prefix among strings."""
        if not strings:
            return ""

        prefix = strings[0]
        for s in strings[1:]:
            while not s.startswith(prefix) and prefix:
                prefix = prefix[:-1]

        return prefix
