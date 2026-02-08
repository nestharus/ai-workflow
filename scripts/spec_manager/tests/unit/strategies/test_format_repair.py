from __future__ import annotations

from typing import Any

from spec_manager.strategies.base import ProcessingContext, StrategyPhase
from spec_manager.strategies.implementations.format_repair import (
    FormatRepairStrategy,
)
from spec_manager.workflow.config import TrackedUnit, UnitType


def _make_unit(unit_id: str, content: str) -> TrackedUnit:
    return TrackedUnit(
        id=unit_id,
        content=content,
        unit_type=UnitType.PROSE,
        source="tests",
        introduced_by="p1",
    )


def test_applies_to_detects_format_noise() -> None:
    strategy = FormatRepairStrategy()

    fenced_unit = _make_unit("u1", '```json\n{"key": "value"}\n```')
    context = ProcessingContext(
        units=[fenced_unit],
        phase=StrategyPhase.CLEANING,
        config={},
    )
    assert strategy.applies_to(context)

    clean_unit = _make_unit("u2", '{"key": "value"}')
    context = ProcessingContext(
        units=[clean_unit],
        phase=StrategyPhase.CLEANING,
        config={},
    )
    assert not strategy.applies_to(context)


def test_execute_removes_code_fence() -> None:
    strategy = FormatRepairStrategy()
    unit = _make_unit("u1", '```json\n{"key": "value"}\n```')
    context = ProcessingContext(
        units=[unit],
        phase=StrategyPhase.CLEANING,
        config={},
    )

    result = strategy.execute(context)

    assert unit.content == '{"key": "value"}'
    assert "Format repair: extracted JSON payload for u1" in result.issues
    assert "Format repair: removed code fences from u1" in result.issues
    assert result.metrics["extraction_count"] == 1
    assert result.metrics["repair_count"] == 0
    assert len(result.evidence_records) >= 1
    rec = result.evidence_records[0]
    assert rec["category"] == "format"
    assert rec["type"] in {"code_fence_removal", "json_extraction", "preamble_stripping"}
    assert "original_length" in rec["details"]
    assert "cleaned_length" in rec["details"]


def test_execute_strips_preamble() -> None:
    strategy = FormatRepairStrategy()
    unit = _make_unit("u1", 'Preamble\n{"key": "value"}')
    context = ProcessingContext(
        units=[unit],
        phase=StrategyPhase.CLEANING,
        config={},
    )

    result = strategy.execute(context)

    assert unit.content == '{"key": "value"}'
    assert "Format repair: extracted JSON payload for u1" in result.issues
    assert "Format repair: stripped preamble from u1" in result.issues
    assert result.metrics["extraction_count"] == 1
    assert result.metrics["repair_count"] == 0
    assert len(result.evidence_records) >= 1
    rec = result.evidence_records[0]
    assert rec["category"] == "format"
    assert rec["type"] == "preamble_stripping"
    assert rec["details"]["location"] == "format_repair:u1"


def test_execute_normalizes_json_via_repair_agent() -> None:
    calls: list[dict[str, Any]] = []

    def fake_repair_agent(**kwargs: Any) -> tuple[str, list[dict[str, Any]]]:
        calls.append(kwargs)
        return '{"fixed": true}', [
            {
                "category": "format",
                "type": "repair_agent_invoked",
                "details": {"artifact_type": "spec"},
            }
        ]

    strategy = FormatRepairStrategy(tools={"repair_agent": fake_repair_agent})
    unit = _make_unit("u1", "```json\n{not json}\n```")
    context = ProcessingContext(
        units=[unit],
        phase=StrategyPhase.CLEANING,
        config={},
    )

    result = strategy.execute(context)

    assert calls, "repair agent should be invoked"
    assert unit.content == '{"fixed": true}'
    assert "Format repair: normalized JSON for u1" in result.issues
    assert result.metrics["repair_count"] == 1
    assert result.metrics["extraction_count"] == 0
    assert len(result.evidence_records) == 1
    rec = result.evidence_records[0]
    assert rec["category"] == "format"
    assert rec["type"] == "repair_agent_invoked"
    assert rec["details"]["artifact_type"] == "spec"
