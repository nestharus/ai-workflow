"""Tests for the core AdjacencyGraph data structure."""

from __future__ import annotations

from spec_manager.analysis.adjacency.graph import (
    AdjacencyGraph,
    Edge,
    EdgeSignal,
    NodeInfo,
    SignalType,
)


class TestNodeInfo:
    def test_to_dict_minimal(self) -> None:
        info = NodeInfo(node_id="f1", node_type="function")
        d = info.to_dict()
        assert d["node_id"] == "f1"
        assert d["node_type"] == "function"
        assert "file_path" not in d
        assert "line_number" not in d

    def test_to_dict_full(self) -> None:
        info = NodeInfo(
            node_id="f1",
            node_type="function",
            file_path="main.py",
            line_number=10,
            metadata={"scope": "module"},
        )
        d = info.to_dict()
        assert d["file_path"] == "main.py"
        assert d["line_number"] == 10
        assert d["metadata"]["scope"] == "module"

    def test_round_trip(self) -> None:
        info = NodeInfo(
            node_id="f1",
            node_type="algorithm",
            file_path="algo.py",
            line_number=5,
            metadata={"key": "val"},
        )
        restored = NodeInfo.from_dict(info.to_dict())
        assert restored.node_id == info.node_id
        assert restored.node_type == info.node_type
        assert restored.file_path == info.file_path
        assert restored.line_number == info.line_number
        assert restored.metadata == info.metadata


class TestEdgeSignal:
    def test_to_dict(self) -> None:
        signal = EdgeSignal(
            signal_type=SignalType.CALL,
            weight=1.0,
            details={"call_site": "line 42"},
        )
        d = signal.to_dict()
        assert d["signal_type"] == "call"
        assert d["weight"] == 1.0
        assert d["details"]["call_site"] == "line 42"

    def test_round_trip(self) -> None:
        signal = EdgeSignal(
            signal_type=SignalType.EVENT,
            weight=0.8,
            details={"topic": "order.created"},
        )
        restored = EdgeSignal.from_dict(signal.to_dict())
        assert restored.signal_type == signal.signal_type
        assert restored.weight == signal.weight
        assert restored.details == signal.details


class TestEdge:
    def test_total_weight_single_signal(self) -> None:
        edge = Edge(
            source="a",
            target="b",
            signals=[EdgeSignal(signal_type=SignalType.CALL, weight=1.0)],
        )
        assert edge.total_weight == 1.0

    def test_total_weight_multiple_signals(self) -> None:
        edge = Edge(source="a", target="b")
        edge.add_signal(EdgeSignal(signal_type=SignalType.CALL, weight=1.0))
        edge.add_signal(EdgeSignal(signal_type=SignalType.CO_OCCURRENCE, weight=0.3))
        assert abs(edge.total_weight - 1.3) < 1e-9

    def test_round_trip(self) -> None:
        edge = Edge(
            source="a",
            target="b",
            signals=[
                EdgeSignal(signal_type=SignalType.CALL, weight=1.0),
                EdgeSignal(signal_type=SignalType.EVENT, weight=0.8),
            ],
        )
        restored = Edge.from_dict(edge.to_dict())
        assert restored.source == "a"
        assert restored.target == "b"
        assert len(restored.signals) == 2
        assert abs(restored.total_weight - 1.8) < 1e-9


