"""Component tests for orchestration.downward_flow.engine module."""

from __future__ import annotations

from pathlib import Path

from spec_manager.orchestration.downward_flow.engine import (
    DownwardFlowEngine,
    FailureEvidence,
    TraceResult,
)


class TestFailureEvidenceDefaults:
    def test_defaults(self) -> None:
        e = FailureEvidence()
        assert e.source == ""
        assert e.failing_files == []
        assert e.failing_lines == []
        assert e.stack_trace == ""
        assert e.gate_results == []
        assert e.review_findings == []
        assert e.evidence_paths == []


class TestTraceResultDefaults:
    def test_defaults(self) -> None:
        t = TraceResult()
        assert t.located_pins == []
        assert t.traced_atoms == []
        assert t.trace_path == []


class TestDownwardFlowEngineTraceAndRoute:
    def test_dispatches_test_failures(self) -> None:
        engine = DownwardFlowEngine(run_id="r1", active_layer="L1")
        evidence = FailureEvidence(
            source="TEST_FAILURE",
            failing_files=["foo.py"],
        )
        batch = engine.trace_and_route(evidence)
        assert len(batch.tickets) == 1
        assert batch.tickets[0].source == "TEST_FAILURE"

    def test_dispatches_gate_failures(self) -> None:
        engine = DownwardFlowEngine(run_id="r1", active_layer="L1")
        evidence = FailureEvidence(
            gate_results=[
                {"gate_id": "G1", "passed": False, "findings": [{"file_path": "a.py"}]},
            ],
        )
        batch = engine.trace_and_route(evidence)
        assert len(batch.tickets) == 1

    def test_dispatches_review_findings(self) -> None:
        engine = DownwardFlowEngine(run_id="r1", active_layer="L1")
        evidence = FailureEvidence(
            review_findings=[
                {"category": "LOGIC", "description": "Bug", "files": ["x.py"]},
            ],
        )
        batch = engine.trace_and_route(evidence)
        assert len(batch.tickets) == 1


class TestDownwardFlowEngineTraceFile:
    def test_no_pin_registry_returns_empty(self) -> None:
        engine = DownwardFlowEngine(run_id="r1", pin_registry=None)
        result = engine._trace_file("/nonexistent/path.py")
        assert result.located_pins == []
        assert result.traced_atoms == []


class TestDownwardFlowEngineScanMarkers:
    def test_finds_pdd_pin_markers(self, tmp_path: Path) -> None:
        f = tmp_path / "service.py"
        f.write_text("# pdd:pin=PIN-ARCH-001\ndef handle(): pass\n# pdd:pin=PIN-ATOM-002\n")
        engine = DownwardFlowEngine()
        pins = engine._scan_markers(str(f))
        assert "PIN-ARCH-001" in pins
        assert "PIN-ATOM-002" in pins

    def test_no_markers_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "plain.py"
        f.write_text("def foo(): pass\n")
        engine = DownwardFlowEngine()
        pins = engine._scan_markers(str(f))
        assert pins == []

    def test_nonexistent_file_returns_empty(self) -> None:
        engine = DownwardFlowEngine()
        pins = engine._scan_markers("/no/such/file.py")
        assert pins == []


class TestDownwardFlowEngineTestFailures:
    def test_sets_origin_layer_and_hop_trace(self) -> None:
        engine = DownwardFlowEngine(run_id="r1", active_layer="L1")
        evidence = FailureEvidence(
            source="TEST_FAILURE",
            failing_files=["foo.py"],
        )
        batch = engine.trace_and_route(evidence)
        ticket = batch.tickets[0]
        assert ticket.origin_layer == "L1"
        assert ticket.hop_trace == ["L1", "L1"]


class TestDownwardFlowEngineReviewFindings:
    def test_enriches_tickets_with_origin(self) -> None:
        engine = DownwardFlowEngine(run_id="r1", active_layer="L2")
        evidence = FailureEvidence(
            review_findings=[
                {"category": "ARCH", "description": "Coupling", "files": ["svc.py"]},
            ],
        )
        batch = engine.trace_and_route(evidence)
        ticket = batch.tickets[0]
        assert ticket.origin_layer == "L2"
        assert "L2" in ticket.hop_trace
