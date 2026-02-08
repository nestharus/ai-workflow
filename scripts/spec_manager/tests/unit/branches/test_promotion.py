"""Tests for PromotionEngine: promotion with/without compliance."""

from __future__ import annotations

from pathlib import Path

import pytest
from spec_manager.branches.atoms import AtomRegistry
from spec_manager.branches.layout import BranchLayout
from spec_manager.branches.pins import PinRegistry
from spec_manager.branches.promotion import PromotionEngine, PromotionResult
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
def atom_registry(layout: BranchLayout) -> AtomRegistry:
    return AtomRegistry(layout)


@pytest.fixture
def pin_registry(layout: BranchLayout) -> PinRegistry:
    return PinRegistry(layout)


@pytest.fixture
def engine(
    layout: BranchLayout,
    atom_registry: AtomRegistry,
    pin_registry: PinRegistry,
) -> PromotionEngine:
    return PromotionEngine(layout, atom_registry, pin_registry)


def _make_atom(atom_id: str) -> AtomDescriptor:
    return AtomDescriptor(
        atom_id=atom_id,
        kind=AtomKind.ALGORITHM,
        file_path=f"{atom_id}.py",
        function_name=atom_id,
        signature="()",
        content_hash="h" + atom_id,
        introduced_by="plan-1",
    )


class TestPromotionWithSkippedCompliance:
    """Tests for promotion with skip_compliance=True."""

    def test_promotes_new_atoms(
        self,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
        engine: PromotionEngine,
    ) -> None:
        atom_registry.register(_make_atom("a1"))
        atom_registry.register(_make_atom("a2"))

        result = engine.promote(atom_ids=["a1", "a2"], skip_compliance=True)
        assert result.success is True
        assert sorted(result.promoted_atoms) == ["a1", "a2"]
        assert len(result.pin_ids_created) == 2

    def test_skips_already_projected(
        self,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
        engine: PromotionEngine,
    ) -> None:
        atom_registry.register(_make_atom("a1"))
        # Pre-register a pin for a1
        pin_registry.register_pin(
            PinProjection(
                pin_id="PIN-0001",
                atom_id="a1",
                architectural_location="services/a1",
                projection_type=ProjectionType.PASS_THROUGH,
            )
        )

        result = engine.promote(atom_ids=["a1"], skip_compliance=True)
        assert result.success is True
        assert result.promoted_atoms == []
        assert result.skipped_atoms == ["a1"]

    def test_errors_for_missing_atom(
        self,
        engine: PromotionEngine,
    ) -> None:
        result = engine.promote(atom_ids=["nonexistent"], skip_compliance=True)
        assert result.success is False
        assert any("not found" in e for e in result.errors)

    def test_auto_identifies_changed_atoms(
        self,
        atom_registry: AtomRegistry,
        engine: PromotionEngine,
    ) -> None:
        atom_registry.register(_make_atom("a1"))
        atom_registry.register(_make_atom("a2"))

        result = engine.promote(skip_compliance=True)
        assert result.success is True
        assert sorted(result.promoted_atoms) == ["a1", "a2"]


class TestPromotionWithCompliance:
    """Tests for promotion with compliance gating."""

    def test_blocked_by_compliance(
        self,
        layout: BranchLayout,
        atom_registry: AtomRegistry,
        engine: PromotionEngine,
    ) -> None:
        # Create a file with comments to fail compliance
        atoms_dir = layout.algorithmic_dir() / "atoms"
        atoms_dir.mkdir(parents=True, exist_ok=True)
        (atoms_dir / "a1.py").write_text(
            "def a1():\n    # todo\n    return 1\n",
            encoding="utf-8",
        )
        atom_registry.register(_make_atom("a1"))

        result = engine.promote(atom_ids=["a1"], skip_compliance=False)
        assert result.success is False
        assert result.compliance_result is not None
        assert result.compliance_result.passed is False
        assert result.promoted_atoms == []

    def test_passes_compliance_on_clean_code(
        self,
        layout: BranchLayout,
        atom_registry: AtomRegistry,
        engine: PromotionEngine,
    ) -> None:
        # No algorithmic files = clean slate
        atom_registry.register(_make_atom("a1"))

        result = engine.promote(atom_ids=["a1"], skip_compliance=False)
        assert result.success is True
        assert result.promoted_atoms == ["a1"]


class TestPromotionResultSerialization:
    """Tests for PromotionResult serialization."""

    def test_roundtrip(self) -> None:
        original = PromotionResult(
            success=True,
            promoted_atoms=["a1", "a2"],
            skipped_atoms=["a3"],
            compliance_result=None,
            pin_ids_created=["PIN-0001", "PIN-0002"],
            errors=[],
        )
        data = original.to_dict()
        restored = PromotionResult.from_dict(data)
        assert restored.success == original.success
        assert restored.promoted_atoms == original.promoted_atoms
        assert restored.pin_ids_created == original.pin_ids_created
