r"""MCP stdio manager for communicating with MCP provider subprocesses.

This module provides the MCPStdioManager class that handles spawning and
communicating with an MCP provider subprocess using newline-delimited
JSON-RPC over stdio (as used by FastMCP).

Protocol Framing Decision:
    The original specified Content-Length framing for JSON-RPC
    messages (similar to LSP). However, this implementation uses newline-delimited
    JSON (JSONL) instead, which is the format used by FastMCP and mcp-background-job.

    Rationale:
    - mcp-background-job uses JSONL format natively
    - FastMCP ecosystem standardizes on JSONL
    - Simpler implementation without header parsing
    - Compatible with existing MCP clients

    The initialize/initialized handshake remains the same:
    1. Client sends {"jsonrpc":"2.0","id":1,"method":"initialize","params":{...}}\n
    2. Server responds with {"jsonrpc":"2.0","id":1,"result":{...}}\n
    3. Client sends {"jsonrpc":"2.0","method":"notifications/initialized"}\n
"""

from __future__ import annotations

import contextlib
import json
import os
import select
import shlex
import subprocess
import threading
import time
from typing import Any, Protocol, runtime_checkable


class MCPError(Exception):
    """Raised when MCP communication fails."""

    pass


class MCPTimeoutError(MCPError):
    """Raised when MCP call times out."""

    pass


class MCPBusyError(MCPError):
    """Raised when provider lock cannot be acquired (backpressure)."""

    def __init__(self, message: str = "Provider is busy", retry_after_ms: int = 1000) -> None:
        """Initialize with retry hint.

        Args:
            message: Error message.
            retry_after_ms: Recommended retry interval in milliseconds.
        """
        super().__init__(message)
        self.retry_after_ms = retry_after_ms


class MCPProviderCrashedError(MCPError):
    """Raised when provider subprocess crashed and was restarted."""

    def __init__(self, message: str = "Provider crashed and was restarted") -> None:
        """Initialize with crash message.

        Args:
            message: Error message indicating state was lost.
        """
        super().__init__(message)


