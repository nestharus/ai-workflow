#!/usr/bin/env python3
r"""Benchmark script for MCP Bridge native socket transport.

This script measures the latency, throughput, and cold start time of the MCP
bridge using native Unix socket transport. It helps validate performance claims
and provides a repeatable way to measure improvements.

Usage:
    # Benchmark Unix socket mode (default, requires running mcp-bridge):
    python scripts/servers/mcp/benchmark_bridge_transport.py

    # Custom number of iterations:
    python scripts/servers/mcp/benchmark_bridge_transport.py --iterations 200

    # Measure cold start time (server startup latency):
    python scripts/servers/mcp/benchmark_bridge_transport.py --cold-start

    # Cold start with custom iterations and threshold:
    python scripts/servers/mcp/benchmark_bridge_transport.py --cold-start \\
        --cold-start-iterations 20 \\
        --cold-start-threshold 100

Requirements:
    - For latency/throughput benchmark: MCP bridge must be running
    - For cold start benchmark: No running server required (spawns its own)
    - MCP_BRIDGE_SOCKET environment variable or socket path must be configured

Output:
    - Latency statistics (min, median, p90, p99, max) in milliseconds
    - Throughput (requests/second)
    - Cold start timing (when using --cold-start)
    - Exit code 1 if thresholds are specified and not met

Cold Start Benchmark:
    The --cold-start flag measures server startup time:
    - Spawns a fresh server process for each iteration
    - Measures time from process spawn until first successful health response
    - Reports timing statistics (min, median, p90, p99, max)
    - Validates against --cold-start-threshold (default: 500ms)

    Target cold start time: <500ms (compared to ~2-3s for FastAPI/uvicorn)

See Also:
    - docs/architecture/mcp-bridge-architecture.yml (performance expectations)
    - scripts/tests/mcp/integration.py (integration tests)
"""

from __future__ import annotations

import argparse
import contextlib
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

# Add the scripts/servers/mcp directory to path for imports
MCP_BRIDGE_PATH = Path(__file__).parent
if str(MCP_BRIDGE_PATH) not in sys.path:
    sys.path.insert(0, str(MCP_BRIDGE_PATH))

from client.http_client import MCPClientError, MCPSocketClient  # type: ignore[import-not-found]

