from __future__ import annotations

import json

import pytest
from spec_manager.orchestration.under_spec.manager import ConstraintsStore
from spec_manager.orchestration.under_spec.planning_gate import (
    CoverageResult,
    PlanningGateResult,
    check_decision_coverage,
    run_planning_gate,
)

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def constraints_store(tmp_path):
    store = ConstraintsStore(tmp_path)
    constraints_path = tmp_path / "analysis" / "constraints" / "test-slice.json"
    constraints_path.parent.mkdir(parents=True, exist_ok=True)
    constraints_path.write_text(
        json.dumps(
            [
                {
                    "constraint_id": "C1",
                    "question": "What auth method to use?",
                    "answer": "JWT",
                    "resolved": True,
                },
                {
                    "constraint_id": "C2",
                    "question": "Which database?",
                    "answer": "PostgreSQL",
                    "resolved": True,
                },
            ]
        )
    )
    return store


# ------------------------------------------------------------------
# CoverageResult / PlanningGateResult dataclass basics
# ------------------------------------------------------------------


def test_coverage_result_defaults():
    r = CoverageResult()
    assert r.covered is False
    assert r.covering_constraints == []
    assert r.rationale == ""


def test_planning_gate_result_all_covered_when_empty():
    r = PlanningGateResult()
    assert r.all_covered is True


def test_planning_gate_result_not_all_covered():
    r = PlanningGateResult(uncovered_decisions=[{"decision_id": "D1"}])
    assert r.all_covered is False


# ------------------------------------------------------------------
# check_decision_coverage
# ------------------------------------------------------------------


def test_coverage_matches_by_constraint_id(constraints_store):
    """Decision with decision_id == C1 should be covered."""
    result = check_decision_coverage(
        constraints_store=constraints_store,
        slice_id="test-slice",
        decision={"decision_id": "C1", "question": "irrelevant question text"},
    )
    assert result.covered is True
    assert "C1" in result.covering_constraints


def test_coverage_matches_by_question_substring(constraints_store):
    """Decision whose question is a substring of constraint C2's question."""
    result = check_decision_coverage(
        constraints_store=constraints_store,
        slice_id="test-slice",
        decision={"decision_id": "D99", "question": "Which database?"},
    )
    assert result.covered is True
    assert len(result.covering_constraints) >= 1


def test_coverage_no_match(constraints_store):
    """Decision that matches neither ID nor question substring."""
    result = check_decision_coverage(
        constraints_store=constraints_store,
        slice_id="test-slice",
        decision={"decision_id": "D100", "question": "How to handle caching?"},
    )
    assert result.covered is False
    assert result.covering_constraints == []
    assert "No constraint covers" in result.rationale


def test_coverage_empty_constraints(tmp_path):
    """No constraints file at all -> not covered."""
    store = ConstraintsStore(tmp_path)
    result = check_decision_coverage(
        constraints_store=store,
        slice_id="nonexistent-slice",
        decision={"decision_id": "D1", "question": "anything"},
    )
    assert result.covered is False


# ------------------------------------------------------------------
# run_planning_gate
# ------------------------------------------------------------------


def test_run_planning_gate_all_covered(constraints_store):
    """All decisions have matching constraints -> no under-spec events."""
    intentions = [
        {
            "intention_id": "I1",
            "target_file": "auth.py",
            "decision_requirements": [
                {"decision_id": "C1", "question": "What auth method to use?"},
                {"decision_id": "C2", "question": "Which database?"},
            ],
        },
    ]
    result = run_planning_gate(
        constraints_store=constraints_store,
        slice_id="test-slice",
        intentions=intentions,
    )
    assert result.all_covered is True
    assert len(result.covered_decisions) == 2
    assert len(result.uncovered_decisions) == 0
    assert len(result.under_spec_events) == 0


def test_run_planning_gate_partially_covered(constraints_store):
    """One decision matches, the other does not -> under-spec events emitted."""
    intentions = [
        {
            "intention_id": "I1",
            "target_file": "service.py",
            "decision_requirements": [
                {"decision_id": "C1", "question": "What auth method to use?"},
                {"decision_id": "D999", "question": "How to handle rate limiting?"},
            ],
        },
    ]
    result = run_planning_gate(
        constraints_store=constraints_store,
        slice_id="test-slice",
        intentions=intentions,
    )
    assert result.all_covered is False
    assert len(result.covered_decisions) == 1
    assert len(result.uncovered_decisions) == 1
    assert result.uncovered_decisions[0]["decision_id"] == "D999"
    assert len(result.under_spec_events) == 1
    assert result.under_spec_events[0]["kind"] == "MISSING_CONSTRAINT"


def test_run_planning_gate_no_decision_requirements(constraints_store):
    """Intentions without decision_requirements produce empty result."""
    intentions = [
        {"intention_id": "I1", "target_file": "simple.py"},
        {"intention_id": "I2", "target_file": "also_simple.py", "decision_requirements": []},
    ]
    result = run_planning_gate(
        constraints_store=constraints_store,
        slice_id="test-slice",
        intentions=intentions,
    )
    assert result.all_covered is True
    assert result.covered_decisions == []
    assert result.uncovered_decisions == []
    assert result.under_spec_events == []


def test_run_planning_gate_under_spec_event_carries_needed_for(constraints_store):
    """Under-spec event should record 'needed_for' from decision or intention."""
    intentions = [
        {
            "intention_id": "I1",
            "target_file": "important.py",
            "decision_requirements": [
                {
                    "decision_id": "D50",
                    "question": "What logging framework?",
                    "needed_for": "logging_module.py",
                    "options": ["loguru", "stdlib"],
                },
            ],
        },
    ]
    result = run_planning_gate(
        constraints_store=constraints_store,
        slice_id="test-slice",
        intentions=intentions,
    )
    event = result.under_spec_events[0]
    assert event["needed_for"] == "logging_module.py"
    assert event["options"] == ["loguru", "stdlib"]
