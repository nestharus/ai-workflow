"""Tests for intent-agent question presentation flow."""

from __future__ import annotations

from datetime import UTC, datetime, timezone

from spec_manager.orchestration.intent_agent.agent import IntentAgentOrchestrator
from spec_manager.orchestration.intent_agent.queue import (
    QuestionBlockers,
    QuestionItem,
    QuestionOrigin,
    QuestionQueue,
    UserPrompt,
)
from spec_manager.orchestration.intent_agent.signals import PlannerUpdateStore
from spec_manager.orchestration.intent_agent.state import IntentSessionState


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _open_question(
    question_id: str,
    canonical_key: str,
    *,
    text: str = "",
    scenario: str = "",
    severity: str = "INFO",
    scope_kind: str = "FEATURE_SPECIFIC",
    taxonomy_type: str = "CONSTRAINT",
    answer_kind: str = "choice",
    blocked_slices: list[str] | None = None,
    decision_requirement_ids: list[str] | None = None,
) -> QuestionItem:
    item = QuestionItem(
        question_id=question_id,
        taxonomy_type=taxonomy_type,
        scope_kind=scope_kind,
        canonical_key=canonical_key,
        user_prompt=UserPrompt(
            text=text or f"Question {question_id}?",
            scenario=scenario,
        ),
        system_binding={
            "decision_requirement_ids": list(decision_requirement_ids or []),
        },
        origins=[
            QuestionOrigin(
                source_kind="PLANNER",
                trace_id=f"trace-{question_id}",
                created_at=_now_iso(),
            ),
        ],
        blockers=QuestionBlockers(
            severity=severity,
            blocked_slices=list(blocked_slices or ["slice-1"]),
        ),
    )
    item.user_prompt.answer_spec.kind = answer_kind
    item.quality_gate.status = "PASS"
    return item


def test_next_action_returns_batch_payload_and_tracks_active_batch_id(tmp_path) -> None:
    orchestrator = IntentAgentOrchestrator(tmp_path)
    orchestrator._state = IntentSessionState(session_id="s_batch")
    orchestrator._queue = QuestionQueue()
    orchestrator._queue.enqueue(
        _open_question(
            "Q-100",
            "billing.approval.threshold",
            text="What approval threshold should enterprise billing use?",
            scenario="An enterprise invoice enters the approval workflow.",
            blocked_slices=["slice-1", "slice-2"],
            decision_requirement_ids=["dr.billing.approval"],
        ),
    )
    orchestrator._queue.enqueue(
        _open_question(
            "Q-200",
            "billing.approval.override",
            text="When can billing approval override that threshold?",
            scenario="Finance policy defines exception handling for approvals.",
            decision_requirement_ids=["dr.billing.approval"],
        ),
    )

    action = orchestrator.next_action()

    assert action is not None
    assert action["action"] == "ask"
    assert action["question_id"] == "Q-100"
    assert action["batch"]["question_ids"] == ["Q-100", "Q-200"]
    assert action["batch"]["questions"][0]["question_id"] == "Q-100"
    assert orchestrator._state.question_queue_state["active_batch_id"] == "Q-100,Q-200"


def test_next_action_single_question_clears_stale_active_batch_id(tmp_path) -> None:
    orchestrator = IntentAgentOrchestrator(tmp_path)
    orchestrator._state = IntentSessionState(session_id="s_single")
    orchestrator._state.question_queue_state["active_batch_id"] = "Q-100,Q-200"
    orchestrator._queue = QuestionQueue()
    orchestrator._queue.enqueue(
        _open_question(
            "Q-300",
            "billing.approval.threshold",
            text="What approval threshold should enterprise billing use?",
        ),
    )

    action = orchestrator.next_action()

    assert action is not None
    assert action["action"] == "ask"
    assert action["question_id"] == "Q-300"
    assert "batch" not in action
    assert orchestrator._state.question_queue_state["active_batch_id"] == ""


def test_next_action_immediate_ask_clears_active_batch_id(tmp_path) -> None:
    orchestrator = IntentAgentOrchestrator(tmp_path)
    orchestrator._state = IntentSessionState(session_id="s_immediate")
    orchestrator._queue = QuestionQueue()

    info = _open_question("Q-100", "scope.a", severity="INFO")
    blocking = _open_question("Q-200", "scope.b", severity="BLOCKING")
    orchestrator._queue.enqueue(info)
    orchestrator._queue.enqueue(blocking)
    orchestrator._state.question_queue_state["last_presented_question_id"] = "Q-100"
    orchestrator._state.question_queue_state["active_batch_id"] = "Q-100,Q-999"

    action = orchestrator.next_action()

    assert action is not None
    assert action["action"] == "ask"
    assert action["question_id"] == "Q-200"
    assert action["immediate_ask"] is True
    assert "batch" not in action
    assert orchestrator._state.question_queue_state["active_batch_id"] == ""


