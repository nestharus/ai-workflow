"""Tests for graph union and disconnected component detection."""

from __future__ import annotations

import json

import pytest
from spec_manager.analysis.adjacency.detector import (
    AdjacencyReport,
    IsolationClassification,
    build_unified_graph,
    detect_disconnected_components,
)
from spec_manager.analysis.adjacency.graph import (
    AdjacencyGraph,
    EdgeSignal,
    NodeInfo,
    SignalType,
)


def _make_graph_with_edges(
    edges: list[tuple[str, str, SignalType, float]],
) -> AdjacencyGraph:
    """Helper to create a graph from a list of (source, target, signal_type, weight) tuples."""
    g = AdjacencyGraph()
    for source, target, sig_type, weight in edges:
        g.add_edge(source, target, EdgeSignal(signal_type=sig_type, weight=weight))
    return g


class TestBuildUnifiedGraph:
    def test_merge_all_signal_types(self) -> None:
        call_g = _make_graph_with_edges([("a", "b", SignalType.CALL, 1.0)])
        event_g = _make_graph_with_edges([("b", "c", SignalType.EVENT, 0.8)])
        store_g = _make_graph_with_edges([("c", "d", SignalType.STORE_TOUCH, 0.5)])
        cooc_g = _make_graph_with_edges([("d", "e", SignalType.CO_OCCURRENCE, 0.3)])

        unified = build_unified_graph(
            call_graph=call_g,
            event_graph=event_g,
            store_graph=store_g,
            cooccurrence_graph=cooc_g,
        )

        assert set(unified.nodes()) == {"a", "b", "c", "d", "e"}
        assert len(unified.edges()) == 4

    def test_overlapping_edges_combined(self) -> None:
        call_g = _make_graph_with_edges([("a", "b", SignalType.CALL, 1.0)])
        cooc_g = _make_graph_with_edges([("a", "b", SignalType.CO_OCCURRENCE, 0.3)])

        unified = build_unified_graph(call_graph=call_g, cooccurrence_graph=cooc_g)

        edge = unified.get_edge("a", "b")
        assert edge is not None
        assert len(edge.signals) == 2
        assert abs(edge.total_weight - 1.3) < 1e-9

    def test_weight_overrides(self) -> None:
        call_g = _make_graph_with_edges([("a", "b", SignalType.CALL, 1.0)])

        unified = build_unified_graph(
            call_graph=call_g,
            weight_overrides={SignalType.CALL: 2.0},
        )

        edge = unified.get_edge("a", "b")
        assert edge is not None
        assert abs(edge.total_weight - 2.0) < 1e-9

    def test_none_graphs_ignored(self) -> None:
        call_g = _make_graph_with_edges([("a", "b", SignalType.CALL, 1.0)])

        unified = build_unified_graph(
            call_graph=call_g,
            event_graph=None,
            store_graph=None,
            cooccurrence_graph=None,
        )

        assert set(unified.nodes()) == {"a", "b"}
        assert len(unified.edges()) == 1

    def test_all_none_produces_empty_graph(self) -> None:
        unified = build_unified_graph()
        assert len(unified.nodes()) == 0
        assert len(unified.edges()) == 0


