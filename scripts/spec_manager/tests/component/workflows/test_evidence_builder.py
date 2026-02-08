"""Tests for evidence range and graph builders (ALG-EVID-0002, ALG-EVID-0003).

Tests:
- test_build_evidence_ranges_covers_all_atoms: 100% coverage case
- test_build_evidence_ranges_detects_uncovered: Uncovered atoms listed
- test_create_unknown_span_for_uncovered: Fallback span created
- test_build_evidence_graph_has_all_nodes: Atoms, ranges, sections present
"""

from spec_manager.refinement.workflows.evidence_builder import (
    build_evidence_graph,
    build_evidence_ranges_from_spans,
    create_unknown_span_for_uncovered,
)
from spec_manager.schemas.atoms import LineAtom
from spec_manager.schemas.evidence_graph import EdgeType, NodeType
from spec_manager.schemas.sections import FileSections, SectionSpan


def make_atom(file_uid: str, rev_id: str, line_no: int, section_id: str = "") -> LineAtom:
    """Helper to create a LineAtom for testing."""
    return LineAtom(
        atom_id=f"ATOM-{file_uid}-{rev_id}-L{line_no:04d}",
        atom_fingerprint="a" * 64,
        file_uid=file_uid,
        rev_id=rev_id,
        line_no=line_no,
        sequence_index=line_no - 1,
        section_id=section_id,
        sha256="b" * 64,
        text=f"Line {line_no} content",
    )


class TestBuildEvidenceRangesFromSpans:
    """Test build_evidence_ranges_from_spans function."""

    def test_build_evidence_ranges_covers_all_atoms(self) -> None:
        """Test 100% coverage: all atoms mapped to sections."""
        file_uid = "F0001"
        rev_id = "R0001"

        # Create atoms for 5 lines
        atoms = [make_atom(file_uid, rev_id, i, f"SEC-{(i - 1) // 3 + 1:03d}") for i in range(1, 6)]

        # Create sections covering all lines
        sections = FileSections(
            file_id=file_uid,
            sections=[
                SectionSpan(section_id="SEC-001", start_line=1, end_line=3, label="Section 1"),
                SectionSpan(section_id="SEC-002", start_line=4, end_line=5, label="Section 2"),
            ],
            total_lines=5,
        )

        evidence_ranges, uncovered = build_evidence_ranges_from_spans(
            file_uid, rev_id, atoms, sections
        )

        assert len(evidence_ranges) == 2
        assert len(uncovered) == 0

        # Check first range
        evr1 = evidence_ranges[0]
        assert evr1.evidence_id == "EVID-F0001-R0001-L1-L3"
        assert evr1.section_id == "SEC-001"
        assert len(evr1.atom_ids) == 3

        # Check second range
        evr2 = evidence_ranges[1]
        assert evr2.evidence_id == "EVID-F0001-R0001-L4-L5"
        assert evr2.section_id == "SEC-002"
        assert len(evr2.atom_ids) == 2

    def test_build_evidence_ranges_detects_uncovered(self) -> None:
        """Test detection of uncovered atoms."""
        file_uid = "F0001"
        rev_id = "R0001"

        # Create atoms for 5 lines
        atoms = [make_atom(file_uid, rev_id, i) for i in range(1, 6)]

        # Create section covering only lines 2-4
        sections = FileSections(
            file_id=file_uid,
            sections=[
                SectionSpan(section_id="SEC-001", start_line=2, end_line=4, label="Section 1"),
            ],
            total_lines=5,
        )

        evidence_ranges, uncovered = build_evidence_ranges_from_spans(
            file_uid, rev_id, atoms, sections
        )

        assert len(evidence_ranges) == 1
        assert len(uncovered) == 2

        # Lines 1 and 5 are uncovered
        uncovered_set = set(uncovered)
        assert "ATOM-F0001-R0001-L0001" in uncovered_set
        assert "ATOM-F0001-R0001-L0005" in uncovered_set

    def test_build_evidence_ranges_with_gaps_in_sections(self) -> None:
        """Test with non-contiguous sections (gap between sections)."""
        file_uid = "F0001"
        rev_id = "R0001"

        # Create atoms for 10 lines
        atoms = [make_atom(file_uid, rev_id, i) for i in range(1, 11)]

        # Create sections with a gap (lines 4-6 not covered)
        sections = FileSections(
            file_id=file_uid,
            sections=[
                SectionSpan(section_id="SEC-001", start_line=1, end_line=3, label="Section 1"),
                SectionSpan(section_id="SEC-002", start_line=7, end_line=10, label="Section 2"),
            ],
            total_lines=10,
        )

        evidence_ranges, uncovered = build_evidence_ranges_from_spans(
            file_uid, rev_id, atoms, sections
        )

        assert len(evidence_ranges) == 2
        assert len(uncovered) == 3  # Lines 4, 5, 6

        uncovered_set = set(uncovered)
        assert "ATOM-F0001-R0001-L0004" in uncovered_set
        assert "ATOM-F0001-R0001-L0005" in uncovered_set
        assert "ATOM-F0001-R0001-L0006" in uncovered_set


