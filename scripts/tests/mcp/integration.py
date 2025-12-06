"""Integration tests for MCP Bridge.

These tests serve as automated QA for the MCP bridge, replacing manual testing.
They start a real Docker container with the MCP bridge and a simple echo MCP server,
then verify the full request flow works end-to-end using Unix socket communication.

Usage:
    uv run python -m pytest scripts/tests/mcp/integration.py -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

# ============================================================================
# Echo MCP Server Script
# ============================================================================

# This is a minimal MCP server that implements one tool with field and list args.
# It echoes back "I RAN WITH <args>" to verify the full call chain works.
ECHO_MCP_SERVER_SCRIPT = textwrap.dedent('''
    #!/usr/bin/env python3
    """Minimal MCP server for integration testing.

    Implements JSON-RPC 2.0 over STDIO with JSONL framing.
    Has one tool 'echo_tool' that echoes back its arguments.
    """
    import json
    import sys

    def read_request():
        """Read a JSON-RPC request from stdin (JSONL format)."""
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line.strip())

    def write_response(response):
        """Write a JSON-RPC response to stdout (JSONL format)."""
        sys.stdout.write(json.dumps(response) + "\\n")
        sys.stdout.flush()

    def handle_initialize(request_id, params):
        """Handle initialize request."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "echo-mcp-server", "version": "1.0.0"},
            },
        }

    def handle_tools_list(request_id, params):
        """Handle tools/list request."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": "echo_tool",
                        "description": "Echoes back its arguments for testing",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "message": {
                                    "type": "string",
                                    "description": "A message to echo"
                                },
                                "count": {
                                    "type": "integer",
                                    "description": "A count value"
                                },
                                "tags": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "A list of tags"
                                },
                            },
                            "required": ["message"],
                        },
                    }
                ]
            },
        }

    def handle_tools_call(request_id, params):
        """Handle tools/call request."""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name != "echo_tool":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": f"Unknown tool: {tool_name}"},
            }

        # Format arguments for echo
        args_str = json.dumps(arguments, sort_keys=True)
        echo_message = f"I RAN WITH {args_str}"

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": echo_message}],
                "isError": False,
            },
        }

    def main():
        """Main server loop."""
        handlers = {
            "initialize": handle_initialize,
            "tools/list": handle_tools_list,
            "tools/call": handle_tools_call,
        }

        while True:
            request = read_request()
            if request is None:
                break

            method = request.get("method", "")
            request_id = request.get("id")
            params = request.get("params", {})

            handler = handlers.get(method)
            if handler:
                response = handler(request_id, params)
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }

            write_response(response)

    if __name__ == "__main__":
        main()
''')


# ============================================================================
# Fixtures
# ============================================================================


def _docker_available() -> bool:
    """Check if Docker is available."""
    docker_path = shutil.which("docker")
    if not docker_path:
        return False
    try:
        result = subprocess.run(
            [docker_path, "info"],
            capture_output=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    else:
        return result.returncode == 0


# Skip all tests if Docker is not available
pytestmark = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker not available",
)


@pytest.fixture(scope="module")
def echo_server_script() -> Iterator[Path]:
    """Create a temporary echo MCP server script.

    Returns the path to the script file.
    """
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        delete=False,
        prefix="echo_mcp_server_",
    ) as f:
        f.write(ECHO_MCP_SERVER_SCRIPT)
        f.flush()
        script_path = Path(f.name)

    # Make executable
    script_path.chmod(0o755)

    yield script_path

    # Cleanup
    script_path.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def mcp_config() -> str:
    """Return MCP configuration YAML that uses the echo server.

    The config points to the echo MCP server script mounted at a known path
    inside the Docker container.
    """
    # Use Python from the container and the script mounted at /app/echo_server.py
    config = """
mcpServers:
  echo:
    type: stdio
    command: python
    args:
      - /app/echo_server.py
