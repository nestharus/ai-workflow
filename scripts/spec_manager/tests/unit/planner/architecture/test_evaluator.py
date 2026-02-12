"""Tests for spec_manager.planner.architecture.evaluator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from spec_manager.planner.architecture.evaluator import (
    CandidateEvaluator,
    _estimate_reversibility,
    _extract_new_constraint_ids,
    _extract_wiring_intentions,
)
from spec_manager.planner.architecture.types import (
    ArchitectureCandidate,
    CandidateAssessment,
    DecisionOutcome,
    DecisionPoint,
)
from spec_manager.planner.constraints.types import ConstraintFact, ImpactClassification


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def decision_point() -> DecisionPoint:
    return DecisionPoint(
        decision_id="DEC-001",
        scope="intra:LIB",
        description="Choose caching strategy",
        impact=ImpactClassification(impact="MEDIUM", blast_radius="SLICE"),
    )


@pytest.fixture()
def constraints() -> list[ConstraintFact]:
    return [
        ConstraintFact(
            constraint_id="CON-001",
            question="Use Redis?",
            answer="Yes",
            authority_required="planner_ok",
        ),
        ConstraintFact(
            constraint_id="CON-002",
            question="Max latency?",
            answer="100ms",
            authority_required="planner_ok",
        ),
    ]


@pytest.fixture()
def candidates() -> list[ArchitectureCandidate]:
    return [
        ArchitectureCandidate(
            candidate_id="CAND-001",
            decision_id="DEC-001",
            scope="intra:LIB",
            position={"performance": "prioritize"},
            proposal={"approach": "in-memory-cache", "details": "Local LRU cache"},
            constraints_introduced={"software": {"cache-ttl": "30s"}, "non_software": {}},
        ),
        ArchitectureCandidate(
            candidate_id="CAND-002",
            decision_id="DEC-001",
            scope="intra:LIB",
            position={"maintainability": "prioritize"},
            proposal={"approach": "redis-cache", "details": "Distributed Redis cache"},
            constraints_introduced={"software": {}, "non_software": {"infra": "Redis cluster"}},
            assumptions=["Redis available"],
        ),
    ]


# ---------------------------------------------------------------------------
# Heuristic evaluation (no LLM)
# ---------------------------------------------------------------------------


class TestHeuristicEvaluation:
    def test_evaluate_returns_one_per_candidate(
        self, workspace: Path, candidates, constraints
    ):
        evaluator = CandidateEvaluator(workspace)
        assessments = evaluator.evaluate(candidates, constraints)
        assert len(assessments) == 2
        ids = {a.candidate_id for a in assessments}
        assert ids == {"CAND-001", "CAND-002"}

    def test_no_human_required_all_accept(self, workspace: Path, candidates):
        constraints = [
            ConstraintFact(
                constraint_id="CON-001",
                authority_required="planner_ok",
            ),
        ]
        evaluator = CandidateEvaluator(workspace)
        assessments = evaluator.evaluate(candidates, constraints)
        cand_001 = next(a for a in assessments if a.candidate_id == "CAND-001")
        assert cand_001.recommendation == "accept"

    def test_human_required_triggers_needs_human(self, workspace: Path, candidates):
        constraints = [
            ConstraintFact(
                constraint_id="CON-HR",
                authority_required="human_required",
            ),
        ]
        evaluator = CandidateEvaluator(workspace)
        assessments = evaluator.evaluate(candidates, constraints)
        for a in assessments:
            assert a.recommendation == "needs_human"

    def test_decision_requirements_triggers_needs_human(self, workspace: Path, constraints):
        cand = ArchitectureCandidate(
            candidate_id="CAND-REQ",
            decision_requirements=["Need DB choice first"],
        )
        evaluator = CandidateEvaluator(workspace)
        assessments = evaluator.evaluate([cand], constraints)
        assert assessments[0].recommendation == "needs_human"

    def test_risk_score_increases_with_assumptions(self, workspace: Path, constraints):
        cand = ArchitectureCandidate(
            candidate_id="CAND-RISK",
            assumptions=["a1", "a2", "a3"],
        )
        evaluator = CandidateEvaluator(workspace)
        assessments = evaluator.evaluate([cand], constraints)
        assert assessments[0].risk_score >= 0.3


# ---------------------------------------------------------------------------
# LLM evaluation (mocked)
# ---------------------------------------------------------------------------


class TestLLMEvaluation:
    def test_evaluate_via_llm(self, workspace: Path, candidates, constraints):
        llm_response = json.dumps([
            {
                "candidate_id": "CAND-001",
                "constraint_satisfaction": {"CON-001": "satisfied", "CON-002": "satisfied"},
                "blockers": [],
                "risk_score": 0.1,
                "reversibility": "EASY",
                "recommendation": "accept",
            },
            {
                "candidate_id": "CAND-002",
                "constraint_satisfaction": {"CON-001": "satisfied", "CON-002": "unknown"},
                "blockers": [],
                "risk_score": 0.4,
                "reversibility": "MEDIUM",
                "recommendation": "needs_human",
            },
        ])
        mock_agent = lambda prompt: llm_response
        evaluator = CandidateEvaluator(workspace, run_agent=mock_agent)
        assessments = evaluator.evaluate(candidates, constraints)
        assert len(assessments) == 2
        a1 = next(a for a in assessments if a.candidate_id == "CAND-001")
        assert a1.recommendation == "accept"
        assert a1.risk_score == 0.1

    def test_llm_returns_garbage(self, workspace: Path, candidates, constraints):
        mock_agent = lambda prompt: "not json"
        evaluator = CandidateEvaluator(workspace, run_agent=mock_agent)
        assessments = evaluator.evaluate(candidates, constraints)
        # Should still produce one assessment per candidate (fallback)
        assert len(assessments) == 2
        for a in assessments:
            assert a.recommendation == "needs_human"

    def test_llm_misses_candidate(self, workspace: Path, candidates, constraints):
        llm_response = json.dumps([
            {
                "candidate_id": "CAND-001",
                "constraint_satisfaction": {},
                "blockers": [],
                "risk_score": 0.2,
                "reversibility": "EASY",
                "recommendation": "accept",
            },
        ])
        mock_agent = lambda prompt: llm_response
        evaluator = CandidateEvaluator(workspace, run_agent=mock_agent)
        assessments = evaluator.evaluate(candidates, constraints)
        assert len(assessments) == 2
        a2 = next(a for a in assessments if a.candidate_id == "CAND-002")
        assert a2.recommendation == "needs_human"


# ---------------------------------------------------------------------------
# select_or_block
# ---------------------------------------------------------------------------


class TestSelectOrBlock:
    def test_commit_best_acceptable(self, workspace: Path, decision_point, candidates):
        assessments = [
            CandidateAssessment(
                candidate_id="CAND-001",
                recommendation="accept",
                risk_score=0.3,
            ),
            CandidateAssessment(
                candidate_id="CAND-002",
                recommendation="accept",
                risk_score=0.1,
            ),
        ]
        evaluator = CandidateEvaluator(workspace)
        outcome = evaluator.select_or_block(
            decision_point, candidates, assessments, []
        )
        assert outcome.committed is True
        assert outcome.selected_candidate_id == "CAND-002"  # lowest risk

    def test_block_when_needs_human(self, workspace: Path, decision_point, candidates):
        assessments = [
            CandidateAssessment(
                candidate_id="CAND-001",
                recommendation="needs_human",
                risk_score=0.5,
            ),
            CandidateAssessment(
                candidate_id="CAND-002",
                recommendation="reject",
                blockers=["violates constraint"],
                risk_score=0.9,
            ),
        ]
        evaluator = CandidateEvaluator(workspace)
        outcome = evaluator.select_or_block(
            decision_point, candidates, assessments, []
        )
        assert outcome.committed is False
        assert len(outcome.decision_requirements) > 0

    def test_block_when_all_rejected(self, workspace: Path, decision_point, candidates):
        assessments = [
            CandidateAssessment(
                candidate_id="CAND-001",
                recommendation="reject",
                blockers=["blocker-1"],
            ),
            CandidateAssessment(
                candidate_id="CAND-002",
                recommendation="reject",
                blockers=["blocker-2"],
            ),
        ]
        evaluator = CandidateEvaluator(workspace)
        outcome = evaluator.select_or_block(
            decision_point, candidates, assessments, []
        )
        assert outcome.committed is False
        assert len(outcome.under_spec_events) > 0

    def test_empty_candidates(self, workspace: Path, decision_point):
        evaluator = CandidateEvaluator(workspace)
        outcome = evaluator.select_or_block(decision_point, [], [], [])
        assert outcome.committed is False
        assert "No candidates" in outcome.decision_requirements[0]

    def test_commit_extracts_wiring_intentions(
        self, workspace: Path, decision_point, candidates
    ):
        assessments = [
            CandidateAssessment(
                candidate_id="CAND-001",
                recommendation="accept",
                risk_score=0.0,
            ),
        ]
        evaluator = CandidateEvaluator(workspace)
        outcome = evaluator.select_or_block(
            decision_point, [candidates[0]], assessments, []
        )
        assert outcome.committed is True
        assert len(outcome.wiring_intentions) == 1
        assert outcome.wiring_intentions[0]["approach"] == "in-memory-cache"

    def test_commit_extracts_new_constraints(
        self, workspace: Path, decision_point, candidates
    ):
        assessments = [
            CandidateAssessment(
                candidate_id="CAND-001",
                recommendation="accept",
                risk_score=0.0,
            ),
        ]
        evaluator = CandidateEvaluator(workspace)
        outcome = evaluator.select_or_block(
            decision_point, [candidates[0]], assessments, []
        )
        assert "cache-ttl" in outcome.new_constraints

    def test_unknown_satisfaction_blocks_accept(
        self, workspace: Path, decision_point, candidates
    ):
        assessments = [
            CandidateAssessment(
                candidate_id="CAND-001",
                recommendation="accept",
                constraint_satisfaction={"CON-001": "unknown"},
                risk_score=0.0,
            ),
        ]
        evaluator = CandidateEvaluator(workspace)
        outcome = evaluator.select_or_block(
            decision_point, [candidates[0]], assessments, []
        )
        # Unknown constraint means needs_human path, not commit
        assert outcome.committed is False


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_estimate_reversibility_local(self):
        cand = ArchitectureCandidate(scope="intra:LIB")
        assert _estimate_reversibility(cand) == "EASY"

    def test_estimate_reversibility_inter(self):
        cand = ArchitectureCandidate(scope="inter:A->B")
        assert _estimate_reversibility(cand) == "MEDIUM"

    def test_estimate_reversibility_system(self):
        cand = ArchitectureCandidate(scope="system")
        assert _estimate_reversibility(cand) == "HARD"

    def test_extract_wiring_intentions(self):
        cand = ArchitectureCandidate(
            decision_id="DEC-X",
            scope="intra:LIB",
            proposal={"approach": "A", "details": "D"},
        )
        intentions = _extract_wiring_intentions(cand)
        assert len(intentions) == 1
        assert intentions[0]["source"] == "DEC-X"

    def test_extract_new_constraint_ids(self):
        cand = ArchitectureCandidate(
            constraints_introduced={
                "software": {"sw-1": "val1", "sw-2": "val2"},
                "non_software": {"nsw-1": "val3"},
            }
        )
        ids = _extract_new_constraint_ids(cand)
        assert set(ids) == {"sw-1", "sw-2", "nsw-1"}
