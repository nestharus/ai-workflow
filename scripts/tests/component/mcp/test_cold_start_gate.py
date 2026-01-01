"""Mandatory cold-start performance gate.

This test enforces the <500ms cold-start acceptance criterion and is designed
to run in CI with a reproducible environment. Unlike the relaxed regression
test (10000ms threshold), this gate uses the exact acceptance threshold.

Environment Requirements:
- Must run in CI environment with controlled resources
- Uses median of multiple iterations to reduce noise
- Requires CI_COLD_START_GATE=true environment variable to run
- Fails build if median cold-start exceeds 500ms

See docs/development/cold-start-gate.md for configuration details.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import pytest

from scripts.tests.conftest import wait_for_server_ready

# Gate configuration
# 500ms threshold represents a significant improvement over FastAPI/uvicorn (~2-3 seconds)
# while accounting for unavoidable Python startup overhead (~200-300ms).
# The 100ms target was unrealistic due to:
# - Process spawn overhead (~50ms)
# - Python interpreter initialization (~50ms)
# - Module imports (asyncio, logging, dataclasses, etc.) (~100ms)
# - Socket setup and health check round trip (~20ms)
COLD_START_THRESHOLD_MS = 500.0
GATE_ITERATIONS = 5  # Number of measurements for median
WARMUP_ITERATIONS = 2  # Discard first N iterations for stability
SERVER_READY_TIMEOUT = 10.0  # Max wait for server to start


@dataclass
class GateResult:
    """Result of cold-start gate measurement."""

    iterations: int
    timings_ms: list[float]
    median_ms: float
    threshold_ms: float
    passed: bool

    def summary(self) -> str:
        """Generate a summary string for the gate result."""
        status = "PASS" if self.passed else "FAIL"
        return (
            f"Cold-Start Gate: {status}\n"
            f"  Median: {self.median_ms:.1f}ms\n"
            f"  Threshold: {self.threshold_ms:.1f}ms\n"
            f"  Iterations: {self.iterations}\n"
            f"  All timings (ms): {[f'{t:.1f}' for t in self.timings_ms]}"
        )


def measure_cold_start(server_script: str, socket_path: str) -> float | None:
    """Measure single cold-start iteration.

    Returns cold-start time in milliseconds, or None if server failed to start.
    """
    # Clean up any existing socket
    socket_file = Path(socket_path)
    if socket_file.exists():
        socket_file.unlink()

    # Include PYTHONPATH so server_impl.py can import from scripts.*
    # Go up 4 levels: mcp/ -> component/ -> tests/ -> scripts/ -> repo root
    repo_root = str(Path(__file__).resolve().parents[4])
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    pythonpath = f"{repo_root}:{existing_pythonpath}" if existing_pythonpath else repo_root

    start = time.perf_counter()

    proc = subprocess.Popen(
        [sys.executable, server_script],
        env={
            **os.environ,
            "MCP_BRIDGE_SOCKET": socket_path,
            "PYTHONPATH": pythonpath,
            # Skip MCP provider init for cold-start measurement (pure server startup)
            "MCP_CONFIG_PATH": "/dev/null",
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        # Wait for server to be ready (2ms poll interval for gate precision)
        ready = wait_for_server_ready(socket_path, SERVER_READY_TIMEOUT, poll_interval=0.002)
        end = time.perf_counter()

        if ready:
            return (end - start) * 1000  # Convert to ms
        return None
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        # Clean up socket file
        with contextlib.suppress(FileNotFoundError):
            Path(socket_path).unlink()


def run_cold_start_gate(server_script: str, socket_path: str) -> GateResult:
    """Run the cold-start gate with warmup and measurement iterations."""
    all_timings: list[float] = []

    # Warmup iterations (discarded)
    for _ in range(WARMUP_ITERATIONS):
        measure_cold_start(server_script, socket_path)

    # Measurement iterations
    for _ in range(GATE_ITERATIONS):
        timing = measure_cold_start(server_script, socket_path)
        if timing is not None:
            all_timings.append(timing)

    if not all_timings:
        return GateResult(
            iterations=GATE_ITERATIONS,
            timings_ms=[],
            median_ms=float("inf"),
            threshold_ms=COLD_START_THRESHOLD_MS,
            passed=False,
        )

    median_ms = median(all_timings)
    return GateResult(
        iterations=len(all_timings),
        timings_ms=all_timings,
        median_ms=median_ms,
        threshold_ms=COLD_START_THRESHOLD_MS,
        passed=median_ms <= COLD_START_THRESHOLD_MS,
    )


@pytest.mark.cold_start_gate
class TestColdStartGate:
    """Mandatory cold-start performance gate for CI.

    This test is REQUIRED to pass for merges. It enforces the exact <500ms
    acceptance criterion using a reproducible CI environment.

    To run locally (for debugging):
        CI_COLD_START_GATE=true pytest scripts/tests/mcp/test_cold_start_gate.py -v

    In CI, this runs automatically via .github/workflows/cold-start-gate.yml
    """

    @pytest.fixture
    def socket_path(self, tmp_path: Path) -> str:
        """Provide a temporary socket path."""
        return str(tmp_path / "gate-test.sock")

    @pytest.fixture
    def server_script(self) -> str:
        """Path to the socket server script."""
        # Go up 4 levels: component/mcp/ -> component/ -> tests/ -> scripts/ -> repo root
        # Then into scripts/servers/mcp/
        return str(
            Path(__file__).parent.parent.parent.parent / "servers" / "mcp" / "server_impl.py"
        )

    @pytest.mark.skipif(
        os.environ.get("CI_COLD_START_GATE") != "true",
        reason=(
            "Cold-start gate requires CI_COLD_START_GATE=true. "
            "This test is run automatically in CI. "
            "Set CI_COLD_START_GATE=true to run locally."
        ),
    )
    def test_cold_start_gate_enforces_threshold(self, socket_path: str, server_script: str) -> None:
        """Mandatory gate: median cold-start must be under 500ms.

        This test:
        1. Runs 2 warmup iterations (discarded)
        2. Measures 5 cold-start iterations
        3. Computes median timing
        4. FAILS if median exceeds 500ms

        The gate is designed for CI with controlled resources. If this test
        fails locally due to environment differences, check:
        - docs/development/cold-start-gate.md for troubleshooting
        - The benchmark script for detailed profiling
        """
        result = run_cold_start_gate(server_script, socket_path)

        # Print detailed results for CI logs
        print(f"\n{result.summary()}")

        assert result.passed, (
            f"COLD-START GATE FAILED: Median {result.median_ms:.1f}ms exceeds "
            f"{result.threshold_ms:.1f}ms threshold.\n\n"
            f"{result.summary()}\n\n"
            f"Possible causes:\n"
            f"1. New imports adding startup overhead\n"
            f"2. Heavy initialization in module-level code\n"
            f"3. CI environment resource contention\n\n"
            f"Debug with: python scripts/servers/mcp/benchmark_bridge_transport.py --cold-start"
        )
