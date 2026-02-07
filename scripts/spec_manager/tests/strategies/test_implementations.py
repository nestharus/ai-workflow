"""Tests for Plan 5: Five paradigm-specific strategy definitions and implementations."""

from __future__ import annotations

from pathlib import Path

from spec_manager.strategies.base import (
    ProcessingContext,
    StrategyPhase,
    TranslationContext,
)
from spec_manager.strategies.implementations.adjacency_detection import (
    AdjacencyDetectionStrategy,
)
from spec_manager.strategies.implementations.ambiguity_research import (
    AmbiguityResearchStrategy,
)
from spec_manager.strategies.implementations.comment_decomposition import (
    CommentDecompositionStrategy,
)
from spec_manager.strategies.implementations.stub_promotion import (
    StubPromotionStrategy,
)
from spec_manager.strategies.implementations.translation_entity_resolution import (
    TranslationEntityResolutionStrategy,
)
from spec_manager.strategies.registry import StrategyRegistry
from tests.strategies.conftest import make_unit


DEFINITIONS_DIR = (
    Path(__file__).resolve().parents[2] / "spec_manager" / "strategies" / "definitions"
)


class TestYAMLDefinitionsLoad:
    """Verify each new strategy can be loaded from YAML definition."""

    def setup_method(self) -> None:
        self.registry = StrategyRegistry()
        self.registry.load_from_directory(DEFINITIONS_DIR)

    def test_comment_decomposition_loaded(self) -> None:
        assert "comment_decomposition" in self.registry.definitions
        defn = self.registry.definitions["comment_decomposition"]
        assert defn.implementation_class is not None
        assert "translation" in defn.phases

    def test_ambiguity_research_loaded(self) -> None:
        assert "ambiguity_research" in self.registry.definitions
        defn = self.registry.definitions["ambiguity_research"]
        assert defn.implementation_class is not None

    def test_adjacency_detection_loaded(self) -> None:
        assert "adjacency_detection" in self.registry.definitions
        defn = self.registry.definitions["adjacency_detection"]
        assert "translation" in defn.phases
        assert "projection" in defn.phases

    def test_stub_promotion_loaded(self) -> None:
        assert "stub_promotion" in self.registry.definitions

    def test_translation_entity_resolution_loaded(self) -> None:
        assert "translation_entity_resolution" in self.registry.definitions

    def test_all_new_definitions_loaded(self) -> None:
        new_names = {
            "comment_decomposition",
            "ambiguity_research",
            "adjacency_detection",
            "stub_promotion",
            "translation_entity_resolution",
        }
        loaded_names = set(self.registry.definitions.keys())
        assert new_names.issubset(loaded_names)


# =========================================================================
# CommentDecompositionStrategy
# =========================================================================


class TestCommentDecompositionStrategy:
    """Verify applies_to and execute for CommentDecompositionStrategy."""

    def test_applies_to_with_multi_concern_comment(self) -> None:
        strategy = CommentDecompositionStrategy()
        tc = TranslationContext(comment_text="# validate payment and send confirmation")
        ctx = ProcessingContext(
            units=[make_unit()],
            phase=StrategyPhase.TRANSLATION,
            translation_context=tc,
        )
        assert strategy.applies_to(ctx) is True

    def test_does_not_apply_without_translation_context(self) -> None:
        strategy = CommentDecompositionStrategy()
        ctx = ProcessingContext(
            units=[make_unit()],
            phase=StrategyPhase.TRANSLATION,
        )
        assert strategy.applies_to(ctx) is False

    def test_does_not_apply_to_single_concern(self) -> None:
        strategy = CommentDecompositionStrategy()
        tc = TranslationContext(comment_text="# validate payment")
        ctx = ProcessingContext(
            units=[make_unit()],
            phase=StrategyPhase.TRANSLATION,
            translation_context=tc,
        )
        assert strategy.applies_to(ctx) is False

    def test_execute_splits_comment(self) -> None:
        strategy = CommentDecompositionStrategy()
        tc = TranslationContext(comment_text="# validate payment and send confirmation")
        ctx = ProcessingContext(
            units=[make_unit()],
            phase=StrategyPhase.TRANSLATION,
            translation_context=tc,
        )
        result = strategy.execute(ctx)
        assert len(result.units) == 2
        assert len(result.actions_taken) > 0
        assert result.metrics["splits_performed"] == 2

    def test_phases_include_translation(self) -> None:
        strategy = CommentDecompositionStrategy()
        assert StrategyPhase.TRANSLATION in strategy.phases

    def test_name_property(self) -> None:
        strategy = CommentDecompositionStrategy()
        assert strategy.name == "comment_decomposition"


