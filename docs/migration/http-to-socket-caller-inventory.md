# HTTP to Socket Caller Migration Inventory

This document tracks all callers of the MCP bridge that were using HTTP and their
migration status to the Unix socket protocol.

## Overview

The MCP bridge was migrated from FastAPI/HTTP to a native Unix socket server. This
provides significant performance improvements (less than 500ms cold start vs 2-3s for
FastAPI/uvicorn) and reduced resource overhead.

All callers that previously used HTTP endpoints must migrate to the socket protocol.
The `HttpMCPClient` class name was preserved for backward compatibility, but it now
uses socket transport internally.

## Migration Summary

| Category | Status |
|----------|--------|
| Python clients using HttpMCPClient | Automatically migrated (socket transport) |
| Docker healthchecks | Updated to Python socket snippet |
| Documentation | Updated with socket examples |
| Integration tests | Updated to use socket transport |
| Benchmark scripts | Updated to use socket transport |

## Caller Inventory

### Python Clients

| File | Caller Type | Migration Status | Notes |
|------|-------------|------------------|-------|
| `scripts/servers/mcp/client/http_client.py` | MCPSocketClient | Complete | Core socket client implementation |
| `scripts/servers/mcp/client/__init__.py` | Module exports | Complete | Exports HttpMCPClient alias |
| `scripts/dev/mcp_agent_client.py` | Higher-level client | Complete | Uses socket client |
| `scripts/servers/mcp/__init__.py` | Package docstring | Complete | Updated examples |

### Test Files

| File | Caller Type | Migration Status | Notes |
|------|-------------|------------------|-------|
| `scripts/tests/mcp/test_bridge.py` | Unit tests | Complete | Tests socket client |
| `scripts/tests/mcp/test_socket_client.py` | Unit tests | Complete | Socket-specific tests |
| `scripts/tests/mcp/integration.py` | Integration tests | Complete | Uses MCPSocketClient |
| `scripts/tests/tasks/test_mcp_agent_client.py` | Agent client tests | Complete | Uses FakeHttpMCPClient |

### Docker Configuration

| File | Component | Migration Status | Notes |
|------|-----------|------------------|-------|
| `docker-compose.dev.yml` | mcp-bridge healthcheck | Complete | Python socket snippet |
| `docker-compose.yml` | mcp-bridge healthcheck | Complete | Python socket snippet |
| `scripts/servers/mcp/Dockerfile` | Container build | Complete | Socket-based server |

### Documentation

| File | Content Type | Migration Status | Notes |
|------|--------------|------------------|-------|
| `docs/architecture/mcp-bridge-architecture.yml` | Architecture docs | Complete | Socket protocol documented |
| `docs/processes/mcp-background-job-setup.yml` | Setup guide | Complete | Socket-first instructions |
| `docs/processes/dev-env.yml` | Dev environment | Complete | Socket path documented |

### Benchmark Scripts

| File | Caller Type | Migration Status | Notes |
|------|-------------|------------------|-------|
| `scripts/servers/mcp/benchmark_bridge_transport.py` | Benchmark | Complete | Uses MCPSocketClient |

## Migration Guide

### Python Code

**Before (HTTP):**

```python
from scripts.servers.mcp.client import HttpMCPClient

# HTTP mode (deprecated)
client = HttpMCPClient(base_url="http://localhost:8080")
```

**After (Socket):**

```python
from scripts.servers.mcp.client import HttpMCPClient  # Name preserved for compatibility
# Or use the explicit name:
from scripts.servers.mcp.client import MCPSocketClient

# Socket path from argument
client = HttpMCPClient(socket_path="/tmp/mcp-sockets/mcp-bridge.sock")

# Or via environment variable (recommended)
# export MCP_BRIDGE_SOCKET=/tmp/mcp-sockets/mcp-bridge.sock
client = HttpMCPClient()  # Uses MCP_BRIDGE_SOCKET env var
```

### Shell Scripts / Manual Testing

**Before (curl over HTTP):**

```bash
curl -X POST http://localhost:8080/servers -H "Content-Type: application/json"
```

