"""Tests for lineage schema validation."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from spec_manager.schemas.lineage import (
    AnalysisFileSchema,
    AtomAdjacency,
    AtomAnalysisEntry,
    DataFlowSummary,
    LineageEdge,
    OrphanedArchEntry,
)


class TestLineageEdge:
    """Test LineageEdge field validation."""

    def test_valid_pass_through(self) -> None:
        edge = LineageEdge(
            from_atom="validate_payment",
            to_location="src/api/handler.py:PaymentHandler.process",
            transformation="pass_through",
        )
        assert edge.transformation == "pass_through"
        assert edge.confidence == 1.0
        assert edge.import_path is None

    def test_valid_wrap(self) -> None:
        edge = LineageEdge(
            from_atom="compute_tax",
            to_location="src/billing/tax.py:apply_tax",
            transformation="middleware_wrap",
            confidence=0.9,
            import_path="from atoms.tax import compute_tax",
        )
        assert edge.transformation == "middleware_wrap"
        assert edge.confidence == 0.9

    def test_valid_smear(self) -> None:
        edge = LineageEdge(
            from_atom="merge_records",
            to_location="src/pipeline.py:run_pipeline",
            transformation="smear",
            confidence=0.8,
        )
        assert edge.transformation == "smear"

    def test_valid_introduction(self) -> None:
        edge = LineageEdge(
            from_atom="ATOM-INTRO-001",
            to_location="src/utils.py:helper",
            transformation="introduction",
            confidence=0.5,
        )
        assert edge.transformation == "introduction"

    def test_invalid_transformation_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LineageEdge(
                from_atom="x",
                to_location="y",
                transformation="invalid_type",  # type: ignore[arg-type]
            )

    def test_confidence_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LineageEdge(
                from_atom="x",
                to_location="y",
                transformation="pass_through",
                confidence=1.5,
            )
        with pytest.raises(ValidationError):
            LineageEdge(
                from_atom="x",
                to_location="y",
                transformation="pass_through",
                confidence=-0.1,
            )

    def test_serialization_round_trip(self) -> None:
        edge = LineageEdge(
            from_atom="validate_payment",
            to_location="src/handler.py:process",
            transformation="middleware_wrap",
            confidence=0.95,
            import_path="from atoms import validate_payment",
            evidence="Line 42",
        )
        data = edge.model_dump()
        restored = LineageEdge.model_validate(data)
        assert restored == edge


class TestAtomAdjacency:
    """Test AtomAdjacency model."""

    def test_empty_edges(self) -> None:
        adj = AtomAdjacency(atom_id="atom_a")
        assert adj.co_occurrence_edges == []
        assert adj.store_touch_edges == []

    def test_with_edges(self) -> None:
        adj = AtomAdjacency(
            atom_id="atom_a",
            co_occurrence_edges=["atom_b", "atom_c"],
            store_touch_edges=["atom_d"],
        )
        assert len(adj.co_occurrence_edges) == 2
        assert "atom_d" in adj.store_touch_edges


class TestDataFlowSummary:
    """Test DataFlowSummary model."""

    def test_empty_flow(self) -> None:
        flow = DataFlowSummary(atom_id="atom_x")
        assert flow.signals_in == []
        assert flow.signals_out == []
        assert flow.stores_touched == []

    def test_populated_flow(self) -> None:
        flow = DataFlowSummary(
            atom_id="compute_tax",
            signals_in=["amount: float", "rate: float"],
            signals_out=["float"],
            stores_touched=["db.tax_rates"],
        )
        assert len(flow.signals_in) == 2
        assert flow.signals_out == ["float"]


class TestAtomAnalysisEntry:
    """Test AtomAnalysisEntry serialization."""

    def test_minimal_entry(self) -> None:
        entry = AtomAnalysisEntry(
            atom_id="validate_payment",
            atom_file="atoms/payment.py",
        )
        assert entry.is_unimplemented is False
        assert entry.forward_traces == []

    def test_full_entry_serialization(self) -> None:
        entry = AtomAnalysisEntry(
            atom_id="validate_payment",
            atom_file="atoms/payment.py",
            forward_traces=[
                LineageEdge(
                    from_atom="validate_payment",
                    to_location="src/handler.py:process",
                    transformation="pass_through",
                )
            ],
            adjacency=AtomAdjacency(
                atom_id="validate_payment",
                co_occurrence_edges=["compute_tax"],
            ),
            data_flow=DataFlowSummary(
                atom_id="validate_payment",
                signals_in=["payment: dict"],
                signals_out=["bool"],
            ),
            is_unimplemented=False,
        )
        data = entry.model_dump()
        restored = AtomAnalysisEntry.model_validate(data)
        assert restored.atom_id == "validate_payment"
        assert len(restored.forward_traces) == 1
        assert restored.adjacency is not None
        assert restored.data_flow is not None


class TestOrphanedArchEntry:
    """Test OrphanedArchEntry validation."""

    def test_default_action(self) -> None:
        orphan = OrphanedArchEntry(location="src/utils.py:helper")
        assert orphan.suggested_action == "investigate"
        assert orphan.description == ""

    def test_valid_actions(self) -> None:
        for action in ("create_atom", "mark_introduction", "investigate"):
            orphan = OrphanedArchEntry(
                location="src/x.py",
                suggested_action=action,  # type: ignore[arg-type]
            )
            assert orphan.suggested_action == action

    def test_invalid_action_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OrphanedArchEntry(
                location="src/x.py",
                suggested_action="delete",  # type: ignore[arg-type]
            )


class TestAnalysisFileSchema:
    """Test the top-level AnalysisFileSchema."""

    def test_empty_schema(self) -> None:
        schema = AnalysisFileSchema(
            run_id="test-001",
            generated_at="2025-01-01T00:00:00Z",
        )
        assert schema.atoms == []
        assert schema.orphaned_architecture == []
        assert schema.summary == {}

    def test_populated_schema(self) -> None:
        schema = AnalysisFileSchema(
            run_id="test-002",
            generated_at="2025-01-01T00:00:00Z",
            atoms=[
                AtomAnalysisEntry(
                    atom_id="validate_payment",
                    atom_file="atoms/payment.py",
                    is_unimplemented=True,
                ),
            ],
            orphaned_architecture=[
                OrphanedArchEntry(
                    location="src/orphan.py",
                    description="Orphaned helper",
                    suggested_action="create_atom",
                ),
            ],
            summary={"total_atoms": 1, "unimplemented_atoms": 1},
        )
        assert len(schema.atoms) == 1
        assert schema.atoms[0].is_unimplemented is True
        assert len(schema.orphaned_architecture) == 1

    def test_json_round_trip(self) -> None:
        schema = AnalysisFileSchema(
            run_id="test-003",
            generated_at="2025-01-01T00:00:00Z",
            atoms=[
                AtomAnalysisEntry(
                    atom_id="compute_tax",
                    atom_file="atoms/tax.py",
                    forward_traces=[
                        LineageEdge(
                            from_atom="compute_tax",
                            to_location="src/billing.py:calc",
                            transformation="middleware_wrap",
                            confidence=0.85,
                        )
                    ],
                ),
            ],
            summary={"total_atoms": 1, "implemented_atoms": 1},
        )
        json_str = json.dumps(schema.model_dump(), indent=2)
        restored = AnalysisFileSchema.model_validate(json.loads(json_str))
        assert restored.run_id == "test-003"
        assert len(restored.atoms) == 1
        assert restored.atoms[0].forward_traces[0].confidence == 0.85
