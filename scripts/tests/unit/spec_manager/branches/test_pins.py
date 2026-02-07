"""Tests for PinRegistry: forward/backward trace, drift, and persistence."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from spec_manager.branches.atoms import AtomRegistry
from spec_manager.branches.layout import BranchLayout
from spec_manager.branches.pins import DriftReport, PinRegistry
from spec_manager.branches.types import (
    AtomDescriptor,
    AtomKind,
    PinProjection,
    ProjectionType,
)


@pytest.fixture
def layout(tmp_path: Path) -> BranchLayout:
    bl = BranchLayout(run_root=tmp_path)
    bl.initialize()
    return bl


@pytest.fixture
def registry(layout: BranchLayout) -> PinRegistry:
    return PinRegistry(layout)


def _make_pin(
    pin_id: str = "PIN-0001",
    atom_id: str = "validate_payment",
    location: str = "services/payment:PaymentService.validate",
    projection: ProjectionType = ProjectionType.PASS_THROUGH,
) -> PinProjection:
    return PinProjection(
        pin_id=pin_id,
        atom_id=atom_id,
        architectural_location=location,
        projection_type=projection,
    )


def _make_atom(
    atom_id: str = "validate_payment",
    content_hash: str = "hash1",
) -> AtomDescriptor:
    return AtomDescriptor(
        atom_id=atom_id,
        kind=AtomKind.ALGORITHM,
        file_path=f"{atom_id}.py",
        function_name=atom_id,
        signature="()",
        content_hash=content_hash,
        introduced_by="plan-1",
    )


class TestPinRegistration:
    """Basic registration and lookup operations."""

    def test_register_and_get(self, registry: PinRegistry) -> None:
        pin = _make_pin()
        registry.register_pin(pin)
        assert registry.get_pin("PIN-0001") is pin

    def test_get_nonexistent(self, registry: PinRegistry) -> None:
        assert registry.get_pin("PIN-9999") is None

    def test_unregister(self, registry: PinRegistry) -> None:
        pin = _make_pin()
        registry.register_pin(pin)
        registry.unregister_pin("PIN-0001")
        assert registry.get_pin("PIN-0001") is None

    def test_unregister_nonexistent_raises(self, registry: PinRegistry) -> None:
        with pytest.raises(KeyError, match="Pin not registered"):
            registry.unregister_pin("PIN-9999")

    def test_list_all(self, registry: PinRegistry) -> None:
        registry.register_pin(_make_pin("PIN-0001"))
        registry.register_pin(_make_pin("PIN-0002", atom_id="apply_discount"))
        assert len(registry.list_all()) == 2


class TestForwardTrace:
    """Forward trace: atom_id -> architectural locations."""

    def test_single_location(self, registry: PinRegistry) -> None:
        registry.register_pin(_make_pin())
        locations = registry.get_architectural_locations("validate_payment")
        assert len(locations) == 1
        assert locations[0].pin_id == "PIN-0001"

    def test_multiple_locations(self, registry: PinRegistry) -> None:
        registry.register_pin(_make_pin("PIN-0001", "a1", "services/s1"))
        registry.register_pin(_make_pin("PIN-0002", "a1", "events/e1"))
        locations = registry.get_architectural_locations("a1")
        assert len(locations) == 2

    def test_no_locations(self, registry: PinRegistry) -> None:
        assert registry.get_architectural_locations("nonexistent") == []


class TestBackwardTrace:
    """Backward trace: architectural location -> atom."""

    def test_exact_match(self, registry: PinRegistry) -> None:
        registry.register_pin(_make_pin())
        pin = registry.get_atom_for_location("services/payment:PaymentService.validate")
        assert pin is not None
        assert pin.atom_id == "validate_payment"

    def test_no_match(self, registry: PinRegistry) -> None:
        assert registry.get_atom_for_location("nonexistent") is None


class TestChangePropagation:
    """Change propagation: affected pins for changed atoms."""

    def test_affected_pins_found(self, registry: PinRegistry) -> None:
        registry.register_pin(_make_pin("PIN-0001", "a1", "s1"))
        registry.register_pin(_make_pin("PIN-0002", "a2", "s2"))
        affected = registry.get_affected_pins(["a1"])
        assert "a1" in affected
        assert len(affected["a1"]) == 1
        assert "a2" not in affected

    def test_affected_pins_none(self, registry: PinRegistry) -> None:
        registry.register_pin(_make_pin("PIN-0001", "a1", "s1"))
        affected = registry.get_affected_pins(["nonexistent"])
        assert affected == {}


class TestDriftDetection:
    """Drift detection using atom content hashes."""

    def test_no_drift_when_no_changes(self, layout: BranchLayout) -> None:
        pin_reg = PinRegistry(layout)
        atom_reg = AtomRegistry(layout)
        atom = _make_atom("a1", "hash1")
        atom_reg.register(atom)
        pin_reg.register_pin(_make_pin("PIN-0001", "a1", "s1"))

        # No file on disk = no changes detected
        reports = pin_reg.detect_drift(atom_reg)
        assert reports == []

    def test_drift_detected_for_pass_through(self, layout: BranchLayout) -> None:
        pin_reg = PinRegistry(layout)
        atom_reg = AtomRegistry(layout)

        # Write file with initial content
        atom_file = layout.atoms_dir / "a1.py"
        atom_file.write_text("def a1(): pass", encoding="utf-8")
        original_hash = hashlib.sha256(b"def a1(): pass").hexdigest()

        atom = _make_atom("a1", original_hash)
        atom_reg.register(atom)
        pin_reg.register_pin(_make_pin("PIN-0001", "a1", "s1", ProjectionType.PASS_THROUGH))

        # Modify the file
        atom_file.write_text("def a1(): return 42", encoding="utf-8")

        reports = pin_reg.detect_drift(atom_reg)
        assert len(reports) == 1
        assert reports[0].drift_type == "atom_changed"
        assert reports[0].pin_id == "PIN-0001"

    def test_drift_detected_for_aggregation(self, layout: BranchLayout) -> None:
        pin_reg = PinRegistry(layout)
        atom_reg = AtomRegistry(layout)

        atom_file = layout.atoms_dir / "a1.py"
        atom_file.write_text("def a1(): pass", encoding="utf-8")
        original_hash = hashlib.sha256(b"def a1(): pass").hexdigest()

        atom = _make_atom("a1", original_hash)
        atom_reg.register(atom)
        pin_reg.register_pin(_make_pin("PIN-0001", "a1", "s1", ProjectionType.AGGREGATION))

        atom_file.write_text("def a1(): return 42", encoding="utf-8")

        reports = pin_reg.detect_drift(atom_reg)
        assert len(reports) == 1
        assert reports[0].drift_type == "aggregation_invalidated"


class TestCoverageAnalysis:
    """Unpinned atoms and orphaned architectural code."""

    def test_unpinned_atoms(self, layout: BranchLayout) -> None:
        pin_reg = PinRegistry(layout)
        atom_reg = AtomRegistry(layout)

        atom_reg.register(_make_atom("a1"))
        atom_reg.register(_make_atom("a2"))
        pin_reg.register_pin(_make_pin("PIN-0001", "a1", "s1"))

        unpinned = pin_reg.get_unpinned_atoms(atom_reg)
        assert unpinned == ["a2"]

    def test_no_unpinned(self, layout: BranchLayout) -> None:
        pin_reg = PinRegistry(layout)
        atom_reg = AtomRegistry(layout)

        atom_reg.register(_make_atom("a1"))
        pin_reg.register_pin(_make_pin("PIN-0001", "a1", "s1"))

        assert pin_reg.get_unpinned_atoms(atom_reg) == []


class TestPinIdAllocation:
    """PIN-#### ID allocation."""

    def test_sequential_allocation(self, registry: PinRegistry) -> None:
        assert registry.allocate_pin_id() == "PIN-0001"
        assert registry.allocate_pin_id() == "PIN-0002"
        assert registry.allocate_pin_id() == "PIN-0003"

    def test_allocation_after_registration(self, registry: PinRegistry) -> None:
        registry.register_pin(_make_pin("PIN-0005", "a1", "s1"))
        assert registry.allocate_pin_id() == "PIN-0006"


