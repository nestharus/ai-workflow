# Phase 3 Implementation Plan: Evidence Ranges and Evidence Graph with 100% Accounting Gates

## Overview

Phase 3 introduces **evidence ranges** (EVID-*) as the canonical bridge between spans/sections and atoms. It also creates an **evidence graph** artifact that captures the relationship topology (atoms -> ranges -> sections) and enforces **full atom accounting** as a hard gate per INV-ACC-0101.

## Design References

- `01_EVIDENCE_LAYER.md`: DS-EVID-0003 (EvidenceRange), DS-EVID-0004 (EvidenceGraph), ALG-EVID-0002 (BuildEvidenceRangesFromSpans)
- `02_PROVENANCE_AND_MEMBERSHIP.md`: DS-PROV-0005 (CoverageReport), ALG-PROV-0002 (UpdateCoverageReport), ALG-PROV-0003 (VerifyCoverageOrEmitGap)
- `13_STRUCTURE_AND_DECOMPOSITION.md`: DS-STRUCT-0001 (SectionSpan) with atom_ids field
- `03_ACCURACY_INVARIANTS.md`: INV-ACC-0101 (atom accounting completeness), INV-ACC-0003 (evidence range integrity)

## Current State Analysis

### Section Spans (schemas/sections.py)
```python
class SectionSpan(BaseModel):
    section_id: str
    start_line: int
    end_line: int
    label: str
```
**Problem**: Sections only track line numbers, not atom_ids. This creates a gap between sections and the atom layer established in Phase 2.

### Atom Emission (atom_emitter.py)
```python
atom_payload = {
    "atom_id": atom_id,
    ...
    "section_id": section_id,
    ...
}
```
**Problem**: Atoms reference section_id but there's no reverse index (section -> atom_ids) or evidence range artifact.

### Coverage Tracking (coverage.py)
The existing CoverageTracker tracks byte-level spans in fragments but doesn't integrate with the atom-level accounting required by INV-ACC-0101.

### Units (provenance.py)
```python
class TrackedUnit:
    source: SourceLocation  # file, line_start, line_end
    source_atom_ids: list[str] = field(default_factory=list)
```
**Partial**: `source_atom_ids` exists but is not populated during decomposition.

---

## Work Items

### WI-1: Evidence Range Data Structure and Schema

**Goal**: Implement DS-EVID-0003 (EvidenceRange) as the canonical bridge between atoms and sections.

**New File**: `scripts/spec_manager/spec_manager/schemas/evidence_ranges.py`

```python
from pydantic import BaseModel, Field, model_validator
import re

EVIDENCE_ID_PATTERN = re.compile(
    r"^EVID-(?P<file_uid>F\d{4})-(?P<rev_id>R\d{4})-L(?P<start>\d+)-L(?P<end>\d+)$"
)

class EvidenceRange(BaseModel):
    """A contiguous range of atoms bridging spans to sections (DS-EVID-0003)."""

    evidence_id: str  # EVID-{file_uid}-{rev_id}-L{start}-L{end}
    file_uid: str
    rev_id: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    atom_ids: list[str]  # All atom IDs in this range
    section_id: str | None = None  # Associated section
    label: str | None = None
    content_sha256: str | None = None
    tags: set[str] = Field(default_factory=set)

    @model_validator(mode="after")
    def validate_evidence_id(self) -> "EvidenceRange":
        """Validate evidence_id format and consistency."""
        match = EVIDENCE_ID_PATTERN.fullmatch(self.evidence_id)
        if not match:
            raise ValueError("evidence_id must match EVID-{file_uid}-{rev_id}-L{start}-L{end}")
        if match.group("file_uid") != self.file_uid:
            raise ValueError("evidence_id file_uid must match file_uid field")
        if match.group("rev_id") != self.rev_id:
            raise ValueError("evidence_id rev_id must match rev_id field")
        return self

    @model_validator(mode="after")
    def validate_line_range(self) -> "EvidenceRange":
        """Ensure end_line >= start_line."""
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        return self

    @model_validator(mode="after")
    def validate_atom_ids_count(self) -> "EvidenceRange":
        """Ensure atom_ids count matches line range."""
        expected = self.end_line - self.start_line + 1
        if len(self.atom_ids) != expected:
            raise ValueError(f"atom_ids count ({len(self.atom_ids)}) must match line range ({expected})")
        return self
```

