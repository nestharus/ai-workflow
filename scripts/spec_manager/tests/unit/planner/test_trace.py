"""Tests for spec_manager.planner.trace — PlannerTrace and record types."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from spec_manager.planner.trace import (
    DecisionRecord,
    ModelCallRecord,
    PlannerTrace,
    ToolCallRecord,
    content_hash,
)


class TestModelCallRecord:
    def test_model_call_record_defaults(self) -> None:
        record = ModelCallRecord(agent_name="gap_agent")
        assert record.agent_name == "gap_agent"
        assert record.model == ""
        assert record.duration_ms == 0
        assert record.timestamp != ""  # auto-set by __post_init__

    def test_model_call_record_with_values(self) -> None:
        record = ModelCallRecord(
            agent_name="plan_agent",
            model="opus",
            prompt_hash="abc123",
            output_hash="def456",
            duration_ms=150.5,
        )
        assert record.model == "opus"
        assert record.prompt_hash == "abc123"
        assert record.duration_ms == 150.5


class TestToolCallRecord:
    def test_tool_call_record_defaults(self) -> None:
        record = ToolCallRecord(tool_name="evidence_search")
        assert record.tool_name == "evidence_search"
        assert record.timestamp != ""

    def test_tool_call_record_with_values(self) -> None:
        record = ToolCallRecord(
            tool_name="research",
            inputs_hash="inp-hash",
            output_summary="found 3 results",
            duration_ms=42.0,
        )
        assert record.output_summary == "found 3 results"


class TestDecisionRecord:
    def test_decision_record_defaults(self) -> None:
        dec = DecisionRecord()
        assert dec.decision_text == ""
        assert dec.confidence == 0.0
        assert dec.assumptions == []
        assert dec.evidence_refs == []
        assert dec.alternatives_considered == []
        assert dec.discriminative_checks == []

    def test_decision_record_with_values(self) -> None:
        dec = DecisionRecord(
            decision_text="promote",
            confidence=0.95,
            assumptions=["all gates pass"],
            evidence_refs=["ev-001"],
        )
        assert dec.decision_text == "promote"
        assert dec.confidence == 0.95


class TestContentHash:
    def test_content_hash_returns_16_hex_chars(self) -> None:
        h = content_hash("hello world")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_content_hash_deterministic(self) -> None:
        assert content_hash("test") == content_hash("test")

    def test_content_hash_different_inputs(self) -> None:
        assert content_hash("a") != content_hash("b")


class TestPlannerTrace:
    def test_trace_start_factory(self) -> None:
        trace = PlannerTrace.start("trace-001", {"slice": "foo", "layer": "L1"})
        assert trace.trace_id == "trace-001"
        assert trace.request_snapshot == {"slice": "foo", "layer": "L1"}
        assert trace.model_calls == []
        assert trace.tool_calls == []
        assert trace.decision is None
        assert trace.artifacts == {}

    def test_trace_records_model_call(self) -> None:
        trace = PlannerTrace.start("t1", {})
        mc = ModelCallRecord(agent_name="gap_agent", model="opus")
        trace.record_model_call(mc)
        assert len(trace.model_calls) == 1
        assert trace.model_calls[0] is mc

        # Record a second call
        mc2 = ModelCallRecord(agent_name="plan_agent", model="sonnet")
        trace.record_model_call(mc2)
        assert len(trace.model_calls) == 2

    def test_trace_records_tool_call(self) -> None:
        trace = PlannerTrace.start("t2", {})
        tc = ToolCallRecord(tool_name="evidence_search", output_summary="3 hits")
        trace.record_tool_call(tc)
        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].tool_name == "evidence_search"

    def test_trace_set_decision(self) -> None:
        trace = PlannerTrace.start("t3", {})
        assert trace.decision is None

        dec = DecisionRecord(decision_text="promote", confidence=0.9)
        trace.set_decision(dec)
        assert trace.decision is dec
        assert trace.decision.decision_text == "promote"

        # Overwrite
        dec2 = DecisionRecord(decision_text="block", confidence=0.3)
        trace.set_decision(dec2)
        assert trace.decision is dec2

    def test_trace_add_artifact(self) -> None:
        trace = PlannerTrace.start("t4", {})
        trace.add_artifact("graph", {"nodes": [1, 2], "edges": []})
        assert "graph" in trace.artifacts
        assert trace.artifacts["graph"]["nodes"] == [1, 2]

    def test_trace_to_dict(self) -> None:
        trace = PlannerTrace.start("t5", {"key": "val"})
        trace.record_model_call(ModelCallRecord(agent_name="a1"))
        trace.record_tool_call(ToolCallRecord(tool_name="t1"))
        trace.set_decision(DecisionRecord(decision_text="ok"))
        trace.add_artifact("plan", {"steps": []})

        d = trace.to_dict()
        assert d["trace_id"] == "t5"
        assert d["request_snapshot"] == {"key": "val"}
        assert len(d["model_calls"]) == 1
        assert len(d["tool_calls"]) == 1
        assert d["decision"]["decision_text"] == "ok"
        assert d["artifacts"]["plan"]["steps"] == []

    def test_trace_persist(self, tmp_path: Path) -> None:
        """persist writes all expected files to disk."""
        trace = PlannerTrace.start("trace-persist", {"slice": "s1"})
        trace.record_model_call(ModelCallRecord(agent_name="gap", model="opus", duration_ms=100))
        trace.record_tool_call(ToolCallRecord(tool_name="evidence", output_summary="2 hits"))
        trace.set_decision(DecisionRecord(decision_text="promote", confidence=0.88))
        trace.add_artifact("integration_graph", {"nodes": [{"id": "n1"}]})

        trace_dir = trace.persist(tmp_path)

        # Verify directory structure
        assert trace_dir.exists()
        assert trace_dir.name == "trace-persist"

        # request.json
        request_path = trace_dir / "request.json"
        assert request_path.exists()
        request_data = json.loads(request_path.read_text(encoding="utf-8"))
        assert request_data["slice"] == "s1"

        # decision.json
        decision_path = trace_dir / "decision.json"
        assert decision_path.exists()
        decision_data = json.loads(decision_path.read_text(encoding="utf-8"))
        assert decision_data["decision_text"] == "promote"
        assert decision_data["confidence"] == 0.88

        # calls/model_calls.jsonl
        model_path = trace_dir / "calls" / "model_calls.jsonl"
        assert model_path.exists()
        lines = [l for l in model_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 1
        mc_data = json.loads(lines[0])
        assert mc_data["agent_name"] == "gap"

        # calls/tool_calls.jsonl
        tool_path = trace_dir / "calls" / "tool_calls.jsonl"
        assert tool_path.exists()
        lines = [l for l in tool_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 1
        tc_data = json.loads(lines[0])
        assert tc_data["tool_name"] == "evidence"

        # artifacts/integration_graph.json
        artifact_path = trace_dir / "artifacts" / "integration_graph.json"
        assert artifact_path.exists()
        art_data = json.loads(artifact_path.read_text(encoding="utf-8"))
        assert art_data["nodes"] == [{"id": "n1"}]

        # replay.json
        replay_path = trace_dir / "replay.json"
        assert replay_path.exists()
        replay_data = json.loads(replay_path.read_text(encoding="utf-8"))
        assert replay_data["trace_id"] == "trace-persist"

    def test_trace_persist_idempotent(self, tmp_path: Path) -> None:
        """Calling persist twice should not duplicate JSONL entries."""
        trace = PlannerTrace.start("trace-idem", {})
        trace.record_model_call(ModelCallRecord(agent_name="a"))

        trace.persist(tmp_path)
        trace.persist(tmp_path)

        model_path = (
            tmp_path / "analysis" / "planner_traces" / "trace-idem" / "calls" / "model_calls.jsonl"
        )
        lines = [l for l in model_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 1
