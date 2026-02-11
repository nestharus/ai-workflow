"""Tests for planner eval scorers: base, resolve_signal, plan, under_spec, integration_analysis.

Covers the Verdict dataclass, _matches_atom helper, and all four concrete
scorer classes with ~30 test functions exercising happy paths, edge cases,
hard-gate failures, and empty ground-truth handling.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from spec_manager.refinement.evals.planner.scorers.base import (
    Verdict,
    _matches_atom,
)
from spec_manager.refinement.evals.planner.scorers.integration_analysis import (
    IntegrationAnalysisScorer,
)
from spec_manager.refinement.evals.planner.scorers.plan import PlanScorer
from spec_manager.refinement.evals.planner.scorers.resolve_signal import (
    ResolveSignalScorer,
)
from spec_manager.refinement.evals.planner.scorers.under_spec import (
    UnderSpecScorer,
)


# ------------------------------------------------------------------
# Helpers: lightweight stand-ins for trace / gt_case objects
# ------------------------------------------------------------------


def _make_trace(
    outputs: dict[str, Any] | None = None,
    decision: dict[str, Any] | None = None,
) -> SimpleNamespace:
    """Build a minimal trace-like object accepted by all scorers."""
    return SimpleNamespace(
        artifacts={"outputs": outputs or {}},
        decision=decision or {},
    )


def _make_gt(expected: dict[str, Any] | None = None) -> SimpleNamespace:
    """Build a minimal ground-truth case-like object."""
    return SimpleNamespace(expected=expected or {})


# ====================================================================
# 1. Verdict dataclass
# ====================================================================


class TestVerdict:
    """Verify Verdict defaults and field assignment."""

    def test_verdict_defaults(self) -> None:
        """A default Verdict should be passing with score 1.0."""
        v = Verdict()
        assert v.passed is True
        assert v.score == 1.0
        assert v.hard_gate_failures == []
        assert v.soft_signal_warnings == []
        assert v.decision_key == ""

    def test_verdict_custom_fields(self) -> None:
        """Fields passed to the constructor should override defaults."""
        v = Verdict(
            decision_key="dk-1",
            trace_id="t-99",
            capability="plan",
            passed=False,
            score=0.5,
            detail="half credit",
            hard_gate_failures=["gate_a"],
            soft_signal_warnings=["warn_b"],
        )
        assert v.decision_key == "dk-1"
        assert v.trace_id == "t-99"
        assert v.capability == "plan"
        assert v.passed is False
        assert v.score == 0.5
        assert v.detail == "half credit"
        assert v.hard_gate_failures == ["gate_a"]
        assert v.soft_signal_warnings == ["warn_b"]


# ====================================================================
# 2. _matches_atom helper
# ====================================================================


class TestMatchesAtom:
    """Verify _matches_atom matching logic with various criteria."""

    def test_function_name_any_of_match(self) -> None:
        """Match succeeds when function_name is in the allowed list."""
        intention = {"function_name": "validate", "file": "a.py"}
        spec = {"function_name_any_of": ["validate", "process"]}
        assert _matches_atom(intention, spec) is True

    def test_function_name_any_of_miss(self) -> None:
        """Match fails when function_name is NOT in the allowed list."""
        intention = {"function_name": "execute", "file": "a.py"}
        spec = {"function_name_any_of": ["validate", "process"]}
        assert _matches_atom(intention, spec) is False

    def test_file_any_of_match(self) -> None:
        """Match succeeds when file is in the allowed list."""
        intention = {"function_name": "f", "file": "src/core.py"}
        spec = {"file_any_of": ["src/core.py", "src/util.py"]}
        assert _matches_atom(intention, spec) is True

    def test_component_id_any_of_match(self) -> None:
        """Match succeeds when component_id is in the allowed list."""
        intention = {"component_id": "auth_service"}
        spec = {"component_id_any_of": ["auth_service", "db_service"]}
        assert _matches_atom(intention, spec) is True

    def test_function_name_regex_match(self) -> None:
        """Match succeeds when function_name matches the regex."""
        intention = {"function_name": "get_user_by_id"}
        spec = {"function_name_regex": r"get_.*_by_id"}
        assert _matches_atom(intention, spec) is True

    def test_function_name_regex_miss(self) -> None:
        """Match fails when function_name does not match the regex."""
        intention = {"function_name": "update_user"}
        spec = {"function_name_regex": r"get_.*_by_id"}
        assert _matches_atom(intention, spec) is False

    def test_description_contains_case_insensitive(self) -> None:
        """description_contains matching is case-insensitive."""
        intention = {"description": "Validate the Payment amount"}
        spec = {"description_contains": "validate the payment"}
        assert _matches_atom(intention, spec) is True

    def test_and_semantics_all_must_match(self) -> None:
        """When multiple criteria are present, ALL must match (AND)."""
        intention = {"function_name": "validate", "file": "src/core.py"}
        spec = {
            "function_name_any_of": ["validate"],
            "file_any_of": ["src/core.py"],
        }
        assert _matches_atom(intention, spec) is True

    def test_and_semantics_partial_fails(self) -> None:
        """If one criterion in a multi-criteria spec fails, result is False."""
        intention = {"function_name": "validate", "file": "src/other.py"}
        spec = {
            "function_name_any_of": ["validate"],
            "file_any_of": ["src/core.py"],
        }
        assert _matches_atom(intention, spec) is False

    def test_empty_spec_returns_false(self) -> None:
        """An empty match spec should never match anything."""
        intention = {"function_name": "anything"}
        assert _matches_atom(intention, {}) is False

    def test_unrecognised_keys_only_returns_false(self) -> None:
        """A spec with only unknown keys produces no checks, so returns False."""
        intention = {"function_name": "anything"}
        spec = {"unknown_key": ["value"]}
        assert _matches_atom(intention, spec) is False

    def test_missing_intention_fields_default_to_empty(self) -> None:
        """If the intention dict lacks a field, it defaults to empty string."""
        intention = {}  # no function_name
        spec = {"function_name_any_of": [""]}
        # Empty string IS in the list, so should match.
        assert _matches_atom(intention, spec) is True


# ====================================================================
# 3. ResolveSignalScorer
# ====================================================================


class TestResolveSignalScorer:
    """Tests for ResolveSignalScorer covering the should_resolve truth table."""

    @pytest.fixture()
    def scorer(self) -> ResolveSignalScorer:
        return ResolveSignalScorer()

    def test_should_resolve_true_correct_answer(
        self, scorer: ResolveSignalScorer
    ) -> None:
        """When should_resolve=true and the answer matches, verdict passes."""
        trace = _make_trace(outputs={"response": "Use the new auth flow"})
        gt = _make_gt(
            expected={
                "should_resolve": True,
                "answers_any_of": ["auth flow"],
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.passed is True
        assert verdict.score == 1.0
        assert verdict.hard_gate_failures == []
        assert "matches expected" in verdict.detail.lower()

    def test_should_resolve_true_wrong_answer(
        self, scorer: ResolveSignalScorer
    ) -> None:
        """When should_resolve=true but the answer does not match, hard gate fails."""
        trace = _make_trace(outputs={"response": "Something unrelated"})
        gt = _make_gt(
            expected={
                "should_resolve": True,
                "answers_any_of": ["auth flow", "token refresh"],
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.passed is False
        assert verdict.score == 0.0
        assert "wrong_answer" in verdict.hard_gate_failures

    def test_should_resolve_true_empty_answer(
        self, scorer: ResolveSignalScorer
    ) -> None:
        """When should_resolve=true but the answer is empty, missing_answer hard gate."""
        trace = _make_trace(outputs={"response": ""})
        gt = _make_gt(
            expected={
                "should_resolve": True,
                "answers_any_of": [],
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.passed is False
        assert "missing_answer" in verdict.hard_gate_failures

    def test_should_resolve_false_correctly_noop(
        self, scorer: ResolveSignalScorer
    ) -> None:
        """When should_resolve=false and answer is empty/NOOP, verdict passes."""
        trace = _make_trace(outputs={"response": "NOOP"})
        gt = _make_gt(expected={"should_resolve": False})
        verdict = scorer.score(trace, gt)
        assert verdict.passed is True
        assert verdict.score == 1.0

    def test_should_resolve_false_but_answered(
        self, scorer: ResolveSignalScorer
    ) -> None:
        """When should_resolve=false but answer is non-empty, false_resolve hard gate."""
        trace = _make_trace(outputs={"response": "I resolved it anyway"})
        gt = _make_gt(expected={"should_resolve": False})
        verdict = scorer.score(trace, gt)
        assert verdict.passed is False
        assert verdict.score == 0.0
        assert "false_resolve" in verdict.hard_gate_failures

    def test_must_cite_present(self, scorer: ResolveSignalScorer) -> None:
        """When must_cite references are found, no warnings."""
        trace = _make_trace(
            outputs={
                "response": "Use auth flow",
                "evidence_refs": ["REF-001", "REF-002"],
            },
        )
        gt = _make_gt(
            expected={
                "should_resolve": True,
                "answers_any_of": ["auth flow"],
                "must_cite": ["REF-001"],
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.passed is True
        assert verdict.soft_signal_warnings == []

    def test_must_cite_missing(self, scorer: ResolveSignalScorer) -> None:
        """When must_cite references are not found, soft warning issued."""
        trace = _make_trace(
            outputs={"response": "Use auth flow"},
        )
        gt = _make_gt(
            expected={
                "should_resolve": True,
                "answers_any_of": ["auth flow"],
                "must_cite": ["REF-MISSING"],
            }
        )
        verdict = scorer.score(trace, gt)
        # Missing citations are soft warnings, not hard gate failures.
        assert verdict.passed is True
        assert any("REF-MISSING" in w for w in verdict.soft_signal_warnings)

    def test_no_should_resolve_in_gt(
        self, scorer: ResolveSignalScorer
    ) -> None:
        """When ground truth has no should_resolve key, neutral verdict."""
        trace = _make_trace(outputs={"response": "anything"})
        gt = _make_gt(expected={})
        verdict = scorer.score(trace, gt)
        assert verdict.passed is True
        assert verdict.score == 1.0
        assert "neutral" in verdict.detail.lower()

    def test_decision_text_fallback(
        self, scorer: ResolveSignalScorer
    ) -> None:
        """When outputs.response is empty, falls back to decision.decision_text."""
        trace = _make_trace(
            outputs={"response": ""},
            decision={"decision_text": "Use auth flow"},
        )
        gt = _make_gt(
            expected={
                "should_resolve": True,
                "answers_any_of": ["auth flow"],
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.passed is True
        assert verdict.score == 1.0


# ====================================================================
# 4. PlanScorer
# ====================================================================


class TestPlanScorer:
    """Tests for PlanScorer covering recall, precision, invariants, and thresholds."""

    @pytest.fixture()
    def scorer(self) -> PlanScorer:
        return PlanScorer()

    def test_must_include_full_recall(self, scorer: PlanScorer) -> None:
        """All must_include atoms matched gives recall=1.0."""
        trace = _make_trace(
            outputs={
                "intentions": [
                    {"function_name": "validate", "file": "src/core.py"},
                    {"function_name": "process", "file": "src/core.py"},
                ]
            }
        )
        gt = _make_gt(
            expected={
                "must_include": [
                    {"match": {"function_name_any_of": ["validate"]}},
                    {"match": {"function_name_any_of": ["process"]}},
                ],
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.passed is True
        assert verdict.score == 1.0
        assert "recall=1.00" in verdict.detail

    def test_must_include_partial_recall(self, scorer: PlanScorer) -> None:
        """Only 1/2 must_include atoms matched gives recall=0.50."""
        trace = _make_trace(
            outputs={
                "intentions": [
                    {"function_name": "validate", "file": "src/core.py"},
                ]
            }
        )
        gt = _make_gt(
            expected={
                "must_include": [
                    {"match": {"function_name_any_of": ["validate"]}},
                    {"match": {"function_name_any_of": ["process"]}},
                ],
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.score == pytest.approx(0.5)
        assert "recall=0.50" in verdict.detail

    def test_must_not_include_no_violations(self, scorer: PlanScorer) -> None:
        """No must_not_include violations gives precision=1.0."""
        trace = _make_trace(
            outputs={
                "intentions": [
                    {"function_name": "validate", "file": "src/core.py"},
                ]
            }
        )
        gt = _make_gt(
            expected={
                "must_not_include": [
                    {"match": {"function_name_any_of": ["forbidden_func"]}},
                ],
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.passed is True
        assert verdict.score == 1.0

    def test_must_not_include_violation_lowers_precision(
        self, scorer: PlanScorer
    ) -> None:
        """A must_not_include violation reduces precision."""
        trace = _make_trace(
            outputs={
                "intentions": [
                    {"function_name": "forbidden_func", "file": "src/core.py"},
                ]
            }
        )
        gt = _make_gt(
            expected={
                "must_not_include": [
                    {"match": {"function_name_any_of": ["forbidden_func"]}},
                    {"match": {"function_name_any_of": ["other_bad"]}},
                ],
            }
        )
        verdict = scorer.score(trace, gt)
        # 1 of 2 must_not_include violated => precision = 1 - 1/2 = 0.5
        assert verdict.score == pytest.approx(0.5)

    def test_dedupe_invariant_no_duplicates(self, scorer: PlanScorer) -> None:
        """Dedupe invariant passes when there are no duplicates."""
        trace = _make_trace(
            outputs={
                "intentions": [
                    {"function_name": "a", "file": "x.py"},
                    {"function_name": "b", "file": "y.py"},
                ]
            }
        )
        gt = _make_gt(
            expected={
                "invariants": [
                    {
                        "type": "dedupe",
                        "key_fields": ["function_name", "file"],
                        "max_duplicates": 0,
                    }
                ],
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.passed is True
        assert not any("dedupe" in f for f in verdict.hard_gate_failures)

    def test_dedupe_invariant_with_duplicates(
        self, scorer: PlanScorer
    ) -> None:
        """Dedupe invariant fails when duplicate intentions exist."""
        trace = _make_trace(
            outputs={
                "intentions": [
                    {"function_name": "a", "file": "x.py"},
                    {"function_name": "a", "file": "x.py"},
                    {"function_name": "b", "file": "y.py"},
                ]
            }
        )
        gt = _make_gt(
            expected={
                "invariants": [
                    {
                        "type": "dedupe",
                        "key_fields": ["function_name", "file"],
                        "max_duplicates": 0,
                    }
                ],
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.passed is False
        assert any("dedupe_violation" in f for f in verdict.hard_gate_failures)

    def test_scope_invariant_all_in_scope(self, scorer: PlanScorer) -> None:
        """Scope invariant passes when all files are under the expected root."""
        trace = _make_trace(
            outputs={
                "intentions": [
                    {"function_name": "a", "file": "src/core.py"},
                    {"function_name": "b", "file": "src/util.py"},
                ]
            }
        )
        gt = _make_gt(
            expected={
                "invariants": [{"type": "scope", "root": "src/"}],
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.passed is True

    def test_scope_invariant_out_of_scope(self, scorer: PlanScorer) -> None:
        """Scope invariant fails when a file is outside the expected root."""
        trace = _make_trace(
            outputs={
                "intentions": [
                    {"function_name": "a", "file": "src/core.py"},
                    {"function_name": "b", "file": "tests/test_core.py"},
                ]
            }
        )
        gt = _make_gt(
            expected={
                "invariants": [{"type": "scope", "root": "src/"}],
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.passed is False
        assert any("scope_violation" in f for f in verdict.hard_gate_failures)

    def test_threshold_recall_breach(self, scorer: PlanScorer) -> None:
        """When recall falls below threshold, hard gate failure is raised."""
        trace = _make_trace(outputs={"intentions": []})
        gt = _make_gt(
            expected={
                "must_include": [
                    {"match": {"function_name_any_of": ["validate"]}},
                ],
                "thresholds": {"recall": 0.8},
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.passed is False
        assert any(
            "recall_below_threshold" in f for f in verdict.hard_gate_failures
        )

    def test_threshold_precision_breach(self, scorer: PlanScorer) -> None:
        """When precision falls below threshold, hard gate failure is raised."""
        trace = _make_trace(
            outputs={
                "intentions": [
                    {"function_name": "forbidden_func", "file": "a.py"},
                ]
            }
        )
        gt = _make_gt(
            expected={
                "must_not_include": [
                    {"match": {"function_name_any_of": ["forbidden_func"]}},
                ],
                "thresholds": {"precision": 0.9},
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.passed is False
        assert any(
            "precision_below_threshold" in f
            for f in verdict.hard_gate_failures
        )

    def test_empty_gt_gives_perfect_score(self, scorer: PlanScorer) -> None:
        """An empty expected dict results in a passing score of 1.0."""
        trace = _make_trace(
            outputs={"intentions": [{"function_name": "a", "file": "b.py"}]}
        )
        gt = _make_gt(expected={})
        verdict = scorer.score(trace, gt)
        assert verdict.passed is True
        assert verdict.score == 1.0

    def test_score_is_min_of_recall_and_precision(
        self, scorer: PlanScorer
    ) -> None:
        """Score is min(recall, precision): lower of the two wins."""
        trace = _make_trace(
            outputs={
                "intentions": [
                    {"function_name": "validate", "file": "src/core.py"},
                    {"function_name": "forbidden_func", "file": "src/core.py"},
                ]
            }
        )
        gt = _make_gt(
            expected={
                "must_include": [
                    {"match": {"function_name_any_of": ["validate"]}},
                    {"match": {"function_name_any_of": ["process"]}},
                ],
                "must_not_include": [
                    {"match": {"function_name_any_of": ["forbidden_func"]}},
                ],
            }
        )
        verdict = scorer.score(trace, gt)
        # recall = 1/2 = 0.5, precision = 1 - 1/1 = 0.0
        assert verdict.score == pytest.approx(0.0)


# ====================================================================
# 5. UnderSpecScorer
# ====================================================================


class TestUnderSpecScorer:
    """Tests for UnderSpecScorer covering the should_block truth table."""

    @pytest.fixture()
    def scorer(self) -> UnderSpecScorer:
        return UnderSpecScorer()

    def test_correct_block(self, scorer: UnderSpecScorer) -> None:
        """Planner correctly blocks an event that should be blocked."""
        trace = _make_trace(
            outputs={"blocked": True, "constraints": {}, "questions": []}
        )
        gt = _make_gt(
            expected={
                "events": [{"event_id": "evt_001", "should_block": True}]
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.passed is True
        assert verdict.score > 0.0
        assert not verdict.hard_gate_failures

    def test_false_unblock_is_hard_gate_failure(
        self, scorer: UnderSpecScorer
    ) -> None:
        """Planner resolves (provides constraint) for an event that should be blocked = hard gate."""
        trace = _make_trace(
            outputs={
                "blocked": False,
                "constraints": {"evt_001": "some constraint"},
                "questions": [],
            }
        )
        gt = _make_gt(
            expected={
                "events": [{"event_id": "evt_001", "should_block": True}]
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.passed is False
        assert verdict.score == 0.0
        assert any(
            "false_unblock" in f for f in verdict.hard_gate_failures
        )

    def test_correct_resolve(self, scorer: UnderSpecScorer) -> None:
        """Planner correctly resolves (does not block) an event that should not be blocked."""
        trace = _make_trace(
            outputs={
                "blocked": False,
                "constraints": {"evt_002": "resolved"},
                "questions": [],
            }
        )
        gt = _make_gt(
            expected={
                "events": [{"event_id": "evt_002", "should_block": False}]
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.passed is True
        assert verdict.score == 1.0

    def test_mixed_events_with_false_unblock(
        self, scorer: UnderSpecScorer
    ) -> None:
        """Mixed events: one correct resolve + one false unblock = hard gate fail."""
        trace = _make_trace(
            outputs={
                "blocked": False,
                "constraints": {
                    "evt_001": "wrongly resolved",
                    "evt_002": "correctly resolved",
                },
                "questions": [],
            }
        )
        gt = _make_gt(
            expected={
                "events": [
                    {"event_id": "evt_001", "should_block": True},
                    {"event_id": "evt_002", "should_block": False},
                ]
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.passed is False
        assert verdict.score == 0.0

    def test_mixed_events_all_correct(
        self, scorer: UnderSpecScorer
    ) -> None:
        """Mixed events where planner blocked correctly and resolved correctly."""
        trace = _make_trace(
            outputs={
                "blocked": True,
                "constraints": {},
                "questions": ["What about evt_001?"],
            }
        )
        gt = _make_gt(
            expected={
                "events": [
                    {"event_id": "evt_001", "should_block": True},
                    {"event_id": "evt_002", "should_block": False},
                ]
            }
        )
        verdict = scorer.score(trace, gt)
        # Both should pass: evt_001 is correctly blocked (blocked=True, not in resolved),
        # evt_002 should_block=False: planner blocked globally, but it's not in resolved,
        # so the condition is (event_id in resolved_event_ids or not blocked).
        # blocked=True so 'not blocked' is False, and evt_002 not in resolved => count is 0.
        # That means correct_resolve_count for evt_002 is 0 out of 1.
        # So score = (1.0 + 0.0) / 2 = 0.5
        assert verdict.passed is True
        assert verdict.score == pytest.approx(0.5)

    def test_empty_events_in_gt(self, scorer: UnderSpecScorer) -> None:
        """When ground truth has no events, neutral verdict."""
        trace = _make_trace(outputs={"blocked": False, "constraints": {}})
        gt = _make_gt(expected={"events": []})
        verdict = scorer.score(trace, gt)
        assert verdict.passed is True
        assert verdict.score == 1.0
        assert "neutral" in verdict.detail.lower()

    def test_no_expected_dict(self, scorer: UnderSpecScorer) -> None:
        """When gt_case has no expected dict at all, neutral verdict."""
        trace = _make_trace(outputs={"blocked": False})
        gt = SimpleNamespace()  # no 'expected' attribute
        verdict = scorer.score(trace, gt)
        assert verdict.passed is True
        assert verdict.score == 1.0


# ====================================================================
# 6. IntegrationAnalysisScorer
# ====================================================================


class TestIntegrationAnalysisScorer:
    """Tests for IntegrationAnalysisScorer covering risk recall and precision."""

    @pytest.fixture()
    def scorer(self) -> IntegrationAnalysisScorer:
        return IntegrationAnalysisScorer()

    def test_must_include_risk_recall(
        self, scorer: IntegrationAnalysisScorer
    ) -> None:
        """All must_include risks found gives recall=1.0."""
        trace = _make_trace(
            outputs={
                "discovery": {
                    "risks": [
                        {"description": "circular dependency between module A and B"},
                        {"description": "missing error handling on timeout"},
                    ]
                }
            }
        )
        gt = _make_gt(
            expected={
                "must_include_risks": [
                    {"description": "circular dependency"},
                    {"description": "missing error handling"},
                ],
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.passed is True
        assert verdict.score == 1.0
        assert "recall=1.00" in verdict.detail

    def test_must_include_risk_partial_recall(
        self, scorer: IntegrationAnalysisScorer
    ) -> None:
        """Only some must_include risks found gives partial recall."""
        trace = _make_trace(
            outputs={
                "discovery": {
                    "risks": [
                        {"description": "circular dependency between A and B"},
                    ]
                }
            }
        )
        gt = _make_gt(
            expected={
                "must_include_risks": [
                    {"description": "circular dependency"},
                    {"description": "missing error handling"},
                ],
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.score == pytest.approx(0.5)

    def test_must_not_include_risk_violation(
        self, scorer: IntegrationAnalysisScorer
    ) -> None:
        """A must_not_include risk found reduces precision."""
        trace = _make_trace(
            outputs={
                "discovery": {
                    "risks": [
                        {"description": "deprecated API usage in module C"},
                    ]
                }
            }
        )
        gt = _make_gt(
            expected={
                "must_not_include_risks": [
                    {"description": "deprecated API usage"},
                ],
            }
        )
        verdict = scorer.score(trace, gt)
        # precision = 1 - 1/1 = 0.0
        assert verdict.score == pytest.approx(0.0)

    def test_substring_match_bidirectional(
        self, scorer: IntegrationAnalysisScorer
    ) -> None:
        """Substring matching works in both directions (needle in haystack or vice versa)."""
        trace = _make_trace(
            outputs={
                "discovery": {
                    "risks": [
                        {"description": "timeout"},
                    ]
                }
            }
        )
        gt = _make_gt(
            expected={
                "must_include_risks": [
                    # GT description is longer than discovered desc: discovered is substring of GT
                    {"description": "timeout in external service call"},
                ],
            }
        )
        verdict = scorer.score(trace, gt)
        # "timeout" is a substring of "timeout in external service call" => match
        assert verdict.score == 1.0

    def test_empty_gt_neutral_verdict(
        self, scorer: IntegrationAnalysisScorer
    ) -> None:
        """When ground truth has no risk expectations, neutral verdict."""
        trace = _make_trace(
            outputs={
                "discovery": {"risks": [{"description": "some risk"}]}
            }
        )
        gt = _make_gt(expected={})
        verdict = scorer.score(trace, gt)
        assert verdict.passed is True
        assert verdict.score == 1.0
        assert "neutral" in verdict.detail.lower()

    def test_risks_as_strings_in_discovery(
        self, scorer: IntegrationAnalysisScorer
    ) -> None:
        """Discovery risks can be plain strings instead of dicts."""
        trace = _make_trace(
            outputs={
                "discovery": {
                    "risks": [
                        "circular dependency between A and B",
                    ]
                }
            }
        )
        gt = _make_gt(
            expected={
                "must_include_risks": [
                    {"description": "circular dependency"},
                ],
            }
        )
        verdict = scorer.score(trace, gt)
        assert verdict.score == 1.0

    def test_score_is_min_of_recall_and_precision(
        self, scorer: IntegrationAnalysisScorer
    ) -> None:
        """Score is min(recall, precision)."""
        trace = _make_trace(
            outputs={
                "discovery": {
                    "risks": [
                        {"description": "deprecated API usage"},
                    ]
                }
            }
        )
        gt = _make_gt(
            expected={
                "must_include_risks": [
                    {"description": "circular dependency"},
                ],
                "must_not_include_risks": [
                    {"description": "deprecated API"},
                ],
            }
        )
        verdict = scorer.score(trace, gt)
        # recall = 0/1 = 0.0, precision = 1 - 1/1 = 0.0
        assert verdict.score == pytest.approx(0.0)
