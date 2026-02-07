"""Tests for Plans 3, 4, 6: Evolution pipeline, promotion, and wiring."""

from __future__ import annotations

from spec_manager.strategies.base import (
    ProcessingContext,
    StrategyPhase,
    StrategyResult,
    TranslationContext,
)
from spec_manager.strategies.evolution import (
    LLMStrategyProposer,
    PromotionCriteria,
    StrategyEvolutionPipeline,
    StrategyPerformanceRecord,
    TemplateStrategyProposer,
)
from spec_manager.strategies.registry import (
    FailureMode,
    StrategyGapEvidence,
    StrategyRegistry,
)
from tests.strategies.conftest import make_unit


# =========================================================================
# Plan 3: Template Proposer Tests
# =========================================================================


class TestTemplateStrategyProposer:
    """Verify template proposer returns correct definition for each FailureMode."""

    def setup_method(self) -> None:
        self.proposer = TemplateStrategyProposer()

    def test_multi_concern_comment_template(self) -> None:
        gap = StrategyGapEvidence(
            failure_mode=FailureMode.MULTI_CONCERN_COMMENT,
            failure_category="translation",
            fixture={},
        )
        defn = self.proposer.propose(gap)
        assert defn is not None
        assert defn.name == "comment_decomposition"
        assert defn.implementation_class is not None
        assert "CommentDecompositionStrategy" in defn.implementation_class

    def test_vague_entity_reference_template(self) -> None:
        gap = StrategyGapEvidence(
            failure_mode=FailureMode.VAGUE_ENTITY_REFERENCE,
            failure_category="translation",
            fixture={},
        )
        defn = self.proposer.propose(gap)
        assert defn is not None
        assert defn.name == "translation_entity_resolution"

    def test_insufficient_detail_template(self) -> None:
        gap = StrategyGapEvidence(
            failure_mode=FailureMode.INSUFFICIENT_DETAIL,
            failure_category="translation",
            fixture={},
        )
        defn = self.proposer.propose(gap)
        assert defn is not None
        assert defn.name == "ambiguity_research"

    def test_shared_store_adjacency_template(self) -> None:
        gap = StrategyGapEvidence(
            failure_mode=FailureMode.SHARED_STORE_ADJACENCY,
            failure_category="translation",
            fixture={},
        )
        defn = self.proposer.propose(gap)
        assert defn is not None
        assert defn.name == "adjacency_detection"

    def test_stub_with_context_template(self) -> None:
        gap = StrategyGapEvidence(
            failure_mode=FailureMode.STUB_WITH_CONTEXT,
            failure_category="translation",
            fixture={},
        )
        defn = self.proposer.propose(gap)
        assert defn is not None
        assert defn.name == "stub_promotion"

    def test_unknown_failure_mode_returns_none(self) -> None:
        gap = StrategyGapEvidence(
            failure_mode="completely_unknown_mode",
            failure_category="translation",
            fixture={},
        )
        defn = self.proposer.propose(gap)
        assert defn is None


class TestLLMStrategyProposer:
    """Verify LLM proposer behavior."""

    def test_no_llm_returns_none(self) -> None:
        proposer = LLMStrategyProposer(llm_client=None)
        gap = StrategyGapEvidence(
            failure_mode="unknown",
            failure_category="translation",
            fixture={"inputs": [], "context": {}, "strategies_attempted": []},
            strategies_attempted=[],
        )
        result = proposer.propose(gap)
        assert result is None

    def test_llm_proposer_with_mock_client(self) -> None:
        import json

        class MockLLM:
            def complete(self, prompt: str) -> str:
                return json.dumps(
                    {
                        "name": "custom_strategy",
                        "purpose": "Handle custom failure",
                        "when_conditions": ["custom condition"],
                        "tools_used": ["custom_tool"],
                        "risk_addressed": "custom risk",
                    }
                )

        proposer = LLMStrategyProposer(llm_client=MockLLM())
        gap = StrategyGapEvidence(
            failure_mode="custom_failure",
            failure_category="translation",
            fixture={"inputs": [], "context": {}, "strategies_attempted": []},
            strategies_attempted=[],
        )
        result = proposer.propose(gap)
        assert result is not None
        assert result.name == "custom_strategy"
        assert result.purpose == "Handle custom failure"


# =========================================================================
# Plan 3: on_translation_failure() tests
# =========================================================================


