"""Tests for ProjectionLineageTable."""

from __future__ import annotations

from spec_manager.projection.lineage.table import ProjectionLineageTable
from spec_manager.schemas.pin_functions import ProjectionType


class TestProjectionLineageTable:
    def _build_sample_table(self) -> ProjectionLineageTable:
        """Build a sample table with known edges for testing."""
        table = ProjectionLineageTable()
        table.add_edge(
            from_unit="validate_payment",
            to_unit="handlers/payment.py:PaymentHandler.process",
            transformation=ProjectionType.EVENT_BRIDGE,
            confidence=0.9,
        )
        table.add_edge(
            from_unit="validate_payment",
            to_unit="api/routes.py:validate_endpoint",
            transformation=ProjectionType.PASS_THROUGH,
            confidence=1.0,
        )
        table.add_edge(
            from_unit="calc_tax",
            to_unit="services/tax.py:TaxService.compute",
            transformation=ProjectionType.MIDDLEWARE_WRAP,
            confidence=0.9,
        )
        table.add_edge(
            from_unit="validate_payment",
            to_unit="workers/batch.py:BatchProcessor.run",
            transformation=ProjectionType.RETRY_DECORATE,
            confidence=0.7,
        )
        table.add_edge(
            from_unit="",
            to_unit="middleware/auth.py:AuthMiddleware",
            transformation=ProjectionType.INTRODUCTION,
            confidence=1.0,
        )
        return table

    def test_add_edge_indexes_correctly(self):
        """Adding an edge updates all three indexes."""
        table = ProjectionLineageTable()
        edge = table.add_edge(
            from_unit="atom_a",
            to_unit="loc_b",
            transformation=ProjectionType.PASS_THROUGH,
            confidence=1.0,
        )
        assert len(table.edges) == 1
        assert table._by_from["atom_a"] == [edge]
        assert table._by_to["loc_b"] == [edge]
        assert table._by_transformation[ProjectionType.PASS_THROUGH] == [edge]

    def test_trace_forward_returns_all_arch_locations(self):
        """Given atom with 3 edges, returns all 3."""
        table = self._build_sample_table()
        edges = table.trace_forward("validate_payment")
        assert len(edges) == 3
        to_units = {e.to_unit for e in edges}
        assert "handlers/payment.py:PaymentHandler.process" in to_units
        assert "api/routes.py:validate_endpoint" in to_units
        assert "workers/batch.py:BatchProcessor.run" in to_units

    def test_trace_forward_respects_min_confidence(self):
        """Only returns edges above threshold."""
        table = self._build_sample_table()
        edges = table.trace_forward("validate_payment", min_confidence=0.9)
        assert len(edges) == 2
        # The 0.7 confidence edge should be filtered out
        confidences = {e.confidence for e in edges}
        assert 0.7 not in confidences

    def test_trace_backward_returns_source_atoms(self):
        """Given arch location, returns source atoms."""
        table = self._build_sample_table()
        edges = table.trace_backward("handlers/payment.py:PaymentHandler.process")
        assert len(edges) == 1
        assert edges[0].from_unit == "validate_payment"

    def test_trace_backward_empty_for_unknown(self):
        """Backward trace returns empty for unknown location."""
        table = self._build_sample_table()
        edges = table.trace_backward("unknown/location.py:foo")
        assert edges == []

    def test_find_orphan_atoms(self):
        """Atoms in known_atoms but not in any edge from_unit."""
        table = self._build_sample_table()
        known = {"validate_payment", "calc_tax", "format_receipt"}
        orphans = table.find_orphan_atoms(known)
        assert orphans == {"format_receipt"}

    def test_find_orphan_arch_locations(self):
        """Locations known but not targeted by any edge."""
        table = self._build_sample_table()
        known = {
            "handlers/payment.py:PaymentHandler.process",
            "services/unknown.py:UnknownService.call",
        }
        orphans = table.find_orphan_arch_locations(known)
        assert orphans == {"services/unknown.py:UnknownService.call"}

    def test_find_introductions(self):
        """Only returns edges with INTRODUCTION transformation."""
        table = self._build_sample_table()
        intros = table.find_introductions()
        assert len(intros) == 1
        assert intros[0].to_unit == "middleware/auth.py:AuthMiddleware"
        assert intros[0].transformation == ProjectionType.INTRODUCTION

    def test_edges_by_transformation(self):
        """Filter by transformation type."""
        table = self._build_sample_table()
        bridges = table.edges_by_transformation(ProjectionType.EVENT_BRIDGE)
        assert len(bridges) == 1
        assert bridges[0].from_unit == "validate_payment"

    def test_table_roundtrip_serialization(self):
        """to_dict() / from_dict() preserves all edges and indexes."""
        table = self._build_sample_table()
        data = table.to_dict()
        restored = ProjectionLineageTable.from_dict(data)

        assert len(restored.edges) == len(table.edges)
        for orig, rest in zip(table.edges, restored.edges, strict=False):
            assert orig.from_unit == rest.from_unit
            assert orig.to_unit == rest.to_unit
            assert orig.transformation == rest.transformation
            assert orig.confidence == rest.confidence

        # Verify indexes are rebuilt
        assert len(restored._by_from["validate_payment"]) == 3
        assert len(restored._by_to["handlers/payment.py:PaymentHandler.process"]) == 1
        assert len(restored._by_transformation[ProjectionType.INTRODUCTION]) == 1

    def test_remove_edges_for(self):
        """Removes edges and updates indexes."""
        table = self._build_sample_table()
        initial_count = len(table.edges)
        removed = table.remove_edges_for("validate_payment")
        assert removed == 3
        assert len(table.edges) == initial_count - 3
        assert table.trace_forward("validate_payment") == []
        # Indexes for the removed edges should be cleaned up
        assert len(table._by_from.get("validate_payment", [])) == 0

    def test_remove_edges_for_as_to_unit(self):
        """remove_edges_for also removes edges where unit is the target."""
        table = ProjectionLineageTable()
        table.add_edge("a", "b", ProjectionType.PASS_THROUGH)
        table.add_edge("c", "b", ProjectionType.SLICE)
        removed = table.remove_edges_for("b")
        assert removed == 2
        assert len(table.edges) == 0

    def test_add_edge_returns_edge(self):
        """add_edge returns the created ProjectionLineageEdge."""
        table = ProjectionLineageTable()
        edge = table.add_edge(
            from_unit="x",
            to_unit="y",
            transformation=ProjectionType.SMEAR,
            confidence=0.8,
            details={"note": "test"},
            pin_id="PIN-X",
        )
        assert edge.from_unit == "x"
        assert edge.to_unit == "y"
        assert edge.confidence == 0.8
        assert edge.details == {"note": "test"}
        assert edge.pin_id == "PIN-X"
