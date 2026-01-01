#!/usr/bin/env python3
"""Native socket client for MCP bridge server.

This module provides a lightweight socket-based client that communicates with
the mcp-bridge via Unix sockets using JSONL (newline-delimited JSON) protocol.
This replaces the curl-based HTTP client for improved performance and reduced
external dependencies.

Transport Mode Precedence:
    1. socket_path constructor argument (highest priority)
    2. MCP_BRIDGE_SOCKET environment variable
    3. base_url constructor argument (for backward compatibility)
    4. MCP_BRIDGE_URL environment variable
    5. Default socket: /tmp/mcp-bridge.sock (lowest priority)

Note: base_url is retained for backward compatibility but ignored when socket
mode is active (which is the default). The socket-based client uses native
JSONL protocol instead of HTTP.

The client supports the multi-server usage pattern:
   - Discover servers with `list_servers()` -> returns `{"servers": [...]}`
     including per-server `healthy` field
   - Per-server health can be inferred from the `healthy` field in
     `list_servers()` response
   - Inspect tools via `list_server_tools(server)` -> returns `{"tools": [...]}`
   - Get specific tool info via `get_server_tool(server, tool_name)` -> returns
     tool dict
   - Call tools via `call_server_tool(server, name, arguments, timeout)` ->
     returns unwrapped result dict
   - Check overall bridge health with `health_check()` -> returns True if healthy

Usage:
    # Unix socket mode (default, preferred for Docker):
    from scripts.mcp.client.http_client import HttpMCPClient, MCPClientError
    client = HttpMCPClient()  # Uses MCP_BRIDGE_SOCKET or /tmp/mcp-bridge.sock

    # Explicit socket path:
    client = HttpMCPClient(socket_path="/tmp/mcp-sockets/mcp-bridge.sock")

    # Or via environment:
    # export MCP_BRIDGE_SOCKET=/tmp/mcp-sockets/mcp-bridge.sock
    # client = HttpMCPClient()

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
import socket
import uuid
from typing import Any


class MCPClientError(Exception):
    """Raised when MCP communication fails."""

    pass


def _validate_server(server: str | None, param_name: str = "server") -> str:
    """Validate a server name for JSONL protocol.

    Strips whitespace and validates non-empty. Unlike HTTP URL paths, JSONL
    protocol sends server names as JSON string values, so URL-encoding is
    not needed and would break server lookups.

    Args:
        server: The server name to validate.
        param_name: Parameter name for error messages (default: "server").

    Returns:
        Validated server name (stripped of whitespace).

    Raises:
        MCPClientError: If server is not a non-empty string after stripping.
    """
    if not isinstance(server, str):
        raise MCPClientError(f"{param_name} parameter must be a non-empty string")
    server = server.strip()
    if not server:
        raise MCPClientError(f"{param_name} parameter must be a non-empty string")
    return server


def _validate_tool_name(tool_name: str | None, param_name: str = "tool_name") -> str:
    """Validate a tool name for JSONL protocol.

    Args:
        tool_name: The tool name to validate.
        param_name: Parameter name for error messages.

    Returns:
        Validated tool name (stripped of whitespace).

    Raises:
        MCPClientError: If tool_name is not a non-empty string.
    """
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise MCPClientError(f"{param_name} parameter must be a non-empty string")
    return tool_name.strip()


# Default socket path for MCP bridge
DEFAULT_SOCKET_PATH = "/tmp/mcp-bridge.sock"


class MCPSocketClient:
    """Native socket client for MCP bridge server using Unix sockets and JSONL protocol."""

    def __init__(
        self,
        base_url: str | None = None,
        socket_path: str | None = None,
    ) -> None:
        """Initialize client.

        Transport mode is determined by precedence (highest to lowest):
        1. socket_path argument
        2. MCP_BRIDGE_SOCKET env var
        3. base_url argument (for backward compatibility, ignored in socket mode)
        4. MCP_BRIDGE_URL env var (for backward compatibility, ignored in socket mode)
        5. Default socket: /tmp/mcp-bridge.sock

        When socket mode is active (which is the default), base_url is ignored.

        Args:
            base_url: Bridge server URL. Retained for backward compatibility but
                      ignored in socket mode. Defaults to MCP_BRIDGE_URL env var
                      or http://localhost:8080.
            socket_path: Path to Unix socket. Takes precedence over base_url.
                        Defaults to MCP_BRIDGE_SOCKET env var or /tmp/mcp-bridge.sock.
        """
        # Precedence: socket_path arg > MCP_BRIDGE_SOCKET env > default socket
        if socket_path is not None and not isinstance(socket_path, str):
            raise MCPClientError("socket_path must be a string path")

        # Resolve socket path (arg > env > default)
        env_socket = os.environ.get("MCP_BRIDGE_SOCKET", "")
        p = (socket_path if socket_path is not None else env_socket).strip()
        self.socket_path = p or DEFAULT_SOCKET_PATH

        # Validate and store base_url for backward compatibility
        # In socket mode, base_url is stored but not used for actual communication
        if base_url is not None and not isinstance(base_url, str):
            raise MCPClientError("base_url must be a string URL")

        if base_url is not None:
            base_url = base_url.strip().rstrip("/")
            if not base_url:
                raise MCPClientError("Invalid base_url: empty or missing host")
            if base_url.endswith("://"):
                raise MCPClientError(f"Invalid base_url: scheme without host: {base_url}")
        else:
            base_url = os.environ.get("MCP_BRIDGE_URL", "http://localhost:8080")

        self.base_url = base_url

    def _request_jsonl(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send a JSONL request over Unix socket and return the response.

        Args:
            method: The method name (e.g., "list_servers", "call_tool").
            params: Request parameters (merged with method and id).
            timeout: Request timeout in seconds.

        Returns:
            The response dict (result from success envelope, or raises on error).

        Raises:
            MCPClientError: On connection failure, timeout, or protocol error.
        """
        try:
            if timeout <= 0:
                msg = "timeout must be > 0"
                raise ValueError(msg)
        except (TypeError, ValueError, OverflowError) as e:
            raise MCPClientError(f"Invalid timeout: {timeout}") from e

        # Build request envelope
        request_id = str(uuid.uuid4())
        request: dict[str, Any] = {
            "id": request_id,
            "method": method,
        }
        if params:
            request.update(params)

        # Serialize to JSONL (JSON + newline)
        try:
            request_json = json.dumps(request)
        except (TypeError, ValueError) as e:
            raise MCPClientError(f"Failed to serialize request: {e}") from e

        request_bytes = (request_json + "\n").encode("utf-8")

        # Connect and communicate
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(timeout)
            try:
                sock.connect(self.socket_path)
            except OSError as e:
                raise MCPClientError(
                    f"Cannot connect to mcp-bridge at {self.socket_path}. "
                    "Socket not available. Ensure mcp-bridge container is running "
                    "and socket is mounted."
                ) from e

            # Send request
            try:
                sock.sendall(request_bytes)
            except TimeoutError as e:
                raise MCPClientError(f"Request timed out after {timeout}s") from e
            except OSError as e:
                raise MCPClientError(f"Failed to send request: {e}") from e

            # Read response (JSONL - read until newline)
            response_buffer = bytearray()
            try:
                while True:
                    chunk = sock.recv(65536)  # 64KB chunks
                    if not chunk:
                        break
                    response_buffer.extend(chunk)
                    # Check for complete JSONL message (newline terminated)
                    if b"\n" in response_buffer:
                        break
            except TimeoutError as e:
                raise MCPClientError(f"Request timed out after {timeout}s") from e
            except OSError as e:
                raise MCPClientError(f"Failed to read response: {e}") from e

        finally:
            sock.close()

        # Parse response
        stdout = response_buffer.decode("utf-8").strip()
        if not stdout:
            raise MCPClientError("Empty response from server")

        # Extract first line (JSONL)
        if "\n" in stdout:
            stdout = stdout.split("\n")[0]

        try:
            response = json.loads(stdout)
        except json.JSONDecodeError as e:
            raise MCPClientError(f"Invalid JSON response: {e} - {stdout[:200]}") from e

        if not isinstance(response, dict):
            raise MCPClientError(
                f"Invalid response type: expected JSON object, got {type(response).__name__}"
            )

        # Check for error envelope (socket protocol format)
        # Format: {"id": "...", "status": "error", "error": {"type": "...", "message": "..."}}
        if response.get("status") == "error":
            if "error" in response:
                error = response["error"]
                if isinstance(error, dict):
                    error_type = error.get("type", "UNKNOWN")
                    message = error.get("message", str(error))
                    raise MCPClientError(f"[{error_type}] {message}")
                raise MCPClientError(f"Server error: {error}")
            # status == "error" without error payload - raise generic error
            raise MCPClientError("Server returned error status without details")

        # Extract result from success envelope
        # Format: {"id": "...", "status": "success", "result": {...}}
        if response.get("status") == "success" and "result" in response:
            return response["result"]  # type: ignore[no-any-return]

        # Fallback: return response as-is (for non-envelope responses like health check)
        return response

    def list_servers(self) -> dict[str, Any]:
        """List all MCP servers.

        Uses a 5-second timeout since this endpoint queries the local in-memory
        server registry and does not require MCP communication.

        Returns:
            Dict with servers list and health status for each server.

        Raises:
            MCPClientError: On connection failure, protocol error, or timeout
        """
        response = self._request_jsonl("list_servers", timeout=5.0)
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
        validated_server = _validate_server(server)
        response = self._request_jsonl(
            "list_tools",
            params={"server": validated_server},
            timeout=10.0,
        )
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
        validated_server = _validate_server(server)
        tool_name = _validate_tool_name(tool_name)
        response = self._request_jsonl(
            "get_server_tool",
            params={"server": validated_server, "tool_name": tool_name},
            timeout=10.0,
        )
        return response

    def call_server_tool(
        self,
        server: str,
        name: str,
        arguments: dict[str, Any],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Call a specific tool on a server.

        The timeout parameter controls both the server-side timeout and socket
        behavior.

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
        validated_server = _validate_server(server)
        name = _validate_tool_name(name, param_name="name")

        response = self._request_jsonl(
            "call_tool",
            params={
                "server": validated_server,
                "tool": name,
                "arguments": arguments,
                "timeout_seconds": timeout,
            },
            timeout=timeout,
        )

        # Extract result from response envelope if present
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
            True if bridge responds with status="ok", False otherwise
        """
        try:
            response = self._request_jsonl("health", timeout=5.0)
            # Health response format: {"status": "ok", "provider": "running"}
            return response.get("status") == "ok"
        except MCPClientError:
            return False


# Backward compatibility alias - HttpMCPClient now uses socket protocol
HttpMCPClient = MCPSocketClient


__all__ = [
    "DEFAULT_SOCKET_PATH",
    "HttpMCPClient",
    "MCPClientError",
    "MCPSocketClient",
]