**ID Format**: `EVID-{file_uid}-{rev_id}-L{start}-L{end}` (deterministic, span-addressed)

---

### WI-2: Evidence Range Builder (ALG-EVID-0002)

**Goal**: Build evidence ranges from section spans with 100% coverage verification.

**New File**: `scripts/spec_manager/spec_manager/refinement/workflows/evidence_builder.py`

```python
from spec_manager.schemas.evidence_ranges import EvidenceRange
from spec_manager.schemas.sections import SectionSpan, FileSections
from spec_manager.schemas.atoms import LineAtom

def build_evidence_ranges_from_spans(
    file_uid: str,
    rev_id: str,
    atoms: list[LineAtom],
    sections: FileSections,
) -> tuple[list[EvidenceRange], list[str]]:
    """ALG-EVID-0002: Build evidence ranges from section spans.

    Returns:
        Tuple of (evidence_ranges, uncovered_atom_ids)
    """
    evidence_ranges = []
    atom_by_line = {a.line_no: a for a in atoms}
    all_atom_ids = {a.atom_id for a in atoms}
    covered_atom_ids = set()

    for span in sections.sections:
        evidence_id = f"EVID-{file_uid}-{rev_id}-L{span.start_line}-L{span.end_line}"

        span_atom_ids = []
        for line_no in range(span.start_line, span.end_line + 1):
            if line_no in atom_by_line:
                atom = atom_by_line[line_no]
                span_atom_ids.append(atom.atom_id)
                covered_atom_ids.add(atom.atom_id)

        evidence_ranges.append(EvidenceRange(
            evidence_id=evidence_id,
            file_uid=file_uid,
            rev_id=rev_id,
            start_line=span.start_line,
            end_line=span.end_line,
            atom_ids=span_atom_ids,
            section_id=span.section_id,
            label=span.label,
        ))

    uncovered = list(all_atom_ids - covered_atom_ids)
    return evidence_ranges, uncovered


def create_unknown_span_for_uncovered(
    file_uid: str,
    rev_id: str,
    uncovered_atoms: list[LineAtom],
) -> EvidenceRange | None:
    """Create UNKNOWN span for uncovered atoms (fallback per CON-0009)."""
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
```

---

### WI-3: Evidence Graph Data Structure

**Goal**: Implement DS-EVID-0004 (EvidenceGraph) with nodes and edges.

**New File**: `scripts/spec_manager/spec_manager/schemas/evidence_graph.py`

```python
from enum import Enum
from pydantic import BaseModel, Field
from typing import Any

class NodeType(str, Enum):
    ATOM = "ATOM"
    EVIDENCE_RANGE = "EVIDENCE_RANGE"
    SECTION = "SECTION"
    ENTITY = "ENTITY"
    DERIVED_ELEMENT = "DERIVED_ELEMENT"
    LIBRARY = "LIBRARY"
    TASK = "TASK"
    GAP = "GAP"

class EdgeType(str, Enum):
    SUPPORTS = "SUPPORTS"      # atom -> range, range -> section
    MENTIONS = "MENTIONS"
    DERIVES = "DERIVES"
    DEPENDS_ON = "DEPENDS_ON"
    RELATES_TO = "RELATES_TO"
    PATCHES = "PATCHES"

class EvidenceGraphNode(BaseModel):
    """A node in the evidence graph (DS-EVID-0005)."""
    node_id: str
    node_type: NodeType
    payload_ref: str | None = None  # Reference to full object
    metadata: dict[str, Any] = Field(default_factory=dict)

class EvidenceGraphEdge(BaseModel):
    """An edge in the evidence graph (DS-EVID-0006)."""
    edge_id: str
    from_node_id: str
    to_node_id: str
    edge_type: EdgeType
    evidence_atom_ids: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    method: str | None = None

class EvidenceGraph(BaseModel):
    """The evidence graph (DS-EVID-0004)."""
    nodes: dict[str, EvidenceGraphNode] = Field(default_factory=dict)
    edges: list[EvidenceGraphEdge] = Field(default_factory=list)

    def add_node(self, node: EvidenceGraphNode) -> None:
        """Add a node to the graph."""
        self.nodes[node.node_id] = node

    def add_edge(self, edge: EvidenceGraphEdge) -> None:
        """Add an edge to the graph."""
        self.edges.append(edge)

    def reindex_adjacency(self) -> None:
        """Rebuild adjacency indexes for queries."""
        pass  # Implementation in builder
```

