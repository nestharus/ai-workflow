"""Tests for stale vs superseded handling in queue mechanical reassessment."""

from __future__ import annotations

from datetime import UTC, datetime, timezone

from spec_manager.orchestration.intent_agent.queue import (
    QualityGateStatus,
    QuestionBlockers,
    QuestionItem,
    QuestionOrigin,
    QuestionQueue,
    UserPrompt,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _open_question(question_id: str, canonical_key: str) -> QuestionItem:
    return QuestionItem(
        question_id=question_id,
        canonical_key=canonical_key,
        user_prompt=UserPrompt(
            text="Which policy should we apply?",
            scenario="A policy conflict must be resolved before implementation.",
            why_it_matters="This blocks planning progress.",
        ),
        origins=[
            QuestionOrigin(
                source_kind="PLANNER",
                trace_id="trace-queue-reassess",
                created_at=_now_iso(),
            )
        ],
        blockers=QuestionBlockers(severity="BLOCKING", blocked_slices=["slice-1"]),
        quality_gate=QualityGateStatus(
            status="PASS",
            attempts=1,
            last_quality_record_id="qc-1",
            last_checked_at=_now_iso(),
        ),
    )


def test_reassess_marks_irrelevant_canonical_key_stale_not_superseded() -> None:
    queue = QuestionQueue()
    queue.enqueue(_open_question("Q-100", "intent.policy.path"))

    result = queue.reassess(
        planner_updates=[
            {
                "type": "constraint_saved",
                "canonical_key": "intent.policy.path",
                "irrelevant": True,
            }
        ],
        question_key_map={},
        run_id="run-1",
        session_id="session-1",
    )

    action_pairs = {(entry["question_id"], entry["action"]) for entry in result["actions"]}
    assert ("Q-100", "STALE") in action_pairs
    assert ("Q-100", "SUPERSEDED") not in action_pairs

    item = queue.get_item("Q-100")
    assert item is not None
    assert item.status == "STALE"


def test_reassess_marks_irrelevant_question_id_stale_not_superseded() -> None:
    queue = QuestionQueue()
    queue.enqueue(_open_question("Q-200", "intent.review.path"))

    result = queue.reassess(
        planner_updates=[
            {
                "type": "decision_recorded",
                "question_id": "Q-200",
                "irrelevant": True,
            }
        ],
        question_key_map={},
        run_id="run-1",
        session_id="session-1",
    )

    action_pairs = {(entry["question_id"], entry["action"]) for entry in result["actions"]}
    assert ("Q-200", "STALE") in action_pairs
    assert ("Q-200", "SUPERSEDED") not in action_pairs

    item = queue.get_item("Q-200")
    assert item is not None
    assert item.status == "STALE"