@runtime_checkable
class MCPClient(Protocol):
    """Protocol for MCP client implementations.

    All MCP clients (stdio, SSE, etc.) must implement this interface.
    """

    def is_alive(self) -> bool:
        """Check if the client is connected and operational."""
        ...

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Call an MCP tool and return the result."""
        ...

    def list_tools(self, timeout: float = 30.0) -> dict[str, Any]:
        """List available MCP tools."""
        ...

    def close(self) -> None:
        """Close the client and release resources."""
        ...


class MCPStdioManager:
    """Manages an MCP provider subprocess using stdio communication.

    This class handles:
    - Spawning the MCP subprocess on init
    - Newline-delimited JSON-RPC communication (FastMCP format)
    - Thread-safe request/response handling
    - Subprocess crash detection and restart capability

    Note:
        This implementation uses select.select() for non-blocking I/O,
        which is Unix-only. The MCP bridge is designed to run in Docker
        containers on Linux. Windows support would require a different
        approach (e.g., reader thread + queue).
    """

    DEFAULT_COMMAND = "uvx mcp-background-job"

    def __init__(
        self,
        command: str | None = None,
        startup_timeout: float = 10.0,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        """Initialize the MCP manager and start the subprocess.

        Args:
            command: Command to start MCP server. Defaults to MCP_COMMAND env var
                or 'uvx mcp-background-job'.
            startup_timeout: Seconds to wait for server startup.
            cwd: Working directory for the subprocess. Defaults to current directory.
            env: Environment variables for the subprocess. If provided, these are
                merged with os.environ (env values take precedence). This avoids
                mutating the global os.environ and ensures proper isolation when
                multiple servers are initialized concurrently.

        Raises:
            MCPError: If server fails to start or times out.
        """
        self._command = command or os.environ.get("MCP_COMMAND", self.DEFAULT_COMMAND)
        self._startup_timeout = startup_timeout
        self._cwd = cwd
        self._env = env
        self._request_id = 0
        self._lock = threading.Lock()
        self._stderr_lock = threading.Lock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._stderr_buffer = bytearray()
        self._stderr_thread: threading.Thread | None = None

        try:
            self._start_subprocess()
            self._initialize()
        except MCPError:
            self._shutdown(timeout=1.0)
            raise
        except Exception as e:
            self._shutdown(timeout=1.0)
            raise MCPError(f"Failed to start MCP server: {e}") from e

    def _initialize(self) -> None:
        """Send MCP initialize handshake (takes lock).

        MCP protocol requires:
        1. Client sends 'initialize' request
        2. Server responds with capabilities
        3. Client sends 'initialized' notification

        Raises:
            MCPError: If initialization fails.
        """
        with self._lock:
            self._do_initialize_unlocked()

    def _do_initialize_unlocked(self) -> None:
        """Send MCP initialize handshake without taking lock.

        Must be called while already holding self._lock.

        Raises:
            MCPError: If initialization fails.
        """
        # Send initialize request
        init_result = self._send_request_unlocked(
            method="initialize",
            params={
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "mcp-bridge",
                    "version": "1.0.0",
                },
            },
            timeout=10.0,
        )

        # Log server info if available
        server_info = init_result.get("serverInfo", {})
        if server_info:
            _server_name = server_info.get("name", "unknown")
            _server_version = server_info.get("version", "unknown")
            # Could add logging here if needed

        # Send initialized notification (no response expected)
        self._send_notification_unlocked("notifications/initialized", {})

    def _send_notification_unlocked(
        self, method: str, params: dict[str, Any] | None = None
    ) -> None:
        """Send a JSON-RPC notification (no response expected).

        Must be called while already holding self._lock.
        Uses newline-delimited JSON format (FastMCP).

        Args:
            method: Method name.
            params: Method parameters (optional for notifications).

        Raises:
            MCPError: If sending fails.
        """
        if self._proc is None or self._proc.stdin is None:
            raise MCPError("MCP server not running")

        notification: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params:
            notification["params"] = params

        try:
            # Newline-delimited JSON format
            data = (json.dumps(notification) + "\n").encode("utf-8")
        except (TypeError, ValueError) as e:
            raise MCPError(f"Failed to serialize notification: {e}") from e

        try:
            total = 0
            while total < len(data):
                written = self._proc.stdin.write(data[total:])
                if written is None or written == 0:
                    raise MCPError("Failed to send notification: partial write")
                total += written
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as e:
            raise MCPError(f"Failed to send notification: {e}") from e

    def _send_request_unlocked(
        self,
        method: str,
        params: dict[str, Any],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for response.

        Must be called while already holding self._lock.
        Uses newline-delimited JSON format (FastMCP).

        Args:
            method: Method name.
            params: Method parameters.
            timeout: Timeout in seconds.

        Returns:
            Result dict from response.

        Raises:
            MCPError: If request fails or times out.
        """
        if self._proc is None or self._proc.stdin is None:
            raise MCPError("MCP server not running")

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        try:
            # Newline-delimited JSON format
            data = (json.dumps(request) + "\n").encode("utf-8")
        except (TypeError, ValueError) as e:
            raise MCPError(f"Failed to serialize request: {e}") from e

        try:
            total = 0
            while total < len(data):
                written = self._proc.stdin.write(data[total:])
                if written is None or written == 0:
                    raise MCPError("Failed to send request: partial write")
                total += written
            self._proc.stdin.flush()

            # Read responses, skipping notifications and mismatched IDs
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MCPTimeoutError(f"MCP call timed out after {timeout}s")
                response = self._read_response(remaining)
                if not isinstance(response, dict):
                    response_type = type(response).__name__
                    raise MCPError(
                        f"Invalid JSON-RPC response type: expected object, got {response_type}"
                    )
                if "id" not in response:
                    continue
                if response.get("id") != self._request_id:
                    continue
                break
        except (BrokenPipeError, OSError, ValueError) as e:
            raise MCPError(f"Failed to send request: {e}") from e

        # Handle JSON-RPC response
        if "error" in response:
            error = response["error"]
            if isinstance(error, dict):
                code = error.get("code", -1)
                message = error.get("message", "Unknown error")
                raise MCPError(f"MCP error {code}: {message}")
            raise MCPError(f"MCP error: {error}")

        if "result" not in response:
            raise MCPError("Invalid MCP response: missing 'result'")

        result = response["result"]
        if not isinstance(result, dict):
            raise MCPError(f"Invalid MCP result type: expected dict, got {type(result).__name__}")
        return result

    def _start_subprocess(self) -> None:
        """Start the MCP subprocess.

        Raises:
            MCPError: If subprocess fails to start.
        """
        try:
            # Parse command string into list for subprocess (shlex handles quotes/spaces)
            command_parts = shlex.split(self._command)

            # Build subprocess environment: merge os.environ with custom env
            # (custom takes precedence). This avoids mutating global os.environ
            # and ensures isolation between servers
            subprocess_env: dict[str, str] | None = None
            if self._env:
                subprocess_env = {**os.environ, **self._env}

            self._proc = subprocess.Popen(
                command_parts,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                cwd=self._cwd,
                env=subprocess_env,
            )
        except OSError as e:
            raise MCPError(f"Failed to start MCP server: {e}") from e

        # Start background thread to drain stderr
        # Capture stderr reference locally to avoid race with _shutdown setting _proc=None
        with self._stderr_lock:
            self._stderr_buffer = bytearray()
        stderr_pipe = self._proc.stderr
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, args=(stderr_pipe,), daemon=True
        )
        self._stderr_thread.start()

        # Wait for server to become ready
        deadline = time.monotonic() + self._startup_timeout
        poll_interval = 0.1
        while time.monotonic() < deadline:
            time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
            poll_result = self._proc.poll()
            if poll_result is not None:
                self._shutdown(timeout=1.0)
                with self._stderr_lock:
                    stderr_content = bytes(self._stderr_buffer).decode(errors="replace")
                raise MCPError(
                    f"MCP server exited immediately with code {poll_result}: {stderr_content}"
                )
            # Server is still running - ready
            return
        # Server is still running after timeout window - ready
        return

    def _drain_stderr(self, stderr_pipe: Any) -> None:
        """Background thread to drain stderr and prevent pipe blocking.

        Args:
            stderr_pipe: The stderr pipe to drain (passed to avoid race with _proc).
        """
        if stderr_pipe is None:
            return
        while True:
            try:
                chunk = stderr_pipe.read(1024)
                if not chunk:
                    break
                with self._stderr_lock:
                    self._stderr_buffer.extend(chunk)
                    # Keep only last 64KB
                    if len(self._stderr_buffer) > 65536:
                        del self._stderr_buffer[:-65536]
            except (OSError, ValueError):
                break

    def _shutdown(self, timeout: float = 5.0) -> None:
        """Terminate the subprocess and clean up resources.

        Args:
            timeout: Seconds to wait for graceful termination before killing.
        """
        if self._proc is None:
            return

        if self._proc.poll() is None:
            with contextlib.suppress(OSError, ProcessLookupError):
                self._proc.terminate()
            try:
                self._proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(OSError, ProcessLookupError):
                    self._proc.kill()
                with contextlib.suppress(OSError):
                    self._proc.wait()

        if self._proc.stdin:
            with contextlib.suppress(OSError):
                self._proc.stdin.close()
        if self._proc.stdout:
            with contextlib.suppress(OSError):
                self._proc.stdout.close()
        if self._proc.stderr:
            with contextlib.suppress(OSError):
                self._proc.stderr.close()

        if self._stderr_thread is not None and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=1.0)

        self._proc = None

    def _read_response(self, timeout: float) -> dict[str, Any]:
        """Read a newline-delimited JSON-RPC response.

        Uses newline-delimited JSON format (FastMCP).

        Args:
            timeout: Timeout in seconds.

        Returns:
            Parsed JSON response.

        Raises:
            MCPError: On timeout, malformed response, or process exit.
        """
        if self._proc is None or self._proc.stdout is None:
            raise MCPError("MCP server stdout not available")

        deadline = time.monotonic() + timeout
        line_data = b""

        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MCPTimeoutError(f"MCP call timed out after {timeout}s")

                ready, _, _ = select.select([self._proc.stdout], [], [], min(remaining, 0.1))
                if not ready:
                    if self._proc.poll() is not None:
                        raise MCPError("MCP server exited unexpectedly")
                    continue

                byte = self._proc.stdout.read(1)
                if not byte:
                    # EOF on stdout - fail fast instead of busy-spinning
                    raise MCPError("MCP server closed stdout unexpectedly")

                line_data += byte

                # Limit line size to prevent memory exhaustion
                max_line_size = 100 * 1024 * 1024  # 100MB
                if len(line_data) > max_line_size:
                    raise MCPError(f"Response line exceeds {max_line_size} byte limit")

                # Newline marks end of JSON message
                if byte == b"\n":
                    break

        except (OSError, ValueError) as e:
            raise MCPError(f"I/O error reading response: {e}") from e

        try:
            text = line_data.decode("utf-8").strip()
            if not text:
                raise MCPError("Empty response from server")
            return json.loads(text)  # type: ignore[no-any-return]
        except UnicodeDecodeError as e:
            raise MCPError(f"Invalid UTF-8 in response: {e} - {line_data[:200]!r}") from e
        except json.JSONDecodeError as e:
            raise MCPError(f"Invalid JSON response: {e} - {line_data[:200]!r}") from e

    def is_alive(self) -> bool:
        """Check if the MCP subprocess is alive.

        Returns:
            True if subprocess is running, False otherwise.
        """
        return self._proc is not None and self._proc.poll() is None

    # Default lock acquire timeout for BUSY backpressure (1 second)
    LOCK_ACQUIRE_TIMEOUT = 1.0

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Call an MCP tool and return the result.

        This method is thread-safe and uses a lock to prevent interleaving
        of concurrent requests. If the subprocess has crashed, it will be
        restarted before making the call (raising MCPProviderCrashedError).

        Uses newline-delimited JSON format (FastMCP).

        Args:
            name: Tool name (e.g., "execute_command", "get_job_status").
            arguments: Tool arguments dict.
            timeout: Per-call timeout in seconds.

        Returns:
            Result dict from tool call.

        Raises:
            MCPBusyError: If lock cannot be acquired within timeout (backpressure).
            MCPProviderCrashedError: If provider crashed and was restarted.
            MCPTimeoutError: If call times out waiting for response.
            MCPError: On JSON-RPC error or subprocess failure.
        """
        # Try to acquire lock with timeout for BUSY backpressure
        acquired = self._lock.acquire(timeout=self.LOCK_ACQUIRE_TIMEOUT)
        if not acquired:
            raise MCPBusyError(
                message="Provider is busy processing another request",
                retry_after_ms=int(self.LOCK_ACQUIRE_TIMEOUT * 1000),
            )

        try:
            # Detect and handle provider crash
            was_dead = not self.is_alive()
            if was_dead:
                # Clean up old process resources before restarting
                self._shutdown(timeout=1.0)
                try:
                    self._start_subprocess()
                    self._do_initialize_unlocked()
                except Exception:
                    self._shutdown(timeout=1.0)
                    raise
                raise MCPProviderCrashedError(
                    "Provider crashed and was restarted. Existing job IDs are no longer valid."
                )

            if self._proc is None or self._proc.stdin is None:
                raise MCPError("MCP server stdin not available")

            self._request_id += 1
            request_id = self._request_id
            request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }

            try:
                # Newline-delimited JSON format
                data = (json.dumps(request) + "\n").encode("utf-8")
            except (TypeError, ValueError) as e:
                raise MCPError(f"Failed to serialize request: {e}") from e

            try:
                try:
                    total = 0
                    while total < len(data):
                        written = self._proc.stdin.write(data[total:])
                        if written is None or written == 0:
                            raise MCPError("Failed to send request: partial write")
                        total += written
                    self._proc.stdin.flush()
                except (BrokenPipeError, OSError, ValueError) as e:
                    raise MCPError(f"Failed to send request: {e}") from e

                deadline = time.monotonic() + timeout
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise MCPTimeoutError(f"MCP call timed out after {timeout}s")
                    response = self._read_response(remaining)
                    if not isinstance(response, dict):
                        response_type = type(response).__name__
                        raise MCPError(
                            f"Invalid JSON-RPC response type: expected object, got {response_type}"
                        )
                    # Skip notifications (no id)
                    if "id" not in response:
                        continue
                    if response.get("id") != request_id:
                        continue
                    break
            except MCPError:
                # Check if server crashed during request
                if not self.is_alive():
                    # Server died during request - restart and signal crash
                    self._shutdown(timeout=1.0)
                    try:
                        self._start_subprocess()
                        self._do_initialize_unlocked()
                    except Exception:
                        self._shutdown(timeout=1.0)
                        raise
                    raise MCPProviderCrashedError(
                        "Provider crashed and was restarted. Existing job IDs are no longer valid."
                    ) from None
                raise  # Re-raise original error if server is still alive

            if "error" in response:
                error = response["error"]
                if not isinstance(error, dict):
                    raise MCPError(f"Invalid JSON-RPC error type: {type(error).__name__}")
                code = error.get("code", -1)
                message = error.get("message", "Unknown error")
                raise MCPError(f"JSON-RPC error {code}: {message}")

            if "result" not in response:
                raise MCPError("Invalid JSON-RPC response: missing 'result'")

            result = response["result"]
            if not isinstance(result, dict):
                raise MCPError(f"Invalid JSON-RPC result type: {type(result).__name__}")
            return result
        finally:
            self._lock.release()

    def list_tools(self, timeout: float = 30.0) -> dict[str, Any]:
        """List available MCP tools.

        This method queries the MCP server for available tools using the
        tools/list method.

        Args:
            timeout: Per-call timeout in seconds.

        Returns:
            Dict containing the tools list from the MCP server.

        Raises:
            MCPBusyError: If lock cannot be acquired within timeout (backpressure).
            MCPProviderCrashedError: If provider crashed and was restarted.
            MCPTimeoutError: If call times out waiting for response.
            MCPError: On JSON-RPC error or subprocess failure.
        """
        # Try to acquire lock with timeout for BUSY backpressure
        acquired = self._lock.acquire(timeout=self.LOCK_ACQUIRE_TIMEOUT)
        if not acquired:
            raise MCPBusyError(
                message="Provider is busy processing another request",
                retry_after_ms=int(self.LOCK_ACQUIRE_TIMEOUT * 1000),
            )

        try:
            # Detect and handle provider crash
            was_dead = not self.is_alive()
            if was_dead:
                # Clean up old process resources before restarting
                self._shutdown(timeout=1.0)
                try:
                    self._start_subprocess()
                    self._do_initialize_unlocked()
                except Exception:
                    self._shutdown(timeout=1.0)
                    raise
                raise MCPProviderCrashedError(
                    "Provider crashed and was restarted. Existing job IDs are no longer valid."
                )

            try:
                result = self._send_request_unlocked(
                    method="tools/list",
                    params={},
                    timeout=timeout,
                )
            except MCPError:
                # Check if server crashed during request
                if not self.is_alive():
                    # Server died during request - restart and signal crash
                    self._shutdown(timeout=1.0)
                    try:
                        self._start_subprocess()
                        self._do_initialize_unlocked()
                    except Exception:
                        self._shutdown(timeout=1.0)
                        raise
                    raise MCPProviderCrashedError(
                        "Provider crashed and was restarted. Existing job IDs are no longer valid."
                    ) from None
                raise  # Re-raise original error if server is still alive
            else:
                return result
        finally:
            self._lock.release()

    def close(self) -> None:
        """Terminate the MCP subprocess and clean up resources."""
        with self._lock:
            self._shutdown()


__all__ = [
    "MCPBusyError",
    "MCPClient",
    "MCPError",
    "MCPProviderCrashedError",
    "MCPStdioManager",
    "MCPTimeoutError",
]
