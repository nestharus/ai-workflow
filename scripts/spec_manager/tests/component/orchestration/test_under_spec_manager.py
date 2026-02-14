"""Component tests for orchestration.under_spec.manager module.

Tests UnderSpecEvent/Constraint/UnderSpecOutcome construction and serialization,
ConstraintsStore file-based persistence, and UnderSpecManager.resolve() behavior
including interactive/auto resolution and constraint validation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from spec_manager.orchestration.intent_agent.signals import (
    UserQuestionSignal,
    UserQuestionSignalStore,
)
from spec_manager.orchestration.under_spec.manager import (
    UnderSpecEvent,
    UnderSpecManager,
    UnderSpecOutcome,
)
from spec_manager.planner.constraints.store import Constraint, ConstraintsStore

# ======================================================================
# UnderSpecEvent
# ======================================================================


class TestUnderSpecEventFromDict:
    """Test UnderSpecEvent.from_dict() deserialization."""

    def test_from_dict_all_fields(self) -> None:
        """from_dict() populates all fields from a well-formed dict."""
        d = {
            "event_id": "evt-1",
            "kind": "AMBIGUOUS_REQUIREMENT",
            "question": "Which format?",
            "context": {"file": "main.py"},
            "source_file": "main.py",
            "source_line": 42,
        }
        event = UnderSpecEvent.from_dict(d)

        assert event.event_id == "evt-1"
        assert event.kind == "AMBIGUOUS_REQUIREMENT"
        assert event.question == "Which format?"
        assert event.context == {"file": "main.py"}
        assert event.source_file == "main.py"
        assert event.source_line == 42

    def test_from_dict_defaults(self) -> None:
        """from_dict() uses defaults for missing keys."""
        event = UnderSpecEvent.from_dict({})

        assert event.event_id == ""
        assert event.kind == "MISSING_CONSTRAINT"
        assert event.question == ""
        assert event.context == {}
        assert event.source_file == ""
        assert event.source_line == 0

    def test_from_dict_file_key_fallback(self) -> None:
        """from_dict() falls back to 'file' key for source_file."""
        event = UnderSpecEvent.from_dict({"file": "legacy.py"})
        assert event.source_file == "legacy.py"

    def test_from_dict_source_file_takes_precedence(self) -> None:
        """from_dict() prefers source_file over file key."""
        event = UnderSpecEvent.from_dict(
            {
                "source_file": "new.py",
                "file": "legacy.py",
            }
        )
        assert event.source_file == "new.py"


class TestUnderSpecEventToDict:
    """Test UnderSpecEvent.to_dict() serialization."""

    def test_to_dict_contains_all_fields(self) -> None:
        """to_dict() includes every field."""
        event = UnderSpecEvent(
            event_id="evt-1",
            kind="CONFLICTING_CONSTRAINTS",
            question="Which one?",
            context={"a": 1},
            source_file="a.py",
            source_line=10,
        )
        d = event.to_dict()

        assert d["event_id"] == "evt-1"
        assert d["kind"] == "CONFLICTING_CONSTRAINTS"
        assert d["question"] == "Which one?"
        assert d["context"] == {"a": 1}
        assert d["source_file"] == "a.py"
        assert d["source_line"] == 10


class TestUnderSpecEventRoundTrip:
    """Test UnderSpecEvent from_dict/to_dict round-trip."""

    def test_round_trip_preserves_data(self) -> None:
        """from_dict(to_dict()) preserves all fields."""
        original = UnderSpecEvent(
            event_id="evt-round",
            kind="EXTERNAL_DEPENDENCY_UNKNOWN",
            question="What API version?",
            context={"api": "v2", "timeout": 30},
            source_file="client.py",
            source_line=99,
        )
        restored = UnderSpecEvent.from_dict(original.to_dict())

        assert restored.event_id == original.event_id
        assert restored.kind == original.kind
        assert restored.question == original.question
        assert restored.context == original.context
        assert restored.source_file == original.source_file
        assert restored.source_line == original.source_line


# ======================================================================
# Constraint
# ======================================================================


class TestConstraintFromDict:
    """Test Constraint.from_dict() deserialization."""

    def test_from_dict_all_fields(self) -> None:
        """from_dict() populates all fields from a well-formed dict."""
        d = {
            "constraint_id": "c-1",
            "question": "Which format?",
            "answer": "Use JSON format.",
            "source": "user",
            "confidence": 0.95,
            "validated": True,
        }
        c = Constraint.from_dict(d)

        assert c.constraint_id == "c-1"
        assert c.question == "Which format?"
        assert c.answer == "Use JSON format."
        assert c.source == "user"
        assert c.confidence == 0.95
        assert c.validated is True

    def test_from_dict_defaults(self) -> None:
        """from_dict() uses defaults for missing keys."""
        c = Constraint.from_dict({})
        assert c.constraint_id == ""
        assert c.source == "existing"
        assert c.confidence == 1.0
        assert c.validated is True


class TestConstraintRoundTrip:
    """Test Constraint from_dict/to_dict round-trip."""

    def test_round_trip_preserves_data(self) -> None:
        """from_dict(to_dict()) preserves all fields."""
        original = Constraint(
            constraint_id="c-round",
            question="What encoding?",
            answer="UTF-8 for all files.",
            source="research",
            confidence=0.8,
            validated=False,
        )
        restored = Constraint.from_dict(original.to_dict())

        assert restored.constraint_id == original.constraint_id
        assert restored.question == original.question
        assert restored.answer == original.answer
        assert restored.source == original.source
        assert restored.confidence == original.confidence
        assert restored.validated == original.validated


# ======================================================================
# UnderSpecOutcome
# ======================================================================


class TestUnderSpecOutcome:
    """Test UnderSpecOutcome properties."""

    def test_is_blocked_when_blocked_events_present(self) -> None:
        """is_blocked returns True when there are blocked events."""
        outcome = UnderSpecOutcome(blocked=[UnderSpecEvent(event_id="b1", question="Why?")])
        assert outcome.is_blocked is True

    def test_not_blocked_when_no_blocked_events(self) -> None:
        """is_blocked returns False when blocked list is empty."""
        outcome = UnderSpecOutcome(
            resolved=[UnderSpecEvent(event_id="r1")],
            blocked=[],
        )
        assert outcome.is_blocked is False

    def test_empty_outcome_is_not_blocked(self) -> None:
        """Default empty outcome is not blocked."""
        outcome = UnderSpecOutcome()
        assert outcome.is_blocked is False

    def test_blocked_questions_property(self) -> None:
        """blocked_questions returns questions from blocked events."""
        outcome = UnderSpecOutcome(
            blocked=[
                UnderSpecEvent(event_id="b1", question="Question 1"),
                UnderSpecEvent(event_id="b2", question="Question 2"),
                UnderSpecEvent(event_id="b3", question=""),  # empty, excluded
            ]
        )
        assert outcome.blocked_questions == ["Question 1", "Question 2"]


# ======================================================================
# ConstraintsStore
# ======================================================================


class TestConstraintsStoreLoad:
    """Test ConstraintsStore.load()."""

    def test_load_returns_empty_for_missing_file(self, tmp_path: Path) -> None:
        """load() returns empty list when no constraint file exists."""
        store = ConstraintsStore(tmp_path)
        result = store.load("nonexistent-slice")
        assert result == []

    def test_load_returns_empty_for_corrupt_json(self, tmp_path: Path) -> None:
        """load() returns empty list for corrupt JSON files."""
        constraints_dir = tmp_path / "analysis" / "constraints"
        constraints_dir.mkdir(parents=True)
        (constraints_dir / "bad.json").write_text("not valid json", encoding="utf-8")

        store = ConstraintsStore(tmp_path)
        result = store.load("bad")
        assert result == []


class TestConstraintsStoreSaveAndLoad:
    """Test ConstraintsStore.save() + load() round-trip."""

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        """save() followed by load() returns the same constraints."""
        store = ConstraintsStore(tmp_path)
        constraints = [
            Constraint(
                constraint_id="c-1",
                question="Format?",
                answer="JSON",
                source="user",
                confidence=1.0,
                validated=True,
            ),
            Constraint(
                constraint_id="c-2",
                question="Encoding?",
                answer="UTF-8",
                source="research",
                confidence=0.8,
                validated=False,
            ),
        ]

        path = store.save("my-slice", constraints)
        assert path.exists()
        assert path.name == "my-slice.json"

        loaded = store.load("my-slice")
        assert len(loaded) == 2
        assert loaded[0].constraint_id == "c-1"
        assert loaded[0].answer == "JSON"
        assert loaded[1].constraint_id == "c-2"
        assert loaded[1].answer == "UTF-8"

    def test_save_merges_with_existing(self, tmp_path: Path) -> None:
        """save() merges new constraints with existing (no duplicates)."""
        store = ConstraintsStore(tmp_path)

        # Save first batch
        store.save(
            "merge-slice",
            [
                Constraint(constraint_id="c-1", answer="First answer"),
            ],
        )

        # Save second batch (includes c-1 duplicate and c-2 new)
        store.save(
            "merge-slice",
            [
                Constraint(constraint_id="c-1", answer="Duplicate"),
                Constraint(constraint_id="c-2", answer="Second answer"),
            ],
        )

        loaded = store.load("merge-slice")
        assert len(loaded) == 2
        ids = [c.constraint_id for c in loaded]
        assert "c-1" in ids
        assert "c-2" in ids

    def test_save_creates_directory(self, tmp_path: Path) -> None:
        """save() creates the constraints directory if it doesn't exist."""
        store = ConstraintsStore(tmp_path)
        store.save(
            "new-slice",
            [
                Constraint(constraint_id="c-1", answer="Answer here"),
            ],
        )

        constraints_dir = tmp_path / "analysis" / "constraints"
        assert constraints_dir.exists()