class TestCreateUnknownSpanForUncovered:
    """Test create_unknown_span_for_uncovered function."""

    def test_create_unknown_span_for_uncovered(self) -> None:
        """Test creating fallback UNKNOWN span."""
        file_uid = "F0001"
        rev_id = "R0001"

        uncovered_atoms = [
            make_atom(file_uid, rev_id, 4),
            make_atom(file_uid, rev_id, 5),
            make_atom(file_uid, rev_id, 6),
        ]

        unknown_span = create_unknown_span_for_uncovered(file_uid, rev_id, uncovered_atoms)

        assert unknown_span is not None
        assert unknown_span.evidence_id == "EVID-F0001-R0001-L4-L6"
        assert unknown_span.start_line == 4
        assert unknown_span.end_line == 6
        assert len(unknown_span.atom_ids) == 3
        assert unknown_span.section_id is None
        assert unknown_span.label == "UNKNOWN"
        assert "remainder" in unknown_span.tags
        assert "GAP(COVERAGE)" in unknown_span.tags

    def test_create_unknown_span_returns_none_for_empty(self) -> None:
        """Test returns None when no uncovered atoms."""
        result = create_unknown_span_for_uncovered("F0001", "R0001", [])
        assert result is None

    def test_create_unknown_span_contiguous_atoms(self) -> None:
        """Test with contiguous uncovered atoms (possibly out of order input)."""
        file_uid = "F0001"
        rev_id = "R0001"

        # Contiguous lines 5, 6, 7 passed in shuffled order
        uncovered_atoms = [
            make_atom(file_uid, rev_id, 7),
            make_atom(file_uid, rev_id, 5),
            make_atom(file_uid, rev_id, 6),
        ]

        unknown_span = create_unknown_span_for_uncovered(file_uid, rev_id, uncovered_atoms)

        assert unknown_span is not None
        # Should use min/max line numbers
        assert unknown_span.start_line == 5
        assert unknown_span.end_line == 7
        # Atom IDs should be in sorted order
        assert len(unknown_span.atom_ids) == 3


