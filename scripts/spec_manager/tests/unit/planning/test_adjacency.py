"""Tests for planning.adjacency module."""

from __future__ import annotations

import textwrap

from spec_manager.planning.adjacency import (
    CallGraph,
    StoreTouchEdge,
    _classify_store_touch,
    build_call_graph,
    discover_adjacent_details,
    find_store_touches,
)
from spec_manager.planning.models import parse_source

# --- Fixtures ---

MODULE_A = textwrap.dedent("""\
    def process(data):
        validated = validate(data)
        result = transform(validated)
        save(result)
        return result

    def validate(data):
        if not data:
            raise ValueError("empty")
        return data

    def transform(data):
        return data.upper()
""")

MODULE_B = textwrap.dedent("""\
    def save(result):
        write(result)
        commit()

    def load():
        data = fetchall()
        return data

    def notify(event):
        emit(event)
""")


class TestCallGraph:
    """Tests for CallGraph data structure."""

    def test_callees(self) -> None:
        graph = CallGraph(
            nodes={"a", "b", "c"},
            edges=[("a", "b"), ("a", "c")],
            reverse_edges={"b": {"a"}, "c": {"a"}},
        )
        assert graph.callees("a") == {"b", "c"}
        assert graph.callees("b") == set()

    def test_callers(self) -> None:
        graph = CallGraph(
            nodes={"a", "b", "c"},
            edges=[("a", "b"), ("a", "c")],
            reverse_edges={"b": {"a"}, "c": {"a"}},
        )
        assert graph.callers("b") == {"a"}
        assert graph.callers("a") == set()

    def test_transitive_callees(self) -> None:
        graph = CallGraph(
            nodes={"a", "b", "c", "d"},
            edges=[("a", "b"), ("b", "c"), ("c", "d")],
            reverse_edges={"b": {"a"}, "c": {"b"}, "d": {"c"}},
        )
        result = graph.transitive_callees("a", depth=3)
        assert "b" in result
        assert "c" in result
        assert "d" in result

    def test_transitive_callees_depth_limited(self) -> None:
        graph = CallGraph(
            nodes={"a", "b", "c", "d"},
            edges=[("a", "b"), ("b", "c"), ("c", "d")],
            reverse_edges={"b": {"a"}, "c": {"b"}, "d": {"c"}},
        )
        result = graph.transitive_callees("a", depth=1)
        assert "b" in result
        assert "d" not in result  # Too deep

    def test_transitive_callers(self) -> None:
        graph = CallGraph(
            nodes={"a", "b", "c"},
            edges=[("a", "b"), ("b", "c")],
            reverse_edges={"b": {"a"}, "c": {"b"}},
        )
        result = graph.transitive_callers("c", depth=3)
        assert "b" in result
        assert "a" in result

    def test_no_self_loops_in_transitive(self) -> None:
        graph = CallGraph(
            nodes={"a", "b"},
            edges=[("a", "b")],
            reverse_edges={"b": {"a"}},
        )
        result = graph.transitive_callees("a")
        assert "a" not in result


class TestBuildCallGraph:
    """Tests for build_call_graph function."""

    def test_builds_from_code_files(self) -> None:
        cf_a = parse_source(MODULE_A, "/test/module_a.py")
        cf_b = parse_source(MODULE_B, "/test/module_b.py")

        graph = build_call_graph([cf_a, cf_b])

        # Nodes come from function names (still populated)
        assert len(graph.nodes) >= 5  # process, validate, transform, save, load, notify
        # Edges are empty because calls=[] (adjacency being deprecated)
        assert len(graph.edges) == 0

    def test_nodes_populated_without_calls(self) -> None:
        cf_a = parse_source(MODULE_A, "/test/module_a.py")
        cf_b = parse_source(MODULE_B, "/test/module_b.py")

        graph = build_call_graph([cf_a, cf_b])

        # Verify function nodes are still discovered
        node_names = {n.split(".")[-1] for n in graph.nodes}
        assert "process" in node_names
        assert "validate" in node_names
        assert "save" in node_names

    def test_single_file(self) -> None:
        cf = parse_source(MODULE_A, "/test/module.py")
        graph = build_call_graph([cf])
        assert len(graph.nodes) >= 3


