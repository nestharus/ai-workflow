"""Types for the implementation step of the PromotionLoop.

These mirror the output schema of the ``pdd-function-implementor`` agent
and are consumed by ``ImplementationRunner`` and downstream steps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class PinProposal:
    """LLM-proposed pin to be merged into the PinRegistry."""

    pin_id: str
    fqn: str
    file: str
    role: Literal["ATOM", "STORE", "SHAPE", "TEST", "ARCH"] = "ATOM"
    span: dict[str, Any] | None = None
    atom_id_hint: str | None = None
    evidence_paths: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PinProposal:
        return cls(
            pin_id=d.get("pin_id", ""),
            fqn=d.get("fqn", ""),
            file=d.get("file", ""),
            role=d.get("role", "ATOM"),
            span=d.get("span"),
            atom_id_hint=d.get("atom_id_hint"),
            evidence_paths=d.get("evidence_paths", []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "pin_id": self.pin_id,
            "fqn": self.fqn,
            "file": self.file,
            "role": self.role,
            "span": self.span,
            "atom_id_hint": self.atom_id_hint,
            "evidence_paths": self.evidence_paths,
        }


@dataclass
class EdgeProposal:
    """LLM-proposed edge to be merged into the adjacency graph."""

    src: str
    dst: str
    signal_type: Literal[
        "CALL", "STORE_TOUCH", "EVENT_EMIT", "EVENT_HANDLE", "IMPORT", "REFERENCE"
    ] = "CALL"
    weight: float = 0.7
    evidence_paths: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EdgeProposal:
        return cls(
            src=d.get("src", ""),
            dst=d.get("dst", ""),
            signal_type=d.get("signal_type", "CALL"),
            weight=d.get("weight", 0.7),
            evidence_paths=d.get("evidence_paths", []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "src": self.src,
            "dst": self.dst,
            "signal_type": self.signal_type,
            "weight": self.weight,
            "evidence_paths": self.evidence_paths,
        }


@dataclass
class TestArtifact:
    """A test file produced by the implementation agent."""

    path: str
    purpose: str
    scope: Literal["UNIT", "SLICE", "INTEGRATION"] = "UNIT"
    runner_hint: str | None = None
    unified_diff: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TestArtifact:
        return cls(
            path=d.get("path", ""),
            purpose=d.get("purpose", ""),
            scope=d.get("scope", "UNIT"),
            runner_hint=d.get("runner_hint"),
            unified_diff=d.get("unified_diff", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "purpose": self.purpose,
            "scope": self.scope,
            "runner_hint": self.runner_hint,
            "unified_diff": self.unified_diff,
        }


@dataclass
class UnderSpecEvent:
    """An under-specification event emitted by the implementation agent.

    When the LLM encounters ambiguity it cannot resolve from the spec
    and constraints, it emits one of these instead of guessing.
    """

    kind: Literal[
        "MISSING_CONSTRAINT",
        "CONFLICTING_CONSTRAINTS",
        "EXTERNAL_DEP_UNKNOWN",
        "NEEDS_PRODUCT_DECISION",
        "NEEDS_API_DECISION",
    ] = "MISSING_CONSTRAINT"
    question: str = ""
    options: list[str] = field(default_factory=list)
    needed_for: str | None = None
    evidence_paths: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> UnderSpecEvent:
        return cls(
            kind=d.get("kind", "MISSING_CONSTRAINT"),
            question=d.get("question", ""),
            options=d.get("options", []),
            needed_for=d.get("needed_for"),
            evidence_paths=d.get("evidence_paths", []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "question": self.question,
            "options": self.options,
            "needed_for": self.needed_for,
            "evidence_paths": self.evidence_paths,
        }


@dataclass
class FunctionTarget:
    """Target function for implementation."""

    file: str = ""
    fqn: str = ""
    signature: str = ""
    span_hint: dict[str, int] | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FunctionTarget:
        return cls(
            file=d.get("file", ""),
            fqn=d.get("fqn", ""),
            signature=d.get("signature", ""),
            span_hint=d.get("span_hint"),
        )


@dataclass
class EditEntry:
    """A single file edit (unified diff)."""

    path: str
    unified_diff: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EditEntry:
        return cls(
            path=d.get("path", ""),
            unified_diff=d.get("unified_diff", ""),
        )


@dataclass
class ImplementorOutput:
    """Parsed output of the pdd-function-implementor agent (new schema).

    Replaces the legacy ``{body, imports_needed, gaps, notes}`` schema.
    """

    function_target: FunctionTarget = field(default_factory=FunctionTarget)
    edits: list[EditEntry] = field(default_factory=list)
    pin_proposals: list[PinProposal] = field(default_factory=list)
    edge_proposals: list[EdgeProposal] = field(default_factory=list)
    tests: list[TestArtifact] = field(default_factory=list)
    under_spec_events: list[UnderSpecEvent] = field(default_factory=list)
    notes_md: str = ""

    # Legacy fields (for backward compatibility during migration)
    body: str = ""
    imports_needed: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ImplementorOutput:
        ft = d.get("function_target")
        return cls(
            function_target=FunctionTarget.from_dict(ft) if ft else FunctionTarget(),
            edits=[EditEntry.from_dict(e) for e in d.get("edits", [])],
            pin_proposals=[PinProposal.from_dict(p) for p in d.get("pin_proposals", [])],
            edge_proposals=[EdgeProposal.from_dict(e) for e in d.get("edge_proposals", [])],
            tests=[TestArtifact.from_dict(t) for t in d.get("tests", [])],
            under_spec_events=[UnderSpecEvent.from_dict(e) for e in d.get("under_spec_events", [])],
            notes_md=d.get("notes_md", d.get("notes", "")),
            body=d.get("body", ""),
            imports_needed=d.get("imports_needed", []),
            gaps=d.get("gaps", []),
        )

    @property
    def is_legacy_format(self) -> bool:
        """True if output uses legacy {body, imports_needed} format."""
        return bool(self.body) and not self.edits
