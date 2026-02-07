"""Tests for pin-function data structures and registry (Plan 1)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from spec_manager.core.pin_registry import PinRegistryIndex
from spec_manager.schemas.pin_functions import (
    ImportEdge,
    MicroAddress,
    PinFunction,
    PinFunctionRegistry,
)


def _make_pin_function(
    pin_func_id: str = "PFUNC-0001",
    function_name: str = "validate_payment",
    **kwargs,
) -> PinFunction:
    """Helper to create a PinFunction with sensible defaults."""
    defaults = dict(
        pin_func_id=pin_func_id,
        function_name=function_name,
        module_path="atoms.payment",
        file_path="atoms/payment.py",
        line_start=10,
        line_end=25,
        signature="(payment_data: dict) -> ValidationResult",
        docstring="Validate a payment transaction.",
        content_hash="a" * 64,
        is_shape=False,
        store_touches=[],
        evidence_atom_ids=[],
    )
    defaults.update(kwargs)
    return PinFunction(**defaults)


def _make_import_edge(
    edge_id: str = "IMEDGE-0001",
    pin_func_id: str = "PFUNC-0001",
    projection_type: str = "pass_through",
    **kwargs,
) -> ImportEdge:
    """Helper to create an ImportEdge with sensible defaults."""
    defaults = dict(
        edge_id=edge_id,
        pin_func_id=pin_func_id,
        arch_location="services/handler.py:PaymentHandler.handle",
        arch_file_path="services/handler.py",
        arch_line=42,
        projection_type=projection_type,
        confidence=1.0,
        is_direct_import=True,
    )
    defaults.update(kwargs)
    return ImportEdge(**defaults)


class TestPinFunctionCreation:
    """Tests for PinFunction model creation and validation."""

    def test_basic_creation(self):
        pf = _make_pin_function()
        assert pf.pin_func_id == "PFUNC-0001"
        assert pf.function_name == "validate_payment"
        assert pf.module_path == "atoms.payment"
        assert pf.line_start == 10
        assert pf.line_end == 25
        assert pf.is_shape is False

    def test_shape_function(self):
        pf = _make_pin_function(is_shape=True)
        assert pf.is_shape is True

    def test_store_touches(self):
        pf = _make_pin_function(store_touches=["db", "cache"])
        assert pf.store_touches == ["db", "cache"]

    def test_evidence_atom_ids(self):
        pf = _make_pin_function(
            evidence_atom_ids=["ATOM-F0001-R0001-L0010", "ATOM-F0001-R0001-L0011"]
        )
        assert len(pf.evidence_atom_ids) == 2

    def test_default_lists_are_empty(self):
        pf = _make_pin_function()
        assert pf.store_touches == []
        assert pf.evidence_atom_ids == []


class TestImportEdgeCreation:
    """Tests for ImportEdge model creation with all ProjectionType variants."""

    def test_pass_through(self):
        edge = _make_import_edge(projection_type="pass_through")
        assert edge.projection_type == "pass_through"

    def test_middleware_wrap(self):
        edge = _make_import_edge(projection_type="middleware_wrap")
        assert edge.projection_type == "middleware_wrap"

    def test_smear(self):
        edge = _make_import_edge(projection_type="smear")
        assert edge.projection_type == "smear"

    def test_introduction(self):
        edge = _make_import_edge(projection_type="introduction")
        assert edge.projection_type == "introduction"

    def test_confidence_bounds(self):
        edge = _make_import_edge(confidence=0.5)
        assert edge.confidence == 0.5

    def test_confidence_lower_bound(self):
        with pytest.raises(Exception):
            _make_import_edge(confidence=-0.1)

    def test_confidence_upper_bound(self):
        with pytest.raises(Exception):
            _make_import_edge(confidence=1.1)

    def test_is_direct_import_default(self):
        edge = _make_import_edge()
        assert edge.is_direct_import is True

    def test_inferred_import(self):
        edge = _make_import_edge(is_direct_import=False)
        assert edge.is_direct_import is False


class TestMicroAddress:
    """Tests for MicroAddress resolution modes."""

    def test_function_level(self):
        addr = MicroAddress(pin_func_id="PFUNC-0001")
        assert addr.pin_func_id == "PFUNC-0001"
        assert addr.line_start is None
        assert addr.line_end is None
        assert addr.composition_func is None

    def test_line_range(self):
        addr = MicroAddress(pin_func_id="PFUNC-0001", line_start=3, line_end=5)
        assert addr.line_start == 3
        assert addr.line_end == 5

    def test_call_site(self):
        addr = MicroAddress(
            pin_func_id="PFUNC-0001",
            composition_func="process_order",
        )
        assert addr.composition_func == "process_order"


class TestPinRegistryIndex:
    """Tests for PinRegistryIndex lookups and graph traversal."""

    @pytest.fixture()
    def sample_registry(self) -> PinFunctionRegistry:
        pf1 = _make_pin_function(
            pin_func_id="PFUNC-0001",
            function_name="validate_payment",
        )
        pf2 = _make_pin_function(
            pin_func_id="PFUNC-0002",
            function_name="compute_tax",
            is_shape=True,
            content_hash="b" * 64,
        )
        pf3 = _make_pin_function(
            pin_func_id="PFUNC-0003",
            function_name="process_order",
            content_hash="c" * 64,
        )

        edge1 = _make_import_edge(
            edge_id="IMEDGE-0001",
            pin_func_id="PFUNC-0001",
            projection_type="pass_through",
            arch_location="handler.py:handle_payment",
        )
        edge2 = _make_import_edge(
            edge_id="IMEDGE-0002",
            pin_func_id="PFUNC-0001",
            projection_type="middleware_wrap",
            arch_location="middleware.py:retry_payment",
        )
        edge3 = _make_import_edge(
            edge_id="IMEDGE-0003",
            pin_func_id="PFUNC-0002",
            projection_type="smear",
            arch_location="handler.py:handle_payment",
        )

        return PinFunctionRegistry(
            pin_functions=[pf1, pf2, pf3],
            import_edges=[edge1, edge2, edge3],
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    @pytest.fixture()
    def index(self, sample_registry) -> PinRegistryIndex:
        return PinRegistryIndex.from_registry(sample_registry)

    def test_get_importers_found(self, index):
        importers = index.get_importers("PFUNC-0001")
        assert len(importers) == 2

    def test_get_importers_not_found(self, index):
        importers = index.get_importers("PFUNC-9999")
        assert importers == []

    def test_get_pin_functions_for_arch(self, index):
        edges = index.get_pin_functions_for_arch("handler.py:handle_payment")
        assert len(edges) == 2
        pin_ids = {e.pin_func_id for e in edges}
        assert pin_ids == {"PFUNC-0001", "PFUNC-0002"}

    def test_get_by_name_found(self, index):
        pf = index.get_by_name("validate_payment")
        assert pf is not None
        assert pf.pin_func_id == "PFUNC-0001"

    def test_get_by_name_not_found(self, index):
        pf = index.get_by_name("nonexistent_func")
        assert pf is None

    def test_get_by_id_found(self, index):
        pf = index.get_by_id("PFUNC-0002")
        assert pf is not None
        assert pf.function_name == "compute_tax"

    def test_get_by_id_not_found(self, index):
        pf = index.get_by_id("PFUNC-9999")
        assert pf is None

    def test_resolve_micro_address_function_level(self, index):
        addr = MicroAddress(pin_func_id="PFUNC-0001")
        result = index.resolve_micro_address(addr)
        assert result is not None
        assert result.function_name == "validate_payment"

    def test_resolve_micro_address_line_range_valid(self, index):
        # pf1 has line_start=10, line_end=25, so length=16
        addr = MicroAddress(pin_func_id="PFUNC-0001", line_start=1, line_end=16)
        result = index.resolve_micro_address(addr)
        assert result is not None

    def test_resolve_micro_address_line_range_invalid(self, index):
        # line_end exceeds function length
        addr = MicroAddress(pin_func_id="PFUNC-0001", line_start=1, line_end=100)
        result = index.resolve_micro_address(addr)
        assert result is None

    def test_resolve_micro_address_line_range_inverted(self, index):
        addr = MicroAddress(pin_func_id="PFUNC-0001", line_start=10, line_end=3)
        result = index.resolve_micro_address(addr)
        assert result is None

    def test_resolve_micro_address_call_site_valid(self, index):
        addr = MicroAddress(
            pin_func_id="PFUNC-0001",
            composition_func="process_order",
        )
        result = index.resolve_micro_address(addr)
        assert result is not None

    def test_resolve_micro_address_call_site_invalid_composition(self, index):
        addr = MicroAddress(
            pin_func_id="PFUNC-0001",
            composition_func="nonexistent_func",
        )
        result = index.resolve_micro_address(addr)
        assert result is None

    def test_resolve_micro_address_nonexistent_pin(self, index):
        addr = MicroAddress(pin_func_id="PFUNC-9999")
        result = index.resolve_micro_address(addr)
        assert result is None

    def test_get_affected_locations(self, index):
        affected = index.get_affected_locations(["PFUNC-0001"])
        assert len(affected) == 2

    def test_get_affected_locations_multiple(self, index):
        affected = index.get_affected_locations(["PFUNC-0001", "PFUNC-0002"])
        assert len(affected) == 3

    def test_get_affected_locations_no_duplicates(self, index):
        affected = index.get_affected_locations(["PFUNC-0001", "PFUNC-0001"])
        assert len(affected) == 2  # Should deduplicate

    def test_get_affected_locations_empty(self, index):
        affected = index.get_affected_locations([])
        assert affected == []

    def test_get_affected_locations_no_importers(self, index):
        affected = index.get_affected_locations(["PFUNC-0003"])
        assert affected == []


class TestSerializationRoundTrip:
    """Tests for PinFunctionRegistry serialization round-trip."""

    def test_json_round_trip(self):
        pf = _make_pin_function(store_touches=["db"], evidence_atom_ids=["ATOM-1"])
        edge = _make_import_edge()
        registry = PinFunctionRegistry(
            schema_version="1.0",
            pin_functions=[pf],
            import_edges=[edge],
            created_at="2025-01-01T00:00:00+00:00",
        )

        # Serialize to JSON
        json_str = registry.model_dump_json()
        data = json.loads(json_str)

        # Deserialize back
        restored = PinFunctionRegistry.model_validate(data)

        assert restored.schema_version == "1.0"
        assert len(restored.pin_functions) == 1
        assert len(restored.import_edges) == 1
        assert restored.created_at == "2025-01-01T00:00:00+00:00"

        rpf = restored.pin_functions[0]
        assert rpf.pin_func_id == pf.pin_func_id
        assert rpf.function_name == pf.function_name
        assert rpf.content_hash == pf.content_hash
        assert rpf.is_shape == pf.is_shape
        assert rpf.store_touches == pf.store_touches
        assert rpf.evidence_atom_ids == pf.evidence_atom_ids

        redge = restored.import_edges[0]
        assert redge.edge_id == edge.edge_id
        assert redge.projection_type == edge.projection_type
        assert redge.confidence == edge.confidence

    def test_empty_registry_round_trip(self):
        registry = PinFunctionRegistry(
            pin_functions=[],
            import_edges=[],
            created_at="2025-01-01T00:00:00+00:00",
        )

        json_str = registry.model_dump_json()
        restored = PinFunctionRegistry.model_validate(json.loads(json_str))

        assert len(restored.pin_functions) == 0
        assert len(restored.import_edges) == 0

    def test_multiple_pin_functions_round_trip(self):
        pfs = [
            _make_pin_function(pin_func_id=f"PFUNC-{i:04d}", function_name=f"func_{i}")
            for i in range(1, 6)
        ]
        edges = [
            _make_import_edge(
                edge_id=f"IMEDGE-{i:04d}",
                pin_func_id=f"PFUNC-{i:04d}",
            )
            for i in range(1, 6)
        ]
        registry = PinFunctionRegistry(
            pin_functions=pfs,
            import_edges=edges,
            created_at="2025-06-01T12:00:00+00:00",
        )

        json_str = registry.model_dump_json()
        restored = PinFunctionRegistry.model_validate(json.loads(json_str))

        assert len(restored.pin_functions) == 5
        assert len(restored.import_edges) == 5
        assert restored.pin_functions[2].function_name == "func_3"
