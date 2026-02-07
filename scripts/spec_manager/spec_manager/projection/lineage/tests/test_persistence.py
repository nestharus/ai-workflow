"""Tests for lineage persistence and workspace manager integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from spec_manager.schemas.pin_functions import ProjectionType
from spec_manager.projection.lineage.import_graph import ImportEdge, ImportGraph
from spec_manager.projection.lineage.persistence import (
    load_import_graph,
    load_lineage_table,
    save_import_graph,
    save_lineage_table,
)
from spec_manager.projection.lineage.table import ProjectionLineageTable


class TestLineageTablePersistence:
    def test_lineage_table_persistence_roundtrip(self, tmp_path: Path):
        """Write and read back preserves all edges."""
        table = ProjectionLineageTable()
        table.add_edge(
            "atom_a", "loc_b", ProjectionType.PASS_THROUGH, confidence=1.0
        )
        table.add_edge(
            "atom_c",
            "loc_d",
            ProjectionType.EVENT_BRIDGE,
            confidence=0.9,
            details={"topic": "events.payment"},
            pin_id="PIN-001",
        )
        table.add_edge(
            "",
            "loc_e",
            ProjectionType.INTRODUCTION,
            confidence=1.0,
        )

        path = tmp_path / "lineage_table.json"
        save_lineage_table(table, path)
        assert path.exists()

        restored = load_lineage_table(path)
        assert len(restored.edges) == 3

        # Verify indexes are rebuilt
        assert len(restored.trace_forward("atom_a")) == 1
        assert len(restored.trace_forward("atom_c")) == 1
        assert len(restored.find_introductions()) == 1

        # Verify edge details
        for orig, rest in zip(table.edges, restored.edges):
            assert orig.from_unit == rest.from_unit
            assert orig.to_unit == rest.to_unit
            assert orig.transformation == rest.transformation
            assert orig.confidence == rest.confidence
            assert orig.details == rest.details
            assert orig.pin_id == rest.pin_id


class TestImportGraphPersistence:
    def test_import_graph_persistence_roundtrip(self, tmp_path: Path):
        """Write and read back preserves all edges."""
        graph = ImportGraph()
        graph._add_edge(
            ImportEdge(
                importer_file="/a/consumer.py",
                importer_location="/a/consumer.py:module-level",
                imported_name="validate_payment",
                imported_from_module="atoms",
                imported_from_file="/a/atoms.py",
                line_no=5,
                is_direct=True,
            )
        )
        graph._add_edge(
            ImportEdge(
                importer_file="/a/consumer.py",
                importer_location="/a/consumer.py:module-level",
                imported_name="calc_tax",
                imported_from_module="atoms",
                imported_from_file="/a/atoms.py",
                line_no=6,
                is_direct=True,
            )
        )

        path = tmp_path / "import_graph.json"
        save_import_graph(graph, path)
        assert path.exists()

        restored = load_import_graph(path)
        assert len(restored.edges) == 2

        # Verify indexes are rebuilt
        assert len(restored.importers_of("validate_payment")) == 1
        assert len(restored.importers_of("calc_tax")) == 1
        assert len(restored.imports_in("/a/consumer.py")) == 2

        # Verify edge data
        for orig, rest in zip(graph.edges, restored.edges):
            assert orig.importer_file == rest.importer_file
            assert orig.imported_name == rest.imported_name
            assert orig.imported_from_module == rest.imported_from_module
            assert orig.line_no == rest.line_no

    def test_save_creates_parent_directories(self, tmp_path: Path):
        """save functions create parent directories if they don't exist."""
        deep_path = tmp_path / "a" / "b" / "c" / "lineage.json"
        table = ProjectionLineageTable()
        save_lineage_table(table, deep_path)
        assert deep_path.exists()

        deep_graph_path = tmp_path / "x" / "y" / "graph.json"
        graph = ImportGraph()
        save_import_graph(graph, deep_graph_path)
        assert deep_graph_path.exists()
