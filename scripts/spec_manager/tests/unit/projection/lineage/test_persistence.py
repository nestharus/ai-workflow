"""Tests for lineage persistence."""

from __future__ import annotations

from pathlib import Path

from spec_manager.projection.lineage.persistence import (
    load_lineage_table,
    save_lineage_table,
)
from spec_manager.projection.lineage.table import ProjectionLineageTable
from spec_manager.schemas.pin_functions import ProjectionType


class TestLineageTablePersistence:
    def test_lineage_table_persistence_roundtrip(self, tmp_path: Path):
        """Write and read back preserves all edges."""
        table = ProjectionLineageTable()
        table.add_edge("atom_a", "loc_b", ProjectionType.PASS_THROUGH, confidence=1.0)
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
        for orig, rest in zip(table.edges, restored.edges, strict=False):
            assert orig.from_unit == rest.from_unit
            assert orig.to_unit == rest.to_unit
            assert orig.transformation == rest.transformation
            assert orig.confidence == rest.confidence
            assert orig.details == rest.details
            assert orig.pin_id == rest.pin_id

    def test_save_creates_parent_directories(self, tmp_path: Path):
        """Save functions create parent directories if they don't exist."""
        deep_path = tmp_path / "a" / "b" / "c" / "lineage.json"
        table = ProjectionLineageTable()
        save_lineage_table(table, deep_path)
        assert deep_path.exists()