class TestBuildEvidenceGraph:
    """Test build_evidence_graph function."""

    def test_build_evidence_graph_has_all_nodes(self) -> None:
        """Test graph contains all atoms, ranges, and sections."""
        file_uid = "F0001"
        rev_id = "R0001"

        # Create atoms
        atoms = [make_atom(file_uid, rev_id, i, "SEC-001") for i in range(1, 4)]

        # Create sections
        section_spans = [
            SectionSpan(section_id="SEC-001", start_line=1, end_line=3, label="Section 1"),
        ]

        sections = FileSections(
            file_id=file_uid,
            sections=section_spans,
            total_lines=3,
        )

        # Build evidence ranges
        evidence_ranges, _ = build_evidence_ranges_from_spans(file_uid, rev_id, atoms, sections)

        # Build graph
        graph = build_evidence_graph(atoms, evidence_ranges, section_spans)

        # Verify all atom nodes exist
        atom_nodes = graph.get_nodes_by_type(NodeType.ATOM)
        assert len(atom_nodes) == 3

        # Verify evidence range node exists
        range_nodes = graph.get_nodes_by_type(NodeType.EVIDENCE_RANGE)
        assert len(range_nodes) == 1
        assert range_nodes[0].node_id == "EVID-F0001-R0001-L1-L3"

        # Verify section node exists
        section_nodes = graph.get_nodes_by_type(NodeType.SECTION)
        assert len(section_nodes) == 1
        assert section_nodes[0].node_id == "SEC-001"

    def test_build_evidence_graph_has_correct_edges(self) -> None:
        """Test graph has correct atom->range and range->section edges."""
        file_uid = "F0001"
        rev_id = "R0001"

        atoms = [make_atom(file_uid, rev_id, i, "SEC-001") for i in range(1, 3)]

        section_spans = [
            SectionSpan(section_id="SEC-001", start_line=1, end_line=2, label="Section 1"),
        ]

        sections = FileSections(
            file_id=file_uid,
            sections=section_spans,
            total_lines=2,
        )

        evidence_ranges, _ = build_evidence_ranges_from_spans(file_uid, rev_id, atoms, sections)
        graph = build_evidence_graph(atoms, evidence_ranges, section_spans)

        # Should have 2 atom->range edges + 1 range->section edge = 3 edges
        assert len(graph.edges) == 3

        # Check all edges are SUPPORTS type
        for edge in graph.edges:
            assert edge.edge_type == EdgeType.SUPPORTS

        # Verify adjacency after reindex
        range_edges = graph.get_outgoing_edges("EVID-F0001-R0001-L1-L2")
        assert len(range_edges) == 1
        assert range_edges[0].to_node_id == "SEC-001"

    def test_build_evidence_graph_incremental(self) -> None:
        """Test incremental graph building with prior graph."""
        file_uid = "F0001"
        rev_id = "R0001"

        # Build initial graph with 2 atoms
        atoms1 = [make_atom(file_uid, rev_id, i, "SEC-001") for i in range(1, 3)]
        section_spans1 = [
            SectionSpan(section_id="SEC-001", start_line=1, end_line=2, label="Section 1"),
        ]
        sections1 = FileSections(file_id=file_uid, sections=section_spans1, total_lines=2)
        evidence_ranges1, _ = build_evidence_ranges_from_spans(file_uid, rev_id, atoms1, sections1)
        build_evidence_graph(atoms1, evidence_ranges1, section_spans1)

        # Extend with more atoms
        atoms2 = [make_atom(file_uid, rev_id, i, "SEC-002") for i in range(3, 5)]
        section_spans2 = [
            SectionSpan(section_id="SEC-002", start_line=3, end_line=4, label="Section 2"),
        ]
        sections2 = FileSections(file_id=file_uid, sections=section_spans2, total_lines=2)
        evidence_ranges2, _ = build_evidence_ranges_from_spans(file_uid, rev_id, atoms2, sections2)

        # Build incrementally on prior graph (note: graph1 is modified in place)
        graph2 = build_evidence_graph(atoms2, evidence_ranges2, section_spans2, prior_graph=graph1)

        # Since prior_graph is same reference, graph2 IS graph1 after modification
        # Combined graph: 4 atoms + 2 ranges + 2 sections = 8 nodes
        # Combined edges: 4 atom->range + 2 range->section = 6 edges
        assert len(graph2.nodes) == 8
        assert len(graph2.edges) == 6

        # Verify nodes from both builds are present
        assert "ATOM-F0001-R0001-L0001" in graph2.nodes
        assert "ATOM-F0001-R0001-L0003" in graph2.nodes
        assert "SEC-001" in graph2.nodes
        assert "SEC-002" in graph2.nodes

    def test_build_evidence_graph_multiple_sections(self) -> None:
        """Test graph with multiple sections."""
        file_uid = "F0001"
        rev_id = "R0001"

        atoms = [make_atom(file_uid, rev_id, i) for i in range(1, 7)]

        section_spans = [
            SectionSpan(section_id="SEC-001", start_line=1, end_line=3, label="Section 1"),
            SectionSpan(section_id="SEC-002", start_line=4, end_line=6, label="Section 2"),
        ]

        sections = FileSections(
            file_id=file_uid,
            sections=section_spans,
            total_lines=6,
        )

        evidence_ranges, _ = build_evidence_ranges_from_spans(file_uid, rev_id, atoms, sections)
        graph = build_evidence_graph(atoms, evidence_ranges, section_spans)

        # 6 atoms + 2 ranges + 2 sections = 10 nodes
        assert len(graph.nodes) == 10

        # 6 atom->range + 2 range->section = 8 edges
        assert len(graph.edges) == 8

        # Verify section nodes
        section_nodes = graph.get_nodes_by_type(NodeType.SECTION)
        assert len(section_nodes) == 2
