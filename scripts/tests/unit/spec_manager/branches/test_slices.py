"""Tests for SliceNavigator: vertical/horizontal slice navigation."""

from __future__ import annotations

from pathlib import Path

import pytest

from spec_manager.branches.atoms import AtomRegistry
from spec_manager.branches.layout import BranchLayout
from spec_manager.branches.pins import PinRegistry
from spec_manager.branches.slices import HorizontalLayer, SliceNavigator
from spec_manager.branches.types import (
    AtomDescriptor,
    AtomKind,
    BranchKind,
    PinProjection,
    ProjectionType,
    VerticalSlice,
)


@pytest.fixture
def layout(tmp_path: Path) -> BranchLayout:
    bl = BranchLayout(run_root=tmp_path)
    bl.initialize()
    return bl


@pytest.fixture
def atom_registry(layout: BranchLayout) -> AtomRegistry:
    return AtomRegistry(layout)


@pytest.fixture
def pin_registry(layout: BranchLayout) -> PinRegistry:
    return PinRegistry(layout)


@pytest.fixture
def navigator(
    layout: BranchLayout,
    atom_registry: AtomRegistry,
    pin_registry: PinRegistry,
) -> SliceNavigator:
    return SliceNavigator(layout, atom_registry, pin_registry)


def _make_atom(atom_id: str, kind: AtomKind = AtomKind.ALGORITHM) -> AtomDescriptor:
    return AtomDescriptor(
        atom_id=atom_id,
        kind=kind,
        file_path=f"{atom_id}.py",
        function_name=atom_id,
        signature="()",
        content_hash="h" + atom_id,
        introduced_by="plan-1",
    )


class TestSliceCreation:
    """Tests for creating vertical slices."""

    def test_create_root_slice(self, navigator: SliceNavigator) -> None:
        vs = navigator.create_slice("Payment")
        assert vs.slice_id == "VS-0001"
        assert vs.name == "Payment"
        assert vs.parent_slice_id is None

    def test_create_child_slice(self, navigator: SliceNavigator) -> None:
        parent = navigator.create_slice("Payment")
        child = navigator.create_slice("Validation", parent_slice_id=parent.slice_id)
        assert child.parent_slice_id == parent.slice_id
        assert child.slice_id in parent.children

    def test_create_child_invalid_parent_raises(self, navigator: SliceNavigator) -> None:
        with pytest.raises(KeyError, match="Parent slice not found"):
            navigator.create_slice("Orphan", parent_slice_id="VS-9999")

    def test_sequential_ids(self, navigator: SliceNavigator) -> None:
        s1 = navigator.create_slice("A")
        s2 = navigator.create_slice("B")
        s3 = navigator.create_slice("C")
        assert s1.slice_id == "VS-0001"
        assert s2.slice_id == "VS-0002"
        assert s3.slice_id == "VS-0003"


class TestSliceLookup:
    """Tests for looking up slices."""

    def test_get_slice(self, navigator: SliceNavigator) -> None:
        vs = navigator.create_slice("Payment")
        assert navigator.get_slice(vs.slice_id) is vs

    def test_get_nonexistent_slice(self, navigator: SliceNavigator) -> None:
        assert navigator.get_slice("VS-9999") is None

    def test_list_root_slices(self, navigator: SliceNavigator) -> None:
        r1 = navigator.create_slice("Payment")
        r2 = navigator.create_slice("Order")
        navigator.create_slice("Validation", parent_slice_id=r1.slice_id)

        roots = navigator.list_root_slices()
        root_ids = [r.slice_id for r in roots]
        assert r1.slice_id in root_ids
        assert r2.slice_id in root_ids
        assert len(roots) == 2

    def test_list_children(self, navigator: SliceNavigator) -> None:
        parent = navigator.create_slice("Payment")
        c1 = navigator.create_slice("Validation", parent_slice_id=parent.slice_id)
        c2 = navigator.create_slice("Processing", parent_slice_id=parent.slice_id)

        children = navigator.list_children(parent.slice_id)
        assert len(children) == 2
        child_ids = [c.slice_id for c in children]
        assert c1.slice_id in child_ids
        assert c2.slice_id in child_ids


