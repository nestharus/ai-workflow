"""Tests for AuthorityDeciderStrategy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spec_manager.planner.strategies.protocol import PlanningSession
from spec_manager.planner.strategies.authority_strategy import AuthorityDeciderStrategy
from spec_manager.planner.constraints.types import (
    ConstraintContext,
    ConstraintFact,
    DecisionRequirement,
    ImpactClassification,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session_with_new_constraints(
    tmp_path: Path,
    *,
    impact: str = "MEDIUM",
    constraints: list[ConstraintFact] | None = None,
    requirements: list[DecisionRequirement] | None = None,
) -> PlanningSession:
    return PlanningSession(
        ctx={"slice_id": "test_lib"},
        impact=ImpactClassification(impact=impact),
        constraint_context=ConstraintContext(
            authoritative=[
                ConstraintFact(
                    constraint_id="CON-001",
                    dimension="software",
                    validated=True,
                )
            ]
        ),
        new_constraints=list(constraints or []),
        decision_requirements=list(requirements or []),
    )


# ---------------------------------------------------------------------------
# Tests: Authority check on new_constraints
# ---------------------------------------------------------------------------


class TestAuthorityDeciderConstraints:
    def test_planner_ok_constraint_persisted(self, tmp_path):
        s = AuthorityDeciderStrategy(workspace_root=tmp_path)
        fact = ConstraintFact(
            constraint_id="CON-NEW-001",
            question="Use JSON?",
            answer="Yes",
            dimension="software",
        )
        session = _session_with_new_constraints(tmp_path, constraints=[fact])
        result = s.run(session)

        # Constraint should be persisted (removed from new_constraints)
        assert len(result.new_constraints) == 0
        # Verify file was written
        constraints_dir = tmp_path / "analysis" / "constraints"
        assert constraints_dir.exists()

    def test_human_required_constraint_escalated(self, tmp_path):
        s = AuthorityDeciderStrategy(workspace_root=tmp_path)
        fact = ConstraintFact(
            constraint_id="CON-LEGAL-001",
            question="GDPR compliant?",
            answer="Unclear",
            dimension="legal",  # legal requires human
        )
        session = _session_with_new_constraints(tmp_path, constraints=[fact])
        result = s.run(session)

        # Constraint should remain in new_constraints (human_required)
        assert len(result.new_constraints) == 1
        assert result.new_constraints[0].authority_required == "human_required"
        # Under-spec event should be emitted
        auth_events = [e for e in result.under_spec_events if e["type"] == "authority_required"]
        assert len(auth_events) == 1
        assert auth_events[0]["constraint_id"] == "CON-LEGAL-001"

    def test_high_impact_always_requires_human(self, tmp_path):
        s = AuthorityDeciderStrategy(workspace_root=tmp_path)
        fact = ConstraintFact(
            constraint_id="CON-SW-001",
            question="Use gRPC?",
            answer="Yes",
            dimension="software",
        )
        session = _session_with_new_constraints(
            tmp_path, impact="HIGH", constraints=[fact]
        )
        result = s.run(session)

        # HIGH impact -> human_required even for software dimension
        assert len(result.new_constraints) == 1
        auth_events = [e for e in result.under_spec_events if e["type"] == "authority_required"]
        assert len(auth_events) == 1

    def test_mixed_constraints(self, tmp_path):
        s = AuthorityDeciderStrategy(workspace_root=tmp_path)
        sw_fact = ConstraintFact(
            constraint_id="CON-SW-001",
            question="Use JSON?",
            answer="Yes",
            dimension="software",
        )
        legal_fact = ConstraintFact(
            constraint_id="CON-LEGAL-001",
            question="GDPR?",
            answer="Unknown",
            dimension="legal",
        )
        session = _session_with_new_constraints(
            tmp_path, constraints=[sw_fact, legal_fact]
        )
        result = s.run(session)

        # Software: planner_ok -> persisted; Legal: human_required -> escalated
        # Note: check_authority checks constraints_introduced count=2 which is <= 3
        # so software should be ok, legal should escalate
        remaining_ids = {c.constraint_id for c in result.new_constraints}
        assert "CON-LEGAL-001" in remaining_ids

    def test_no_impact_skips(self, tmp_path):
        s = AuthorityDeciderStrategy(workspace_root=tmp_path)
        session = PlanningSession(
            ctx={"slice_id": "test_lib"},
            new_constraints=[ConstraintFact(constraint_id="CON-001")],
        )
        result = s.run(session)
        # No impact -> strategy returns early, constraints unchanged
        assert len(result.new_constraints) == 1


# ---------------------------------------------------------------------------
# Tests: Authority check on decision_requirements
# ---------------------------------------------------------------------------


class TestAuthorityDeciderRequirements:
    def test_planner_ok_requirement_kept(self, tmp_path):
        s = AuthorityDeciderStrategy(workspace_root=tmp_path)
        dr = DecisionRequirement(
            decision_id="DR-001",
            question="Which format?",
            kind="tech_choice",
            dimension="software",
        )
        session = _session_with_new_constraints(tmp_path, requirements=[dr])
        result = s.run(session)

        # planner_ok: kept in decision_requirements, NOT escalated
        assert len(result.decision_requirements) == 1
        assert result.decision_requirements[0].decision_id == "DR-001"

    def test_human_required_requirement_escalated(self, tmp_path):
        s = AuthorityDeciderStrategy(workspace_root=tmp_path)
        dr = DecisionRequirement(
            decision_id="DR-LEGAL",
            question="Licensing model?",
            kind="legal_choice",
            dimension="legal",
        )
        session = _session_with_new_constraints(tmp_path, requirements=[dr])
        result = s.run(session)

        # legal -> human_required: removed from decision_requirements
        assert len(result.decision_requirements) == 0
        # Emitted as under_spec_event
        decision_events = [e for e in result.under_spec_events if e["type"] == "decision_required"]
        assert len(decision_events) == 1
        assert decision_events[0]["decision_id"] == "DR-LEGAL"

    def test_economic_dimension_escalated(self, tmp_path):
        s = AuthorityDeciderStrategy(workspace_root=tmp_path)
        dr = DecisionRequirement(
            decision_id="DR-COST",
            question="Cloud provider?",
            kind="economic_choice",
            dimension="economic",
        )
        session = _session_with_new_constraints(tmp_path, requirements=[dr])
        result = s.run(session)

        assert len(result.decision_requirements) == 0
        decision_events = [e for e in result.under_spec_events if e["type"] == "decision_required"]
        assert len(decision_events) == 1


# ---------------------------------------------------------------------------
# Tests: Meta
# ---------------------------------------------------------------------------


class TestAuthorityDeciderMeta:
    def test_name(self, tmp_path):
        s = AuthorityDeciderStrategy(workspace_root=tmp_path)
        assert s.name == "authority_decider"