def test_next_action_immediate_ask_when_queue_context_is_empty(tmp_path) -> None:
    orchestrator = IntentAgentOrchestrator(tmp_path)
    orchestrator._state = IntentSessionState(session_id="s_empty_context")
    orchestrator._queue = QuestionQueue()

    blocking = _open_question("Q-200", "scope.blocking", severity="BLOCKING")
    orchestrator._queue.enqueue(blocking)
    orchestrator._state.question_queue_state["active_batch_id"] = "Q-legacy,Q-older"

    action = orchestrator.next_action()

    assert action is not None
    assert action["action"] == "ask"
    assert action["question_id"] == "Q-200"
    assert action["immediate_ask"] is True
    assert orchestrator._state.question_queue_state["active_batch_id"] == ""


def test_next_action_does_not_preempt_when_last_presented_is_unknown(tmp_path) -> None:
    orchestrator = IntentAgentOrchestrator(tmp_path)
    orchestrator._state = IntentSessionState(session_id="s_unknown_last_presented")
    orchestrator._queue = QuestionQueue()

    info = _open_question("Q-100", "scope.info", severity="INFO")
    blocking = _open_question("Q-200", "scope.blocking", severity="BLOCKING")
    orchestrator._queue.enqueue(info)
    orchestrator._queue.enqueue(blocking)
    orchestrator._state.question_queue_state["last_presented_question_id"] = "Q-404"

    action = orchestrator.next_action()

    assert action is not None
    assert action["action"] == "ask"
    assert action["question_id"] == "Q-200"
    assert "immediate_ask" not in action


def test_resume_uses_batch_selection_and_returns_batch_head(tmp_path, monkeypatch) -> None:
    state = IntentSessionState(session_id="s_resume")
    state.save(tmp_path)

    queue = QuestionQueue()
    queue.enqueue(
        _open_question(
            "Q-100",
            "risk.availability.rto",
            text="What recovery-time objective should the platform guarantee?",
            blocked_slices=["slice-1", "slice-2"],
        ),
    )
    queue.enqueue(
        _open_question(
            "Q-200",
            "risk.availability.rpo",
            text="What recovery-point objective should the platform guarantee?",
        ),
    )
    queue.save(tmp_path)

    call_counter = {"count": 0}
    original_next_batch = QuestionQueue.next_batch

    def _counting_next_batch(self: QuestionQueue, run_agent=None):  # type: ignore[no-untyped-def]
        call_counter["count"] += 1
        return original_next_batch(self, run_agent=run_agent)

    monkeypatch.setattr(QuestionQueue, "next_batch", _counting_next_batch)

    orchestrator = IntentAgentOrchestrator(tmp_path)
    next_question = orchestrator.resume()

    assert call_counter["count"] == 1
    assert next_question is not None
    assert next_question.question_id == "Q-100"
    assert orchestrator._state is not None
    assert orchestrator._state.question_queue_state["active_batch_id"] == "Q-100,Q-200"


def test_resume_single_question_clears_stale_active_batch_id(tmp_path) -> None:
    state = IntentSessionState(session_id="s_resume_single")
    state.question_queue_state["active_batch_id"] = "Q-100,Q-200"
    state.save(tmp_path)

    queue = QuestionQueue()
    queue.enqueue(
        _open_question(
            "Q-300",
            "risk.availability.rto",
            text="What recovery-time objective should the platform guarantee?",
            blocked_slices=["slice-1"],
        ),
    )
    queue.save(tmp_path)

    orchestrator = IntentAgentOrchestrator(tmp_path)
    next_question = orchestrator.resume()

    assert next_question is not None
    assert next_question.question_id == "Q-300"
    assert orchestrator._state is not None
    assert orchestrator._state.question_queue_state["active_batch_id"] == ""


