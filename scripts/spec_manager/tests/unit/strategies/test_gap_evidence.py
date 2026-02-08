"""Tests for Plan 2: Formalized Strategy Gap Evidence with Rich Failure Context."""

from __future__ import annotations

from spec_manager.strategies.base import (
    ProcessingContext,
    StrategyPhase,
    TranslationContext,
)
from spec_manager.strategies.registry import (
    FailureMode,
    StrategyGapEvidence,
    StrategyRegistry,
)

from tests.unit.strategies.conftest import make_unit


class TestFailureMode:
    """Verify FailureMode constants are accessible."""

    def test_multi_concern_comment(self) -> None:
        assert FailureMode.MULTI_CONCERN_COMMENT == "multi_concern_comment"

    def test_vague_entity_reference(self) -> None:
        assert FailureMode.VAGUE_ENTITY_REFERENCE == "vague_entity_reference"

    def test_insufficient_detail(self) -> None:
        assert FailureMode.INSUFFICIENT_DETAIL == "insufficient_detail"

    def test_shared_store_adjacency(self) -> None:
        assert FailureMode.SHARED_STORE_ADJACENCY == "shared_store_adjacency"

    def test_stub_with_context(self) -> None:
        assert FailureMode.STUB_WITH_CONTEXT == "stub_with_context"

    def test_conflicting_requirements(self) -> None:
        assert FailureMode.CONFLICTING_REQUIREMENTS == "conflicting_requirements"

    def test_unknown_projection_type(self) -> None:
        assert FailureMode.UNKNOWN_PROJECTION_TYPE == "unknown_projection_type"


class TestStrategyGapEvidence:
    """Verify StrategyGapEvidence generates unique gap_id and has enhanced fields."""

    def test_auto_generated_gap_id(self) -> None:
        gap = StrategyGapEvidence(
            failure_mode=FailureMode.MULTI_CONCERN_COMMENT,
            failure_category="translation",
            fixture={"failure_mode": "multi_concern_comment"},
        )
        assert gap.gap_id.startswith("gap_")
        assert len(gap.gap_id) > 4

    def test_unique_gap_ids(self) -> None:
        gap1 = StrategyGapEvidence(
            failure_mode=FailureMode.MULTI_CONCERN_COMMENT,
            failure_category="translation",
            fixture={},
        )
        gap2 = StrategyGapEvidence(
            failure_mode=FailureMode.VAGUE_ENTITY_REFERENCE,
            failure_category="translation",
            fixture={},
        )
        assert gap1.gap_id != gap2.gap_id

    def test_custom_gap_id_preserved(self) -> None:
        gap = StrategyGapEvidence(
            failure_mode="test",
            failure_category="translation",
            fixture={},
            gap_id="custom_gap_123",
        )
        assert gap.gap_id == "custom_gap_123"

    def test_failure_category_field(self) -> None:
        gap = StrategyGapEvidence(
            failure_mode="test",
            failure_category="projection",
            fixture={},
        )
        assert gap.failure_category == "projection"

    def test_translation_context_field(self) -> None:
        tc = TranslationContext(comment_text="# handle edge case")
        gap = StrategyGapEvidence(
            failure_mode="test",
            failure_category="translation",
            fixture={},
            translation_context=tc,
        )
        assert gap.translation_context is not None
        assert gap.translation_context.comment_text == "# handle edge case"

    def test_strategies_attempted_field(self) -> None:
        gap = StrategyGapEvidence(
            failure_mode="test",
            failure_category="translation",
            fixture={},
            strategies_attempted=["entity_resolution", "sentence_decomposition"],
        )
        assert len(gap.strategies_attempted) == 2

    def test_severity_property(self) -> None:
        gap = StrategyGapEvidence(
            failure_mode="test",
            failure_category="translation",
            fixture={},
        )
        assert gap.severity == "warning"

    def test_message_property(self) -> None:
        gap = StrategyGapEvidence(
            failure_mode="multi_concern_comment",
            failure_category="translation",
            fixture={},
        )
        assert "multi_concern_comment" in gap.message


class TestCaptureStrategyGap:
    """Verify capture_strategy_gap() populates failure_category and translation_context."""

    def test_capture_with_translation_context(self) -> None:
        registry = StrategyRegistry()
        tc = TranslationContext(
            comment_text="# validate and send",
            function_signature="def handle()",
            store_dependencies=["db"],
        )
        unit = make_unit(unit_id="u1", content="test content")
        ctx = ProcessingContext(
            units=[unit],
            phase=StrategyPhase.TRANSLATION,
            translation_context=tc,
        )

        gap = registry.capture_strategy_gap(
            context=ctx,
            failure_mode=FailureMode.MULTI_CONCERN_COMMENT,
            failing_inputs=[unit],
        )

        assert gap.failure_category == "translation"
        assert gap.translation_context is not None
        assert gap.translation_context.comment_text == "# validate and send"
        assert gap.fixture["context"]["comment_text"] == "# validate and send"
        assert gap.fixture["context"]["function_signature"] == "def handle()"
        assert gap.fixture["context"]["store_dependencies"] == ["db"]

    def test_capture_auto_categorizes_from_phase(self) -> None:
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
        assert gap.failure_category == "resolution"

    def test_capture_with_explicit_category(self) -> None:
        registry = StrategyRegistry()
        unit = make_unit(unit_id="u1", content="test")
        ctx = ProcessingContext(units=[unit], phase=StrategyPhase.CLEANING)

        gap = registry.capture_strategy_gap(
            context=ctx,
            failure_mode="test",
            failing_inputs=[unit],
            failure_category="projection",
        )
        assert gap.failure_category == "projection"
