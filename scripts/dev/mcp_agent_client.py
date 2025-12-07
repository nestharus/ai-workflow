#!/usr/bin/env python3
"""MCP Agent Client - Manages long-running agent processes via MCP background-job server.

This script acts as an MCP client to the background-job server, providing modes for
starting, waiting on, listing, and cancelling background jobs. It replaces poll_agents.py
with a more robust solution that handles all polling in Python.

Architecture Note (Layering):
    This client implements the **normalization layer** for background-job tool results.
    The MCP bridge (scripts/mcp/) is transport-only and returns provider-native payloads.
    This client normalizes those payloads to provide consistent response shapes:

    - Ensures `job_id` exists (falls back to provider's `id` field)
    - Ensures `status` and `exit_code` are present for completed jobs
    - Ensures `stdout` and `stderr` default to empty strings
    - Enforces client-side timeouts with proper cleanup

    HTTP-only consumers of the bridge should expect provider-native payloads and
    implement their own normalization if needed.

Usage:
    # Start a job and return immediately with job_id
    uv run agent.mcp start --command "uv run agent.tasks --agent planner --prompt '...'"

    # Start a job and wait for completion
    uv run agent.mcp wait --command "uv run agent.tasks ..." --max-seconds 600

    # Wait on existing job
    uv run agent.mcp wait --job-id <job_id> --max-seconds 600

    # List all jobs
    uv run agent.mcp list

    # Cancel a job
    uv run agent.mcp cancel --job-id <job_id>

Output (JSON):
    {
        "status": "completed|failed|killed|timeout|started",
        "job_id": "abc123",
        "exit_code": 0,
        "stdout": "...",
        "stderr": "...",
        "error": "..."
    }

Exit Codes:
    0   - Job completed successfully, or job started (start mode)
    N   - Job completed with error code N
    1   - Client/server error (startup failure, malformed response)
    124 - Job exceeded --max-seconds timeout
    137 - Job was terminated via cancel

Platform Support:
    This script uses select.select() on pipes, which is not supported on native Windows.
    It works on Linux, macOS, and WSL (Windows Subsystem for Linux).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import select
import subprocess
import sys
import threading
import time
from typing import Any

from scripts.mcp.client.http_client import HttpMCPClient
from scripts.mcp.client.http_client import MCPClientError as HttpMCPClientError


class MCPClientError(Exception):
    """Raised when MCP communication fails."""

    pass


class MCPClient:
    """Minimal MCP client for background-job server using JSON-RPC 2.0.

    Uses newline-delimited JSON format (FastMCP).
    """

    def __init__(
        self,
        command: list[str] | None = None,
        startup_timeout: float = 10.0,
    ) -> None:
        """Start MCP server as subprocess.

        Args:
            command: Command to start MCP server. Defaults to ["uvx", "mcp-background-job"].
            startup_timeout: Seconds to wait for server startup.

        Raises:
            MCPClientError: If server fails to start or times out.
        """
        if command is None:
            command = ["uvx", "mcp-background-job"]

        try:
            self.proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,  # Unbuffered for immediate I/O
            )
        except OSError as e:
            raise MCPClientError(f"Failed to start MCP server: {e}") from e

        self._request_id = 0
        self._startup_timeout = startup_timeout
        self._initialized = False

        # Start background thread to drain stderr (prevents pipe blocking)
        self._stderr_buffer = bytearray()
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

        # Wait for server to become ready (poll until startup_timeout)
        # MCP servers are considered ready when the process is alive and accepting stdin
        deadline = time.monotonic() + startup_timeout
        poll_interval = 0.1  # Check every 100ms
        while time.monotonic() < deadline:
            time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
            poll_result = self.proc.poll()
            if poll_result is not None:
                # Server exited - clean up and raise
                self._shutdown(timeout=1.0)
                raise MCPClientError(
                    f"MCP server exited immediately with code {poll_result}: "
                    f"{bytes(self._stderr_buffer).decode(errors='replace')}"
                )
            # Server is still running - perform MCP handshake
            try:
                self._initialize()
            except Exception:
                self._shutdown(timeout=1.0)
                raise
            else:
                return
        # Timeout waiting for startup
        self._shutdown(timeout=1.0)
        raise MCPClientError(f"MCP server did not become ready within {startup_timeout}s")

    def _initialize(self) -> None:
        """Perform MCP protocol handshake."""
        if self._initialized:
            return

        # Send initialize request
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mcp-agent-client", "version": "1.0.0"},
            },
        }
        self._send_json(request)

        # Read initialize response, skipping notifications and mismatched ids
        deadline = time.monotonic() + self._startup_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MCPClientError(f"MCP initialize timed out after {self._startup_timeout}s")
            response = self._read_response(timeout=remaining)
            # Skip notifications (no id) and mismatched responses
            if "id" not in response:
                continue
            if response.get("id") != self._request_id:
                continue
            break

        if "error" in response:
            raise MCPClientError(f"MCP initialize failed: {response['error']}")

        if "result" not in response or not isinstance(response.get("result"), dict):
            raise MCPClientError("Invalid MCP initialize response: missing or invalid 'result'")

        # Send initialized notification
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        self._send_json(notification)

        self._initialized = True

    def _send_json(self, obj: dict[str, Any]) -> None:
        """Send newline-delimited JSON."""
        if self.proc.stdin is None:
            raise MCPClientError("MCP server stdin not available")

        try:
            data = (json.dumps(obj) + "\n").encode("utf-8")
        except (TypeError, ValueError) as e:
            raise MCPClientError(f"Failed to serialize JSON: {e}") from e

        try:
            total = 0
            while total < len(data):
                written = self.proc.stdin.write(data[total:])
                if written is None or written == 0:
                    raise MCPClientError("Failed to send request: partial write")
                total += written
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as e:
            raise MCPClientError(f"Failed to send request: {e}") from e

    def _drain_stderr(self) -> None:
        """Background thread to drain stderr and prevent pipe blocking."""
        if self.proc.stderr is None:
            return
        while True:
            try:
                chunk = self.proc.stderr.read(1024)
                if not chunk:
                    break
                self._stderr_buffer.extend(chunk)
                # Keep only last 64KB
                if len(self._stderr_buffer) > 65536:
                    del self._stderr_buffer[:-65536]
            except (OSError, ValueError):
                # Pipe closed or invalid
                break

    def _shutdown(self, timeout: float = 5.0) -> None:
        """Robust shutdown: terminate/kill process, close pipes, join stderr thread.

        Args:
            timeout: Seconds to wait for graceful termination before killing.
        """
        # Terminate process if running
        if self.proc.poll() is None:
            with contextlib.suppress(OSError, ProcessLookupError):
                self.proc.terminate()
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(OSError, ProcessLookupError):
                    self.proc.kill()
                with contextlib.suppress(OSError):
                    self.proc.wait()

        # Close all pipes
        if self.proc.stdin:
            with contextlib.suppress(OSError):
                self.proc.stdin.close()
        if self.proc.stdout:
            with contextlib.suppress(OSError):
                self.proc.stdout.close()
        if self.proc.stderr:
            with contextlib.suppress(OSError):
                self.proc.stderr.close()

        # Join stderr drain thread (with timeout to avoid hanging)
        if hasattr(self, "_stderr_thread") and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=1.0)

    def _read_response(self, timeout: float) -> dict[str, Any]:
        """Read a newline-delimited JSON-RPC response.

        Uses newline-delimited JSON format (FastMCP).

        Args:
            timeout: Timeout in seconds.

        Returns:
            Parsed JSON response.

        Raises:
            MCPClientError: On timeout, malformed response, or process exit.
        """
        if self.proc.stdout is None:
            raise MCPClientError("MCP server stdout not available")

        deadline = time.monotonic() + timeout
        line_data = b""

        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MCPClientError(f"MCP call timed out after {timeout}s")

                # Check if data is available
                # NOTE: select.select on pipes only works on Unix; this script is designed
                # for WSL/Linux development environments. Native Windows would require
                # a threading-based reader or WaitForSingleObject/PeekNamedPipe.
                ready, _, _ = select.select([self.proc.stdout], [], [], min(remaining, 0.1))
                if not ready:
                    # Check if process died
                    if self.proc.poll() is not None:
                        raise MCPClientError("MCP server exited unexpectedly")
                    continue

                byte = self.proc.stdout.read(1)
                if not byte:
                    if self.proc.poll() is not None:
                        raise MCPClientError("MCP server exited unexpectedly")
                    continue

                line_data += byte

                # Limit line size to prevent memory exhaustion
                max_line_size = 100 * 1024 * 1024  # 100MB
                if len(line_data) > max_line_size:
                    raise MCPClientError(f"Response line exceeds {max_line_size} byte limit")

                # Newline marks end of JSON message
                if byte == b"\n":
                    break

        except (OSError, ValueError) as e:
            raise MCPClientError(f"I/O error reading response: {e}") from e

        try:
            text = line_data.decode("utf-8").strip()
            if not text:
                raise MCPClientError("Empty response from server")
            return json.loads(text)  # type: ignore[no-any-return]
        except UnicodeDecodeError as e:
            raise MCPClientError(f"Invalid UTF-8 in response: {e} - {line_data[:200]!r}") from e
        except json.JSONDecodeError as e:
            raise MCPClientError(f"Invalid JSON response: {e} - {line_data[:200]!r}") from e

    def call_tool(
        self, name: str, arguments: dict[str, Any], timeout: float = 30.0
    ) -> dict[str, Any]:
        """Call an MCP tool and return result.

        Uses newline-delimited JSON format (FastMCP).

        Args:
            name: Tool name (e.g., "execute_command", "get_job_status").
            arguments: Tool arguments dict.
            timeout: Per-call timeout in seconds.

        Returns:
            Result dict from tool call.

        Raises:
            MCPClientError: On JSON-RPC error, timeout, or unexpected process exit.
        """
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }

        self._send_json(request)

        # Read response, validating that the id matches our request
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MCPClientError(f"MCP call timed out after {timeout}s")
            response = self._read_response(remaining)
            # Skip notifications (no id) and mismatched responses
            if "id" not in response:
                continue
            if response.get("id") != self._request_id:
                continue
            break

        # Validate JSON-RPC response
        if "error" in response:
            error = response["error"]
            if not isinstance(error, dict):
                raise MCPClientError(f"Invalid JSON-RPC error type: {type(error).__name__}")
            code = error.get("code", -1)
            message = error.get("message", "Unknown error")
            raise MCPClientError(f"JSON-RPC error {code}: {message}")

        if "result" not in response:
            raise MCPClientError("Invalid JSON-RPC response: missing 'result'")

        result = response["result"]
        if not isinstance(result, dict):
            raise MCPClientError(f"Invalid JSON-RPC result type: {type(result).__name__}")
        return result

    def close(self) -> None:
        """Terminate MCP server subprocess."""
        self._shutdown()


def get_mcp_client() -> MCPClient | HttpMCPClient:
    """Get MCP client based on MCP_TRANSPORT environment variable.

    Returns:
        MCPClient if MCP_TRANSPORT is not set or is "stdio"
        HttpMCPClient if MCP_TRANSPORT is "http"

    Raises:
        ValueError: If MCP_TRANSPORT is set to an unknown value
    """
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    if transport == "stdio":
        return MCPClient()
    elif transport == "http":
        return HttpMCPClient()
    else:
        raise ValueError(f"Unknown MCP_TRANSPORT: {transport}. Use 'stdio' or 'http'")


# Default server name for HTTP transport (configurable via MCP_SERVER env var)
_MCP_SERVER = os.environ.get("MCP_SERVER", "background-job")


def call_mcp_tool(
    client: MCPClient | HttpMCPClient,
    name: str,
    arguments: dict[str, Any],
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Call an MCP tool using the appropriate client method.

    For stdio transport (MCPClient), calls call_tool() directly.
    For HTTP transport (HttpMCPClient), calls call_server_tool() with the
    server name from MCP_SERVER env var (defaults to 'background-job').

    Args:
        client: MCP client instance.
        name: Tool name.
        arguments: Tool arguments.
        timeout: Request timeout in seconds.

    Returns:
        Result dict from tool call.

    Raises:
        MCPClientError or HttpMCPClientError: On communication failure.
    """
    if isinstance(client, HttpMCPClient):
        return client.call_server_tool(
            server=_MCP_SERVER, name=name, arguments=arguments, timeout=timeout
        )
    return client.call_tool(name=name, arguments=arguments, timeout=timeout)


