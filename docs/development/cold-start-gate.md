# Cold-Start Performance Gate

The MCP bridge socket server has a mandatory cold-start performance requirement:
**median startup time must be under 500ms**. This is enforced by a CI gate that runs
on every PR affecting the MCP bridge.

## Gate Configuration

| Parameter | Value | Description |
|-----------|-------|-------------|
| Threshold | 500ms | Maximum allowed median cold-start time |
| Iterations | 5 | Number of measurements (after warmup) |
| Warmup | 2 | Iterations discarded before measurement |
| Environment | `CI_COLD_START_GATE=true` | Required to run gate |

### Why 500ms?

The 500ms threshold represents a significant improvement over FastAPI/uvicorn (~2-3 seconds)
while accounting for unavoidable Python startup overhead:

* **Process spawn overhead**: ~50ms
* **Python interpreter initialization**: ~50ms
* **Module imports (asyncio, logging, dataclasses, etc.)**: ~100-200ms
* **Socket setup and health check round trip**: ~20ms

The original 100ms target was unrealistic for a Python application with any meaningful
imports. The 500ms threshold ensures:

* A **5-6x improvement** over the previous FastAPI/uvicorn implementation
* Achievable in both CI and local environments
* Still enforces the "fast cold start" requirement for CLI hooks and IPC scenarios

## How the Gate Works

1. **Warmup Phase**: 2 iterations are run and discarded to stabilize the environment (file caches, JIT effects)

2. **Measurement Phase**: 5 iterations measure cold-start time:
   * Spawn server process
   * Poll until socket accepts connection
   * Send health request and receive response
   * Record elapsed time

3. **Evaluation**: Median of 5 measurements must be <= 500ms

## Running Locally

```bash
# Quick check (runs the gate test)
CI_COLD_START_GATE=true uv run pytest scripts/tests/mcp/test_cold_start_gate.py -v

# Detailed benchmark with statistics
uv run python scripts/servers/mcp/benchmark_bridge_transport.py --cold-start

# Extended benchmark (more iterations)
uv run python scripts/servers/mcp/benchmark_bridge_transport.py --cold-start --cold-start-iterations 20
```

## CI Environment

The gate runs on GitHub Actions with these characteristics:

* **Runner**: `ubuntu-latest` (2-core CPU, 7GB RAM)
* **Python**: 3.14 (controlled version)
* **Concurrency**: One run per PR (cancels in-progress on new push)
* **Trigger**: PRs/pushes affecting `scripts/servers/mcp/**`

### Why These Settings?

* **ubuntu-latest**: Standard runner, consistent across PRs
* **5 iterations with median**: Reduces impact of outliers from resource contention
* **2 warmup iterations**: Eliminates cold-cache effects from first runs
* **500ms threshold**: Balances realistic Python startup overhead with performance goals

## Troubleshooting Gate Failures

### 1. Verify Locally First

```bash
CI_COLD_START_GATE=true uv run pytest scripts/tests/mcp/test_cold_start_gate.py -v
```

If this passes locally but fails in CI, the issue is likely:

* Heavy imports added to server_impl.py
* Module-level initialization code
* Resource contention in CI

### 2. Profile Imports

```bash
python -X importtime scripts/servers/mcp/server_impl.py 2>&1 | head -50
```

Look for slow imports (>10ms) that can be deferred or removed.

### 3. Check Recent Changes

Common causes of regression:

* Adding new `import` statements to server_impl.py
* Module-level code that runs on import
* Adding dependencies to the MCP bridge package
* Loading MCP configuration with providers (config should be empty for cold-start tests)

### 4. Use the Benchmark Script

```bash
uv run python scripts/servers/mcp/benchmark_bridge_transport.py --cold-start --cold-start-iterations 20
```

This provides detailed statistics including min/max/p90/p99.

## Cold-Start Optimizations Applied

The following optimizations reduce cold-start time:

1. **Deferred YAML import**: YAML is only imported when actually parsing config files,
   saving ~200ms when config is empty or not found.

2. **Deferred httpx import**: The SSE client (which uses httpx) is only imported when
   creating SSE server connections, saving ~500ms when no SSE servers are configured.

3. **Config skip for cold-start tests**: The test uses `MCP_CONFIG_PATH=/dev/null` to
   skip loading `.mcp.yml` and avoid MCP provider initialization (~2-3s savings).

## Relationship to Regression Test

There are TWO cold-start tests:

| Test | Threshold | Purpose | When it runs |
| -- | -- | -- | -- |
| Gate (`test_cold_start_gate.py`) | 500ms | **Mandatory acceptance criterion** | CI (every PR) |
| Regression (`test_cold_start.py`) | 10000ms | Catch major regressions locally | Local development |

The regression test uses a relaxed threshold (10000ms) because:

* Local machines vary significantly in performance
* It is meant to catch 10x regressions, not enforce exact criterion
* Developers can run it without CI_COLD_START_GATE set

The gate test uses the performance threshold (500ms) because:

* It enforces the acceptance criterion
* CI environment is controlled and reproducible
* PRs must pass this to merge

## Modifying the Gate

If the 500ms threshold needs adjustment:

1. **Update the ticket acceptance criteria first** - the gate enforces the ticket requirement
2. Update `COLD_START_THRESHOLD_MS` in `test_cold_start_gate.py`
3. Update this documentation
4. Get approval from team lead

Do NOT relax the threshold to make tests pass. Fix the performance issue instead,
unless the threshold is genuinely unrealistic (as was the case with the original 100ms target).
