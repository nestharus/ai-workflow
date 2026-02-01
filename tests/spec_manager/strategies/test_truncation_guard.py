from __future__ import annotations

from scripts.spec_manager.spec_manager.strategies.base import ProcessingContext, StrategyPhase
from scripts.spec_manager.spec_manager.strategies.implementations.truncation_guard import (
    TruncationGuardStrategy,
)
from scripts.spec_manager.spec_manager.workflow.config import TrackedUnit, UnitType


def _make_unit(unit_id: str, content: str) -> TrackedUnit:
    return TrackedUnit(
        id=unit_id,
        content=content,
        unit_type=UnitType.PROSE,
        source="tests",
        introduced_by="p1",
    )


def test_applies_to_respects_cap() -> None:
    strategy = TruncationGuardStrategy()
    unit = _make_unit("u1", "12345")
    context = ProcessingContext(
        units=[unit],
        phase=StrategyPhase.CLEANING,
        config={"max_unit_content_length": 10},
    )
    assert not strategy.applies_to(context)

    unit_long = _make_unit("u2", "12345678901")
    context = ProcessingContext(
        units=[unit_long],
        phase=StrategyPhase.CLEANING,
        config={"max_unit_content_length": 10},
    )
    assert strategy.applies_to(context)


def test_execute_truncates_over_cap() -> None:
    strategy = TruncationGuardStrategy()
    unit = _make_unit("u1", "123456789012345")
    context = ProcessingContext(
        units=[unit],
        phase=StrategyPhase.CLEANING,
        config={"max_unit_content_length": 10},
    )

    result = strategy.execute(context)

    assert unit.content == "1234567890"
    assert result.metrics["truncation_count"] == 1
    assert result.metrics["total_chars_removed"] == 5
    assert any("WARNING: Truncation guard" in issue for issue in result.issues)
    assert len(result.evidence_records) == 1
    rec = result.evidence_records[0]
    assert rec["severity"] == "warning"
    assert rec["details"]["original_length"] == 15
    assert rec["details"]["truncated_length"] == 10
    assert rec["details"]["chars_removed"] == 5


def test_execute_flags_severe_truncation() -> None:
    strategy = TruncationGuardStrategy()
    unit = _make_unit("u1", "x" * 25)
    context = ProcessingContext(
        units=[unit],
        phase=StrategyPhase.CLEANING,
        config={"max_unit_content_length": 10},
    )

    result = strategy.execute(context)

    assert unit.content == "x" * 10
    assert any(issue.startswith("ERROR: Truncation guard") for issue in result.issues)
    assert result.metrics["truncation_count"] == 1
    assert result.metrics["total_chars_removed"] == 15
    assert len(result.evidence_records) == 1
    rec = result.evidence_records[0]
    assert rec["severity"] == "error"
    assert rec["details"]["original_length"] == 25
    assert rec["details"]["truncated_length"] == 10
    assert rec["details"]["chars_removed"] == 15


def test_execute_no_truncation_at_cap() -> None:
    strategy = TruncationGuardStrategy()
    unit = _make_unit("u1", "1234567890")
    context = ProcessingContext(
        units=[unit],
        phase=StrategyPhase.CLEANING,
        config={"max_unit_content_length": 10},
    )

    result = strategy.execute(context)

    assert unit.content == "1234567890"
    assert result.metrics["truncation_count"] == 0
    assert result.metrics["total_chars_removed"] == 0
    assert not result.issues
    assert not result.evidence_records
