"""Tests for evidence graph schema (DS-EVID-0004/5/6).

Tests:
- test_add_node_and_edge: Basic graph operations
- test_reindex_adjacency: Indexes built correctly
- test_graph_serialization_roundtrip: Model serialization
"""

import pytest

from spec_manager.schemas.evidence_graph import (
    EdgeType,
    EvidenceGraph,
    EvidenceGraphEdge,
    EvidenceGraphNode,
    NodeType,
)


class TestEvidenceGraphNode:
    """Test EvidenceGraphNode model."""

    def test_atom_node(self) -> None:
        """Test creating an atom node."""
        node = EvidenceGraphNode(
            node_id="ATOM-F0001-R0001-L0001",
            node_type=NodeType.ATOM,
            payload_ref="ATOM-F0001-R0001-L0001",
        )
        assert node.node_id == "ATOM-F0001-R0001-L0001"
        assert node.node_type == NodeType.ATOM
        assert node.payload_ref == "ATOM-F0001-R0001-L0001"
        assert node.metadata == {}

    def test_evidence_range_node(self) -> None:
        """Test creating an evidence range node."""
        node = EvidenceGraphNode(
            node_id="EVID-F0001-R0001-L1-L25",
            node_type=NodeType.EVIDENCE_RANGE,
            payload_ref="EVID-F0001-R0001-L1-L25",
            metadata={"label": "Introduction"},
        )
        assert node.node_type == NodeType.EVIDENCE_RANGE
        assert node.metadata["label"] == "Introduction"

    def test_section_node(self) -> None:
        """Test creating a section node."""
        node = EvidenceGraphNode(
            node_id="SEC-001",
            node_type=NodeType.SECTION,
        )
        assert node.node_type == NodeType.SECTION
        assert node.payload_ref is None


class TestEvidenceGraphEdge:
    """Test EvidenceGraphEdge model."""

    def test_supports_edge(self) -> None:
        """Test creating a SUPPORTS edge."""
        edge = EvidenceGraphEdge(
            edge_id="EDGE-000001",
            from_node_id="ATOM-F0001-R0001-L0001",
            to_node_id="EVID-F0001-R0001-L1-L25",
            edge_type=EdgeType.SUPPORTS,
        )
        assert edge.edge_id == "EDGE-000001"
        assert edge.edge_type == EdgeType.SUPPORTS
        assert edge.confidence == 1.0
        assert edge.evidence_atom_ids == []

    def test_edge_with_evidence_atoms(self) -> None:
        """Test edge with evidence atom IDs."""
        edge = EvidenceGraphEdge(
            edge_id="EDGE-000002",
            from_node_id="EVID-F0001-R0001-L1-L25",
            to_node_id="SEC-001",
            edge_type=EdgeType.SUPPORTS,
            evidence_atom_ids=["ATOM-F0001-R0001-L0001", "ATOM-F0001-R0001-L0002"],
            confidence=0.95,
            method="sectionization",
        )
        assert len(edge.evidence_atom_ids) == 2
        assert edge.confidence == 0.95
        assert edge.method == "sectionization"