class TestConstraintsStoreFindCovering:
    """Test ConstraintsStore.find_covering()."""

    def test_partitions_events_correctly(self, tmp_path: Path) -> None:
        """find_covering() separates covered and uncovered events."""
        store = ConstraintsStore(tmp_path)

        # Save constraints covering evt-1 and evt-3
        store.save(
            "test-slice",
            [
                Constraint(constraint_id="evt-1", answer="Answer 1"),
                Constraint(constraint_id="evt-3", answer="Answer 3"),
            ],
        )

        events = [
            UnderSpecEvent(event_id="evt-1", question="Q1"),
            UnderSpecEvent(event_id="evt-2", question="Q2"),
            UnderSpecEvent(event_id="evt-3", question="Q3"),
        ]

        covered, uncovered = store.find_covering("test-slice", events)

        assert len(covered) == 2
        assert len(uncovered) == 1
        assert covered[0].event_id == "evt-1"
        assert covered[1].event_id == "evt-3"
        assert uncovered[0].event_id == "evt-2"

    def test_all_uncovered_when_no_constraints(self, tmp_path: Path) -> None:
        """find_covering() returns all events as uncovered when no constraints exist."""
        store = ConstraintsStore(tmp_path)
        events = [
            UnderSpecEvent(event_id="evt-1"),
            UnderSpecEvent(event_id="evt-2"),
        ]

        covered, uncovered = store.find_covering("empty-slice", events)

        assert covered == []
        assert len(uncovered) == 2

    def test_all_covered(self, tmp_path: Path) -> None:
        """find_covering() returns all events as covered when fully covered."""
        store = ConstraintsStore(tmp_path)
        store.save(
            "full-slice",
            [
                Constraint(constraint_id="evt-1", answer="A1"),
                Constraint(constraint_id="evt-2", answer="A2"),
            ],
        )

        events = [
            UnderSpecEvent(event_id="evt-1"),
            UnderSpecEvent(event_id="evt-2"),
        ]

        covered, uncovered = store.find_covering("full-slice", events)

        assert len(covered) == 2
        assert uncovered == []


