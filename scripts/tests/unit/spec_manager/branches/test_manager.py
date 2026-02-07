"""Tests for BranchManager facade: lifecycle, integration, and delegation."""

from __future__ import annotations

from pathlib import Path

import pytest

from spec_manager.branches.downward_flow import ArchitecturalIssue
from spec_manager.branches.manager import BranchManager
from spec_manager.branches.types import (
    AtomDescriptor,
    AtomKind,
    PinProjection,
    ProjectionType,
)


@pytest.fixture
def manager(tmp_path: Path) -> BranchManager:
    return BranchManager(run_root=tmp_path)


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


class TestLifecycle:
    """Tests for initialize and is_initialized."""

    def test_not_initialized_initially(self, manager: BranchManager) -> None:
        assert manager.is_initialized() is False

    def test_initialize_creates_dirs(self, manager: BranchManager) -> None:
        issues = manager.initialize()
        assert issues == []
        assert manager.is_initialized() is True

    def test_initialize_idempotent(self, manager: BranchManager) -> None:
        manager.initialize()
        manager.initialize()
        assert manager.is_initialized() is True

    def test_initialize_force(self, manager: BranchManager) -> None:
        manager.initialize()
        issues = manager.initialize(force=True)
        assert issues == []


class TestAtomManagement:
    """Tests for atom registration and lookup via facade."""

    def test_register_and_get(self, manager: BranchManager) -> None:
        manager.initialize()
        atom = _make_atom("a1")
        manager.register_atom(atom)
        assert manager.get_atom("a1") is atom

    def test_get_nonexistent(self, manager: BranchManager) -> None:
        manager.initialize()
        assert manager.get_atom("nonexistent") is None

    def test_list_atoms_all(self, manager: BranchManager) -> None:
        manager.initialize()
        manager.register_atom(_make_atom("a1"))
        manager.register_atom(_make_atom("a2"))
        assert len(manager.list_atoms()) == 2

    def test_list_atoms_by_kind(self, manager: BranchManager) -> None:
        manager.initialize()
        manager.register_atom(_make_atom("algo1", AtomKind.ALGORITHM))
        manager.register_atom(_make_atom("store1", AtomKind.STORE))
        assert len(manager.list_atoms(AtomKind.ALGORITHM)) == 1
        assert len(manager.list_atoms(AtomKind.STORE)) == 1
        assert len(manager.list_atoms(AtomKind.SHAPE)) == 0


class TestPinManagement:
    """Tests for pin registration and tracing via facade."""

    def test_register_and_trace_forward(self, manager: BranchManager) -> None:
        manager.initialize()
        manager.register_atom(_make_atom("a1"))
        pin = PinProjection(
            pin_id="PIN-0001",
            atom_id="a1",
            architectural_location="services/s1",
            projection_type=ProjectionType.PASS_THROUGH,
        )
        manager.register_pin(pin)
        locations = manager.trace_forward("a1")
        assert len(locations) == 1

    def test_trace_backward(self, manager: BranchManager) -> None:
        manager.initialize()
        pin = PinProjection(
            pin_id="PIN-0001",
            atom_id="a1",
            architectural_location="services/s1",
            projection_type=ProjectionType.PASS_THROUGH,
        )
        manager.register_pin(pin)
        found = manager.trace_backward("services/s1")
        assert found is not None
        assert found.atom_id == "a1"


class TestPromotion:
    """Tests for promotion via facade."""

    def test_promote_with_skip(self, manager: BranchManager) -> None:
        manager.initialize()
        manager.register_atom(_make_atom("a1"))
        result = manager.promote(atom_ids=["a1"], skip_compliance=True)
        assert result.success is True
        assert result.promoted_atoms == ["a1"]


class TestDownwardFlow:
    """Tests for issue tracing via facade."""

    def test_trace_issue(self, manager: BranchManager) -> None:
        manager.initialize()
        manager.register_atom(_make_atom("a1"))
        manager.register_pin(PinProjection(
            pin_id="PIN-0001",
            atom_id="a1",
            architectural_location="services/s1",
            projection_type=ProjectionType.PASS_THROUGH,
        ))

        issue = ArchitecturalIssue(
            issue_id="I1",
            location="services/s1",
            description="Failed",
        )
        result = manager.trace_issue(issue)
        assert result.confidence == 1.0
        assert len(result.traced_atoms) == 1


class TestCollapse:
    """Tests for codebase collapse via facade."""

    def test_collapse(self, manager: BranchManager, tmp_path: Path) -> None:
        manager.initialize()
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "utils.py").write_text(
            "def helper(x: int) -> int:\n    return x * 2\n",
            encoding="utf-8",
        )
        result = manager.collapse_codebase(src_dir)
        total = (
            len(result.extracted_atoms)
            + len(result.extracted_stores)
            + len(result.extracted_shapes)
        )
        assert total >= 1


