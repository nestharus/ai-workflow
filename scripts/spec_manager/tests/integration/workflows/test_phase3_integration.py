"""Integration test for Phase 3 workflow: atoms -> evidence ranges -> graph -> coverage.

This test verifies the complete Phase 3 pipeline:
1. Emit atoms with evidence ranges
2. Build evidence graph
3. Generate and verify coverage report
4. Coverage gate blocks promotion on incomplete coverage
"""

import json
from pathlib import Path

from spec_manager.compliance.coverage_gate import (
    build_coverage_report,
    verify_coverage_or_emit_gap,
)
from spec_manager.refinement.workflows.atom_emitter import emit_atoms_with_evidence
from spec_manager.refinement.workflows.evidence_builder import build_evidence_graph
from spec_manager.schemas.evidence_graph import NodeType
from spec_manager.schemas.sections import FileSections, SectionSpan


class TestPhase3Integration:
    """Integration tests for Phase 3 workflow."""

    def test_full_workflow_complete_coverage(self, tmp_path: Path) -> None:
        """Test full workflow with 100% coverage."""
        # Create a test source file
        source_file = tmp_path / "test_spec.md"
        source_file.write_text(
            "# Introduction\n"
            "This is the introduction section.\n"
            "It has three lines.\n"
            "## Methods\n"
            "Methods are described here.\n"
        )

        file_uid = "F0001"
        rev_id = "R0001"

        # Create sections covering all 5 lines
        sections = FileSections(
            file_id=file_uid,
            sections=[
                SectionSpan(
                    section_id="SEC-001",
                    start_line=1,
                    end_line=3,
                    label="Introduction",
                ),
                SectionSpan(
                    section_id="SEC-002",
                    start_line=4,
                    end_line=5,
                    label="Methods",
                ),
            ],
            total_lines=5,
        )

        # Step 1: Emit atoms with evidence
        atoms_output = tmp_path / "atoms.jsonl"
        evidence_output = tmp_path / "evidence.jsonl"
        evidence_ranges_output = tmp_path / "evidence_ranges.json"

        result = emit_atoms_with_evidence(
            file_uid=file_uid,
            rev_id=rev_id,
            file_path=source_file,
            sections=sections,
            output_path=atoms_output,
            evidence_output=evidence_output,
            evidence_ranges_output=evidence_ranges_output,
        )

        # Verify atoms emitted
        assert result.atoms_emitted == 5
        assert len(result.atoms) == 5
        assert len(result.evidence_ranges) == 2
        assert len(result.uncovered_atom_ids) == 0

        # Verify evidence ranges artifact written
        assert evidence_ranges_output.exists()
        artifact_data = json.loads(evidence_ranges_output.read_text())
        assert artifact_data["file_uid"] == file_uid
        assert len(artifact_data["ranges"]) == 2
        assert len(artifact_data["uncovered_atoms"]) == 0

        # Step 2: Build evidence graph
        graph = build_evidence_graph(
            atoms=result.atoms,
            evidence_ranges=result.evidence_ranges,
            sections=sections.sections,
        )

        # Verify graph structure
        atom_nodes = graph.get_nodes_by_type(NodeType.ATOM)
        assert len(atom_nodes) == 5

        range_nodes = graph.get_nodes_by_type(NodeType.EVIDENCE_RANGE)
        assert len(range_nodes) == 2

        section_nodes = graph.get_nodes_by_type(NodeType.SECTION)
        assert len(section_nodes) == 2

        # 5 atom->range edges + 2 range->section edges = 7 edges
        assert len(graph.edges) == 7

        # Step 3: Build and verify coverage report
        all_atom_ids = {a.atom_id for a in result.atoms}
        mapped_atom_ids = set()
        for evr in result.evidence_ranges:
            if evr.section_id is not None:
                mapped_atom_ids.update(evr.atom_ids)

        coverage_report = build_coverage_report(
            file_uid=file_uid,
            rev_id=rev_id,
            total_atom_ids=all_atom_ids,
            mapped_atom_ids=mapped_atom_ids,
            remainder_atom_ids=set(),
        )

        assert coverage_report.total_atoms == 5
        assert coverage_report.mapped_atoms == 5
        assert coverage_report.is_complete
        assert coverage_report.coverage_ratio == 1.0

        # Step 4: Verify coverage gate passes
        gate_result = verify_coverage_or_emit_gap(coverage_report, "test_run")
        assert gate_result.passed
        assert gate_result.gap_element is None

    def test_full_workflow_incomplete_coverage(self, tmp_path: Path) -> None:
        """Test full workflow with incomplete coverage - gate should block."""
        # Create a test source file
        source_file = tmp_path / "test_spec.md"
        source_file.write_text(
            "# Introduction\n"
            "Intro content.\n"
            "More intro.\n"
            "Uncovered line 1.\n"
            "Uncovered line 2.\n"
            "## Methods\n"
            "Methods content.\n"
        )

        file_uid = "F0001"
        rev_id = "R0001"

        # Create sections with a gap (lines 4-5 not covered)
        sections = FileSections(
            file_id=file_uid,
            sections=[
                SectionSpan(
                    section_id="SEC-001",
                    start_line=1,
                    end_line=3,
                    label="Introduction",
                ),
                SectionSpan(
                    section_id="SEC-002",
                    start_line=6,
                    end_line=7,
                    label="Methods",
                ),
            ],
            total_lines=7,
        )

        # Emit atoms with evidence
        result = emit_atoms_with_evidence(
            file_uid=file_uid,
            rev_id=rev_id,
            file_path=source_file,
            sections=sections,
        )

        assert result.atoms_emitted == 7
        assert len(result.uncovered_atom_ids) == 2

        # Build coverage report
        all_atom_ids = {a.atom_id for a in result.atoms}
        mapped_atom_ids = set()
        for evr in result.evidence_ranges:
            if evr.section_id is not None:
                mapped_atom_ids.update(evr.atom_ids)

        coverage_report = build_coverage_report(
            file_uid=file_uid,
            rev_id=rev_id,
            total_atom_ids=all_atom_ids,
            mapped_atom_ids=mapped_atom_ids,
            remainder_atom_ids=set(),
        )

        assert coverage_report.total_atoms == 7
        assert coverage_report.mapped_atoms == 5
        assert not coverage_report.is_complete

        # Verify coverage gate FAILS
        gate_result = verify_coverage_or_emit_gap(coverage_report, "test_run")
        assert not gate_result.passed
        assert gate_result.gap_element is not None

        # But fallback state is still valid (CON-0009)
        assert gate_result.fallback_state_valid

        # Verify gap details
        gap = gate_result.gap_element
        assert "GAP-COVERAGE" in gap.id
        assert "F0001" in gap.affects

    def test_artifacts_are_json_serializable(self, tmp_path: Path) -> None:
        """Test all artifacts can be serialized to JSON."""
        source_file = tmp_path / "test.md"
        source_file.write_text("Line 1\nLine 2\n")

        file_uid = "F0001"
        rev_id = "R0001"

        sections = FileSections(
            file_id=file_uid,
            sections=[
                SectionSpan(section_id="SEC-001", start_line=1, end_line=2, label="Section"),
            ],
            total_lines=2,
        )

        result = emit_atoms_with_evidence(
            file_uid=file_uid,
            rev_id=rev_id,
            file_path=source_file,
            sections=sections,
        )

        graph = build_evidence_graph(
            atoms=result.atoms,
            evidence_ranges=result.evidence_ranges,
            sections=sections.sections,
        )

        # Test atoms JSON serialization
        for atom in result.atoms:
            json_str = json.dumps(atom.model_dump())
            assert json_str

        # Test evidence ranges JSON serialization
        for evr in result.evidence_ranges:
            # Use model_dump_json for proper set serialization
            json_str = evr.model_dump_json()
            assert json_str

        # Test graph JSON serialization
        graph_json = graph.model_dump_json()
        assert graph_json
        restored = json.loads(graph_json)
        assert "nodes" in restored
        assert "edges" in restored

    def test_evidence_graph_adjacency_queries(self, tmp_path: Path) -> None:
        """Test graph adjacency queries work correctly."""
        source_file = tmp_path / "test.md"
        source_file.write_text("Line 1\nLine 2\nLine 3\n")

        file_uid = "F0001"
        rev_id = "R0001"

        sections = FileSections(
            file_id=file_uid,
            sections=[
                SectionSpan(section_id="SEC-001", start_line=1, end_line=3, label="Section"),
            ],
            total_lines=3,
        )

        result = emit_atoms_with_evidence(
            file_uid=file_uid,
            rev_id=rev_id,
            file_path=source_file,
            sections=sections,
        )

        graph = build_evidence_graph(
            atoms=result.atoms,
            evidence_ranges=result.evidence_ranges,
            sections=sections.sections,
        )

        # Query outgoing edges from atom
        atom_id = result.atoms[0].atom_id
        outgoing = graph.get_outgoing_edges(atom_id)
        assert len(outgoing) == 1
        assert "EVID" in outgoing[0].to_node_id

        # Query incoming edges to section
        section_id = "SEC-001"
        incoming = graph.get_incoming_edges(section_id)
        assert len(incoming) == 1
        assert "EVID" in incoming[0].from_node_id

        # Query incoming edges to evidence range
        range_id = result.evidence_ranges[0].evidence_id
        incoming_to_range = graph.get_incoming_edges(range_id)
        assert len(incoming_to_range) == 3  # All 3 atoms


