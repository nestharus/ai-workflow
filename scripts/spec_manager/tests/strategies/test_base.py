"""Tests for Plan 1: Extend ProcessingContext and StrategyPhase for Translation/Projection."""

from __future__ import annotations

from spec_manager.strategies.base import (
    ProcessingContext,
    StrategyPhase,
    TranslationContext,
)
from tests.strategies.conftest import make_unit


class TestStrategyPhaseExtensions:
    """Verify TRANSLATION and PROJECTION phases exist."""

    def test_translation_phase_exists(self) -> None:
        assert StrategyPhase.TRANSLATION.value == "translation"

    def test_projection_phase_exists(self) -> None:
        assert StrategyPhase.PROJECTION.value == "projection"

    def test_all_original_phases_still_exist(self) -> None:
        expected = {
            "cleaning", "compositing", "decomposition",
            "extraction", "resolution", "labeling", "verification",
            "translation", "projection",
        }
        actual = {phase.value for phase in StrategyPhase}
        assert expected == actual


class TestTranslationContext:
    """Verify TranslationContext fields and serialization."""

    def test_minimal_construction(self) -> None:
        tc = TranslationContext(comment_text="# validate payment")
        assert tc.comment_text == "# validate payment"
        assert tc.function_signature is None
        assert tc.surrounding_code == []
        assert tc.file_path is None
        assert tc.line_number is None
        assert tc.hollowed_spec_path is None
        assert tc.store_dependencies == []
        assert tc.call_graph_neighbors == []

    def test_full_construction(self) -> None:
        tc = TranslationContext(
            comment_text="# handle payment",
            function_signature="def process_payment(amount: float) -> bool",
            surrounding_code=["    result = validate(amount)", "    return result"],
            file_path="/src/payments.py",
            line_number=42,
            hollowed_spec_path="/specs/payment_spec.md",
            store_dependencies=["payment_db", "audit_log"],
            call_graph_neighbors=["validate_payment", "send_confirmation"],
        )
        assert tc.function_signature == "def process_payment(amount: float) -> bool"
        assert len(tc.surrounding_code) == 2
        assert tc.line_number == 42
        assert "payment_db" in tc.store_dependencies
        assert "validate_payment" in tc.call_graph_neighbors


class TestProcessingContextWithTranslation:
    """Verify ProcessingContext accepts translation_context."""

    def test_context_without_translation(self) -> None:
        ctx = ProcessingContext(
            units=[],
            phase=StrategyPhase.CLEANING,
        )
        assert ctx.translation_context is None

    def test_context_with_translation(self) -> None:
        tc = TranslationContext(comment_text="# do something")
        unit = make_unit(unit_id="test_unit", content="test content")
        ctx = ProcessingContext(
            units=[unit],
            phase=StrategyPhase.TRANSLATION,
            translation_context=tc,
        )
        assert ctx.translation_context is not None
        assert ctx.translation_context.comment_text == "# do something"
        assert ctx.phase == StrategyPhase.TRANSLATION
