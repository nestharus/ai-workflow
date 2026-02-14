"""Tests for question origin source kind validation."""

from __future__ import annotations

from datetime import UTC, datetime, timezone

from spec_manager.orchestration.intent_agent.queue import (
    QuestionBlockers,
    QuestionItem,
    QuestionOrigin,
    UserPrompt,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def test_validate_accepts_slice_agent_origin_source_kind() -> None:
    item = QuestionItem(
        question_id="Q-SOURCE-1",
        canonical_key="intent.source.validation",
        user_prompt=UserPrompt(text="Which option should we use?"),
        origins=[
            QuestionOrigin(
                source_kind="SLICE_AGENT",
                trace_id="trace-source-1",
                created_at=_now_iso(),
            )
        ],
        blockers=QuestionBlockers(severity="BLOCKING", blocked_slices=["slice-1"]),
    )

    item.validate()