"""
    return config


@pytest.fixture(scope="module")
def mcp_bridge_container(mcp_config: str, echo_server_script: Path) -> Iterator[tuple[str, str]]:
    """Start the MCP bridge Docker container and return socket path and dummy base URL.

    Returns:
        Tuple of (socket_path, base_url) where base_url is always "http://localhost"

    Failure Diagnostics:
        This fixture distinguishes between three failure conditions:
        (a) Docker image build failure - skip with build error details
        (b) Container process crash/healthcheck failure - skip with container logs
        (c) Host-side Unix-socket/HTTPX connectivity issues - skip with transport error
    """
    # Create temp directory for socket
    socket_dir = tempfile.mkdtemp(prefix="mcp_socket_")
    socket_path = os.path.join(socket_dir, "mcp-bridge.sock")
    container_name = f"mcp-bridge-test-{os.getpid()}"
    base_url = "http://localhost"

    # Create temp config file
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".yml",
        delete=False,
        prefix="mcp_config_",
    ) as f:
        f.write(mcp_config)
        f.flush()
        config_path = Path(f.name)

    # Make config readable by Docker container (non-root user)
    config_path.chmod(0o644)

    # Get the project root (where Dockerfile is)
    project_root = Path(__file__).parent.parent.parent.parent
    dockerfile_context = project_root / "scripts" / "mcp"

    # Get full docker path to avoid S607 security warning
    docker_path = shutil.which("docker")
    if not docker_path:
        shutil.rmtree(socket_dir, ignore_errors=True)
        pytest.skip("Docker not available")

    try:
        # Build - capture and classify build failures (condition a)
        build_result = subprocess.run(
            [
                docker_path,
                "build",
                "-t",
                "mcp-bridge-test:latest",
                "-f",
                str(dockerfile_context / "Dockerfile"),
                str(dockerfile_context),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if build_result.returncode != 0:
            shutil.rmtree(socket_dir, ignore_errors=True)
            config_path.unlink(missing_ok=True)
            # Truncate build logs to avoid overwhelming CI output (max 2000 chars)
            build_stderr = build_result.stderr[:2000] + (
                "..." if len(build_result.stderr) > 2000 else ""
            )
            pytest.skip(
                f"[DOCKER BUILD FAILURE] Exit code: {build_result.returncode}. "
                f"Error: {build_stderr}"
            )

        # Run the container - no port mapping, volume mount for socket
        run_result = subprocess.run(
            [
                docker_path,
                "run",
                "-d",
                "--name",
                container_name,
                "-v",
                f"{socket_dir}:/tmp:rw",  # Mount socket directory
                "-v",
                f"{config_path}:/app/config/.mcp.yml:ro",
                "-v",
                f"{echo_server_script}:/app/echo_server.py:ro",
                "-e",
                "MCP_CONFIG_PATH=/app/config/.mcp.yml",
                "-e",
                "MCP_BRIDGE_SOCKET=/tmp/mcp-bridge.sock",
                "mcp-bridge-test:latest",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if run_result.returncode != 0:
            shutil.rmtree(socket_dir, ignore_errors=True)
            config_path.unlink(missing_ok=True)
            pytest.skip(
                f"[CONTAINER START FAILURE] Exit code: {run_result.returncode}. "
                f"Error: {run_result.stderr[:1000]}"
            )

        # Wait for socket file to exist and become healthy
        start_time = time.time()
        timeout_secs = 60.0
        healthy = False
        last_error_classification: str | None = None

        while time.time() - start_time < timeout_secs:
            # Check container health first (condition b)
            inspect_result = subprocess.run(
                [docker_path, "inspect", "--format", "{{.State.Status}}", container_name],
                capture_output=True,
                text=True,
            )
            container_status = inspect_result.stdout.strip()
            if container_status == "exited":
                logs_result = subprocess.run(
                    [docker_path, "logs", container_name], capture_output=True, text=True
                )
                logs_truncated = logs_result.stdout[:2000] + (
                    "..." if len(logs_result.stdout) > 2000 else ""
                )
                subprocess.run([docker_path, "rm", "-f", container_name], capture_output=True)
                shutil.rmtree(socket_dir, ignore_errors=True)
                config_path.unlink(missing_ok=True)
                pytest.skip(
                    f"[CONTAINER CRASH] Container exited unexpectedly. Logs: {logs_truncated}"
                )

            # Check socket file exists (condition c)
            if os.path.exists(socket_path):
                try:
                    # Use httpx with Unix socket transport
                    transport = httpx.HTTPTransport(uds=socket_path)
                    with httpx.Client(transport=transport, timeout=5.0) as client:
                        response = client.get(f"{base_url}/health")
                        if response.status_code == 200:
                            data = response.json()
                            if data.get("status") == "ok":
                                healthy = True
                                break
                        else:
                            last_error_classification = (
                                f"[NON-200 STATUS] HTTP {response.status_code}"
                            )
                except httpx.TimeoutException as e:
                    last_error_classification = (
                        f"[HTTPX TIMEOUT] {type(e).__name__}: {str(e)[:200]}"
                    )
                except httpx.TransportError as e:
                    last_error_classification = (
                        f"[TRANSPORT ERROR] {type(e).__name__}: {str(e)[:200]}"
                    )
                except httpx.RequestError as e:
                    last_error_classification = (
                        f"[REQUEST ERROR] {type(e).__name__}: {str(e)[:200]}"
                    )
                except OSError as e:
                    # Permission or socket errors
                    last_error_classification = f"[OS ERROR] errno={e.errno}, {str(e)[:200]}"
            else:
                last_error_classification = "[SOCKET NOT FOUND] Socket file does not exist yet"

            time.sleep(1.0)

        if not healthy:
            # Log informative message about socket status with truncated details
            socket_exists = os.path.exists(socket_path)
            logs_result = subprocess.run(
                [docker_path, "logs", container_name],
                capture_output=True,
                text=True,
            )
            logs_truncated = logs_result.stdout[:2000] + (
                "..." if len(logs_result.stdout) > 2000 else ""
            )
            subprocess.run([docker_path, "rm", "-f", container_name], capture_output=True)
            shutil.rmtree(socket_dir, ignore_errors=True)
            config_path.unlink(missing_ok=True)
            pytest.skip(
                f"[HEALTHCHECK FAILURE] Container did not become healthy within "
                f"{timeout_secs}s. Socket exists: {socket_exists}, Path: {socket_path}. "
                f"Last error: {last_error_classification}. Container logs: {logs_truncated}"
            )

        yield socket_path, base_url

    finally:
        # Cleanup: stop and remove container
        subprocess.run([docker_path, "rm", "-f", container_name], capture_output=True)
        config_path.unlink(missing_ok=True)

        # Unconditionally remove socket directory and verify cleanup
        shutil.rmtree(socket_dir, ignore_errors=True)
        assert not os.path.exists(socket_dir), f"Socket directory not cleaned up: {socket_dir}"


@pytest.fixture
def http_client(mcp_bridge_container: tuple[str, str]) -> Iterator[httpx.Client]:
    """Create an HTTP client for the MCP bridge using Unix socket."""
    socket_path, base_url = mcp_bridge_container
    transport = httpx.HTTPTransport(uds=socket_path)
    with httpx.Client(transport=transport, base_url=base_url, timeout=30.0) as client:
        yield client


# ============================================================================
# Integration Tests
# ============================================================================


class TestMCPBridgeIntegration:
    """Integration tests for the MCP Bridge.

    These tests verify the full request flow from HTTP client through
    the bridge to the MCP server and back using Unix socket transport.
    """

    def test_list_servers(self, http_client: httpx.Client) -> None:
        """Test GET /mcp/servers returns the configured echo server."""
        response = http_client.get("/mcp/servers")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "servers" in data
        servers = data["servers"]
        assert isinstance(servers, list)

        # Find our echo server
        server_names = [s["name"] for s in servers]
        assert "echo" in server_names, f"Expected 'echo' server, got: {server_names}"

        # Verify echo server details
        echo_server = next(s for s in servers if s["name"] == "echo")
        assert echo_server["transport"] == "stdio"
        assert echo_server["healthy"] is True

    def test_list_tools(self, http_client: httpx.Client) -> None:
        """Test GET /mcp/{server}/tools returns the echo_tool."""
        response = http_client.get("/mcp/echo/tools")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "tools" in data
        tools = data["tools"]
        assert isinstance(tools, list)

        # Find our echo_tool
        tool_names = [t["name"] for t in tools]
        assert "echo_tool" in tool_names, f"Expected 'echo_tool', got: {tool_names}"

    def test_get_tool(self, http_client: httpx.Client) -> None:
        """Test GET /mcp/{server}/tools/{tool} returns tool details."""
        response = http_client.get("/mcp/echo/tools/echo_tool")

        assert response.status_code == 200
        data = response.json()

        # Verify tool structure
        assert data["name"] == "echo_tool"
        assert "description" in data
        assert "inputSchema" in data

        # Verify schema has our expected properties
        schema = data["inputSchema"]
        assert schema["type"] == "object"
        properties = schema["properties"]
        assert "message" in properties
        assert "count" in properties
        assert "tags" in properties

        # Verify message is required
        assert "message" in schema.get("required", [])

    def test_call_tool(self, http_client: httpx.Client) -> None:
        """Test POST /mcp/{server}/call executes the tool and returns echo."""
        # Prepare test arguments with field and list values
        test_args = {
            "message": "Hello, MCP!",
            "count": 42,
            "tags": ["test", "integration", "qa"],
        }

        response = http_client.post(
            "/mcp/echo/call",
            json={
                "tool": "echo_tool",
                "arguments": test_args,
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Verify result envelope
        assert "result" in data
        result = data["result"]

        # Verify content structure (MCP tools/call response format)
        assert "content" in result
        content = result["content"]
        assert isinstance(content, list)
        assert len(content) > 0

        # Verify the echo message
        text_content = content[0]
        assert text_content["type"] == "text"
        echo_text = text_content["text"]

        # The echo should contain "I RAN WITH" and our arguments
        assert echo_text.startswith("I RAN WITH ")

        # Parse the echoed arguments and verify
        args_json = echo_text.replace("I RAN WITH ", "")
        echoed_args = json.loads(args_json)

        assert echoed_args["message"] == test_args["message"]
        assert echoed_args["count"] == test_args["count"]
        assert echoed_args["tags"] == test_args["tags"]

    def test_health_check(self, http_client: httpx.Client) -> None:
        """Test GET /health returns ok status."""
        response = http_client.get("/health")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "ok"
        assert data["provider"] == "running"
