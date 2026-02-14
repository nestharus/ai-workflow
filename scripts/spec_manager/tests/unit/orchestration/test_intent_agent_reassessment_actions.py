"""Tests for canonical reassessment action values in intent-agent outputs."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timezone
from pathlib import Path

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

_CANONICAL_REASSESS_ACTIONS = {
    "KEEP",
    "ANSWERED",
    "STALE",
    "SUPERSEDED",
    "REWORD",
    "DISMISSED",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _build_orchestrator(tmp_path: Path) -> IntentAgentOrchestrator:
    orchestrator = IntentAgentOrchestrator(tmp_path)
    orchestrator._state = IntentSessionState(run_id="run-1", session_id="session-1")
    orchestrator._queue = QuestionQueue()
    orchestrator._planner_store = PlannerUpdateStore(tmp_path)
    return orchestrator


def _open_question(question_id: str, canonical_key: str) -> QuestionItem:
    return QuestionItem(
        question_id=question_id,
        canonical_key=canonical_key,
        user_prompt=UserPrompt(
            text="Which path should we use for approval checks?",
            scenario="A reviewer cannot approve because policy behavior is unclear.",
            why_it_matters="This blocks the workflow handoff.",
        ),
        origins=[
            QuestionOrigin(
                source_kind="PLANNER",
                trace_id="trace-1",
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


def _latest_reassess_payload(run_dir: Path) -> dict[str, object]:
    reassess_dir = run_dir / "intent" / "reassess_results"
    files = sorted(reassess_dir.glob("reassess_*.json"))
    assert files
    return json.loads(files[-1].read_text(encoding="utf-8"))


def test_handle_planner_updates_redefinition_actions_are_canonical(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    orchestrator = _build_orchestrator(tmp_path)
    assert orchestrator._planner_store is not None

    orchestrator._planner_store.write(
        {
            "type": "problem_redefinition",
            "event_id": "evt-1",
            "created_at": "2026-02-13T12:00:00+00:00",
            "source": "PLANNER",
            "action": "REPLACE",
            "question_id": "Q-OLD",
            "reason": "Scope changed after planner update.",
            "replacement": {
                "new_question_id": "Q-NEW",
                "new_canonical_key": "intent.redefinition.updated",
                "new_user_prompt_text": "Confirm updated approval flow assumptions.",
            },
        }
    )

    redefined_item = QuestionItem(
        question_id="Q-NEW",
        canonical_key="intent.redefinition.updated",
        user_prompt=UserPrompt(
            text="Confirm updated approval flow assumptions.",
            scenario="The planner changed the scope.",
        ),
    )
    monkeypatch.setattr(orchestrator, "handle_redefinition", lambda update: redefined_item)

    result = orchestrator.handle_planner_updates()

    actions = [entry["action"] for entry in result["actions"]]
    assert set(actions).issubset(_CANONICAL_REASSESS_ACTIONS)
    assert "REDEFINITION" not in actions
    assert "REPLACE" not in actions
    assert ("Q-NEW", "REWORD") in {(a["question_id"], a["action"]) for a in result["actions"]}
    assert ("Q-OLD", "SUPERSEDED") in {(a["question_id"], a["action"]) for a in result["actions"]}

    persisted = _latest_reassess_payload(tmp_path)
    persisted_actions = [entry["action"] for entry in persisted["actions"]]
    assert set(persisted_actions).issubset(_CANONICAL_REASSESS_ACTIONS)
    assert "REDEFINITION" not in persisted_actions
    assert "REPLACE" not in persisted_actions


def test_handle_planner_updates_irrelevant_marks_question_stale(tmp_path) -> None:
    orchestrator = _build_orchestrator(tmp_path)
    assert orchestrator._planner_store is not None
    assert orchestrator._queue is not None

    orchestrator._queue.enqueue(_open_question("Q-IRREL", "intent.irrelevant.path"))

    orchestrator._planner_store.write(
        {
            "type": "constraint_saved",
            "event_id": "evt-irrel-1",
            "created_at": "2026-02-13T12:00:30+00:00",
            "source": "PLANNER",
            "canonical_key": "intent.irrelevant.path",
            "irrelevant": True,
        }
    )

    result = orchestrator.handle_planner_updates()

    action_pairs = {(a["question_id"], a["action"]) for a in result["actions"]}
    assert ("Q-IRREL", "STALE") in action_pairs
    assert ("Q-IRREL", "SUPERSEDED") not in action_pairs

    queued_item = orchestrator._queue.get_item("Q-IRREL")
    assert queued_item is not None
    assert queued_item.status == "STALE"

    persisted = _latest_reassess_payload(tmp_path)
    persisted_pairs = {(a["question_id"], a["action"]) for a in persisted["actions"]}
    assert ("Q-IRREL", "STALE") in persisted_pairs
    assert ("Q-IRREL", "SUPERSEDED") not in persisted_pairs


class _ReplacementAsSupersededStrategy:
    def reassess(self, open_questions, problem_frame, new_constraints, *, run_agent=None):  # type: ignore[no-untyped-def]
        return [
            {
                "question_id": "Q-OLD",
                "action": "SUPERSEDED",
                "reason": "Question was replaced by newer planning context.",
                "replacement": {
                    "new_question_id": "Q-NEW",
                    "new_canonical_key": "intent.new.path",
                    "new_user_prompt_text": "Which updated path should be used?",
                },
            }
        ]


def test_handle_planner_updates_replacement_payload_uses_superseded_action(tmp_path) -> None:
    orchestrator = _build_orchestrator(tmp_path)
    assert orchestrator._planner_store is not None
    assert orchestrator._queue is not None

    orchestrator._queue.enqueue(_open_question("Q-OLD", "intent.old.path"))
    orchestrator._queue_reassess = _ReplacementAsSupersededStrategy()

    orchestrator._planner_store.write(
        {
            "type": "constraint_saved",
            "event_id": "evt-2",
            "created_at": "2026-02-13T12:01:00+00:00",
            "source": "PLANNER",
            "constraint_ids": ["CON-2"],
        }
    )

    result = orchestrator.handle_planner_updates()

    actions = [entry["action"] for entry in result["actions"]]
    assert set(actions).issubset(_CANONICAL_REASSESS_ACTIONS)
    assert "REPLACE" not in actions
    assert ("Q-OLD", "SUPERSEDED") in {(a["question_id"], a["action"]) for a in result["actions"]}

    old_item = orchestrator._queue.get_item("Q-OLD")
    new_item = orchestrator._queue.get_item("Q-NEW")
    assert old_item is not None
    assert old_item.status == "SUPERSEDED"
    assert new_item is not None
    assert new_item.status == "OPEN"

    persisted = _latest_reassess_payload(tmp_path)
    persisted_actions = [entry["action"] for entry in persisted["actions"]]
    assert set(persisted_actions).issubset(_CANONICAL_REASSESS_ACTIONS)
    assert "REPLACE" not in persisted_actions
