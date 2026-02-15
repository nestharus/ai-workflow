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


class CallRelationshipFact(BaseModel):
    """A call relationship declared by LLM relationship analysis.

    Attributes:
        caller_pin: Source pin/function node initiating the call
        callee_pin: Destination pin/function node receiving the call
        confidence: Confidence score for the relationship
        evidence_pin: Optional pin that anchors the evidence for this call
    """

    caller_pin: str
    callee_pin: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_pin: str | None = None


class EventRelationshipFact(BaseModel):
    """An event flow relationship declared by LLM relationship analysis.

    Attributes:
        emitter_pin: Pin/function that emits the event
        event_id: Stable event identifier
        consumer_pin: Optional pin/function that consumes the event
    """

    emitter_pin: str
    event_id: str
    consumer_pin: str | None = None


class StoreRelationshipFact(BaseModel):
    """A store access relationship declared by LLM relationship analysis.

    Attributes:
        pin: Pin/function touching the store
        store_id: Stable store identifier
        access_type: Access mode for the store touch
    """

    pin: str
    store_id: str
    access_type: Literal["read", "write", "read_write"] = "read_write"


class RelationshipFacts(BaseModel):
    """Unified LLM relationship payload used for graph construction.

    Replaces independent mechanical extractors with one authoritative schema.
    """

    calls: list[CallRelationshipFact] = Field(default_factory=list)
    events: list[EventRelationshipFact] = Field(default_factory=list)
    stores: list[StoreRelationshipFact] = Field(default_factory=list)


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
        relationship_facts: Declared call/event/store relationships for this atom
        data_flow: Signals in/out/stores touched
        is_unimplemented: True if atom has no architectural imports
    """

    atom_id: str
    atom_file: str
    forward_traces: list[LineageEdge] = Field(default_factory=list)
    relationship_facts: RelationshipFacts | None = None
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
