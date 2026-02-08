"""Tests for co-occurrence graph builder (ALG-DISC-0001).

Tests:
- test_graph_building: Graph construction from entity tags
- test_window_policy: Window-based co-occurrence weights
- test_cluster_finding: Finding clusters in the graph
- test_neighbor_lookup: Neighbor retrieval with weights
"""

from spec_manager.discovery.cooccurrence import (
    CooccurrenceGraph,
    WeightedEdge,
    WeightedGraph,
    WindowPolicy,
)
from spec_manager.schemas.entities import EntityTag


class TestWeightedGraph:
    """Test WeightedGraph data structure."""

    def test_add_edge_creates_edge(self) -> None:
        """Test adding an edge creates the edge."""
        graph = WeightedGraph()
        graph.add_edge("ENT-0001", "ENT-0002", 1.0, "ATOM-1")

        key = ("ENT-0001", "ENT-0002")
        assert key in graph.edges
        assert graph.edges[key].weight == 1.0
        assert "ATOM-1" in graph.edges[key].atom_ids

    def test_add_edge_accumulates_weight(self) -> None:
        """Test adding edges accumulates weight."""
        graph = WeightedGraph()
        graph.add_edge("ENT-0001", "ENT-0002", 1.0, "ATOM-1")
        graph.add_edge("ENT-0001", "ENT-0002", 0.5, "ATOM-2")

        key = ("ENT-0001", "ENT-0002")
        assert graph.edges[key].weight == 1.5
        assert len(graph.edges[key].atom_ids) == 2

    def test_add_edge_normalizes_key(self) -> None:
        """Test edge key is normalized (sorted)."""
        graph = WeightedGraph()
        graph.add_edge("ENT-0002", "ENT-0001", 1.0, "ATOM-1")

        # Key should be sorted
        key = ("ENT-0001", "ENT-0002")
        assert key in graph.edges
        assert ("ENT-0002", "ENT-0001") not in graph.edges

    def test_add_edge_no_self_loops(self) -> None:
        """Test self-loops are not added."""
        graph = WeightedGraph()
        graph.add_edge("ENT-0001", "ENT-0001", 1.0, "ATOM-1")

        assert len(graph.edges) == 0

    def test_get_neighbors(self) -> None:
        """Test getting neighbors of an entity."""
        graph = WeightedGraph()
        graph.add_edge("ENT-0001", "ENT-0002", 2.0, "ATOM-1")
        graph.add_edge("ENT-0001", "ENT-0003", 1.0, "ATOM-2")
        graph.add_edge("ENT-0002", "ENT-0003", 0.5, "ATOM-3")

        neighbors = graph.get_neighbors("ENT-0001")
        assert len(neighbors) == 2
        # Should be sorted by weight descending
        assert neighbors[0] == ("ENT-0002", 2.0)
        assert neighbors[1] == ("ENT-0003", 1.0)

    def test_get_edge_weight(self) -> None:
        """Test getting edge weight between entities."""
        graph = WeightedGraph()
        graph.add_edge("ENT-0001", "ENT-0002", 1.5, "ATOM-1")

        assert graph.get_edge_weight("ENT-0001", "ENT-0002") == 1.5
        assert graph.get_edge_weight("ENT-0002", "ENT-0001") == 1.5  # Order doesn't matter
        assert graph.get_edge_weight("ENT-0001", "ENT-0003") == 0.0  # No edge

    def test_get_top_entities(self) -> None:
        """Test getting top entities by weight."""
        graph = WeightedGraph()
        graph.add_edge("ENT-0001", "ENT-0002", 3.0, "ATOM-1")
        graph.add_edge("ENT-0001", "ENT-0003", 2.0, "ATOM-2")
        graph.add_edge("ENT-0002", "ENT-0003", 1.0, "ATOM-3")

        top = graph.get_top_entities(2)
        assert len(top) == 2
        # ENT-0001 has highest total weight (3+2=5)
        assert top[0][0] == "ENT-0001"
        # ENT-0002 second (3+1=4)
        assert top[1][0] == "ENT-0002"

    def test_entity_weights_tracked(self) -> None:
        """Test entity weights are tracked correctly."""
        graph = WeightedGraph()
        graph.add_edge("ENT-0001", "ENT-0002", 1.0, "ATOM-1")
        graph.add_edge("ENT-0001", "ENT-0003", 2.0, "ATOM-2")

        assert graph.entity_weights["ENT-0001"] == 3.0  # 1.0 + 2.0
        assert graph.entity_weights["ENT-0002"] == 1.0
        assert graph.entity_weights["ENT-0003"] == 2.0


class TestWindowPolicy:
    """Test WindowPolicy configuration."""

    def test_default_values(self) -> None:
        """Test default policy values."""
        policy = WindowPolicy()
        assert policy.same_atom_weight == 1.0
        assert policy.adjacent_atom_weight == 0.5
        assert policy.same_section_weight == 0.25
        assert policy.window_size == 5

    def test_custom_values(self) -> None:
        """Test custom policy values."""
        policy = WindowPolicy(
            same_atom_weight=2.0,
            adjacent_atom_weight=1.0,
            window_size=10,
        )
        assert policy.same_atom_weight == 2.0
        assert policy.window_size == 10


