"""Tests for tiered dedup behavior in intent-agent question queue."""

from __future__ import annotations

from datetime import UTC, datetime, timezone

from spec_manager.orchestration.intent_agent.queue import (
    QuestionBlockers,
    QuestionItem,
    QuestionOrigin,
    QuestionQueue,
    UserPrompt,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _question(
    question_id: str,
    *,
    canonical_key: str,
    text: str,
    scenario: str = "",
    taxonomy_type: str = "CONSTRAINT",
    scope_kind: str = "FEATURE_SPECIFIC",
    trace_id: str,
) -> QuestionItem:
    item = QuestionItem(
        question_id=question_id,
        taxonomy_type=taxonomy_type,
        scope_kind=scope_kind,
        canonical_key=canonical_key,
        user_prompt=UserPrompt(text=text, scenario=scenario),
        origins=[
            QuestionOrigin(
                source_kind="PLANNER",
                trace_id=trace_id,
                created_at=_now_iso(),
            )
        ],
        blockers=QuestionBlockers(
            severity="BLOCKING",
            blocked_slices=[question_id],
        ),
    )
    item.quality_gate.status = "PASS"
    return item


def test_dedup_tier3_semantic_same_taxonomy_and_scope_merges() -> None:
    queue = QuestionQueue()
    existing = _question(
        "Q-100",
        canonical_key="approval.enterprise.threshold",
        text="What approval limit should we enforce for enterprise invoices?",
        scenario="A large invoice enters the finance approval workflow.",
        trace_id="trace-existing",
    )
    queue.enqueue(existing)

    incoming = _question(
        "Q-200",
        canonical_key="finance.invoice.authority",
        text="Which approval threshold must apply to enterprise invoices?",
        scenario="An enterprise invoice is waiting for approval.",
        trace_id="trace-new",
    )

    duplicate = queue.dedup(incoming)

    assert duplicate is not None
    assert duplicate.question_id == "Q-100"
    merged = queue.get_item("Q-100")
    assert merged is not None
    assert sorted(origin.trace_id for origin in merged.origins) == ["trace-existing", "trace-new"]
    assert sorted(merged.blockers.blocked_slices) == ["Q-100", "Q-200"]


def test_dedup_tier3_semantic_does_not_merge_different_meaning() -> None:
    queue = QuestionQueue()
    queue.enqueue(
        _question(
            "Q-100",
            canonical_key="approval.enterprise.threshold",
            text="What approval limit should we enforce for enterprise invoices?",
            scenario="A large invoice enters the finance approval workflow.",
            trace_id="trace-existing",
        ),
    )

    incoming = _question(
        "Q-200",
        canonical_key="invoice.payment.currency",
        text="Which currencies must payment processing support for suppliers?",
        scenario="The team is defining payment integration requirements.",
        trace_id="trace-new",
    )

    assert queue.dedup(incoming) is None


def test_dedup_tier3_semantic_requires_same_taxonomy_and_scope() -> None:
    queue = QuestionQueue()
    queue.enqueue(
        _question(
            "Q-100",
            canonical_key="approval.enterprise.threshold",
            text="What approval limit should we enforce for enterprise invoices?",
            scenario="A large invoice enters the finance approval workflow.",
            taxonomy_type="CONSTRAINT",
            scope_kind="FEATURE_SPECIFIC",
            trace_id="trace-existing",
        ),
    )

    same_text_other_scope = _question(
        "Q-200",
        canonical_key="finance.invoice.authority",
        text="Which approval threshold must apply to enterprise invoices?",
        scenario="An enterprise invoice is waiting for approval.",
        taxonomy_type="CONSTRAINT",
        scope_kind="SYSTEM_WIDE",
        trace_id="trace-scope",
    )
    same_text_other_taxonomy = _question(
        "Q-300",
        canonical_key="finance.invoice.authority.alt",
        text="Which approval threshold must apply to enterprise invoices?",
        scenario="An enterprise invoice is waiting for approval.",
        taxonomy_type="TRADEOFF",
        scope_kind="FEATURE_SPECIFIC",
        trace_id="trace-taxonomy",
    )

    assert queue.dedup(same_text_other_scope) is None
    assert queue.dedup(same_text_other_taxonomy) is None


def test_dedup_tier3_semantic_uses_deterministic_best_candidate_order() -> None:
    queue = QuestionQueue()
    # Insert in reverse ID order to verify dedup selection is not insertion-order dependent.
    queue.enqueue(
        _question(
            "Q-200",
            canonical_key="approval.enterprise.threshold.v2",
            text="Which approval threshold must apply to enterprise invoices?",
            scenario="An enterprise invoice is waiting for approval.",
            trace_id="trace-q200",
        ),
    )
    queue.enqueue(
        _question(
            "Q-100",
            canonical_key="approval.enterprise.threshold.v1",
            text="Which approval threshold must apply to enterprise invoices?",
            scenario="An enterprise invoice is waiting for approval.",
            trace_id="trace-q100",
        ),
    )

    incoming = _question(
        "Q-300",
        canonical_key="finance.invoice.authority",
        text="Which approval threshold must apply to enterprise invoices?",
        scenario="An enterprise invoice is waiting for approval.",
        trace_id="trace-new",
    )

    duplicate = queue.dedup(incoming)

    assert duplicate is not None
    assert duplicate.question_id == "Q-100"
