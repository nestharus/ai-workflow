"""MCP stdio manager for communicating with MCP provider subprocesses.

This module provides the MCPStdioManager class that handles spawning and
communicating with an MCP provider subprocess using Content-Length framed
JSON-RPC over stdio.
"""

from __future__ import annotations

import contextlib
import json
import os
import select
import subprocess
import threading
import time
from typing import Any


class MCPError(Exception):
    """Raised when MCP communication fails."""

    pass


class MCPStdioManager:
    """Manages an MCP provider subprocess using stdio communication.

    This class handles:
    - Spawning the MCP subprocess on init
    - Content-Length framed JSON-RPC communication
    - Thread-safe request/response handling
    - Subprocess crash detection and restart capability
    """

    DEFAULT_COMMAND = "uvx mcp-background-job"

    def __init__(
        self,
        command: str | None = None,
        startup_timeout: float = 10.0,
    ) -> None:
        """Initialize the MCP manager and start the subprocess.

        Args:
            command: Command to start MCP server. Defaults to MCP_COMMAND env var
                or 'uvx mcp-background-job'.
            startup_timeout: Seconds to wait for server startup.

        Raises:
            MCPError: If server fails to start or times out.
        """
        self._command = command or os.environ.get("MCP_COMMAND", self.DEFAULT_COMMAND)
        self._startup_timeout = startup_timeout
        self._request_id = 0
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._stderr_buffer = bytearray()
        self._stderr_thread: threading.Thread | None = None

        self._start_subprocess()

    def _start_subprocess(self) -> None:
        """Start the MCP subprocess.

        Raises:
            MCPError: If subprocess fails to start.
        """
        try:
            # Parse command string into list for subprocess
            command_parts = self._command.split()
            self._proc = subprocess.Popen(
                command_parts,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except OSError as e:
            raise MCPError(f"Failed to start MCP server: {e}") from e

        # Start background thread to drain stderr
        self._stderr_buffer = bytearray()
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

        # Wait for server to become ready
        deadline = time.monotonic() + self._startup_timeout
        poll_interval = 0.1
        while time.monotonic() < deadline:
            time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
            poll_result = self._proc.poll()
            if poll_result is not None:
                self._shutdown(timeout=1.0)
                raise MCPError(
                    f"MCP server exited immediately with code {poll_result}: "
                    f"{bytes(self._stderr_buffer).decode(errors='replace')}"
                )
            return

        self._shutdown(timeout=1.0)
        raise MCPError(f"MCP server did not become ready within {self._startup_timeout}s")

    def _drain_stderr(self) -> None:
        """Background thread to drain stderr and prevent pipe blocking."""
        if self._proc is None or self._proc.stderr is None:
            return
        while True:
            try:
                chunk = self._proc.stderr.read(1024)
                if not chunk:
                    break
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
        """Read a JSON-RPC response with Content-Length header.

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
        header_data = b""

        content_length = -1
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MCPError(f"MCP call timed out after {timeout}s")

                ready, _, _ = select.select([self._proc.stdout], [], [], min(remaining, 0.1))
                if not ready:
                    if self._proc.poll() is not None:
                        raise MCPError("MCP server exited unexpectedly")
                    continue

                byte = self._proc.stdout.read(1)
                if not byte:
                    if self._proc.poll() is not None:
                        raise MCPError("MCP server exited unexpectedly")
                    continue

                header_data += byte
                if len(header_data) > 65536:
                    raise MCPError("Response headers exceed 64KB limit")

                if header_data.endswith(b"\r\n\r\n"):
                    header_str = header_data.decode("utf-8", errors="replace")
                    for line in header_str.split("\r\n"):
                        if line.lower().startswith("content-length:"):
                            try:
                                content_length = int(line.split(":", 1)[1].strip())
                            except ValueError:
                                raise MCPError(f"Invalid Content-Length header: {line}") from None
                            break
                    break
        except OSError as e:
            raise MCPError(f"I/O error reading response headers: {e}") from e

        if content_length < 0:
            raise MCPError(f"Missing Content-Length header in response: {header_data!r}")

        max_body_size = 100 * 1024 * 1024
        if content_length > max_body_size:
            raise MCPError(f"Response body size {content_length} exceeds {max_body_size} byte limit")

        body_data = b""
        try:
            while len(body_data) < content_length:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MCPError(f"MCP call timed out after {timeout}s")

                ready, _, _ = select.select([self._proc.stdout], [], [], min(remaining, 0.1))
                if not ready:
                    if self._proc.poll() is not None:
                        raise MCPError("MCP server exited unexpectedly")
                    continue

                chunk = self._proc.stdout.read(content_length - len(body_data))
                if not chunk:
                    raise MCPError("Unexpected EOF while reading response body")
                body_data += chunk
        except OSError as e:
            raise MCPError(f"I/O error reading response body: {e}") from e

        try:
            text = body_data.decode("utf-8")
            return json.loads(text)  # type: ignore[no-any-return]
        except UnicodeDecodeError as e:
            raise MCPError(f"Invalid UTF-8 in response body: {e} - {body_data[:200]!r}") from e
        except json.JSONDecodeError as e:
            raise MCPError(f"Invalid JSON response: {e} - {body_data[:200]!r}") from e

    def is_alive(self) -> bool:
        """Check if the MCP subprocess is alive.

        Returns:
            True if subprocess is running, False otherwise.
        """
        return self._proc is not None and self._proc.poll() is None

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Call an MCP tool and return the result.

        This method is thread-safe and uses a lock to prevent interleaving
        of concurrent requests. If the subprocess has crashed, it will be
        restarted before making the call.

        Args:
            name: Tool name (e.g., "execute", "status").
            arguments: Tool arguments dict.
            timeout: Per-call timeout in seconds.

        Returns:
            Result dict from tool call.

        Raises:
            MCPError: On JSON-RPC error, timeout, or subprocess failure.
        """
        with self._lock:
            # Restart subprocess if it has crashed
            if not self.is_alive():
                self._start_subprocess()

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
                body = json.dumps(request).encode("utf-8")
            except (TypeError, ValueError) as e:
                raise MCPError(f"Failed to serialize request: {e}") from e

            header = f"Content-Length: {len(body)}\r\n\r\n".encode()

            try:
                data = header + body
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
                    raise MCPError(f"MCP call timed out after {timeout}s")
                response = self._read_response(remaining)
                if "id" not in response:
                    continue
                if response.get("id") != request_id:
                    continue
                break

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

    def close(self) -> None:
        """Terminate the MCP subprocess and clean up resources."""
        self._shutdown()


__all__ = ["MCPError", "MCPStdioManager"]
