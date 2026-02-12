"""Architecture decision types used throughout the planner architecture sub-package.

All dataclasses provide ``to_dict()`` and ``from_dict()`` for JSON round-trip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from spec_manager.planner.constraints.types import ConstraintFact, ImpactClassification


# ------------------------------------------------------------------
# Decision point
# ------------------------------------------------------------------


@dataclass
class DecisionPoint:
    """An identified architecture decision that must be resolved.

    Attributes:
        decision_id: Stable identifier (e.g. ``DEC-001``).
        scope: Scope descriptor (``intra:LIB``, ``inter:A->B``, ``system``).
        description: Human-readable summary of what needs to be decided.
        trigger_evidence: Evidence references that triggered this decision.
        impact: Impact classification for the decision.
        owner_slice_id: Slice that owns this decision point.
        status: Lifecycle status of the decision.
        required_constraints: Constraint IDs that must be satisfied.
        candidate_refs: References to proposed candidates.
        selected_candidate_ref: Chosen candidate reference (empty if undecided).
    """

    decision_id: str = ""
    scope: str = ""
    description: str = ""
    trigger_evidence: list[str] = field(default_factory=list)
    impact: ImpactClassification = field(default_factory=ImpactClassification)
    owner_slice_id: str = ""
    status: Literal["OPEN", "EXPLORING", "BLOCKED", "DECIDED"] = "OPEN"
    required_constraints: list[str] = field(default_factory=list)
    candidate_refs: list[str] = field(default_factory=list)
    selected_candidate_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "scope": self.scope,
            "description": self.description,
            "trigger_evidence": list(self.trigger_evidence),
            "impact": self.impact.to_dict(),
            "owner_slice_id": self.owner_slice_id,
            "status": self.status,
            "required_constraints": list(self.required_constraints),
            "candidate_refs": list(self.candidate_refs),
            "selected_candidate_ref": self.selected_candidate_ref,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DecisionPoint:
        return cls(
            decision_id=d.get("decision_id", ""),
            scope=d.get("scope", ""),
            description=d.get("description", ""),
            trigger_evidence=list(d.get("trigger_evidence", [])),
            impact=ImpactClassification.from_dict(d.get("impact", {})),
            owner_slice_id=d.get("owner_slice_id", ""),
            status=d.get("status", "OPEN"),
            required_constraints=list(d.get("required_constraints", [])),
            candidate_refs=list(d.get("candidate_refs", [])),
            selected_candidate_ref=d.get("selected_candidate_ref", ""),
        )


# ------------------------------------------------------------------
# Scope packet
# ------------------------------------------------------------------


@dataclass
class ScopePacket:
    """Context bundle assembled for a specific decision point.

    Packages together the decision scope, relevant evidence, constraints,
    and any positions already taken so that proposers can work from a
    self-contained context.

    Attributes:
        decision_id: The decision this packet belongs to.
        scope: Scope descriptor.
        trigger_evidence: Evidence references triggering this decision.
        source_artifacts: Mapping of artifact type to artifact references.
        authoritative_constraints: Validated constraints relevant to this decision.
        current_arch_state_refs: References to current architecture state.
        tradeoff_assignment: Mapping of tradeoff axis to assigned priority.
        positions_taken: Positions already taken on tradeoff axes.
    """

    decision_id: str = ""
    scope: str = ""
    trigger_evidence: list[str] = field(default_factory=list)
    source_artifacts: dict[str, Any] = field(default_factory=dict)
    authoritative_constraints: list[ConstraintFact] = field(default_factory=list)
    current_arch_state_refs: list[str] = field(default_factory=list)
    tradeoff_assignment: dict[str, str] = field(default_factory=dict)
    positions_taken: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "scope": self.scope,
            "trigger_evidence": list(self.trigger_evidence),
            "source_artifacts": dict(self.source_artifacts),
            "authoritative_constraints": [c.to_dict() for c in self.authoritative_constraints],
            "current_arch_state_refs": list(self.current_arch_state_refs),
            "tradeoff_assignment": dict(self.tradeoff_assignment),
            "positions_taken": list(self.positions_taken),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ScopePacket:
        return cls(
            decision_id=d.get("decision_id", ""),
            scope=d.get("scope", ""),
            trigger_evidence=list(d.get("trigger_evidence", [])),
            source_artifacts=dict(d.get("source_artifacts", {})),
            authoritative_constraints=[
                ConstraintFact.from_dict(c) for c in d.get("authoritative_constraints", [])
            ],
            current_arch_state_refs=list(d.get("current_arch_state_refs", [])),
            tradeoff_assignment=dict(d.get("tradeoff_assignment", {})),
            positions_taken=list(d.get("positions_taken", [])),
        )


# ------------------------------------------------------------------
# Architecture candidate
# ------------------------------------------------------------------


@dataclass
class ArchitectureCandidate:
    """A proposed architecture candidate for a decision point.

    Attributes:
        candidate_id: Unique identifier for this candidate.
        decision_id: The decision this candidate addresses.
        scope: Scope descriptor.
        position: Tradeoff position this candidate takes (axis -> priority).
        proposal: The architecture proposal details.
        constraints_introduced: New constraints introduced, keyed by
            ``software`` and ``non_software``.
        decision_requirements: Decision requirements this candidate raises.
        assumptions: Assumptions this candidate relies on.
        trace: Audit trail entries.
    """

    candidate_id: str = ""
    decision_id: str = ""
    scope: str = ""
    position: dict[str, str] = field(default_factory=dict)
    proposal: dict[str, Any] = field(default_factory=dict)
    constraints_introduced: dict[str, Any] = field(
        default_factory=lambda: {"software": {}, "non_software": {}}
    )
    decision_requirements: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "decision_id": self.decision_id,
            "scope": self.scope,
            "position": dict(self.position),
            "proposal": dict(self.proposal),
            "constraints_introduced": {
                "software": dict(self.constraints_introduced.get("software", {})),
                "non_software": dict(self.constraints_introduced.get("non_software", {})),
            },
            "decision_requirements": list(self.decision_requirements),
            "assumptions": list(self.assumptions),
            "trace": list(self.trace),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ArchitectureCandidate:
        ci = d.get("constraints_introduced", {})
        return cls(
            candidate_id=d.get("candidate_id", ""),
            decision_id=d.get("decision_id", ""),
            scope=d.get("scope", ""),
            position=dict(d.get("position", {})),
            proposal=dict(d.get("proposal", {})),
            constraints_introduced={
                "software": dict(ci.get("software", {})),
                "non_software": dict(ci.get("non_software", {})),
            },
            decision_requirements=list(d.get("decision_requirements", [])),
            assumptions=list(d.get("assumptions", [])),
            trace=list(d.get("trace", [])),
        )


# ------------------------------------------------------------------
# Candidate assessment
# ------------------------------------------------------------------


@dataclass
class CandidateAssessment:
    """Evaluation result for an architecture candidate.

    Attributes:
        candidate_id: The candidate being assessed.
        constraint_satisfaction: Mapping of constraint_id to satisfaction status.
        blockers: List of blocking issues.
        risk_score: Numeric risk score (0.0 = no risk, 1.0 = maximum risk).
        reversibility: How easy it is to reverse this candidate.
        recommendation: Overall recommendation.
    """

    candidate_id: str = ""
    constraint_satisfaction: dict[str, str] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    risk_score: float = 0.0
    reversibility: str = "EASY"
    recommendation: Literal["accept", "reject", "needs_human"] = "accept"

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "constraint_satisfaction": dict(self.constraint_satisfaction),
            "blockers": list(self.blockers),
            "risk_score": self.risk_score,
            "reversibility": self.reversibility,
            "recommendation": self.recommendation,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CandidateAssessment:
        return cls(
            candidate_id=d.get("candidate_id", ""),
            constraint_satisfaction=dict(d.get("constraint_satisfaction", {})),
            blockers=list(d.get("blockers", [])),
            risk_score=d.get("risk_score", 0.0),
            reversibility=d.get("reversibility", "EASY"),
            recommendation=d.get("recommendation", "accept"),
        )


# ------------------------------------------------------------------
# Decision outcome
# ------------------------------------------------------------------


@dataclass
class DecisionOutcome:
    """The resolved outcome of an architecture decision.

    Attributes:
        decision_id: The decision this outcome belongs to.
        committed: Whether the decision was committed (vs. blocked).
        selected_candidate_id: The chosen candidate.
        wiring_intentions: Wiring intentions resulting from the decision.
        new_constraints: New constraint IDs introduced.
        under_spec_events: Under-spec events emitted during resolution.
        decision_requirements: Outstanding decision requirements.
    """

    decision_id: str = ""
    committed: bool = False
    selected_candidate_id: str = ""
    wiring_intentions: list[dict[str, Any]] = field(default_factory=list)
    new_constraints: list[str] = field(default_factory=list)
    under_spec_events: list[dict[str, Any]] = field(default_factory=list)
    decision_requirements: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "committed": self.committed,
            "selected_candidate_id": self.selected_candidate_id,
            "wiring_intentions": [dict(w) for w in self.wiring_intentions],
            "new_constraints": list(self.new_constraints),
            "under_spec_events": [dict(e) for e in self.under_spec_events],
            "decision_requirements": list(self.decision_requirements),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DecisionOutcome:
        return cls(
            decision_id=d.get("decision_id", ""),
            committed=d.get("committed", False),
            selected_candidate_id=d.get("selected_candidate_id", ""),
            wiring_intentions=[dict(w) for w in d.get("wiring_intentions", [])],
            new_constraints=list(d.get("new_constraints", [])),
            under_spec_events=[dict(e) for e in d.get("under_spec_events", [])],
            decision_requirements=list(d.get("decision_requirements", [])),
        )