class TestOnTranslationFailure:
    """Verify on_translation_failure produces a registered experimental strategy."""

    def _make_context(self) -> ProcessingContext:
        unit = make_unit(unit_id="u1", content="test")
        tc = TranslationContext(comment_text="# validate and send confirmation")
        return ProcessingContext(
            units=[unit],
            phase=StrategyPhase.TRANSLATION,
            translation_context=tc,
        )

    def test_on_failure_registers_experimental_strategy(self) -> None:
        registry = StrategyRegistry()
        registry.enable_evolution()
        ctx = self._make_context()

        result = registry.evolution_pipeline.on_translation_failure(
            context=ctx,
            failure_mode=FailureMode.MULTI_CONCERN_COMMENT,
        )

        assert result is not None
        assert result.name == "comment_decomposition"
        assert result.metadata.get("status") == "experimental"
        assert result.name in registry.definitions

    def test_on_failure_logs_gap(self) -> None:
        registry = StrategyRegistry()
        registry.enable_evolution()
        ctx = self._make_context()

        registry.evolution_pipeline.on_translation_failure(
            context=ctx,
            failure_mode=FailureMode.VAGUE_ENTITY_REFERENCE,
        )

        assert len(registry.evolution_pipeline.gap_log) == 1
        gap = registry.evolution_pipeline.gap_log[0]
        assert gap.failure_mode == FailureMode.VAGUE_ENTITY_REFERENCE

    def test_on_failure_unknown_mode_tries_llm(self) -> None:
        registry = StrategyRegistry()
        registry.enable_evolution()
        ctx = self._make_context()

        result = registry.evolution_pipeline.on_translation_failure(
            context=ctx,
            failure_mode="completely_unknown_failure",
        )

        # No LLM client, so should return None
        assert result is None
        # But gap is still logged
        assert len(registry.evolution_pipeline.gap_log) == 1


# =========================================================================
# Plan 4: Promotion Gate Tests
# =========================================================================


class TestPromotionCriteria:
    """Verify PromotionCriteria defaults."""

    def test_default_criteria(self) -> None:
        criteria = PromotionCriteria()
        assert criteria.min_successful_applications == 3
        assert criteria.min_failure_mode_reduction == 0.5
        assert criteria.max_regression_rate == 0.0
        assert criteria.fixture_pass_rate == 1.0


class TestStrategyPerformanceRecord:
    """Verify performance tracking."""

    def test_success_rate_empty(self) -> None:
        record = StrategyPerformanceRecord(strategy_name="test")
        assert record.success_rate == 0.0

    def test_success_rate_calculation(self) -> None:
        record = StrategyPerformanceRecord(strategy_name="test")
        result = StrategyResult(
            units=[], actions_taken=["action1"], issues=[], metrics={}
        )
        record.record_application(result, success=True)
        record.record_application(result, success=True)
        record.record_application(result, success=False)
        assert record.successes == 2
        assert record.failures == 1
        assert abs(record.success_rate - 2 / 3) < 0.001

    def test_record_application_stores_details(self) -> None:
        record = StrategyPerformanceRecord(strategy_name="test")
        result = StrategyResult(
            units=[],
            actions_taken=["split comment"],
            issues=["minor issue"],
            metrics={"splits": 2},
        )
        record.record_application(result, success=True)
        assert len(record.applications) == 1
        assert record.applications[0]["success"] is True
        assert record.applications[0]["actions"] == ["split comment"]


class TestPromoteToStable:
    """Verify promotion validation logic."""

    def _setup_experimental_strategy(self, registry: StrategyRegistry) -> None:
        """Helper to register an experimental strategy."""
        registry.enable_evolution()
        unit = make_unit(unit_id="u1", content="test")
        tc = TranslationContext(comment_text="# validate and send")
        ctx = ProcessingContext(
            units=[unit],
            phase=StrategyPhase.TRANSLATION,
            translation_context=tc,
        )
        registry.evolution_pipeline.on_translation_failure(
            context=ctx,
            failure_mode=FailureMode.MULTI_CONCERN_COMMENT,
        )

    def test_promotion_fails_with_insufficient_successes(self) -> None:
        registry = StrategyRegistry()
        self._setup_experimental_strategy(registry)

        record = StrategyPerformanceRecord(strategy_name="comment_decomposition")
        record.successes = 2  # Below threshold of 3
        record.failures = 0

        success = registry.promote_to_stable("comment_decomposition", performance=record)
        assert success is False
        assert registry.definitions["comment_decomposition"].metadata["status"] == "experimental"

    def test_promotion_fails_with_low_success_rate(self) -> None:
        registry = StrategyRegistry()
        self._setup_experimental_strategy(registry)

        record = StrategyPerformanceRecord(strategy_name="comment_decomposition")
        record.successes = 3
        record.failures = 10  # Very low success rate

        success = registry.promote_to_stable("comment_decomposition", performance=record)
        assert success is False

    def test_promotion_succeeds_with_valid_record(self) -> None:
        registry = StrategyRegistry()
        self._setup_experimental_strategy(registry)

        record = StrategyPerformanceRecord(strategy_name="comment_decomposition")
        record.successes = 5
        record.failures = 0

        success = registry.promote_to_stable("comment_decomposition", performance=record)
        assert success is True
        defn = registry.definitions["comment_decomposition"]
        assert defn.metadata["status"] == "stable"
        assert "promoted_at" in defn.metadata
        assert defn.metadata["promotion_evidence"]["successes"] == 5
        assert defn.metadata["promotion_evidence"]["success_rate"] == 1.0

    def test_promotion_fails_for_nonexistent_strategy(self) -> None:
        registry = StrategyRegistry()
        success = registry.promote_to_stable("nonexistent")
        assert success is False

    def test_promotion_fails_for_non_experimental(self) -> None:
        from spec_manager.strategies.base import StrategyDefinition

        registry = StrategyRegistry()
        registry.add_strategy(
            StrategyDefinition(
                name="stable_strat",
                purpose="test",
                risk_addressed="test",
                metadata={"status": "stable"},
            )
        )
        success = registry.promote_to_stable("stable_strat")
        assert success is False

    def test_promotion_without_performance_record(self) -> None:
        registry = StrategyRegistry()
        self._setup_experimental_strategy(registry)

        # Without performance record, promotion should succeed (no criteria to fail)
        success = registry.promote_to_stable("comment_decomposition")
        assert success is True


