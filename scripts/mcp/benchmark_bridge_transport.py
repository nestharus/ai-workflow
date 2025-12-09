#!/usr/bin/env python3
r"""Benchmark script for MCP Bridge transport modes.

This script measures the latency and throughput of the MCP bridge using both
Unix socket and HTTP transport modes. It helps validate performance claims
and provides a repeatable way to measure improvements.

Usage:
    # Benchmark Unix socket mode (default, requires running mcp-bridge):
    python scripts/mcp/benchmark_bridge_transport.py

    # Benchmark HTTP mode:
    python scripts/mcp/benchmark_bridge_transport.py --mode http --url http://localhost:8080

    # Compare both modes side-by-side:
    python scripts/mcp/benchmark_bridge_transport.py --compare

    # Custom number of iterations:
    python scripts/mcp/benchmark_bridge_transport.py --iterations 200

    # Compare with performance thresholds (exits non-zero if thresholds not met):
    python scripts/mcp/benchmark_bridge_transport.py --compare \\
        --min-latency-improvement 20 \\
        --min-throughput-improvement 15

Requirements:
    - MCP bridge must be running via the dev-tools stack. Preferred method:
      uv run dev.ensure-env
      Or start manually:
      docker compose -p ai-workflow-devtools -f docker-compose.dev.yml up -d mcp-bridge
    - For socket mode: MCP_BRIDGE_SOCKET must be set or socket must exist
    - For HTTP mode: Bridge must be accessible at the specified URL

Output:
    - Latency statistics (min, median, p90, p99, max) in milliseconds
    - Throughput (requests/second)
    - Optional side-by-side comparison of transport modes
    - Exit code 1 if thresholds are specified and not met

Threshold Checking:
    When using --compare with --min-latency-improvement and/or --min-throughput-improvement,
    the script will compute the percentage improvement of Unix socket over HTTP and exit
    with code 1 if the measured improvement is below the specified threshold.

    This is useful for validating performance targets:
    - Target latency improvement: ~30-50% (use --min-latency-improvement 30)
    - Target throughput improvement: varies by workload

    Note: This script is diagnostic and NOT enforced in CI. Use it to manually validate
    performance claims after changes. Actual results vary by workload and system config.

See Also:
    - docs/architecture/mcp-bridge-architecture.yml (performance expectations)
    - scripts/tests/mcp/integration.py (integration tests)
"""

from __future__ import annotations

import argparse
import contextlib
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

# Add the scripts/mcp directory to path for imports
MCP_BRIDGE_PATH = Path(__file__).parent
if str(MCP_BRIDGE_PATH) not in sys.path:
    sys.path.insert(0, str(MCP_BRIDGE_PATH))

from client.http_client import HttpMCPClient, MCPClientError  # type: ignore[import-not-found]

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