---

### WI-4: Evidence Graph Builder (ALG-EVID-0003)

**Goal**: Build evidence graph incrementally from atoms, ranges, and sections.

**Add to**: `scripts/spec_manager/spec_manager/refinement/workflows/evidence_builder.py`

```python
def build_evidence_graph(
    atoms: list[LineAtom],
    evidence_ranges: list[EvidenceRange],
    sections: list[SectionSpan],
    prior_graph: EvidenceGraph | None = None,
) -> EvidenceGraph:
    """ALG-EVID-0003: Build evidence graph incrementally."""
    graph = prior_graph or EvidenceGraph()
    edge_counter = len(graph.edges)

    # Add atom nodes
    for atom in atoms:
        graph.add_node(EvidenceGraphNode(
            node_id=atom.atom_id,
            node_type=NodeType.ATOM,
            payload_ref=atom.atom_id,
        ))

    # Add evidence range nodes and atom->range edges
    for evr in evidence_ranges:
        graph.add_node(EvidenceGraphNode(
            node_id=evr.evidence_id,
            node_type=NodeType.EVIDENCE_RANGE,
            payload_ref=evr.evidence_id,
        ))

        # Edges: atom -> evidence_range
        for atom_id in evr.atom_ids:
            edge_counter += 1
            graph.add_edge(EvidenceGraphEdge(
                edge_id=f"EDGE-{edge_counter:06d}",
                from_node_id=atom_id,
                to_node_id=evr.evidence_id,
                edge_type=EdgeType.SUPPORTS,
            ))

    # Add section nodes and range->section edges
    for section in sections:
        section_node_id = section.section_id
        graph.add_node(EvidenceGraphNode(
            node_id=section_node_id,
            node_type=NodeType.SECTION,
            payload_ref=section.section_id,
        ))

        # Find evidence ranges for this section
        for evr in evidence_ranges:
            if evr.section_id == section.section_id:
                edge_counter += 1
                graph.add_edge(EvidenceGraphEdge(
                    edge_id=f"EDGE-{edge_counter:06d}",
                    from_node_id=evr.evidence_id,
                    to_node_id=section_node_id,
                    edge_type=EdgeType.SUPPORTS,
                ))

    graph.reindex_adjacency()
    return graph
```

---

### WI-5: Coverage Report with Hard Gate (INV-ACC-0101)

**Goal**: Coverage validator blocks promotion on non-100% coverage but produces valid fallback state (CON-0009).

**New File**: `scripts/spec_manager/spec_manager/compliance/coverage_gate.py`