def cmd_start(client: MCPClient | HttpMCPClient, command: str) -> dict[str, Any]:
    """Start a job and return immediately.

    Args:
        client: MCP client instance.
        command: Shell command to execute.

    Returns:
        Result dict with status and job_id.
    """
    try:
        result = call_mcp_tool(client, "execute_command", {"command": command})
        # FastMCP wraps results in structuredContent
        # Use `or` to handle null structuredContent
        structured = result.get("structuredContent") or result
        if not isinstance(structured, dict):
            return {"status": "failed", "error": "Invalid response format from server"}
        # Normalize: provider returns `id`, we expose `job_id` for consistency
        job_id = structured.get("job_id", structured.get("id"))
    except (MCPClientError, HttpMCPClientError) as e:
        return {"status": "failed", "error": str(e)}
    else:
        if not job_id:
            return {"status": "failed", "error": "No job_id returned by server"}
        return {"status": "started", "job_id": job_id}


def cmd_wait(
    client: MCPClient | HttpMCPClient,
    command: str | None,
    job_id: str | None,
    max_seconds: int,
    poll_interval: float,
) -> dict[str, Any]:
    """Start a job (or attach to existing) and wait for completion.

    Args:
        client: MCP client instance.
        command: Shell command to execute (if starting new job).
        job_id: Existing job ID to wait on.
        max_seconds: Maximum time to wait.
        poll_interval: How often to poll for status.

    Returns:
        Result dict with status, job_id, exit_code, stdout, stderr.
    """
    # Validate inputs (handles negative and NaN)
    if not (poll_interval >= 0):
        return {
            "status": "failed",
            "job_id": job_id,
            "error": "Invalid poll_interval; must be >= 0",
        }
    if not (max_seconds >= 0):
        return {
            "status": "failed",
            "job_id": job_id,
            "error": "Invalid max_seconds; must be >= 0",
        }

    try:
        deadline = time.monotonic() + max_seconds

        def get_remaining_timeout() -> float:
            """Get remaining time before deadline, with minimum floor."""
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return 0.0
            # Use at least 1 second for individual calls to allow completion
            return max(1.0, remaining)

        if command:
            remaining = get_remaining_timeout()
            if remaining <= 0:
                return {
                    "status": "timeout",
                    "job_id": job_id,
                    "error": f"Job exceeded {max_seconds}s timeout before starting",
                }
            result = call_mcp_tool(client, "execute_command", {"command": command}, remaining)
            # FastMCP wraps results in structuredContent
            # Use `or` to handle null structuredContent
            structured = result.get("structuredContent") or result
            if not isinstance(structured, dict):
                return {"status": "failed", "error": "Invalid response format from server"}
            # Normalize: provider returns `id`, we expose `job_id` for consistency
            job_id = structured.get("job_id", structured.get("id"))

        if not job_id:
            return {"status": "failed", "error": "No job_id available"}

        while True:
            remaining = get_remaining_timeout()
            if remaining <= 0:
                # Kill job on timeout (best effort, with very short timeout)
                with contextlib.suppress(MCPClientError, HttpMCPClientError):
                    call_mcp_tool(client, "kill_job", {"job_id": job_id}, 1.0)
                return {
                    "status": "timeout",
                    "job_id": job_id,
                    "error": f"Job exceeded {max_seconds}s timeout and was killed",
                }

            status_res = call_mcp_tool(client, "get_job_status", {"job_id": job_id}, remaining)
            # FastMCP wraps results in structuredContent
            # Use `or` to handle null structuredContent
            structured = status_res.get("structuredContent") or status_res
            if not isinstance(structured, dict):
                return {
                    "status": "failed",
                    "job_id": job_id,
                    "error": "Invalid response format from server",
                }
            job_status = structured.get("status", "unknown")

            if job_status in ("completed", "failed", "killed"):
                remaining = get_remaining_timeout()
                if remaining <= 0:
                    return {
                        "status": "timeout",
                        "job_id": job_id,
                        "error": f"Job exceeded {max_seconds}s timeout while fetching output",
                    }
                output_res = call_mcp_tool(client, "get_job_output", {"job_id": job_id}, remaining)
                # Use `or` to handle null structuredContent
                output_structured = output_res.get("structuredContent") or output_res
                if not isinstance(output_structured, dict):
                    return {
                        "status": "failed",
                        "job_id": job_id,
                        "error": "Invalid response format from server",
                    }
                return {
                    "status": job_status,
                    "job_id": job_id,
                    "exit_code": structured.get("exit_code"),
                    "stdout": output_structured.get("stdout", ""),
                    "stderr": output_structured.get("stderr", ""),
                }

            time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))

    except (MCPClientError, HttpMCPClientError) as e:
        # Detect timeout errors and return appropriate status
        error_msg = str(e).lower()
        if "timed out" in error_msg or "timeout" in error_msg:
            return {
                "status": "timeout",
                "job_id": job_id,
                "error": f"Job exceeded {max_seconds}s timeout: {e}",
            }
        return {"status": "failed", "job_id": job_id, "error": str(e)}


