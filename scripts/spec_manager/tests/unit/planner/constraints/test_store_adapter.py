"""Tests for planner.constraints.store_adapter — load/save, merge, conversion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spec_manager.orchestration.under_spec.manager import Constraint, ConstraintsStore
from spec_manager.planner.constraints.store_adapter import ConstraintStoreAdapter
from spec_manager.planner.constraints.types import (
    ConstraintFact,
    ConstraintHypothesis,
)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Create an empty workspace."""
    return tmp_path


@pytest.fixture()
def adapter(workspace: Path) -> ConstraintStoreAdapter:
    return ConstraintStoreAdapter(workspace)


# ===================================================================
# load_merged
# ===================================================================


class TestLoadMerged:
    def test_empty_store(self, adapter: ConstraintStoreAdapter):
        result = adapter.load_merged("my_slice")
        assert result == []

    def test_system_only(self, workspace: Path, adapter: ConstraintStoreAdapter):
        store = ConstraintsStore(workspace)
        store.save("__system__", [
            Constraint(constraint_id="SYS-1", question="Q1", answer="A1"),
        ])
        result = adapter.load_merged("my_slice")
        assert len(result) == 1
        assert result[0].constraint_id == "SYS-1"
        assert isinstance(result[0], ConstraintFact)

    def test_slice_only(self, workspace: Path, adapter: ConstraintStoreAdapter):
        store = ConstraintsStore(workspace)
        store.save("my_slice", [
            Constraint(constraint_id="LOC-1", question="Q2", answer="A2"),
        ])
        result = adapter.load_merged("my_slice")
        assert len(result) == 1
        assert result[0].constraint_id == "LOC-1"

    def test_merge_system_and_slice(self, workspace: Path, adapter: ConstraintStoreAdapter):
        store = ConstraintsStore(workspace)
        store.save("__system__", [
            Constraint(constraint_id="SYS-1", question="Q1", answer="A1"),
            Constraint(constraint_id="SYS-2", question="Q2", answer="A2"),
        ])
        store.save("my_slice", [
            Constraint(constraint_id="LOC-1", question="Q3", answer="A3"),
        ])
        result = adapter.load_merged("my_slice")
        ids = {f.constraint_id for f in result}
        assert ids == {"SYS-1", "SYS-2", "LOC-1"}

    def test_slice_overrides_system(self, workspace: Path, adapter: ConstraintStoreAdapter):
        store = ConstraintsStore(workspace)
        store.save("__system__", [
            Constraint(constraint_id="C-1", question="Q", answer="system_answer"),
        ])
        store.save("my_slice", [
            Constraint(constraint_id="C-1", question="Q", answer="slice_answer"),
        ])
        result = adapter.load_merged("my_slice")
        assert len(result) == 1
        assert result[0].answer == "slice_answer"

    def test_result_types_are_constraint_facts(self, workspace: Path, adapter: ConstraintStoreAdapter):
        store = ConstraintsStore(workspace)
        store.save("__system__", [
            Constraint(constraint_id="X", question="Q", answer="A", source="user"),
        ])
        result = adapter.load_merged("test")
        assert all(isinstance(f, ConstraintFact) for f in result)
        assert result[0].source == "user"


# ===================================================================
# save_facts
# ===================================================================


