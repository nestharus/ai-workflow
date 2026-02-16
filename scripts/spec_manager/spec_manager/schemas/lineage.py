"""Schemas for algorithmic-to-architectural lineage edges."""

from __future__ import annotations

from typing import Any, Literal

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


class ReferenceRelationshipFact(BaseModel):
    """A reference relationship declared by LLM relationship analysis.

    Attributes:
        referrer_pin: Source pin/function that references another symbol
        referenced_id: Destination symbol or pin/function being referenced
        confidence: Confidence score for the relationship
        evidence_pin: Optional pin that anchors evidence for this relationship
    """

    referrer_pin: str
    referenced_id: str
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
    references: list[ReferenceRelationshipFact] = Field(default_factory=list)
    events: list[EventRelationshipFact] = Field(default_factory=list)
    stores: list[StoreRelationshipFact] = Field(default_factory=list)

    @staticmethod
    def _canonical_signal(value: Any) -> Literal["CALL", "REFERENCE", "STORE_TOUCH", "EVENT"]:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("signal_type must be a non-empty string")
        signal = value.strip().upper()
        if signal in {"CALL", "CALLS"}:
            return "CALL"
        if signal in {"STORE_TOUCH", "AGGREGATION"}:
            return "STORE_TOUCH"
        if signal in {"EVENT", "EVENT_EMIT", "EVENT_HANDLE"}:
            return "EVENT"
        if signal in {"REFERENCE", "REFERENCES"}:
            return "REFERENCE"
        raise ValueError(f"unsupported signal_type '{value}'")

    @staticmethod
    def _parse_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            raise ValueError("confidence must be numeric") from None
        if confidence < 0.0 or confidence > 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return confidence

    @staticmethod
    def _extract_id(edge: dict[str, Any], keys: tuple[str, ...], *, field_name: str) -> str:
        for key in keys:
            if key not in edge:
                continue
            raw = edge.get(key)
            if raw is None:
                continue
            if not isinstance(raw, str):
                raise TypeError(f"{field_name} from '{key}' must be a string")
            parsed = raw.strip()
            if parsed:
                return parsed
        raise ValueError(f"{field_name} is required")

    @classmethod
    def from_edge_records(cls, edge_records: list[dict[str, Any]]) -> RelationshipFacts:
        """Build typed relationship facts from generic edge dict payloads."""
        facts = cls()
        errors: list[str] = []
        for index, edge in enumerate(edge_records, start=1):
            if not isinstance(edge, dict):
                errors.append(f"edge_records[{index}] must be an object")
                continue
            try:
                signal = cls._canonical_signal(
                    edge.get("signal_type")
                    or edge.get("type")
                    or edge.get("facet")
                    or edge.get("kind")
                )
                src = cls._extract_id(
                    edge,
                    ("src_id", "src", "caller", "from", "pin", "emitter_pin", "referrer_pin"),
                    field_name="src_id",
                )
                dst = cls._extract_id(
                    edge,
                    ("dst_id", "dst", "callee", "to", "store_id", "event_id", "referenced_id"),
                    field_name="dst_id",
                )
                confidence = cls._parse_confidence(edge.get("confidence", 1.0))
                evidence_pin_raw = edge.get("evidence_pin")
                if evidence_pin_raw is None:
                    evidence_pin = None
                elif isinstance(evidence_pin_raw, str):
                    evidence_pin = evidence_pin_raw.strip() or None
                else:
                    raise ValueError("evidence_pin must be a string when provided")

                if signal == "CALL":
                    facts.calls.append(
                        CallRelationshipFact(
                            caller_pin=src,
                            callee_pin=dst,
                            confidence=confidence,
                            evidence_pin=evidence_pin,
                        )
                    )
                    continue
                if signal == "REFERENCE":
                    facts.references.append(
                        ReferenceRelationshipFact(
                            referrer_pin=src,
                            referenced_id=dst,
                            confidence=confidence,
                            evidence_pin=evidence_pin,
                        )
                    )
                    continue
                if signal == "STORE_TOUCH":
                    raw_access_type = edge.get("access_type", "read_write")
                    if not isinstance(raw_access_type, str):
                        raise ValueError("access_type must be a string")
                    access_type = raw_access_type.strip().lower() or "read_write"
                    if access_type not in {"read", "write", "read_write"}:
                        raise ValueError("access_type must be one of: read, write, read_write")
                    facts.stores.append(
                        StoreRelationshipFact(
                            pin=src,
                            store_id=dst,
                            access_type=access_type,
                        )
                    )
                    continue

                role_raw = edge.get("role", "")
                if not isinstance(role_raw, str):
                    raise TypeError("role must be a string when provided")
                role = role_raw.strip().lower()
                if role not in {"", "emit", "consume"}:
                    raise ValueError("role must be one of: emit, consume")
                if role == "consume":
                    emitter_pin_raw = edge.get("emitter_pin")
                    event_id_raw = edge.get("event_id")
                    consumer_pin_raw = edge.get("consumer_pin")
                    if emitter_pin_raw is not None and not isinstance(emitter_pin_raw, str):
                        raise ValueError("emitter_pin must be a string when provided")
                    if event_id_raw is not None and not isinstance(event_id_raw, str):
                        raise ValueError("event_id must be a string when provided")
                    if consumer_pin_raw is not None and not isinstance(consumer_pin_raw, str):
                        raise ValueError("consumer_pin must be a string when provided")
                    emitter_pin = (
                        emitter_pin_raw.strip() if isinstance(emitter_pin_raw, str) else src
                    ) or src
                    event_id = (
                        event_id_raw.strip() if isinstance(event_id_raw, str) else src
                    ) or src
                    consumer_pin = (
                        consumer_pin_raw.strip() if isinstance(consumer_pin_raw, str) else dst
                    ) or dst
                    facts.events.append(
                        EventRelationshipFact(
                            emitter_pin=emitter_pin,
                            event_id=event_id,
                            consumer_pin=consumer_pin,
                        )
                    )
                    continue
                consumer_pin_raw = edge.get("consumer_pin")
                if consumer_pin_raw is not None and not isinstance(consumer_pin_raw, str):
                    raise ValueError("consumer_pin must be a string when provided")
                event_id_raw = edge.get("event_id")
                if event_id_raw is not None and not isinstance(event_id_raw, str):
                    raise ValueError("event_id must be a string when provided")
                event_id = (event_id_raw.strip() if isinstance(event_id_raw, str) else dst) or dst
                facts.events.append(
                    EventRelationshipFact(
                        emitter_pin=src,
                        event_id=event_id,
                        consumer_pin=(
                            consumer_pin_raw.strip() if isinstance(consumer_pin_raw, str) else None
                        )
                        or None,
                    )
                )
            except ValueError as exc:
                errors.append(f"edge_records[{index}]: {exc}")
        if errors:
            raise ValueError("Invalid relationship edge records:\n- " + "\n- ".join(errors))
        return facts

    def to_edge_records(self) -> list[dict[str, Any]]:
        """Convert typed relationship facts to normalized edge dict records."""
        edges: list[dict[str, Any]] = []
        for fact in self.calls:
            edges.append(
                {
                    "signal_type": "CALL",
                    "src_id": fact.caller_pin,
                    "dst_id": fact.callee_pin,
                    "confidence": fact.confidence,
                    "evidence_pin": fact.evidence_pin,
                }
            )
        for fact in self.references:
            edges.append(
                {
                    "signal_type": "REFERENCE",
                    "src_id": fact.referrer_pin,
                    "dst_id": fact.referenced_id,
                    "confidence": fact.confidence,
                    "evidence_pin": fact.evidence_pin,
                }
            )
        for fact in self.stores:
            edges.append(
                {
                    "signal_type": "STORE_TOUCH",
                    "src_id": fact.pin,
                    "dst_id": fact.store_id,
                    "access_type": fact.access_type,
                }
            )
        for fact in self.events:
            edges.append(
                {
                    "signal_type": "EVENT",
                    "src_id": fact.emitter_pin,
                    "dst_id": fact.event_id,
                    "event_id": fact.event_id,
                    "role": "emit",
                }
            )
            if fact.consumer_pin:
                edges.append(
                    {
                        "signal_type": "EVENT",
                        "src_id": fact.event_id,
                        "dst_id": fact.consumer_pin,
                        "event_id": fact.event_id,
                        "role": "consume",
                    }
                )
        return edges


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
        relationship_facts: Declared call/reference/event/store relationships
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
