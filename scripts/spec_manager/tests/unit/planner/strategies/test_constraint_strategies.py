"""Tests for constraint-related planning strategies."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from spec_manager.planner.constraints.types import (
    ConflictReport,
    ConstraintContext,
    ConstraintFact,
    ConstraintHypothesis,
    DecisionRequirement,
    ImpactClassification,
    ProblemFrame,
)
from spec_manager.planner.strategies.constraint_strategies import (
    ConstraintCollectionStrategy,
    ConstraintEnricherStrategy,
    ImpactClassifierStrategy,
    NonSoftwareChecklistStrategy,
    ProblemFramerStrategy,
    QuestionComposerStrategy,
    _impact_at_least_medium,
)
from spec_manager.planner.strategies.protocol import PlanningSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session_with_impact(impact: str, **ctx_overrides) -> PlanningSession:
    ctx = {"layer": "L1", "slice_id": "test_lib", **ctx_overrides}
    return PlanningSession(
        ctx=ctx,
        impact=ImpactClassification(impact=impact),
    )


def _session_low() -> PlanningSession:
    return _session_with_impact("LOW")


def _session_medium() -> PlanningSession:
    return _session_with_impact("MEDIUM")


def _session_high() -> PlanningSession:
    return _session_with_impact("HIGH")


# ---------------------------------------------------------------------------
# Tests: _impact_at_least_medium
# ---------------------------------------------------------------------------


class TestImpactGating:
    def test_none_impact_returns_false(self):
        session = PlanningSession()
        assert not _impact_at_least_medium(session)

    def test_low_returns_false(self):
        assert not _impact_at_least_medium(_session_low())

    def test_medium_returns_true(self):
        assert _impact_at_least_medium(_session_medium())

    def test_high_returns_true(self):
        assert _impact_at_least_medium(_session_high())


# ---------------------------------------------------------------------------
# Tests: ImpactClassifierStrategy
# ---------------------------------------------------------------------------


class TestImpactClassifierStrategy:
    def test_name(self):
        s = ImpactClassifierStrategy()
        assert s.name == "impact_classifier"

    def test_classifies_low_by_default(self):
        s = ImpactClassifierStrategy()
        session = PlanningSession(ctx={"layer": "L1"})
        result = s.run(session)
        assert result.impact is not None
        assert result.impact.impact == "LOW"

    def test_classifies_medium_for_l2(self):
        s = ImpactClassifierStrategy()
        session = PlanningSession(ctx={"layer": "L2"})
        result = s.run(session)
        assert result.impact is not None
        assert result.impact.impact == "MEDIUM"

    def test_classifies_high_for_cross_library(self):
        s = ImpactClassifierStrategy()
        session = PlanningSession(ctx={"layer": "L1", "cross_library_contract": True})
        result = s.run(session)
        assert result.impact is not None
        assert result.impact.impact == "HIGH"

    def test_uses_gap_kinds(self):
        s = ImpactClassifierStrategy()
        session = PlanningSession(
            ctx={"layer": "L1"},
            gaps=[{"kind": "topology"}, {"kind": "naming"}],
        )
        result = s.run(session)
        assert result.impact is not None
        assert result.impact.impact == "MEDIUM"

    def test_uses_touched_files_count(self):
        s = ImpactClassifierStrategy()
        session = PlanningSession(ctx={"layer": "L1", "touched_files_count": 5})
        result = s.run(session)
        assert result.impact is not None
        assert result.impact.impact == "MEDIUM"


# ---------------------------------------------------------------------------
# Tests: ConstraintCollectionStrategy
# ---------------------------------------------------------------------------


class TestConstraintCollectionStrategy:
    def test_name(self):
        s = ConstraintCollectionStrategy(Path("/tmp/ws"))
        assert s.name == "constraint_collection"

    def test_loads_constraints(self, tmp_path):
        # Set up constraint store files
        constraints_dir = tmp_path / "analysis" / "constraints"
        constraints_dir.mkdir(parents=True)
        (constraints_dir / "__system__.json").write_text(
            json.dumps(
                [
                    {
                        "constraint_id": "CON-SYS-001",
                        "question": "Use REST?",
                        "answer": "Yes",
                        "source": "user",
                        "confidence": 1.0,
                        "validated": True,
                    }
                ]
            ),
            encoding="utf-8",
        )
        (constraints_dir / "test_lib.json").write_text(
            json.dumps([]),
            encoding="utf-8",
        )

        s = ConstraintCollectionStrategy(tmp_path)
        session = PlanningSession(ctx={"slice_id": "test_lib"})
        result = s.run(session)

        assert result.constraint_context is not None
        # System constraint loaded as authoritative (no decision_type)
        total = len(result.constraint_context.authoritative) + len(
            result.constraint_context.decisions
        )
        assert total >= 1

    def test_empty_store(self, tmp_path):
        s = ConstraintCollectionStrategy(tmp_path)
        session = PlanningSession(ctx={"slice_id": "nonexistent"})
        result = s.run(session)
        assert result.constraint_context is not None
        assert result.constraint_context.authoritative == []


# ---------------------------------------------------------------------------
# Tests: ProblemFramerStrategy
# ---------------------------------------------------------------------------


class TestProblemFramerStrategy:
    def test_name(self):
        s = ProblemFramerStrategy()
        assert s.name == "problem_framer"

    def test_skips_for_low_impact(self):
        s = ProblemFramerStrategy()
        session = _session_low()
        result = s.run(session)
        assert result.problem_frame is None

    def test_runs_for_medium_impact_without_llm(self):
        s = ProblemFramerStrategy(run_agent=None)
        session = _session_medium()
        result = s.run(session)
        assert result.problem_frame is not None
        assert result.problem_frame.goal == "Resolve identified gaps"

    def test_runs_for_high_impact_without_llm(self):
        s = ProblemFramerStrategy(run_agent=None)
        session = _session_high()
        result = s.run(session)
        assert result.problem_frame is not None

    def test_calls_llm_for_medium_impact(self):
        mock_agent = MagicMock(
            return_value=json.dumps(
                {
                    "goal": "Build payment processor",
                    "scope": "PaymentLib",
                    "domain_markers": ["transaction", "settlement"],
                    "decision_points": ["Which protocol?"],
                    "tradeoff_axes": ["performance vs safety"],
                    "unknowns": ["Volume requirements"],
                }
            )
        )

        s = ProblemFramerStrategy(run_agent=mock_agent)
        session = _session_medium()
        result = s.run(session)

        mock_agent.assert_called_once()
        assert result.problem_frame is not None
        assert result.problem_frame.goal == "Build payment processor"
        assert "transaction" in result.problem_frame.domain_markers

    def test_handles_malformed_llm_output(self):
        mock_agent = MagicMock(return_value="not json at all")
        s = ProblemFramerStrategy(run_agent=mock_agent)
        session = _session_medium()
        result = s.run(session)
        assert result.problem_frame is not None
        # Falls back to empty ProblemFrame
        assert result.problem_frame.goal == ""


# ---------------------------------------------------------------------------
# Tests: ConstraintEnricherStrategy
# ---------------------------------------------------------------------------


class TestConstraintEnricherStrategy:
    def test_name(self):
        s = ConstraintEnricherStrategy()
        assert s.name == "constraint_enricher"

    def test_skips_for_low_impact(self):
        s = ConstraintEnricherStrategy()
        session = _session_low()
        result = s.run(session)
        assert result.hypotheses == []

    def test_skips_without_llm(self):
        s = ConstraintEnricherStrategy(run_agent=None)
        session = _session_medium()
        result = s.run(session)
        assert result.hypotheses == []

    def test_enriches_with_llm(self):
        mock_agent = MagicMock(
            return_value=json.dumps(
                {
                    "hypotheses": [
                        {
                            "hypothesis_id": "HYP-001",
                            "question": "Is caching needed?",
                            "inferred_answer": "Probably yes",
                            "source": "gap_analysis",
                            "confidence": 0.7,
                            "dimension": "software",
                            "reasoning": "Multiple read-heavy endpoints",
                        }
                    ],
                    "decision_requirements": [
                        {
                            "decision_id": "DR-001",
                            "question": "Which cache backend?",
                            "kind": "technology_choice",
                            "dimension": "software",
                            "scope": "intra:LIB",
                            "impact": "MEDIUM",
                            "options": ["redis", "memcached"],
                            "needed_for": ["PaymentLib"],
                        }
                    ],
                    "conflicts": [{"between": "CON-001 and CON-002", "nature": "contradictory"}],
                }
            )
        )

        s = ConstraintEnricherStrategy(run_agent=mock_agent)
        session = _session_medium()
        result = s.run(session)

        mock_agent.assert_called_once()
        assert len(result.hypotheses) == 1
        assert result.hypotheses[0].hypothesis_id == "HYP-001"
        assert len(result.decision_requirements) == 1
        assert result.decision_requirements[0].decision_id == "DR-001"
        assert result.conflict_report is not None
        assert len(result.conflict_report.conflicts) == 1

    def test_handles_malformed_llm_output(self):
        mock_agent = MagicMock(return_value="garbage")
        s = ConstraintEnricherStrategy(run_agent=mock_agent)
        session = _session_medium()
        result = s.run(session)
        assert result.hypotheses == []
        assert result.decision_requirements == []


# ---------------------------------------------------------------------------
# Tests: NonSoftwareChecklistStrategy
# ---------------------------------------------------------------------------


class TestNonSoftwareChecklistStrategy:
    def test_name(self):
        s = NonSoftwareChecklistStrategy()
        assert s.name == "non_software_checklist"

    def test_skips_for_low_impact(self):
        s = NonSoftwareChecklistStrategy()
        session = _session_low()
        session.gaps = [{"description": "legal compliance issue"}]
        result = s.run(session)
        assert result.decision_requirements == []

    def test_detects_legal_dimension(self):
        s = NonSoftwareChecklistStrategy()
        session = _session_medium()
        session.gaps = [{"description": "legal compliance requirements"}]
        result = s.run(session)
        assert len(result.decision_requirements) == 1
        assert result.decision_requirements[0].dimension == "legal"
        assert result.decision_requirements[0].kind == "non_software_checklist"

    def test_detects_multiple_dimensions(self):
        s = NonSoftwareChecklistStrategy()
        session = _session_high()
        session.gaps = [
            {"description": "legal and economic concerns"},
            {"description": "organizational structure"},
        ]
        result = s.run(session)
        dimensions = {dr.dimension for dr in result.decision_requirements}
        assert "legal" in dimensions
        assert "economic" in dimensions
        assert "organizational" in dimensions

    def test_skips_already_covered_dimensions(self):
        s = NonSoftwareChecklistStrategy()
        session = _session_medium()
        session.gaps = [{"description": "legal issue"}]
        session.decision_requirements = [
            DecisionRequirement(decision_id="EXIST", dimension="legal")
        ]
        result = s.run(session)
        # Should not add duplicate
        legal_reqs = [dr for dr in result.decision_requirements if dr.dimension == "legal"]
        assert len(legal_reqs) == 1

    def test_no_detection_when_no_gaps_mention_dimensions(self):
        s = NonSoftwareChecklistStrategy()
        session = _session_medium()
        session.gaps = [{"description": "fix the button color"}]
        result = s.run(session)
        assert result.decision_requirements == []

    def test_detects_from_ctx(self):
        s = NonSoftwareChecklistStrategy()
        session = _session_medium()
        session.ctx["notes"] = "temporal deadline approaching"
        result = s.run(session)
        assert len(result.decision_requirements) == 1
        assert result.decision_requirements[0].dimension == "temporal"


# ---------------------------------------------------------------------------
# Tests: QuestionComposerStrategy
# ---------------------------------------------------------------------------


class TestQuestionComposerStrategy:
    def test_name(self):
        s = QuestionComposerStrategy()
        assert s.name == "question_composer"

    def test_skips_when_not_interactive(self):
        s = QuestionComposerStrategy()
        session = PlanningSession(
            ctx={"interactive": False},
            under_spec_events=[{"type": "gap", "detail": "missing info"}],
        )
        result = s.run(session)
        assert len(result.under_spec_events) == 1  # unchanged

    def test_skips_when_no_events(self):
        mock_agent = MagicMock()
        s = QuestionComposerStrategy(run_agent=mock_agent)
        session = PlanningSession(ctx={"interactive": True})
        result = s.run(session)
        mock_agent.assert_not_called()
        assert result.under_spec_events == []

    def test_skips_without_llm(self):
        s = QuestionComposerStrategy(run_agent=None)
        session = PlanningSession(
            ctx={"interactive": True},
            under_spec_events=[{"type": "gap", "detail": "missing info"}],
        )
        result = s.run(session)
        assert len(result.under_spec_events) == 1  # unchanged

    def test_refines_events_with_llm(self):
        mock_agent = MagicMock(
            return_value=json.dumps(
                [
                    {
                        "type": "gap",
                        "question": "What is the expected latency SLA?",
                        "context": "Performance requirement unclear",
                        "original_detail": "missing info",
                    }
                ]
            )
        )

        s = QuestionComposerStrategy(run_agent=mock_agent)
        session = PlanningSession(
            ctx={"interactive": True},
            under_spec_events=[{"type": "gap", "detail": "missing info"}],
        )
        result = s.run(session)

        mock_agent.assert_called_once()
        assert len(result.under_spec_events) == 1
        assert result.under_spec_events[0]["question"] == "What is the expected latency SLA?"

    def test_falls_back_on_malformed_llm_output(self):
        mock_agent = MagicMock(return_value="not json")
        s = QuestionComposerStrategy(run_agent=mock_agent)
        session = PlanningSession(
            ctx={"interactive": True},
            under_spec_events=[{"type": "gap", "detail": "original"}],
        )
        result = s.run(session)
        assert len(result.under_spec_events) == 1
        assert result.under_spec_events[0]["detail"] == "original"


# ---------------------------------------------------------------------------
# Tests: TradeoffMapperStrategy
# ---------------------------------------------------------------------------


class TestTradeoffMapperStrategy:
    def test_name(self):
        from spec_manager.planner.strategies.constraint_strategies import (
            TradeoffMapperStrategy,
        )

        s = TradeoffMapperStrategy()
        assert s.name == "tradeoff_mapper"

    def test_tradeoff_mapper_default_axes(self):
        from spec_manager.planner.strategies.constraint_strategies import (
            TradeoffMapperStrategy,
        )

        # No workspace
        s = TradeoffMapperStrategy(workspace_root=None)
        session = PlanningSession()
        result = s.run(session)

        # Should return default axes
        assert result.tradeoff_axes is not None
        assert "performance" in result.tradeoff_axes
        assert "maintainability" in result.tradeoff_axes
        assert "simplicity" in result.tradeoff_axes
        assert "extensibility" in result.tradeoff_axes
        assert "reliability" in result.tradeoff_axes
        assert "scalability" in result.tradeoff_axes
        assert "security" in result.tradeoff_axes

    def test_tradeoff_mapper_reads_tradeoffs_md(self, tmp_path):
        from spec_manager.planner.strategies.constraint_strategies import (
            TradeoffMapperStrategy,
        )

        # Create TRADEOFFS.md with custom axes
        design_dir = tmp_path / "design"
        design_dir.mkdir()
        tradeoffs_file = design_dir / "TRADEOFFS.md"
        tradeoffs_file.write_text(
            """# Tradeoffs

