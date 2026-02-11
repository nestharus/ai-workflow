"""Component tests for orchestration.under_spec.manager module.

Tests UnderSpecEvent/Constraint/UnderSpecOutcome construction and serialization,
ConstraintsStore file-based persistence, and UnderSpecManager.resolve() behavior
including interactive/auto resolution and constraint validation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from spec_manager.orchestration.under_spec.manager import (
    Constraint,
    ConstraintsStore,
    UnderSpecEvent,
    UnderSpecManager,
    UnderSpecOutcome,
)

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


class TestUnderSpecManagerWriteConstraintRequest:
    """Test UnderSpecManager._write_constraint_request()."""

    def test_creates_markdown_file(self, tmp_path: Path) -> None:
        """_write_constraint_request() writes a markdown constraint request document."""
        manager = UnderSpecManager(workspace_root=tmp_path)
        events = [
            UnderSpecEvent(
                event_id="evt-1",
                kind="MISSING_CONSTRAINT",
                question="What timeout should be used?",
                source_file="client.py",
                source_line=42,
                context={"api": "payments"},
            ),
            UnderSpecEvent(
                event_id="evt-2",
                kind="AMBIGUOUS_REQUIREMENT",
                question="Which format for responses?",
            ),
        ]

        path = manager._write_constraint_request("test-slice", events)

        assert path.exists()
        assert path.name == "test-slice.md"
        assert path.parent.name == "constraint_requests"

        content = path.read_text(encoding="utf-8")
        assert "# Constraint Request: test-slice" in content
        assert "MISSING_CONSTRAINT" in content
        assert "What timeout should be used?" in content
        assert "`client.py`:42" in content
        assert "api: payments" in content
        assert "AMBIGUOUS_REQUIREMENT" in content
        assert "Which format for responses?" in content

    def test_creates_directory_structure(self, tmp_path: Path) -> None:
        """_write_constraint_request() creates parent directories."""
        manager = UnderSpecManager(workspace_root=tmp_path)
        events = [UnderSpecEvent(event_id="e1", question="Q?")]

        path = manager._write_constraint_request("s1", events)

        expected_dir = tmp_path / "analysis" / "constraint_requests"
        assert expected_dir.exists()
        assert path.parent == expected_dir