class TestClassifyStoreTouch:
    """Tests for store touch classification."""

    def test_database_read(self) -> None:
        result = _classify_store_touch("fetchall")
        assert result is not None
        assert result == ("database", "read")

    def test_database_write(self) -> None:
        result = _classify_store_touch("commit")
        assert result is not None
        assert result == ("database", "write")

    def test_file_read(self) -> None:
        result = _classify_store_touch("read_text")
        assert result is not None
        assert result == ("filesystem", "read")

    def test_file_write(self) -> None:
        result = _classify_store_touch("write_text")
        assert result is not None
        assert result == ("filesystem", "write")

    def test_queue_write(self) -> None:
        result = _classify_store_touch("publish")
        assert result is not None
        assert result == ("queue", "write")

    def test_event_write(self) -> None:
        result = _classify_store_touch("emit")
        assert result is not None
        assert result == ("event_bus", "write")

    def test_event_read(self) -> None:
        result = _classify_store_touch("subscribe")
        # subscribe appears in both queue and event patterns
        assert result is not None

    def test_no_match(self) -> None:
        result = _classify_store_touch("custom_function")
        assert result is None


class TestFindStoreTouches:
    """Tests for find_store_touches function."""

    def test_no_touches_without_calls(self) -> None:
        # calls=[] now (adjacency being deprecated), so no store touches detected
        cf_b = parse_source(MODULE_B, "/test/module_b.py")
        touches = find_store_touches([cf_b])
        assert len(touches) == 0

    def test_detects_touches_from_manual_calls(self) -> None:
        # Verify store detection still works when calls are provided directly
        from spec_manager.planning.models import CodeFile, FunctionInfo

        func = FunctionInfo(
            name="save",
            file_path="/test/module_b.py",
            start_line=1,
            end_line=3,
            indent_level=0,
            parameters=[],
            return_annotation=None,
            docstring=None,
            body_lines=2,
            calls=["write", "commit"],
            comments=[],
            class_name=None,
            decorators=[],
        )
        cf = CodeFile(
            file_path="/test/module_b.py",
            functions=[func],
            top_level_comments=[],
            imports=[],
            classes=[],
        )
        touches = find_store_touches([cf])
        store_names = {t.store_name for t in touches}
        assert "filesystem" in store_names or "database" in store_names


class TestDiscoverAdjacentDetails:
    """Tests for discover_adjacent_details function."""

    def test_finds_downstream(self) -> None:
        graph = CallGraph(
            nodes={"a", "b", "c"},
            edges=[("a", "b"), ("a", "c")],
            reverse_edges={"b": {"a"}, "c": {"a"}},
        )
        adjacencies = discover_adjacent_details("a", graph, [])
        relationships = {adj.relationship for adj in adjacencies}
        assert "calls" in relationships

    def test_finds_upstream(self) -> None:
        graph = CallGraph(
            nodes={"a", "b"},
            edges=[("a", "b")],
            reverse_edges={"b": {"a"}},
        )
        adjacencies = discover_adjacent_details("b", graph, [])
        relationships = {adj.relationship for adj in adjacencies}
        assert "called_by" in relationships

    def test_finds_shared_store(self) -> None:
        graph = CallGraph(nodes={"a", "b"}, edges=[], reverse_edges={})
        touches = [
            StoreTouchEdge(
                function_name="a",
                store_name="database",
                access_type="write",
                line_no=1,
                file_path="/test.py",
            ),
            StoreTouchEdge(
                function_name="b",
                store_name="database",
                access_type="read",
                line_no=5,
                file_path="/test.py",
            ),
        ]
        adjacencies = discover_adjacent_details("a", graph, touches)
        assert len(adjacencies) == 1
        assert adjacencies[0].relationship == "shared_store"
        assert adjacencies[0].store_or_event == "database"

    def test_default_no_test_coverage(self) -> None:
        graph = CallGraph(
            nodes={"a", "b"},
            edges=[("a", "b")],
            reverse_edges={"b": {"a"}},
        )
        adjacencies = discover_adjacent_details("a", graph, [])
        for adj in adjacencies:
            assert adj.has_test_coverage is False
            assert adj.needs_plan is True

    def test_with_test_coverage(self) -> None:
        graph = CallGraph(
            nodes={"a", "b"},
            edges=[("a", "b")],
            reverse_edges={"b": {"a"}},
        )
        coverage = {"b": True}
        adjacencies = discover_adjacent_details("a", graph, [], test_coverage=coverage)
        for adj in adjacencies:
            if adj.related_function == "b":
                assert adj.has_test_coverage is True
                assert adj.needs_plan is False

    def test_no_duplicates(self) -> None:
        graph = CallGraph(
            nodes={"a", "b"},
            edges=[("a", "b")],
            reverse_edges={"b": {"a"}},
        )
        touches = [
            StoreTouchEdge(
                function_name="a",
                store_name="database",
                access_type="write",
                line_no=1,
                file_path="/test.py",
            ),
            StoreTouchEdge(
                function_name="b",
                store_name="database",
                access_type="read",
                line_no=5,
                file_path="/test.py",
            ),
        ]
        adjacencies = discover_adjacent_details("a", graph, touches)
        related_funcs = [adj.related_function for adj in adjacencies]
        # "b" should appear only once even though it's both a callee and shares a store
        assert related_funcs.count("b") == 1