## Performance
We prioritize speed over memory usage.

## Security
All endpoints must be authenticated.

## Scalability
Must handle 1M requests/day.
""",
            encoding="utf-8",
        )

        s = TradeoffMapperStrategy(workspace_root=tmp_path)
        session = PlanningSession()
        result = s.run(session)

        # Should parse axes from headings
        assert result.tradeoff_axes is not None
        assert "performance" in result.tradeoff_axes
        assert "security" in result.tradeoff_axes
        assert "scalability" in result.tradeoff_axes

    def test_tradeoff_mapper_fallback_on_missing_file(self, tmp_path):
        from spec_manager.planner.strategies.constraint_strategies import (
            TradeoffMapperStrategy,
        )

        # Workspace exists but no TRADEOFFS.md
        s = TradeoffMapperStrategy(workspace_root=tmp_path)
        session = PlanningSession()
        result = s.run(session)

        # Should return defaults
        assert result.tradeoff_axes is not None
        assert "performance" in result.tradeoff_axes
        assert len(result.tradeoff_axes) == 7  # 7 default axes

    def test_tradeoff_mapper_parse_list_items(self, tmp_path):
        from spec_manager.planner.strategies.constraint_strategies import (
            TradeoffMapperStrategy,
        )

        # Create TRADEOFFS.md with list items
        tradeoffs_file = tmp_path / "TRADEOFFS.md"
        tradeoffs_file.write_text(
            """# Key Tradeoffs

