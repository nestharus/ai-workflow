"""Tests for test-pin alignment checker."""

from __future__ import annotations

import textwrap
from pathlib import Path

from spec_manager.projection.lineage.drift_detector import DriftKind
from spec_manager.projection.lineage.test_pin_baseline import (
    build_baseline,
    save_baseline,
)
from spec_manager.projection.lineage.test_pin_checker import (
    check_test_pin_alignment,
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


class TestDriftDetection:
    """Test drift detection when test signatures change."""

    def test_detects_parameter_change(self, tmp_path: Path) -> None:
        """Detects drift when a test function's parameter list changes."""
        # Write initial test file and create baseline
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        test_file = _write_file(
            test_dir,
            "test_payment.py",
            """\
            from atoms.payment import validate_payment

            def test_valid_payment(amount: float) -> bool:
                return validate_payment(amount)
            """,
        )

        registry = _make_registry([_make_pin_func()])
        test_pin_map = discover_test_pin_associations([test_file], registry)
        baseline_store = build_baseline(test_pin_map)

        baseline_path = tmp_path / ".spec" / "test_pin_baselines.json"
        save_baseline(baseline_store, baseline_path)

        # Now modify the test file to change the parameter list
        _write_file(
            test_dir,
            "test_payment.py",
            """\
            from atoms.payment import validate_payment

            def test_valid_payment(amount: float, currency: str) -> bool:
                return validate_payment(amount, currency)
            """,
        )

        result = check_test_pin_alignment(registry, [test_dir], baseline_path)

        assert len(result.drift_items) == 1
        assert result.drift_items[0].drift_kind == DriftKind.TEST_SIGNATURE_CHANGED

    def test_detects_return_annotation_change(self, tmp_path: Path) -> None:
        """Detects drift when a test function's return annotation changes."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        test_file = _write_file(
            test_dir,
            "test_payment.py",
            """\
            from atoms.payment import validate_payment

            def test_valid_payment() -> bool:
                return validate_payment()
            """,
        )

        registry = _make_registry([_make_pin_func()])
        test_pin_map = discover_test_pin_associations([test_file], registry)
        baseline_store = build_baseline(test_pin_map)

        baseline_path = tmp_path / ".spec" / "test_pin_baselines.json"
        save_baseline(baseline_store, baseline_path)

        # Change return annotation
        _write_file(
            test_dir,
            "test_payment.py",
            """\
            from atoms.payment import validate_payment

            def test_valid_payment() -> None:
                validate_payment()
            """,
        )

        result = check_test_pin_alignment(registry, [test_dir], baseline_path)

        assert len(result.drift_items) == 1
        assert result.drift_items[0].drift_kind == DriftKind.TEST_SIGNATURE_CHANGED

    def test_detects_renamed_test_function(self, tmp_path: Path) -> None:
        """Detects drift when a test function is renamed (orphaned baseline)."""
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
        test_pin_map = discover_test_pin_associations([test_file], registry)
        baseline_store = build_baseline(test_pin_map)

        baseline_path = tmp_path / ".spec" / "test_pin_baselines.json"
        save_baseline(baseline_store, baseline_path)

        # Rename the test function
        _write_file(
            test_dir,
            "test_payment.py",
            """\
            from atoms.payment import validate_payment

            def test_payment_validation() -> None:
                validate_payment()
            """,
        )

        result = check_test_pin_alignment(registry, [test_dir], baseline_path)

        # Orphaned baseline entry reports drift
        assert len(result.drift_items) == 1
        assert result.drift_items[0].drift_kind == DriftKind.TEST_SIGNATURE_CHANGED
        assert "missing or renamed" in result.drift_items[0].actual


class TestNoDrift:
    """Test that no drift is reported when signatures match."""

    def test_no_drift_when_signatures_match(self, tmp_path: Path) -> None:
        """No drift when test signatures match baseline."""
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
        test_pin_map = discover_test_pin_associations([test_file], registry)
        baseline_store = build_baseline(test_pin_map)

        baseline_path = tmp_path / ".spec" / "test_pin_baselines.json"
        save_baseline(baseline_store, baseline_path)

        # Run check without modifying the file
        result = check_test_pin_alignment(registry, [test_dir], baseline_path)

        assert len(result.drift_items) == 0


class TestNoBaseline:
    """Test behavior when no baseline file exists."""

    def test_no_baseline_no_drift(self, tmp_path: Path) -> None:
        """No drift reported when no baseline file exists."""
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

        result = check_test_pin_alignment(registry, [test_dir], baseline_path)

        # No baseline means no drift to detect
        assert len(result.drift_items) == 0
        assert result.baseline_updated is False

    def test_creates_baseline_when_update_flag(self, tmp_path: Path) -> None:
        """Creates baseline file when update_baseline=True and no prior baseline."""
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

        result = check_test_pin_alignment(
            registry, [test_dir], baseline_path, update_baseline_flag=True
        )

        assert result.baseline_updated is True
        assert baseline_path.exists()


class TestCoverageStatistics:
    """Test that coverage statistics are computed correctly."""

    def test_coverage_with_all_tested(self, tmp_path: Path) -> None:
        """100% coverage when all pin-functions have associated tests."""
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

        result = check_test_pin_alignment(registry, [test_dir], baseline_path)

        assert result.total_pin_functions == 1
        assert result.pin_functions_with_tests == 1
        assert result.pin_functions_without_tests == 0
        assert result.test_coverage_ratio == 1.0

    def test_coverage_with_untested_pins(self, tmp_path: Path) -> None:
        """Partial coverage when some pin-functions have no tests."""
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
        registry = _make_registry(
            [
                _make_pin_func("PFUNC-0001", "validate_payment"),
                _make_pin_func("PFUNC-0002", "process_order"),
            ]
        )
        baseline_path = tmp_path / ".spec" / "test_pin_baselines.json"

        result = check_test_pin_alignment(registry, [test_dir], baseline_path)

        assert result.total_pin_functions == 2
        assert result.pin_functions_with_tests == 1
        assert result.pin_functions_without_tests == 1
        assert result.test_coverage_ratio == 0.5

    def test_coverage_with_no_pin_functions(self, tmp_path: Path) -> None:
        """Zero pin-functions results in 0.0 coverage ratio."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        registry = _make_registry()
        baseline_path = tmp_path / ".spec" / "test_pin_baselines.json"

        result = check_test_pin_alignment(registry, [test_dir], baseline_path)

        assert result.total_pin_functions == 0
        assert result.test_coverage_ratio == 0.0
