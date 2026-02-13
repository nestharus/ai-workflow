"""Tests for spec_manager.planner.architecture.types — round-trip serialization."""

from __future__ import annotations

import copy

import pytest
from spec_manager.planner.architecture.types import (
    ArchitectureCandidate,
    CandidateAssessment,
    DecisionOutcome,
    DecisionPoint,
    ScopePacket,
)
from spec_manager.planner.constraints.types import ConstraintFact, ImpactClassification

# ---------------------------------------------------------------------------
# DecisionPoint
# ---------------------------------------------------------------------------


class TestDecisionPoint:
    def test_defaults(self):
        dp = DecisionPoint()
        assert dp.decision_id == ""
        assert dp.status == "OPEN"
        assert dp.impact.impact == "LOW"

    def test_to_dict_minimal(self):
        dp = DecisionPoint(decision_id="DEC-001")
        d = dp.to_dict()
        assert d["decision_id"] == "DEC-001"
        assert d["status"] == "OPEN"
        assert isinstance(d["impact"], dict)

    def test_round_trip(self):
        dp = DecisionPoint(
            decision_id="DEC-002",
            scope="inter:A->B",
            description="Choose caching strategy",
            trigger_evidence=["ev-1", "ev-2"],
            impact=ImpactClassification(impact="HIGH", blast_radius="CROSS_SLICE"),
            owner_slice_id="slice-a",
            status="EXPLORING",
            required_constraints=["CON-001"],
            candidate_refs=["CAND-1", "CAND-2"],
            selected_candidate_ref="CAND-1",
        )
        d = dp.to_dict()
        restored = DecisionPoint.from_dict(d)
        assert restored.decision_id == dp.decision_id
        assert restored.scope == dp.scope
        assert restored.description == dp.description
        assert restored.trigger_evidence == dp.trigger_evidence
        assert restored.impact.impact == "HIGH"
        assert restored.impact.blast_radius == "CROSS_SLICE"
        assert restored.owner_slice_id == dp.owner_slice_id
        assert restored.status == "EXPLORING"
        assert restored.required_constraints == ["CON-001"]
        assert restored.candidate_refs == ["CAND-1", "CAND-2"]
        assert restored.selected_candidate_ref == "CAND-1"

    def test_from_dict_missing_keys(self):
        dp = DecisionPoint.from_dict({})
        assert dp.decision_id == ""
        assert dp.status == "OPEN"
        assert dp.impact.impact == "LOW"

    def test_impact_nested_round_trip(self):
        dp = DecisionPoint(
            decision_id="DEC-003",
            impact=ImpactClassification(
                impact="MEDIUM",
                blast_radius="SYSTEM",
                reversibility="HARD",
                triggers=["cross-cutting concern"],
            ),
        )
        d = dp.to_dict()
        restored = DecisionPoint.from_dict(d)
        assert restored.impact.reversibility == "HARD"
        assert restored.impact.triggers == ["cross-cutting concern"]


# ---------------------------------------------------------------------------
# ScopePacket
# ---------------------------------------------------------------------------


class TestScopePacket:
    def test_defaults(self):
        sp = ScopePacket()
        assert sp.decision_id == ""
        assert sp.authoritative_constraints == []

    def test_round_trip(self):
        constraint = ConstraintFact(
            constraint_id="CON-001",
            question="Use async?",
            answer="Yes",
        )
        sp = ScopePacket(
            decision_id="DEC-001",
            scope="intra:LIB",
            trigger_evidence=["ev-1"],
            source_artifacts={"spec": "section-5"},
            authoritative_constraints=[constraint],
            current_arch_state_refs=["ref-1"],
            tradeoff_assignment={"performance": "prioritize"},
            positions_taken=["pos-1"],
        )
        d = sp.to_dict()
        restored = ScopePacket.from_dict(d)
        assert restored.decision_id == "DEC-001"
        assert restored.source_artifacts == {"spec": "section-5"}
        assert len(restored.authoritative_constraints) == 1
        assert restored.authoritative_constraints[0].constraint_id == "CON-001"
        assert restored.tradeoff_assignment == {"performance": "prioritize"}

    def test_from_dict_empty(self):
        sp = ScopePacket.from_dict({})
        assert sp.authoritative_constraints == []
        assert sp.tradeoff_assignment == {}

    def test_constraint_list_round_trip(self):
        constraints = [
            ConstraintFact(constraint_id=f"CON-{i}", question=f"Q{i}", answer=f"A{i}")
            for i in range(3)
        ]
        sp = ScopePacket(authoritative_constraints=constraints)
        d = sp.to_dict()
        restored = ScopePacket.from_dict(d)
        assert len(restored.authoritative_constraints) == 3
        assert restored.authoritative_constraints[2].constraint_id == "CON-2"


# ---------------------------------------------------------------------------
# ArchitectureCandidate
# ---------------------------------------------------------------------------


