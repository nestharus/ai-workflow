"""Evidence range and graph builders (ALG-EVID-0002, ALG-EVID-0003).

This module provides algorithms to:
1. Build evidence ranges from section spans with 100% coverage verification
2. Build evidence graphs incrementally from atoms, ranges, and sections
"""

from __future__ import annotations

from spec_manager.schemas.atoms import LineAtom
from spec_manager.schemas.evidence_graph import (
    EdgeType,
    EvidenceGraph,
    EvidenceGraphEdge,
    EvidenceGraphNode,
    NodeType,
)
from spec_manager.schemas.evidence_ranges import EvidenceRange
from spec_manager.schemas.sections import FileSections, SectionSpan


def build_evidence_ranges_from_spans(
    file_uid: str,
    rev_id: str,
    atoms: list[LineAtom],
    sections: FileSections,
) -> tuple[list[EvidenceRange], list[str]]:
    """ALG-EVID-0002: Build evidence ranges from section spans.

    Creates evidence ranges by mapping atoms to their containing sections.
    Returns both the evidence ranges and any uncovered atom IDs.

    Args:
        file_uid: File UID (F####)
        rev_id: Revision ID (R####)
        atoms: List of line atoms for the file
        sections: Section spans for the file

    Returns:
        Tuple of (evidence_ranges, uncovered_atom_ids)
    """
    evidence_ranges: list[EvidenceRange] = []
    atom_by_line: dict[int, LineAtom] = {a.line_no: a for a in atoms}
    all_atom_ids: set[str] = {a.atom_id for a in atoms}
    covered_atom_ids: set[str] = set()

    for span in sections.sections:
        evidence_id = f"EVID-{file_uid}-{rev_id}-L{span.start_line}-L{span.end_line}"

        span_atom_ids: list[str] = []
        for line_no in range(span.start_line, span.end_line + 1):
            if line_no in atom_by_line:
                atom = atom_by_line[line_no]
                span_atom_ids.append(atom.atom_id)
                covered_atom_ids.add(atom.atom_id)

        evidence_ranges.append(
            EvidenceRange(
                evidence_id=evidence_id,
                file_uid=file_uid,
                rev_id=rev_id,
                start_line=span.start_line,
                end_line=span.end_line,
                atom_ids=span_atom_ids,
                section_id=span.section_id,
                label=span.label,
            )
        )

    uncovered = list(all_atom_ids - covered_atom_ids)
    return evidence_ranges, uncovered


def create_unknown_span_for_uncovered(
    file_uid: str,
    rev_id: str,
    uncovered_atoms: list[LineAtom],
) -> EvidenceRange | None:
    """Create UNKNOWN span for uncovered atoms (fallback per CON-0009).

    When atoms are not covered by any section span, this function creates
    a fallback evidence range to maintain atom accounting.

    Args:
        file_uid: File UID (F####)
        rev_id: Revision ID (R####)
        uncovered_atoms: List of atoms not covered by section spans

    Returns:
        An EvidenceRange for the uncovered atoms, or None if no uncovered atoms
    """
    if not uncovered_atoms:
        return None

    sorted_atoms = sorted(uncovered_atoms, key=lambda a: a.line_no)
    start_line = sorted_atoms[0].line_no
    end_line = sorted_atoms[-1].line_no

    return EvidenceRange(
        evidence_id=f"EVID-{file_uid}-{rev_id}-L{start_line}-L{end_line}",
        file_uid=file_uid,
        rev_id=rev_id,
        start_line=start_line,
        end_line=end_line,
        atom_ids=[a.atom_id for a in sorted_atoms],
        section_id=None,
        label="UNKNOWN",
        tags={"remainder", "GAP(COVERAGE)"},
    )


def build_evidence_graph(
    atoms: list[LineAtom],
    evidence_ranges: list[EvidenceRange],
    sections: list[SectionSpan],
    prior_graph: EvidenceGraph | None = None,
) -> EvidenceGraph:
    """ALG-EVID-0003: Build evidence graph incrementally.

    Creates a graph with:
    - ATOM nodes for each line atom
    - EVIDENCE_RANGE nodes for each evidence range
    - SECTION nodes for each section span
    - SUPPORTS edges from atoms to ranges and ranges to sections

    Args:
        atoms: List of line atoms
        evidence_ranges: List of evidence ranges
        sections: List of section spans
        prior_graph: Optional prior graph to extend

    Returns:
        The built or extended evidence graph
    """
    graph = prior_graph or EvidenceGraph()
    edge_counter = len(graph.edges)

    # Add atom nodes
    for atom in atoms:
        graph.add_node(
            EvidenceGraphNode(
                node_id=atom.atom_id,
                node_type=NodeType.ATOM,
                payload_ref=atom.atom_id,
            )
        )

    # Add evidence range nodes and atom->range edges
    for evr in evidence_ranges:
        graph.add_node(
            EvidenceGraphNode(
                node_id=evr.evidence_id,
                node_type=NodeType.EVIDENCE_RANGE,
                payload_ref=evr.evidence_id,
            )
        )

        # Edges: atom -> evidence_range
        for atom_id in evr.atom_ids:
            edge_counter += 1
            graph.add_edge(
                EvidenceGraphEdge(
                    edge_id=f"EDGE-{edge_counter:06d}",
                    from_node_id=atom_id,
                    to_node_id=evr.evidence_id,
                    edge_type=EdgeType.SUPPORTS,
                )
            )

    # Add section nodes and range->section edges
    for section in sections:
        section_node_id = section.section_id
        graph.add_node(
            EvidenceGraphNode(
                node_id=section_node_id,
                node_type=NodeType.SECTION,
                payload_ref=section.section_id,
            )
        )

        # Find evidence ranges for this section
        for evr in evidence_ranges:
            if evr.section_id == section.section_id:
                edge_counter += 1
                graph.add_edge(
                    EvidenceGraphEdge(
                        edge_id=f"EDGE-{edge_counter:06d}",
                        from_node_id=evr.evidence_id,
                        to_node_id=section_node_id,
                        edge_type=EdgeType.SUPPORTS,
                    )
                )

    graph.reindex_adjacency()
    return graph