class TestEvidenceGraph:
    """Test EvidenceGraph model."""

    def test_empty_graph(self) -> None:
        """Test creating an empty graph."""
        graph = EvidenceGraph()
        assert graph.schema_version == "1.0"
        assert graph.nodes == {}
        assert graph.edges == []

    def test_add_node(self) -> None:
        """Test adding nodes to graph."""
        graph = EvidenceGraph()
        node = EvidenceGraphNode(
            node_id="ATOM-F0001-R0001-L0001",
            node_type=NodeType.ATOM,
        )
        graph.add_node(node)
        assert "ATOM-F0001-R0001-L0001" in graph.nodes
        assert graph.nodes["ATOM-F0001-R0001-L0001"].node_type == NodeType.ATOM

    def test_add_edge(self) -> None:
        """Test adding edges to graph."""
        graph = EvidenceGraph()
        edge = EvidenceGraphEdge(
            edge_id="EDGE-000001",
            from_node_id="ATOM-F0001-R0001-L0001",
            to_node_id="EVID-F0001-R0001-L1-L1",
            edge_type=EdgeType.SUPPORTS,
        )
        graph.add_edge(edge)
        assert len(graph.edges) == 1
        assert graph.edges[0].edge_id == "EDGE-000001"

    def test_reindex_adjacency(self) -> None:
        """Test adjacency index building."""
        graph = EvidenceGraph()

        # Add nodes
        for node_id in ["A", "B", "C"]:
            graph.add_node(EvidenceGraphNode(node_id=node_id, node_type=NodeType.ATOM))

        # Add edges: A -> B, A -> C, B -> C
        graph.add_edge(
            EvidenceGraphEdge(
                edge_id="E1", from_node_id="A", to_node_id="B", edge_type=EdgeType.SUPPORTS
            )
        )
        graph.add_edge(
            EvidenceGraphEdge(
                edge_id="E2", from_node_id="A", to_node_id="C", edge_type=EdgeType.SUPPORTS
            )
        )
        graph.add_edge(
            EvidenceGraphEdge(
                edge_id="E3", from_node_id="B", to_node_id="C", edge_type=EdgeType.SUPPORTS
            )
        )

        graph.reindex_adjacency()

        # Check outgoing edges
        outgoing_a = graph.get_outgoing_edges("A")
        assert len(outgoing_a) == 2
        assert {e.to_node_id for e in outgoing_a} == {"B", "C"}

        outgoing_b = graph.get_outgoing_edges("B")
        assert len(outgoing_b) == 1
        assert outgoing_b[0].to_node_id == "C"

        outgoing_c = graph.get_outgoing_edges("C")
        assert len(outgoing_c) == 0

        # Check incoming edges
        incoming_c = graph.get_incoming_edges("C")
        assert len(incoming_c) == 2
        assert {e.from_node_id for e in incoming_c} == {"A", "B"}

        incoming_a = graph.get_incoming_edges("A")
        assert len(incoming_a) == 0

    def test_get_nodes_by_type(self) -> None:
        """Test filtering nodes by type."""
        graph = EvidenceGraph()

        # Add nodes of different types
        graph.add_node(EvidenceGraphNode(node_id="ATOM-1", node_type=NodeType.ATOM))
        graph.add_node(EvidenceGraphNode(node_id="ATOM-2", node_type=NodeType.ATOM))
        graph.add_node(EvidenceGraphNode(node_id="EVID-1", node_type=NodeType.EVIDENCE_RANGE))
        graph.add_node(EvidenceGraphNode(node_id="SEC-1", node_type=NodeType.SECTION))

        atoms = graph.get_nodes_by_type(NodeType.ATOM)
        assert len(atoms) == 2

        ranges = graph.get_nodes_by_type(NodeType.EVIDENCE_RANGE)
        assert len(ranges) == 1

        sections = graph.get_nodes_by_type(NodeType.SECTION)
        assert len(sections) == 1

        gaps = graph.get_nodes_by_type(NodeType.GAP)
        assert len(gaps) == 0

    def test_graph_serialization_roundtrip(self) -> None:
        """Test graph serialization and deserialization."""
        graph = EvidenceGraph()

        # Add nodes
        graph.add_node(
            EvidenceGraphNode(
                node_id="ATOM-F0001-R0001-L0001",
                node_type=NodeType.ATOM,
                payload_ref="ATOM-F0001-R0001-L0001",
            )
        )
        graph.add_node(
            EvidenceGraphNode(
                node_id="EVID-F0001-R0001-L1-L1",
                node_type=NodeType.EVIDENCE_RANGE,
                payload_ref="EVID-F0001-R0001-L1-L1",
            )
        )

        # Add edge
        graph.add_edge(
            EvidenceGraphEdge(
                edge_id="EDGE-000001",
                from_node_id="ATOM-F0001-R0001-L0001",
                to_node_id="EVID-F0001-R0001-L1-L1",
                edge_type=EdgeType.SUPPORTS,
                confidence=0.9,
            )
        )

        # Serialize and deserialize
        data = graph.model_dump()
        restored = EvidenceGraph.model_validate(data)

        assert len(restored.nodes) == 2
        assert len(restored.edges) == 1
        assert restored.edges[0].confidence == 0.9
        assert restored.nodes["ATOM-F0001-R0001-L0001"].node_type == NodeType.ATOM

    def test_graph_json_roundtrip(self) -> None:
        """Test JSON serialization roundtrip."""
        graph = EvidenceGraph()
        graph.add_node(
            EvidenceGraphNode(
                node_id="ATOM-1",
                node_type=NodeType.ATOM,
            )
        )

        json_str = graph.model_dump_json()
        restored = EvidenceGraph.model_validate_json(json_str)

        assert "ATOM-1" in restored.nodes


class TestNodeTypes:
    """Test node type enumeration."""

    def test_all_node_types_exist(self) -> None:
        """Verify all expected node types are defined."""
        expected_types = [
            "ATOM",
            "EVIDENCE_RANGE",
            "SECTION",
            "ENTITY",
            "DERIVED_ELEMENT",
            "LIBRARY",
            "TASK",
            "GAP",
        ]
        for type_name in expected_types:
            assert hasattr(NodeType, type_name)


class TestEdgeTypes:
    """Test edge type enumeration."""

    def test_all_edge_types_exist(self) -> None:
        """Verify all expected edge types are defined."""
        expected_types = [
            "SUPPORTS",
            "MENTIONS",
            "DERIVES",
            "DEPENDS_ON",
            "RELATES_TO",
            "PATCHES",
        ]
        for type_name in expected_types:
            assert hasattr(EdgeType, type_name)