class TestSaveFacts:
    def test_save_and_reload(self, adapter: ConstraintStoreAdapter):
        facts = [
            ConstraintFact(
                constraint_id="F-1",
                question="Q",
                answer="A",
                source="research",
                confidence=0.8,
                validated=True,
            ),
        ]
        path = adapter.save_facts("my_slice", facts)
        assert path.exists()

        reloaded = adapter.load_merged("my_slice")
        assert len(reloaded) == 1
        assert reloaded[0].constraint_id == "F-1"
        assert reloaded[0].question == "Q"
        assert reloaded[0].answer == "A"

    def test_save_multiple(self, adapter: ConstraintStoreAdapter):
        facts = [
            ConstraintFact(constraint_id="F-1", question="Q1", answer="A1"),
            ConstraintFact(constraint_id="F-2", question="Q2", answer="A2"),
        ]
        adapter.save_facts("s", facts)
        reloaded = adapter.load_merged("s")
        assert len(reloaded) == 2

    def test_save_merges_with_existing(self, workspace: Path, adapter: ConstraintStoreAdapter):
        store = ConstraintsStore(workspace)
        store.save("s", [Constraint(constraint_id="OLD", question="Q0", answer="A0")])

        adapter.save_facts("s", [
            ConstraintFact(constraint_id="NEW", question="Q1", answer="A1"),
        ])
        reloaded = adapter.load_merged("s")
        ids = {f.constraint_id for f in reloaded}
        assert ids == {"OLD", "NEW"}

    def test_save_returns_path(self, adapter: ConstraintStoreAdapter):
        path = adapter.save_facts("s", [
            ConstraintFact(constraint_id="X", question="Q", answer="A"),
        ])
        assert isinstance(path, Path)
        assert path.suffix == ".json"

    def test_conversion_preserves_core_fields(self, adapter: ConstraintStoreAdapter):
        fact = ConstraintFact(
            constraint_id="C",
            question="Q",
            answer="A",
            source="steering",
            confidence=0.5,
            validated=False,
        )
        adapter.save_facts("s", [fact])
        reloaded = adapter.load_merged("s")
        r = reloaded[0]
        assert r.constraint_id == "C"
        assert r.source == "steering"
        assert r.confidence == 0.5
        assert r.validated is False


# ===================================================================
# Hypotheses
# ===================================================================


class TestHypotheses:
    def test_save_and_load(self, adapter: ConstraintStoreAdapter):
        hyps = [
            ConstraintHypothesis(
                hypothesis_id="H-1",
                question="Q",
                inferred_answer="A",
                source="llm",
                confidence=0.4,
                reasoning="because",
            ),
        ]
        path = adapter.save_hypotheses("s", hyps)
        assert path.exists()

        reloaded = adapter.load_hypotheses("s")
        assert len(reloaded) == 1
        assert reloaded[0].hypothesis_id == "H-1"
        assert reloaded[0].inferred_answer == "A"

    def test_load_nonexistent(self, adapter: ConstraintStoreAdapter):
        assert adapter.load_hypotheses("nope") == []

    def test_save_overwrites(self, adapter: ConstraintStoreAdapter):
        adapter.save_hypotheses("s", [
            ConstraintHypothesis(hypothesis_id="H1"),
        ])
        adapter.save_hypotheses("s", [
            ConstraintHypothesis(hypothesis_id="H2"),
        ])
        reloaded = adapter.load_hypotheses("s")
        assert len(reloaded) == 1
        assert reloaded[0].hypothesis_id == "H2"

    def test_save_creates_directory(self, workspace: Path, adapter: ConstraintStoreAdapter):
        adapter.save_hypotheses("s", [ConstraintHypothesis(hypothesis_id="H")])
        hyp_dir = workspace / "analysis" / "constraints_hypotheses"
        assert hyp_dir.is_dir()

    def test_hypothesis_round_trip_all_fields(self, adapter: ConstraintStoreAdapter):
        h = ConstraintHypothesis(
            hypothesis_id="H",
            question="Q",
            inferred_answer="A",
            source="src",
            confidence=0.7,
            dimension="legal",
            reasoning="because reasons",
        )
        adapter.save_hypotheses("s", [h])
        reloaded = adapter.load_hypotheses("s")
        assert reloaded[0] == h

    def test_load_corrupt_json(self, workspace: Path, adapter: ConstraintStoreAdapter):
        hyp_dir = workspace / "analysis" / "constraints_hypotheses"
        hyp_dir.mkdir(parents=True, exist_ok=True)
        (hyp_dir / "bad.json").write_text("not json", encoding="utf-8")
        assert adapter.load_hypotheses("bad") == []


# ===================================================================
# Conversion helpers
# ===================================================================


