"""Tests for store touch graph extraction."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from spec_manager.analysis.adjacency.extractors.store_graph import (
    AccessMode,
    StoreType,
    _classify_store_type,
    extract_store_graph,
)
from spec_manager.analysis.adjacency.graph import SignalType


def _write_source(directory: Path, filename: str, code: str) -> Path:
    """Write a Python source file and return its path."""
    path = directory / filename
    path.write_text(textwrap.dedent(code), encoding="utf-8")
    return path


class TestExtractStoreGraph:
    def test_naming_convention_shared_store(self, tmp_path: Path) -> None:
        """Two functions calling read_orders() and write_orders() share a store edge."""
        path = _write_source(
            tmp_path,
            "orders.py",
            """\
            def read_orders():
                return db.query("SELECT * FROM orders")

            def write_orders(orders):
                db.insert("orders", orders)

            def process():
                data = read_orders()
                write_orders(transform(data))
            """,
        )
        graph = extract_store_graph([path], root_dir=tmp_path)

        # read_orders and write_orders both touch "orders" store
        edge = graph.get_edge("orders.read_orders", "orders.write_orders")
        reverse_edge = graph.get_edge("orders.write_orders", "orders.read_orders")

        assert edge is not None or reverse_edge is not None
        found_edge = edge or reverse_edge
        assert found_edge is not None
        assert any(s.signal_type == SignalType.STORE_TOUCH for s in found_edge.signals)

    def test_type_hint_detection(self, tmp_path: Path) -> None:
        """Type hint detection: def process(db: DatabaseStore) detects store access."""
        path = _write_source(
            tmp_path,
            "service.py",
            """\
            class DatabaseStore:
                pass

            def process_a(db: DatabaseStore):
                return db.query()

            def process_b(db: DatabaseStore):
                return db.insert()
            """,
        )
        graph = extract_store_graph([path], root_dir=tmp_path)

        # Both process_a and process_b access the same store via type hint
        edge = graph.get_edge("service.process_a", "service.process_b")
        reverse = graph.get_edge("service.process_b", "service.process_a")
        assert edge is not None or reverse is not None

    def test_store_type_classification(self) -> None:
        """Store type classification: db -> persisted, cache -> long-lived, temp -> ephemeral."""
        assert _classify_store_type("order_db") == StoreType.PERSISTED
        assert _classify_store_type("user_cache") == StoreType.LONG_LIVED
        assert _classify_store_type("temp_buffer") == StoreType.EPHEMERAL
        assert _classify_store_type("session_store") == StoreType.LONG_LIVED
        assert _classify_store_type("file_storage") == StoreType.PERSISTED
        # Default: PERSISTED for unrecognized names
        assert _classify_store_type("orders") == StoreType.PERSISTED

    def test_no_false_edges_different_stores(self, tmp_path: Path) -> None:
        """No false edges between functions touching different stores."""
        path = _write_source(
            tmp_path,
            "separate.py",
            """\
            def read_users():
                pass

            def write_products():
                pass
            """,
        )
        graph = extract_store_graph([path], root_dir=tmp_path)

        # These functions touch different stores (users vs products)
        edge = graph.get_edge("separate.read_users", "separate.write_products")
        reverse = graph.get_edge("separate.write_products", "separate.read_users")
        assert edge is None
        assert reverse is None

    def test_pin_annotation_integration(self, tmp_path: Path) -> None:
        """Pin annotation integration adds store touches."""
        path = _write_source(
            tmp_path,
            "module.py",
            """\
            def regular_reader():
                pass
            """,
        )
        pin_annotations = {
            "module.regular_reader": "orders.py",
            "module.other_fn": "orders.py",
        }
        graph = extract_store_graph([path], root_dir=tmp_path, pin_annotations=pin_annotations)

        # Both functions should be connected via the "orders" store
        edge = graph.get_edge("module.regular_reader", "module.other_fn")
        reverse = graph.get_edge("module.other_fn", "module.regular_reader")
        assert edge is not None or reverse is not None

    def test_empty_source_list(self) -> None:
        graph = extract_store_graph([], root_dir=None)
        assert len(graph.nodes()) == 0
        assert len(graph.edges()) == 0

    def test_handles_syntax_errors(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.py"
        path.write_text("def broken(:\n", encoding="utf-8")
        graph = extract_store_graph([path], root_dir=tmp_path)
        assert len(graph.nodes()) == 0

    def test_multiple_stores_multiple_functions(self, tmp_path: Path) -> None:
        """Four functions touching two stores produce correct adjacency."""
        path = _write_source(
            tmp_path,
            "multi.py",
            """\
            def read_orders():
                pass

            def write_orders():
                pass

            def fetch_inventory():
                pass

            def save_inventory():
                pass
            """,
        )
        graph = extract_store_graph([path], root_dir=tmp_path)

        # orders: read_orders and write_orders should be connected
        orders_edge = graph.get_edge("multi.read_orders", "multi.write_orders")
        orders_reverse = graph.get_edge("multi.write_orders", "multi.read_orders")
        assert orders_edge is not None or orders_reverse is not None

        # inventory: fetch_inventory and save_inventory should be connected
        # fetch_ maps to "inventory" store, save_ maps to "inventory" store
        inv_edge = graph.get_edge("multi.fetch_inventory", "multi.save_inventory")
        inv_reverse = graph.get_edge("multi.save_inventory", "multi.fetch_inventory")
        assert inv_edge is not None or inv_reverse is not None

        # No cross-store edges
        cross1 = graph.get_edge("multi.read_orders", "multi.fetch_inventory")
        cross2 = graph.get_edge("multi.fetch_inventory", "multi.read_orders")
        assert cross1 is None
        assert cross2 is None

    def test_store_nodes_in_graph(self, tmp_path: Path) -> None:
        """Store nodes should be added to the graph."""
        path = _write_source(
            tmp_path,
            "stores.py",
            """\
            def read_orders():
                pass

            def write_orders():
                pass
            """,
        )
        graph = extract_store_graph([path], root_dir=tmp_path)

        # A store node should exist
        store_nodes = [n for n in graph.nodes() if n.startswith("store:")]
        assert len(store_nodes) >= 1
        assert "store:orders" in store_nodes