# =========================================================================
# Plan 6: check_and_evolve() and Integration Tests
# =========================================================================


class TestCheckAndEvolve:
    """Verify check_and_evolve() returns new strategies when triggers fire."""

    def test_no_evolution_when_not_enabled(self) -> None:
        registry = StrategyRegistry()
        ctx = ProcessingContext(
            units=[],
            phase=StrategyPhase.TRANSLATION,
        )
        result = registry.check_and_evolve(ctx)
        assert result == []

    def test_no_triggers_returns_empty(self) -> None:
        registry = StrategyRegistry()
        registry.enable_evolution()
        ctx = ProcessingContext(
            units=[],
            phase=StrategyPhase.TRANSLATION,
        )
        result = registry.check_and_evolve(ctx)
        assert result == []

    def test_remainder_stuck_trigger_evolves(self) -> None:
        registry = StrategyRegistry()
        registry.enable_evolution()

        prev_ctx = ProcessingContext(
            units=[],
            phase=StrategyPhase.TRANSLATION,
            results={"remainders": ["a", "b", "c"]},
        )
        curr_ctx = ProcessingContext(
            units=[make_unit(unit_id="u1", content="test")],
            phase=StrategyPhase.TRANSLATION,
            results={"remainders": ["a", "b", "c"]},
            translation_context=TranslationContext(comment_text="# test"),
        )

        new_strategies = registry.check_and_evolve(curr_ctx, prev_ctx)
        assert len(new_strategies) >= 1
        # remainder_stuck maps to INSUFFICIENT_DETAIL -> ambiguity_research
        names = [s.name for s in new_strategies]
        assert "ambiguity_research" in names

    def test_resolution_failures_trigger_evolves(self) -> None:
        registry = StrategyRegistry()
        registry.enable_evolution()

        prev_ctx = ProcessingContext(
            units=[],
            phase=StrategyPhase.TRANSLATION,
            results={"remainders": []},
        )
        curr_ctx = ProcessingContext(
            units=[make_unit(unit_id="u1", content="test")],
            phase=StrategyPhase.TRANSLATION,
            results={
                "remainders": [],
                "resolution_failures": 5,
                "total_references": 10,
            },
            translation_context=TranslationContext(comment_text="# test"),
        )

        new_strategies = registry.check_and_evolve(curr_ctx, prev_ctx)
        assert len(new_strategies) >= 1
        names = [s.name for s in new_strategies]
        assert "translation_entity_resolution" in names

    def test_backward_compat_capture_strategy_gap(self) -> None:
        """Existing callers of capture_strategy_gap() still work."""
        registry = StrategyRegistry()
        unit = make_unit(unit_id="u1", content="test")
        ctx = ProcessingContext(
            units=[unit],
            phase=StrategyPhase.RESOLUTION,
        )

        gap = registry.capture_strategy_gap(
            context=ctx,
            failure_mode="test_failure",
            failing_inputs=[unit],
        )
        assert gap.failure_mode == "test_failure"
        assert gap.failure_category == "resolution"


class TestEvolutionReport:
    """Verify get_evolution_report() returns structured summary."""

    def test_empty_report(self) -> None:
        registry = StrategyRegistry()
        registry.enable_evolution()
        report = registry.evolution_pipeline.get_evolution_report()
        assert report["total_gaps"] == 0
        assert report["gaps"] == []
        assert report["performance"] == {}
        assert report["experimental_strategies"] == []

    def test_report_after_evolution(self) -> None:
        registry = StrategyRegistry()
        registry.enable_evolution()
        unit = make_unit(unit_id="u1", content="test")
        ctx = ProcessingContext(
            units=[unit],
            phase=StrategyPhase.TRANSLATION,
            translation_context=TranslationContext(comment_text="# test and more"),
        )

        registry.evolution_pipeline.on_translation_failure(
            context=ctx,
            failure_mode=FailureMode.MULTI_CONCERN_COMMENT,
        )

        report = registry.evolution_pipeline.get_evolution_report()
        assert report["total_gaps"] == 1
        assert len(report["gaps"]) == 1
        assert report["gaps"][0]["failure_mode"] == FailureMode.MULTI_CONCERN_COMMENT
        assert "comment_decomposition" in report["experimental_strategies"]