class TestPinPersistence:
    """Save and load roundtrip."""

    def test_save_and_load(self, layout: BranchLayout) -> None:
        reg = PinRegistry(layout)
        reg.register_pin(_make_pin("PIN-0001", "a1", "s1", ProjectionType.PASS_THROUGH))
        reg.register_pin(_make_pin("PIN-0002", "a2", "s2", ProjectionType.AGGREGATION))
        reg.save()

        loaded = PinRegistry.load(layout)
        assert loaded.get_pin("PIN-0001") is not None
        assert loaded.get_pin("PIN-0002") is not None
        assert loaded.get_pin("PIN-0001").projection_type == ProjectionType.PASS_THROUGH
        assert loaded.get_pin("PIN-0002").projection_type == ProjectionType.AGGREGATION

    def test_load_empty(self, layout: BranchLayout) -> None:
        loaded = PinRegistry.load(layout)
        assert loaded.list_all() == []

    def test_pin_number_preserved(self, layout: BranchLayout) -> None:
        reg = PinRegistry(layout)
        reg.register_pin(_make_pin("PIN-0010", "a1", "s1"))
        reg.save()

        loaded = PinRegistry.load(layout)
        assert loaded.allocate_pin_id() == "PIN-0011"


class TestDriftReportSerialization:
    """DriftReport to_dict/from_dict roundtrip."""

    def test_roundtrip(self) -> None:
        dr = DriftReport(
            pin_id="PIN-0001",
            atom_id="a1",
            drift_type="atom_changed",
            architectural_location="services/s1",
            projection_type=ProjectionType.PASS_THROUGH,
            details="hash changed",
        )
        data = dr.to_dict()
        restored = DriftReport.from_dict(data)
        assert restored.pin_id == dr.pin_id
        assert restored.drift_type == dr.drift_type
        assert restored.projection_type == dr.projection_type
