"""Cold start regression tests for MCP Socket Server (SUPPLEMENTAL).

IMPORTANT: This is a SUPPLEMENTAL test for catching major regressions during
local development. The MANDATORY <500ms acceptance criterion is enforced by
the CI gate in `test_cold_start_gate.py` (Plan 9).

These tests verify the socket server starts within acceptable bounds.
The thresholds are intentionally relaxed (10000ms) to avoid flaky failures
on developer machines due to environment variability.

For the mandatory CI gate (500ms threshold):
    CI_COLD_START_GATE=true pytest scripts/tests/mcp/test_cold_start_gate.py -v

For precise measurements, use the benchmark script directly:
    python scripts/servers/mcp/benchmark_bridge_transport.py --cold-start

To run these supplemental tests locally:
    pytest scripts/tests/mcp/test_cold_start.py -v

To run in CI (must opt-in):
    RUN_COLD_START_TESTS=true pytest scripts/tests/mcp/test_cold_start.py -v

## Cold Start Performance Testing

The socket server targets <500ms cold start time. To validate this:

### Quick check (single measurement):
```bash
python scripts/servers/mcp/benchmark_bridge_transport.py --cold-start --cold-start-iterations 1
```

### Full benchmark (10 iterations with statistics):
```bash
python scripts/servers/mcp/benchmark_bridge_transport.py --cold-start
```

### Run regression guard tests:
```bash
# Locally (runs by default)
pytest scripts/tests/mcp/test_cold_start.py -v

# In CI (must opt-in)
RUN_COLD_START_TESTS=true pytest scripts/tests/mcp/test_cold_start.py -v
```

Note: Cold start times vary by environment (CPU, disk speed, Python version).
The regression test uses a relaxed 10000ms threshold for local development stability.
The actual <500ms target is enforced by the mandatory CI gate (Plan 9).
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.tests.conftest import wait_for_server_ready


# Mark as slow/integration test - not run by default in CI
@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("CI") == "true" and os.environ.get("RUN_COLD_START_TESTS") != "true",
    reason="Cold start tests are environment-dependent; set RUN_COLD_START_TESTS=true to run in CI",
)
class TestColdStartRegression:
    """Cold start regression tests with relaxed thresholds (SUPPLEMENTAL).

    IMPORTANT: This is a SUPPLEMENTAL test for catching major regressions during
    local development. The MANDATORY <500ms acceptance criterion is enforced by
    the CI gate in `test_cold_start_gate.py` (Plan 9).

    These tests verify the socket server starts within acceptable bounds.
    The thresholds are intentionally relaxed (10000ms) to avoid flaky failures
    on developer machines due to environment variability.
    """

    # Very relaxed threshold for local dev stability
    # This is a SUPPLEMENTAL test - the mandatory <500ms CI gate is in Plan 9
    # WSL, VMs, and busy machines can have much slower startup times
    COLD_START_THRESHOLD_MS = 10000.0  # 10 seconds - catch major regressions only

    @pytest.fixture
    def socket_path(self, tmp_path: Path) -> str:
        """Provide a temporary socket path."""
        return str(tmp_path / "test-mcp-bridge.sock")

    @pytest.fixture
    def server_script(self) -> str:
        """Path to the socket server script."""
        return str(
            Path(__file__).parent.parent.parent.parent / "servers" / "mcp" / "server_impl.py"
        )

    def test_cold_start_under_threshold(self, socket_path: str, server_script: str) -> None:
        """Test that server cold start is under the regression threshold.

        This test spawns the server process and measures time until it
        responds to a health check. Uses a relaxed threshold (10000ms) to
        avoid CI flakiness while catching major regressions.
        """
        start = time.perf_counter()

        proc = subprocess.Popen(
            [sys.executable, server_script],
            env={
                **os.environ,
                "MCP_BRIDGE_SOCKET": socket_path,
                # Skip MCP provider init for cold-start measurement (pure server startup)
                "MCP_CONFIG_PATH": "/dev/null",
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            # Wait for server to be ready (max 5 seconds, 5ms poll interval for dev)
            ready = wait_for_server_ready(socket_path, timeout=5.0, poll_interval=0.005)
            end = time.perf_counter()

            assert ready, "Server did not become ready within 5 seconds"

            cold_start_ms = (end - start) * 1000
            assert cold_start_ms < self.COLD_START_THRESHOLD_MS, (
                f"Cold start time {cold_start_ms:.1f}ms exceeds threshold "
                f"{self.COLD_START_THRESHOLD_MS}ms. "
                f"Run 'python scripts/servers/mcp/benchmark_bridge_transport.py --cold-start' "
                f"for detailed measurements."
            )

            # Log actual time for visibility
            threshold_ms = self.COLD_START_THRESHOLD_MS
            print(f"\n  Cold start time: {cold_start_ms:.1f}ms (threshold: {threshold_ms}ms)")

        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            # Clean up socket file
            with contextlib.suppress(FileNotFoundError):
                os.unlink(socket_path)

    def test_cold_start_multiple_iterations(self, socket_path: str, server_script: str) -> None:
        """Test cold start time consistency across multiple iterations.

        This test runs multiple cold start iterations to check for consistency
        and catch any intermittent performance issues.
        """
        iterations = 3
        times: list[float] = []

        for i in range(iterations):
            # Use unique socket path for each iteration
            iter_socket_path = socket_path.replace(".sock", f"-{i}.sock")

            start = time.perf_counter()
            proc = subprocess.Popen(
                [sys.executable, server_script],
                env={
                    **os.environ,
                    "MCP_BRIDGE_SOCKET": iter_socket_path,
                    # Skip MCP provider init for cold-start measurement (pure server startup)
                    "MCP_CONFIG_PATH": "/dev/null",
                },
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            try:
                ready = wait_for_server_ready(iter_socket_path, timeout=5.0, poll_interval=0.005)
                end = time.perf_counter()

                assert ready, f"Server did not become ready on iteration {i}"
                times.append((end - start) * 1000)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                # Clean up socket file
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(iter_socket_path)

            # Brief pause between iterations
            time.sleep(0.1)

        # Check all times are under threshold
        max_time = max(times)
        avg_time = sum(times) / len(times)

        print(f"\n  Cold start times: {[f'{t:.1f}ms' for t in times]}")
        print(f"  Average: {avg_time:.1f}ms, Max: {max_time:.1f}ms")

        assert max_time < self.COLD_START_THRESHOLD_MS, (
            f"Max cold start time {max_time:.1f}ms exceeds threshold "
            f"{self.COLD_START_THRESHOLD_MS}ms. Times: {times}"
        )

    def test_server_responds_to_health_check_after_startup(
        self, socket_path: str, server_script: str
    ) -> None:
        """Test that server responds correctly to health check after startup.

        This test verifies the server is fully functional after cold start,
        not just that the socket is accepting connections.
        """
        proc = subprocess.Popen(
            [sys.executable, server_script],
            env={
                **os.environ,
                "MCP_BRIDGE_SOCKET": socket_path,
                # Skip MCP provider init for cold-start measurement (pure server startup)
                "MCP_CONFIG_PATH": "/dev/null",
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            ready = wait_for_server_ready(socket_path, timeout=5.0, poll_interval=0.005)
            assert ready, "Server did not become ready"

            # Send another health check to verify server is fully operational
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(5.0)
                sock.connect(socket_path)
                sock.sendall(b'{"method": "health", "id": "functional-check"}\n')

                # Accumulate response bytes until newline (JSONL terminator) is received
                buffer = b""
                while True:
                    try:
                        chunk = sock.recv(4096)
                    except TimeoutError as err:
                        raise AssertionError(
                            "Socket timeout while waiting for complete JSONL response"
                        ) from err
                    if not chunk:
                        raise AssertionError(
                            "Connection closed before receiving complete JSONL response"
                        )
                    buffer += chunk
                    if b"\n" in buffer:
                        break

            # Verify response structure
            data = json.loads(buffer.decode())
            assert data.get("status") == "success", f"Unexpected status: {data}"
            assert data.get("id") == "functional-check"
            result = data.get("result", {})
            # Health response should have status field
            assert "status" in result, f"Missing status in result: {result}"

        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            # Clean up socket file
            with contextlib.suppress(FileNotFoundError):
                os.unlink(socket_path)
