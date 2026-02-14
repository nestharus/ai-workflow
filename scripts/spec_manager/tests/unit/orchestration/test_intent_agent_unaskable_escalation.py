"""Tests for UNASKABLE quality-fail escalation to planner reformulation updates."""

from __future__ import annotations

from datetime import UTC, datetime, timezone
from pathlib import Path

from spec_manager.orchestration.intent_agent.agent import IntentAgentOrchestrator
from spec_manager.orchestration.intent_agent.answer_translation import (
    AnswerTranslation,
    ExtractedContent,
    FollowupQuestionDraft,
    RecursionBudget,
    UserAnswer,
)
from spec_manager.orchestration.intent_agent.quality_gate import (
    QualityCheckRecord,
    QualityChecks,
)
from spec_manager.orchestration.intent_agent.queue import (
    QuestionItem,
    QuestionOrigin,
    QuestionQueue,
    UserPrompt,
)
from spec_manager.orchestration.intent_agent.signals import (
    PlannerUpdateStore,
    SignalBlocking,
    SignalContext,
    SignalQuestion,
    SignalSource,
    UserQuestionSignal,
)
from spec_manager.orchestration.intent_agent.state import IntentSessionState


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _quality_fail_record(reason: str) -> QualityCheckRecord:
    return QualityCheckRecord(
        checks=QualityChecks(
            domain_language_only=False,
            bounded_answerability=False,
            specific_behavior=False,
            scenario_grounded=False,
            single_question=False,
        ),
        result="FAIL",
        reason=reason,
    )


def _build_orchestrator(tmp_path: Path) -> IntentAgentOrchestrator:
    orchestrator = IntentAgentOrchestrator(tmp_path)
    orchestrator._state = IntentSessionState(run_id="run-unaskable", session_id="session-unaskable")
    orchestrator._queue = QuestionQueue()
    orchestrator._planner_store = PlannerUpdateStore(tmp_path)
    return orchestrator


def _parent_question(question_id: str, canonical_key: str) -> QuestionItem:
    item = QuestionItem(
        question_id=question_id,
        taxonomy_type="SCOPE",
        canonical_key=canonical_key,
        user_prompt=UserPrompt(
            text="Which approval workflow should we adopt?",
            scenario="Release promotion currently has no threshold decision.",
        ),
        origins=[
            QuestionOrigin(
                source_kind="PLANNER",
                trace_id=f"trace-{question_id}",
                created_at=_now_iso(),
            ),
        ],
    )
    item.quality_gate.status = "PASS"
    return item


class _FollowupDraftingStrategy:
    def translate(self, **kwargs):  # type: ignore[no-untyped-def]
        return AnswerTranslation(
            question_id=str(kwargs["question_id"]),
            user_answer=UserAnswer(raw_text=str(kwargs["raw_answer"])),
            extracted=ExtractedContent(
                followup_question_drafts=[
                    FollowupQuestionDraft(
                        draft_id="fq-quality-fail",
                        taxonomy_type="VALIDATION",
                        canonical_key_hint="intent.followup.approval.threshold",
                        text="List every possible exception and edge case in full detail.",
                        scenario="The current answer leaves validation conditions unresolved.",
                        answer_spec={"kind": "bounded_text"},
                    )
                ]
            ),
            recursion_budget=RecursionBudget(max_followups=2, used_followups=0),
        )


