"""Tests for cost ledger."""

import time

from spec_manager.evaluation.cost_ledger import CostLedger, LLMCallRecord


class TestLLMCallRecord:
    def test_to_dict(self):
        record = LLMCallRecord(
            agent_name="test-agent",
            duration_ms=500.0,
            timestamp=1000.0,
            run_id="run-1",
        )
        d = record.to_dict()
        assert d["agent_name"] == "test-agent"
        assert d["duration_ms"] == 500.0

    def test_from_dict(self):
        data = {"agent_name": "agent-x", "duration_ms": 100.0, "timestamp": 1.0}
        record = LLMCallRecord.from_dict(data)
        assert record.agent_name == "agent-x"
        assert record.duration_ms == 100.0

    def test_roundtrip(self):
        original = LLMCallRecord(
            agent_name="rt", duration_ms=42.0, timestamp=time.time(), layer="l1"
        )
        restored = LLMCallRecord.from_dict(original.to_dict())
        assert restored.agent_name == original.agent_name
        assert restored.layer == original.layer


class TestCostLedger:
    def test_empty_ledger(self, tmp_path):
        ledger = CostLedger(tmp_path / "llm_calls.jsonl")
        assert ledger.read_all() == []

    def test_record_and_read(self, tmp_path):
        ledger = CostLedger(tmp_path / "llm_calls.jsonl")
        record = LLMCallRecord(agent_name="test", duration_ms=100.0, timestamp=1.0)
        ledger.record(record)

        records = ledger.read_all()
        assert len(records) == 1
        assert records[0].agent_name == "test"

    def test_multiple_records(self, tmp_path):
        ledger = CostLedger(tmp_path / "llm_calls.jsonl")
        for i in range(5):
            ledger.record(LLMCallRecord(agent_name=f"agent-{i}", duration_ms=float(i * 100)))

        records = ledger.read_all()
        assert len(records) == 5

    def test_summary(self, tmp_path):
        ledger = CostLedger(tmp_path / "llm_calls.jsonl")
        ledger.record(LLMCallRecord(agent_name="a", duration_ms=100.0, layer="l1"))
        ledger.record(LLMCallRecord(agent_name="a", duration_ms=200.0, layer="l1"))
        ledger.record(LLMCallRecord(agent_name="b", duration_ms=300.0, layer="l2"))

        stats = ledger.summary()
        assert stats["total_calls"] == 3
        assert stats["total_duration_ms"] == 600.0
        assert stats["by_agent"]["a"] == 2
        assert stats["by_agent"]["b"] == 1
        assert stats["by_layer"]["l1"] == 2
        assert stats["by_layer"]["l2"] == 1

    def test_empty_summary(self, tmp_path):
        ledger = CostLedger(tmp_path / "nonexistent.jsonl")
        stats = ledger.summary()
        assert stats["total_calls"] == 0

    def test_creates_parent_dirs(self, tmp_path):
        deep_path = tmp_path / "a" / "b" / "c" / "ledger.jsonl"
        ledger = CostLedger(deep_path)
        ledger.record(LLMCallRecord(agent_name="test"))
        assert deep_path.exists()
