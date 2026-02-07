"""Schemas for algorithmic-to-architectural lineage edges."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from spec_manager.schemas.pin_functions import ProjectionType


class LineageEdge(BaseModel):
    """A directed edge from an algorithmic atom to an architectural location.

    Attributes:
        from_atom: Algorithmic atom ID (pin-function name or ATOM-* ID)
        to_location: Architectural location (file_path:class.method or file_path:function)
        transformation: How the atom was projected into architecture
        confidence: 1.0 for mechanical (import-based), <1.0 for inferred
        import_path: The Python import path if mechanically detected
        evidence: Optional textual evidence supporting this edge
    """

    from_atom: str
    to_location: str
    transformation: ProjectionType
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    import_path: str | None = None
    evidence: str | None = None


class AtomAdjacency(BaseModel):
    """Adjacency edges for an algorithmic atom.

    Attributes:
        atom_id: The atom identifier
        co_occurrence_edges: Atoms that co-occur in the same evidence window / section
        store_touch_edges: Atoms that read/write the same stores
    """

    atom_id: str
    co_occurrence_edges: list[str] = Field(default_factory=list)
    store_touch_edges: list[str] = Field(default_factory=list)


class DataFlowSummary(BaseModel):
    """Data flow summary for an atom.

    Attributes:
        atom_id: The atom identifier
        signals_in: Parameter names / types consumed
        signals_out: Return values / types produced
        stores_touched: Store identifiers read or written
    """

    atom_id: str
    signals_in: list[str] = Field(default_factory=list)
    signals_out: list[str] = Field(default_factory=list)
    stores_touched: list[str] = Field(default_factory=list)


class AtomAnalysisEntry(BaseModel):
    """Complete analysis entry for a single atom.

    Attributes:
        atom_id: The atom identifier (function name or ATOM-* ID)
        atom_file: File where the atom is defined
        forward_traces: All architectural locations importing this atom
        adjacency: Co-occurrence and store-touch edges
        data_flow: Signals in/out/stores touched
        is_unimplemented: True if atom has no architectural imports
    """

    atom_id: str
    atom_file: str
    forward_traces: list[LineageEdge] = Field(default_factory=list)
    adjacency: AtomAdjacency | None = None
    data_flow: DataFlowSummary | None = None
    is_unimplemented: bool = False


class OrphanedArchEntry(BaseModel):
    """An architectural location with no atom imports.

    Attributes:
        location: File path and function/class
        description: What the orphaned code appears to do
        suggested_action: Recommended remediation
    """

    location: str
    description: str = ""
    suggested_action: Literal[
        "create_atom",  # Should be an atom but was never extracted
        "mark_introduction",  # Legitimate architectural introduction
        "investigate",  # Unclear, needs manual review
    ] = "investigate"


class AnalysisFileSchema(BaseModel):
    """Top-level schema for the analysis file artifact.

    Attributes:
        run_id: The run that generated this analysis
        generated_at: ISO-8601 timestamp
        atoms: Per-atom analysis entries
        orphaned_architecture: Architectural code with no atom imports
        summary: Aggregate statistics
    """

    run_id: str
    generated_at: str
    atoms: list[AtomAnalysisEntry] = Field(default_factory=list)
    orphaned_architecture: list[OrphanedArchEntry] = Field(default_factory=list)
    summary: dict[str, int | float] = Field(default_factory=dict)