def test_ingest_signal_unaskable_emits_reformulation_planner_update(
    tmp_path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    orchestrator = _build_orchestrator(tmp_path)
    assert orchestrator._planner_store is not None

    def _fail_gate(*args, **kwargs):  # type: ignore[no-untyped-def]
        return None, [_quality_fail_record("question is unbounded")], False

    monkeypatch.setattr(
        "spec_manager.orchestration.intent_agent.agent.enforce_quality_gate", _fail_gate
    )

    item = orchestrator.ingest_signal(
        UserQuestionSignal(
            uq_id="uq-unaskable-1",
            run_id="run-unaskable",
            created_at=_now_iso(),
            source=SignalSource(kind="UNDER_SPEC"),
            question=SignalQuestion(
                text="Describe every architecture detail for the full implementation.",
                taxonomy_hint="ARCHITECTURE",
                canonical_key_hint="intent.approval.threshold",
            ),
            context=SignalContext(
                blocking=SignalBlocking(severity="BLOCKING", blocked_slices=["slice-1"])
            ),
        )
    )

    assert item is not None
    assert item.status == "UNASKABLE"

    events = orchestrator._planner_store.read_since("")
    assert len(events) == 1
    event = events[0]
    assert event["type"] == "problem_redefinition"
    assert event["stage"] == "unaskable_question"
    assert event["action"] == "REWORD"
    assert event["question_id"] == item.question_id
    assert event["canonical_key"] == "intent.approval.threshold"
    assert event["run_id"] == "run-unaskable"
    assert event["session_id"] == "session-unaskable"
    assert event["details"]["unaskable_source"] == "ingest_signal"
    assert event["details"]["signal_id"] == "uq-unaskable-1"
    assert event["details"]["attempts"] == 1


def test_redefinition_unaskable_emits_reformulation_planner_update(
    tmp_path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    orchestrator = _build_orchestrator(tmp_path)
    assert orchestrator._planner_store is not None

    def _fail_gate(*args, **kwargs):  # type: ignore[no-untyped-def]
        return None, [_quality_fail_record("scenario missing")], False

    monkeypatch.setattr(
        "spec_manager.orchestration.intent_agent.agent.enforce_quality_gate", _fail_gate
    )

    result = orchestrator.handle_redefinition(
        {
            "type": "problem_redefinition",
            "event_id": "evt-unaskable-redef",
            "canonical_key": "intent.redefinition",
            "question_text": "How should we proceed with the updated scope?",
        }
    )

    assert result.status == "UNASKABLE"

    events = orchestrator._planner_store.read_since("")
    assert len(events) == 1
    event = events[0]
    assert event["type"] == "problem_redefinition"
    assert event["stage"] == "unaskable_question"
    assert event["action"] == "REWORD"
    assert event["question_id"] == result.question_id
    assert event["canonical_key"] == "intent.redefinition"
    assert event["details"]["unaskable_source"] == "redefinition"
    assert event["details"]["redefinition_trigger"] == "evt-unaskable-redef"
    assert event["details"]["attempts"] == 1


def test_followup_quality_fail_escalates_via_canonical_unaskable_reformulation(
    tmp_path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    def _on_translation_saved(translation):  # type: ignore[no-untyped-def]
        return {"status": "OK", "trace_id": "trace-followup-quality-fail"}

    orchestrator = IntentAgentOrchestrator(
        tmp_path,
        on_translation_saved=_on_translation_saved,
        answer_translate_strategy=_FollowupDraftingStrategy(),
    )
    orchestrator._state = IntentSessionState(run_id="run-unaskable", session_id="session-unaskable")
    orchestrator._queue = QuestionQueue()
    orchestrator._planner_store = PlannerUpdateStore(tmp_path)
    assert orchestrator._queue is not None
    assert orchestrator._planner_store is not None
    assert orchestrator._state is not None

    orchestrator._queue.enqueue(_parent_question("Q-parent", "intent.approval.threshold"))

    def _fail_gate(*args, **kwargs):  # type: ignore[no-untyped-def]
        return None, [_quality_fail_record("follow-up question is not bounded")], False

    monkeypatch.setattr(
        "spec_manager.orchestration.intent_agent.agent.enforce_quality_gate", _fail_gate
    )

    orchestrator.handle_answer(question_id="Q-parent", raw_text="Use two approvers.")

    events = orchestrator._planner_store.read_since("")
    assert len(events) == 1

    event = events[0]
    assert event["type"] == "problem_redefinition"
    assert event["stage"] == "unaskable_question"
    assert event["action"] == "REWORD"
    assert event["stage"] != "followup_quality_gate"
    assert event["details"]["unaskable_source"] == "followup_question"
    assert event["details"]["parent_question_id"] == "Q-parent"
    assert event["details"]["failure_reason"] == "follow-up question is not bounded"
    assert event["details"]["attempts"] == 1
    assert event["details"]["escalation_path"] == "planner_reformulation"
    assert event["canonical_key"] == "intent.followup.approval.threshold"
    assert event["question_type"] == "VALIDATION"
    assert event["question_id"]
    assert (
        event["question_id"] in orchestrator._state.question_queue_state["unaskable_question_ids"]
    )
