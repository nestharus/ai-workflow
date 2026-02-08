"""Tests for Plan 7: Persistence for Gap Evidence and Evolution State."""

from __future__ import annotations

import tempfile
from pathlib import Path

from spec_manager.strategies.base import (
    ProcessingContext,
    StrategyPhase,
    TranslationContext,
)
from spec_manager.strategies.evolution import (
    EvolutionStateStore,
    StrategyPerformanceRecord,
)
from spec_manager.strategies.registry import (
    FailureMode,
    StrategyGapEvidence,
    StrategyRegistry,
)

from tests.unit.strategies.conftest import make_unit


class TestEvolutionStateStoreGaps:
    """Verify gaps are written to and read from disk."""

    def test_save_and_load_gap_without_translation_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EvolutionStateStore(state_dir=tmpdir)

            gap = StrategyGapEvidence(
                failure_mode=FailureMode.MULTI_CONCERN_COMMENT,
                failure_category="translation",
                fixture={"failure_mode": "multi_concern_comment", "inputs": []},
                strategies_attempted=["sentence_decomposition"],
            )

            path = store.save_gap(gap)
            assert path.exists()
            assert path.suffix == ".yaml"

            loaded_gaps = store.load_gaps()
            assert len(loaded_gaps) == 1
            loaded = loaded_gaps[0]
            assert loaded.gap_id == gap.gap_id
            assert loaded.failure_mode == FailureMode.MULTI_CONCERN_COMMENT
            assert loaded.failure_category == "translation"
            assert loaded.strategies_attempted == ["sentence_decomposition"]

    def test_save_and_load_gap_with_translation_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EvolutionStateStore(state_dir=tmpdir)

            tc = TranslationContext(
                comment_text="# validate and send",
                function_signature="def process()",
                file_path="/src/main.py",
                line_number=42,
                hollowed_spec_path="/specs/spec.md",
                surrounding_code=["    pass"],
                store_dependencies=["db"],
                call_graph_neighbors=["validate"],
            )

            gap = StrategyGapEvidence(
                failure_mode=FailureMode.MULTI_CONCERN_COMMENT,
                failure_category="translation",
                fixture={},
                translation_context=tc,
            )

            store.save_gap(gap)
            loaded_gaps = store.load_gaps()
            assert len(loaded_gaps) == 1
            loaded = loaded_gaps[0]
            assert loaded.translation_context is not None
            assert loaded.translation_context.comment_text == "# validate and send"
            assert loaded.translation_context.function_signature == "def process()"
            assert loaded.translation_context.file_path == "/src/main.py"
            assert loaded.translation_context.line_number == 42
            assert loaded.translation_context.store_dependencies == ["db"]
            assert loaded.translation_context.call_graph_neighbors == ["validate"]

    def test_load_gaps_from_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EvolutionStateStore(state_dir=tmpdir)
            gaps = store.load_gaps()
            assert gaps == []

    def test_multiple_gaps_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EvolutionStateStore(state_dir=tmpdir)

            for fm in [FailureMode.MULTI_CONCERN_COMMENT, FailureMode.VAGUE_ENTITY_REFERENCE]:
                gap = StrategyGapEvidence(
                    failure_mode=fm,
                    failure_category="translation",
                    fixture={},
                )
                store.save_gap(gap)

            loaded = store.load_gaps()
            assert len(loaded) == 2
            modes = {g.failure_mode for g in loaded}
            assert FailureMode.MULTI_CONCERN_COMMENT in modes
            assert FailureMode.VAGUE_ENTITY_REFERENCE in modes


class TestEvolutionStateStorePerformance:
    """Verify performance records survive round-trip serialization."""

    def test_save_and_load_performance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EvolutionStateStore(state_dir=tmpdir)

            record = StrategyPerformanceRecord(
                strategy_name="comment_decomposition",
                successes=5,
                failures=1,
                applications=[{"actions": ["split"], "issues": [], "metrics": {}, "success": True}],
                failure_mode_counts_before={"multi_concern": 10},
                failure_mode_counts_after={"multi_concern": 3},
            )

            path = store.save_performance(record)
            assert path.exists()

            loaded = store.load_performance("comment_decomposition")
            assert loaded is not None
            assert loaded.strategy_name == "comment_decomposition"
            assert loaded.successes == 5
            assert loaded.failures == 1
            assert len(loaded.applications) == 1
            assert loaded.failure_mode_counts_before == {"multi_concern": 10}
            assert loaded.failure_mode_counts_after == {"multi_concern": 3}

    def test_load_nonexistent_performance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EvolutionStateStore(state_dir=tmpdir)
            result = store.load_performance("nonexistent")
            assert result is None


class TestEvolutionStateStoreExperimental:
    """Verify experimental strategy definitions are saved alongside stable ones."""

    def test_save_experimental_definition(self) -> None:
        from spec_manager.strategies.base import StrategyDefinition

        with tempfile.TemporaryDirectory() as tmpdir:
            store = EvolutionStateStore(state_dir=tmpdir)

            defn = StrategyDefinition(
                name="test_experimental",
                purpose="Test strategy",
                risk_addressed="Test risk",
                version="1.0",
                phases=["translation"],
                implementation_class="test.TestStrategy",
                metadata={"status": "experimental", "source_gap": "gap_123"},
            )

            path = store.save_experimental_definition(defn)
            assert path.exists()
            assert path.name == "test_experimental.yaml"

            # Verify the YAML content is readable
            import yaml

            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            assert data["name"] == "test_experimental"
            assert data["metadata"]["status"] == "experimental"


class TestPipelineWithPersistence:
    """Verify evolution pipeline integrates with state store."""

    def test_pipeline_persists_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = StrategyRegistry()
            registry.enable_evolution()

            store = EvolutionStateStore(state_dir=tmpdir)
            registry.evolution_pipeline.state_store = store

            unit = make_unit(unit_id="u1", content="test")
            ctx = ProcessingContext(
                units=[unit],
                phase=StrategyPhase.TRANSLATION,
                translation_context=TranslationContext(comment_text="# validate and send"),
            )

            registry.evolution_pipeline.on_translation_failure(
                context=ctx,
                failure_mode=FailureMode.MULTI_CONCERN_COMMENT,
            )

            # Verify gap was persisted
            loaded_gaps = store.load_gaps()
            assert len(loaded_gaps) == 1
            assert loaded_gaps[0].failure_mode == FailureMode.MULTI_CONCERN_COMMENT

            # Verify experimental definition was persisted
            exp_dir = Path(tmpdir) / "experimental"
            assert exp_dir.exists()
            exp_files = list(exp_dir.glob("*.yaml"))
            assert len(exp_files) == 1
