"""Tests for test-pin alignment compliance gate."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from spec_manager.compliance.promotion.config import (
    GateId,
    GateMode,
    GateSpec,
)
from spec_manager.compliance.promotion.test_pin_gate import (
    check_test_pin_alignment_gate,
)
from spec_manager.projection.lineage.test_pin_baseline import (
    TestPinBaselineStore,
    TestSignatureBaseline,
    build_baseline,
    save_baseline,
)
from spec_manager.projection.lineage.test_pin_discovery import (
    discover_test_pin_associations,
)
from spec_manager.schemas.pin_functions import PinFunction, PinFunctionRegistry


def _make_registry(
    pin_funcs: list[PinFunction] | None = None,
) -> PinFunctionRegistry:
    return PinFunctionRegistry(
        schema_version="1.0",
        pin_functions=pin_funcs or [],
        import_edges=[],
        created_at="2024-01-01T00:00:00Z",
    )


def _make_pin_func(
    pin_func_id: str = "PFUNC-0001",
    function_name: str = "validate_payment",
) -> PinFunction:
    return PinFunction(
        pin_func_id=pin_func_id,
        function_name=function_name,
        module_path=f"atoms.{function_name}",
        file_path=f"atoms/{function_name}.py",
        line_start=1,
        line_end=10,
        signature=f"def {function_name}()",
        docstring=f"Docstring for {function_name}",
        content_hash="abc123",
    )


def _write_file(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


class TestGatePasses:
    """Test gate passes when no drift is detected."""

    def test_passes_when_no_drift(self, tmp_path: Path) -> None:
        """Gate passes with no drift detected."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        _write_file(
            test_dir,
            "test_payment.py",
            """\
            from atoms.payment import validate_payment

            def test_valid_payment() -> None:
                validate_payment()
            """,
        )
        registry = _make_registry([_make_pin_func()])

        # Create a baseline from the current state
        test_files = list(test_dir.rglob("test_*.py"))
        test_pin_map = discover_test_pin_associations(test_files, registry)
        baseline = build_baseline(test_pin_map)
        baseline_path = tmp_path / ".spec" / "test_pin_baselines.json"
        save_baseline(baseline, baseline_path)

        gate_spec = GateSpec(
            gate_id=GateId.TEST_PIN_ALIGNMENT,
            mode=GateMode.ADVISORY,
        )

        result = check_test_pin_alignment_gate(
            registry, [test_dir], baseline_path, gate_spec
        )

        assert result.passed is True
        assert result.gate_id == "test_pin_alignment"
        assert result.mode == "advisory"
        assert len(result.findings) == 0


class TestGateFails:
    """Test gate fails (advisory warning) when drift is detected."""

    def test_fails_when_test_signatures_drift(self, tmp_path: Path) -> None:
        """Gate fails with advisory warning when signatures drift."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        test_file = _write_file(
            test_dir,
            "test_payment.py",
            """\
            from atoms.payment import validate_payment

            def test_valid_payment() -> None:
                validate_payment()
            """,
        )
        registry = _make_registry([_make_pin_func()])

        # Create baseline
        test_files = list(test_dir.rglob("test_*.py"))
        test_pin_map = discover_test_pin_associations(test_files, registry)
        baseline = build_baseline(test_pin_map)
        baseline_path = tmp_path / ".spec" / "test_pin_baselines.json"
        save_baseline(baseline, baseline_path)

        # Modify the test file to change the signature
        _write_file(
            test_dir,
            "test_payment.py",
            """\
            from atoms.payment import validate_payment

            def test_valid_payment(amount: float) -> bool:
                return validate_payment(amount)
            """,
        )

        gate_spec = GateSpec(
            gate_id=GateId.TEST_PIN_ALIGNMENT,
            mode=GateMode.ADVISORY,
        )

        result = check_test_pin_alignment_gate(
            registry, [test_dir], baseline_path, gate_spec
        )

        assert result.passed is False
        assert result.mode == "advisory"
        assert len(result.findings) >= 1
        # Findings should contain drift details
        drift_finding = result.findings[0]
        assert drift_finding["drift_kind"] == "test_signature_changed"


class TestGateFindings:
    """Test that gate produces findings with proper details."""

    def test_findings_contain_pin_func_id(self, tmp_path: Path) -> None:
        """Findings include test file paths and pin-function IDs."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        _write_file(
            test_dir,
            "test_payment.py",
            """\
            from atoms.payment import validate_payment

            def test_valid_payment() -> None:
                validate_payment()
            """,
        )
        registry = _make_registry([_make_pin_func()])

        # Create baseline
        test_files = list(test_dir.rglob("test_*.py"))
        test_pin_map = discover_test_pin_associations(test_files, registry)
        baseline = build_baseline(test_pin_map)
        baseline_path = tmp_path / ".spec" / "test_pin_baselines.json"
        save_baseline(baseline, baseline_path)

        # Modify signature
        _write_file(
            test_dir,
            "test_payment.py",
            """\
            from atoms.payment import validate_payment

            def test_valid_payment(new_param: str) -> None:
                validate_payment()
            """,
        )

        gate_spec = GateSpec(
            gate_id=GateId.TEST_PIN_ALIGNMENT,
            mode=GateMode.ADVISORY,
        )

        result = check_test_pin_alignment_gate(
            registry, [test_dir], baseline_path, gate_spec
        )

        assert len(result.findings) >= 1
        finding = result.findings[0]
        assert "pin_func_id" in finding
        assert "expected" in finding
        assert "actual" in finding


class TestGateSkipped:
    """Test gate behavior with no registry."""

    def test_no_baseline_no_drift(self, tmp_path: Path) -> None:
        """Gate passes when no baseline exists (nothing to drift from)."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        _write_file(
            test_dir,
            "test_payment.py",
            """\
            from atoms.payment import validate_payment

            def test_valid_payment() -> None:
                validate_payment()
            """,
        )
        registry = _make_registry([_make_pin_func()])
        baseline_path = tmp_path / ".spec" / "test_pin_baselines.json"
        # No baseline file exists

        gate_spec = GateSpec(
            gate_id=GateId.TEST_PIN_ALIGNMENT,
            mode=GateMode.ADVISORY,
        )

        result = check_test_pin_alignment_gate(
            registry, [test_dir], baseline_path, gate_spec
        )

        assert result.passed is True


class TestCoverageThreshold:
    """Test coverage threshold enforcement."""

    def test_fails_when_below_threshold(self, tmp_path: Path) -> None:
        """Gate fails when test coverage is below configured threshold."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        # No test file covers the pin-function
        _write_file(
            test_dir,
            "test_empty.py",
            """\
            def test_nothing():
                pass
            """,
        )
        registry = _make_registry([_make_pin_func()])
        baseline_path = tmp_path / ".spec" / "test_pin_baselines.json"

        gate_spec = GateSpec(
            gate_id=GateId.TEST_PIN_ALIGNMENT,
            mode=GateMode.ADVISORY,
            threshold=0.5,  # Require at least 50% coverage
        )

        result = check_test_pin_alignment_gate(
            registry, [test_dir], baseline_path, gate_spec
        )

        assert result.passed is False
        # Should have a finding about coverage below threshold
        coverage_findings = [
            f for f in result.findings
            if f.get("coverage_below_threshold")
        ]
        assert len(coverage_findings) == 1
