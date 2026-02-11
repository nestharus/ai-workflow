"""Tests for ground_truth and trace_loader modules in planner eval package.

Module 1: spec_manager.refinement.evals.planner.ground_truth
    - Dataclass constructors, load/save, find_case, find_cases_by_capability

Module 2: spec_manager.refinement.evals.planner.trace_loader
    - TraceEntry/LoadedTrace constructors, load_index, load_trace,
      filter_traces, load_traces_for_run, trace_stats
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from spec_manager.refinement.evals.planner.ground_truth import (
    AtomMatch,
    GroundTruthCase,
    GroundTruthMeta,
    InvariantRule,
    PlannerGroundTruth,
    ProcessExpectation,
    Rubric,
    RubricGate,
    RubricSignal,
    find_case,
    find_cases_by_capability,
    load_ground_truth,
    save_ground_truth,
)
from spec_manager.refinement.evals.planner.trace_loader import (
    LoadedTrace,
    TraceEntry,
    filter_traces,
    load_index,
    load_trace,
    load_traces_for_run,
    trace_stats,
)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _make_gt_dict(
    *,
    spec_id: str = "test_spec",
    cases: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a minimal ground-truth dictionary for serialization tests."""
    return {
        "meta": {
            "spec_id": spec_id,
            "gt_version": 1,
            "created_at": "2026-01-01",
            "notes": "unit test fixture",
        },
        "cases": cases or [],
    }