class TestConversion:
    def test_constraint_to_fact(self):
        c = Constraint(
            constraint_id="C",
            question="Q",
            answer="A",
            source="user",
            confidence=0.9,
            validated=True,
        )
        f = ConstraintStoreAdapter._constraint_to_fact(c)
        assert isinstance(f, ConstraintFact)
        assert f.constraint_id == "C"
        assert f.source == "user"

    def test_fact_to_constraint(self):
        f = ConstraintFact(
            constraint_id="F",
            question="Q",
            answer="A",
            source="research",
            confidence=0.5,
            validated=False,
        )
        c = ConstraintStoreAdapter._fact_to_constraint(f)
        assert isinstance(c, Constraint)
        assert c.constraint_id == "F"
        assert c.source == "research"
        assert c.validated is False

    def test_constraint_to_fact_preserves_rich_fields(self):
        """Verify that _constraint_to_fact preserves all rich fields."""
        c = Constraint(
            constraint_id="RICH-1",
            question="Should we use ORM?",
            answer="No ORM, use raw SQL",
            source="user",
            confidence=1.0,
            validated=True,
            dimension="legal",
            authority_required="human_required",
            scope="intra:payments",
            applies_to_layers=["L1", "L2"],
            status="ACTIVE",
            supersedes=["old-1"],
            trace=["source.md:5", "discussion.md:12"],
        )
        f = ConstraintStoreAdapter._constraint_to_fact(c)

        assert f.constraint_id == "RICH-1"
        assert f.question == "Should we use ORM?"
        assert f.answer == "No ORM, use raw SQL"
        assert f.source == "user"
        assert f.confidence == 1.0
        assert f.validated is True
        assert f.dimension == "legal"
        assert f.authority_required == "human_required"
        assert f.scope == "intra:payments"
        assert f.applies_to_layers == ["L1", "L2"]
        assert f.status == "ACTIVE"
        assert f.supersedes == ["old-1"]
        assert f.trace == ["source.md:5", "discussion.md:12"]

    def test_fact_to_constraint_preserves_rich_fields(self):
        """Verify that _fact_to_constraint preserves all rich fields."""
        f = ConstraintFact(
            constraint_id="RICH-2",
            question="What authentication method?",
            answer="Use JWT tokens",
            source="research",
            confidence=0.85,
            validated=True,
            dimension="organizational",
            authority_required="planner_ok",
            scope="inter:auth->api:tokens",
            applies_to_layers=["L1", "L2", "L3"],
            status="ACTIVE",
            supersedes=["old-2", "old-3"],
            trace=["research.md:10", "decision.md:5"],
        )
        c = ConstraintStoreAdapter._fact_to_constraint(f)

        assert c.constraint_id == "RICH-2"
        assert c.question == "What authentication method?"
        assert c.answer == "Use JWT tokens"
        assert c.source == "research"
        assert c.confidence == 0.85
        assert c.validated is True
        assert c.dimension == "organizational"
        assert c.authority_required == "planner_ok"
        assert c.scope == "inter:auth->api:tokens"
        assert c.applies_to_layers == ["L1", "L2", "L3"]
        assert c.status == "ACTIVE"
        assert c.supersedes == ["old-2", "old-3"]
        assert c.trace == ["research.md:10", "decision.md:5"]

    def test_load_save_roundtrip_preserves_rich_fields(self, tmp_path: Path):
        """Verify that save_facts + load_merged preserves all rich fields."""
        adapter = ConstraintStoreAdapter(tmp_path)

        # Create a fact with all rich fields populated
        original_fact = ConstraintFact(
            constraint_id="ROUNDTRIP-1",
            question="Database choice?",
            answer="PostgreSQL with partitioning",
            source="steering",
            confidence=0.95,
            validated=True,
            dimension="economic",
            authority_required="human_required",
            scope="system",
            applies_to_layers=["L1"],
            status="ACTIVE",
            supersedes=["prev-1"],
            trace=["spec.md:100", "meeting.md:5"],
        )

        # Save via adapter
        adapter.save_facts("test_slice", [original_fact])

        # Reload via adapter
        reloaded = adapter.load_merged("test_slice")

        # Verify all fields survived
        assert len(reloaded) == 1
        r = reloaded[0]
        assert r.constraint_id == "ROUNDTRIP-1"
        assert r.question == "Database choice?"
        assert r.answer == "PostgreSQL with partitioning"
        assert r.source == "steering"
        assert r.confidence == 0.95
        assert r.validated is True
        assert r.dimension == "economic"
        assert r.authority_required == "human_required"
        assert r.scope == "system"
        assert r.applies_to_layers == ["L1"]
        assert r.status == "ACTIVE"
        assert r.supersedes == ["prev-1"]
        assert r.trace == ["spec.md:100", "meeting.md:5"]


