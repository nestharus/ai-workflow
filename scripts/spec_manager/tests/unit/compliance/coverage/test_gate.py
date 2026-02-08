"""Tests for the entity coverage compliance gate."""

from __future__ import annotations

import tempfile
from pathlib import Path

from spec_manager.branches.atoms import AtomRegistry
from spec_manager.branches.layout import BranchLayout
from spec_manager.branches.types import AtomDescriptor, AtomKind
from spec_manager.compliance.coverage.gate import (
    build_entity_coverage_report,
    check_entity_coverage,
)
from spec_manager.compliance.promotion.config import GateId, GateMode, GateSpec
from spec_manager.refinement.hollowed_spec.indexer import EvidenceIndex
from spec_manager.schemas.entities import (
    EntitiesArtifact,
    Entity,
    EntityKind,
    EntityMention,
)


def _make_atom(atom_id: str, function_name: str) -> AtomDescriptor:
    return AtomDescriptor(
        atom_id=atom_id,
        kind=AtomKind.ALGORITHM,
        file_path=f"{function_name}.py",
        function_name=function_name,
        signature="() -> None",
        content_hash="abc123",
        introduced_by="test",
    )


def _make_registry(atoms: list[AtomDescriptor]) -> AtomRegistry:
    with tempfile.TemporaryDirectory() as tmpdir:
        layout = BranchLayout(run_root=Path(tmpdir))
        registry = AtomRegistry(layout)
        for atom in atoms:
            registry.register(atom)
        return registry


class TestCheckEntityCoverage:
    def test_passes_when_coverage_meets_threshold(self) -> None:
        artifact = EntitiesArtifact(
            entities=[
                Entity(entity_id="ENT-0001", name="Widget", kind=EntityKind.CONCEPT),
            ],
            mentions=[
                EntityMention(
                    entity_id="ENT-0001",
                    section_id="SEC-01",
                    atom_ids=["atom_widget"],
                ),
            ],
        )
        registry = _make_registry([_make_atom("atom_widget", "widget_handler")])
        index = EvidenceIndex()
        gate_spec = GateSpec(
            gate_id=GateId.ENTITY_COVERAGE,
            mode=GateMode.ADVISORY,
            threshold=0.5,
        )

        result = check_entity_coverage(index, registry, gate_spec, artifact)

        assert result.passed is True
        assert result.gate_id == GateId.ENTITY_COVERAGE.value
        assert result.score >= 0.5

    def test_fails_when_coverage_below_threshold(self) -> None:
        artifact = EntitiesArtifact(
            entities=[
                Entity(entity_id="ENT-0001", name="Widget", kind=EntityKind.CONCEPT),
                Entity(entity_id="ENT-0002", name="Gadget", kind=EntityKind.CONCEPT),
            ],
        )
        # No atoms match either entity
        registry = _make_registry([_make_atom("atom_unrelated", "something_else")])
        index = EvidenceIndex()
        gate_spec = GateSpec(
            gate_id=GateId.ENTITY_COVERAGE,
            mode=GateMode.ADVISORY,
            threshold=0.9,
        )

        result = check_entity_coverage(index, registry, gate_spec, artifact)

        assert result.passed is False
        assert result.score < 0.9

    def test_passes_with_zero_threshold(self) -> None:
        artifact = EntitiesArtifact(
            entities=[
                Entity(entity_id="ENT-0001", name="Orphan", kind=EntityKind.CONCEPT),
            ],
        )
        registry = _make_registry([_make_atom("atom_x", "unrelated_func")])
        index = EvidenceIndex()
        gate_spec = GateSpec(
            gate_id=GateId.ENTITY_COVERAGE,
            mode=GateMode.ADVISORY,
            threshold=0.0,
        )

        result = check_entity_coverage(index, registry, gate_spec, artifact)

        assert result.passed is True

    def test_findings_include_unmatched_entities(self) -> None:
        artifact = EntitiesArtifact(
            entities=[
                Entity(entity_id="ENT-0001", name="Orphan Entity", kind=EntityKind.CONCEPT),
            ],
        )
        registry = _make_registry([_make_atom("atom_x", "unrelated")])
        index = EvidenceIndex()
        gate_spec = GateSpec(
            gate_id=GateId.ENTITY_COVERAGE,
            mode=GateMode.ADVISORY,
            threshold=0.0,
        )

        result = check_entity_coverage(index, registry, gate_spec, artifact)

        entity_findings = [f for f in result.findings if f.get("type") == "unmatched_entity"]
        assert len(entity_findings) == 1
        assert entity_findings[0]["entity_id"] == "ENT-0001"

    def test_findings_include_unmatched_atoms(self) -> None:
        artifact = EntitiesArtifact(
            entities=[
                Entity(entity_id="ENT-0001", name="Widget", kind=EntityKind.CONCEPT),
            ],
            mentions=[
                EntityMention(
                    entity_id="ENT-0001",
                    section_id="SEC-01",
                    atom_ids=["atom_widget"],
                ),
            ],
        )
        registry = _make_registry(
            [
                _make_atom("atom_widget", "widget_handler"),
                _make_atom("atom_orphan", "orphan_function"),
            ]
        )
        index = EvidenceIndex()
        gate_spec = GateSpec(
            gate_id=GateId.ENTITY_COVERAGE,
            mode=GateMode.ADVISORY,
            threshold=0.0,
        )

        result = check_entity_coverage(index, registry, gate_spec, artifact)

        atom_findings = [f for f in result.findings if f.get("type") == "unmatched_atom"]
        assert any(f["atom_id"] == "atom_orphan" for f in atom_findings)

    def test_mode_propagated_to_result(self) -> None:
        artifact = EntitiesArtifact()
        registry = _make_registry([])
        index = EvidenceIndex()
        gate_spec = GateSpec(
            gate_id=GateId.ENTITY_COVERAGE,
            mode=GateMode.REQUIRED,
            threshold=0.0,
        )

        result = check_entity_coverage(index, registry, gate_spec, artifact)

        assert result.mode == GateMode.REQUIRED.value

    def test_duration_recorded(self) -> None:
        artifact = EntitiesArtifact()
        registry = _make_registry([])
        index = EvidenceIndex()
        gate_spec = GateSpec(
            gate_id=GateId.ENTITY_COVERAGE,
            mode=GateMode.ADVISORY,
            threshold=0.0,
        )

        result = check_entity_coverage(index, registry, gate_spec, artifact)

        assert result.duration_ms >= 0.0


class TestBuildEntityCoverageReport:
    def test_returns_report(self) -> None:
        artifact = EntitiesArtifact(
            entities=[
                Entity(entity_id="ENT-0001", name="Widget", kind=EntityKind.CONCEPT),
            ],
            mentions=[
                EntityMention(
                    entity_id="ENT-0001",
                    section_id="SEC-01",
                    atom_ids=["atom_widget"],
                ),
            ],
        )
        registry = _make_registry([_make_atom("atom_widget", "widget_handler")])
        index = EvidenceIndex()

        report = build_entity_coverage_report(index, registry, artifact)

        assert report.total_entities == 1
        assert report.total_atoms == 1
        assert len(report.matched) >= 1
