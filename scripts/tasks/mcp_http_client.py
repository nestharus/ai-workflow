#!/usr/bin/env python3
"""HTTP client for MCP bridge server using curl subprocess.

This module provides a lightweight HTTP client that uses curl via subprocess
to call the mcp-bridge REST API. This avoids adding httpx as a dependency.

Usage:
    from scripts.tasks.mcp_http_client import HttpMCPClient, MCPClientError

    client = HttpMCPClient()  # Uses MCP_BRIDGE_URL env var or localhost:8080

    # Check if bridge is healthy
    if client.health_check():
        # Call an MCP tool
        result = client.call_tool("execute", {"command": "echo hello"})
        print(result)
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any


class MCPClientError(Exception):
    """Raised when MCP communication fails."""

    pass


class HttpMCPClient:
    """HTTP client for MCP bridge server using curl subprocess."""

    def __init__(self, base_url: str | None = None) -> None:
        """Initialize client.

        Args:
            base_url: Bridge server URL. Defaults to MCP_BRIDGE_URL env var
                      or http://localhost:8080
        """
        if base_url is None:
            base_url = os.environ.get("MCP_BRIDGE_URL", "http://localhost:8080")
        self.base_url = base_url.rstrip("/")

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Call an MCP tool via the bridge.

        Args:
            name: Tool name (e.g., "execute", "status", "output", "kill", "list")
            arguments: Tool arguments dict
            timeout: Request timeout in seconds

        Returns:
            Result dict from MCP tool call

        Raises:
            MCPClientError: On connection failure, HTTP error, or timeout
        """
        url = f"{self.base_url}/mcp/call"
        payload = {"tool": name, "arguments": arguments, "timeout": timeout}

        try:
            payload_json = json.dumps(payload)
        except (TypeError, ValueError) as e:
            raise MCPClientError(f"Failed to serialize request: {e}") from e

        # Build curl command
        # -s: silent mode (no progress)
        # -S: show errors even in silent mode
        # -X POST: HTTP POST method
        # -H: Content-Type header
        # --data-binary @-: read data from stdin (avoids shell quoting issues)
        # --max-time: timeout in seconds
        cmd = [
            "curl",
            "-sS",
            "-X",
            "POST",
            url,
            "-H",
            "Content-Type: application/json",
            "--data-binary",
            "@-",
            "--max-time",
            str(int(timeout + 1)),  # Add 1 second buffer for curl
        ]

        try:
            result = subprocess.run(
                cmd,
                input=payload_json,
                capture_output=True,
                text=True,
                timeout=timeout + 5,  # Extra buffer for subprocess timeout
            )
        except subprocess.TimeoutExpired as e:
            raise MCPClientError(f"Request timed out after {timeout}s") from e
        except OSError as e:
            raise MCPClientError(f"Failed to run curl: {e}") from e

        # Handle curl exit codes
        if result.returncode == 7:
            # Connection refused
            raise MCPClientError(
                f"Cannot connect to mcp-bridge at {self.base_url}. "
                "Docker environment not running. Run: "
                "docker-compose -f docker-compose.dev.yml up -d"
            )
        elif result.returncode == 28:
            # Timeout
            raise MCPClientError(f"Request timed out after {timeout}s")
        elif result.returncode != 0:
            # Other curl error
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

        # Check for error in response
        if isinstance(response, dict) and "error" in response:
            error = response["error"]
            message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            raise MCPClientError(f"Server error: {message}")

        return response  # type: ignore[no-any-return]

    def health_check(self) -> bool:
        """Check if bridge is healthy.

        Returns:
            True if bridge responds with 200, False otherwise
        """
        url = f"{self.base_url}/health"

        cmd = [
            "curl",
            "-sS",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-time",
            "5",
            url,
        ]

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