def test_resume_includes_progress_summary_from_planner_updates(tmp_path) -> None:
    state = IntentSessionState(session_id="s_resume_progress")
    state.watermarks.planner_update_watermark = "2026-02-13T11:59:00+00:00"
    state.save(tmp_path)

    queue = QuestionQueue()
    queue.enqueue(
        _open_question(
            "Q-100",
            "risk.availability.rpo",
            text="What recovery-point objective should the platform guarantee?",
        ),
    )
    queue.save(tmp_path)

    planner_store = PlannerUpdateStore(tmp_path)
    planner_store.write(
        {
            "type": "constraint_saved",
            "event_id": "evt-100",
            "created_at": "2026-02-13T12:00:00+00:00",
            "slice_id": "slice-l1",
            "status": "waiting",
            "canonical_key": "risk.availability.rto",
            "constraint_ids": ["CON-100"],
        }
    )
    planner_store.write(
        {
            "type": "decision_recorded",
            "event_id": "evt-200",
            "created_at": "2026-02-13T12:01:00+00:00",
            "slice_id": "slice-l2",
            "slice_status": "complete",
            "decision_ids": ["DEC-200"],
        }
    )

    orchestrator = IntentAgentOrchestrator(tmp_path)
    next_question = orchestrator.resume()

    assert next_question is not None
    resume_summary = next_question.system_binding.get("resume_progress_summary")
    assert isinstance(resume_summary, dict)
    assert resume_summary["planner_watermark"] == "2026-02-13T11:59:00+00:00"
    assert resume_summary["planner_updates_seen"] == 2
    assert resume_summary["planner_update_types"] == {
        "constraint_saved": 1,
        "decision_recorded": 1,
    }
    assert resume_summary["slice_ids"] == ["slice-l1", "slice-l2"]
    assert resume_summary["slice_status_counts"] == {
        "COMPLETE": 1,
        "WAITING": 1,
    }
    assert resume_summary["latest_planner_update_at"] == "2026-02-13T12:01:00+00:00"

    assert orchestrator._state is not None
    persisted_summary = orchestrator._state.question_queue_state["resume_progress_summary"]
    assert persisted_summary["planner_updates_seen"] == 2
    assert persisted_summary["slice_status_counts"] == {
        "COMPLETE": 1,
        "WAITING": 1,
    }


def test_resume_includes_zeroed_progress_summary_without_new_updates(tmp_path) -> None:
    state = IntentSessionState(session_id="s_resume_no_updates")
    state.watermarks.planner_update_watermark = "2026-02-13T12:30:00+00:00"
    state.save(tmp_path)

    queue = QuestionQueue()
    queue.enqueue(
        _open_question(
            "Q-100",
            "risk.availability.rpo",
            text="What recovery-point objective should the platform guarantee?",
        ),
    )
    queue.save(tmp_path)

    planner_store = PlannerUpdateStore(tmp_path)
    planner_store.write(
        {
            "type": "constraint_saved",
            "event_id": "evt-older",
            "created_at": "2026-02-13T12:00:00+00:00",
            "slice_id": "slice-l1",
            "slice_status": "complete",
            "constraint_ids": ["CON-OLDER"],
        }
    )

    orchestrator = IntentAgentOrchestrator(tmp_path)
    next_question = orchestrator.resume()

    assert next_question is not None
    resume_summary = next_question.system_binding.get("resume_progress_summary")
    assert isinstance(resume_summary, dict)
    assert resume_summary["planner_watermark"] == "2026-02-13T12:30:00+00:00"
    assert resume_summary["planner_updates_seen"] == 0
    assert resume_summary["planner_update_types"] == {}
    assert resume_summary["slice_ids"] == []
    assert resume_summary["slice_status_counts"] == {}
    assert resume_summary["latest_planner_update_at"] == "2026-02-13T12:30:00+00:00"
    assert resume_summary["reassess_action_counts"] == {}
    assert resume_summary["reassess_resolved_count"] == 0


def test_next_action_falls_back_to_single_question_when_batch_is_ambiguous(tmp_path) -> None:
    orchestrator = IntentAgentOrchestrator(tmp_path)
    orchestrator._state = IntentSessionState(session_id="s_ambiguous_batch")
    orchestrator._queue = QuestionQueue()
    orchestrator._queue.enqueue(
        _open_question(
            "Q-100",
            "billing.approval.threshold",
            text="What approval threshold should enterprise billing use?",
            scenario="An enterprise invoice enters the approval workflow.",
            blocked_slices=["slice-1", "slice-2"],
            decision_requirement_ids=["dr.billing.approval"],
        ),
    )
    orchestrator._queue.enqueue(
        _open_question(
            "Q-200",
            "billing.currency.support",
            text="Which payout currencies must disbursements support?",
            scenario="Treasury integration chooses settlement rails by currency.",
            decision_requirement_ids=["dr.billing.currency"],
        ),
    )

    action = orchestrator.next_action()

    assert action is not None
    assert action["action"] == "ask"
    assert action["question_id"] == "Q-100"
    assert "batch" not in action
    assert orchestrator._state.question_queue_state["active_batch_id"] == ""