def _make_case_dict(
    *,
    decision_key: str = "l1:PLAN:LIB-01:0:abcd1234",
    capability: str = "PLAN",
    layer: str = "l1",
    slice_id: str = "LIB-01",
    iteration: int = 0,
    rubric: dict[str, Any] | None = None,
    process_expectations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a ground-truth case dictionary."""
    d: dict[str, Any] = {
        "decision_key": decision_key,
        "capability": capability,
        "layer": layer,
        "slice_id": slice_id,
        "iteration": iteration,
        "input_fingerprint": {"gaps_hash": "sha256:aaa"},
        "expected": {
            "must_include": [
                {"id": "fn:create_entry", "match": {"function_name_any_of": ["create_entry"]}}
            ],
            "must_not_include": [],
            "invariants": [{"type": "schema", "rule": "l1_plan_intentions_v1"}],
        },
    }
    if rubric is not None:
        d["rubric"] = rubric
    if process_expectations is not None:
        d["process_expectations"] = process_expectations
    return d


def _write_json(path: Path, data: Any) -> None:
    """Write a JSON file, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write a JSONL file, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# =======================================================================
# Module 1: ground_truth
# =======================================================================


class TestGroundTruthDataclassDefaults:
    """Verify all dataclass constructors produce correct defaults."""

    def test_ground_truth_meta_defaults(self) -> None:
        """GroundTruthMeta defaults to empty strings and gt_version=1."""
        meta = GroundTruthMeta()
        assert meta.spec_id == ""
        assert meta.gt_version == 1
        assert meta.created_at == ""
        assert meta.notes == ""

    def test_atom_match_defaults(self) -> None:
        """AtomMatch defaults to empty id and empty match dict."""
        atom = AtomMatch()
        assert atom.id == ""
        assert atom.match == {}

    def test_invariant_rule_defaults(self) -> None:
        """InvariantRule defaults to empty strings/list and max_duplicates=0."""
        inv = InvariantRule()
        assert inv.type == ""
        assert inv.rule == ""
        assert inv.key_fields == []
        assert inv.max_duplicates == 0

    def test_process_expectation_defaults(self) -> None:
        """ProcessExpectation defaults to empty strings and min_rate=0.0."""
        pe = ProcessExpectation()
        assert pe.type == ""
        assert pe.min_rate == 0.0
        assert pe.applicable_when == ""

    def test_rubric_gate_defaults(self) -> None:
        """RubricGate defaults to empty metric and threshold=0.0."""
        gate = RubricGate()
        assert gate.metric == ""
        assert gate.threshold == 0.0

    def test_rubric_signal_defaults(self) -> None:
        """RubricSignal defaults to empty metric and both thresholds=0.0."""
        sig = RubricSignal()
        assert sig.metric == ""
        assert sig.threshold_warn == 0.0
        assert sig.threshold_fail == 0.0

    def test_rubric_defaults(self) -> None:
        """Rubric defaults to empty hard_gates and soft_signals lists."""
        rubric = Rubric()
        assert rubric.hard_gates == []
        assert rubric.soft_signals == []

    def test_ground_truth_case_defaults(self) -> None:
        """GroundTruthCase defaults to empty fields and a default Rubric."""
        case = GroundTruthCase()
        assert case.decision_key == ""
        assert case.capability == ""
        assert case.layer == ""
        assert case.slice_id == ""
        assert case.iteration == 0
        assert case.input_fingerprint == {}
        assert case.expected == {}
        assert case.process_expectations == []
        assert isinstance(case.rubric, Rubric)
        assert case.rubric.hard_gates == []

    def test_planner_ground_truth_defaults(self) -> None:
        """PlannerGroundTruth defaults to empty meta and empty cases list."""
        gt = PlannerGroundTruth()
        assert isinstance(gt.meta, GroundTruthMeta)
        assert gt.meta.spec_id == ""
        assert gt.cases == []


class TestLoadGroundTruthJSON:
    """Test load_ground_truth from JSON files."""

    def test_load_from_json_minimal(self, tmp_path: Path) -> None:
        """Loading a minimal JSON file produces a valid PlannerGroundTruth."""
        data = _make_gt_dict()
        path = tmp_path / "gt.json"
        _write_json(path, data)

        gt = load_ground_truth(path)
        assert gt.meta.spec_id == "test_spec"
        assert gt.meta.gt_version == 1
        assert gt.cases == []

    def test_load_from_json_with_cases(self, tmp_path: Path) -> None:
        """Loading JSON with cases deserializes all case fields correctly."""
        case_dict = _make_case_dict()
        data = _make_gt_dict(cases=[case_dict])
        path = tmp_path / "gt.json"
        _write_json(path, data)

        gt = load_ground_truth(path)
        assert len(gt.cases) == 1
        case = gt.cases[0]
        assert case.decision_key == "l1:PLAN:LIB-01:0:abcd1234"
        assert case.capability == "PLAN"
        assert case.layer == "l1"
        assert case.slice_id == "LIB-01"
        assert case.iteration == 0
        assert case.input_fingerprint == {"gaps_hash": "sha256:aaa"}
        assert "must_include" in case.expected

    def test_load_from_json_file_not_found(self, tmp_path: Path) -> None:
        """load_ground_truth raises FileNotFoundError for missing file."""
        path = tmp_path / "nonexistent.json"
        with pytest.raises(FileNotFoundError, match="not found"):
            load_ground_truth(path)

    def test_load_from_json_bad_content(self, tmp_path: Path) -> None:
        """load_ground_truth raises ValueError for invalid JSON."""
        path = tmp_path / "bad.json"
        path.write_text("not valid json {{{", encoding="utf-8")
        with pytest.raises(ValueError, match="Failed to parse"):
            load_ground_truth(path)

    def test_load_from_json_non_dict_root(self, tmp_path: Path) -> None:
        """load_ground_truth raises ValueError when root is a list."""
        path = tmp_path / "list.json"
        path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        with pytest.raises(ValueError, match="must contain a mapping"):
            load_ground_truth(path)


class TestLoadGroundTruthYAML:
    """Test load_ground_truth from YAML files (when pyyaml is available)."""

    def test_load_from_yaml(self, tmp_path: Path) -> None:
        """Loading a YAML file with cases works end-to-end."""
        yaml = pytest.importorskip("yaml")
        case_dict = _make_case_dict(capability="GAP", layer="l2")
        data = _make_gt_dict(spec_id="yaml_spec", cases=[case_dict])
        path = tmp_path / "gt.yaml"
        path.write_text(
            yaml.dump(data, default_flow_style=False), encoding="utf-8"
        )

        gt = load_ground_truth(path)
        assert gt.meta.spec_id == "yaml_spec"
        assert len(gt.cases) == 1
        assert gt.cases[0].capability == "GAP"
        assert gt.cases[0].layer == "l2"


class TestSaveGroundTruth:
    """Test save_ground_truth serialization."""

    def test_save_to_json(self, tmp_path: Path) -> None:
        """save_ground_truth writes valid JSON that is readable."""
        gt = PlannerGroundTruth(
            meta=GroundTruthMeta(spec_id="save_test", gt_version=1),
            cases=[
                GroundTruthCase(
                    decision_key="l1:PLAN:LIB-01:0:aaaa",
                    capability="PLAN",
                    layer="l1",
                    slice_id="LIB-01",
                )
            ],
        )
        path = tmp_path / "output.json"
        save_ground_truth(gt, path)

        assert path.exists()
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["meta"]["spec_id"] == "save_test"
        assert len(raw["cases"]) == 1
        assert raw["cases"][0]["decision_key"] == "l1:PLAN:LIB-01:0:aaaa"

    def test_save_roundtrip_json(self, tmp_path: Path) -> None:
        """save then load produces an equivalent PlannerGroundTruth."""
        original = PlannerGroundTruth(
            meta=GroundTruthMeta(
                spec_id="roundtrip",
                gt_version=2,
                created_at="2026-02-11",
                notes="roundtrip test",
            ),
            cases=[
                GroundTruthCase(
                    decision_key="l2:GAP:COMP-01:1:bbbb",
                    capability="GAP",
                    layer="l2",
                    slice_id="COMP-01",
                    iteration=1,
                    input_fingerprint={"spec_hash": "sha256:bbb"},
                    expected={"must_include": [], "must_not_include": []},
                    process_expectations=[
                        ProcessExpectation(type="evidence_first", min_rate=0.8)
                    ],
                    rubric=Rubric(
                        hard_gates=[RubricGate(metric="must_include_recall", threshold=0.9)],
                        soft_signals=[
                            RubricSignal(
                                metric="actionability",
                                threshold_warn=0.6,
                                threshold_fail=0.3,
                            )
                        ],
                    ),
                )
            ],
        )
        path = tmp_path / "roundtrip.json"
        save_ground_truth(original, path)

        loaded = load_ground_truth(path)
        assert loaded.meta.spec_id == "roundtrip"
        assert loaded.meta.gt_version == 2
        assert loaded.meta.notes == "roundtrip test"
        assert len(loaded.cases) == 1

        case = loaded.cases[0]
        assert case.decision_key == "l2:GAP:COMP-01:1:bbbb"
        assert case.capability == "GAP"
        assert case.iteration == 1
        assert len(case.process_expectations) == 1
        assert case.process_expectations[0].type == "evidence_first"
        assert case.process_expectations[0].min_rate == 0.8
        assert len(case.rubric.hard_gates) == 1
        assert case.rubric.hard_gates[0].metric == "must_include_recall"
        assert case.rubric.hard_gates[0].threshold == 0.9
        assert len(case.rubric.soft_signals) == 1
        assert case.rubric.soft_signals[0].metric == "actionability"
        assert case.rubric.soft_signals[0].threshold_warn == 0.6

    def test_save_creates_parent_directories(self, tmp_path: Path) -> None:
        """save_ground_truth creates intermediate directories."""
        gt = PlannerGroundTruth()
        path = tmp_path / "nested" / "deep" / "gt.json"
        save_ground_truth(gt, path)
        assert path.exists()


class TestFindCase:
    """Test find_case lookup."""

    def _make_gt_with_cases(self) -> PlannerGroundTruth:
        return PlannerGroundTruth(
            cases=[
                GroundTruthCase(decision_key="l1:PLAN:LIB-01:0:aaaa", capability="PLAN"),
                GroundTruthCase(decision_key="l2:GAP:COMP-01:0:bbbb", capability="GAP"),
                GroundTruthCase(decision_key="l3:PLAN:FILE-01:0:cccc", capability="PLAN"),
            ]
        )

    def test_find_case_returns_match(self) -> None:
        """find_case returns the matching GroundTruthCase."""
        gt = self._make_gt_with_cases()
        result = find_case(gt, "l2:GAP:COMP-01:0:bbbb")
        assert result is not None
        assert result.capability == "GAP"
        assert result.decision_key == "l2:GAP:COMP-01:0:bbbb"

    def test_find_case_returns_none_for_missing(self) -> None:
        """find_case returns None when decision_key is not present."""
        gt = self._make_gt_with_cases()
        result = find_case(gt, "l1:UNKNOWN:X:0:zzzz")
        assert result is None

    def test_find_case_empty_cases(self) -> None:
        """find_case returns None when cases list is empty."""
        gt = PlannerGroundTruth()
        assert find_case(gt, "anything") is None


class TestFindCasesByCapability:
    """Test find_cases_by_capability filtering."""

    def _make_gt_with_cases(self) -> PlannerGroundTruth:
        return PlannerGroundTruth(
            cases=[
                GroundTruthCase(decision_key="k1", capability="PLAN"),
                GroundTruthCase(decision_key="k2", capability="GAP"),
                GroundTruthCase(decision_key="k3", capability="PLAN"),
                GroundTruthCase(decision_key="k4", capability="UNDER_SPEC"),
            ]
        )

    def test_find_cases_by_capability_returns_matches(self) -> None:
        """find_cases_by_capability returns all cases with matching capability."""
        gt = self._make_gt_with_cases()
        results = find_cases_by_capability(gt, "PLAN")
        assert len(results) == 2
        assert all(c.capability == "PLAN" for c in results)

    def test_find_cases_by_capability_single_match(self) -> None:
        """find_cases_by_capability returns single-item list for unique capability."""
        gt = self._make_gt_with_cases()
        results = find_cases_by_capability(gt, "UNDER_SPEC")
        assert len(results) == 1
        assert results[0].decision_key == "k4"

    def test_find_cases_by_capability_no_match(self) -> None:
        """find_cases_by_capability returns empty list for unknown capability."""
        gt = self._make_gt_with_cases()
        results = find_cases_by_capability(gt, "NONEXISTENT")
        assert results == []

    def test_find_cases_by_capability_empty_gt(self) -> None:
        """find_cases_by_capability returns empty for GT with no cases."""
        gt = PlannerGroundTruth()
        assert find_cases_by_capability(gt, "PLAN") == []


class TestGroundTruthFullCase:
    """Test a fully populated ground-truth case with all nested structures."""

    def test_full_case_all_fields(self, tmp_path: Path) -> None:
        """A case with rubric, process_expectations, and all fields roundtrips."""
        case_dict: dict[str, Any] = {
            "decision_key": "l1:RESOLVE_SIGNAL:LIB-02:3:deadbeef",
            "capability": "RESOLVE_SIGNAL",
            "layer": "l1",
            "slice_id": "LIB-02",
            "iteration": 3,
            "input_fingerprint": {
                "signal_hash": "sha256:111",
                "context_hash": "sha256:222",
            },
            "expected": {
                "must_include": [
                    {
                        "id": "fn:validate_transaction",
                        "match": {"function_name_any_of": ["validate_transaction"]},
                    },
                    {
                        "id": "fn:log_error",
                        "match": {"function_name_regex": "log_.*"},
                    },
                ],
                "must_not_include": [
                    {"id": "fn:deprecated_handler", "match": {"function_name_any_of": ["deprecated_handler"]}},
                ],
                "invariants": [
                    {"type": "schema", "rule": "l1_resolve_signal_v1"},
                    {"type": "dedupe", "rule": "no_dup_fns", "key_fields": ["name"], "max_duplicates": 0},
                ],
            },
            "process_expectations": [
                {"type": "evidence_first", "min_rate": 0.9, "applicable_when": "layer=l1"},
                {"type": "no_hallucination", "min_rate": 1.0},
            ],
            "rubric": {
                "hard_gates": [
                    {"metric": "must_include_recall", "threshold": 0.95},
                    {"metric": "invariant_pass_rate", "threshold": 1.0},
                ],
                "soft_signals": [
                    {"metric": "actionability", "threshold_warn": 0.7, "threshold_fail": 0.4},
                    {"metric": "conciseness", "threshold_warn": 0.5, "threshold_fail": 0.2},
                ],
            },
        }
        data = _make_gt_dict(spec_id="full_test", cases=[case_dict])
        path = tmp_path / "full.json"
        _write_json(path, data)

        gt = load_ground_truth(path)
        assert len(gt.cases) == 1
        case = gt.cases[0]

        # Top-level fields
        assert case.decision_key == "l1:RESOLVE_SIGNAL:LIB-02:3:deadbeef"
        assert case.capability == "RESOLVE_SIGNAL"
        assert case.iteration == 3
        assert len(case.input_fingerprint) == 2

        # Process expectations
        assert len(case.process_expectations) == 2
        assert case.process_expectations[0].type == "evidence_first"
        assert case.process_expectations[0].min_rate == 0.9
        assert case.process_expectations[0].applicable_when == "layer=l1"
        assert case.process_expectations[1].type == "no_hallucination"
        assert case.process_expectations[1].min_rate == 1.0

        # Rubric hard gates
        assert len(case.rubric.hard_gates) == 2
        assert case.rubric.hard_gates[0].metric == "must_include_recall"
        assert case.rubric.hard_gates[0].threshold == 0.95
        assert case.rubric.hard_gates[1].metric == "invariant_pass_rate"

        # Rubric soft signals
        assert len(case.rubric.soft_signals) == 2
        assert case.rubric.soft_signals[0].metric == "actionability"
        assert case.rubric.soft_signals[0].threshold_warn == 0.7
        assert case.rubric.soft_signals[0].threshold_fail == 0.4

    def test_rubric_parsing_from_dict(self) -> None:
        """Rubric gate and signal values are parsed to correct numeric types."""
        gate = RubricGate(metric="recall", threshold=0.85)
        assert isinstance(gate.threshold, float)
        assert gate.threshold == 0.85

        signal = RubricSignal(metric="precision", threshold_warn=0.6, threshold_fail=0.3)
        assert isinstance(signal.threshold_warn, float)
        assert isinstance(signal.threshold_fail, float)

    def test_gt_with_empty_cases_list(self, tmp_path: Path) -> None:
        """Loading GT with an explicit empty cases list produces empty cases."""
        data = {"meta": {"spec_id": "empty"}, "cases": []}
        path = tmp_path / "empty.json"
        _write_json(path, data)

        gt = load_ground_truth(path)
        assert gt.meta.spec_id == "empty"
        assert gt.cases == []

    def test_gt_with_no_cases_key(self, tmp_path: Path) -> None:
        """Loading GT with no 'cases' key defaults to empty list."""
        data = {"meta": {"spec_id": "no_cases"}}
        path = tmp_path / "no_cases.json"
        _write_json(path, data)

        gt = load_ground_truth(path)
        assert gt.cases == []


# =======================================================================
# Module 2: trace_loader
# =======================================================================


def _make_trace_index_entry(
    *,
    trace_id: str = "trace-001",
    run_id: str = "run-A",
    slice_id: str = "LIB-01",
    layer: str = "l1",
    capability: str = "PLAN",
    status: str = "OK",
    overridden: bool = False,
    model_calls_count: int = 2,
    tool_calls_count: int = 1,
) -> dict[str, Any]:
    """Build a single index.jsonl row dictionary."""
    return {
        "trace_id": trace_id,
        "timestamp": "2026-02-11T10:00:00Z",
        "run_id": run_id,
        "model_id": "opus",
        "slice_id": slice_id,
        "layer": layer,
        "capability": capability,
        "decision_key": f"{layer}:{capability}:{slice_id}:0:abcd1234",
        "status": status,
        "overridden": overridden,
        "model_calls_count": model_calls_count,
        "tool_calls_count": tool_calls_count,
    }


def _setup_trace_on_disk(
    workspace: Path,
    trace_id: str,
    *,
    decision_key: str = "l1:PLAN:LIB-01:0:abcd1234",
    status: str = "OK",
    overridden: bool = False,
    num_model_calls: int = 1,
    num_tool_calls: int = 0,
    artifacts: dict[str, Any] | None = None,
) -> Path:
    """Create a full trace directory structure on disk."""
    traces_dir = workspace / "analysis" / "planner_traces"
    trace_dir = traces_dir / trace_id
    trace_dir.mkdir(parents=True, exist_ok=True)

    # request.json
    _write_json(trace_dir / "request.json", {"slice_id": "LIB-01", "layer": "l1"})

    # decision.json
    _write_json(
        trace_dir / "decision.json",
        {
            "decision_key": decision_key,
            "status": status,
            "overridden": overridden,
            "decision_text": "promote",
        },
    )

    # calls/
    calls_dir = trace_dir / "calls"
    calls_dir.mkdir(parents=True, exist_ok=True)
    model_rows = [
        {"agent_name": f"agent_{i}", "model": "opus", "duration_ms": 100 + i}
        for i in range(num_model_calls)
    ]
    _write_jsonl(calls_dir / "model_calls.jsonl", model_rows)

    tool_rows = [
        {"tool_name": f"tool_{i}", "duration_ms": 50 + i}
        for i in range(num_tool_calls)
    ]
    _write_jsonl(calls_dir / "tool_calls.jsonl", tool_rows)

    # artifacts/
    if artifacts:
        art_dir = trace_dir / "artifacts"
        art_dir.mkdir(parents=True, exist_ok=True)
        for name, content in artifacts.items():
            _write_json(art_dir / f"{name}.json", content)

    return trace_dir


class TestTraceEntryDefaults:
    """Test TraceEntry dataclass defaults."""

    def test_trace_entry_defaults(self) -> None:
        """TraceEntry defaults to empty strings, False, and 0."""
        entry = TraceEntry()
        assert entry.trace_id == ""
        assert entry.timestamp == ""
        assert entry.run_id == ""
        assert entry.model_id == ""
        assert entry.slice_id == ""
        assert entry.layer == ""
        assert entry.capability == ""
        assert entry.decision_key == ""
        assert entry.status == ""
        assert entry.overridden is False
        assert entry.model_calls_count == 0
        assert entry.tool_calls_count == 0

    def test_trace_entry_with_values(self) -> None:
        """TraceEntry correctly stores provided values."""
        entry = TraceEntry(
            trace_id="t-42",
            run_id="run-X",
            layer="l2",
            capability="GAP",
            status="ERROR",
            overridden=True,
            model_calls_count=5,
        )
        assert entry.trace_id == "t-42"
        assert entry.run_id == "run-X"
        assert entry.layer == "l2"
        assert entry.overridden is True
        assert entry.model_calls_count == 5


class TestLoadedTraceDefaults:
    """Test LoadedTrace dataclass defaults."""

    def test_loaded_trace_defaults(self) -> None:
        """LoadedTrace defaults to empty dicts/lists and False."""
        trace = LoadedTrace()
        assert trace.trace_id == ""
        assert trace.decision_key == ""
        assert trace.request == {}
        assert trace.decision == {}
        assert trace.model_calls == []
        assert trace.tool_calls == []
        assert trace.artifacts == {}
        assert trace.status == ""
        assert trace.overridden is False

    def test_loaded_trace_with_values(self) -> None:
        """LoadedTrace correctly stores provided values."""
        trace = LoadedTrace(
            trace_id="lt-1",
            decision_key="l1:PLAN:X:0:1234",
            request={"slice": "X"},
            decision={"text": "ok"},
            model_calls=[{"agent": "a"}],
            tool_calls=[{"tool": "t"}],
            artifacts={"graph": {"nodes": []}},
            status="OK",
            overridden=True,
        )
        assert trace.trace_id == "lt-1"
        assert trace.artifacts["graph"]["nodes"] == []
        assert trace.overridden is True


class TestLoadIndex:
    """Test load_index reading index.jsonl from disk."""

    def test_load_index_missing_file(self, tmp_path: Path) -> None:
        """load_index returns empty list when index.jsonl does not exist."""
        entries = load_index(tmp_path)
        assert entries == []

    def test_load_index_valid_jsonl(self, tmp_path: Path) -> None:
        """load_index parses valid JSONL rows into TraceEntry objects."""
        index_path = tmp_path / "analysis" / "planner_traces" / "index.jsonl"
        rows = [
            _make_trace_index_entry(trace_id="t1", run_id="run-A", capability="PLAN"),
            _make_trace_index_entry(trace_id="t2", run_id="run-A", capability="GAP"),
            _make_trace_index_entry(trace_id="t3", run_id="run-B", capability="PLAN"),
        ]
        _write_jsonl(index_path, rows)

        entries = load_index(tmp_path)
        assert len(entries) == 3
        assert entries[0].trace_id == "t1"
        assert entries[0].run_id == "run-A"
        assert entries[0].capability == "PLAN"
        assert entries[1].trace_id == "t2"
        assert entries[2].run_id == "run-B"

    def test_load_index_skips_malformed_lines(self, tmp_path: Path) -> None:
        """load_index skips lines that are not valid JSON or not dicts."""
        index_path = tmp_path / "analysis" / "planner_traces" / "index.jsonl"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        valid = json.dumps(_make_trace_index_entry(trace_id="good"))
        lines = [
            valid,
            "this is not json",
            json.dumps([1, 2, 3]),  # non-dict
            "",  # empty line
            valid.replace("good", "also_good"),
        ]
        index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        entries = load_index(tmp_path)
        assert len(entries) == 2
        assert entries[0].trace_id == "good"
        assert entries[1].trace_id == "also_good"

    def test_load_index_empty_file(self, tmp_path: Path) -> None:
        """load_index returns empty list for an empty file."""
        index_path = tmp_path / "analysis" / "planner_traces" / "index.jsonl"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text("", encoding="utf-8")

        entries = load_index(tmp_path)
        assert entries == []


class TestLoadTrace:
    """Test load_trace reading full trace from disk."""

    def test_load_trace_all_files(self, tmp_path: Path) -> None:
        """load_trace reads request, decision, calls, and artifacts."""
        _setup_trace_on_disk(
            tmp_path,
            "trace-full",
            decision_key="l1:PLAN:LIB-01:0:aaaa",
            status="OK",
            num_model_calls=2,
            num_tool_calls=1,
            artifacts={"plan_output": {"steps": ["a", "b"]}},
        )

        trace = load_trace(tmp_path, "trace-full")
        assert trace.trace_id == "trace-full"
        assert trace.decision_key == "l1:PLAN:LIB-01:0:aaaa"
        assert trace.status == "OK"
        assert trace.overridden is False
        assert trace.request["slice_id"] == "LIB-01"
        assert trace.decision["decision_text"] == "promote"
        assert len(trace.model_calls) == 2
        assert trace.model_calls[0]["agent_name"] == "agent_0"
        assert len(trace.tool_calls) == 1
        assert "plan_output" in trace.artifacts
        assert trace.artifacts["plan_output"]["steps"] == ["a", "b"]

    def test_load_trace_missing_directory(self, tmp_path: Path) -> None:
        """load_trace raises FileNotFoundError when trace dir is missing."""
        with pytest.raises(FileNotFoundError, match="Trace directory not found"):
            load_trace(tmp_path, "nonexistent-trace")

    def test_load_trace_no_artifacts_dir(self, tmp_path: Path) -> None:
        """load_trace works when there is no artifacts/ subdirectory."""
        _setup_trace_on_disk(tmp_path, "trace-no-art", artifacts=None)

        trace = load_trace(tmp_path, "trace-no-art")
        assert trace.artifacts == {}

    def test_load_trace_multiple_artifacts(self, tmp_path: Path) -> None:
        """load_trace loads all .json files from artifacts/ directory."""
        _setup_trace_on_disk(
            tmp_path,
            "trace-multi-art",
            artifacts={
                "graph": {"nodes": ["n1"]},
                "metrics": {"coverage": 0.85},
                "gaps": {"items": []},
            },
        )

        trace = load_trace(tmp_path, "trace-multi-art")
        assert len(trace.artifacts) == 3
        assert "graph" in trace.artifacts
        assert "metrics" in trace.artifacts
        assert "gaps" in trace.artifacts
        assert trace.artifacts["metrics"]["coverage"] == 0.85

    def test_load_trace_overridden_flag(self, tmp_path: Path) -> None:
        """load_trace correctly reads the overridden flag from decision.json."""
        _setup_trace_on_disk(tmp_path, "trace-ovr", overridden=True)

        trace = load_trace(tmp_path, "trace-ovr")
        assert trace.overridden is True


class TestFilterTraces:
    """Test filter_traces filtering logic."""

    @pytest.fixture()
    def sample_entries(self) -> list[TraceEntry]:
        """Create a diverse set of trace entries for filtering tests."""
        return [
            TraceEntry(trace_id="t1", run_id="run-A", slice_id="LIB-01", layer="l1", capability="PLAN"),
            TraceEntry(trace_id="t2", run_id="run-A", slice_id="LIB-02", layer="l1", capability="GAP"),
            TraceEntry(trace_id="t3", run_id="run-B", slice_id="COMP-01", layer="l2", capability="PLAN"),
            TraceEntry(trace_id="t4", run_id="run-B", slice_id="FILE-01", layer="l3", capability="UNDER_SPEC"),
            TraceEntry(trace_id="t5", run_id="run-A", slice_id="LIB-01", layer="l1", capability="PLAN"),
        ]

    def test_filter_by_run_id(self, sample_entries: list[TraceEntry]) -> None:
        """filter_traces with run_id keeps only matching entries."""
        result = filter_traces(sample_entries, run_id="run-A")
        assert len(result) == 3
        assert all(e.run_id == "run-A" for e in result)

    def test_filter_by_capability(self, sample_entries: list[TraceEntry]) -> None:
        """filter_traces with capability keeps only matching entries."""
        result = filter_traces(sample_entries, capability="PLAN")
        assert len(result) == 3
        assert all(e.capability == "PLAN" for e in result)

    def test_filter_by_layer(self, sample_entries: list[TraceEntry]) -> None:
        """filter_traces with layer keeps only matching entries."""
        result = filter_traces(sample_entries, layer="l2")
        assert len(result) == 1
        assert result[0].trace_id == "t3"

    def test_filter_by_multiple_criteria(self, sample_entries: list[TraceEntry]) -> None:
        """filter_traces with multiple criteria ANDs them together."""
        result = filter_traces(sample_entries, run_id="run-A", capability="PLAN")
        assert len(result) == 2
        assert all(e.run_id == "run-A" and e.capability == "PLAN" for e in result)

    def test_filter_with_no_criteria_returns_all(self, sample_entries: list[TraceEntry]) -> None:
        """filter_traces with no criteria returns all entries."""
        result = filter_traces(sample_entries)
        assert len(result) == 5

    def test_filter_no_match(self, sample_entries: list[TraceEntry]) -> None:
        """filter_traces with non-matching criteria returns empty list."""
        result = filter_traces(sample_entries, run_id="run-NONEXISTENT")
        assert result == []

    def test_filter_by_slice_id(self, sample_entries: list[TraceEntry]) -> None:
        """filter_traces with slice_id keeps only matching entries."""
        result = filter_traces(sample_entries, slice_id="LIB-01")
        assert len(result) == 2
        assert all(e.slice_id == "LIB-01" for e in result)

    def test_filter_all_criteria_combined(self, sample_entries: list[TraceEntry]) -> None:
        """filter_traces with all four criteria narrows to one entry."""
        result = filter_traces(
            sample_entries,
            run_id="run-B",
            slice_id="COMP-01",
            layer="l2",
            capability="PLAN",
        )
        assert len(result) == 1
        assert result[0].trace_id == "t3"


class TestLoadTracesForRun:
    """Test load_traces_for_run convenience function."""

    def test_load_traces_for_run_integrates(self, tmp_path: Path) -> None:
        """load_traces_for_run reads index, filters, and loads traces."""
        # Set up two traces on disk
        _setup_trace_on_disk(
            tmp_path, "t-a1",
            decision_key="l1:PLAN:LIB-01:0:aaaa",
        )
        _setup_trace_on_disk(
            tmp_path, "t-a2",
            decision_key="l1:GAP:LIB-02:0:bbbb",
        )
        _setup_trace_on_disk(
            tmp_path, "t-b1",
            decision_key="l2:PLAN:COMP-01:0:cccc",
        )

        # Write index
        index_path = tmp_path / "analysis" / "planner_traces" / "index.jsonl"
        rows = [
            _make_trace_index_entry(trace_id="t-a1", run_id="run-A"),
            _make_trace_index_entry(trace_id="t-a2", run_id="run-A"),
            _make_trace_index_entry(trace_id="t-b1", run_id="run-B"),
        ]
        _write_jsonl(index_path, rows)

        traces = load_traces_for_run(tmp_path, "run-A")
        assert len(traces) == 2
        trace_ids = {t.trace_id for t in traces}
        assert trace_ids == {"t-a1", "t-a2"}

    def test_load_traces_for_run_skips_missing(self, tmp_path: Path) -> None:
        """load_traces_for_run skips traces whose directories are missing."""
        # Only create one trace on disk, but index references two
        _setup_trace_on_disk(tmp_path, "t-exists")
        index_path = tmp_path / "analysis" / "planner_traces" / "index.jsonl"
        rows = [
            _make_trace_index_entry(trace_id="t-exists", run_id="run-X"),
            _make_trace_index_entry(trace_id="t-gone", run_id="run-X"),
        ]
        _write_jsonl(index_path, rows)

        traces = load_traces_for_run(tmp_path, "run-X")
        assert len(traces) == 1
        assert traces[0].trace_id == "t-exists"

    def test_load_traces_for_run_empty(self, tmp_path: Path) -> None:
        """load_traces_for_run returns empty when no traces match."""
        index_path = tmp_path / "analysis" / "planner_traces" / "index.jsonl"
        rows = [_make_trace_index_entry(trace_id="t1", run_id="run-OTHER")]
        _write_jsonl(index_path, rows)

        traces = load_traces_for_run(tmp_path, "run-MISSING")
        assert traces == []


class TestTraceStats:
    """Test trace_stats aggregation."""

    def test_trace_stats_empty(self) -> None:
        """trace_stats with empty list returns zero counts."""
        stats = trace_stats([])
        assert stats["total_traces"] == 0
        assert stats["by_capability"] == {}
        assert stats["by_layer"] == {}
        assert stats["by_status"] == {}
        assert stats["model_calls_total"] == 0
        assert stats["tool_calls_total"] == 0
        assert stats["error_count"] == 0
        assert stats["overridden_count"] == 0

    def test_trace_stats_single_ok(self) -> None:
        """trace_stats for a single OK trace counts correctly."""
        trace = LoadedTrace(
            trace_id="t1",
            decision_key="l1:PLAN:LIB-01:0:aaaa",
            model_calls=[{"agent": "a1"}, {"agent": "a2"}],
            tool_calls=[{"tool": "t1"}],
            status="OK",
            overridden=False,
        )
        stats = trace_stats([trace])
        assert stats["total_traces"] == 1
        assert stats["by_capability"] == {"PLAN": 1}
        assert stats["by_layer"] == {"l1": 1}
        assert stats["by_status"] == {"OK": 1}
        assert stats["model_calls_total"] == 2
        assert stats["tool_calls_total"] == 1
        assert stats["error_count"] == 0
        assert stats["overridden_count"] == 0

    def test_trace_stats_mixed_statuses(self) -> None:
        """trace_stats correctly counts errors, overrides, and capabilities."""
        traces = [
            LoadedTrace(
                trace_id="t1",
                decision_key="l1:PLAN:LIB-01:0:aaaa",
                model_calls=[{"a": 1}],
                tool_calls=[],
                status="OK",
                overridden=False,
            ),
            LoadedTrace(
                trace_id="t2",
                decision_key="l2:GAP:COMP-01:0:bbbb",
                model_calls=[{"a": 1}, {"a": 2}, {"a": 3}],
                tool_calls=[{"t": 1}],
                status="ERROR",
                overridden=False,
            ),
            LoadedTrace(
                trace_id="t3",
                decision_key="l1:PLAN:LIB-02:0:cccc",
                model_calls=[],
                tool_calls=[{"t": 1}, {"t": 2}],
                status="OK",
                overridden=True,
            ),
            LoadedTrace(
                trace_id="t4",
                decision_key="l3:UNDER_SPEC:FILE-01:0:dddd",
                model_calls=[{"a": 1}],
                tool_calls=[],
                status="TIMEOUT",
                overridden=True,
            ),
        ]
        stats = trace_stats(traces)

        assert stats["total_traces"] == 4

        # by_capability
        assert stats["by_capability"]["PLAN"] == 2
        assert stats["by_capability"]["GAP"] == 1
        assert stats["by_capability"]["UNDER_SPEC"] == 1

        # by_layer
        assert stats["by_layer"]["l1"] == 2
        assert stats["by_layer"]["l2"] == 1
        assert stats["by_layer"]["l3"] == 1

        # by_status
        assert stats["by_status"]["OK"] == 2
        assert stats["by_status"]["ERROR"] == 1
        assert stats["by_status"]["TIMEOUT"] == 1

        # Totals
        assert stats["model_calls_total"] == 5  # 1+3+0+1
        assert stats["tool_calls_total"] == 3   # 0+1+2+0
        assert stats["error_count"] == 2         # ERROR + TIMEOUT
        assert stats["overridden_count"] == 2    # t3 + t4

    def test_trace_stats_empty_decision_key(self) -> None:
        """trace_stats handles traces with empty decision_key gracefully."""
        trace = LoadedTrace(
            trace_id="t-empty",
            decision_key="",
            model_calls=[],
            tool_calls=[],
            status="OK",
        )
        stats = trace_stats([trace])
        assert stats["total_traces"] == 1
        # With empty key, parts is empty, so capability and layer are "unknown"
        assert stats["by_capability"] == {"unknown": 1}
        assert stats["by_layer"] == {"unknown": 1}

    def test_trace_stats_all_keys_present(self) -> None:
        """trace_stats returns all expected keys even for a single trace."""
        stats = trace_stats([
            LoadedTrace(
                trace_id="t1",
                decision_key="l1:PLAN:X:0:hash",
                status="OK",
            ),
        ])
        expected_keys = {
            "total_traces",
            "by_capability",
            "by_layer",
            "by_status",
            "model_calls_total",
            "tool_calls_total",
            "error_count",
            "overridden_count",
        }
        assert set(stats.keys()) == expected_keys