class TestPhase3EdgeCases:
    """Edge case tests for Phase 3."""

    def test_empty_file(self, tmp_path: Path) -> None:
        """Test handling of empty file."""
        source_file = tmp_path / "empty.md"
        source_file.write_text("")

        file_uid = "F0001"
        rev_id = "R0001"

        # Empty file needs empty sections (total_lines=0)
        sections = FileSections(
            file_id=file_uid,
            sections=[],
            total_lines=0,
        )

        result = emit_atoms_with_evidence(
            file_uid=file_uid,
            rev_id=rev_id,
            file_path=source_file,
            sections=sections,
        )

        assert result.atoms_emitted == 0
        assert len(result.atoms) == 0
        assert len(result.evidence_ranges) == 0

    def test_single_line_file(self, tmp_path: Path) -> None:
        """Test handling of single line file."""
        source_file = tmp_path / "single.md"
        source_file.write_text("Single line")

        file_uid = "F0001"
        rev_id = "R0001"

        sections = FileSections(
            file_id=file_uid,
            sections=[
                SectionSpan(section_id="SEC-001", start_line=1, end_line=1, label="Only"),
            ],
            total_lines=1,
        )

        result = emit_atoms_with_evidence(
            file_uid=file_uid,
            rev_id=rev_id,
            file_path=source_file,
            sections=sections,
        )

        assert result.atoms_emitted == 1
        assert len(result.evidence_ranges) == 1
        assert result.evidence_ranges[0].evidence_id == "EVID-F0001-R0001-L1-L1"

    def test_unicode_content(self, tmp_path: Path) -> None:
        """Test handling of unicode content."""
        source_file = tmp_path / "unicode.md"
        source_file.write_text("Hello World\nUnicode chars: ", encoding="utf-8")

        file_uid = "F0001"
        rev_id = "R0001"

        sections = FileSections(
            file_id=file_uid,
            sections=[
                SectionSpan(section_id="SEC-001", start_line=1, end_line=2, label="Unicode"),
            ],
            total_lines=2,
        )

        result = emit_atoms_with_evidence(
            file_uid=file_uid,
            rev_id=rev_id,
            file_path=source_file,
            sections=sections,
        )

        assert result.atoms_emitted == 2
        # Verify unicode preserved
        assert "" in result.atoms[1].text