class TestAtomAndStoreAssignment:
    """Tests for adding atoms and stores to slices."""

    def test_add_atom_to_slice(self, navigator: SliceNavigator) -> None:
        vs = navigator.create_slice("Payment")
        navigator.add_atom_to_slice(vs.slice_id, "validate_payment")
        assert "validate_payment" in vs.atom_ids

    def test_add_atom_idempotent(self, navigator: SliceNavigator) -> None:
        vs = navigator.create_slice("Payment")
        navigator.add_atom_to_slice(vs.slice_id, "a1")
        navigator.add_atom_to_slice(vs.slice_id, "a1")
        assert vs.atom_ids.count("a1") == 1

    def test_add_atom_invalid_slice_raises(self, navigator: SliceNavigator) -> None:
        with pytest.raises(KeyError, match="Slice not found"):
            navigator.add_atom_to_slice("VS-9999", "a1")

    def test_add_store_to_slice(self, navigator: SliceNavigator) -> None:
        vs = navigator.create_slice("Payment")
        navigator.add_store_to_slice(vs.slice_id, "payment_store")
        assert "payment_store" in vs.store_ids


class TestHorizontalLayers:
    """Tests for horizontal layer enumeration."""

    def test_algorithmic_layers(
        self,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
        navigator: SliceNavigator,
    ) -> None:
        atom_registry.register(_make_atom("algo1", AtomKind.ALGORITHM))
        atom_registry.register(_make_atom("store1", AtomKind.STORE))
        atom_registry.register(_make_atom("shape1", AtomKind.SHAPE))

        vs = navigator.create_slice("Payment")
        navigator.add_atom_to_slice(vs.slice_id, "algo1")
        navigator.add_atom_to_slice(vs.slice_id, "store1")
        navigator.add_atom_to_slice(vs.slice_id, "shape1")

        layers = navigator.get_horizontal_layers(vs.slice_id)
        layer_names = [l.name for l in layers]
        assert "Algorithms" in layer_names
        assert "Stores" in layer_names
        assert "Shapes" in layer_names

    def test_architectural_layers(
        self,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
        navigator: SliceNavigator,
    ) -> None:
        atom_registry.register(_make_atom("algo1"))
        pin_registry.register_pin(PinProjection(
            pin_id="PIN-0001",
            atom_id="algo1",
            architectural_location="services/payment",
            projection_type=ProjectionType.PASS_THROUGH,
        ))

        vs = navigator.create_slice("Payment")
        navigator.add_atom_to_slice(vs.slice_id, "algo1")

        layers = navigator.get_horizontal_layers(vs.slice_id)
        layer_names = [l.name for l in layers]
        assert "Algorithms" in layer_names
        assert "Services" in layer_names

    def test_empty_slice_no_layers(self, navigator: SliceNavigator) -> None:
        vs = navigator.create_slice("Empty")
        layers = navigator.get_horizontal_layers(vs.slice_id)
        assert layers == []

    def test_nonexistent_slice_no_layers(self, navigator: SliceNavigator) -> None:
        assert navigator.get_horizontal_layers("VS-9999") == []


