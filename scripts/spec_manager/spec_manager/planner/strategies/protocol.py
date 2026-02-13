"""Planning strategy protocol and session runner.

Defines the :class:`PlanningStrategy` protocol that all strategies implement,
the mutable :class:`PlanningSession` that flows through the pipeline, and
:class:`PlanningSessionRunner` that orchestrates strategy execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

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
class PlanningSession:
    """Mutable session object passed through the strategy pipeline.

    Attributes:
        ctx: Contextual information for the planning request (layer, slice_id, etc.).
        gaps: Gap analysis results.
        discovery: Discovery graph data.
        impact: Impact classification (set by ImpactClassifierStrategy).
        problem_frame: Problem framing (set by ProblemFramerStrategy).
        constraint_context: Loaded constraints (set by ConstraintCollectionStrategy).
        hypotheses: Inferred hypotheses (set by ConstraintEnricherStrategy).
        decision_requirements: Decisions needed (accumulated by strategies).
        conflict_report: Detected conflicts (set by ConstraintEnricherStrategy).
        decision_outcomes: Architecture decision outcomes (set by ArchitecturePlannerStrategy).
        intentions: Planning intentions (accumulated by strategies).
        under_spec_events: Events for human review (accumulated by strategies).
        new_constraints: New constraint facts to persist (accumulated by strategies).
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
    under_spec_events: list[dict[str, Any]] = field(default_factory=list)
    new_constraints: list[ConstraintFact] = field(default_factory=list)
    tradeoff_axes: list[str] = field(default_factory=list)


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
        return session
