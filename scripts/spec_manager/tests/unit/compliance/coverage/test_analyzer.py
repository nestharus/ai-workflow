"""Tests for the EntityCoverageAnalyzer integration."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from spec_manager.branches.atoms import AtomRegistry
from spec_manager.branches.layout import BranchLayout
from spec_manager.branches.types import AtomDescriptor, AtomKind
from spec_manager.compliance.coverage.analyzer import EntityCoverageAnalyzer
from spec_manager.compliance.coverage.report import EntityCoverageReport
from spec_manager.core.evidence_index import EvidenceIndex
from spec_manager.schemas.entities import (
    EntitiesArtifact,
    Entity,
    EntityKind,
    EntityMention,
)
from spec_manager.schemas.hollowed_spec import (
    HollowedParagraph,
    HollowedSpec,
    ParagraphKind,
)


def _make_atom(
    atom_id: str,
    function_name: str,
    kind: AtomKind = AtomKind.ALGORITHM,
    vertical_slice: str | None = None,
) -> AtomDescriptor:
    return AtomDescriptor(
        atom_id=atom_id,
        kind=kind,
        file_path=f"{function_name}.py",
        function_name=function_name,
        signature="() -> None",
        content_hash="abc123",
        introduced_by="test",
        vertical_slice=vertical_slice,
    )


def _make_evidence_index(
    entity_entries: dict[str, list[tuple[str, str]]] | None = None,
    specs: dict[str, HollowedSpec] | None = None,
) -> EvidenceIndex:
    index = EvidenceIndex()
    if specs:
        for lib_id, spec in specs.items():
            index.specs[lib_id] = spec
    if entity_entries:
        index.global_entity_index = entity_entries
    return index


def _make_atom_registry(atoms: list[AtomDescriptor]) -> AtomRegistry:
    with tempfile.TemporaryDirectory() as tmpdir:
        layout = BranchLayout(run_root=Path(tmpdir))
        registry = AtomRegistry(layout)
        for atom in atoms:
            registry.register(atom)
        return registry


def _make_spec(lib_id: str, paragraphs: dict[str, HollowedParagraph]) -> HollowedSpec:
    return HollowedSpec(
        lib_id=lib_id,
        spec_hash="deadbeef",
        paragraphs=paragraphs,
    )


def _make_paragraph(
    para_id: str,
    keywords: list[str] | None = None,
    entity_refs: list[str] | None = None,
) -> HollowedParagraph:
    return HollowedParagraph(
        paragraph_id=para_id,
        section_path="Test.Section",
        kind=ParagraphKind.PROSE,
        text="Test paragraph",
        keywords=keywords or [],
        entity_refs=entity_refs or [],
        line_start=1,
        line_end=2,
    )


class TestEntityCoverageAnalyzer:
    def test_explicit_match_found(self) -> None:
        entities_artifact = EntitiesArtifact(
            entities=[
                Entity(entity_id="ENT-0001", name="PaymentProcessor", kind=EntityKind.COMPONENT),
            ],
            mentions=[
                EntityMention(
                    entity_id="ENT-0001",
                    section_id="SEC-01",
                    atom_ids=["atom_process_payment"],
                ),
            ],
        )
        atoms = [_make_atom("atom_process_payment", "process_payment")]
        registry = _make_atom_registry(atoms)
        index = _make_evidence_index()

        analyzer = EntityCoverageAnalyzer(index, registry, entities_artifact)
        report = analyzer.analyze()

        assert len(report.matched) >= 1
        explicit = [m for m in report.matched if m.match_method == "explicit"]
        assert len(explicit) == 1
        assert explicit[0].entity_id == "ENT-0001"
        assert explicit[0].atom_id == "atom_process_payment"

    def test_naming_heuristic_match(self) -> None:
        entities_artifact = EntitiesArtifact(
            entities=[
                Entity(entity_id="ENT-0001", name="calculate_total", kind=EntityKind.PROCESS),
            ],
        )
        atoms = [_make_atom("atom_calc_total", "calculate_total")]
        registry = _make_atom_registry(atoms)
        index = _make_evidence_index()

        analyzer = EntityCoverageAnalyzer(index, registry, entities_artifact)
        report = analyzer.analyze()

        assert len(report.matched) >= 1
        naming = [m for m in report.matched if m.match_method == "naming"]
        assert len(naming) >= 1

    def test_unmatched_entities_detected(self) -> None:
        entities_artifact = EntitiesArtifact(
            entities=[
                Entity(entity_id="ENT-0001", name="Orphan Entity", kind=EntityKind.CONCEPT),
            ],
        )
        atoms = [_make_atom("atom_unrelated", "something_else_entirely")]
        registry = _make_atom_registry(atoms)
        index = _make_evidence_index()

        analyzer = EntityCoverageAnalyzer(index, registry, entities_artifact)
        report = analyzer.analyze()

        assert len(report.unmatched_entities) == 1
        assert report.unmatched_entities[0].entity_id == "ENT-0001"
        assert report.unmatched_entities[0].name == "Orphan Entity"

    def test_unmatched_atoms_detected(self) -> None:
        entities_artifact = EntitiesArtifact(
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
        atoms = [
            _make_atom("atom_widget", "widget_handler"),
            _make_atom("atom_orphan", "completely_different_function"),
        ]
        registry = _make_atom_registry(atoms)
        index = _make_evidence_index()

        analyzer = EntityCoverageAnalyzer(index, registry, entities_artifact)
        report = analyzer.analyze()

        unmatched_atom_ids = {a.atom_id for a in report.unmatched_atoms}
        assert "atom_orphan" in unmatched_atom_ids

    def test_coverage_ratios_calculated(self) -> None:
        entities_artifact = EntitiesArtifact(
            entities=[
                Entity(entity_id="ENT-0001", name="Matched Entity", kind=EntityKind.CONCEPT),
                Entity(entity_id="ENT-0002", name="Unmatched Entity", kind=EntityKind.CONCEPT),
            ],
            mentions=[
                EntityMention(
                    entity_id="ENT-0001",
                    section_id="SEC-01",
                    atom_ids=["atom_matched"],
                ),
            ],
        )
        atoms = [
            _make_atom("atom_matched", "matched_function"),
            _make_atom("atom_orphan", "orphan_function"),
        ]
        registry = _make_atom_registry(atoms)
        index = _make_evidence_index()

        analyzer = EntityCoverageAnalyzer(index, registry, entities_artifact)
        report = analyzer.analyze()

        assert report.total_entities == 2
        assert report.total_atoms == 2
        assert report.entity_coverage == 0.5
        assert report.atom_coverage == 0.5

    def test_empty_inputs(self) -> None:
        entities_artifact = EntitiesArtifact()
        registry = _make_atom_registry([])
        index = _make_evidence_index()

        analyzer = EntityCoverageAnalyzer(index, registry, entities_artifact)
        report = analyzer.analyze()

        assert report.total_entities == 0
        assert report.total_atoms == 0
        assert report.entity_coverage == 1.0
        assert report.atom_coverage == 1.0
        assert report.matched == []
        assert report.unmatched_entities == []
        assert report.unmatched_atoms == []

    def test_no_entities_artifact_uses_evidence_index(self) -> None:
        para = _make_paragraph("p1", keywords=["auth", "token", "validate", "session"])
        spec = _make_spec("lib1", {"p1": para})
        index = _make_evidence_index(
            entity_entries={"AuthService": [("lib1", "p1")]},
            specs={"lib1": spec},
        )
        atoms = [_make_atom("atom_unrelated", "completely_different")]
        registry = _make_atom_registry(atoms)

        analyzer = EntityCoverageAnalyzer(index, registry, entities_artifact=None)
        report = analyzer.analyze()

        # AuthService should be unmatched
        assert report.total_entities == 1
        assert len(report.unmatched_entities) == 1
        assert report.unmatched_entities[0].name == "AuthService"

    def test_report_serialization(self) -> None:
        entities_artifact = EntitiesArtifact(
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
        atoms = [_make_atom("atom_widget", "widget_handler")]
        registry = _make_atom_registry(atoms)
        index = _make_evidence_index()

        analyzer = EntityCoverageAnalyzer(index, registry, entities_artifact)
        report = analyzer.analyze()

        d = report.to_dict()
        assert "matched" in d
        assert "unmatched_entities" in d
        assert "unmatched_atoms" in d
        assert "entity_coverage" in d
        assert "atom_coverage" in d

        # Verify JSON-serializable
        serialized = json.dumps(d)
        deserialized = json.loads(serialized)
        assert isinstance(deserialized["entity_coverage"], float)

    def test_report_save(self) -> None:
        report = EntityCoverageReport(
            entity_coverage=0.75,
            atom_coverage=0.5,
            total_entities=4,
            total_atoms=2,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sub" / "report.json"
            report.save(path)
            assert path.exists()
            loaded = json.loads(path.read_text(encoding="utf-8"))
            assert loaded["entity_coverage"] == 0.75
            assert loaded["total_entities"] == 4
