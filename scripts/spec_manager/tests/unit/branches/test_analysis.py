"""Tests for AnalysisGenerator: computed analysis branch generation."""

from __future__ import annotations

from pathlib import Path

import pytest
from spec_manager.branches.analysis import (
    AnalysisArtifact,
    AnalysisGenerator,
    AnalysisReport,
)
from spec_manager.branches.atoms import AtomRegistry
from spec_manager.branches.layout import BranchLayout
from spec_manager.branches.pins import PinRegistry
from spec_manager.branches.slices import SliceNavigator
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
def slice_navigator(
    layout: BranchLayout,
    atom_registry: AtomRegistry,
    pin_registry: PinRegistry,
) -> SliceNavigator:
    return SliceNavigator(layout, atom_registry, pin_registry)


@pytest.fixture
def generator(
    layout: BranchLayout,
    atom_registry: AtomRegistry,
    pin_registry: PinRegistry,
    slice_navigator: SliceNavigator,
) -> AnalysisGenerator:
    return AnalysisGenerator(layout, atom_registry, pin_registry, slice_navigator)


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


class TestGenerate:
    """Tests for full analysis generation."""

    def test_empty_registry(self, generator: AnalysisGenerator) -> None:
        report = generator.generate()
        assert report.atoms == []
        assert report.disconnected_subgraphs == []
        assert report.store_touch_edges == []

    def test_single_atom_unprojected(
        self,
        atom_registry: AtomRegistry,
        generator: AnalysisGenerator,
    ) -> None:
        atom_registry.register(_make_atom("a1"))
        report = generator.generate()
        assert len(report.atoms) == 1
        assert report.atoms[0].unprojected is True

    def test_single_atom_projected(
        self,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
        generator: AnalysisGenerator,
    ) -> None:
        atom_registry.register(_make_atom("a1"))
        pin_registry.register_pin(
            PinProjection(
                pin_id="PIN-0001",
                atom_id="a1",
                architectural_location="services/s1",
                projection_type=ProjectionType.PASS_THROUGH,
            )
        )
        report = generator.generate()
        assert len(report.atoms) == 1
        assert report.atoms[0].unprojected is False
        assert "PIN-0001" in report.atoms[0].projection_types

    def test_multiple_atoms_adjacency(
        self,
        atom_registry: AtomRegistry,
        slice_navigator: SliceNavigator,
        generator: AnalysisGenerator,
    ) -> None:
        atom_registry.register(_make_atom("a1"))
        atom_registry.register(_make_atom("a2"))

        vs = slice_navigator.create_slice("Payment")
        slice_navigator.add_atom_to_slice(vs.slice_id, "a1")
        slice_navigator.add_atom_to_slice(vs.slice_id, "a2")

        report = generator.generate()
        a1_artifact = next(a for a in report.atoms if a.atom_id == "a1")
        assert "a2" in a1_artifact.adjacencies

    def test_disconnected_subgraphs(
        self,
        atom_registry: AtomRegistry,
        slice_navigator: SliceNavigator,
        generator: AnalysisGenerator,
    ) -> None:
        atom_registry.register(_make_atom("a1"))
        atom_registry.register(_make_atom("a2"))

        s1 = slice_navigator.create_slice("S1")
        s2 = slice_navigator.create_slice("S2")
        slice_navigator.add_atom_to_slice(s1.slice_id, "a1")
        slice_navigator.add_atom_to_slice(s2.slice_id, "a2")

        report = generator.generate()
        # Two disconnected atoms should form two subgraphs
        assert len(report.disconnected_subgraphs) == 2


class TestWriteArtifacts:
    """Tests for writing analysis files to disk."""

    def test_write_lineage_table(
        self,
        atom_registry: AtomRegistry,
        generator: AnalysisGenerator,
        layout: BranchLayout,
    ) -> None:
        atom_registry.register(_make_atom("a1"))
        report = generator.generate()
        path = generator.write_lineage_table(report)
        assert path.exists()
        assert path.name == "lineage_table.json"

    def test_write_adjacency_graph(
        self,
        atom_registry: AtomRegistry,
        generator: AnalysisGenerator,
        layout: BranchLayout,
    ) -> None:
        atom_registry.register(_make_atom("a1"))
        report = generator.generate()
        path = generator.write_adjacency_graph(report)
        assert path.exists()
        assert path.name == "adjacency_graph.json"

    def test_write_drift_report(
        self,
        atom_registry: AtomRegistry,
        generator: AnalysisGenerator,
        layout: BranchLayout,
    ) -> None:
        atom_registry.register(_make_atom("a1"))
        report = generator.generate()
        path = generator.write_drift_report(report)
        assert path.exists()
        assert path.name == "drift_report.md"
        content = path.read_text(encoding="utf-8")
        assert "Drift Report" in content

    def test_drift_report_shows_unprojected(
        self,
        atom_registry: AtomRegistry,
        generator: AnalysisGenerator,
    ) -> None:
        atom_registry.register(_make_atom("a1"))
        report = generator.generate()
        path = generator.write_drift_report(report)
        content = path.read_text(encoding="utf-8")
        assert "Unprojected Atoms" in content


class TestAnalysisReportSerialization:
    """Tests for AnalysisReport serialization."""

    def test_roundtrip(self) -> None:
        artifact = AnalysisArtifact(
            atom_id="a1",
            architectural_imports=[],
            projection_types={},
            adjacencies=["a2"],
            data_flow_in=[],
            data_flow_out=[],
            stores_touched=["s1"],
            unprojected=True,
        )
        original = AnalysisReport(
            generated_at="2024-01-01T00:00:00",
            atoms=[artifact],
            orphaned_architectural=["orphan1"],
            disconnected_subgraphs=[["a1"], ["a2"]],
            store_touch_edges=[("a1", "s1", "a2")],
        )
        data = original.to_dict()
        restored = AnalysisReport.from_dict(data)
        assert restored.generated_at == original.generated_at
        assert len(restored.atoms) == 1
        assert restored.atoms[0].atom_id == "a1"
        assert restored.disconnected_subgraphs == [["a1"], ["a2"]]
        assert restored.store_touch_edges == [("a1", "s1", "a2")]


class TestAnalysisArtifactSerialization:
    """Tests for AnalysisArtifact serialization."""

    def test_roundtrip(self) -> None:
        original = AnalysisArtifact(
            atom_id="a1",
            architectural_imports=[
                PinProjection(
                    pin_id="PIN-0001",
                    atom_id="a1",
                    architectural_location="services/s1",
                    projection_type=ProjectionType.PASS_THROUGH,
                )
            ],
            projection_types={"PIN-0001": ProjectionType.PASS_THROUGH},
            adjacencies=["a2", "a3"],
            data_flow_in=["signal_in"],
            data_flow_out=["signal_out"],
            stores_touched=["s1"],
            unprojected=False,
        )
        data = original.to_dict()
        restored = AnalysisArtifact.from_dict(data)
        assert restored.atom_id == "a1"
        assert len(restored.architectural_imports) == 1
        assert restored.projection_types["PIN-0001"] == ProjectionType.PASS_THROUGH
        assert restored.adjacencies == ["a2", "a3"]
        assert restored.unprojected is False