**After (Python socket snippet):**

```bash
python -c "
import socket,json
s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
s.connect('/tmp/mcp-sockets/mcp-bridge.sock')
s.sendall(b'{\"method\":\"list_servers\",\"id\":\"test\"}\n')
print(s.recv(4096).decode())
s.close()
"
```

**Alternative (curl with Unix socket):**

```bash
# Note: Requires curl compiled with Unix socket support
# The bridge expects JSONL, not HTTP, so this won't work for data requests
# Only useful for raw socket testing with tools like socat
```

### Docker Healthchecks

**Before (curl over HTTP):**

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
```

**After (external script - recommended):**

The repository uses an external healthcheck script for maintainability. This is the
approach used in `docker-compose.yml` and `docker-compose.dev.yml`:

```yaml
healthcheck:
  test: ["CMD", "python", "/app/scripts/servers/mcp/healthcheck.py"]
  interval: 30s
  timeout: 5s
  start_period: 10s
  retries: 3
```

The script is located at `scripts/servers/mcp/healthcheck.py` and handles socket
connection, timeout, and response validation.

**Alternative (inline one-liner for quick tests):**

For quick tests or environments without access to the external script, an inline
Python one-liner can be used:

```yaml
healthcheck:
  test:
    - CMD
    - python
    - -c
    - import socket,json,sys;
      s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);
      s.settimeout(3);
      try:
        s.connect('/tmp/mcp-bridge.sock');
        s.sendall(b'{"method":"health","id":"hc"}\n');
        r=s.recv(4096);
        s.close();
        d=json.loads(r);
        res=d.get('result',{});
        sys.exit(0 if d.get('status')=='success' and res.get('status')=='ok' else 1)
      except Exception:
        sys.exit(1)
  interval: 30s
  timeout: 5s
  start_period: 10s
  retries: 3
```

**Note:** Inline one-liners are valid for quick tests, but the repository uses the
external script (`/app/scripts/servers/mcp/healthcheck.py`) for maintainability and
better error handling.

### Environment Variables

**Before:**

```bash
export MCP_BRIDGE_URL=http://localhost:8080
```

**After:**

```bash
export MCP_BRIDGE_SOCKET=/tmp/mcp-sockets/mcp-bridge.sock
```

## Backward Compatibility

The following backward compatibility measures are in place:

1. **HttpMCPClient alias**: The `HttpMCPClient` class name is preserved as an alias for
   `MCPSocketClient`. Existing code using this name will continue to work.

2. **MCP_BRIDGE_URL fallback**: If `MCP_BRIDGE_SOCKET` is not set, the client checks
   `MCP_BRIDGE_URL` for backward compatibility. However, HTTP mode is no longer
   supported by the server.

3. **base_url parameter**: The constructor still accepts `base_url` for backward
   compatibility, but socket transport takes precedence when `socket_path` or
   `MCP_BRIDGE_SOCKET` is available.

## Deprecation Notice

HTTP mode is **deprecated and no longer supported** by the MCP bridge server. The server
only listens on Unix sockets. If HTTP access is needed, implement a separate HTTP-to-socket
proxy outside the bridge.

Deprecated patterns:
* `base_url` parameter without `socket_path`
* `MCP_BRIDGE_URL` environment variable (only useful with external HTTP proxy)
* `curl` commands to HTTP endpoints

## Verification

To verify migration is complete:

1. Run unit tests: `uv run pytest scripts/tests/mcp/test_bridge.py -v`
2. Run socket client tests: `uv run pytest scripts/tests/mcp/test_socket_client.py -v`
3. Run caller migration tests: `uv run pytest scripts/tests/mcp/test_caller_migration.py -v`
4. Run integration tests: `uv run pytest scripts/tests/mcp/integration.py -v`

## No HTTP Shim Required

After inventory analysis, no external callers were found that require an HTTP shim.
All callers have been migrated to socket protocol:

* Python clients use `MCPSocketClient` (or `HttpMCPClient` alias)
* Docker healthchecks use Python socket snippets
* Documentation has been updated with socket examples
* No CI workflows depend on HTTP endpoints