from scripts.tests.conftest import wait_for_server_ready

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass
class BenchmarkResult:
    """Results from a benchmark run."""

    mode: str
    iterations: int
    successful: int
    failed: int
    latencies_ms: list[float]
    total_time_s: float

    @property
    def min_ms(self) -> float:
        """Minimum latency in milliseconds."""
        return min(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def max_ms(self) -> float:
        """Maximum latency in milliseconds."""
        return max(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def median_ms(self) -> float:
        """Median latency in milliseconds."""
        return statistics.median(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def mean_ms(self) -> float:
        """Mean latency in milliseconds."""
        return statistics.mean(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def p90_ms(self) -> float:
        """90th percentile latency in milliseconds."""
        if not self.latencies_ms:
            return 0.0
        # Use statistics.quantiles for accurate percentile calculation with interpolation
        quantile_cuts = statistics.quantiles(self.latencies_ms, n=10)
        return quantile_cuts[8]  # 9th cut point = 90th percentile

    @property
    def p99_ms(self) -> float:
        """99th percentile latency in milliseconds."""
        if not self.latencies_ms:
            return 0.0
        # Use statistics.quantiles for accurate percentile calculation with interpolation
        quantile_cuts = statistics.quantiles(self.latencies_ms, n=100)
        return quantile_cuts[98]  # 99th cut point = 99th percentile

    @property
    def throughput_rps(self) -> float:
        """Throughput in requests per second."""
        if self.total_time_s <= 0:
            return 0.0
        return self.successful / self.total_time_s

    @property
    def success_rate(self) -> float:
        """Success rate as a percentage."""
        if self.iterations <= 0:
            return 0.0
        return (self.successful / self.iterations) * 100.0


@dataclass
class ColdStartResult:
    """Results from cold start benchmark."""

    iterations: int
    successful: int
    timings_ms: list[float]

    @property
    def min_ms(self) -> float:
        """Minimum cold start time in milliseconds."""
        return min(self.timings_ms) if self.timings_ms else 0.0

    @property
    def max_ms(self) -> float:
        """Maximum cold start time in milliseconds."""
        return max(self.timings_ms) if self.timings_ms else 0.0

    @property
    def median_ms(self) -> float:
        """Median cold start time in milliseconds."""
        return statistics.median(self.timings_ms) if self.timings_ms else 0.0

    @property
    def p90_ms(self) -> float:
        """90th percentile cold start time in milliseconds."""
        if len(self.timings_ms) < 10:
            return self.max_ms
        return statistics.quantiles(self.timings_ms, n=10)[8]

    @property
    def p99_ms(self) -> float:
        """99th percentile cold start time in milliseconds."""
        if len(self.timings_ms) < 100:
            return self.max_ms
        return statistics.quantiles(self.timings_ms, n=100)[98]


def benchmark_cold_start(
    server_script: str,
    socket_path: str,
    iterations: int = 10,
    timeout: float = 10.0,
) -> ColdStartResult:
    """Measure cold start time for the socket server.

    Cold start is defined as: time from process spawn until the server
    responds to a health request over the Unix socket.

    Args:
        server_script: Path to server script (e.g., "scripts/servers/mcp/server_impl.py")
        socket_path: Unix socket path the server will bind to
        iterations: Number of cold start measurements to take
        timeout: Maximum time to wait for server readiness (seconds)

    Returns:
        ColdStartResult with timing statistics
    """
    timings: list[float] = []

    for i in range(iterations):
        # Clean up any existing socket
        if Path(socket_path).exists():
            with contextlib.suppress(OSError):
                os.unlink(socket_path)

        start = time.perf_counter()

        # Spawn server process
        # Include PYTHONPATH so server_impl.py can import from scripts.*
        repo_root = str(Path(__file__).resolve().parents[3])
        existing_pythonpath = os.environ.get("PYTHONPATH", "")
        pythonpath = f"{repo_root}:{existing_pythonpath}" if existing_pythonpath else repo_root
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
            stderr=subprocess.PIPE,
        )

        try:
            # Poll until socket is ready and responds to health check
            ready = wait_for_server_ready(socket_path, timeout)
            end = time.perf_counter()

            if ready:
                timings.append((end - start) * 1000)  # Convert to ms
                print(f"  Iteration {i + 1}/{iterations}: {timings[-1]:.1f}ms")
            else:
                # Capture stderr for diagnostic purposes
                stderr_output = ""
                if proc.stderr is not None:
                    stderr_bytes = proc.stderr.read()
                    if stderr_bytes:
                        stderr_output = stderr_bytes.decode("utf-8", errors="replace")
                        # Truncate to reasonable length for display
                        if len(stderr_output) > 500:
                            stderr_output = stderr_output[:500] + "..."
                failure_msg = (
                    f"  Iteration {i + 1}/{iterations}: "
                    f"Server did not become ready within {timeout}s"
                )
                if stderr_output:
                    failure_msg += f"\n    stderr: {stderr_output}"
                print(failure_msg)

        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

            # Clean up socket
            if Path(socket_path).exists():
                with contextlib.suppress(OSError):
                    os.unlink(socket_path)

    return ColdStartResult(
        iterations=iterations,
        successful=len(timings),
        timings_ms=timings,
    )


def print_cold_start_result(result: ColdStartResult, threshold_ms: float) -> bool:
    """Print cold start benchmark results.

    Args:
        result: ColdStartResult from benchmark.
        threshold_ms: Threshold in milliseconds to compare against.

    Returns:
        True if median is below threshold, False otherwise.
    """
    print(f"\n{'=' * 60}")
    print("Cold Start Benchmark Results")
    print(f"{'=' * 60}")
    print(f"  Iterations:     {result.iterations}")
    print(f"  Successful:     {result.successful}")
    print()
    print("  Timing (ms):")
    print(f"    Min:          {result.min_ms:.1f}")
    print(f"    Median:       {result.median_ms:.1f}")
    print(f"    P90:          {result.p90_ms:.1f}")
    print(f"    P99:          {result.p99_ms:.1f}")
    print(f"    Max:          {result.max_ms:.1f}")
    print()
    print(f"  Target:         <{threshold_ms:.0f}ms")

    passed = result.median_ms < threshold_ms
    if passed:
        print(f"  Result:         PASS (median {result.median_ms:.1f}ms < {threshold_ms:.0f}ms)")
    else:
        print(f"  Result:         FAIL (median {result.median_ms:.1f}ms >= {threshold_ms:.0f}ms)")
    print(f"{'=' * 60}")

    return passed


def run_benchmark(
    client: MCPSocketClient,
    iterations: int,
    mode: str,
    warmup: int = 5,
) -> BenchmarkResult:
    """Run benchmark against the MCP bridge.

    Args:
        client: MCPSocketClient instance.
        iterations: Number of requests to make.
        mode: Transport mode name for display.
        warmup: Number of warmup requests before measuring.

    Returns:
        BenchmarkResult with latency statistics.
    """
    latencies: list[float] = []
    failed = 0

    # Warmup phase - don't measure these
    print(f"  Warming up with {warmup} requests...")
    for _ in range(warmup):
        with contextlib.suppress(MCPClientError):
            client.list_servers()

    # Benchmark phase
    print(f"  Running {iterations} benchmark requests...")
    start_total = time.perf_counter()

    for i in range(iterations):
        start = time.perf_counter()
        try:
            # Use list_servers() as a lightweight health-check-like operation
            # This measures the full round-trip through the bridge
            client.list_servers()
            end = time.perf_counter()
            latencies.append((end - start) * 1000)  # Convert to ms
        except MCPClientError as e:
            failed += 1
            if failed <= 3:  # Only print first few errors
                print(f"    Request {i + 1} failed: {e}")

        # Progress indicator every 50 requests
        if (i + 1) % 50 == 0:
            print(f"    Completed {i + 1}/{iterations} requests...")

    end_total = time.perf_counter()
    total_time = end_total - start_total

    return BenchmarkResult(
        mode=mode,
        iterations=iterations,
        successful=len(latencies),
        failed=failed,
        latencies_ms=latencies,
        total_time_s=total_time,
    )


def print_result(result: BenchmarkResult) -> None:
    """Print benchmark results in a formatted table."""
    print(f"\n{'=' * 60}")
    print(f"Results for {result.mode.upper()} mode")
    print(f"{'=' * 60}")
    print(f"  Iterations:     {result.iterations}")
    print(f"  Successful:     {result.successful}")
    print(f"  Failed:         {result.failed}")
    print(f"  Success Rate:   {result.success_rate:.1f}%")
    print()
    print("  Latency (ms):")
    print(f"    Min:          {result.min_ms:.2f}")
    print(f"    Median:       {result.median_ms:.2f}")
    print(f"    Mean:         {result.mean_ms:.2f}")
    print(f"    P90:          {result.p90_ms:.2f}")
    print(f"    P99:          {result.p99_ms:.2f}")
    print(f"    Max:          {result.max_ms:.2f}")
    print()
    print(f"  Throughput:     {result.throughput_rps:.1f} req/s")
    print(f"  Total Time:     {result.total_time_s:.2f}s")


def main(argv: Sequence[str] | None = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Benchmark MCP Bridge native socket transport",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--socket",
        default=os.environ.get("MCP_BRIDGE_SOCKET", "/tmp/mcp-bridge.sock"),
        help="Unix socket path (default: $MCP_BRIDGE_SOCKET or /tmp/mcp-bridge.sock)",
    )
    parser.add_argument(
        "--iterations",
        "-n",
        type=int,
        default=100,
        help="Number of requests to benchmark (default: 100)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=5,
        help="Number of warmup requests (default: 5)",
    )
    parser.add_argument(
        "--cold-start",
        action="store_true",
        help="Measure cold start time (server startup latency)",
    )
    parser.add_argument(
        "--cold-start-iterations",
        type=int,
        default=10,
        help="Number of cold start measurements (default: 10)",
    )
    parser.add_argument(
        "--cold-start-threshold",
        type=float,
        default=500.0,
        metavar="MS",
        help="Cold start threshold in milliseconds (default: 500ms). "
        "Exit non-zero if median cold start exceeds threshold.",
    )
    parser.add_argument(
        "--server-script",
        default=str(MCP_BRIDGE_PATH / "server_impl.py"),
        help="Path to server script for cold start measurement",
    )

    args = parser.parse_args(argv)

    print("MCP Bridge Transport Benchmark")
    print("=" * 60)

    if args.cold_start:
        # Cold start benchmark
        print("\nMeasuring cold start time for native socket server...")
        print(f"  Server script: {args.server_script}")
        print(f"  Socket path:   {args.socket}")
        print(f"  Iterations:    {args.cold_start_iterations}")
        print()

        # Validate server script exists
        if not Path(args.server_script).exists():
            print(f"\n[ERROR] Server script not found: {args.server_script}")
            return 1

        cold_start_result = benchmark_cold_start(
            server_script=args.server_script,
            socket_path=args.socket,
            iterations=args.cold_start_iterations,
            timeout=10.0,
        )

        passed = print_cold_start_result(cold_start_result, args.cold_start_threshold)

        if cold_start_result.successful == 0:
            print("\n[ERROR] All cold start iterations failed")
            return 1

        if not passed:
            return 1

    else:
        # Latency/throughput benchmark (requires running server)
        print("\nBenchmarking SOCKET mode...")
        print(f"  Socket path: {args.socket}")
        print()

        try:
            client = MCPSocketClient(socket_path=args.socket)
            benchmark_result = run_benchmark(client, args.iterations, "socket", args.warmup)
            print_result(benchmark_result)

            if benchmark_result.failed > 0:
                print(f"\n[WARNING] {benchmark_result.failed} requests failed")
                return 1

        except MCPClientError as e:
            print(f"\n[ERROR] Benchmark failed: {e}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
