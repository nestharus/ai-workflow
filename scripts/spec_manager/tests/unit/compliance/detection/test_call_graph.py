"""Tests for call graph builder and adjacency detection."""

from __future__ import annotations

import textwrap
from pathlib import Path

from spec_manager.compliance.detection.call_graph import (
    CallGraph,
    FunctionNode,
    build_call_graph,
    detect_adjacency_gaps,
)


class TestCallGraph:
    """Test CallGraph data structure operations."""

    def test_add_node_and_edge(self) -> None:
        graph = CallGraph()
        graph.add_node(FunctionNode("mod.func_a", "a.py", 1, False))
        graph.add_node(FunctionNode("mod.func_b", "a.py", 10, False))
        graph.add_edge("mod.func_a", "mod.func_b")

        assert "mod.func_a" in graph.nodes
        assert "mod.func_b" in graph.nodes
        assert "mod.func_b" in graph.edges["mod.func_a"]
        assert "mod.func_a" in graph.reverse_edges["mod.func_b"]

    def test_get_callers(self) -> None:
        graph = CallGraph()
        graph.add_node(FunctionNode("a", "a.py", 1, False))
        graph.add_node(FunctionNode("b", "a.py", 10, False))
        graph.add_edge("a", "b")

        assert graph.get_callers("b") == {"a"}
        assert graph.get_callers("a") == set()

    def test_get_callees(self) -> None:
        graph = CallGraph()
        graph.add_node(FunctionNode("a", "a.py", 1, False))
        graph.add_node(FunctionNode("b", "a.py", 10, False))
        graph.add_edge("a", "b")

        assert graph.get_callees("a") == {"b"}
        assert graph.get_callees("b") == set()

    def test_get_reachable(self) -> None:
        graph = CallGraph()
        graph.add_node(FunctionNode("a", "a.py", 1, False))
        graph.add_node(FunctionNode("b", "a.py", 10, False))
        graph.add_node(FunctionNode("c", "a.py", 20, False))
        graph.add_edge("a", "b")
        graph.add_edge("b", "c")

        reachable = graph.get_reachable("a")
        assert reachable == {"b", "c"}
        assert graph.get_reachable("c") == set()

    def test_connected_components_single(self) -> None:
        graph = CallGraph()
        graph.add_node(FunctionNode("a", "a.py", 1, False))
        graph.add_node(FunctionNode("b", "a.py", 10, False))
        graph.add_edge("a", "b")

        components = graph.get_connected_components()
        assert len(components) == 1
        assert components[0] == {"a", "b"}

    def test_connected_components_two_clusters(self) -> None:
        graph = CallGraph()
        graph.add_node(FunctionNode("a", "a.py", 1, False))
        graph.add_node(FunctionNode("b", "a.py", 10, False))
        graph.add_node(FunctionNode("c", "a.py", 20, False))
        graph.add_node(FunctionNode("d", "a.py", 30, False))
        graph.add_edge("a", "b")
        graph.add_edge("c", "d")

        components = graph.get_connected_components()
        assert len(components) == 2
        component_sets = [frozenset(c) for c in components]
        assert frozenset({"a", "b"}) in component_sets
        assert frozenset({"c", "d"}) in component_sets

    def test_disconnected_subgraphs(self) -> None:
        graph = CallGraph()
        graph.add_node(FunctionNode("a", "a.py", 1, False))
        graph.add_node(FunctionNode("b", "a.py", 10, False))
        graph.add_node(FunctionNode("c", "a.py", 20, False))
        graph.add_node(FunctionNode("d", "a.py", 30, False))
        graph.add_edge("a", "b")
        graph.add_edge("c", "d")

        subgraphs = graph.get_disconnected_subgraphs()
        assert len(subgraphs) == 2

    def test_singleton_component(self) -> None:
        graph = CallGraph()
        graph.add_node(FunctionNode("isolated", "a.py", 1, False))

        components = graph.get_connected_components()
        assert len(components) == 1
        assert components[0] == {"isolated"}