# ======================================================================
# UnderSpecManager
# ======================================================================


class TestUnderSpecManagerResolveNoEvents:
    """Test UnderSpecManager.resolve() with no events."""

    def test_returns_empty_outcome(self, tmp_path: Path) -> None:
        """resolve() with empty events list returns empty outcome."""
        manager = UnderSpecManager(workspace_root=tmp_path)
        outcome = manager.resolve(slice_id="s1", events=[])

        assert outcome.resolved == []
        assert outcome.blocked == []
        assert outcome.constraints == []
        assert outcome.is_blocked is False


class TestUnderSpecManagerResolveCoveredEvents:
    """Test UnderSpecManager.resolve() with fully covered events."""

    def test_returns_resolved(self, tmp_path: Path) -> None:
        """resolve() with constraint-covered events returns resolved outcome."""
        # Pre-create constraints
        store = ConstraintsStore(tmp_path)
        store.save(
            "covered-slice",
            [
                Constraint(
                    constraint_id="evt-1",
                    question="Which format?",
                    answer="Use JSON format for all data exchange.",
                    source="user",
                    confidence=1.0,
                    validated=True,
                ),
            ],
        )

        manager = UnderSpecManager(workspace_root=tmp_path)
        events = [
            UnderSpecEvent(event_id="evt-1", question="Which format?"),
        ]

        outcome = manager.resolve(slice_id="covered-slice", events=events)

        assert len(outcome.resolved) == 1
        assert outcome.resolved[0].event_id == "evt-1"
        assert outcome.blocked == []
        assert outcome.is_blocked is False


