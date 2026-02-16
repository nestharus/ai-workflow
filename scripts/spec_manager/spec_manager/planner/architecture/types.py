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
        payload = _require_mapping(d, "DecisionPoint")
        impact_payload = _require_mapping(
            _require_key(payload, "impact", "DecisionPoint"), "DecisionPoint.impact"
        )
        return cls(
            decision_id=_require_string(
                _require_key(payload, "decision_id", "DecisionPoint"), "DecisionPoint.decision_id"
            ),
            scope=_require_string(
                _require_key(payload, "scope", "DecisionPoint"), "DecisionPoint.scope"
            ),
            description=_require_string(
                _require_key(payload, "description", "DecisionPoint"), "DecisionPoint.description"
            ),
            trigger_evidence=_require_string_list(
                _require_key(payload, "trigger_evidence", "DecisionPoint"),
                "DecisionPoint.trigger_evidence",
            ),
            impact=ImpactClassification(
                impact=_require_literal(
                    _require_key(impact_payload, "impact", "DecisionPoint.impact"),
                    "DecisionPoint.impact.impact",
                    {"LOW", "MEDIUM", "HIGH"},
                ),
                blast_radius=_require_literal(
                    _require_key(impact_payload, "blast_radius", "DecisionPoint.impact"),
                    "DecisionPoint.impact.blast_radius",
                    {"LOCAL", "SLICE", "CROSS_SLICE", "SYSTEM"},
                ),
                reversibility=_require_literal(
                    _require_key(impact_payload, "reversibility", "DecisionPoint.impact"),
                    "DecisionPoint.impact.reversibility",
                    {"EASY", "MEDIUM", "HARD"},
                ),
                triggers=_require_string_list(
                    _require_key(impact_payload, "triggers", "DecisionPoint.impact"),
                    "DecisionPoint.impact.triggers",
                ),
            ),
            owner_slice_id=_require_string(
                _require_key(payload, "owner_slice_id", "DecisionPoint"),
                "DecisionPoint.owner_slice_id",
            ),
            status=_require_literal(
                _require_key(payload, "status", "DecisionPoint"),
                "DecisionPoint.status",
                {"OPEN", "EXPLORING", "BLOCKED", "DECIDED"},
            ),
            required_constraints=_require_string_list(
                _require_key(payload, "required_constraints", "DecisionPoint"),
                "DecisionPoint.required_constraints",
            ),
            candidate_refs=_require_string_list(
                _require_key(payload, "candidate_refs", "DecisionPoint"),
                "DecisionPoint.candidate_refs",
            ),
            selected_candidate_ref=_require_string(
                _require_key(payload, "selected_candidate_ref", "DecisionPoint"),
                "DecisionPoint.selected_candidate_ref",
            ),
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
        payload = _require_mapping(d, "ScopePacket")
        constraints_payload = _require_list(
            _require_key(payload, "authoritative_constraints", "ScopePacket"),
            "ScopePacket.authoritative_constraints",
        )
        return cls(
            decision_id=_require_string(
                _require_key(payload, "decision_id", "ScopePacket"), "ScopePacket.decision_id"
            ),
            scope=_require_string(
                _require_key(payload, "scope", "ScopePacket"), "ScopePacket.scope"
            ),
            trigger_evidence=_require_string_list(
                _require_key(payload, "trigger_evidence", "ScopePacket"),
                "ScopePacket.trigger_evidence",
            ),
            source_artifacts=_require_mapping(
                _require_key(payload, "source_artifacts", "ScopePacket"),
                "ScopePacket.source_artifacts",
            ),
            authoritative_constraints=[
                ConstraintFact.from_dict(
                    _require_mapping(
                        item,
                        f"ScopePacket.authoritative_constraints[{index}]",
                    )
                )
                for index, item in enumerate(constraints_payload)
            ],
            current_arch_state_refs=_require_string_list(
                _require_key(payload, "current_arch_state_refs", "ScopePacket"),
                "ScopePacket.current_arch_state_refs",
            ),
            tradeoff_assignment=_require_string_mapping(
                _require_key(payload, "tradeoff_assignment", "ScopePacket"),
                "ScopePacket.tradeoff_assignment",
            ),
            positions_taken=_require_string_list(
                _require_key(payload, "positions_taken", "ScopePacket"),
                "ScopePacket.positions_taken",
            ),
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
        payload = _require_mapping(d, "ArchitectureCandidate")
        ci = _require_mapping(
            _require_key(payload, "constraints_introduced", "ArchitectureCandidate"),
            "ArchitectureCandidate.constraints_introduced",
        )
        software = _require_mapping(
            _require_key(ci, "software", "ArchitectureCandidate.constraints_introduced"),
            "ArchitectureCandidate.constraints_introduced.software",
        )
        non_software = _require_mapping(
            _require_key(ci, "non_software", "ArchitectureCandidate.constraints_introduced"),
            "ArchitectureCandidate.constraints_introduced.non_software",
        )
        return cls(
            candidate_id=_require_string(
                _require_key(payload, "candidate_id", "ArchitectureCandidate"),
                "ArchitectureCandidate.candidate_id",
            ),
            decision_id=_require_string(
                _require_key(payload, "decision_id", "ArchitectureCandidate"),
                "ArchitectureCandidate.decision_id",
            ),
            scope=_require_string(
                _require_key(payload, "scope", "ArchitectureCandidate"),
                "ArchitectureCandidate.scope",
            ),
            position=_require_string_mapping(
                _require_key(payload, "position", "ArchitectureCandidate"),
                "ArchitectureCandidate.position",
            ),
            proposal=_require_mapping(
                _require_key(payload, "proposal", "ArchitectureCandidate"),
                "ArchitectureCandidate.proposal",
            ),
            constraints_introduced={
                "software": software,
                "non_software": non_software,
            },
            decision_requirements=_require_string_list(
                _require_key(payload, "decision_requirements", "ArchitectureCandidate"),
                "ArchitectureCandidate.decision_requirements",
            ),
            assumptions=_require_string_list(
                _require_key(payload, "assumptions", "ArchitectureCandidate"),
                "ArchitectureCandidate.assumptions",
            ),
            trace=_require_string_list(
                _require_key(payload, "trace", "ArchitectureCandidate"),
                "ArchitectureCandidate.trace",
            ),
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
        payload = _require_mapping(d, "CandidateAssessment")
        return cls(
            candidate_id=_require_string(
                _require_key(payload, "candidate_id", "CandidateAssessment"),
                "CandidateAssessment.candidate_id",
            ),
            constraint_satisfaction=_require_literal_mapping(
                _require_key(payload, "constraint_satisfaction", "CandidateAssessment"),
                "CandidateAssessment.constraint_satisfaction",
                {"satisfied", "violated", "unknown", "unevaluated"},
            ),
            blockers=_require_string_list(
                _require_key(payload, "blockers", "CandidateAssessment"),
                "CandidateAssessment.blockers",
            ),
            risk_score=_require_float(
                _require_key(payload, "risk_score", "CandidateAssessment"),
                "CandidateAssessment.risk_score",
            ),
            reversibility=_require_literal(
                _require_key(payload, "reversibility", "CandidateAssessment"),
                "CandidateAssessment.reversibility",
                {"EASY", "MEDIUM", "HARD"},
            ),
            recommendation=_require_literal(
                _require_key(payload, "recommendation", "CandidateAssessment"),
                "CandidateAssessment.recommendation",
                {"accept", "reject", "needs_human"},
            ),
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
        payload = _require_mapping(d, "DecisionOutcome")
        return cls(
            decision_id=_require_string(
                _require_key(payload, "decision_id", "DecisionOutcome"),
                "DecisionOutcome.decision_id",
            ),
            committed=_require_bool(
                _require_key(payload, "committed", "DecisionOutcome"),
                "DecisionOutcome.committed",
            ),
            selected_candidate_id=_require_string(
                _require_key(payload, "selected_candidate_id", "DecisionOutcome"),
                "DecisionOutcome.selected_candidate_id",
            ),
            wiring_intentions=_require_mapping_list(
                _require_key(payload, "wiring_intentions", "DecisionOutcome"),
                "DecisionOutcome.wiring_intentions",
            ),
            new_constraints=_require_string_list(
                _require_key(payload, "new_constraints", "DecisionOutcome"),
                "DecisionOutcome.new_constraints",
            ),
            under_spec_events=_require_mapping_list(
                _require_key(payload, "under_spec_events", "DecisionOutcome"),
                "DecisionOutcome.under_spec_events",
            ),
            decision_requirements=_require_string_list(
                _require_key(payload, "decision_requirements", "DecisionOutcome"),
                "DecisionOutcome.decision_requirements",
            ),
        )


def _require_key(payload: dict[str, Any], key: str, context: str) -> Any:
    if key not in payload:
        raise ValueError(f"{context} missing required key '{key}'")
    return payload[key]


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be an object")
    return dict(value)


def _require_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a list")
    return list(value)


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    return value


def _require_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a boolean")
    return value


def _require_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field_name} must be a number")
    return float(value)


def _require_literal(value: Any, field_name: str, allowed: set[str]) -> str:
    text = _require_string(value, field_name)
    if text not in allowed:
        raise ValueError(f"{field_name} must be one of {sorted(allowed)}")
    return text


def _require_string_list(value: Any, field_name: str) -> list[str]:
    items = _require_list(value, field_name)
    result: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, str):
            raise TypeError(f"{field_name}[{index}] must be a string")
        result.append(item)
    return result


def _require_mapping_list(value: Any, field_name: str) -> list[dict[str, Any]]:
    items = _require_list(value, field_name)
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        result.append(_require_mapping(item, f"{field_name}[{index}]"))
    return result


def _require_string_mapping(value: Any, field_name: str) -> dict[str, str]:
    mapping = _require_mapping(value, field_name)
    result: dict[str, str] = {}
    for key, item in mapping.items():
        if not isinstance(key, str):
            raise TypeError(f"{field_name} keys must be strings")
        if not isinstance(item, str):
            raise TypeError(f"{field_name}[{key!r}] must be a string")
        result[key] = item
    return result


def _require_literal_mapping(value: Any, field_name: str, allowed: set[str]) -> dict[str, str]:
    mapping = _require_string_mapping(value, field_name)
    for key, status in mapping.items():
        if status not in allowed:
            raise ValueError(f"{field_name}[{key!r}] must be one of {sorted(allowed)}")
    return mapping