class TestBuildCallGraph:
    """Test building call graphs from source files."""

    def test_direct_function_calls(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def helper():
                return 42

            def main():
                x = helper()
                return x
        """)
        filepath = tmp_path / "calls.py"
        filepath.write_text(source, encoding="utf-8")

        graph = build_call_graph([filepath], tmp_path)

        # Should have at least 2 nodes
        assert len(graph.nodes) >= 2

        # Find the qualified names that end with our function names
        helper_names = [n for n in graph.nodes if n.endswith("helper")]
        main_names = [n for n in graph.nodes if n.endswith("main")]
        assert len(helper_names) >= 1
        assert len(main_names) >= 1

    def test_class_method_calls(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            class Calculator:
                def add(self, a, b):
                    return a + b

                def compute(self, x):
                    return self.add(x, 1)
        """)
        filepath = tmp_path / "cls.py"
        filepath.write_text(source, encoding="utf-8")

        graph = build_call_graph([filepath], tmp_path)
        assert len(graph.nodes) >= 2

    def test_multiple_files(self, tmp_path: Path) -> None:
        file_a = tmp_path / "a.py"
        file_a.write_text(
            textwrap.dedent("""\
                def func_a():
                    return 1
            """),
            encoding="utf-8",
        )

        file_b = tmp_path / "b.py"
        file_b.write_text(
            textwrap.dedent("""\
                def func_b():
                    return 2
            """),
            encoding="utf-8",
        )

        graph = build_call_graph([file_a, file_b], tmp_path)
        assert len(graph.nodes) >= 2

    def test_no_files(self) -> None:
        graph = build_call_graph([], None)
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    def test_syntax_error_file_skipped(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("def bad(:\n  pass\n", encoding="utf-8")

        good_file = tmp_path / "good.py"
        good_file.write_text("def good():\n    return 1\n", encoding="utf-8")

        graph = build_call_graph([bad_file, good_file], tmp_path)
        good_names = [n for n in graph.nodes if "good" in n]
        assert len(good_names) >= 1

    def test_two_disconnected_clusters(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def cluster1_a():
                cluster1_b()

            def cluster1_b():
                return 1

            def cluster2_a():
                cluster2_b()

            def cluster2_b():
                return 2
        """)
        filepath = tmp_path / "clusters.py"
        filepath.write_text(source, encoding="utf-8")

        graph = build_call_graph([filepath], tmp_path)
        components = graph.get_connected_components()

        # Should have 2 connected components
        assert len(components) == 2


class TestDetectAdjacencyGaps:
    """Test adjacency gap detection."""

    def test_single_component_no_gaps(self) -> None:
        graph = CallGraph()
        graph.add_node(FunctionNode("a", "a.py", 1, False))
        graph.add_node(FunctionNode("b", "a.py", 10, False))
        graph.add_edge("a", "b")

        gaps = detect_adjacency_gaps(graph, min_component_size=2)
        assert len(gaps) == 0

    def test_two_components_detected(self) -> None:
        graph = CallGraph()
        graph.add_node(FunctionNode("a", "a.py", 1, False))
        graph.add_node(FunctionNode("b", "a.py", 10, False))
        graph.add_node(FunctionNode("c", "c.py", 1, False))
        graph.add_node(FunctionNode("d", "c.py", 10, False))
        graph.add_edge("a", "b")
        graph.add_edge("c", "d")

        gaps = detect_adjacency_gaps(graph, min_component_size=2)
        assert len(gaps) == 2

        for gap in gaps:
            assert gap.invariant_family == "executable_adjacency"
            assert gap.detector == "call_graph"
            assert gap.confidence == 0.6

    def test_singletons_filtered(self) -> None:
        graph = CallGraph()
        graph.add_node(FunctionNode("isolated", "a.py", 1, False))
        graph.add_node(FunctionNode("a", "a.py", 10, False))
        graph.add_node(FunctionNode("b", "a.py", 20, False))
        graph.add_edge("a", "b")

        gaps = detect_adjacency_gaps(graph, min_component_size=2)
        # Only 1 significant component (a, b), so no adjacency gaps
        assert len(gaps) == 0

    def test_min_component_size_filter(self) -> None:
        graph = CallGraph()
        graph.add_node(FunctionNode("a", "a.py", 1, False))
        graph.add_node(FunctionNode("b", "a.py", 10, False))
        graph.add_node(FunctionNode("c", "c.py", 1, False))
        graph.add_node(FunctionNode("d", "c.py", 10, False))
        graph.add_node(FunctionNode("e", "c.py", 20, False))
        graph.add_edge("a", "b")
        graph.add_edge("c", "d")
        graph.add_edge("d", "e")

        # min_component_size=3 filters out the {a, b} pair
        gaps = detect_adjacency_gaps(graph, min_component_size=3)
        # Only {c, d, e} meets the threshold, so only 1 component >= 3 -> no gap
        assert len(gaps) == 0

    def test_empty_graph_no_gaps(self) -> None:
        graph = CallGraph()
        gaps = detect_adjacency_gaps(graph)
        assert len(gaps) == 0

    def test_evidence_details(self) -> None:
        graph = CallGraph()
        graph.add_node(FunctionNode("a", "file_a.py", 1, False))
        graph.add_node(FunctionNode("b", "file_a.py", 10, False))
        graph.add_node(FunctionNode("c", "file_b.py", 1, False))
        graph.add_node(FunctionNode("d", "file_b.py", 10, False))
        graph.add_edge("a", "b")
        graph.add_edge("c", "d")

        gaps = detect_adjacency_gaps(graph, min_component_size=2)
        assert len(gaps) == 2

        for gap in gaps:
            assert "component_size" in gap.details
            assert "members" in gap.details
            assert "total_components" in gap.details
            assert gap.details["total_components"] == 2
