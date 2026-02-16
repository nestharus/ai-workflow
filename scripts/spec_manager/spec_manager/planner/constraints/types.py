"""Shared constraint types used throughout the planner constraints sub-package.

All dataclasses provide ``to_dict()`` and ``from_dict()`` for JSON round-trip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


def _coerce_confidence(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_validated(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"true", "1", "yes"}:
            return True
        if token in {"false", "0", "no", ""}:
            return False
        return default
    if isinstance(value, (int, float)):
        return value != 0
    return default


# ------------------------------------------------------------------
# Core fact
# ------------------------------------------------------------------


@dataclass
class ConstraintFact:
    """An authoritative, validated constraint fact.

    Attributes:
        constraint_id: Stable identifier (e.g. ``CON-LIB-001``).
        question: The requirement or design question this answers.
        answer: The decided answer.
        source: Origin of the fact (``user``, ``research``, ``steering``, ``existing``).
        confidence: 0.0-1.0 confidence level.
        validated: Whether the fact has been validated.
        dimension: Classification axis.
        authority_required: Whether planner can decide or human is needed.
        decision_type: Free-text classification of the decision kind.
        scope: Scope descriptor (``intra:LIB``, ``inter:A->B:handle``, ``system``).
        applies_to_layers: Which layers this fact applies to (e.g. ``["L1", "L2"]``).
        status: Lifecycle status.
        supersedes: IDs of facts this one replaces.
        trace: Audit trail entries.
    """

    constraint_id: str = ""
    question: str = ""
    answer: str = ""
    source: Literal["user", "research", "steering", "existing"] = "existing"
    confidence: float = 1.0
    validated: bool = True
    dimension: Literal[
        "software", "legal", "economic", "organizational", "temporal", "operational"
    ] = "software"
    authority_required: Literal["planner_ok", "human_required"] = "planner_ok"
    decision_type: str = ""
    scope: str = "intra:LIB"
    applies_to_layers: list[str] = field(default_factory=list)
    status: Literal["ACTIVE", "SUPERSEDED"] = "ACTIVE"
    supersedes: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "question": self.question,
            "answer": self.answer,
            "source": self.source,
            "confidence": self.confidence,
            "validated": self.validated,
            "dimension": self.dimension,
            "authority_required": self.authority_required,
            "decision_type": self.decision_type,
            "scope": self.scope,
            "applies_to_layers": list(self.applies_to_layers),
            "status": self.status,
            "supersedes": list(self.supersedes),
            "trace": list(self.trace),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ConstraintFact:
        confidence_raw = d.get("confidence")
        validated_raw = d.get("validated")
        return cls(
            constraint_id=d.get("constraint_id", ""),
            question=d.get("question", ""),
            answer=d.get("answer", ""),
            source=d.get("source", "existing"),
            confidence=_coerce_confidence(confidence_raw, default=0.0),
            validated=_coerce_validated(validated_raw, default=False),
            dimension=d.get("dimension", "software"),
            authority_required=d.get("authority_required", "planner_ok"),
            decision_type=d.get("decision_type", ""),
            scope=d.get("scope", "intra:LIB"),
            applies_to_layers=list(d.get("applies_to_layers", [])),
            status=d.get("status", "ACTIVE"),
            supersedes=list(d.get("supersedes", [])),
            trace=list(d.get("trace", [])),
        )


# ------------------------------------------------------------------
# Hypothesis (unverified)
# ------------------------------------------------------------------


@dataclass
class ConstraintHypothesis:
    """An unverified hypothesis inferred by the planner.

    Attributes:
        hypothesis_id: Unique identifier.
        question: The question being hypothesized about.
        inferred_answer: The tentative answer.
        source: Where this hypothesis came from.
        confidence: Certainty level (0.0-1.0).
        dimension: Classification axis.
        reasoning: Explanation of why the hypothesis was inferred.
    """

    hypothesis_id: str = ""
    question: str = ""
    inferred_answer: str = ""
    source: str = ""
    confidence: float = 0.0
    dimension: Literal[
        "software", "legal", "economic", "organizational", "temporal", "operational"
    ] = "software"
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "question": self.question,
            "inferred_answer": self.inferred_answer,
            "source": self.source,
            "confidence": self.confidence,
            "dimension": self.dimension,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ConstraintHypothesis:
        return cls(
            hypothesis_id=d.get("hypothesis_id", ""),
            question=d.get("question", ""),
            inferred_answer=d.get("inferred_answer", ""),
            source=d.get("source", ""),
            confidence=d.get("confidence", 0.0),
            dimension=d.get("dimension", "software"),
            reasoning=d.get("reasoning", ""),
        )


# ------------------------------------------------------------------
# Decision requirement
# ------------------------------------------------------------------


@dataclass
class DecisionRequirement:
    """A decision that needs to be made before implementation can proceed.

    Attributes:
        decision_id: Unique identifier.
        question: What needs to be decided.
        kind: Classification of the decision.
        dimension: Classification axis.
        scope: Scope descriptor.
        impact: Impact classification (reference, not embedded).
        options: Possible answers/approaches.
        needed_for: What downstream work depends on this decision.
    """

    decision_id: str = ""
    question: str = ""
    kind: str = ""
    dimension: Literal[
        "software", "legal", "economic", "organizational", "temporal", "operational"
    ] = "software"
    scope: str = "intra:LIB"
    impact: str = ""
    options: list[str] = field(default_factory=list)
    needed_for: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "question": self.question,
            "kind": self.kind,
            "dimension": self.dimension,
            "scope": self.scope,
            "impact": self.impact,
            "options": list(self.options),
            "needed_for": list(self.needed_for),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DecisionRequirement:
        return cls(
            decision_id=d.get("decision_id", ""),
            question=d.get("question", ""),
            kind=d.get("kind", ""),
            dimension=d.get("dimension", "software"),
            scope=d.get("scope", "intra:LIB"),
            impact=d.get("impact", ""),
            options=list(d.get("options", [])),
            needed_for=list(d.get("needed_for", [])),
        )


# ------------------------------------------------------------------
# Impact classification
# ------------------------------------------------------------------


@dataclass
class ImpactClassification:
    """Deterministic impact classification of a change.

    Attributes:
        impact: Overall severity.
        blast_radius: How far the change ripples.
        reversibility: How easy it is to undo.
        triggers: List of reasons that contributed to the classification.
    """

    impact: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    blast_radius: Literal["LOCAL", "SLICE", "CROSS_SLICE", "SYSTEM"] = "LOCAL"
    reversibility: Literal["EASY", "MEDIUM", "HARD"] = "EASY"
    triggers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "impact": self.impact,
            "blast_radius": self.blast_radius,
            "reversibility": self.reversibility,
            "triggers": list(self.triggers),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ImpactClassification:
        return cls(
            impact=d.get("impact", "LOW"),
            blast_radius=d.get("blast_radius", "LOCAL"),
            reversibility=d.get("reversibility", "EASY"),
            triggers=list(d.get("triggers", [])),
        )


# ------------------------------------------------------------------
# Problem frame
# ------------------------------------------------------------------


@dataclass
class ProblemFrame:
    """High-level problem framing for a spec section or library.

    Attributes:
        goal: What the spec section aims to achieve.
        scope: Boundary of the problem.
        domain_markers: Key domain terms or concepts.
        decision_points: Questions that require decisions.
        tradeoff_axes: Dimensions where tradeoffs exist.
        unknowns: Identified unknowns or ambiguities.
    """

    goal: str = ""
    scope: str = ""
    domain_markers: list[str] = field(default_factory=list)
    decision_points: list[str] = field(default_factory=list)
    tradeoff_axes: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "scope": self.scope,
            "domain_markers": list(self.domain_markers),
            "decision_points": list(self.decision_points),
            "tradeoff_axes": list(self.tradeoff_axes),
            "unknowns": list(self.unknowns),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProblemFrame:
        return cls(
            goal=d.get("goal", ""),
            scope=d.get("scope", ""),
            domain_markers=list(d.get("domain_markers", [])),
            decision_points=list(d.get("decision_points", [])),
            tradeoff_axes=list(d.get("tradeoff_axes", [])),
            unknowns=list(d.get("unknowns", [])),
        )


# ------------------------------------------------------------------
# Constraint context (composite)
# ------------------------------------------------------------------


@dataclass
class ConstraintContext:
    """Composite view of constraints for a planning request.

    Attributes:
        authoritative: Validated, authoritative constraint facts.
        decisions: Facts that record past decisions.
        unverified: Hypotheses that have not been validated.
    """

    authoritative: list[ConstraintFact] = field(default_factory=list)
    decisions: list[ConstraintFact] = field(default_factory=list)
    unverified: list[ConstraintHypothesis] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authoritative": [f.to_dict() for f in self.authoritative],
            "decisions": [f.to_dict() for f in self.decisions],
            "unverified": [h.to_dict() for h in self.unverified],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ConstraintContext:
        return cls(
            authoritative=[ConstraintFact.from_dict(f) for f in d.get("authoritative", [])],
            decisions=[ConstraintFact.from_dict(f) for f in d.get("decisions", [])],
            unverified=[ConstraintHypothesis.from_dict(h) for h in d.get("unverified", [])],
        )


# ------------------------------------------------------------------
# Conflict report
# ------------------------------------------------------------------


@dataclass
class ConflictReport:
    """Report of detected conflicts between constraints.

    Attributes:
        conflicts: List of conflict descriptions (dicts with arbitrary keys).
    """

    conflicts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflicts": [dict(c) for c in self.conflicts],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ConflictReport:
        return cls(
            conflicts=[dict(c) for c in d.get("conflicts", [])],
        )


# ------------------------------------------------------------------
# Constraint index entry
# ------------------------------------------------------------------


@dataclass
class ConstraintIndexEntry:
    """Index entry for fast constraint lookups.

    Attributes:
        element_id: Constraint identifier (e.g. ``CON-LIB-001``).
        subtype: Classification from SEC-108 shallow tags
            (e.g. ``performance``, ``security``, ``policy``).
        scope_hint: Scope indicator (``intra``, ``inter``, ``system``).
        entities: Named entities referenced by the constraint.
        text_preview: Short preview of the constraint text.
    """

    element_id: str = ""
    subtype: str = ""
    scope_hint: str = ""
    entities: list[str] = field(default_factory=list)
    text_preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "subtype": self.subtype,
            "scope_hint": self.scope_hint,
            "entities": list(self.entities),
            "text_preview": self.text_preview,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ConstraintIndexEntry:
        return cls(
            element_id=d.get("element_id", ""),
            subtype=d.get("subtype", ""),
            scope_hint=d.get("scope_hint", ""),
            entities=list(d.get("entities", [])),
            text_preview=d.get("text_preview", ""),
        )