def run_benchmark(
    client: HttpMCPClient,
    iterations: int,
    mode: str,
    warmup: int = 5,
) -> BenchmarkResult:
    """Run benchmark against the MCP bridge.

    Args:
        client: HttpMCPClient instance configured for the transport mode.
        iterations: Number of requests to make.
        mode: Transport mode name for display ("socket" or "http").
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


def print_comparison(socket_result: BenchmarkResult, http_result: BenchmarkResult) -> None:
    """Print side-by-side comparison of two benchmark results."""
    print(f"\n{'=' * 70}")
    print("TRANSPORT COMPARISON: Unix Socket vs HTTP")
    print(f"{'=' * 70}")
    print(f"{'Metric':<20} {'Socket':>15} {'HTTP':>15} {'Improvement':>15}")
    print(f"{'-' * 70}")

    # Calculate improvements (positive = socket is better)
    def improvement(socket_val: float, http_val: float) -> str:
        if http_val <= 0:
            return "N/A"
        pct = ((http_val - socket_val) / http_val) * 100
        if pct > 0:
            return f"+{pct:.1f}% faster"
        elif pct < 0:
            return f"{-pct:.1f}% slower"
        else:
            return "same"

    print(
        f"{'Min Latency (ms)':<20} "
        f"{socket_result.min_ms:>15.2f} "
        f"{http_result.min_ms:>15.2f} "
        f"{improvement(socket_result.min_ms, http_result.min_ms):>15}"
    )
    print(
        f"{'Median Latency (ms)':<20} "
        f"{socket_result.median_ms:>15.2f} "
        f"{http_result.median_ms:>15.2f} "
        f"{improvement(socket_result.median_ms, http_result.median_ms):>15}"
    )
    print(
        f"{'P90 Latency (ms)':<20} "
        f"{socket_result.p90_ms:>15.2f} "
        f"{http_result.p90_ms:>15.2f} "
        f"{improvement(socket_result.p90_ms, http_result.p90_ms):>15}"
    )
    print(
        f"{'P99 Latency (ms)':<20} "
        f"{socket_result.p99_ms:>15.2f} "
        f"{http_result.p99_ms:>15.2f} "
        f"{improvement(socket_result.p99_ms, http_result.p99_ms):>15}"
    )
    print(
        f"{'Max Latency (ms)':<20} "
        f"{socket_result.max_ms:>15.2f} "
        f"{http_result.max_ms:>15.2f} "
        f"{improvement(socket_result.max_ms, http_result.max_ms):>15}"
    )
    print(f"{'-' * 70}")

    # Throughput comparison (higher is better, so invert the comparison)
    throughput_imp = ""
    if http_result.throughput_rps > 0:
        pct = (
            (socket_result.throughput_rps - http_result.throughput_rps) / http_result.throughput_rps
        ) * 100
        if pct > 0:
            throughput_imp = f"+{pct:.1f}% faster"
        elif pct < 0:
            throughput_imp = f"{-pct:.1f}% slower"
        else:
            throughput_imp = "same"

    print(
        f"{'Throughput (req/s)':<20} "
        f"{socket_result.throughput_rps:>15.1f} "
        f"{http_result.throughput_rps:>15.1f} "
        f"{throughput_imp:>15}"
    )
    print(f"{'=' * 70}")


def main(argv: Sequence[str] | None = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Benchmark MCP Bridge transport modes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--mode",
        choices=["socket", "http"],
        default="socket",
        help="Transport mode to benchmark (default: socket)",
    )
    parser.add_argument(
        "--socket",
        default=os.environ.get("MCP_BRIDGE_SOCKET", "/tmp/mcp-bridge.sock"),
        help="Unix socket path (default: $MCP_BRIDGE_SOCKET or /tmp/mcp-bridge.sock)",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("MCP_BRIDGE_URL", "http://localhost:8080"),
        help="HTTP URL for bridge (default: $MCP_BRIDGE_URL or http://localhost:8080)",
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
        "--compare",
        action="store_true",
        help="Compare both socket and HTTP modes side-by-side",
    )
    parser.add_argument(
        "--min-latency-improvement",
        type=float,
        default=None,
        metavar="PCT",
        help="Minimum required latency improvement (percentage) for socket vs HTTP. "
        "Only applies with --compare. Exit non-zero if improvement is below threshold.",
    )
    parser.add_argument(
        "--min-throughput-improvement",
        type=float,
        default=None,
        metavar="PCT",
        help="Minimum required throughput improvement (percentage) for socket vs HTTP. "
        "Only applies with --compare. Exit non-zero if improvement is below threshold.",
    )

    args = parser.parse_args(argv)

    print("MCP Bridge Transport Benchmark")
    print("=" * 60)

    results: list[BenchmarkResult] = []

    if args.compare:
        # Run both modes
        print("\n[1/2] Benchmarking Unix Socket mode...")
        try:
            socket_client = HttpMCPClient(socket_path=args.socket)
            socket_result = run_benchmark(socket_client, args.iterations, "socket", args.warmup)
            results.append(socket_result)
            print_result(socket_result)
        except MCPClientError as e:
            print(f"  Socket mode failed: {e}")
            socket_result = None

        print("\n[2/2] Benchmarking HTTP mode...")
        try:
            http_client = HttpMCPClient(base_url=args.url)
            http_result = run_benchmark(http_client, args.iterations, "http", args.warmup)
            results.append(http_result)
            print_result(http_result)
        except MCPClientError as e:
            print(f"  HTTP mode failed: {e}")
            http_result = None

        # Print comparison if both succeeded
        if socket_result and http_result:
            print_comparison(socket_result, http_result)

            # Check thresholds if specified
            threshold_failures: list[str] = []

            if args.min_latency_improvement is not None:
                # Calculate median latency improvement (positive = socket faster)
                if http_result.median_ms > 0:
                    latency_improvement = (
                        (http_result.median_ms - socket_result.median_ms) / http_result.median_ms
                    ) * 100
                    if latency_improvement < args.min_latency_improvement:
                        threshold_failures.append(
                            f"Latency improvement {latency_improvement:.1f}% "
                            f"< required {args.min_latency_improvement:.1f}%"
                        )
                else:
                    threshold_failures.append(
                        "Cannot calculate latency improvement: HTTP median is 0"
                    )

            if args.min_throughput_improvement is not None:
                # Calculate throughput improvement (positive = socket faster)
                if http_result.throughput_rps > 0:
                    throughput_improvement = (
                        (socket_result.throughput_rps - http_result.throughput_rps)
                        / http_result.throughput_rps
                    ) * 100
                    if throughput_improvement < args.min_throughput_improvement:
                        threshold_failures.append(
                            f"Throughput improvement {throughput_improvement:.1f}% "
                            f"< required {args.min_throughput_improvement:.1f}%"
                        )
                else:
                    threshold_failures.append(
                        "Cannot calculate throughput improvement: HTTP throughput is 0"
                    )

            if threshold_failures:
                print(f"\n{'=' * 70}")
                print("THRESHOLD CHECK FAILED")
                print(f"{'=' * 70}")
                for failure in threshold_failures:
                    print(f"  - {failure}")
                return 1

        else:
            print("\n[WARNING] Could not compare - one or both modes failed")
            return 1

    else:
        # Single mode
        print(f"\nBenchmarking {args.mode.upper()} mode...")
        try:
            if args.mode == "socket":
                client = HttpMCPClient(socket_path=args.socket)
            else:
                client = HttpMCPClient(base_url=args.url)

            result = run_benchmark(client, args.iterations, args.mode, args.warmup)
            print_result(result)

            if result.failed > 0:
                print(f"\n[WARNING] {result.failed} requests failed")
                return 1

        except MCPClientError as e:
            print(f"\n[ERROR] Benchmark failed: {e}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