```python
from dataclasses import dataclass, field
from spec_manager.core.gaps import GapElement, Severity, DetectorFinding

@dataclass
class CoverageReport:
    """Coverage report per DS-PROV-0005."""
    file_uid: str
    rev_id: str
    total_atoms: int
    mapped_atoms: int
    remainder_atoms: int
    excluded_atoms: int
    unaccounted_atom_ids: list[str] = field(default_factory=list)

    @property
    def coverage_ratio(self) -> float:
        if self.total_atoms == 0:
            return 1.0
        return self.mapped_atoms / self.total_atoms

    @property
    def is_complete(self) -> bool:
        return len(self.unaccounted_atom_ids) == 0

@dataclass
class CoverageGateResult:
    """Result of coverage gate check."""
    passed: bool
    coverage_report: CoverageReport
    gap_element: GapElement | None = None
    fallback_state_valid: bool = True

def verify_coverage_or_emit_gap(
    coverage_report: CoverageReport,
    run_id: str,
) -> CoverageGateResult:
    """ALG-PROV-0003: Verify 100% coverage or emit gap.

    Per CON-0009: Non-100% coverage blocks promotion but produces
    valid fallback state.
    """
    if coverage_report.is_complete and coverage_report.coverage_ratio == 1.0:
        return CoverageGateResult(
            passed=True,
            coverage_report=coverage_report,
        )

    # Emit GAP(COVERAGE) element
    gap = GapElement(
        id=f"GAP-COVERAGE-{coverage_report.file_uid}-{run_id}",
        severity=Severity.ERROR,
        summary=f"Incomplete atom coverage: {coverage_report.coverage_ratio:.1%}",
        affects=[coverage_report.file_uid],
        evidence=[DetectorFinding(
            severity=Severity.ERROR,
            message=f"{len(coverage_report.unaccounted_atom_ids)} atoms unaccounted",
            location=f"{coverage_report.file_uid}:{coverage_report.rev_id}",
            detector="coverage_gate",
            details={
                "unaccounted_atoms": coverage_report.unaccounted_atom_ids[:20],
                "total_unaccounted": len(coverage_report.unaccounted_atom_ids),
            },
        )],
    )

    return CoverageGateResult(
        passed=False,
        coverage_report=coverage_report,
        gap_element=gap,
        fallback_state_valid=True,  # CON-0009: fallback is valid
    )
```

---

### WI-6: Update SectionSpan to Include atom_ids

**Goal**: Per DS-STRUCT-0001, sections track their atom_ids directly.

**Modify**: `scripts/spec_manager/spec_manager/schemas/sections.py`

```python
class SectionSpan(BaseModel):
    """Represents a contiguous line range belonging to a logical section."""

    section_id: str
    file_uid: str | None = None       # NEW
    rev_id: str | None = None         # NEW
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    label: str
    atom_ids: list[str] = Field(default_factory=list)  # NEW
    span_type: str | None = None      # NEW: BLOCK, LIST, TABLE, etc.
    confidence: float = 1.0           # NEW
```

---

### WI-7: Update TrackedUnit to Require atom_ids

**Goal**: Units reference atom_ids (with rev ids), not just line numbers.

**Modify**: `scripts/spec_manager/spec_manager/core/provenance.py`

Add validation to ensure `source_atom_ids` is populated:

```python
def validate_unit_has_atom_ids(unit: TrackedUnit) -> list[str]:
    """Validate that a unit has source_atom_ids populated (Phase 3 requirement)."""
    errors = []
    if not unit.source_atom_ids:
        errors.append(f"Unit {unit.id} missing source_atom_ids")
    return errors
```

---

## Output Artifacts

### evidence_ranges.json (per file or global)

```json
{
  "schema_version": "1.0",
  "file_uid": "F0001",
  "rev_id": "R0001",
  "ranges": [
    {
      "evidence_id": "EVID-F0001-R0001-L1-L25",
      "file_uid": "F0001",
      "rev_id": "R0001",
      "start_line": 1,
      "end_line": 25,
      "atom_ids": ["ATOM-F0001-R0001-L0001", "..."],
      "section_id": "SEC-F0001-0001",
      "label": "Introduction"
    }
  ],
  "uncovered_atoms": []
}
```

### evidence_graph.json

```json
{
  "schema_version": "1.0",
  "nodes": {
    "ATOM-F0001-R0001-L0001": {
      "node_id": "ATOM-F0001-R0001-L0001",
      "node_type": "ATOM",
      "payload_ref": "ATOM-F0001-R0001-L0001"
    },
    "EVID-F0001-R0001-L1-L25": {
      "node_id": "EVID-F0001-R0001-L1-L25",
      "node_type": "EVIDENCE_RANGE",
      "payload_ref": "EVID-F0001-R0001-L1-L25"
    }
  },
  "edges": [
    {
      "edge_id": "EDGE-000001",
      "from_node_id": "ATOM-F0001-R0001-L0001",
      "to_node_id": "EVID-F0001-R0001-L1-L25",
      "edge_type": "SUPPORTS"
    }
  ]
}
```

