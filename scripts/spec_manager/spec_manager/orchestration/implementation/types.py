"""Types for the implementation step of the PromotionLoop.

These mirror the output schema of the ``pdd-function-implementor`` agent
and are consumed by ``ImplementationRunner`` and downstream steps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS: dict[str, list[str]] = {
    "FunctionTarget": ["file", "fqn", "signature", "span_hint"],
    "PinProposal": ["pin_id", "role", "fqn", "file", "span"],
    "EdgeProposal": ["src", "dst", "signal_type", "weight"],
    "TestArtifact": ["path", "purpose", "scope", "unified_diff"],
    "EditEntry": ["path", "unified_diff"],
    "UnderSpecEvent": ["kind", "question", "options", "needed_for", "evidence_paths"],
    "ImplementorOutput": [
        "function_target",
        "edits",
        "pin_proposals",
        "edge_proposals",
        "tests",
        "under_spec_events",
        "notes_md",
    ],
}

_PIN_ROLES = ("ATOM", "STORE", "SHAPE", "TEST", "ARCH")
_EDGE_SIGNAL_TYPES = (
    "CALL",
    "STORE_TOUCH",
    "EVENT_EMIT",
    "EVENT_HANDLE",
    "IMPORT",
    "REFERENCE",
)
_TEST_SCOPES = ("UNIT", "SLICE", "INTEGRATION")
_UNDER_SPEC_KINDS = (
    "MISSING_CONSTRAINT",
    "CONFLICTING_CONSTRAINTS",
    "EXTERNAL_DEP_UNKNOWN",
    "NEEDS_PRODUCT_DECISION",
    "NEEDS_API_DECISION",
)
_UNDER_SPEC_DIMENSIONS = (
    "software",
    "legal",
    "economic",
    "organizational",
    "temporal",
    "operational",
)
_UNDER_SPEC_AUTHORITIES = ("planner_ok", "human_required")
_UNDER_SPEC_DECISION_TYPES = (
    "dependency",
    "infrastructure",
    "data_policy",
    "security",
    "performance",
    "architecture",
)


def _parse_literal(
    value: Any,
    *,
    field_name: str,
    allowed: tuple[str, ...],
    default: str | None = None,
) -> str:
    if value is None:
        if default is not None:
            return default
        raise ValueError(f"{field_name} is required")

    text = str(value).strip()
    if not text:
        if default is not None:
            return default
        raise ValueError(f"{field_name} is required")

    if text not in allowed:
        allowed_values = ", ".join(allowed)
        raise ValueError(f"{field_name} must be one of [{allowed_values}], got {text!r}")
    return text


def _parse_string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a list")

    values: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise TypeError(f"{field_name}[{index}] must be a string")
        values.append(item)
    return values


def implementor_output_json_schema() -> dict[str, Any]:
    """Single-source response schema for implementor prompting + parsing."""
    return {
        "type": "object",
        "required": list(_REQUIRED_FIELDS["ImplementorOutput"]),
        "properties": {
            "function_target": {
                "type": "object",
                "required": list(_REQUIRED_FIELDS["FunctionTarget"]),
                "properties": {
                    "file": {"type": "string"},
                    "fqn": {"type": "string"},
                    "signature": {"type": "string"},
                    "span_hint": {
                        "type": "object",
                        "required": ["start_line", "end_line"],
                        "properties": {
                            "start_line": {"type": "integer"},
                            "end_line": {"type": "integer"},
                        },
                    },
                },
            },
            "edits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": list(_REQUIRED_FIELDS["EditEntry"]),
                    "properties": {
                        "path": {"type": "string"},
                        "unified_diff": {"type": "string"},
                    },
                },
            },
            "pin_proposals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": list(_REQUIRED_FIELDS["PinProposal"]),
                    "properties": {
                        "pin_id": {"type": "string"},
                        "role": {"type": "string", "enum": list(_PIN_ROLES)},
                        "fqn": {"type": "string"},
                        "file": {"type": "string"},
                        "span": {"type": "object"},
                        "atom_id_hint": {"type": ["string", "null"]},
                        "evidence_paths": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "edge_proposals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": list(_REQUIRED_FIELDS["EdgeProposal"]),
                    "properties": {
                        "src": {"type": "string"},
                        "dst": {"type": "string"},
                        "signal_type": {
                            "type": "string",
                            "enum": list(_EDGE_SIGNAL_TYPES),
                        },
                        "weight": {"type": "number"},
                        "evidence_paths": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "tests": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": list(_REQUIRED_FIELDS["TestArtifact"]),
                    "properties": {
                        "path": {"type": "string"},
                        "purpose": {"type": "string"},
                        "scope": {"type": "string", "enum": list(_TEST_SCOPES)},
                        "runner_hint": {"type": ["string", "null"]},
                        "unified_diff": {"type": "string"},
                    },
                },
            },
            "under_spec_events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": list(_REQUIRED_FIELDS["UnderSpecEvent"]),
                    "properties": {
                        "kind": {"type": "string", "enum": list(_UNDER_SPEC_KINDS)},
                        "question": {"type": "string"},
                        "dimension": {"type": "string", "enum": list(_UNDER_SPEC_DIMENSIONS)},
                        "authority_required": {
                            "type": "string",
                            "enum": list(_UNDER_SPEC_AUTHORITIES),
                        },
                        "decision_type": {
                            "type": "string",
                            "enum": list(_UNDER_SPEC_DECISION_TYPES),
                        },
                        "options": {"type": "array", "items": {"type": "string"}},
                        "needed_for": {"type": ["string", "null"]},
                        "evidence_paths": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "notes_md": {"type": "string"},
        },
    }


def _check_required(cls_name: str, d: dict[str, Any]) -> None:
    """Raise when required fields are missing in LLM output."""
    for key in _REQUIRED_FIELDS.get(cls_name, []):
        if key not in d or d[key] in (None, ""):
            raise ValueError(f"{cls_name} missing required field: {key}")


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
        _check_required("PinProposal", d)
        span = d.get("span")
        if not isinstance(span, dict):
            raise TypeError("PinProposal.span must be an object")
        atom_id_hint = d.get("atom_id_hint")
        if atom_id_hint is not None and not isinstance(atom_id_hint, str):
            raise TypeError("PinProposal.atom_id_hint must be a string or null")
        return cls(
            pin_id=str(d["pin_id"]).strip(),
            fqn=str(d["fqn"]).strip(),
            file=str(d["file"]).strip(),
            role=_parse_literal(
                d.get("role"),
                field_name="PinProposal.role",
                allowed=_PIN_ROLES,
                default="ATOM",
            ),
            span=span,
            atom_id_hint=atom_id_hint,
            evidence_paths=_parse_string_list(
                d.get("evidence_paths"),
                field_name="PinProposal.evidence_paths",
            ),
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
        _check_required("EdgeProposal", d)
        return cls(
            src=str(d["src"]).strip(),
            dst=str(d["dst"]).strip(),
            signal_type=_parse_literal(
                d.get("signal_type"),
                field_name="EdgeProposal.signal_type",
                allowed=_EDGE_SIGNAL_TYPES,
                default="CALL",
            ),
            weight=float(d["weight"]),
            evidence_paths=_parse_string_list(
                d.get("evidence_paths"),
                field_name="EdgeProposal.evidence_paths",
            ),
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
        _check_required("TestArtifact", d)
        runner_hint = d.get("runner_hint")
        if runner_hint is not None and not isinstance(runner_hint, str):
            raise TypeError("TestArtifact.runner_hint must be a string or null")
        return cls(
            path=str(d["path"]).strip(),
            purpose=str(d["purpose"]).strip(),
            scope=_parse_literal(
                d.get("scope"),
                field_name="TestArtifact.scope",
                allowed=_TEST_SCOPES,
                default="UNIT",
            ),
            runner_hint=runner_hint,
            unified_diff=str(d["unified_diff"]),
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
    dimension: Literal[
        "software",
        "legal",
        "economic",
        "organizational",
        "temporal",
        "operational",
    ] = "software"
    authority_required: Literal["planner_ok", "human_required"] = "planner_ok"
    decision_type: Literal[
        "dependency",
        "infrastructure",
        "data_policy",
        "security",
        "performance",
        "architecture",
    ] = "performance"
    options: list[str] = field(default_factory=list)
    needed_for: str | None = None
    evidence_paths: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> UnderSpecEvent:
        _check_required("UnderSpecEvent", d)
        kind = _parse_literal(
            d.get("kind"),
            field_name="UnderSpecEvent.kind",
            allowed=_UNDER_SPEC_KINDS,
            default="MISSING_CONSTRAINT",
        )
        dimension = _parse_literal(
            d.get("dimension"),
            field_name="UnderSpecEvent.dimension",
            allowed=_UNDER_SPEC_DIMENSIONS,
            default="software",
        )
        authority_required = _parse_literal(
            d.get("authority_required"),
            field_name="UnderSpecEvent.authority_required",
            allowed=_UNDER_SPEC_AUTHORITIES,
            default="planner_ok",
        )
        decision_type = _parse_literal(
            d.get("decision_type"),
            field_name="UnderSpecEvent.decision_type",
            allowed=_UNDER_SPEC_DECISION_TYPES,
            default="performance",
        )
        needed_for = d.get("needed_for")
        if needed_for is not None and not isinstance(needed_for, str):
            raise TypeError("UnderSpecEvent.needed_for must be a string or null")
        question = d.get("question", "")
        if not isinstance(question, str):
            raise TypeError("UnderSpecEvent.question must be a string")
        return cls(
            kind=kind,
            question=question,
            dimension=dimension,  # type: ignore[arg-type]
            authority_required=authority_required,  # type: ignore[arg-type]
            decision_type=decision_type,  # type: ignore[arg-type]
            options=_parse_string_list(
                d.get("options"),
                field_name="UnderSpecEvent.options",
            ),
            needed_for=needed_for,
            evidence_paths=_parse_string_list(
                d.get("evidence_paths"),
                field_name="UnderSpecEvent.evidence_paths",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "question": self.question,
            "dimension": self.dimension,
            "authority_required": self.authority_required,
            "decision_type": self.decision_type,
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
        _check_required("FunctionTarget", d)
        span_hint = d.get("span_hint")
        if not isinstance(span_hint, dict):
            raise TypeError("FunctionTarget.span_hint must be an object")
        return cls(
            file=str(d["file"]).strip(),
            fqn=str(d["fqn"]).strip(),
            signature=str(d["signature"]),
            span_hint=span_hint,
        )


@dataclass
class EditEntry:
    """A single file edit (unified diff)."""

    path: str
    unified_diff: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EditEntry:
        _check_required("EditEntry", d)
        return cls(
            path=str(d["path"]).strip(),
            unified_diff=str(d["unified_diff"]),
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

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ImplementorOutput:
        _check_required("ImplementorOutput", d)
        ft = d.get("function_target")
        if not isinstance(ft, dict):
            raise TypeError("ImplementorOutput.function_target must be an object")
        edits = d.get("edits")
        pin_proposals = d.get("pin_proposals")
        edge_proposals = d.get("edge_proposals")
        tests = d.get("tests")
        under_spec_events = d.get("under_spec_events")
        if not isinstance(edits, list):
            raise TypeError("ImplementorOutput.edits must be a list")
        if not isinstance(pin_proposals, list):
            raise TypeError("ImplementorOutput.pin_proposals must be a list")
        if not isinstance(edge_proposals, list):
            raise TypeError("ImplementorOutput.edge_proposals must be a list")
        if not isinstance(tests, list):
            raise TypeError("ImplementorOutput.tests must be a list")
        if not isinstance(under_spec_events, list):
            raise TypeError("ImplementorOutput.under_spec_events must be a list")
        return cls(
            function_target=FunctionTarget.from_dict(ft),
            edits=[EditEntry.from_dict(e) for e in edits],
            pin_proposals=[PinProposal.from_dict(p) for p in pin_proposals],
            edge_proposals=[EdgeProposal.from_dict(e) for e in edge_proposals],
            tests=[TestArtifact.from_dict(t) for t in tests],
            under_spec_events=[UnderSpecEvent.from_dict(e) for e in under_spec_events],
            notes_md=str(d["notes_md"]),
        )
