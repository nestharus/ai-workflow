"""Tests for promotion gate configuration and result types."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from spec_manager.compliance.promotion.config import (
    ALL_PHASES,
    GATE_PHASES,
    GateId,
    GateMode,
    GateSpec,
    PhaseId,
    PromotionGateConfig,
)
from spec_manager.compliance.promotion.result import (
    GateCheckResult,
    PromotionReport,
)


class TestGateMode:
    def test_required_value(self) -> None:
        assert GateMode.REQUIRED.value == "required"

    def test_advisory_value(self) -> None:
        assert GateMode.ADVISORY.value == "advisory"


class TestGateId:
    def test_all_gate_ids_have_unique_values(self) -> None:
        values = [g.value for g in GateId]
        assert len(values) == len(set(values))

    def test_expected_gates_exist(self) -> None:
        expected = {
            "no_remaining_comments",
            "no_stub_functions",
            "all_tests_pass",
            "call_graph_connected",
            "store_monogamy",
            "introduced_algorithm_specs",
            "function_recomposition",
            "no_orphan_components",
            "event_handler_coverage",
            "config_externalization",
            "shape_verifiers_pass",
            "import_boundary_check",
            "shape_drift_resolved",
            "provenance_complete",
            "entity_coverage",
        }
        actual = {g.value for g in GateId}
        assert actual == expected


class TestPhaseIdAndGatePhases:
    def test_all_phases_tuple(self) -> None:
        assert ALL_PHASES == ("libraries", "architecture", "quality")

    def test_every_gate_has_phase_mapping(self) -> None:
        for gate_id in GateId:
            assert gate_id in GATE_PHASES, f"{gate_id} missing from GATE_PHASES"

    def test_all_tests_pass_runs_in_all_phases(self) -> None:
        assert GATE_PHASES[GateId.ALL_TESTS_PASS] == ALL_PHASES

    def test_shape_verifiers_pass_runs_in_all_phases(self) -> None:
        assert GATE_PHASES[GateId.SHAPE_VERIFIERS_PASS] == ALL_PHASES


class TestGateSpec:
    def test_default_values(self) -> None:
        spec = GateSpec(gate_id=GateId.NO_REMAINING_COMMENTS)
        assert spec.mode == GateMode.REQUIRED
        assert spec.threshold == 0.0
        assert spec.enabled is True
        assert spec.params == {}

    def test_custom_values(self) -> None:
        spec = GateSpec(
            gate_id=GateId.SHAPE_VERIFIERS_PASS,
            mode=GateMode.ADVISORY,
            threshold=0.95,
            enabled=False,
            params={"exclude_patterns": ["**/test_*"]},
        )
        assert spec.mode == GateMode.ADVISORY
        assert spec.threshold == 0.95
        assert spec.enabled is False
        assert spec.params == {"exclude_patterns": ["**/test_*"]}


class TestPromotionGateConfig:
    def test_default_creates_all_gates(self) -> None:
        config = PromotionGateConfig.default()
        for gate_id in GateId:
            assert gate_id in config.gates
            assert config.gates[gate_id].gate_id == gate_id

    def test_default_advisory_gates(self) -> None:
        config = PromotionGateConfig.default()
        assert config.gates[GateId.CALL_GRAPH_CONNECTED].mode == GateMode.ADVISORY
        assert config.gates[GateId.NO_STUB_FUNCTIONS].mode == GateMode.ADVISORY
        assert config.gates[GateId.ENTITY_COVERAGE].mode == GateMode.ADVISORY

    def test_default_required_gates(self) -> None:
        config = PromotionGateConfig.default()
        required_gates = [
            GateId.ALL_TESTS_PASS,
            GateId.SHAPE_VERIFIERS_PASS,
            GateId.IMPORT_BOUNDARY_CHECK,
            GateId.SHAPE_DRIFT_RESOLVED,
        ]
        for gate_id in required_gates:
            assert config.gates[gate_id].mode == GateMode.REQUIRED

    def test_get_gate_configured(self) -> None:
        config = PromotionGateConfig()
        spec = GateSpec(gate_id=GateId.SHAPE_VERIFIERS_PASS, threshold=0.9)
        config.gates[GateId.SHAPE_VERIFIERS_PASS] = spec
        result = config.get_gate(GateId.SHAPE_VERIFIERS_PASS)
        assert result.threshold == 0.9

    def test_get_gate_default(self) -> None:
        config = PromotionGateConfig()
        result = config.get_gate(GateId.SHAPE_VERIFIERS_PASS)
        assert result.gate_id == GateId.SHAPE_VERIFIERS_PASS
        assert result.mode == GateMode.REQUIRED
        assert result.threshold == 0.0

    def test_default_roots(self) -> None:
        config = PromotionGateConfig()
        assert "algorithmic/atoms" in config.algorithmic_roots
        assert "architectural/services" in config.architectural_roots


class TestGateCheckResult:
    def test_to_dict(self) -> None:
        result = GateCheckResult(
            gate_id="no_remaining_comments",
            passed=True,
            mode="required",
            score=1.0,
            findings=[],
            summary="No comments found",
            duration_ms=42.5,
        )
        d = result.to_dict()
        assert d["gate_id"] == "no_remaining_comments"
        assert d["passed"] is True
        assert d["mode"] == "required"
        assert d["score"] == 1.0
        assert d["findings"] == []
        assert d["summary"] == "No comments found"
        assert d["duration_ms"] == 42.5

    def test_to_dict_with_findings(self) -> None:
        result = GateCheckResult(
            gate_id="no_stub_functions",
            passed=False,
            mode="required",
            score=0.0,
            findings=[{"file_path": "foo.py", "line": 10, "name": "bar", "stub_type": "pass"}],
            summary="Found 1 stub",
        )
        d = result.to_dict()
        assert len(d["findings"]) == 1
        assert d["findings"][0]["file_path"] == "foo.py"


class TestPromotionReport:
    def test_to_dict(self) -> None:
        result1 = GateCheckResult(gate_id="gate_a", passed=True, mode="required")
        result2 = GateCheckResult(gate_id="gate_b", passed=False, mode="advisory")
        report = PromotionReport(
            passed=True,
            gate_results=[result1, result2],
            blockers=[],
            warnings=[result2],
            total_duration_ms=100.0,
        )
        d = report.to_dict()
        assert d["passed"] is True
        assert len(d["gate_results"]) == 2
        assert len(d["blockers"]) == 0
        assert len(d["warnings"]) == 1
        assert d["total_duration_ms"] == 100.0

    def test_serialization_roundtrip(self) -> None:
        result = GateCheckResult(
            gate_id="test_gate",
            passed=False,
            mode="required",
            score=0.5,
            findings=[{"key": "value"}],
            summary="Test summary",
            duration_ms=10.0,
        )
        report = PromotionReport(
            passed=False,
            gate_results=[result],
            blockers=[result],
            warnings=[],
            total_duration_ms=10.0,
        )
        d = report.to_dict()
        serialized = json.dumps(d)
        deserialized = json.loads(serialized)
        assert deserialized["passed"] is False
        assert len(deserialized["gate_results"]) == 1
        assert deserialized["gate_results"][0]["gate_id"] == "test_gate"
        assert deserialized["gate_results"][0]["score"] == 0.5

    def test_save(self) -> None:
        result = GateCheckResult(gate_id="save_test", passed=True, mode="required")
        report = PromotionReport(
            passed=True,
            gate_results=[result],
            total_duration_ms=5.0,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sub" / "report.json"
            report.save(path)
            assert path.exists()
            loaded = json.loads(path.read_text(encoding="utf-8"))
            assert loaded["passed"] is True
            assert len(loaded["gate_results"]) == 1