class TestDetectDisconnectedComponents:
    def test_fully_connected_no_warnings(self) -> None:
        graph = _make_graph_with_edges(
            [
                ("a", "b", SignalType.CALL, 1.0),
                ("b", "c", SignalType.CALL, 1.0),
                ("c", "d", SignalType.CALL, 1.0),
            ]
        )

        report = detect_disconnected_components(graph)

        assert report.num_components == 1
        assert len(report.disconnected_warnings) == 0
        assert report.total_nodes == 4

    def test_two_disconnected_truly_isolated(self) -> None:
        graph = _make_graph_with_edges(
            [
                ("a", "b", SignalType.CALL, 1.0),
                ("c", "d", SignalType.CALL, 1.0),
            ]
        )

        report = detect_disconnected_components(graph)

        assert report.num_components == 2
        # Both components should be classified as truly_isolated
        isolated = [
            c
            for c in report.components
            if c.classification == IsolationClassification.TRULY_ISOLATED
        ]
        assert len(isolated) == 2

    def test_potentially_missed_via_store(self) -> None:
        # Call graph has two disconnected components
        call_g = _make_graph_with_edges(
            [
                ("a", "b", SignalType.CALL, 1.0),
                ("c", "d", SignalType.CALL, 1.0),
            ]
        )
        # Store graph connects them
        store_g = _make_graph_with_edges(
            [
                ("a", "c", SignalType.STORE_TOUCH, 0.5),
            ]
        )

        # Unified graph will have a->b, c->d, a->c (all connected)
        unified = build_unified_graph(call_graph=call_g, store_graph=store_g)

        # If the unified graph is connected, there's only 1 component and no warnings
        report = detect_disconnected_components(unified)
        assert report.num_components == 1

    def test_potentially_missed_with_partial_graphs(self) -> None:
        # Create a unified graph with two disconnected components
        unified = _make_graph_with_edges(
            [
                ("a", "b", SignalType.CALL, 1.0),
                ("c", "d", SignalType.CALL, 1.0),
            ]
        )

        # Provide a store graph that connects them (as partial graph for cross-checking)
        store_g = _make_graph_with_edges(
            [
                ("b", "c", SignalType.STORE_TOUCH, 0.5),
            ]
        )

        report = detect_disconnected_components(
            unified,
            partial_graphs={"store": store_g},
        )

        assert report.num_components == 2
        # One component should be potentially_missed because store connects them
        potentially_missed = [
            c
            for c in report.components
            if c.classification == IsolationClassification.POTENTIALLY_MISSED
        ]
        assert len(potentially_missed) >= 1
        assert len(potentially_missed[0].bridge_candidates) >= 1

    def test_single_isolated_node_suspiciously_isolated(self) -> None:
        graph = AdjacencyGraph()
        graph.add_node("lonely", NodeInfo(node_id="lonely", node_type="function"))
        graph.add_edge("a", "b", EdgeSignal(signal_type=SignalType.CALL, weight=1.0))

        report = detect_disconnected_components(graph)

        assert report.num_components == 2
        suspicious = [
            c
            for c in report.components
            if c.classification == IsolationClassification.SUSPICIOUSLY_ISOLATED
        ]
        assert len(suspicious) == 1
        assert "lonely" in suspicious[0].nodes

    def test_empty_graph_empty_report(self) -> None:
        graph = AdjacencyGraph()
        report = detect_disconnected_components(graph)

        assert report.total_nodes == 0
        assert report.total_edges == 0
        assert report.num_components == 0
        assert len(report.components) == 0
        assert len(report.disconnected_warnings) == 0

    def test_signal_type_counts(self) -> None:
        graph = _make_graph_with_edges(
            [
                ("a", "b", SignalType.CALL, 1.0),
                ("b", "c", SignalType.CALL, 1.0),
                ("c", "d", SignalType.EVENT, 0.8),
            ]
        )

        report = detect_disconnected_components(graph)

        assert report.signal_type_counts.get("call") == 2
        assert report.signal_type_counts.get("event") == 1
        assert abs(report.signal_type_weights.get("call", 0) - 2.0) < 1e-9

    def test_markdown_report_generation(self) -> None:
        graph = _make_graph_with_edges(
            [
                ("a", "b", SignalType.CALL, 1.0),
                ("c", "d", SignalType.EVENT, 0.8),
            ]
        )

        report = detect_disconnected_components(graph)
        md = report.to_markdown()

        assert "# Adjacency Analysis Report" in md
        assert "Total nodes" in md
        assert "Connected components" in md

    def test_report_serialization_round_trip(self) -> None:
        graph = _make_graph_with_edges(
            [
                ("a", "b", SignalType.CALL, 1.0),
                ("c", "d", SignalType.EVENT, 0.8),
            ]
        )

        report = detect_disconnected_components(graph)
        data = report.to_dict()
        # Ensure it is JSON-serializable
        json_str = json.dumps(data)
        restored_data = json.loads(json_str)
        restored = AdjacencyReport.from_dict(restored_data)

        assert restored.total_nodes == report.total_nodes
        assert restored.total_edges == report.total_edges
        assert restored.num_components == report.num_components
        assert len(restored.components) == len(report.components)

    def test_weight_override_affects_total_weight(self) -> None:
        call_g = _make_graph_with_edges([("a", "b", SignalType.CALL, 1.0)])

        unified = build_unified_graph(
            call_graph=call_g,
            weight_overrides={SignalType.CALL: 3.0},
        )

        report = detect_disconnected_components(unified)
        assert report.components[0].total_internal_weight == pytest.approx(3.0)