def cmd_list(client: MCPClient | HttpMCPClient) -> dict[str, Any]:
    """List all jobs.

    Args:
        client: MCP client instance.

    Returns:
        Result dict with status and jobs list.
    """
    try:
        result = call_mcp_tool(client, "list_jobs", {})
        # FastMCP wraps results in structuredContent
        # Use `or` to handle null structuredContent
        structured = result.get("structuredContent") or result
        if not isinstance(structured, dict):
            return {"status": "failed", "error": "Invalid response format from server"}
        return {"status": "completed", "jobs": structured.get("jobs", [])}
    except (MCPClientError, HttpMCPClientError) as e:
        return {"status": "failed", "error": str(e)}


def cmd_cancel(client: MCPClient | HttpMCPClient, job_id: str) -> dict[str, Any]:
    """Cancel a running job.

    Args:
        client: MCP client instance.
        job_id: ID of job to cancel.

    Returns:
        Result dict with status.
    """
    try:
        call_mcp_tool(client, "kill_job", {"job_id": job_id})
    except (MCPClientError, HttpMCPClientError) as e:
        return {"status": "failed", "job_id": job_id, "error": str(e)}
    else:
        return {"status": "killed", "job_id": job_id}


def get_exit_code(result: dict[str, Any]) -> int:
    """Determine exit code from result dict.

    Args:
        result: Result dict from command execution.

    Returns:
        Appropriate exit code.
    """
    status = result.get("status", "failed")

    if status == "completed":
        exit_code = result.get("exit_code")
        if exit_code is not None:
            try:
                return int(exit_code)
            except (ValueError, TypeError):
                return 0
        return 0
    elif status == "started":
        return 0
    elif status == "timeout":
        return 124
    elif status == "killed":
        return 137
    else:  # failed or unknown
        return 1