class TestCooccurrenceGraph:
    """Test CooccurrenceGraph builder."""

    def test_build_from_same_atom(self) -> None:
        """Test co-occurrence from same atom."""
        tags = [
            EntityTag(entity_id="ENT-0001", atom_ids=["ATOM-1"]),
            EntityTag(entity_id="ENT-0002", atom_ids=["ATOM-1"]),
        ]

        builder = CooccurrenceGraph()
        graph = builder.build_from_entity_tags(tags)

        # Entities in same atom should have edge
        assert graph.get_edge_weight("ENT-0001", "ENT-0002") == 1.0

    def test_build_from_adjacent_atoms(self) -> None:
        """Test co-occurrence from adjacent atoms."""
        tags = [
            EntityTag(entity_id="ENT-0001", atom_ids=["ATOM-0001"]),
            EntityTag(entity_id="ENT-0002", atom_ids=["ATOM-0002"]),
        ]

        builder = CooccurrenceGraph()
        graph = builder.build_from_entity_tags(tags)

        # Adjacent atoms should have edge with reduced weight
        weight = graph.get_edge_weight("ENT-0001", "ENT-0002")
        assert weight > 0
        assert weight < 1.0  # Less than same-atom weight

    def test_build_with_custom_policy(self) -> None:
        """Test building with custom window policy."""
        tags = [
            EntityTag(entity_id="ENT-0001", atom_ids=["ATOM-1"]),
            EntityTag(entity_id="ENT-0002", atom_ids=["ATOM-1"]),
        ]

        policy = WindowPolicy(same_atom_weight=2.0)
        builder = CooccurrenceGraph(policy=policy)
        graph = builder.build_from_entity_tags(tags)

        assert graph.get_edge_weight("ENT-0001", "ENT-0002") == 2.0

    def test_build_multiple_atoms_per_entity(self) -> None:
        """Test entity with multiple atom occurrences."""
        tags = [
            EntityTag(entity_id="ENT-0001", atom_ids=["ATOM-1", "ATOM-2"]),
            EntityTag(entity_id="ENT-0002", atom_ids=["ATOM-1"]),
            EntityTag(entity_id="ENT-0003", atom_ids=["ATOM-2"]),
        ]

        builder = CooccurrenceGraph()
        graph = builder.build_from_entity_tags(tags)

        # ENT-0001 co-occurs with ENT-0002 in ATOM-1
        assert graph.get_edge_weight("ENT-0001", "ENT-0002") > 0
        # ENT-0001 co-occurs with ENT-0003 in ATOM-2
        assert graph.get_edge_weight("ENT-0001", "ENT-0003") > 0

    def test_find_clusters_basic(self) -> None:
        """Test finding clusters in graph."""
        graph = WeightedGraph()
        # Cluster 1: ENT-0001, ENT-0002
        graph.add_edge("ENT-0001", "ENT-0002", 1.0, "ATOM-1")
        # Cluster 2: ENT-0003, ENT-0004
        graph.add_edge("ENT-0003", "ENT-0004", 1.0, "ATOM-2")

        builder = CooccurrenceGraph()
        clusters = builder.find_clusters(graph, min_cluster_size=2, weight_threshold=0.5)

        assert len(clusters) == 2

    def test_find_clusters_respects_threshold(self) -> None:
        """Test cluster finding respects weight threshold."""
        graph = WeightedGraph()
        graph.add_edge("ENT-0001", "ENT-0002", 1.0, "ATOM-1")
        graph.add_edge("ENT-0002", "ENT-0003", 0.2, "ATOM-2")  # Below threshold

        builder = CooccurrenceGraph()
        clusters = builder.find_clusters(graph, min_cluster_size=2, weight_threshold=0.5)

        # Only ENT-0001 and ENT-0002 should cluster
        assert len(clusters) == 1
        assert {"ENT-0001", "ENT-0002"} in clusters

    def test_find_clusters_respects_min_size(self) -> None:
        """Test cluster finding respects minimum size."""
        graph = WeightedGraph()
        graph.add_edge("ENT-0001", "ENT-0002", 1.0, "ATOM-1")

        builder = CooccurrenceGraph()
        clusters = builder.find_clusters(graph, min_cluster_size=3, weight_threshold=0.5)

        # Cluster of 2 doesn't meet min_size of 3
        assert len(clusters) == 0

    def test_find_clusters_connected_components(self) -> None:
        """Test clusters are connected components."""
        graph = WeightedGraph()
        # Triangle cluster
        graph.add_edge("ENT-0001", "ENT-0002", 1.0, "ATOM-1")
        graph.add_edge("ENT-0002", "ENT-0003", 1.0, "ATOM-2")
        graph.add_edge("ENT-0001", "ENT-0003", 1.0, "ATOM-3")

        builder = CooccurrenceGraph()
        clusters = builder.find_clusters(graph, min_cluster_size=2, weight_threshold=0.5)

        assert len(clusters) == 1
        assert {"ENT-0001", "ENT-0002", "ENT-0003"} == clusters[0]


class TestWeightedEdge:
    """Test WeightedEdge data class."""

    def test_normalized_key(self) -> None:
        """Test normalized key generation."""
        edge1 = WeightedEdge(entity_a="ENT-0002", entity_b="ENT-0001", weight=1.0)
        edge2 = WeightedEdge(entity_a="ENT-0001", entity_b="ENT-0002", weight=1.0)

        # Both should produce same normalized key
        assert edge1.normalized_key() == edge2.normalized_key()
        assert edge1.normalized_key() == ("ENT-0001", "ENT-0002")
