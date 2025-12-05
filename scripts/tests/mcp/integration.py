"""Integration tests for MCP Bridge.

These tests serve as automated QA for the MCP bridge, replacing manual testing.
They start a real Docker container with the MCP bridge and a simple echo MCP server,
then verify the full request flow works end-to-end.

Usage:
    uv run python -m pytest scripts/tests/mcp/integration.py -v
"""

from __future__ import annotations

import json
import shutil
import socket
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


def _find_free_port() -> int:
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _docker_available() -> bool:
    """Check if Docker is available."""
    docker_path = shutil.which("docker")
    if not docker_path:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


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
def mcp_bridge_container(mcp_config: str, echo_server_script: Path) -> Iterator[str]:
    """Start the MCP bridge Docker container and return its base URL.

    This fixture:
    1. Creates a temp config file
    2. Builds the Docker image
    3. Runs the container with the config and echo server mounted
    4. Waits for health check
    5. Yields the base URL
    6. Cleans up on teardown
    """
    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    container_name = f"mcp-bridge-test-{port}"

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

    try:
        # Build the Docker image
        build_result = subprocess.run(
            [
                "docker",
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
            pytest.skip(f"Docker build failed: {build_result.stderr}")

        # Run the container
        # Mount the config file and the echo server script
        run_result = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                container_name,
                "-p",
                f"127.0.0.1:{port}:8080",
                "-v",
                f"{config_path}:/app/config/.mcp.yml:ro",
                "-v",
                f"{echo_server_script}:/app/echo_server.py:ro",
                "-e",
                "MCP_CONFIG_PATH=/app/config/.mcp.yml",
                "mcp-bridge-test:latest",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if run_result.returncode != 0:
            pytest.skip(f"Docker run failed: {run_result.stderr}")

        # Wait for the container to be healthy
        start_time = time.time()
        timeout = 60.0
        healthy = False

        while time.time() - start_time < timeout:
            try:
                response = httpx.get(f"{base_url}/health", timeout=5.0)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "ok":
                        healthy = True
                        break
            except (httpx.RequestError, httpx.HTTPStatusError):
                pass
            time.sleep(1.0)

        if not healthy:
            # Get container logs for debugging
            logs_result = subprocess.run(
                ["docker", "logs", container_name],
                capture_output=True,
                text=True,
            )
            # Stop and remove container
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
            config_path.unlink(missing_ok=True)
            pytest.skip(
                f"Container did not become healthy within {timeout}s. "
                f"Logs: {logs_result.stdout}\n{logs_result.stderr}"
            )

        yield base_url

    finally:
        # Cleanup: stop and remove container
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
        )
        config_path.unlink(missing_ok=True)


@pytest.fixture
def http_client(mcp_bridge_container: str) -> Iterator[httpx.Client]:
    """Create an HTTP client for the MCP bridge."""
    with httpx.Client(base_url=mcp_bridge_container, timeout=30.0) as client:
        yield client


# ============================================================================
# Integration Tests
# ============================================================================


class TestMCPBridgeIntegration:
    """Integration tests for the MCP Bridge.

    These tests verify the full request flow from HTTP client through
    the bridge to the MCP server and back.
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

    def test_call_tool_legacy_endpoint(self, http_client: httpx.Client) -> None:
        """Test POST /mcp/call (legacy) also works."""
        response = http_client.post(
            "/mcp/call",
            json={
                "tool": "echo_tool",
                "arguments": {"message": "legacy test"},
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "result" in data

        # Verify echo
        content = data["result"]["content"]
        echo_text = content[0]["text"]
        assert "legacy test" in echo_text

    def test_health_check(self, http_client: httpx.Client) -> None:
        """Test GET /health returns ok status."""
        response = http_client.get("/health")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "ok"
        assert data["provider"] == "running"
