"""Test-pin alignment compliance gate.

Checks that test signatures anchoring pin-functions have not drifted,
providing a second layer of identity verification for pin-functions.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from spec_manager.compliance.promotion.config import GateId, GateMode, GateSpec
from spec_manager.compliance.promotion.result import GateCheckResult
from spec_manager.projection.lineage.test_pin_checker import (
    check_test_pin_alignment,
)

if TYPE_CHECKING:
    from spec_manager.schemas.pin_functions import PinFunctionRegistry


def check_test_pin_alignment_gate(
    registry: PinFunctionRegistry,
    test_roots: list[Path],
    baseline_path: Path,
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: Test signatures anchoring pin-functions have not drifted.

    Runs the test-pin checker and evaluates against gate thresholds.

    gate_spec.threshold: Minimum test-pin coverage ratio (default 0.0 = no minimum).
    gate_spec.params:
        - test_roots (list[str]): Override test directories.
        - update_baseline (bool): Whether to update baseline after check.

    Args:
        registry: The pin-function registry.
        test_roots: Test directories to scan.
        baseline_path: Path to the baseline JSON file.
        gate_spec: Gate configuration.

    Returns:
        GateCheckResult with findings for each drifted test signature.
    """
    start = time.monotonic()

    # Extract optional params
    update_bl = gate_spec.params.get("update_baseline", False)

    # Run the test-pin alignment check
    result = check_test_pin_alignment(
        registry=registry,
        test_roots=test_roots,
        baseline_path=baseline_path,
        update_baseline_flag=update_bl,
    )

    # Build findings
    findings: list[dict[str, object]] = []
    for drift in result.drift_items:
        findings.append({
            "drift_kind": drift.drift_kind.value,
            "pin_func_id": drift.edge.from_unit,
            "expected": drift.expected,
            "actual": drift.actual,
            "severity": drift.severity,
        })

    # Determine pass/fail
    has_drift = len(result.drift_items) > 0
    below_threshold = (
        gate_spec.threshold > 0.0
        and result.test_coverage_ratio < gate_spec.threshold
    )

    passed = not has_drift and not below_threshold

    if below_threshold:
        findings.append({
            "coverage_below_threshold": True,
            "test_coverage_ratio": result.test_coverage_ratio,
            "required_threshold": gate_spec.threshold,
        })

    # Build summary
    if passed:
        summary = (
            f"Test-pin alignment OK: {result.pin_functions_with_tests}/"
            f"{result.total_pin_functions} pin-functions have tests, "
            f"no drift detected"
        )
    else:
        parts = []
        if has_drift:
            parts.append(f"{len(result.drift_items)} test signature drift(s) detected")
        if below_threshold:
            parts.append(
                f"test coverage {result.test_coverage_ratio:.1%} "
                f"below threshold {gate_spec.threshold:.1%}"
            )
        summary = "Test-pin alignment: " + "; ".join(parts)

    duration_ms = (time.monotonic() - start) * 1000

    return GateCheckResult(
        gate_id=GateId.TEST_PIN_ALIGNMENT.value,
        passed=passed,
        mode=gate_spec.mode.value,
        score=result.test_coverage_ratio,
        findings=findings,
        summary=summary,
        duration_ms=duration_ms,
    )


__all__ = [
    "check_test_pin_alignment_gate",
]
