"""Unit tests for strict UserQuestionSignal schema parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from spec_manager.orchestration.intent_agent.signals import (
    SignalBlocking,
    SignalContext,
    SignalQuestion,
    SignalSource,
    UserQuestionSignal,
    UserQuestionSignalStore,
)

CANONICAL_SOURCE_KINDS = (
    "PLANNER",
    "UNDER_SPEC",
    "PROMOTION_LOOP",
    "PDD_LIFECYCLE",
    "SLICE_AGENT",
)


def _valid_signal_dict() -> dict[str, object]:
    return {
        "uq_version": 1,
        "uq_id": "uq-valid-1",
        "run_id": "run-1",
        "created_at": "2026-01-01T00:00:00+00:00",
        "source": {"kind": "UNDER_SPEC"},
        "question": {"text": "Which API version should we use?"},
        "context": {
            "blocking": {
                "severity": "BLOCKING",
                "blocked_slices": ["slice-a"],
            }
        },
    }


def test_from_dict_accepts_valid_minimal_payload() -> None:
    signal = UserQuestionSignal.from_dict(_valid_signal_dict())

    assert signal.uq_id == "uq-valid-1"
    assert signal.run_id == "run-1"
    assert signal.source.kind == "UNDER_SPEC"
    assert signal.question.text == "Which API version should we use?"
    assert signal.context.blocking.severity == "BLOCKING"
    assert signal.context.blocking.blocked_slices == ["slice-a"]


@pytest.mark.parametrize("source_kind", CANONICAL_SOURCE_KINDS)
def test_from_dict_accepts_all_canonical_source_kinds(source_kind: str) -> None:
    payload = _valid_signal_dict()
    payload["source"] = {"kind": source_kind}

    signal = UserQuestionSignal.from_dict(payload)

    assert signal.source.kind == source_kind


def test_from_dict_rejects_missing_required_top_level_field() -> None:
    payload = _valid_signal_dict()
    payload.pop("run_id")

    with pytest.raises(ValueError, match="missing required fields: run_id"):
        UserQuestionSignal.from_dict(payload)


def test_from_dict_rejects_unexpected_top_level_field() -> None:
    payload = _valid_signal_dict()
    payload["extra"] = True

    with pytest.raises(ValueError, match="has unexpected fields: extra"):
        UserQuestionSignal.from_dict(payload)


def test_from_dict_rejects_unexpected_nested_field() -> None:
    payload = _valid_signal_dict()
    payload["source"] = {"kind": "UNDER_SPEC", "extra": "nope"}

    with pytest.raises(ValueError, match=r"source has unexpected fields: extra"):
        UserQuestionSignal.from_dict(payload)


@pytest.mark.parametrize(
    "source_kind",
    ("INTENT_AGENT", "planner", "PLANNER ", "PDD-LIFECYCLE", "UNDERSPEC"),
)
def test_from_dict_rejects_non_canonical_source_kind(source_kind: str) -> None:
    payload = _valid_signal_dict()
    payload["source"] = {"kind": source_kind}

    with pytest.raises(ValueError, match="source.kind must be one of"):
        UserQuestionSignal.from_dict(payload)


def test_init_rejects_non_canonical_source_kind() -> None:
    with pytest.raises(ValueError, match="source.kind must be one of"):
        UserQuestionSignal(source=SignalSource(kind="INTENT_AGENT"))


def test_signal_store_read_all_skips_schema_invalid_lines(tmp_path: Path) -> None:
    run_dir = tmp_path / ".pdd_runs" / "run-signals"
    store = UserQuestionSignalStore(run_dir)

    store.write(
        UserQuestionSignal(
            uq_id="uq-first",
            run_id="run-signals",
            created_at="2026-01-01T00:00:00+00:00",
            source=SignalSource(kind="UNDER_SPEC"),
            question=SignalQuestion(text="First question"),
            context=SignalContext(
                blocking=SignalBlocking(severity="BLOCKING", blocked_slices=["slice-1"])
            ),
        )
    )
    signal_path = run_dir / "coordination" / "user_questions.jsonl"
    with signal_path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "uq_version": 1,
                    "uq_id": "uq-invalid",
                    # Missing required run_id.
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "source": {"kind": "UNDER_SPEC"},
                    "question": {"text": "invalid"},
                    "context": {"blocking": {"severity": "BLOCKING", "blocked_slices": []}},
                }
            )
            + "\n"
        )
    store.write(
        UserQuestionSignal(
            uq_id="uq-second",
            run_id="run-signals",
            created_at="2026-01-01T00:00:01+00:00",
            source=SignalSource(kind="UNDER_SPEC"),
            question=SignalQuestion(text="Second question"),
            context=SignalContext(
                blocking=SignalBlocking(severity="BLOCKING", blocked_slices=["slice-2"])
            ),
        )
    )

    parsed = store.read_all()

    assert [signal.uq_id for signal in parsed] == ["uq-first", "uq-second"]