class TestAnalysis:
    """Tests for analysis regeneration via facade."""

    def test_regenerate_analysis(self, manager: BranchManager) -> None:
        manager.initialize()
        manager.register_atom(_make_atom("a1"))
        report = manager.regenerate_analysis()
        assert len(report.atoms) == 1
        # Check that files were written
        analysis_dir = manager.layout.analysis_dir()
        assert (analysis_dir / "lineage_table.json").exists()
        assert (analysis_dir / "adjacency_graph.json").exists()
        assert (analysis_dir / "drift_report.md").exists()


class TestNavigation:
    """Tests for navigation via facade."""

    def test_navigate_down(self, manager: BranchManager) -> None:
        manager.initialize()
        manager.register_atom(_make_atom("a1"))
        desc = manager.navigate_down("a1")
        assert desc.atom_id == "a1"

    def test_navigate_up(self, manager: BranchManager) -> None:
        manager.initialize()
        manager.register_atom(_make_atom("a1"))
        manager.register_pin(PinProjection(
            pin_id="PIN-0001",
            atom_id="a1",
            architectural_location="services/s1",
            projection_type=ProjectionType.PASS_THROUGH,
        ))
        pins = manager.navigate_up("a1")
        assert len(pins) == 1

    def test_navigate_across(self, manager: BranchManager) -> None:
        manager.initialize()
        s1 = manager.create_slice("Payment")
        s2 = manager.create_slice("Order")
        siblings = manager.navigate_across(s1.slice_id)
        assert len(siblings) == 1
        assert siblings[0].slice_id == s2.slice_id


class TestSliceManagement:
    """Tests for slice management via facade."""

    def test_create_slice(self, manager: BranchManager) -> None:
        manager.initialize()
        vs = manager.create_slice("Payment")
        assert vs.name == "Payment"

    def test_create_child_slice(self, manager: BranchManager) -> None:
        manager.initialize()
        parent = manager.create_slice("Payment")
        child = manager.create_slice("Validation", parent=parent.slice_id)
        assert child.parent_slice_id == parent.slice_id

    def test_validate_store_monogamy(self, manager: BranchManager) -> None:
        manager.initialize()
        assert manager.validate_store_monogamy() == []


class TestPersistence:
    """Tests for save and load."""

    def test_save_and_load(self, tmp_path: Path) -> None:
        mgr = BranchManager(run_root=tmp_path)
        mgr.initialize()
        mgr.register_atom(_make_atom("a1"))
        mgr.register_pin(PinProjection(
            pin_id="PIN-0001",
            atom_id="a1",
            architectural_location="services/s1",
            projection_type=ProjectionType.PASS_THROUGH,
        ))
        mgr.create_slice("Payment")
        mgr.save()

        # Create new manager and load
        mgr2 = BranchManager(run_root=tmp_path)
        mgr2.load()
        assert mgr2.get_atom("a1") is not None
        assert mgr2.trace_backward("services/s1") is not None
        assert len(mgr2.slice_navigator.list_root_slices()) == 1


class TestFullLifecycle:
    """Integration test: initialize -> register -> promote -> trace -> analyze."""

    def test_full_lifecycle(self, manager: BranchManager) -> None:
        # Step 1: Initialize
        manager.initialize()

        # Step 2: Register atoms
        manager.register_atom(_make_atom("validate_payment"))
        manager.register_atom(_make_atom("apply_discount"))
        manager.register_atom(_make_atom("order_store", AtomKind.STORE))

        # Step 3: Create slices
        payment = manager.create_slice("Payment")
        manager.slice_navigator.add_atom_to_slice(payment.slice_id, "validate_payment")
        manager.slice_navigator.add_atom_to_slice(payment.slice_id, "apply_discount")
        manager.slice_navigator.add_store_to_slice(payment.slice_id, "order_store")

        # Step 4: Promote (skip compliance for test)
        result = manager.promote(
            atom_ids=["validate_payment", "apply_discount"],
            skip_compliance=True,
        )
        assert result.success is True
        assert len(result.promoted_atoms) == 2

        # Step 5: Trace an issue
        issue = ArchitecturalIssue(
            issue_id="I1",
            location=f"services/validate_payment",
            description="Validation failure",
        )
        trace = manager.trace_issue(issue)
        assert trace.confidence > 0

        # Step 6: Regenerate analysis
        report = manager.regenerate_analysis()
        assert len(report.atoms) == 3

        # Step 7: Validate monogamy
        violations = manager.validate_store_monogamy()
        assert violations == []

        # Step 8: Save and load
        manager.save()
        manager.load()
        assert manager.get_atom("validate_payment") is not None
