"""Tests for PlanningStrategy protocol, PlanningSession, and PlanningSessionRunner."""

from __future__ import annotations

from spec_manager.planner.architecture.types import DecisionOutcome
from spec_manager.planner.constraints.types import (
    ConstraintContext,
    ConstraintFact,
    ImpactClassification,
)
from spec_manager.planner.strategies.protocol import (
    PlanningSession,
    PlanningSessionRunner,
    PlanningStrategy,
)

# ---------------------------------------------------------------------------
# Concrete strategy for testing
# ---------------------------------------------------------------------------


class AppendStrategy:
    """Test strategy that appends a value to session.intentions."""

    def __init__(self, value: str) -> None:
        self._value = value

    @property
    def name(self) -> str:
        return f"append_{self._value}"

    def run(self, session: PlanningSession) -> PlanningSession:
        session.intentions.append({"added_by": self._value})
        return session


class SetImpactStrategy:
    """Test strategy that sets session.impact."""

    @property
    def name(self) -> str:
        return "set_impact"

    def run(self, session: PlanningSession) -> PlanningSession:
        session.impact = ImpactClassification(impact="HIGH")
        return session


class FailingStrategy:
    """Strategy that raises."""

    @property
    def name(self) -> str:
        return "failing"

    def run(self, session: PlanningSession) -> PlanningSession:
        raise RuntimeError("intentional failure")


# ---------------------------------------------------------------------------
# Tests: PlanningSession
# ---------------------------------------------------------------------------


class TestPlanningSession:
    def test_default_fields(self):
        session = PlanningSession()
        assert session.ctx == {}
        assert session.gaps == []
        assert session.discovery == {}
        assert session.impact is None
        assert session.problem_frame is None
        assert session.constraint_context is None
        assert session.hypotheses == []
        assert session.decision_requirements == []
        assert session.conflict_report is None
        assert session.decision_outcomes == []
        assert session.intentions == []
        assert session.under_spec_events == []
        assert session.new_constraints == []

    def test_mutable_fields(self):
        session = PlanningSession(ctx={"layer": "L2"})
        session.gaps.append({"kind": "test"})
        assert len(session.gaps) == 1
        assert session.ctx["layer"] == "L2"

    def test_impact_can_be_set(self):
        session = PlanningSession()
        session.impact = ImpactClassification(impact="MEDIUM")
        assert session.impact.impact == "MEDIUM"

    def test_decision_outcomes_can_be_appended(self):
        session = PlanningSession()
        outcome = DecisionOutcome(decision_id="DEC-001", committed=True)
        session.decision_outcomes.append(outcome)
        assert len(session.decision_outcomes) == 1
        assert session.decision_outcomes[0].decision_id == "DEC-001"


# ---------------------------------------------------------------------------
# Tests: PlanningStrategy protocol
# ---------------------------------------------------------------------------


class TestPlanningStrategyProtocol:
    def test_append_strategy_satisfies_protocol(self):
        strategy = AppendStrategy("test")
        assert isinstance(strategy, PlanningStrategy)

    def test_set_impact_strategy_satisfies_protocol(self):
        strategy = SetImpactStrategy()
        assert isinstance(strategy, PlanningStrategy)


# ---------------------------------------------------------------------------
# Tests: PlanningSessionRunner
# ---------------------------------------------------------------------------


class TestPlanningSessionRunner:
    def test_empty_strategies_returns_session_unchanged(self):
        runner = PlanningSessionRunner([])
        session = PlanningSession(ctx={"layer": "L1"})
        result = runner.run(session)
        assert result.ctx == {"layer": "L1"}
        assert result.intentions == []

    def test_single_strategy_runs(self):
        runner = PlanningSessionRunner([AppendStrategy("alpha")])
        session = PlanningSession()
        result = runner.run(session)
        assert len(result.intentions) == 1
        assert result.intentions[0]["added_by"] == "alpha"

    def test_multiple_strategies_run_in_order(self):
        runner = PlanningSessionRunner(
            [
                AppendStrategy("first"),
                AppendStrategy("second"),
                AppendStrategy("third"),
            ]
        )
        session = PlanningSession()
        result = runner.run(session)
        assert len(result.intentions) == 3
        assert result.intentions[0]["added_by"] == "first"
        assert result.intentions[1]["added_by"] == "second"
        assert result.intentions[2]["added_by"] == "third"

    def test_strategies_share_session_state(self):
        runner = PlanningSessionRunner(
            [
                SetImpactStrategy(),
                AppendStrategy("after_impact"),
            ]
        )
        session = PlanningSession()
        result = runner.run(session)
        assert result.impact is not None
        assert result.impact.impact == "HIGH"
        assert len(result.intentions) == 1

    def test_strategies_property_returns_copy(self):
        strategies = [AppendStrategy("a")]
        runner = PlanningSessionRunner(strategies)
        returned = runner.strategies
        assert len(returned) == 1
        returned.append(AppendStrategy("b"))
        assert len(runner.strategies) == 1  # original unchanged

    def test_failing_strategy_propagates_error(self):
        runner = PlanningSessionRunner(
            [
                AppendStrategy("ok"),
                FailingStrategy(),
                AppendStrategy("never"),
            ]
        )
        session = PlanningSession()
        try:
            runner.run(session)
            assert False, "Should have raised"
        except RuntimeError as e:
            assert "intentional failure" in str(e)
        # First strategy ran before failure
        assert len(session.intentions) == 1
