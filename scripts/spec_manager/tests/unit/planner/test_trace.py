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
    canonical_json,
    compute_decision_key,
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

    # -- new fields on PlannerTrace -----------------------------------------

    def test_trace_new_fields_defaults(self) -> None:
        """New metadata fields default to empty/falsy values."""
        trace = PlannerTrace.start("t-defaults", {})
        assert trace.decision_key == ""
        assert trace.run_id == ""
        assert trace.model_id == ""
        assert trace.layer == ""
        assert trace.capability == ""
        assert trace.slice_id == ""
        assert trace.status == ""
        assert trace.overridden is False

    def test_trace_start_with_kwargs_sets_new_fields(self) -> None:
        """PlannerTrace.start() accepts keyword args for new fields."""
        trace = PlannerTrace.start(
            "t-kwargs",
            {"key": "val"},
            decision_key="l1:GAP:slice-a:0:deadbeef",
            run_id="run-42",
            model_id="opus-4",
            layer="l1",
            capability="GAP",
            slice_id="slice-a",
        )
        assert trace.trace_id == "t-kwargs"
        assert trace.decision_key == "l1:GAP:slice-a:0:deadbeef"
        assert trace.run_id == "run-42"
        assert trace.model_id == "opus-4"
        assert trace.layer == "l1"
        assert trace.capability == "GAP"
        assert trace.slice_id == "slice-a"

    def test_to_dict_includes_all_new_fields(self) -> None:
        """to_dict() includes every new metadata field."""
        trace = PlannerTrace.start(
            "t-dict",
            {},
            decision_key="l2:PLAN:s1:1:ab12cd34",
            run_id="run-99",
            model_id="sonnet-5",
            layer="l2",
            capability="PLAN",
            slice_id="s1",
        )
        trace.status = "OK"
        trace.overridden = True

        d = trace.to_dict()
        assert d["decision_key"] == "l2:PLAN:s1:1:ab12cd34"
        assert d["run_id"] == "run-99"
        assert d["model_id"] == "sonnet-5"
        assert d["layer"] == "l2"
        assert d["capability"] == "PLAN"
        assert d["slice_id"] == "s1"
        assert d["status"] == "OK"
        assert d["overridden"] is True

    def test_index_entry_shape(self) -> None:
        """_index_entry() returns a dict with expected keys."""
        trace = PlannerTrace.start(
            "t-idx",
            {},
            decision_key="l1:GAP:s1:0:aabbccdd",
            run_id="run-1",
            model_id="opus",
            layer="l1",
            capability="GAP",
            slice_id="s1",
        )
        trace.status = "OK"
        trace.overridden = False
        trace.record_model_call(ModelCallRecord(agent_name="a"))
        trace.record_tool_call(ToolCallRecord(tool_name="t"))

        entry = trace._index_entry()
        assert entry["trace_id"] == "t-idx"
        assert "timestamp" in entry
        assert entry["run_id"] == "run-1"
        assert entry["model_id"] == "opus"
        assert entry["slice_id"] == "s1"
        assert entry["layer"] == "l1"
        assert entry["capability"] == "GAP"
        assert entry["decision_key"] == "l1:GAP:s1:0:aabbccdd"
        assert entry["status"] == "OK"
        assert entry["overridden"] is False
        assert entry["model_calls_count"] == 1
        assert entry["tool_calls_count"] == 1

    # -- index.jsonl persistence --------------------------------------------

    def test_persist_creates_index_jsonl(self, tmp_path: Path) -> None:
        """persist() writes an index.jsonl file alongside trace directories."""
        trace = PlannerTrace.start("t-index", {}, layer="l1", capability="GAP")
        trace.status = "OK"
        trace.persist(tmp_path)

        index_path = tmp_path / "analysis" / "planner_traces" / "index.jsonl"
        assert index_path.exists()

    def test_index_jsonl_contains_trace_metadata(self, tmp_path: Path) -> None:
        """index.jsonl entry contains key trace metadata."""
        trace = PlannerTrace.start(
            "t-idx-content",
            {},
            run_id="run-7",
            layer="l2",
            capability="PLAN",
            slice_id="slice-b",
        )
        trace.status = "OK"
        trace.persist(tmp_path)

        index_path = tmp_path / "analysis" / "planner_traces" / "index.jsonl"
        lines = [ln for ln in index_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["trace_id"] == "t-idx-content"
        assert entry["run_id"] == "run-7"
        assert entry["layer"] == "l2"
        assert entry["capability"] == "PLAN"
        assert entry["slice_id"] == "slice-b"
        assert entry["status"] == "OK"

    def test_multiple_persists_append_to_index_jsonl(self, tmp_path: Path) -> None:
        """Each persist() call appends a new line to index.jsonl."""
        for i in range(3):
            trace = PlannerTrace.start(f"t-multi-{i}", {}, layer="l1")
            trace.status = "OK"
            trace.persist(tmp_path)

        index_path = tmp_path / "analysis" / "planner_traces" / "index.jsonl"
        lines = [ln for ln in index_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 3
        ids = [json.loads(ln)["trace_id"] for ln in lines]
        assert ids == ["t-multi-0", "t-multi-1", "t-multi-2"]


# ---------------------------------------------------------------------------
# compute_decision_key
# ---------------------------------------------------------------------------


class TestComputeDecisionKey:
    def test_basic_key_format(self) -> None:
        """Key follows {layer}:{capability}:{slice_id}:{iteration}:{hash} format."""
        key = compute_decision_key(
            layer="l1",
            capability="GAP",
            slice_id="slice-a",
            iteration=0,
            inputs={"gaps": [{"id": "g1"}]},
        )
        parts = key.split(":")
        assert len(parts) == 5
        assert parts[0] == "l1"
        assert parts[1] == "GAP"
        assert parts[2] == "slice-a"
        assert parts[3] == "0"
        # Hash portion is 8 hex chars
        assert len(parts[4]) == 8
        assert all(c in "0123456789abcdef" for c in parts[4])

    def test_deterministic(self) -> None:
        """Same inputs produce the same key."""
        kwargs: dict[str, Any] = {
            "layer": "l2",
            "capability": "PLAN",
            "slice_id": "s1",
            "iteration": 3,
            "inputs": {"gaps": [{"target": "f1"}]},
        }
        key1 = compute_decision_key(**kwargs)
        key2 = compute_decision_key(**kwargs)
        assert key1 == key2

    def test_different_inputs_produce_different_keys(self) -> None:
        """Distinct inputs produce different keys."""
        base: dict[str, Any] = {
            "layer": "l1",
            "capability": "GAP",
            "slice_id": "s1",
            "iteration": 0,
        }
        key_a = compute_decision_key(**base, inputs={"gaps": [{"id": "a"}]})
        key_b = compute_decision_key(**base, inputs={"gaps": [{"id": "b"}]})
        assert key_a != key_b

    def test_different_layers_produce_different_keys(self) -> None:
        """Keys differ when the layer field differs."""
        inputs: dict[str, Any] = {"gaps": []}
        key_l1 = compute_decision_key("l1", "GAP", "s1", 0, inputs)
        key_l2 = compute_decision_key("l2", "GAP", "s1", 0, inputs)
        assert key_l1 != key_l2

    def test_with_empty_inputs(self) -> None:
        """Empty inputs dict produces a valid key."""
        key = compute_decision_key(
            layer="l3",
            capability="PLAN",
            slice_id="",
            iteration=0,
            inputs={},
        )
        parts = key.split(":")
        assert len(parts) == 5
        assert parts[0] == "l3"
        assert parts[2] == ""  # empty slice_id preserved

    def test_custom_capability_input_fields(self) -> None:
        """Custom capability_input_fields narrows the input subset used for hashing."""
        inputs = {"alpha": 1, "beta": 2, "gamma": 3}
        custom_fields: dict[str, list[str]] = {"MY_CAP": ["alpha"]}

        key_custom = compute_decision_key(
            layer="l1",
            capability="MY_CAP",
            slice_id="s1",
            iteration=0,
            inputs=inputs,
            capability_input_fields=custom_fields,
        )
        # Changing an ignored field should NOT change the key
        inputs_different_beta = {"alpha": 1, "beta": 999, "gamma": 3}
        key_custom2 = compute_decision_key(
            layer="l1",
            capability="MY_CAP",
            slice_id="s1",
            iteration=0,
            inputs=inputs_different_beta,
            capability_input_fields=custom_fields,
        )
        assert key_custom == key_custom2

        # Changing the included field SHOULD change the key
        inputs_different_alpha = {"alpha": 99, "beta": 2, "gamma": 3}
        key_custom3 = compute_decision_key(
            layer="l1",
            capability="MY_CAP",
            slice_id="s1",
            iteration=0,
            inputs=inputs_different_alpha,
            capability_input_fields=custom_fields,
        )
        assert key_custom != key_custom3


# ---------------------------------------------------------------------------
# canonical_json
# ---------------------------------------------------------------------------


class TestCanonicalJson:
    def test_sorted_keys(self) -> None:
        """canonical_json produces sorted keys."""
        result = canonical_json({"z": 1, "a": 2, "m": 3})
        assert result == '{"a":2,"m":3,"z":1}'

    def test_deterministic(self) -> None:
        """Same input always produces the same output."""
        obj = {"b": [1, 2], "a": {"x": True}}
        assert canonical_json(obj) == canonical_json(obj)

    def test_nested_objects_sorted(self) -> None:
        """Nested dicts also have their keys sorted."""
        obj = {"outer": {"z_inner": 1, "a_inner": 2}}
        result = canonical_json(obj)
        # inner keys should be a_inner before z_inner
        assert '"a_inner":2' in result
        assert result.index('"a_inner"') < result.index('"z_inner"')

    def test_no_extra_whitespace(self) -> None:
        """Output has no extra whitespace (compact separators)."""
        result = canonical_json({"key": "value"})
        assert " " not in result


# ---------------------------------------------------------------------------
# ModelCallRecord — new fields
# ---------------------------------------------------------------------------


class TestModelCallRecordNewFields:
    def test_tokens_in_out_defaults(self) -> None:
        """tokens_in and tokens_out default to 0."""
        record = ModelCallRecord(agent_name="test")
        assert record.tokens_in == 0
        assert record.tokens_out == 0

    def test_tokens_in_out_with_values(self) -> None:
        """tokens_in and tokens_out can be set explicitly."""
        record = ModelCallRecord(
            agent_name="gap_agent",
            model="opus",
            tokens_in=1500,
            tokens_out=800,
        )
        assert record.tokens_in == 1500
        assert record.tokens_out == 800
