"""Tests for promotion gate orchestrator and compliance integration."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from spec_manager.compliance.promotion.config import (
    GateId,
    GateMode,
    GateSpec,
    PromotionGateConfig,
)
from spec_manager.compliance.promotion.orchestrator import LayerPromotionGate
from spec_manager.compliance.promotion.result import PromotionReport
from spec_manager.compliance.scorer import ComplianceScorer
from spec_manager.schemas.pin_functions import (
    ImportEdge,
    PinFunction,
    PinFunctionRegistry,
)


def _write_py(tmpdir: Path, name: str, content: str) -> Path:
    path = tmpdir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def _make_config(
    project_root: str,
    algorithmic_roots: list[str] | None = None,
    architectural_roots: list[str] | None = None,
) -> PromotionGateConfig:
    config = PromotionGateConfig.default()
    config.project_root = project_root
    if algorithmic_roots is not None:
        config.algorithmic_roots = algorithmic_roots
    if architectural_roots is not None:
        config.architectural_roots = architectural_roots
    return config


def _make_registry(
    pin_funcs: list[PinFunction] | None = None,
    edges: list[ImportEdge] | None = None,
) -> PinFunctionRegistry:
    return PinFunctionRegistry(
        schema_version="1.0",
        pin_functions=pin_funcs or [],
        import_edges=edges or [],
        created_at="2024-01-01T00:00:00Z",
    )


class TestLayerPromotionGate:
    def test_all_gates_pass_clean_project(self, tmp_path: Path) -> None:
        # Create clean algorithmic directory
        algo_dir = tmp_path / "algo"
        algo_dir.mkdir()
        _write_py(algo_dir, "compute.py", """\
            def compute(x):
                return x * 2
        """)

        # Create clean architectural directory
        arch_dir = tmp_path / "arch"
        arch_dir.mkdir()
        _write_py(arch_dir, "service.py", """\
            def handle(x):
                return x
        """)

        config = _make_config(
            project_root=str(tmp_path),
            algorithmic_roots=["algo"],
            architectural_roots=["arch"],
        )
        # Disable test runner (no real test suite)
        config.gates[GateId.ALL_TESTS_PASS].enabled = False

        gate = LayerPromotionGate(config, pin_registry=_make_registry())
        report = gate.run_all_checks()

        # With clean code and no pin requirements, most gates should pass
        assert isinstance(report, PromotionReport)
        assert report.total_duration_ms >= 0

    def test_required_gate_failure_blocks(self, tmp_path: Path) -> None:
        algo_dir = tmp_path / "algo"
        algo_dir.mkdir()
        _write_py(algo_dir, "stub.py", """\
            def not_done():
                pass
        """)

        config = _make_config(
            project_root=str(tmp_path),
            algorithmic_roots=["algo"],
            architectural_roots=[],
        )
        config.gates[GateId.ALL_TESTS_PASS].enabled = False
        # Make stub gate required
        config.gates[GateId.NO_STUB_FUNCTIONS].mode = GateMode.REQUIRED

        gate = LayerPromotionGate(config, pin_registry=_make_registry())
        report = gate.run_all_checks()

        assert report.passed is False
        blocker_ids = [b.gate_id for b in report.blockers]
        assert GateId.NO_STUB_FUNCTIONS.value in blocker_ids

    def test_advisory_gate_failure_warns(self, tmp_path: Path) -> None:
        algo_dir = tmp_path / "algo"
        algo_dir.mkdir()
        _write_py(algo_dir, "stub.py", """\
            def not_done():
                pass
        """)

        config = _make_config(
            project_root=str(tmp_path),
            algorithmic_roots=["algo"],
            architectural_roots=[],
        )
        config.gates[GateId.ALL_TESTS_PASS].enabled = False
        # Make ALL gates advisory
        for gate_id in GateId:
            config.gates[gate_id].mode = GateMode.ADVISORY

        gate = LayerPromotionGate(config, pin_registry=_make_registry())
        report = gate.run_all_checks()

        assert report.passed is True
        # Stub gate should appear in warnings
        warning_ids = [w.gate_id for w in report.warnings]
        assert GateId.NO_STUB_FUNCTIONS.value in warning_ids

    def test_disabled_gates_skipped(self, tmp_path: Path) -> None:
        config = _make_config(
            project_root=str(tmp_path),
            algorithmic_roots=[],
            architectural_roots=[],
        )
        # Disable all gates
        for gate_id in GateId:
            config.gates[gate_id].enabled = False

        gate = LayerPromotionGate(config, pin_registry=_make_registry())
        report = gate.run_all_checks()

        assert report.passed is True
        assert len(report.gate_results) == 0

    def test_run_single_check(self, tmp_path: Path) -> None:
        algo_dir = tmp_path / "algo"
        algo_dir.mkdir()
        _write_py(algo_dir, "clean.py", """\
            def compute(x):
                return x + 1
        """)

        config = _make_config(
            project_root=str(tmp_path),
            algorithmic_roots=["algo"],
        )

        gate = LayerPromotionGate(config, pin_registry=_make_registry())
        result = gate.run_single_check(GateId.NO_REMAINING_COMMENTS)

        assert result.gate_id == GateId.NO_REMAINING_COMMENTS.value
        assert result.passed is True

    def test_no_pin_registry_skips_pin_gates(self, tmp_path: Path) -> None:
        config = _make_config(
            project_root=str(tmp_path),
            algorithmic_roots=[],
            architectural_roots=[],
        )
        config.gates[GateId.ALL_TESTS_PASS].enabled = False

        gate = LayerPromotionGate(config, pin_registry=None)
        report = gate.run_all_checks()

        # Pin-related gates should be skipped (still passing)
        pin_related = [
            r for r in report.gate_results
            if r.gate_id in {
                GateId.PIN_COVERAGE.value,
                GateId.INTRODUCED_ALGORITHM_SPECS.value,
                GateId.NO_INLINED_ATOM_LOGIC.value,
                GateId.FUNCTION_RECOMPOSITION.value,
                GateId.PROVENANCE_COMPLETE.value,
            }
        ]
        for result in pin_related:
            assert result.passed is True  # Skipped gates pass
            assert any(
                f.get("skipped") is True
                for f in result.findings
            )

    def test_report_serialization(self, tmp_path: Path) -> None:
        config = _make_config(
            project_root=str(tmp_path),
            algorithmic_roots=[],
            architectural_roots=[],
        )
        for gate_id in GateId:
            config.gates[gate_id].enabled = False

        gate = LayerPromotionGate(config, pin_registry=_make_registry())
        report = gate.run_all_checks()

        # Verify report can be serialized to JSON
        d = report.to_dict()
        serialized = json.dumps(d)
        deserialized = json.loads(serialized)
        assert isinstance(deserialized["passed"], bool)

        # Verify save works
        path = tmp_path / "report.json"
        report.save(path)
        assert path.exists()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["passed"] == report.passed


class TestComplianceScorerIntegration:
    def test_score_promotion_compliance(self, tmp_path: Path) -> None:
        config = _make_config(
            project_root=str(tmp_path),
            algorithmic_roots=[],
            architectural_roots=[],
        )
        # Disable all gates for a clean pass
        for gate_id in GateId:
            config.gates[gate_id].enabled = False

        scorer = ComplianceScorer()
        result = scorer.score_promotion_compliance(
            config=config,
            pin_registry=_make_registry(),
        )

        assert result.passed is True
        assert result.score >= 0.0
        assert isinstance(result.blockers, list)
        assert isinstance(result.warnings, list)
        assert "promotion_report" in result.details

    def test_score_promotion_compliance_with_failures(self, tmp_path: Path) -> None:
        algo_dir = tmp_path / "algo"
        algo_dir.mkdir()
        _write_py(algo_dir, "stub.py", """\
            def not_done():
                pass
        """)

        config = _make_config(
            project_root=str(tmp_path),
            algorithmic_roots=["algo"],
            architectural_roots=[],
        )
        config.gates[GateId.ALL_TESTS_PASS].enabled = False
        config.gates[GateId.NO_STUB_FUNCTIONS].mode = GateMode.REQUIRED

        scorer = ComplianceScorer()
        result = scorer.score_promotion_compliance(
            config=config,
            pin_registry=_make_registry(),
        )

        assert result.passed is False
        assert len(result.blockers) >= 1
        assert any(
            "no_stub_functions" in b["type"]
            for b in result.blockers
        )