- performance
- reliability
- cost optimization
""",
            encoding="utf-8",
        )

        s = TradeoffMapperStrategy(workspace_root=tmp_path)
        session = PlanningSession()
        result = s.run(session)

        # Should parse axes from list items
        assert result.tradeoff_axes is not None
        assert "performance" in result.tradeoff_axes
        assert "reliability" in result.tradeoff_axes
        assert "cost optimization" in result.tradeoff_axes

    def test_tradeoff_mapper_skips_generic_headings(self, tmp_path):
        from spec_manager.planner.strategies.constraint_strategies import (
            TradeoffMapperStrategy,
        )

        # Create TRADEOFFS.md with generic and specific headings
        design_dir = tmp_path / "design"
        design_dir.mkdir()
        tradeoffs_file = design_dir / "TRADEOFFS.md"
        tradeoffs_file.write_text(
            """# Tradeoffs

## Overview
This document describes our tradeoffs.

## Introduction
Let's get started.

## Performance
Speed matters.

## Summary
That's all.
""",
            encoding="utf-8",
        )

        s = TradeoffMapperStrategy(workspace_root=tmp_path)
        session = PlanningSession()
        result = s.run(session)

        # Should skip "overview", "introduction", "summary"
        assert result.tradeoff_axes is not None
        assert "performance" in result.tradeoff_axes
        assert "overview" not in result.tradeoff_axes
        assert "introduction" not in result.tradeoff_axes
        assert "summary" not in result.tradeoff_axes