class TestUnderSpecManagerValidateConstraint:
    """Test UnderSpecManager._validate_constraint()."""

    def test_rejects_empty_answer(self, tmp_path: Path) -> None:
        """_validate_constraint() rejects constraints with empty answer."""
        manager = UnderSpecManager(workspace_root=tmp_path)
        c = Constraint(answer="")
        assert manager._validate_constraint(c) is False

    def test_rejects_whitespace_answer(self, tmp_path: Path) -> None:
        """_validate_constraint() rejects constraints with whitespace-only answer."""
        manager = UnderSpecManager(workspace_root=tmp_path)
        c = Constraint(answer="   ")
        assert manager._validate_constraint(c) is False

    def test_rejects_tbd(self, tmp_path: Path) -> None:
        """_validate_constraint() rejects 'TBD' as a non-answer."""
        manager = UnderSpecManager(workspace_root=tmp_path)
        c = Constraint(answer="TBD")
        assert manager._validate_constraint(c) is False

    def test_rejects_todo(self, tmp_path: Path) -> None:
        """_validate_constraint() rejects 'TODO' as a non-answer."""
        manager = UnderSpecManager(workspace_root=tmp_path)
        c = Constraint(answer="todo")
        assert manager._validate_constraint(c) is False

    def test_rejects_unknown(self, tmp_path: Path) -> None:
        """_validate_constraint() rejects 'unknown' as a non-answer."""
        manager = UnderSpecManager(workspace_root=tmp_path)
        c = Constraint(answer="unknown")
        assert manager._validate_constraint(c) is False

    def test_rejects_na(self, tmp_path: Path) -> None:
        """_validate_constraint() rejects 'N/A' as a non-answer."""
        manager = UnderSpecManager(workspace_root=tmp_path)
        c = Constraint(answer="N/A")
        assert manager._validate_constraint(c) is False

    def test_rejects_question_mark(self, tmp_path: Path) -> None:
        """_validate_constraint() rejects '?' as a non-answer."""
        manager = UnderSpecManager(workspace_root=tmp_path)
        c = Constraint(answer="?")
        assert manager._validate_constraint(c) is False

    def test_rejects_ellipsis(self, tmp_path: Path) -> None:
        """_validate_constraint() rejects '...' as a non-answer."""
        manager = UnderSpecManager(workspace_root=tmp_path)
        c = Constraint(answer="...")
        assert manager._validate_constraint(c) is False

    def test_rejects_short_answer(self, tmp_path: Path) -> None:
        """_validate_constraint() rejects answers shorter than 5 characters."""
        manager = UnderSpecManager(workspace_root=tmp_path)
        c = Constraint(answer="yes")
        assert manager._validate_constraint(c) is False

    def test_accepts_valid_answer(self, tmp_path: Path) -> None:
        """_validate_constraint() accepts a concrete answer."""
        manager = UnderSpecManager(workspace_root=tmp_path)
        c = Constraint(answer="Use JSON format for all data exchange.")
        assert manager._validate_constraint(c) is True


# ======================================================================
# _resolve_interactive — UserQuestionSignal emission (Gap 3)
# ======================================================================