# =========================================================================
# AmbiguityResearchStrategy
# =========================================================================


class TestAmbiguityResearchStrategy:
    """Verify applies_to and execute for AmbiguityResearchStrategy."""

    def test_applies_to_with_short_comment_and_spec(self) -> None:
        strategy = AmbiguityResearchStrategy()
        tc = TranslationContext(
            comment_text="# fix it",
            hollowed_spec_path="/specs/payment.md",
        )
        ctx = ProcessingContext(
            units=[make_unit()],
            phase=StrategyPhase.TRANSLATION,
            translation_context=tc,
        )
        assert strategy.applies_to(ctx) is True

    def test_does_not_apply_without_spec_path(self) -> None:
        strategy = AmbiguityResearchStrategy()
        tc = TranslationContext(comment_text="# fix it")
        ctx = ProcessingContext(
            units=[make_unit()],
            phase=StrategyPhase.TRANSLATION,
            translation_context=tc,
        )
        assert strategy.applies_to(ctx) is False

    def test_does_not_apply_without_translation_context(self) -> None:
        strategy = AmbiguityResearchStrategy()
        ctx = ProcessingContext(
            units=[make_unit()],
            phase=StrategyPhase.TRANSLATION,
        )
        assert strategy.applies_to(ctx) is False

    def test_execute_without_tools(self) -> None:
        strategy = AmbiguityResearchStrategy()
        tc = TranslationContext(
            comment_text="# fix it",
            hollowed_spec_path="/specs/payment.md",
        )
        ctx = ProcessingContext(
            units=[make_unit()],
            phase=StrategyPhase.TRANSLATION,
            translation_context=tc,
        )
        result = strategy.execute(ctx)
        # Without tools, no research hits
        assert result.metrics["research_hits"] == 0
        assert len(result.issues) > 0  # Should report no hits found

    def test_name_property(self) -> None:
        strategy = AmbiguityResearchStrategy()
        assert strategy.name == "ambiguity_research"


# =========================================================================
# AdjacencyDetectionStrategy
# =========================================================================


class TestAdjacencyDetectionStrategy:
    """Verify applies_to and execute for AdjacencyDetectionStrategy."""

    def test_applies_to_with_store_dependencies(self) -> None:
        strategy = AdjacencyDetectionStrategy()
        tc = TranslationContext(
            comment_text="# update payment record",
            store_dependencies=["payment_db"],
            call_graph_neighbors=["validate_payment"],
        )
        ctx = ProcessingContext(
            units=[make_unit()],
            phase=StrategyPhase.TRANSLATION,
            translation_context=tc,
        )
        assert strategy.applies_to(ctx) is True

    def test_does_not_apply_without_stores(self) -> None:
        strategy = AdjacencyDetectionStrategy()
        tc = TranslationContext(comment_text="# simple calculation")
        ctx = ProcessingContext(
            units=[make_unit()],
            phase=StrategyPhase.TRANSLATION,
            translation_context=tc,
        )
        assert strategy.applies_to(ctx) is False

    def test_execute_detects_adjacencies(self) -> None:
        strategy = AdjacencyDetectionStrategy()
        tc = TranslationContext(
            comment_text="# update payment",
            function_signature="def update_payment()",
            store_dependencies=["payment_db", "audit_log"],
            call_graph_neighbors=["validate_payment", "send_receipt"],
        )
        ctx = ProcessingContext(
            units=[make_unit()],
            phase=StrategyPhase.TRANSLATION,
            translation_context=tc,
        )
        result = strategy.execute(ctx)
        assert result.metrics["adjacencies_detected"] > 0
        assert result.metrics["stores_analyzed"] == 2

    def test_phases_include_translation_and_projection(self) -> None:
        strategy = AdjacencyDetectionStrategy()
        assert StrategyPhase.TRANSLATION in strategy.phases
        assert StrategyPhase.PROJECTION in strategy.phases


