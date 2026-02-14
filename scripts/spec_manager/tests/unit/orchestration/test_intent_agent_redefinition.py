"""Tests for redefinition enqueue semantics in the intent agent."""

from __future__ import annotations

from datetime import UTC, datetime, timezone

import pytest
from spec_manager.orchestration.intent_agent.agent import IntentAgentOrchestrator
from spec_manager.orchestration.intent_agent.quality_gate import (
    QualityCheckCandidate,
    QualityCheckRecord,
    QualityChecks,
)
from spec_manager.orchestration.intent_agent.queue import (
    AnswerSpec,
    QualityGateStatus,
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


def _quality_record(result: str, reason: str) -> QualityCheckRecord:
    passed = result == "PASS"
    return QualityCheckRecord(
        checks=QualityChecks(
            domain_language_only=passed,
            bounded_answerability=passed,
            specific_behavior=passed,
            scenario_grounded=passed,
            single_question=passed,
        ),
        result=result,
        reason=reason,
    )


def _build_orchestrator(tmp_path) -> IntentAgentOrchestrator:  # type: ignore[no-untyped-def]
    orchestrator = IntentAgentOrchestrator(tmp_path)
    orchestrator._state = IntentSessionState(session_id="s_redefinition")
    orchestrator._state.original_intent.user_statement = "Build the workflow"
    orchestrator._state.problem_frame.current_restatement = (
        "Build a workflow with strict approval rules"
    )
    orchestrator._queue = QuestionQueue()
    return orchestrator


def test_redefinition_not_enqueued_when_quality_gate_fails(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    orchestrator = _build_orchestrator(tmp_path)

    def _fail_gate(*args, **kwargs):  # type: ignore[no-untyped-def]
        return None, [_quality_record("FAIL", "missing scenario")], False

    monkeypatch.setattr(
        "spec_manager.orchestration.intent_agent.agent.enforce_quality_gate", _fail_gate
    )

    result = orchestrator.handle_redefinition(
        {
            "type": "problem_redefinition",
            "event_id": "evt-fail",
            "canonical_key": "intent.redefinition",
            "question_text": "How should we proceed?",
        }
    )

    assert result.status == "UNASKABLE"
    assert result.quality_gate.status == "FAIL"
    assert orchestrator._queue.get_item(result.question_id) is None
    assert result.question_id in orchestrator._state.question_queue_state["unaskable_question_ids"]


def test_redefinition_enqueues_only_after_quality_gate_pass(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    orchestrator = _build_orchestrator(tmp_path)
    enqueue_statuses: list[str] = []

    def _pass_gate(*args, **kwargs):  # type: ignore[no-untyped-def]
        return (
            QualityCheckCandidate(
                text="Confirm the updated scope for approval flow.",
                scenario="A planner update changed approval assumptions.",
                answer_spec_kind="choice",
                taxonomy_type="SCOPE",
            ),
            [_quality_record("PASS", "ok")],
            True,
        )

    real_enqueue = QuestionQueue.enqueue

    def _capture_enqueue(self: QuestionQueue, item: QuestionItem) -> None:
        enqueue_statuses.append(item.quality_gate.status)
        real_enqueue(self, item)

    monkeypatch.setattr(
        "spec_manager.orchestration.intent_agent.agent.enforce_quality_gate", _pass_gate
    )
    monkeypatch.setattr(QuestionQueue, "enqueue", _capture_enqueue)

    result = orchestrator.handle_redefinition(
        {
            "type": "problem_redefinition",
            "event_id": "evt-pass",
            "canonical_key": "intent.redefinition",
            "question_text": "What should change?",
        }
    )

    queued_item = orchestrator._queue.get_item(result.question_id)
    assert enqueue_statuses == ["PASS"]
    assert queued_item is not None
    assert queued_item.quality_gate.status == "PASS"
    assert queued_item.user_prompt.text == "Confirm the updated scope for approval flow."


def test_existing_redefinition_item_not_forced_to_pass_on_failed_gate(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    orchestrator = _build_orchestrator(tmp_path)
    existing = QuestionItem(
        question_id="Q-EXISTING",
        canonical_key="intent.redefinition",
        user_prompt=UserPrompt(
            text="Existing validated question",
            scenario="Existing scenario",
            answer_spec=AnswerSpec(
                kind="choice",
                choices=[{"id": "keep", "label": "Keep existing"}],
            ),
        ),
        origins=[
            QuestionOrigin(
                source_kind="PLANNER",
                trace_id="trace-existing",
                created_at=_now_iso(),
            )
        ],
        blockers=QuestionBlockers(severity="BLOCKING"),
        quality_gate=QualityGateStatus(
            status="FAIL",
            attempts=1,
            last_checked_at=_now_iso(),
        ),
    )
    orchestrator._queue._items[existing.question_id] = existing

    def _fail_gate(*args, **kwargs):  # type: ignore[no-untyped-def]
        return None, [_quality_record("FAIL", "still invalid")], False

    monkeypatch.setattr(
        "spec_manager.orchestration.intent_agent.agent.enforce_quality_gate", _fail_gate
    )

    result = orchestrator.handle_redefinition(
        {
            "type": "problem_redefinition",
            "event_id": "evt-existing-fail",
            "question_id": existing.question_id,
            "canonical_key": existing.canonical_key,
            "question_text": "Rewrite this question in an invalid way",
        }
    )

    assert result.question_id == existing.question_id
    assert existing.quality_gate.status == "FAIL"
    assert existing.user_prompt.text == "Existing validated question"


@pytest.mark.parametrize(
    ("text", "family", "question_type"),
    [
        (
            "I changed my mind, let's redefine this around compliance audits.",
            "intent_reset",
            "VALIDATION",
        ),
        (
            "For the first release, keep real-time dashboards out of scope and only support exports.",
            "scope_shift",
            "SCOPE",
        ),
        (
            "Prioritize throughput over immediate visibility for the initial rollout.",
            "priority_tradeoff",
            "TRADEOFF",
        ),
        (
            "We cannot do both strict real-time updates and maximum throughput at the same time.",
            "requirement_conflict",
            "TRADEOFF",
        ),
    ],
)
def test_user_redefinition_trigger_matrix_detects_families(
    tmp_path,
    text: str,
    family: str,
    question_type: str,
) -> None:  # type: ignore[no-untyped-def]
    orchestrator = _build_orchestrator(tmp_path)

    trigger = orchestrator._parse_user_redefinition_trigger(text)

    assert trigger is not None
    assert trigger["canonical_key"] == f"intent.redefinition.user.{family}"
    assert trigger["stage"] == f"user_trigger.{family}"
    assert trigger["question_type"] == question_type
    assert trigger["source"] == "INTENT_AGENT"
    assert trigger["type"] == "problem_redefinition"
    assert trigger["what_changed"]
    assert trigger["reason"].endswith(f"({family}).")


def test_user_redefinition_trigger_matrix_ignores_non_redefinition_text(tmp_path) -> None:  # type: ignore[no-untyped-def]
    orchestrator = _build_orchestrator(tmp_path)

    trigger = orchestrator._parse_user_redefinition_trigger(
        "Can you summarize what is currently in scope?",
    )

    assert trigger is None


def test_handle_user_message_user_redefinition_routes_to_redefinition_flow(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    orchestrator = _build_orchestrator(tmp_path)
    captured_trigger: dict[str, object] = {}
    returned_item = QuestionItem(
        question_id="Q-USER-REDEF",
        canonical_key="intent.redefinition.user.scope_shift",
        taxonomy_type="SCOPE",
        user_prompt=UserPrompt(
            text="Confirm updated scope boundaries.",
            scenario="Original intent and current restatement diverged.",
            answer_spec=AnswerSpec(
                kind="choice",
                choices=[
                    {"id": "adopt_new", "label": "Adopt the new understanding"},
                    {"id": "keep_original", "label": "Keep the original intent"},
                    {"id": "partial", "label": "Adopt parts of the new understanding"},
                ],
            ),
        ),
        origins=[
            QuestionOrigin(
                source_kind="INTENT_AGENT",
                trace_id="trace-user-redef",
                created_at=_now_iso(),
            )
        ],
        blockers=QuestionBlockers(severity="BLOCKING"),
    )

    def _capture_handle_redefinition(trigger):  # type: ignore[no-untyped-def]
        captured_trigger.update(trigger)
        return returned_item

    monkeypatch.setattr(orchestrator, "handle_redefinition", _capture_handle_redefinition)

    action = orchestrator.handle_user_message(
        "For the first release, keep advanced analytics out of scope and only ship exports.",
    )

    assert action["action"] == "ask"
    assert action["immediate_ask"] is True
    assert action["question_id"] == "Q-USER-REDEF"
    assert captured_trigger["canonical_key"] == "intent.redefinition.user.scope_shift"
    assert captured_trigger["stage"] == "user_trigger.scope_shift"
    assert captured_trigger["question_type"] == "SCOPE"


def test_alignment_violation_auto_classifies_scope_redefinition(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    orchestrator = _build_orchestrator(tmp_path)

    def _pass_gate(candidate, *args, **kwargs):  # type: ignore[no-untyped-def]
        return candidate, [_quality_record("PASS", "ok")], True

    monkeypatch.setattr(
        "spec_manager.orchestration.intent_agent.agent.enforce_quality_gate", _pass_gate
    )

    result = orchestrator.handle_redefinition(
        {
            "type": "alignment_violation",
            "event_id": "evt-invariant-scope",
            "source": "PLANNER",
            "what_changed": [
                "Planner expanded in-scope deliverables to include advanced analytics.",
                "The prior scope excluded advanced analytics for phase 1.",
            ],
            "alignment_invariants": [
                {"text": "Phase 1 keeps advanced analytics out of scope.", "status": "CONFIRMED"},
            ],
        }
    )

    assert result.taxonomy_type == "SCOPE"
    assert result.canonical_key == "intent.redefinition.invariant_drift.scope"
    assert result.system_binding["redefinition_taxonomy"] == "SCOPE"
    classification = result.system_binding.get("redefinition_classification")
    assert isinstance(classification, dict)
    assert classification["method"] == "invariant_drift_auto"
    assert classification["question_type"] == "SCOPE"


def test_alignment_violation_emits_classified_problem_redefinition_update(
    tmp_path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    orchestrator = _build_orchestrator(tmp_path)
    orchestrator._planner_store = PlannerUpdateStore(tmp_path)
    assert orchestrator._planner_store is not None

    orchestrator._planner_store.write(
        {
            "type": "alignment_violation",
            "event_id": "evt-alignment-1",
            "created_at": "2026-02-13T12:30:00+00:00",
            "source": "PLANNER",
            "reason": "Cannot satisfy immediate visibility and peak throughput together.",
            "what_changed": [
                "Current plan cannot satisfy both immediate visibility and highest throughput.",
            ],
            "alignment_invariants": [
                {"text": "Immediate visibility for every transaction", "status": "CONFIRMED"},
                {"text": "Sustain peak throughput under load", "status": "CONFIRMED"},
            ],
        }
    )

    captured_trigger: dict[str, object] = {}
    redefined_item = QuestionItem(
        question_id="Q-INVARIANT-NEW",
        canonical_key="intent.redefinition.invariant_drift.tradeoff",
        taxonomy_type="TRADEOFF",
        user_prompt=UserPrompt(
            text="Which priority should drive the initial version?",
            scenario="An invariant conflict introduced a tradeoff.",
        ),
    )

    def _capture_handle_redefinition(trigger):  # type: ignore[no-untyped-def]
        captured_trigger.update(trigger)
        return redefined_item

    monkeypatch.setattr(orchestrator, "handle_redefinition", _capture_handle_redefinition)

    result = orchestrator.handle_planner_updates()

    assert captured_trigger["type"] == "problem_redefinition"
    assert captured_trigger["question_type"] == "TRADEOFF"
    assert captured_trigger["redefinition_taxonomy"] == "TRADEOFF"
    classification = captured_trigger.get("redefinition_classification")
    assert isinstance(classification, dict)
    assert classification["question_type"] == "TRADEOFF"
    assert classification["method"] == "invariant_drift_auto"

    events = orchestrator._planner_store.read_since("")
    assert len(events) == 2
    emitted = events[1]
    assert emitted["type"] == "problem_redefinition"
    assert emitted["event_id"] == "evt-alignment-1.redefinition"
    assert emitted["question_type"] == "TRADEOFF"
    assert emitted["redefinition_taxonomy"] == "TRADEOFF"
    assert emitted["redefinition_classification"]["question_type"] == "TRADEOFF"
    assert emitted["details"]["redefinition_classification"]["question_type"] == "TRADEOFF"

    assert ("Q-INVARIANT-NEW", "REWORD") in {
        (action["question_id"], action["action"]) for action in result["actions"]
    }