class TestNavigation:
    """Tests for down/up/across navigation."""

    def test_navigate_down(
        self,
        atom_registry: AtomRegistry,
        navigator: SliceNavigator,
    ) -> None:
        atom_registry.register(_make_atom("a1"))
        desc = navigator.navigate_down("a1")
        assert desc.atom_id == "a1"

    def test_navigate_down_missing_raises(self, navigator: SliceNavigator) -> None:
        with pytest.raises(KeyError, match="Atom not found"):
            navigator.navigate_down("nonexistent")

    def test_navigate_up(
        self,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
        navigator: SliceNavigator,
    ) -> None:
        atom_registry.register(_make_atom("a1"))
        pin_registry.register_pin(PinProjection(
            pin_id="PIN-0001",
            atom_id="a1",
            architectural_location="services/s1",
            projection_type=ProjectionType.PASS_THROUGH,
        ))
        pins = navigator.navigate_up("a1")
        assert len(pins) == 1
        assert pins[0].pin_id == "PIN-0001"

    def test_navigate_up_no_pins(
        self,
        atom_registry: AtomRegistry,
        navigator: SliceNavigator,
    ) -> None:
        atom_registry.register(_make_atom("a1"))
        assert navigator.navigate_up("a1") == []

    def test_navigate_across_root_siblings(self, navigator: SliceNavigator) -> None:
        s1 = navigator.create_slice("Payment")
        s2 = navigator.create_slice("Order")
        s3 = navigator.create_slice("Inventory")

        siblings = navigator.navigate_across(s1.slice_id)
        sibling_ids = [s.slice_id for s in siblings]
        assert s2.slice_id in sibling_ids
        assert s3.slice_id in sibling_ids
        assert s1.slice_id not in sibling_ids

    def test_navigate_across_child_siblings(self, navigator: SliceNavigator) -> None:
        parent = navigator.create_slice("Parent")
        c1 = navigator.create_slice("Child1", parent_slice_id=parent.slice_id)
        c2 = navigator.create_slice("Child2", parent_slice_id=parent.slice_id)

        siblings = navigator.navigate_across(c1.slice_id)
        assert len(siblings) == 1
        assert siblings[0].slice_id == c2.slice_id


class TestStoreMonogamy:
    """Tests for store monogamy validation."""

    def test_no_violations(self, navigator: SliceNavigator) -> None:
        s1 = navigator.create_slice("Payment")
        s2 = navigator.create_slice("Order")
        navigator.add_store_to_slice(s1.slice_id, "payment_store")
        navigator.add_store_to_slice(s2.slice_id, "order_store")

        violations = navigator.validate_store_monogamy()
        assert violations == []

    def test_violation_detected(self, navigator: SliceNavigator) -> None:
        s1 = navigator.create_slice("Payment")
        s2 = navigator.create_slice("Order")
        navigator.add_store_to_slice(s1.slice_id, "shared_store")
        navigator.add_store_to_slice(s2.slice_id, "shared_store")

        violations = navigator.validate_store_monogamy()
        assert len(violations) == 1
        assert "shared_store" in violations[0]

    def test_empty_slices_no_violations(self, navigator: SliceNavigator) -> None:
        navigator.create_slice("Empty1")
        navigator.create_slice("Empty2")
        assert navigator.validate_store_monogamy() == []


class TestSlicePersistence:
    """Tests for save and load roundtrip."""

    def test_save_and_load(
        self,
        layout: BranchLayout,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
    ) -> None:
        nav = SliceNavigator(layout, atom_registry, pin_registry)
        parent = nav.create_slice("Payment")
        child = nav.create_slice("Validation", parent_slice_id=parent.slice_id)
        nav.add_atom_to_slice(parent.slice_id, "a1")
        nav.add_store_to_slice(parent.slice_id, "s1")
        nav.save()

        loaded = SliceNavigator.load(layout, atom_registry, pin_registry)
        assert loaded.get_slice(parent.slice_id) is not None
        assert loaded.get_slice(child.slice_id) is not None
        lp = loaded.get_slice(parent.slice_id)
        assert "a1" in lp.atom_ids
        assert "s1" in lp.store_ids
        assert child.slice_id in lp.children

    def test_load_empty(
        self,
        layout: BranchLayout,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
    ) -> None:
        loaded = SliceNavigator.load(layout, atom_registry, pin_registry)
        assert loaded.list_root_slices() == []


class TestHorizontalLayerSerialization:
    """Tests for HorizontalLayer serialization."""

    def test_roundtrip(self) -> None:
        original = HorizontalLayer(
            layer_id="VS-0001:algorithms",
            name="Algorithms",
            branch_kind=BranchKind.ALGORITHMIC,
            item_ids=["a1", "a2"],
        )
        data = original.to_dict()
        restored = HorizontalLayer.from_dict(data)
        assert restored.layer_id == original.layer_id
        assert restored.branch_kind == original.branch_kind
        assert restored.item_ids == original.item_ids