# =========================================================================
# StubPromotionStrategy
# =========================================================================


class TestStubPromotionStrategy:
    """Verify applies_to and execute for StubPromotionStrategy."""

    def test_applies_to_with_stub_and_context(self) -> None:
        strategy = StubPromotionStrategy()
        tc = TranslationContext(
            comment_text="# implement payment validation logic",
            function_signature="def validate_payment(amount: float) -> bool",
            surrounding_code=[
                "def validate_payment(amount: float) -> bool:",
                '    """Validate payment amount against fraud rules."""',
                "    pass",
            ],
        )
        ctx = ProcessingContext(
            units=[make_unit()],
            phase=StrategyPhase.TRANSLATION,
            translation_context=tc,
        )
        assert strategy.applies_to(ctx) is True

    def test_does_not_apply_without_stub(self) -> None:
        strategy = StubPromotionStrategy()
        tc = TranslationContext(
            comment_text="# update record",
            function_signature="def update()",
            surrounding_code=["    result = db.query()", "    return result"],
        )
        ctx = ProcessingContext(
            units=[make_unit()],
            phase=StrategyPhase.TRANSLATION,
            translation_context=tc,
        )
        assert strategy.applies_to(ctx) is False

    def test_execute_with_promotable_stub(self) -> None:
        strategy = StubPromotionStrategy()
        tc = TranslationContext(
            comment_text="# calculate fibonacci recursively",
            function_signature="def fibonacci(n: int) -> int",
            surrounding_code=[
                "def fibonacci(n: int) -> int:",
                '    """Return the nth fibonacci number."""',
                "    raise NotImplementedError",
            ],
        )
        ctx = ProcessingContext(
            units=[make_unit()],
            phase=StrategyPhase.TRANSLATION,
            translation_context=tc,
        )
        result = strategy.execute(ctx)
        assert result.metrics["stubs_promoted"] == 1
        assert len(result.actions_taken) > 0

    def test_name_property(self) -> None:
        strategy = StubPromotionStrategy()
        assert strategy.name == "stub_promotion"


# =========================================================================
# TranslationEntityResolutionStrategy
# =========================================================================


class TestTranslationEntityResolutionStrategy:
    """Verify applies_to and execute for TranslationEntityResolutionStrategy."""

    def test_applies_to_with_vague_reference(self) -> None:
        strategy = TranslationEntityResolutionStrategy()
        tc = TranslationContext(
            comment_text="# the algorithm processes the input",
            call_graph_neighbors=["process_data", "validate_input"],
        )
        ctx = ProcessingContext(
            units=[make_unit()],
            phase=StrategyPhase.TRANSLATION,
            translation_context=tc,
        )
        assert strategy.applies_to(ctx) is True

    def test_does_not_apply_without_vague_refs(self) -> None:
        strategy = TranslationEntityResolutionStrategy()
        tc = TranslationContext(
            comment_text="# validate payment amount using fraud_checker module",
        )
        ctx = ProcessingContext(
            units=[make_unit()],
            phase=StrategyPhase.TRANSLATION,
            translation_context=tc,
        )
        assert strategy.applies_to(ctx) is False

    def test_execute_resolves_with_neighbors(self) -> None:
        strategy = TranslationEntityResolutionStrategy()
        tc = TranslationContext(
            comment_text="# the algorithm processes data",
            call_graph_neighbors=["process_algorithm"],
        )
        ctx = ProcessingContext(
            units=[make_unit(content="# the algorithm processes data")],
            phase=StrategyPhase.TRANSLATION,
            translation_context=tc,
        )
        result = strategy.execute(ctx)
        assert result.metrics["vague_references_found"] > 0

    def test_phases_include_translation(self) -> None:
        strategy = TranslationEntityResolutionStrategy()
        assert StrategyPhase.TRANSLATION in strategy.phases

    def test_name_property(self) -> None:
        strategy = TranslationEntityResolutionStrategy()
        assert strategy.name == "translation_entity_resolution"
