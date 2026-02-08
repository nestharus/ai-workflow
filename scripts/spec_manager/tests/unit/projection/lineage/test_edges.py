"""Tests for ProjectionLineageEdge and ProjectionType."""

from __future__ import annotations

from datetime import datetime

from spec_manager.projection.lineage.edges import ProjectionLineageEdge
from spec_manager.schemas.pin_functions import ProjectionType


class TestProjectionType:
    def test_projection_type_values(self):
        """All enum values match design doc strings."""
        assert ProjectionType.PASS_THROUGH.value == "pass_through"
        assert ProjectionType.EVENT_BRIDGE.value == "event_bridge"
        assert ProjectionType.MIDDLEWARE_WRAP.value == "middleware_wrap"
        assert ProjectionType.RETRY_DECORATE.value == "retry_decorate"
        assert ProjectionType.SLICE.value == "slice"
        assert ProjectionType.SMEAR.value == "smear"
        assert ProjectionType.AGGREGATION.value == "aggregation"
        assert ProjectionType.INTRODUCTION.value == "introduction"

    def test_all_eight_types_exist(self):
        """Exactly 8 projection types defined."""
        assert len(ProjectionType) == 8


class TestProjectionLineageEdge:
    def test_edge_roundtrip_serialization(self):
        """to_dict() / from_dict() roundtrip preserves all fields."""
        ts = datetime(2025, 1, 15, 10, 30, 0)
        edge = ProjectionLineageEdge(
            from_unit="validate_payment",
            to_unit="api/handlers.py:PaymentHandler.process",
            transformation=ProjectionType.EVENT_BRIDGE,
            confidence=0.9,
            timestamp=ts,
            details={"event_topic": "payment.validated"},
            pin_id="PIN-001",
        )

        data = edge.to_dict()
        restored = ProjectionLineageEdge.from_dict(data)

        assert restored.from_unit == edge.from_unit
        assert restored.to_unit == edge.to_unit
        assert restored.transformation == edge.transformation
        assert restored.confidence == edge.confidence
        assert restored.timestamp == edge.timestamp
        assert restored.details == edge.details
        assert restored.pin_id == edge.pin_id

    def test_edge_default_confidence(self):
        """Default confidence is 1.0."""
        edge = ProjectionLineageEdge(
            from_unit="calc_tax",
            to_unit="services/tax.py:compute",
            transformation=ProjectionType.PASS_THROUGH,
        )
        assert edge.confidence == 1.0

    def test_edge_introduction_no_from_unit(self):
        """Introduction edges can have empty from_unit."""
        edge = ProjectionLineageEdge(
            from_unit="",
            to_unit="middleware/auth.py:AuthMiddleware",
            transformation=ProjectionType.INTRODUCTION,
            confidence=1.0,
        )
        assert edge.from_unit == ""
        assert edge.transformation == ProjectionType.INTRODUCTION

    def test_edge_to_dict_structure(self):
        """to_dict returns expected keys."""
        edge = ProjectionLineageEdge(
            from_unit="atom_a",
            to_unit="loc_b",
            transformation=ProjectionType.SLICE,
            confidence=0.8,
        )
        data = edge.to_dict()
        assert "from_unit" in data
        assert "to_unit" in data
        assert "transformation" in data
        assert "confidence" in data
        assert "timestamp" in data
        assert "details" in data
        assert "pin_id" in data
        assert data["transformation"] == "slice"

    def test_from_dict_with_missing_optional_fields(self):
        """from_dict handles missing optional fields gracefully."""
        data = {
            "from_unit": "atom_x",
            "to_unit": "loc_y",
            "transformation": "pass_through",
            "timestamp": "2025-01-15T10:30:00",
        }
        edge = ProjectionLineageEdge.from_dict(data)
        assert edge.confidence == 1.0
        assert edge.details == {}
        assert edge.pin_id is None
