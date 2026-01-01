"""MCP SSE client for HTTP-based MCP servers.

This module provides the MCPSSEClient class that handles communication
with MCP servers using Server-Sent Events (SSE) transport, such as
Linear's MCP server.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import httpx

from scripts.servers.mcp.manager import MCPError


class MCPSSEError(MCPError):
    """Raised when MCP SSE communication fails.

    Inherits from MCPError so callers can catch all MCP-related errors
    with a single exception type.
    """

    pass


class MCPSSEClient:
    """Client for SSE-based MCP servers.

    This class handles:
    - Connecting to SSE MCP endpoints
    - JSON-RPC request/response over HTTP POST
    - Thread-safe request handling
    - Health tracking for real remote liveness detection
    """

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        max_consecutive_failures: int = 3,
        max_staleness_seconds: float = 300.0,
    ) -> None:
        """Initialize the SSE MCP client.

        Args:
            url: Base URL of the SSE MCP server (e.g., https://mcp.linear.app/sse).
            headers: Optional headers to include in requests (e.g., Authorization).
            timeout: Default timeout for requests in seconds.
            max_consecutive_failures: Number of consecutive failures before marking
                the client as unhealthy. Defaults to 3.
            max_staleness_seconds: Maximum time in seconds since last successful
                request before considering the connection stale. Defaults to 300.0
                (5 minutes).
        """
        self._url = url.rstrip("/")
        self._headers = headers or {}
        self._timeout = timeout
        self._lock = threading.Lock()
        self._request_id = 0
        self._session_id: str | None = None
        self._client = httpx.Client(timeout=timeout)
        self._initialized = False

        # Health tracking for real remote liveness detection
        self._last_success_time: float | None = None
        self._consecutive_failures = 0
        self._max_consecutive_failures = max_consecutive_failures
        self._max_staleness_seconds = max_staleness_seconds

    def _get_request_id(self) -> int:
        """Get a unique request ID."""
        self._request_id += 1
        return self._request_id

    def _record_failure(self) -> None:
        """Record a failure and reset initialized state if threshold is reached.

        Increments _consecutive_failures and, when the threshold
        _max_consecutive_failures is reached or exceeded, sets _initialized to False.
        """
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._max_consecutive_failures:
            self._initialized = False

    def _initialize(self) -> None:
        """Perform MCP initialization handshake.

        Raises:
            MCPSSEError: If initialization fails.
        """
        if self._initialized:
            return

        # Recreate client if it was closed
        if self._client.is_closed:
            self._client = httpx.Client(timeout=self._timeout)

        # Connect to SSE endpoint to get session
        try:
            # Some SSE servers require establishing a session first
            # For Linear, the SSE endpoint handles both connection and messages
            _init_result = self._send_request(
                method="initialize",
                params={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "mcp-bridge",
                        "version": "1.0.0",
                    },
                },
            )

            # Send initialized notification
            self._send_notification("notifications/initialized", {})
            self._initialized = True
            self._last_success_time = time.monotonic()
            self._consecutive_failures = 0

        except Exception as e:
            self._initialized = False
            raise MCPSSEError(f"Failed to initialize SSE connection: {e}") from e

    def _send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification (no response expected).

        Args:
            method: Method name.
            params: Method parameters.

        Raises:
            MCPSSEError: If sending fails.
        """
        notification: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params:
            notification["params"] = params

        try:
            response = self._client.post(
                f"{self._url}/message",
                json=notification,
                headers=self._headers,
            )
            response.raise_for_status()
            # Notifications don't expect a response body
        except httpx.HTTPError as e:
            raise MCPSSEError(f"Failed to send notification: {e}") from e
        except (TypeError, ValueError) as e:
            raise MCPSSEError(f"Failed to serialize notification: {e}") from e

    def _send_request(
        self,
        method: str,
        params: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for response.

        Args:
            method: Method name.
            params: Method parameters.
            timeout: Optional timeout override.

        Returns:
            Result dict from response.

        Raises:
            MCPSSEError: If request fails.
        """
        request_id = self._get_request_id()
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        try:
            # For SSE servers, we typically POST to a message endpoint
            # and receive the response directly or via SSE
            response = self._client.post(
                f"{self._url}/message",
                json=request,
                headers=self._headers,
                timeout=timeout or self._timeout,
            )
            response.raise_for_status()

            result = response.json()

            if not isinstance(result, dict):
                self._record_failure()
                raise MCPSSEError(
                    f"Invalid MCP response: expected JSON object, got {type(result).__name__}"
                )

            if "error" in result:
                self._record_failure()
                error = result["error"]
                if isinstance(error, dict):
                    code = error.get("code", -1)
                    message = error.get("message", "Unknown error")
                    raise MCPSSEError(f"MCP error {code}: {message}")
                raise MCPSSEError(f"MCP error: {error}")

            if "result" not in result:
                self._record_failure()
                raise MCPSSEError("Invalid MCP response: missing 'result'")

            response_result = result["result"]
            if not isinstance(response_result, dict):
                self._record_failure()
                result_type = type(response_result).__name__
                raise MCPSSEError(
                    f"Invalid MCP response: expected result object, got {result_type}"
                )

            # Success - update health tracking
            self._last_success_time = time.monotonic()
            self._consecutive_failures = 0
            return response_result

        except httpx.HTTPError as e:
            self._record_failure()
            raise MCPSSEError(f"HTTP error: {e}") from e
        except json.JSONDecodeError as e:
            self._record_failure()
            raise MCPSSEError(f"Invalid JSON response: {e}") from e
        except (TypeError, ValueError) as e:
            self._record_failure()
            raise MCPSSEError(f"Failed to serialize request: {e}") from e

    def is_alive(self) -> bool:
        """Check if the SSE connection is alive.

        Returns True if:
        - Client is initialized AND
        - Has had at least one successful request AND
        - Consecutive failures are below threshold AND
        - Last success was within the staleness window

        This reflects real remote liveness rather than just local initialization state.

        Returns:
            True if client appears healthy, False otherwise.
        """
        # Read fields under lock to prevent race with close() or other methods
        with self._lock:
            initialized = self._initialized
            last_success_time = self._last_success_time
            consecutive_failures = self._consecutive_failures
            max_failures = self._max_consecutive_failures
            max_staleness = self._max_staleness_seconds

        if not initialized:
            return False
        if last_success_time is None:
            return False
        if consecutive_failures >= max_failures:
            return False

        # Consider stale if no successful requests in last 5 minutes
        # Uses monotonic time to be immune to system clock changes
        return time.monotonic() - last_success_time <= max_staleness

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Call an MCP tool and return the result.

        Args:
            name: Tool name.
            arguments: Tool arguments dict.
            timeout: Per-call timeout in seconds.

        Returns:
            Result dict from tool call.

        Raises:
            MCPSSEError: On error or timeout.
        """
        with self._lock:
            if not self._initialized:
                self._initialize()

            result = self._send_request(
                method="tools/call",
                params={"name": name, "arguments": arguments},
                timeout=timeout,
            )
            return result

    def list_tools(self, timeout: float = 30.0) -> dict[str, Any]:
        """List available MCP tools.

        Args:
            timeout: Per-call timeout in seconds.

        Returns:
            Dict containing the tools list.

        Raises:
            MCPSSEError: On error or timeout.
        """
        with self._lock:
            if not self._initialized:
                self._initialize()

            result = self._send_request(
                method="tools/list",
                params={},
                timeout=timeout,
            )
            return result

    def close(self) -> None:
        """Close the HTTP client and reset health tracking."""
        with self._lock:
            self._client.close()
            self._initialized = False
            self._last_success_time = None
            self._consecutive_failures = 0


__all__ = ["MCPSSEClient", "MCPSSEError"]
