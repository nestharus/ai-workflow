"""Tests for call graph extraction."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from spec_manager.analysis.adjacency.extractors.call_graph import (
    CallSite,
    _resolve_callee,
    extract_call_graph,
)
from spec_manager.analysis.adjacency.graph import SignalType


@pytest.fixture
def tmp_source_dir(tmp_path: Path) -> Path:
    """Create a temporary source directory with Python files."""
    return tmp_path


def _write_source(directory: Path, filename: str, code: str) -> Path:
    """Write a Python source file and return its path."""
    path = directory / filename
    path.write_text(textwrap.dedent(code), encoding="utf-8")
    return path


class TestExtractCallGraph:
    def test_simple_function_calls(self, tmp_source_dir: Path) -> None:
        path = _write_source(
            tmp_source_dir,
            "module.py",
            """\
            def validate(data):
                return len(data) > 0

            def process(data):
                if validate(data):
                    return transform(data)
                return None

            def transform(data):
                return data.upper()
            """,
        )
        graph = extract_call_graph([path], root_dir=tmp_source_dir)

        # process calls validate and transform
        nodes = set(graph.nodes())
        assert "module.validate" in nodes
        assert "module.process" in nodes
        assert "module.transform" in nodes

        edge_pv = graph.get_edge("module.process", "module.validate")
        assert edge_pv is not None
        assert edge_pv.signals[0].signal_type == SignalType.CALL

        edge_pt = graph.get_edge("module.process", "module.transform")
        assert edge_pt is not None

    def test_method_calls_on_self(self, tmp_source_dir: Path) -> None:
        path = _write_source(
            tmp_source_dir,
            "service.py",
            """\
            class OrderService:
                def process_order(self, order):
                    self.validate(order)
                    self.save(order)

                def validate(self, order):
                    return order.is_valid()

                def save(self, order):
                    pass
            """,
        )
        graph = extract_call_graph([path], root_dir=tmp_source_dir)

        nodes = set(graph.nodes())
        assert "service.OrderService.process_order" in nodes
        assert "service.OrderService.validate" in nodes
        assert "service.OrderService.save" in nodes

        # process_order calls validate and save via self
        edge_v = graph.get_edge(
            "service.OrderService.process_order",
            "service.OrderService.validate",
        )
        assert edge_v is not None

        edge_s = graph.get_edge(
            "service.OrderService.process_order",
            "service.OrderService.save",
        )
        assert edge_s is not None

    def test_calls_across_files(self, tmp_source_dir: Path) -> None:
        path_a = _write_source(
            tmp_source_dir,
            "helpers.py",
            """\
            def compute_tax(amount):
                return amount * 0.2
            """,
        )
        path_b = _write_source(
            tmp_source_dir,
            "billing.py",
            """\
            def create_invoice(amount):
                tax = compute_tax(amount)
                return amount + tax
            """,
        )
        graph = extract_call_graph([path_a, path_b], root_dir=tmp_source_dir)

        # billing.create_invoice calls helpers.compute_tax
        # Resolution: compute_tax is unique, so it should resolve
        edge = graph.get_edge("billing.create_invoice", "helpers.compute_tax")
        assert edge is not None

    def test_unresolvable_calls_excluded(self, tmp_source_dir: Path) -> None:
        path = _write_source(
            tmp_source_dir,
            "module.py",
            """\
            import json

            def process(data):
                return json.loads(data)
            """,
        )
        graph = extract_call_graph([path], root_dir=tmp_source_dir)

        # json.loads should not be resolved (external library)
        edges = graph.edges()
        # There should be no edges since json.loads is not in known functions
        assert len(edges) == 0

    def test_async_function_calls(self, tmp_source_dir: Path) -> None:
        path = _write_source(
            tmp_source_dir,
            "async_module.py",
            """\
            async def fetch_data():
                return await transform_data([1, 2, 3])

            async def transform_data(items):
                return [x * 2 for x in items]
            """,
        )
        graph = extract_call_graph([path], root_dir=tmp_source_dir)

        nodes = set(graph.nodes())
        assert "async_module.fetch_data" in nodes
        assert "async_module.transform_data" in nodes

        edge = graph.get_edge("async_module.fetch_data", "async_module.transform_data")
        assert edge is not None

    def test_nested_function_definitions(self, tmp_source_dir: Path) -> None:
        path = _write_source(
            tmp_source_dir,
            "nested.py",
            """\
            def outer():
                def inner():
                    return 42
                return inner()
            """,
        )
        graph = extract_call_graph([path], root_dir=tmp_source_dir)

        nodes = set(graph.nodes())
        assert "nested.outer" in nodes
        assert "nested.outer.inner" in nodes

        # outer calls inner
        edge = graph.get_edge("nested.outer", "nested.outer.inner")
        assert edge is not None

    def test_skips_test_files(self, tmp_source_dir: Path) -> None:
        _write_source(
            tmp_source_dir,
            "test_module.py",
            """\
            def test_something():
                pass
            """,
        )
        graph = extract_call_graph([tmp_source_dir / "test_module.py"], root_dir=tmp_source_dir)
        assert len(graph.nodes()) == 0

    def test_skips_init_files(self, tmp_source_dir: Path) -> None:
        _write_source(
            tmp_source_dir,
            "__init__.py",
            """\
            def setup():
                pass
            """,
        )
        graph = extract_call_graph([tmp_source_dir / "__init__.py"], root_dir=tmp_source_dir)
        assert len(graph.nodes()) == 0

    def test_handles_syntax_errors(self, tmp_source_dir: Path) -> None:
        path = tmp_source_dir / "broken.py"
        path.write_text("def broken(:\n", encoding="utf-8")
        graph = extract_call_graph([path], root_dir=tmp_source_dir)
        assert len(graph.nodes()) == 0

    def test_multiple_callers_same_callee(self, tmp_source_dir: Path) -> None:
        path = _write_source(
            tmp_source_dir,
            "multi.py",
            """\
            def shared_util():
                return 42

            def caller_a():
                return shared_util()

            def caller_b():
                return shared_util()

            def caller_c():
                return shared_util()
            """,
        )
        graph = extract_call_graph([path], root_dir=tmp_source_dir)

        for caller in ["multi.caller_a", "multi.caller_b", "multi.caller_c"]:
            edge = graph.get_edge(caller, "multi.shared_util")
            assert edge is not None, f"Expected edge from {caller} to multi.shared_util"


class TestResolveCallee:
    def test_direct_match(self) -> None:
        known = {"mod.func_a", "mod.func_b"}
        call = CallSite(
            caller="mod.func_a",
            callee="mod.func_b",
            file_path="mod.py",
            line_number=5,
            is_method_call=False,
        )
        assert _resolve_callee(call, known) == "mod.func_b"

    def test_unqualified_match(self) -> None:
        known = {"mod.helper"}
        call = CallSite(
            caller="mod.main_func",
            callee="helper",
            file_path="mod.py",
            line_number=5,
            is_method_call=False,
        )
        assert _resolve_callee(call, known) == "mod.helper"

    def test_self_method_match(self) -> None:
        known = {"mod.MyClass.validate", "mod.MyClass.process"}
        call = CallSite(
            caller="mod.MyClass.process",
            callee="self.validate",
            file_path="mod.py",
            line_number=10,
            is_method_call=True,
        )
        assert _resolve_callee(call, known) == "mod.MyClass.validate"

    def test_no_match_returns_none(self) -> None:
        known = {"mod.func_a"}
        call = CallSite(
            caller="mod.func_a",
            callee="external_lib.something",
            file_path="mod.py",
            line_number=5,
            is_method_call=True,
        )
        assert _resolve_callee(call, known) is None
