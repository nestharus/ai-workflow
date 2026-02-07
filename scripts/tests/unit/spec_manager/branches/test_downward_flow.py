"""Tests for DownwardFlowEngine: tracing issues back to atoms."""

from __future__ import annotations

from pathlib import Path

import pytest

from spec_manager.branches.atoms import AtomRegistry
from spec_manager.branches.downward_flow import (
    ArchitecturalIssue,
    DownwardFlowEngine,
    DownwardTraceResult,
)
from spec_manager.branches.layout import BranchLayout
from spec_manager.branches.pins import PinRegistry
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
) -> DownwardFlowEngine:
    return DownwardFlowEngine(layout, atom_registry, pin_registry)


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


def _make_pin(
    pin_id: str,
    atom_id: str,
    location: str,
    projection: ProjectionType = ProjectionType.PASS_THROUGH,
) -> PinProjection:
    return PinProjection(
        pin_id=pin_id,
        atom_id=atom_id,
        architectural_location=location,
        projection_type=projection,
    )


class TestTraceIssue:
    """Tests for tracing architectural issues back to atoms."""

    def test_exact_location_match(
        self,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
        engine: DownwardFlowEngine,
    ) -> None:
        atom_registry.register(_make_atom("validate_payment"))
        pin_registry.register_pin(
            _make_pin("PIN-0001", "validate_payment", "services/payment:validate")
        )

        issue = ArchitecturalIssue(
            issue_id="ISSUE-001",
            location="services/payment:validate",
            description="Payment validation failed",
        )
        result = engine.trace_issue(issue)
        assert result.confidence == 1.0
        assert len(result.traced_pins) == 1
        assert len(result.traced_atoms) == 1
        assert result.traced_atoms[0].atom_id == "validate_payment"
        assert result.suggested_fix_location == "atoms/validate_payment.py"

    def test_prefix_match(
        self,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
        engine: DownwardFlowEngine,
    ) -> None:
        atom_registry.register(_make_atom("process_order"))
        pin_registry.register_pin(
            _make_pin("PIN-0001", "process_order", "services/order")
        )

        issue = ArchitecturalIssue(
            issue_id="ISSUE-002",
            location="services/order:OrderService.process",
            description="Order processing failed",
        )
        result = engine.trace_issue(issue)
        assert result.confidence == 0.7
        assert len(result.traced_pins) == 1

    def test_no_match(self, engine: DownwardFlowEngine) -> None:
        issue = ArchitecturalIssue(
            issue_id="ISSUE-003",
            location="unknown/location",
            description="Unknown failure",
        )
        result = engine.trace_issue(issue)
        assert result.confidence == 0.0
        assert result.traced_pins == []
        assert result.traced_atoms == []
        assert result.suggested_fix_location is None

    def test_trace_through_wrapping_pin(
        self,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
        engine: DownwardFlowEngine,
    ) -> None:
        atom_registry.register(_make_atom("calc_discount"))
        pin_registry.register_pin(
            _make_pin(
                "PIN-0001", "calc_discount", "middleware/discount_wrapper",
                ProjectionType.SLICE,
            )
        )

        issue = ArchitecturalIssue(
            issue_id="ISSUE-004",
            location="middleware/discount_wrapper",
            description="Discount calculation wrong",
        )
        result = engine.trace_issue(issue)
        assert len(result.traced_atoms) == 1
        assert result.traced_atoms[0].atom_id == "calc_discount"

    def test_trace_through_aggregation_pin(
        self,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
        engine: DownwardFlowEngine,
    ) -> None:
        atom_registry.register(_make_atom("step_a"))
        atom_registry.register(_make_atom("step_b"))
        pin_registry.register_pin(
            _make_pin("PIN-0001", "step_a", "services/aggregated", ProjectionType.AGGREGATION)
        )
        pin_registry.register_pin(
            _make_pin("PIN-0002", "step_b", "services/aggregated", ProjectionType.AGGREGATION)
        )

        issue = ArchitecturalIssue(
            issue_id="ISSUE-005",
            location="services/aggregated",
            description="Aggregated service failed",
        )
        result = engine.trace_issue(issue)
        assert len(result.traced_atoms) == 2


class TestVerifyFix:
    """Tests for verify_fix after an atom change."""

    def test_verify_existing_atom(
        self,
        layout: BranchLayout,
        atom_registry: AtomRegistry,
        engine: DownwardFlowEngine,
    ) -> None:
        atom_registry.register(_make_atom("a1"))
        # Create the atom file
        atom_file = layout.atoms_dir / "a1.py"
        atom_file.write_text("def a1(): return 42", encoding="utf-8")

        result = engine.verify_fix("a1")
        assert result["algorithmic"] is True
        assert result["architectural"] is True  # No pins = trivially valid

    def test_verify_nonexistent_atom(self, engine: DownwardFlowEngine) -> None:
        result = engine.verify_fix("nonexistent")
        assert result["algorithmic"] is False


class TestArchitecturalIssueSerialization:
    """Tests for ArchitecturalIssue serialization."""

    def test_roundtrip(self) -> None:
        original = ArchitecturalIssue(
            issue_id="ISSUE-001",
            location="services/payment:validate",
            description="Failed",
            test_name="test_payment",
            stack_trace="traceback...",
        )
        data = original.to_dict()
        restored = ArchitecturalIssue.from_dict(data)
        assert restored.issue_id == original.issue_id
        assert restored.location == original.location
        assert restored.test_name == original.test_name
        assert restored.stack_trace == original.stack_trace


class TestDownwardTraceResultSerialization:
    """Tests for DownwardTraceResult serialization."""

    def test_roundtrip(self) -> None:
        original = DownwardTraceResult(
            issue=ArchitecturalIssue(
                issue_id="I1", location="loc", description="desc",
            ),
            traced_pins=[PinProjection(
                pin_id="PIN-0001", atom_id="a1",
                architectural_location="loc",
                projection_type=ProjectionType.PASS_THROUGH,
            )],
            traced_atoms=[_make_atom("a1")],
            confidence=1.0,
            suggested_fix_location="atoms/a1.py",
        )
        data = original.to_dict()
        restored = DownwardTraceResult.from_dict(data)
        assert restored.confidence == original.confidence
        assert restored.suggested_fix_location == original.suggested_fix_location
        assert len(restored.traced_pins) == 1
        assert len(restored.traced_atoms) == 1