class TestResolveInteractiveEmitsSignals:
    """Test _resolve_interactive() emits UserQuestionSignals."""

    def test_emits_one_signal_per_event(self, tmp_path: Path) -> None:
        """_resolve_interactive() writes one UserQuestionSignal per event."""
        manager = UnderSpecManager(
            workspace_root=tmp_path,
            mode="interactive",
            run_id="run-42",
        )
        events = [
            UnderSpecEvent(event_id="evt-1", kind="MISSING_CONSTRAINT", question="What format?"),
            UnderSpecEvent(event_id="evt-2", kind="AMBIGUOUS_REQUIREMENT", question="Which API?"),
        ]

        constraints, blocked = manager._resolve_interactive("my-slice", events)

        # No constraints — Planner is the only writer
        assert constraints == []
        # All events remain blocked
        assert len(blocked) == 2

        # Read back signals from the store
        run_dir = tmp_path / ".pdd_runs" / "run-42"
        store = UserQuestionSignalStore(run_dir)
        signals = store.read_all()

        assert len(signals) == 2
        assert signals[0].source.kind == "UNDER_SPEC"
        assert signals[0].source.slice_id == "my-slice"
        assert signals[0].source.trace_id == "evt-1"
        assert signals[0].question.text == "What format?"
        assert signals[0].question.canonical_key_hint == "underspec.evt-1"
        assert signals[0].context.blocking.severity == "BLOCKING"
        assert "my-slice" in signals[0].context.blocking.blocked_slices
        assert signals[0].run_id == "run-42"

        # Ambiguous slice-level event is attributed to SLICE_AGENT.
        assert signals[1].source.kind == "SLICE_AGENT"
        assert signals[1].source.trace_id == "evt-2"
        assert signals[1].question.text == "Which API?"

    def test_payload_contains_event_dict(self, tmp_path: Path) -> None:
        """_resolve_interactive() stores the event dict as payload."""
        manager = UnderSpecManager(
            workspace_root=tmp_path,
            mode="interactive",
            run_id="run-payload",
        )
        event = UnderSpecEvent(
            event_id="evt-p",
            kind="MISSING_CONSTRAINT",
            question="What timeout?",
            source_file="client.py",
            source_line=42,
            context={"api": "payments"},
        )

        manager._resolve_interactive("slice-p", [event])

        run_dir = tmp_path / ".pdd_runs" / "run-payload"
        store = UserQuestionSignalStore(run_dir)
        signals = store.read_all()

        assert len(signals) == 1
        assert signals[0].payload["event_id"] == "evt-p"
        assert signals[0].payload["kind"] == "MISSING_CONSTRAINT"
        assert signals[0].payload["question"] == "What timeout?"
        assert signals[0].payload["source_file"] == "client.py"
        assert signals[0].payload["source_line"] == 42

    def test_code_refs_populated_when_source_file_present(self, tmp_path: Path) -> None:
        """_resolve_interactive() populates code_refs when source_file is set."""
        manager = UnderSpecManager(
            workspace_root=tmp_path,
            mode="interactive",
            run_id="run-refs",
        )
        event = UnderSpecEvent(
            event_id="evt-r",
            question="What encoding?",
            source_file="parser.py",
            source_line=99,
        )

        manager._resolve_interactive("slice-r", [event])

        run_dir = tmp_path / ".pdd_runs" / "run-refs"
        store = UserQuestionSignalStore(run_dir)
        signals = store.read_all()

        assert len(signals) == 1
        assert len(signals[0].context.code_refs) == 1
        assert signals[0].context.code_refs[0].file == "parser.py"
        assert signals[0].context.code_refs[0].line == 99

    def test_no_code_refs_when_no_source_file(self, tmp_path: Path) -> None:
        """_resolve_interactive() omits code_refs when source_file is empty."""
        manager = UnderSpecManager(
            workspace_root=tmp_path,
            mode="interactive",
            run_id="run-norefs",
        )
        event = UnderSpecEvent(event_id="evt-n", question="What?")

        manager._resolve_interactive("slice-n", [event])

        run_dir = tmp_path / ".pdd_runs" / "run-norefs"
        store = UserQuestionSignalStore(run_dir)
        signals = store.read_all()

        assert len(signals) == 1
        assert signals[0].context.code_refs == []

    def test_resolve_routes_to_interactive_signal_emission(self, tmp_path: Path) -> None:
        """resolve() in interactive mode delegates to _resolve_interactive, emitting signals."""
        manager = UnderSpecManager(
            workspace_root=tmp_path,
            mode="interactive",
            run_id="run-resolve",
        )
        events = [
            UnderSpecEvent(event_id="evt-x", question="What should X do?"),
        ]

        outcome = manager.resolve(slice_id="my-slice", events=events)

        # Event is blocked (no constraints from interactive mode)
        assert outcome.is_blocked is True
        assert len(outcome.blocked) == 1

        # Signal was emitted
        run_dir = tmp_path / ".pdd_runs" / "run-resolve"
        store = UserQuestionSignalStore(run_dir)
        signals = store.read_all()
        assert len(signals) == 1
        assert signals[0].question.text == "What should X do?"