class TestAdjacencyGraph:
    def test_add_nodes_and_edges(self) -> None:
        g = AdjacencyGraph()
        g.add_node("a", NodeInfo(node_id="a", node_type="function"))
        g.add_node("b", NodeInfo(node_id="b", node_type="function"))
        g.add_edge("a", "b", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))

        assert set(g.nodes()) == {"a", "b"}
        assert len(g.edges()) == 1
        edge = g.get_edge("a", "b")
        assert edge is not None
        assert edge.total_weight == 1.0

    def test_implicit_node_creation(self) -> None:
        g = AdjacencyGraph()
        g.add_edge("x", "y", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))
        assert "x" in g.nodes()
        assert "y" in g.nodes()

    def test_multiple_signals_same_edge(self) -> None:
        g = AdjacencyGraph()
        g.add_edge("a", "b", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))
        g.add_edge("a", "b", EdgeSignal(signal_type=SignalType.CO_OCCURRENCE, weight=0.3))
        edge = g.get_edge("a", "b")
        assert edge is not None
        assert len(edge.signals) == 2
        assert abs(edge.total_weight - 1.3) < 1e-9

    def test_get_edge_not_found(self) -> None:
        g = AdjacencyGraph()
        g.add_node("a")
        assert g.get_edge("a", "b") is None
        assert g.get_edge("x", "y") is None

    def test_neighbors_outgoing(self) -> None:
        g = AdjacencyGraph()
        g.add_edge("a", "b", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))
        g.add_edge("a", "c", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))
        neighbors = g.neighbors("a")
        neighbor_ids = {n for n, _ in neighbors}
        assert neighbor_ids == {"b", "c"}

    def test_all_neighbors_undirected(self) -> None:
        g = AdjacencyGraph()
        g.add_edge("a", "b", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))
        g.add_edge("c", "a", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))
        # 'a' should see both 'b' (outgoing) and 'c' (incoming)
        all_nbrs = g.all_neighbors("a")
        nbr_ids = {n for n, _ in all_nbrs}
        assert nbr_ids == {"b", "c"}

    def test_connected_components_single(self) -> None:
        g = AdjacencyGraph()
        g.add_edge("a", "b", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))
        g.add_edge("b", "c", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))
        components = g.connected_components()
        assert len(components) == 1
        assert components[0] == {"a", "b", "c"}

    def test_connected_components_two(self) -> None:
        g = AdjacencyGraph()
        g.add_edge("a", "b", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))
        g.add_edge("c", "d", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))
        components = g.connected_components()
        assert len(components) == 2
        component_sets = [frozenset(c) for c in components]
        assert frozenset({"a", "b"}) in component_sets
        assert frozenset({"c", "d"}) in component_sets

    def test_connected_components_isolated_node(self) -> None:
        g = AdjacencyGraph()
        g.add_node("a")
        g.add_edge("b", "c", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))
        components = g.connected_components()
        assert len(components) == 2
        component_sets = [frozenset(c) for c in components]
        assert frozenset({"a"}) in component_sets
        assert frozenset({"b", "c"}) in component_sets

    def test_connected_components_directed_treated_undirected(self) -> None:
        """Directed edge a->b should still make a and b connected."""
        g = AdjacencyGraph()
        g.add_edge("a", "b", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))
        components = g.connected_components()
        assert len(components) == 1
        assert components[0] == {"a", "b"}

    def test_subgraph_extraction(self) -> None:
        g = AdjacencyGraph()
        g.add_edge("a", "b", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))
        g.add_edge("b", "c", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))
        g.add_edge("c", "d", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))

        sub = g.subgraph({"a", "b", "c"})
        assert set(sub.nodes()) == {"a", "b", "c"}
        assert sub.get_edge("a", "b") is not None
        assert sub.get_edge("b", "c") is not None
        assert sub.get_edge("c", "d") is None  # d is not in subgraph

    def test_subgraph_preserves_signals(self) -> None:
        g = AdjacencyGraph()
        g.add_edge("a", "b", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))
        g.add_edge("a", "b", EdgeSignal(signal_type=SignalType.EVENT, weight=0.8))

        sub = g.subgraph({"a", "b"})
        edge = sub.get_edge("a", "b")
        assert edge is not None
        assert len(edge.signals) == 2

    def test_graph_union(self) -> None:
        g1 = AdjacencyGraph()
        g1.add_edge("a", "b", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))

        g2 = AdjacencyGraph()
        g2.add_edge("b", "c", EdgeSignal(signal_type=SignalType.EVENT, weight=0.8))

        merged = g1.union(g2)
        assert set(merged.nodes()) == {"a", "b", "c"}
        assert merged.get_edge("a", "b") is not None
        assert merged.get_edge("b", "c") is not None

    def test_graph_union_overlapping_edges(self) -> None:
        g1 = AdjacencyGraph()
        g1.add_edge("a", "b", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))

        g2 = AdjacencyGraph()
        g2.add_edge("a", "b", EdgeSignal(signal_type=SignalType.CO_OCCURRENCE, weight=0.3))

        merged = g1.union(g2)
        edge = merged.get_edge("a", "b")
        assert edge is not None
        assert len(edge.signals) == 2
        assert abs(edge.total_weight - 1.3) < 1e-9

    def test_filter_by_signal_type(self) -> None:
        g = AdjacencyGraph()
        g.add_edge("a", "b", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))
        g.add_edge("a", "b", EdgeSignal(signal_type=SignalType.EVENT, weight=0.8))
        g.add_edge("c", "d", EdgeSignal(signal_type=SignalType.STORE_TOUCH, weight=0.5))

        filtered = g.filter_by_signal_type({SignalType.CALL})
        # Should keep a->b with only CALL signal, and drop c->d entirely
        edge_ab = filtered.get_edge("a", "b")
        assert edge_ab is not None
        assert len(edge_ab.signals) == 1
        assert edge_ab.signals[0].signal_type == SignalType.CALL

        # c->d should have no edges in filtered graph
        assert filtered.get_edge("c", "d") is None

    def test_filter_preserves_all_nodes(self) -> None:
        g = AdjacencyGraph()
        g.add_node("x", NodeInfo(node_id="x", node_type="function"))
        g.add_edge("a", "b", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))

        filtered = g.filter_by_signal_type({SignalType.EVENT})
        # All nodes should be preserved even though no edges match
        assert "x" in filtered.nodes()
        assert "a" in filtered.nodes()
        assert "b" in filtered.nodes()

    def test_serialization_round_trip(self) -> None:
        g = AdjacencyGraph()
        g.add_node("a", NodeInfo(node_id="a", node_type="function", file_path="main.py"))
        g.add_node("b", NodeInfo(node_id="b", node_type="algorithm"))
        g.add_edge(
            "a",
            "b",
            EdgeSignal(
                signal_type=SignalType.CALL,
                weight=1.0,
                details={"call_site": "line 42"},
            ),
        )
        g.add_edge(
            "a",
            "b",
            EdgeSignal(signal_type=SignalType.CO_OCCURRENCE, weight=0.3),
        )

        data = g.to_dict()
        restored = AdjacencyGraph.from_dict(data)

        assert set(restored.nodes()) == {"a", "b"}
        edge = restored.get_edge("a", "b")
        assert edge is not None
        assert len(edge.signals) == 2
        assert abs(edge.total_weight - 1.3) < 1e-9

        info_a = restored.node_info("a")
        assert info_a is not None
        assert info_a.file_path == "main.py"

    def test_empty_graph(self) -> None:
        g = AdjacencyGraph()
        assert g.nodes() == []
        assert g.edges() == []
        assert g.connected_components() == []

    def test_node_info_lookup(self) -> None:
        g = AdjacencyGraph()
        g.add_node("a", NodeInfo(node_id="a", node_type="function"))
        assert g.node_info("a") is not None
        assert g.node_info("a").node_type == "function"  # type: ignore[union-attr]
        assert g.node_info("nonexistent") is None

    def test_update_node_info(self) -> None:
        g = AdjacencyGraph()
        g.add_node("a", NodeInfo(node_id="a", node_type="function"))
        g.add_node("a", NodeInfo(node_id="a", node_type="algorithm"))
        info = g.node_info("a")
        assert info is not None
        assert info.node_type == "algorithm"