# ===================================================================
# Callback tests
# ===================================================================


class TestOnConstraintSavedCallback:
    def test_save_facts_fires_callback(self, workspace: Path):
        """Verify that save_facts invokes the callback for each constraint."""
        # Track callback invocations
        calls: list[tuple[str, str]] = []

        def callback(slice_id: str, constraint_id: str) -> None:
            calls.append((slice_id, constraint_id))

        adapter = ConstraintStoreAdapter(workspace, on_constraint_saved=callback)

        facts = [
            ConstraintFact(constraint_id="C-1", question="Q1", answer="A1"),
            ConstraintFact(constraint_id="C-2", question="Q2", answer="A2"),
            ConstraintFact(constraint_id="C-3", question="Q3", answer="A3"),
        ]

        adapter.save_facts("my_slice", facts)

        # Verify callback was called for each constraint
        assert len(calls) == 3
        assert calls == [
            ("my_slice", "C-1"),
            ("my_slice", "C-2"),
            ("my_slice", "C-3"),
        ]

    def test_save_facts_no_callback(self, workspace: Path):
        """Verify that save_facts works without a callback."""
        adapter = ConstraintStoreAdapter(workspace)  # No callback

        facts = [
            ConstraintFact(constraint_id="C-1", question="Q", answer="A"),
        ]

        # Should not raise
        path = adapter.save_facts("slice", facts)
        assert path.exists()

        # Facts should still be saved
        reloaded = adapter.load_merged("slice")
        assert len(reloaded) == 1
        assert reloaded[0].constraint_id == "C-1"

    def test_save_facts_callback_error_suppressed(self, workspace: Path):
        """Verify that callback errors don't prevent saving."""

        def bad_callback(slice_id: str, constraint_id: str) -> None:
            raise RuntimeError("Callback intentionally failed")

        adapter = ConstraintStoreAdapter(workspace, on_constraint_saved=bad_callback)

        facts = [
            ConstraintFact(constraint_id="C-1", question="Q", answer="A"),
        ]

        # Should not raise despite callback error
        path = adapter.save_facts("slice", facts)
        assert path.exists()

        # Facts should still be saved
        reloaded = adapter.load_merged("slice")
        assert len(reloaded) == 1
        assert reloaded[0].constraint_id == "C-1"

    def test_callback_not_invoked_for_empty_constraint_id(self, workspace: Path):
        """Verify that callback is skipped for facts with empty constraint_id."""
        calls: list[tuple[str, str]] = []

        def callback(slice_id: str, constraint_id: str) -> None:
            calls.append((slice_id, constraint_id))

        adapter = ConstraintStoreAdapter(workspace, on_constraint_saved=callback)

        facts = [
            ConstraintFact(constraint_id="C-1", question="Q1", answer="A1"),
            ConstraintFact(constraint_id="", question="Q2", answer="A2"),  # Empty ID
            ConstraintFact(constraint_id="C-3", question="Q3", answer="A3"),
        ]

        adapter.save_facts("slice", facts)

        # Callback should only be invoked for C-1 and C-3
        assert len(calls) == 2
        assert calls == [
            ("slice", "C-1"),
            ("slice", "C-3"),
        ]
