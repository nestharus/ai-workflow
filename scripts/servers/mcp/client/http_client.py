#!/usr/bin/env python3
"""HTTP client for MCP bridge server using curl subprocess.

This module provides a lightweight HTTP client that uses curl via subprocess
to call the mcp-bridge REST API. This avoids adding httpx as a dependency.

Transport Mode Precedence:
    1. socket_path constructor argument (highest priority)
    2. MCP_BRIDGE_SOCKET environment variable
    3. base_url constructor argument
    4. MCP_BRIDGE_URL environment variable
    5. Default: http://localhost:8080 (lowest priority)

When using Unix socket mode (options 1-2), a dummy base URL (http://localhost)
is used for curl's URL argument since --unix-socket requires a URL but ignores
the host portion.

The client supports the multi-server usage pattern:
   - Discover servers with `list_servers()` → returns `{"servers": [...]}`
     including per-server `healthy` field
   - Per-server health can be inferred from the `healthy` field in
     `list_servers()` response
   - Inspect tools via `list_server_tools(server)` → returns `{"tools": [...]}`
   - Get specific tool info via `get_server_tool(server, tool_name)` → returns
     tool dict
   - Call tools via `call_server_tool(server, name, arguments, timeout)` →
     returns unwrapped result dict
   - Check overall bridge health with `health_check()` → returns True if healthy

Usage:
    # HTTP mode (default, for non-Docker host usage):
    from scripts.mcp.client.http_client import HttpMCPClient, MCPClientError
    client = HttpMCPClient()  # Uses MCP_BRIDGE_URL or http://localhost:8080

    # Unix socket mode (preferred for Docker):
    # When using the dev-tools compose stack, the host-visible socket path is
    # /tmp/mcp-sockets/mcp-bridge.sock (mapped to /tmp/mcp-bridge.sock inside
    # the container). Use socket_path or MCP_BRIDGE_SOCKET to specify:
    #
    # Host-side (running client on WSL/host against dev-tools bridge):
    client = HttpMCPClient(socket_path="/tmp/mcp-sockets/mcp-bridge.sock")
    # Or via environment:
    # export MCP_BRIDGE_SOCKET=/tmp/mcp-sockets/mcp-bridge.sock
    # client = HttpMCPClient()
    #
    # Container-side (running client in same container namespace as bridge):
    # client = HttpMCPClient(socket_path="/tmp/mcp-bridge.sock")

    # Check overall bridge health
    if client.health_check():
        print("Bridge is healthy")

    # Multi-server: Discover and call specific server
    servers = client.list_servers()
    for server in servers["servers"]:
        if server["healthy"]:  # Per-server health from list_servers()
            tools = client.list_server_tools(server["name"])
            # ...
    result = client.call_server_tool("background-job", "execute", {"command": "ls"})
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any
from urllib.parse import quote


class MCPClientError(Exception):
    """Raised when MCP communication fails."""

    pass


def _validate_and_encode_server(server: str | None, param_name: str = "server") -> str:
    """Validate and URL-encode a server name for safe use in URL paths.

    Strips whitespace, validates non-empty, and URL-encodes for path safety.

    Args:
        server: The server name to validate and encode.
        param_name: Parameter name for error messages (default: "server").

    Returns:
        URL-encoded server name safe for use in URL paths.

    Raises:
        MCPClientError: If server is not a non-empty string after stripping.
    """
    if not isinstance(server, str):
        raise MCPClientError(f"{param_name} parameter must be a non-empty string")
    server = server.strip()
    if not server:
        raise MCPClientError(f"{param_name} parameter must be a non-empty string")
    # URL-encode to handle special characters (/, #, %, ?, etc.)
    return quote(server, safe="")


class HttpMCPClient:
    """HTTP client for MCP bridge server using curl subprocess."""

    def __init__(
        self,
        base_url: str | None = None,
        socket_path: str | None = None,
    ) -> None:
        """Initialize client.

        Transport mode is determined by precedence (highest to lowest):
        1. socket_path argument
        2. MCP_BRIDGE_SOCKET env var
        3. base_url argument
        4. MCP_BRIDGE_URL env var
        5. Default http://localhost:8080

        When socket_path is set (directly or via env), base_url is ignored
        and a dummy URL (http://localhost) is used for curl compatibility.

        Args:
            base_url: Bridge server URL. Only used if socket_path is not set.
                      Defaults to MCP_BRIDGE_URL env var or http://localhost:8080.
            socket_path: Path to Unix socket. Takes precedence over base_url.
                        Defaults to MCP_BRIDGE_SOCKET env var if set.
        """
        # Precedence: socket_path arg > MCP_BRIDGE_SOCKET env > base_url arg >
        # MCP_BRIDGE_URL env > default
        if socket_path is not None and not isinstance(socket_path, str):
            raise MCPClientError("socket_path must be a string path")

        # Resolve socket path first (arg > env)
        env_socket = os.environ.get("MCP_BRIDGE_SOCKET", "")
        p = (socket_path if socket_path is not None else env_socket).strip()
        self.socket_path = p or None

        if self.socket_path:
            # Unix socket mode - base_url is ignored, use dummy hostname for curl
            self.base_url = "http://localhost"
        else:
            # HTTP mode - validate and resolve base_url
            if base_url is not None and not isinstance(base_url, str):
                raise MCPClientError("base_url must be a string URL")
            if base_url is None:
                base_url = os.environ.get("MCP_BRIDGE_URL", "http://localhost:8080")
            base_url = base_url.strip().rstrip("/")
            if not base_url:
                raise MCPClientError("Invalid base_url: empty or missing host")
            if base_url.endswith("://"):
                raise MCPClientError(f"Invalid base_url: scheme without host: {base_url}")
            self.base_url = base_url

    def _request_json(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        try:
            if timeout <= 0:
                msg = "timeout must be > 0"
                raise ValueError(msg)
            max_time_str = str(int(timeout + 1))
        except (TypeError, ValueError, OverflowError) as e:
            raise MCPClientError(f"Invalid timeout: {timeout}") from e

        # Build curl command
        cmd = [
            "curl",
            "-sS",
            "--fail-with-body",
            "--max-time",
            max_time_str,
        ]

        # Add Unix socket option if configured
        if self.socket_path:
            cmd.extend(["--unix-socket", self.socket_path])

        payload_json = None
        if method == "POST":
            if payload is None:
                raise MCPClientError("POST request requires payload")
            try:
                payload_json = json.dumps(payload)
            except (TypeError, ValueError) as e:
                raise MCPClientError(f"Failed to serialize request: {e}") from e

            cmd.extend(
                [
                    "-X",
                    "POST",
                    url,
                    "-H",
                    "Content-Type: application/json",
                    "--data-binary",
                    "@-",
                ]
            )
        else:
            cmd.append(url)

        try:
            result = subprocess.run(
                cmd,
                input=payload_json,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout + 5,
            )
        except subprocess.TimeoutExpired as e:
            raise MCPClientError(f"Request timed out after {timeout}s") from e
        except OSError as e:
            raise MCPClientError(f"Failed to run curl: {e}") from e
        except UnicodeError as e:
            raise MCPClientError(f"Invalid UTF-8 in response: {e}") from e

        # Handle curl exit codes
        if result.returncode == 7:
            if self.socket_path:
                raise MCPClientError(
                    f"Cannot connect to mcp-bridge at {self.socket_path}. "
                    "Socket not available. Ensure mcp-bridge container is running "
                    "and socket is mounted."
                )
            else:
                raise MCPClientError(
                    f"Cannot connect to mcp-bridge at {self.base_url}. "
                    "Ensure the MCP bridge is running. For local development, run "
                    "'uv run dev.ensure-env' (preferred) or "
                    "'docker compose -p ai-workflow-devtools "
                    "-f docker-compose.dev.yml up -d mcp-bridge'."
                )
        elif result.returncode == 28:
            raise MCPClientError(f"Request timed out after {timeout}s")
        elif result.returncode == 22:
            # HTTP error (from --fail-with-body), try to parse response body for details
            stdout = result.stdout.strip() if result.stdout else ""
            if stdout:
                try:
                    error_response = json.loads(stdout)
                    if isinstance(error_response, dict) and "error" in error_response:
                        error = error_response["error"]
                        if isinstance(error, dict):
                            error_type = error.get("type", "UNKNOWN")
                            message = error.get("message", str(error))
                            raise MCPClientError(f"[{error_type}] {message}")
                        raise MCPClientError(f"Server error: {error}")
                except json.JSONDecodeError:
                    pass
            error_msg = result.stderr.strip() if result.stderr else "HTTP error"
            raise MCPClientError(f"HTTP request failed: {error_msg}")
        elif result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else f"exit code {result.returncode}"
            raise MCPClientError(f"curl failed: {error_msg}")

        # Parse response JSON
        stdout = result.stdout.strip()
        if not stdout:
            raise MCPClientError("Empty response from server")

        try:
            response = json.loads(stdout)
        except json.JSONDecodeError as e:
            raise MCPClientError(f"Invalid JSON response: {e} - {stdout[:200]}") from e

        if not isinstance(response, dict):
            raise MCPClientError(
                f"Invalid response type: expected JSON object, got {type(response).__name__}"
            )

        # Check for error envelope
        if "error" in response:
            error = response["error"]
            if isinstance(error, dict):
                error_type = error.get("type", "UNKNOWN")
                message = error.get("message", str(error))
                raise MCPClientError(f"[{error_type}] {message}")
            raise MCPClientError(f"Server error: {error}")

        return response

    def list_servers(self) -> dict[str, Any]:
        """List all MCP servers.

        Uses a 5-second timeout since this endpoint queries the local in-memory
        server registry and does not require MCP communication.

        Returns:
            Dict with servers list and health status for each server.

        Raises:
            MCPClientError: On connection failure, HTTP error, or timeout
        """
        url = f"{self.base_url}/mcp/servers"
        response = self._request_json("GET", url, payload=None, timeout=5.0)
        return response

    def list_server_tools(self, server: str) -> dict[str, Any]:
        """List tools available on a specific server.

        Uses a 10-second timeout to allow for MCP server communication.

        Args:
            server: Name of the server.

        Returns:
            Dict with list of available tools on the server.

        Raises:
            MCPClientError: If server is invalid or on connection failure
        """
        encoded_server = _validate_and_encode_server(server)
        url = f"{self.base_url}/mcp/{encoded_server}/tools"
        response = self._request_json("GET", url, payload=None, timeout=10.0)
        return response

    def get_server_tool(self, server: str, tool_name: str) -> dict[str, Any]:
        """Get information about a specific tool on a server.

        Uses a 10-second timeout to allow for MCP server communication.

        Args:
            server: Name of the server.
            tool_name: Name of the tool.

        Returns:
            Dict with tool information.

        Raises:
            MCPClientError: If parameters are invalid or on connection failure
        """
        encoded_server = _validate_and_encode_server(server)
        if not isinstance(tool_name, str) or not tool_name:
            raise MCPClientError("tool_name parameter must be a non-empty string")
        url = f"{self.base_url}/mcp/{encoded_server}/tools/{tool_name}"
        response = self._request_json("GET", url, payload=None, timeout=10.0)
        return response

    def call_server_tool(
        self,
        server: str,
        name: str,
        arguments: dict[str, Any],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Call a specific tool on a server.

        The timeout parameter controls both the server-side timeout and curl
        behavior. Curl's --max-time is set to timeout + 1 second as a buffer,
        and the subprocess timeout is set to timeout + 5 seconds to allow for
        process overhead.

        Args:
            server: Name of the server.
            name: Tool name.
            arguments: Tool arguments dict.
            timeout: Request timeout in seconds (default 30.0).

        Returns:
            Result dict from the tool call.

        Raises:
            MCPClientError: If parameters are invalid or on connection failure
        """
        encoded_server = _validate_and_encode_server(server)
        if not isinstance(name, str) or not name:
            raise MCPClientError("name parameter must be a non-empty string")
        url = f"{self.base_url}/mcp/{encoded_server}/call"
        # Use canonical field name 'timeout_seconds' per MCPCallRequest schema
        payload = {"tool": name, "arguments": arguments, "timeout_seconds": timeout}

        response = self._request_json("POST", url, payload, timeout)

        if "result" in response:
            result_dict = response["result"]
            if not isinstance(result_dict, dict):
                raise MCPClientError(
                    f"Invalid result type: expected dict, got {type(result_dict).__name__}"
                )
            return result_dict

        return response

    def health_check(self) -> bool:
        """Check if bridge is healthy.

        Returns:
            True if bridge responds with 200, False otherwise
        """
        import os as _os

        url = f"{self.base_url}/health"

        cmd = [
            "curl",
            "-sS",
            "-o",
            _os.devnull,  # Cross-platform null sink
            "-w",
            "%{http_code}",
            "--max-time",
            "5",
        ]

        # Add Unix socket option if configured
        if self.socket_path:
            cmd.extend(["--unix-socket", self.socket_path])

        cmd.append(url)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError):
            return False

        if result.returncode != 0:
            return False

        # Check HTTP status code
        try:
            status_code = int(result.stdout.strip())
        except ValueError:
            return False
        else:
            return status_code == 200