class _PlannerUnderSpecStub:
    """Simple planner stub for UnderSpecManager auto-resolution tests."""

    def __init__(self, outputs: dict[str, Any]) -> None:
        self._outputs = outputs

    def resolve_under_spec(self, ctx: Any, events: list[dict[str, Any]]) -> dict[str, Any]:
        return self._outputs


class TestResolveAutoAuthorityConfidenceGate:
    """Auto-mode gate tests for authority and confidence checks."""

    def test_auto_resolves_when_authority_and_confidence_pass(self, tmp_path: Path) -> None:
        """Auto mode resolves only when gate passes."""
        manager = UnderSpecManager(
            workspace_root=tmp_path,
            mode="auto",
            planner=_PlannerUnderSpecStub(
                {
                    "blocked": False,
                    "constraints": {
                        "evt-pass": {
                            "answer": "Use JSON responses for all endpoints.",
                            "confidence": 0.93,
                            "authority_required": "planner_ok",
                        }
                    },
                }
            ),
        )
        events = [
            UnderSpecEvent(event_id="evt-pass", question="What format should API output use?")
        ]

        outcome = manager.resolve(slice_id="slice-pass", events=events, layer="l2")

        assert outcome.is_blocked is False
        assert len(outcome.resolved) == 1
        assert outcome.resolved[0].event_id == "evt-pass"
        assert len(outcome.constraints) == 1
        assert outcome.constraints[0].confidence == pytest.approx(0.93)
        assert outcome.constraints[0].authority_required == "planner_ok"
        assert "auto_resolve_gate=passed" in outcome.constraints[0].trace

    def test_auto_blocks_human_authority_even_with_high_confidence(self, tmp_path: Path) -> None:
        """Auto mode blocks human-authority events regardless of confidence."""
        manager = UnderSpecManager(
            workspace_root=tmp_path,
            mode="auto",
            planner=_PlannerUnderSpecStub(
                {
                    "blocked": False,
                    "constraints": {
                        "evt-human": {
                            "answer": "Choose provider A.",
                            "confidence": 0.95,
                            "authority_required": "human_required",
                        }
                    },
                }
            ),
        )
        events = [
            UnderSpecEvent(
                event_id="evt-human",
                question="Which vendor should be selected?",
                context={"type": "decision_required", "reason": "human authority required"},
            )
        ]

        outcome = manager.resolve(slice_id="slice-human", events=events, layer="l2")

        assert outcome.is_blocked is True
        assert outcome.resolved == []
        assert outcome.constraints == []
        assert len(outcome.blocked) == 1
        gate = outcome.blocked[0].context.get("auto_resolve_gate", {})
        assert gate.get("decision") == "blocked"
        assert gate.get("reason") == "human_authority_required"
        assert gate.get("authority_required") == "human_required"

    def test_auto_blocks_low_confidence(self, tmp_path: Path) -> None:
        """Auto mode blocks low-confidence constraints with gate traceability."""
        manager = UnderSpecManager(
            workspace_root=tmp_path,
            mode="auto",
            planner=_PlannerUnderSpecStub(
                {
                    "blocked": False,
                    "constraints": {
                        "evt-low": {
                            "answer": "Use provider B for now.",
                            "confidence": 0.41,
                            "authority_required": "planner_ok",
                        }
                    },
                }
            ),
        )
        events = [UnderSpecEvent(event_id="evt-low", question="Which provider should be selected?")]

        outcome = manager.resolve(slice_id="slice-low", events=events, layer="l2")

        assert outcome.is_blocked is True
        assert outcome.resolved == []
        assert outcome.constraints == []
        assert len(outcome.blocked) == 1
        gate = outcome.blocked[0].context.get("auto_resolve_gate", {})
        assert gate.get("decision") == "blocked"
        assert gate.get("reason") == "confidence_below_threshold"
        assert gate.get("authority_required") == "planner_ok"
        assert gate.get("confidence") == pytest.approx(0.41)