def main() -> int:
    """Main entry point.

    Returns:
        Exit code.
    """
    parser = argparse.ArgumentParser(
        description="MCP Agent Client - Manage long-running agent processes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="mode", required=True, help="Operation mode")

    # Start mode
    start_parser = subparsers.add_parser("start", help="Start a job and return immediately")
    start_parser.add_argument("--command", required=True, help="Shell command to execute")

    # Wait mode
    wait_parser = subparsers.add_parser("wait", help="Start a job and wait for completion")
    wait_parser.add_argument("--command", help="Shell command to execute")
    wait_parser.add_argument("--job-id", help="Existing job ID to wait on")
    wait_parser.add_argument(
        "--max-seconds",
        type=int,
        default=600,
        help="Maximum time to wait in seconds (default: 600)",
    )
    wait_parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="How often to poll in seconds (default: 2.0)",
    )

    # List mode
    subparsers.add_parser("list", help="List all jobs")

    # Cancel mode
    cancel_parser = subparsers.add_parser("cancel", help="Cancel a running job")
    cancel_parser.add_argument("--job-id", required=True, help="Job ID to cancel")

    args = parser.parse_args()

    # Validate wait mode arguments
    if args.mode == "wait" and not args.command and not args.job_id:
        parser.error("wait mode requires either --command or --job-id")

    client = None
    try:
        client = get_mcp_client()

        if args.mode == "start":
            result = cmd_start(client, args.command)
        elif args.mode == "wait":
            result = cmd_wait(
                client,
                args.command,
                args.job_id,
                args.max_seconds,
                args.poll_interval,
            )
        elif args.mode == "list":
            result = cmd_list(client)
        elif args.mode == "cancel":
            result = cmd_cancel(client, args.job_id)
        else:
            result = {"status": "failed", "error": f"Unknown mode: {args.mode}"}

        print(json.dumps(result, indent=2))
        return get_exit_code(result)

    except MCPClientError as e:
        result = {"status": "failed", "error": str(e)}
        print(json.dumps(result, indent=2))
        return 1

    except ValueError as e:
        result = {"status": "failed", "error": str(e)}
        print(json.dumps(result, indent=2))
        return 1

    except KeyboardInterrupt:
        result = {"status": "failed", "error": "Interrupted by user"}
        print(json.dumps(result, indent=2))
        return 130

    finally:
        if client and hasattr(client, "close"):
            client.close()


if __name__ == "__main__":
    sys.exit(main())
