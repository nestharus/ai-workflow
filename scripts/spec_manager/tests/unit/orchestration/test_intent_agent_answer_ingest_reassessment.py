"""Tests for immediate reassessment after successful answer ingest."""

from __future__ import annotations

from spec_manager.orchestration.intent_agent.agent import IntentAgentOrchestrator
from spec_manager.orchestration.intent_agent.queue import (
    QualityGateStatus,
    QuestionBlockers,
    QuestionItem,
    QuestionOrigin,
    QuestionQueue,
    UserPrompt,
)
from spec_manager.orchestration.intent_agent.signals import PlannerUpdateStore
from spec_manager.orchestration.intent_agent.state import IntentSessionState


def _open_question(question_id: str, canonical_key: str) -> QuestionItem:
    return QuestionItem(
        question_id=question_id,
        canonical_key=canonical_key,
        user_prompt=UserPrompt(
            text="What approval threshold should we enforce?",
            scenario="Approval behavior is currently undefined.",
            why_it_matters="The planner cannot finalize lifecycle constraints.",
        ),
        origins=[
            QuestionOrigin(
                source_kind="PLANNER",
                trace_id="trace-question",
                created_at="2026-02-13T12:00:00+00:00",
            ),
        ],
        blockers=QuestionBlockers(severity="BLOCKING", blocked_slices=["slice-1"]),
        quality_gate=QualityGateStatus(
            status="PASS",
            attempts=1,
            last_quality_record_id="qc-pass",
            last_checked_at="2026-02-13T12:00:01+00:00",
        ),
    )


def _build_orchestrator(tmp_path, on_translation_saved):  # type: ignore[no-untyped-def]
    orchestrator = IntentAgentOrchestrator(
        tmp_path,
        on_translation_saved=on_translation_saved,
    )
    orchestrator._state = IntentSessionState(run_id="run-1", session_id="session-1")
    orchestrator._queue = QuestionQueue()
    orchestrator._planner_store = PlannerUpdateStore(tmp_path)
    return orchestrator


def test_handle_answer_success_triggers_immediate_reassessment(tmp_path) -> None:
    created_at = "2026-02-13T12:15:00+00:00"

    def _on_translation_saved(translation) -> dict[str, str]:  # type: ignore[no-untyped-def]
        assert orchestrator._planner_store is not None
        orchestrator._planner_store.write(
            {
                "type": "constraint_saved",
                "event_id": "evt-answer-success",
                "created_at": created_at,
                "source": "PLANNER",
                "canonical_key": "intent.approval.threshold",
                "constraint_ids": ["CON-123"],
            }
        )
        return {"status": "OK", "trace_id": "trace-ingest-success"}

    orchestrator = _build_orchestrator(tmp_path, _on_translation_saved)
    assert orchestrator._queue is not None
    assert orchestrator._state is not None

    orchestrator._queue.enqueue(_open_question("Q-1", "intent.approval.threshold"))
    orchestrator.handle_answer(question_id="Q-1", raw_text="Use three approvers.")

    queued = orchestrator._queue.get_item("Q-1")
    assert queued is not None
    assert queued.status == "ANSWERED"
    assert orchestrator._state.watermarks.planner_update_watermark == created_at

    reassess_dir = tmp_path / "intent" / "reassess_results"
    assert reassess_dir.exists()
    assert list(reassess_dir.glob("reassess_*.json"))


def test_handle_answer_ingest_failure_does_not_trigger_reassessment(tmp_path) -> None:
    created_at = "2026-02-13T12:16:00+00:00"

    def _on_translation_saved(translation) -> dict[str, str]:  # type: ignore[no-untyped-def]
        assert orchestrator._planner_store is not None
        orchestrator._planner_store.write(
            {
                "type": "constraint_saved",
                "event_id": "evt-answer-failure",
                "created_at": created_at,
                "source": "PLANNER",
                "canonical_key": "intent.approval.threshold",
                "constraint_ids": ["CON-999"],
            }
        )
        return {"status": "ERROR", "error": "planner rejected payload"}

    orchestrator = _build_orchestrator(tmp_path, _on_translation_saved)
    assert orchestrator._queue is not None
    assert orchestrator._state is not None

    orchestrator._queue.enqueue(_open_question("Q-2", "intent.approval.threshold"))
    orchestrator.handle_answer(question_id="Q-2", raw_text="Keep it flexible.")

    queued = orchestrator._queue.get_item("Q-2")
    assert queued is not None
    assert queued.status == "OPEN"
    assert orchestrator._state.watermarks.planner_update_watermark == ""

    reassess_dir = tmp_path / "intent" / "reassess_results"
    assert not reassess_dir.exists()