class TestArchitectureCandidate:
    def test_defaults(self):
        ac = ArchitectureCandidate()
        assert ac.candidate_id == ""
        assert ac.constraints_introduced == {"software": {}, "non_software": {}}

    def test_round_trip(self):
        ac = ArchitectureCandidate(
            candidate_id="CAND-001",
            decision_id="DEC-001",
            scope="intra:LIB",
            position={"performance": "prioritize", "simplicity": "sacrifice"},
            proposal={"approach": "event-driven", "details": "Use message queue"},
            constraints_introduced={
                "software": {"async-required": "Must use async IO"},
                "non_software": {"cost": "Additional infra cost"},
            },
            decision_requirements=["req-1"],
            assumptions=["assume-1", "assume-2"],
            trace=["step-1", "step-2"],
        )
        d = ac.to_dict()
        restored = ArchitectureCandidate.from_dict(d)
        assert restored.candidate_id == "CAND-001"
        assert restored.position == {"performance": "prioritize", "simplicity": "sacrifice"}
        assert restored.proposal["approach"] == "event-driven"
        assert restored.constraints_introduced["software"]["async-required"] == "Must use async IO"
        assert restored.decision_requirements == ["req-1"]
        assert restored.assumptions == ["assume-1", "assume-2"]
        assert restored.trace == ["step-1", "step-2"]

    def test_from_dict_missing_constraints_introduced(self):
        ac = ArchitectureCandidate.from_dict({"candidate_id": "CAND-X"})
        assert ac.constraints_introduced == {"software": {}, "non_software": {}}

    def test_mutation_isolation(self):
        ac = ArchitectureCandidate(
            candidate_id="CAND-002",
            trace=["a"],
        )
        d = ac.to_dict()
        d["trace"].append("b")
        assert ac.trace == ["a"]


# ---------------------------------------------------------------------------
# CandidateAssessment
# ---------------------------------------------------------------------------


class TestCandidateAssessment:
    def test_defaults(self):
        ca = CandidateAssessment()
        assert ca.risk_score == 0.0
        assert ca.recommendation == "accept"

    def test_round_trip(self):
        ca = CandidateAssessment(
            candidate_id="CAND-001",
            constraint_satisfaction={"CON-001": "satisfied", "CON-002": "violated"},
            blockers=["blocker-1"],
            risk_score=0.75,
            reversibility="HARD",
            recommendation="reject",
        )
        d = ca.to_dict()
        restored = CandidateAssessment.from_dict(d)
        assert restored.candidate_id == "CAND-001"
        assert restored.constraint_satisfaction["CON-002"] == "violated"
        assert restored.blockers == ["blocker-1"]
        assert restored.risk_score == 0.75
        assert restored.reversibility == "HARD"
        assert restored.recommendation == "reject"

    def test_from_dict_empty(self):
        ca = CandidateAssessment.from_dict({})
        assert ca.candidate_id == ""
        assert ca.risk_score == 0.0

    def test_all_recommendations(self):
        for rec in ("accept", "reject", "needs_human"):
            ca = CandidateAssessment(recommendation=rec)
            d = ca.to_dict()
            assert CandidateAssessment.from_dict(d).recommendation == rec


# ---------------------------------------------------------------------------
# DecisionOutcome
# ---------------------------------------------------------------------------


class TestDecisionOutcome:
    def test_defaults(self):
        do = DecisionOutcome()
        assert do.committed is False
        assert do.wiring_intentions == []

    def test_round_trip_committed(self):
        do = DecisionOutcome(
            decision_id="DEC-001",
            committed=True,
            selected_candidate_id="CAND-001",
            wiring_intentions=[{"source": "DEC-001", "approach": "event-driven"}],
            new_constraints=["async-required"],
        )
        d = do.to_dict()
        restored = DecisionOutcome.from_dict(d)
        assert restored.committed is True
        assert restored.selected_candidate_id == "CAND-001"
        assert len(restored.wiring_intentions) == 1
        assert restored.new_constraints == ["async-required"]

    def test_round_trip_blocked(self):
        do = DecisionOutcome(
            decision_id="DEC-002",
            committed=False,
            under_spec_events=[{"type": "architecture_blocked", "detail": "need info"}],
            decision_requirements=["req-1", "req-2"],
        )
        d = do.to_dict()
        restored = DecisionOutcome.from_dict(d)
        assert restored.committed is False
        assert len(restored.under_spec_events) == 1
        assert restored.decision_requirements == ["req-1", "req-2"]

    def test_from_dict_empty(self):
        do = DecisionOutcome.from_dict({})
        assert do.decision_id == ""
        assert do.committed is False

    def test_wiring_intentions_deep_copy(self):
        do = DecisionOutcome(
            wiring_intentions=[{"key": "val"}],
        )
        d = do.to_dict()
        d["wiring_intentions"][0]["key"] = "changed"
        assert do.wiring_intentions[0]["key"] == "val"
