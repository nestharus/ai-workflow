"""Tests for branch type definitions and serialization roundtrips."""

from __future__ import annotations

import pytest

from spec_manager.branches.types import (
    AtomDescriptor,
    AtomKind,
    BranchKind,
    PinProjection,
    ProjectionType,
    SliceOrientation,
    StoreType,
    VerticalSlice,
)


class TestEnums:
    """Verify enum values match expected strings."""

    def test_branch_kind_values(self) -> None:
        assert BranchKind.ALGORITHMIC.value == "algorithmic"
        assert BranchKind.ARCHITECTURAL.value == "architectural"
        assert BranchKind.ANALYSIS.value == "analysis"

    def test_atom_kind_values(self) -> None:
        assert AtomKind.ALGORITHM.value == "algorithm"
        assert AtomKind.STORE.value == "store"
        assert AtomKind.SHAPE.value == "shape"

    def test_store_type_values(self) -> None:
        assert StoreType.PERSISTED.value == "persisted"
        assert StoreType.LONG_LIVED_EPHEMERAL.value == "ephemeral_long"
        assert StoreType.PURE_EPHEMERAL.value == "ephemeral_pure"

    def test_projection_type_values(self) -> None:
        assert ProjectionType.PASS_THROUGH.value == "pass_through"
        assert ProjectionType.EVENT_BRIDGE.value == "event_bridge"
        assert ProjectionType.MIDDLEWARE_WRAP.value == "middleware_wrap"
        assert ProjectionType.RETRY_DECORATE.value == "retry_decorate"
        assert ProjectionType.SLICE.value == "slice"
        assert ProjectionType.SMEAR.value == "smear"
        assert ProjectionType.AGGREGATION.value == "aggregation"
        assert ProjectionType.INTRODUCTION.value == "introduction"

    def test_slice_orientation_values(self) -> None:
        assert SliceOrientation.HORIZONTAL.value == "horizontal"
        assert SliceOrientation.VERTICAL.value == "vertical"


class TestAtomDescriptor:
    """Tests for AtomDescriptor serialization and construction."""

    def _make_descriptor(self, **overrides) -> AtomDescriptor:
        defaults = {
            "atom_id": "validate_payment",
            "kind": AtomKind.ALGORITHM,
            "file_path": "validate_payment.py",
            "function_name": "validate_payment",
            "signature": "(amount: float) -> bool",
            "content_hash": "abc123",
            "introduced_by": "plan-1",
        }
        defaults.update(overrides)
        return AtomDescriptor(**defaults)

    def test_construction_minimal(self) -> None:
        d = self._make_descriptor()
        assert d.atom_id == "validate_payment"
        assert d.kind == AtomKind.ALGORITHM
        assert d.modified_by == []
        assert d.store_type is None
        assert d.vertical_slice is None

    def test_construction_with_store_type(self) -> None:
        d = self._make_descriptor(
            kind=AtomKind.STORE,
            store_type=StoreType.PERSISTED,
        )
        assert d.store_type == StoreType.PERSISTED

    def test_to_dict_roundtrip(self) -> None:
        original = self._make_descriptor(
            modified_by=["patch-2"],
            store_type=StoreType.PURE_EPHEMERAL,
            vertical_slice="payment",
        )
        data = original.to_dict()
        restored = AtomDescriptor.from_dict(data)

        assert restored.atom_id == original.atom_id
        assert restored.kind == original.kind
        assert restored.file_path == original.file_path
        assert restored.function_name == original.function_name
        assert restored.signature == original.signature
        assert restored.content_hash == original.content_hash
        assert restored.introduced_by == original.introduced_by
        assert restored.modified_by == original.modified_by
        assert restored.store_type == original.store_type
        assert restored.vertical_slice == original.vertical_slice

    def test_to_dict_without_optional(self) -> None:
        d = self._make_descriptor()
        data = d.to_dict()
        assert data["store_type"] is None
        assert data["vertical_slice"] is None

    def test_from_dict_missing_optional(self) -> None:
        data = {
            "atom_id": "x",
            "kind": "algorithm",
            "file_path": "x.py",
            "function_name": "x",
            "signature": "()",
            "content_hash": "h",
            "introduced_by": "p1",
        }
        d = AtomDescriptor.from_dict(data)
        assert d.modified_by == []
        assert d.store_type is None
        assert d.vertical_slice is None


class TestPinProjection:
    """Tests for PinProjection serialization and construction."""

    def _make_pin(self, **overrides) -> PinProjection:
        defaults = {
            "pin_id": "PIN-0001",
            "atom_id": "validate_payment",
            "architectural_location": "services/payment_service.py:PaymentService.validate",
            "projection_type": ProjectionType.PASS_THROUGH,
        }
        defaults.update(overrides)
        return PinProjection(**defaults)

    def test_construction_defaults(self) -> None:
        p = self._make_pin()
        assert p.confidence == 1.0
        assert p.wrapper_hash is None

    def test_to_dict_roundtrip(self) -> None:
        original = self._make_pin(
            confidence=0.85,
            wrapper_hash="wh123",
        )
        data = original.to_dict()
        restored = PinProjection.from_dict(data)

        assert restored.pin_id == original.pin_id
        assert restored.atom_id == original.atom_id
        assert restored.architectural_location == original.architectural_location
        assert restored.projection_type == original.projection_type
        assert restored.confidence == original.confidence
        assert restored.wrapper_hash == original.wrapper_hash

    def test_from_dict_defaults(self) -> None:
        data = {
            "pin_id": "PIN-0002",
            "atom_id": "x",
            "architectural_location": "services/x",
            "projection_type": "aggregation",
        }
        p = PinProjection.from_dict(data)
        assert p.confidence == 1.0
        assert p.wrapper_hash is None


class TestVerticalSlice:
    """Tests for VerticalSlice serialization and construction."""

    def test_construction_root(self) -> None:
        vs = VerticalSlice(slice_id="VS-0001", name="Payment")
        assert vs.parent_slice_id is None
        assert vs.atom_ids == []
        assert vs.store_ids == []
        assert vs.children == []

    def test_construction_with_parent(self) -> None:
        vs = VerticalSlice(
            slice_id="VS-0002",
            name="Payment Validation",
            parent_slice_id="VS-0001",
            atom_ids=["validate_payment"],
            store_ids=["payment_store"],
            children=["VS-0003"],
        )
        assert vs.parent_slice_id == "VS-0001"
        assert len(vs.atom_ids) == 1
        assert len(vs.store_ids) == 1
        assert len(vs.children) == 1

    def test_to_dict_roundtrip(self) -> None:
        original = VerticalSlice(
            slice_id="VS-0001",
            name="Order Processing",
            parent_slice_id="VS-0000",
            atom_ids=["process_order", "validate_order"],
            store_ids=["order_store"],
            children=["VS-0002", "VS-0003"],
        )
        data = original.to_dict()
        restored = VerticalSlice.from_dict(data)

        assert restored.slice_id == original.slice_id
        assert restored.name == original.name
        assert restored.parent_slice_id == original.parent_slice_id
        assert restored.atom_ids == original.atom_ids
        assert restored.store_ids == original.store_ids
        assert restored.children == original.children
