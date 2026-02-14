"""Cost tracking ledger for LLM calls during PDD pipeline runs.

Append-only JSONL ledger records agent invocations with timing metadata.

Usage::

    ledger = CostLedger(Path(".pdd_runs/abc/analysis/llm_calls.jsonl"))
    ledger.record(LLMCallRecord(agent_name="opus-arch", duration_ms=1200, timestamp=time.time()))
    records = ledger.read_all()
    stats = ledger.summary()
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _as_int(value: Any) -> int:
    """Convert value to int with safe fallback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    """Convert value to float with safe fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class LLMCallRecord:
    """A single LLM call record."""

    agent_name: str = ""
    role: str = ""
    model_id: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: float = 0.0
    timestamp: float = 0.0
    run_id: str = ""
    slice_id: str = ""
    layer: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LLMCallRecord:
        return cls(
            agent_name=data.get("agent_name", ""),
            role=data.get("role", ""),
            model_id=data.get("model_id", ""),
            tokens_in=_as_int(data.get("tokens_in", 0)),
            tokens_out=_as_int(data.get("tokens_out", 0)),
            duration_ms=_as_float(data.get("duration_ms", 0.0)),
            timestamp=_as_float(data.get("timestamp", 0.0)),
            run_id=data.get("run_id", ""),
            slice_id=data.get("slice_id", ""),
            layer=data.get("layer", ""),
        )


class CostLedger:
    """Append-only JSONL ledger for LLM call tracking."""

    def __init__(self, ledger_path: Path) -> None:
        self.ledger_path = ledger_path

    def record(self, call: LLMCallRecord) -> None:
        """Append a call record to the ledger."""
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(call.to_dict()) + "\n")

    def read_all(self) -> list[LLMCallRecord]:
        """Read all records from the ledger."""
        if not self.ledger_path.exists():
            return []
        records: list[LLMCallRecord] = []
        for line in self.ledger_path.read_text(encoding="utf-8").strip().split("\n"):
            if line:
                records.append(LLMCallRecord.from_dict(json.loads(line)))
        return records

    def summary(self) -> dict[str, Any]:
        """Compute summary statistics from the ledger."""
        records = self.read_all()
        by_agent: dict[str, int] = {}
        by_layer: dict[str, int] = {}
        by_model: dict[str, int] = {}
        total_duration_ms = 0.0
        total_tokens_in = 0
        total_tokens_out = 0

        for r in records:
            by_agent[r.agent_name] = by_agent.get(r.agent_name, 0) + 1
            if r.layer:
                by_layer[r.layer] = by_layer.get(r.layer, 0) + 1
            if r.model_id:
                by_model[r.model_id] = by_model.get(r.model_id, 0) + 1
            total_duration_ms += r.duration_ms
            total_tokens_in += r.tokens_in
            total_tokens_out += r.tokens_out

        return {
            "total_calls": len(records),
            "total_duration_ms": total_duration_ms,
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "by_agent": by_agent,
            "by_layer": by_layer,
            "by_model": by_model,
        }
