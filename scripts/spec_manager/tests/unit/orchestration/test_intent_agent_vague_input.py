"""Tests for vague-input fallback behavior in Intent Agent."""

from __future__ import annotations

from spec_manager.orchestration.intent_agent.agent import IntentAgentOrchestrator
from spec_manager.orchestration.intent_agent.quality_gate import (
    QualityCheckRecord,
    QualityChecks,
)


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


def test_handle_vague_input_quality_fail_uses_question_fallback(
    tmp_path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    orchestrator = IntentAgentOrchestrator(tmp_path)

    def _fail_gate(*args, **kwargs):  # type: ignore[no-untyped-def]
        return None, [_quality_fail_record("No LLM available for validation.")], False

    monkeypatch.setattr(
        "spec_manager.orchestration.intent_agent.agent.enforce_quality_gate", _fail_gate
    )

    item = orchestrator.handle_vague_input("help")

    assert item.status == "OPEN"
    assert item.taxonomy_type == "INTENT"
    assert item.user_prompt.text.endswith("?")
    assert item.user_prompt.answer_spec.kind == "choice"
    assert item.user_prompt.answer_spec.choices == [
        {"id": "primary_outcome", "label": "Primary outcome"},
        {"id": "target_users", "label": "Target users"},
        {"id": "must_have_constraints", "label": "Must-have constraints"},
    ]
    assert item.quality_gate.status == "PASS"
    assert item.user_prompt.scenario == 'You said: "help".'
    assert orchestrator._queue is not None
    assert orchestrator._queue.get_item(item.question_id) is not None
    assert orchestrator._state is not None
    assert (
        item.question_id not in orchestrator._state.question_queue_state["unaskable_question_ids"]
    )


def test_handle_user_message_vague_input_fail_still_returns_ask_action(
    tmp_path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    orchestrator = IntentAgentOrchestrator(tmp_path)

    def _fail_gate(*args, **kwargs):  # type: ignore[no-untyped-def]
        return None, [_quality_fail_record("No LLM available for validation.")], False

    monkeypatch.setattr(
        "spec_manager.orchestration.intent_agent.agent.enforce_quality_gate", _fail_gate
    )

    action = orchestrator.handle_user_message("help")

    assert action["action"] == "ask"
    assert action["immediate_ask"] is True
    assert action["question"]["status"] == "OPEN"
    assert action["question"]["user_prompt"]["text"].endswith("?")
    assert action["question"]["user_prompt"]["answer_spec"]["kind"] == "choice"
    assert action["question"]["user_prompt"]["answer_spec"]["choices"] == [
        {"id": "primary_outcome", "label": "Primary outcome"},
        {"id": "target_users", "label": "Target users"},
        {"id": "must_have_constraints", "label": "Must-have constraints"},
    ]