### coverage_report.json (per phase)

```json
{
  "schema_version": "1.0",
  "run_id": "run_001",
  "phase": "sectionization",
  "files": [
    {
      "file_uid": "F0001",
      "rev_id": "R0001",
      "total_atoms": 150,
      "mapped_atoms": 150,
      "remainder_atoms": 0,
      "excluded_atoms": 0,
      "unaccounted_atom_ids": [],
      "coverage_complete": true
    }
  ],
  "gate_passed": true
}
```

---

## File Changes Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `schemas/evidence_ranges.py` | NEW | EvidenceRange model (DS-EVID-0003) |
| `schemas/evidence_graph.py` | NEW | EvidenceGraph, Node, Edge models (DS-EVID-0004/5/6) |
| `refinement/workflows/evidence_builder.py` | NEW | ALG-EVID-0002, ALG-EVID-0003 implementation |
| `compliance/coverage_gate.py` | NEW | CoverageReport, coverage gate (ALG-PROV-0003) |
| `schemas/sections.py` | MODIFY | Add atom_ids, file_uid, rev_id to SectionSpan |
| `core/provenance.py` | MODIFY | Add validation for source_atom_ids |
| `refinement/workflows/atom_emitter.py` | MODIFY | Return evidence_ranges alongside atoms |

---

## Test Plan

### Unit Tests

1. **test_evidence_ranges.py**
   - `test_evidence_range_id_format` - EVID-F0001-R0001-L1-L25 validates
   - `test_evidence_range_atom_ids_count_matches_lines` - Validation enforced
   - `test_evidence_range_serialization_roundtrip`

2. **test_evidence_graph.py**
   - `test_add_node_and_edge` - Basic graph operations
   - `test_reindex_adjacency` - Indexes built correctly
   - `test_graph_serialization_roundtrip`

3. **test_evidence_builder.py**
   - `test_build_evidence_ranges_covers_all_atoms` - 100% coverage
   - `test_build_evidence_ranges_detects_uncovered` - Uncovered atoms listed
   - `test_create_unknown_span_for_uncovered` - Fallback span created
   - `test_build_evidence_graph_has_all_nodes` - Atoms, ranges, sections

4. **test_coverage_gate.py**
   - `test_gate_passes_on_complete_coverage`
   - `test_gate_fails_on_incomplete_coverage`
   - `test_gap_element_emitted_on_failure`
   - `test_fallback_state_valid_on_failure` - CON-0009 compliance

### Integration Tests

1. **test_phase3_workflow.py**
   - Full workflow: atoms -> evidence ranges -> graph -> coverage report
   - Verify artifacts written correctly
   - Verify gate blocks promotion when coverage incomplete

---

## Implementation Sequence

1. **Step 1**: Create `schemas/evidence_ranges.py` with EvidenceRange model
2. **Step 2**: Create `schemas/evidence_graph.py` with graph models
3. **Step 3**: Create `refinement/workflows/evidence_builder.py` with builders
4. **Step 4**: Create `compliance/coverage_gate.py` with coverage verification
5. **Step 5**: Update `schemas/sections.py` to include atom_ids
6. **Step 6**: Update `atom_emitter.py` to produce evidence_ranges alongside atoms
7. **Step 7**: Update `provenance.py` to validate source_atom_ids
8. **Step 8**: Write unit tests for all new modules
9. **Step 9**: Write integration test for full workflow

---

## Constraints Addressed

| Constraint | Implementation |
|------------|----------------|
| INV-ACC-0101 | 100% atom accounting enforced by coverage gate |
| INV-ACC-0003 | Evidence ranges validated as contiguous atom slices |
| CON-0009 | Non-100% coverage produces valid fallback state |
| CON-0008 | Evidence IDs deterministic (span-addressed) |
