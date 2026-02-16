"""Planning strategy protocol and session runner.

Defines the :class:`PlanningStrategy` protocol that all strategies implement,
the mutable :class:`PlanningSession` that flows through the pipeline, and
:class:`PlanningSessionRunner` that orchestrates strategy execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from spec_manager.planner.architecture.types import DecisionOutcome
from spec_manager.planner.constraints.types import (
    ConflictReport,
    ConstraintContext,
    ConstraintFact,
    ConstraintHypothesis,
    DecisionRequirement,
    ImpactClassification,
    ProblemFrame,
)


@runtime_checkable
class PlanningStrategy(Protocol):
    """Protocol for planning strategies.

    Each strategy reads from and mutates a :class:`PlanningSession`,
    returning the (possibly modified) session.
    """

    @property
    def name(self) -> str: ...

    def run(self, session: PlanningSession) -> PlanningSession: ...


@dataclass
class CandidateEvaluation:
    """Typed projection for candidate-evaluation signals shared across strategies."""

    candidate_id: str = ""
    source: str = "unknown"
    coupling_score: int = 0
    blast_radius: int = 0
    constraints_checked: int = 0
    recommendation: Literal["accept", "needs_human", "reject"] = "needs_human"
    reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "candidate_id": self.candidate_id,
            "source": self.source,
            "coupling_score": self.coupling_score,
            "blast_radius": self.blast_radius,
            "constraints_checked": self.constraints_checked,
            "recommendation": self.recommendation,
            "reasons": list(self.reasons),
        }
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CandidateEvaluation:
        if not isinstance(payload, dict):
            raise TypeError("candidate evaluation payload must be a dict")
        reasons_raw = payload.get("reasons", [])
        reasons = [str(reason).strip() for reason in reasons_raw if str(reason).strip()]
        recommendation = str(payload.get("recommendation", "needs_human")).strip().lower()
        if recommendation not in {"accept", "needs_human", "reject"}:
            recommendation = "needs_human"
        metadata_raw = payload.get("metadata", {})
        metadata = dict(metadata_raw) if isinstance(metadata_raw, dict) else {}
        return cls(
            candidate_id=str(payload.get("candidate_id", "")).strip(),
            source=str(payload.get("source", "unknown")).strip() or "unknown",
            coupling_score=_coerce_int(payload.get("coupling_score"), default=0),
            blast_radius=_coerce_int(payload.get("blast_radius"), default=0),
            constraints_checked=_coerce_int(payload.get("constraints_checked"), default=0),
            recommendation=recommendation,  # type: ignore[arg-type]
            reasons=reasons,
            metadata=metadata,
        )


@dataclass
class UnderSpecEvent:
    """Typed projection for under-spec signals shared across strategies."""

    type: str = ""
    question: str = ""
    reason: str = ""
    detail: str = ""
    context: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        event: dict[str, Any] = {"type": self.type}
        if self.question:
            event["question"] = self.question
        if self.reason:
            event["reason"] = self.reason
        if self.detail:
            event["detail"] = self.detail
        if self.context:
            event["context"] = self.context
        if self.payload:
            event.update(dict(self.payload))
        return event

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> UnderSpecEvent:
        if not isinstance(payload, dict):
            raise TypeError("under-spec event payload must be a dict")
        event_type = str(payload.get("type", "")).strip()
        if not event_type:
            event_type = "under_spec"
        core_keys = {"type", "question", "reason", "detail", "context"}
        extras = {key: value for key, value in payload.items() if key not in core_keys}
        return cls(
            type=event_type,
            question=str(payload.get("question", "")).strip(),
            reason=str(payload.get("reason", "")).strip(),
            detail=str(payload.get("detail", "")).strip(),
            context=str(payload.get("context", "")).strip(),
            payload=extras,
        )


@dataclass
class PlanningSession:
    """Mutable session object passed through the strategy pipeline.

    Attributes:
        ctx: Contextual information for the planning request (layer, slice_id, etc.).
        gaps: Gap analysis results.
        discovery: Discovery graph data.
        impact: Impact classification (set by ImpactClassifierStrategy).
        problem_frame: Problem framing (set by ProblemFramerStrategy).
        constraint_context: Loaded constraints (set by ConstraintBootstrapStrategy).
        hypotheses: Inferred hypotheses (set by ConstraintEnricherStrategy).
        decision_requirements: Decisions needed (accumulated by strategies).
        conflict_report: Detected conflicts (set by ConstraintEnricherStrategy).
        decision_outcomes: Architecture decision outcomes (set by ArchitecturePlannerStrategy).
        intentions: Planning intentions (accumulated by strategies).
        candidate_evaluations: Typed evaluation projections for planning candidates
            (set by CandidateEvaluatorStrategy).
        under_spec_events: Typed under-spec events for human review.
        new_constraints: New constraint facts to persist (accumulated by strategies).
        constraint_authority_audit: Additive authority-review log for all reviewed constraints.
    """

    ctx: dict[str, Any] = field(default_factory=dict)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    discovery: dict[str, Any] = field(default_factory=dict)
    impact: ImpactClassification | None = None
    problem_frame: ProblemFrame | None = None
    constraint_context: ConstraintContext | None = None
    hypotheses: list[ConstraintHypothesis] = field(default_factory=list)
    decision_requirements: list[DecisionRequirement] = field(default_factory=list)
    conflict_report: ConflictReport | None = None
    decision_outcomes: list[DecisionOutcome] = field(default_factory=list)
    intentions: list[dict[str, Any]] = field(default_factory=list)
    candidate_evaluations: list[CandidateEvaluation] = field(default_factory=list)
    under_spec_events: list[UnderSpecEvent] = field(default_factory=list)
    new_constraints: list[ConstraintFact] = field(default_factory=list)
    tradeoff_axes: list[str] = field(default_factory=list)
    constraint_authority_audit: list[dict[str, Any]] = field(default_factory=list)

    def set_candidate_evaluations(
        self, evaluations: list[CandidateEvaluation | dict[str, Any]]
    ) -> None:
        self.candidate_evaluations = [
            value
            if isinstance(value, CandidateEvaluation)
            else CandidateEvaluation.from_dict(value)
            for value in evaluations
        ]

    def add_under_spec_event(self, event: UnderSpecEvent | dict[str, Any]) -> None:
        self.under_spec_events.append(
            event if isinstance(event, UnderSpecEvent) else UnderSpecEvent.from_dict(event)
        )

    def extend_under_spec_events(self, events: list[UnderSpecEvent | dict[str, Any]]) -> None:
        for event in events:
            self.add_under_spec_event(event)

    def set_under_spec_events(self, events: list[UnderSpecEvent | dict[str, Any]]) -> None:
        self.under_spec_events = []
        self.extend_under_spec_events(events)

    def under_spec_event_dicts(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.under_spec_events]

    def candidate_evaluation_dicts(self) -> list[dict[str, Any]]:
        return [evaluation.to_dict() for evaluation in self.candidate_evaluations]

    def normalize_projections(self) -> None:
        self.set_candidate_evaluations(
            [
                value if isinstance(value, CandidateEvaluation) else dict(value)
                for value in self.candidate_evaluations
            ]
        )
        self.set_under_spec_events(
            [
                value if isinstance(value, UnderSpecEvent) else dict(value)
                for value in self.under_spec_events
            ]
        )


class PlanningSessionRunner:
    """Executes a list of strategies sequentially on a session.

    Args:
        strategies: Ordered list of strategies to execute.
    """

    def __init__(self, strategies: list[PlanningStrategy]) -> None:
        self._strategies = list(strategies)

    @property
    def strategies(self) -> list[PlanningStrategy]:
        return list(self._strategies)

    def run(self, session: PlanningSession) -> PlanningSession:
        """Run all strategies in order, threading the session through each."""
        for strategy in self._strategies:
            session = strategy.run(session)
            session.normalize_projections()
        return session


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
