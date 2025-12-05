#!/usr/bin/env python3
"""MCP Agent Client - Manages long-running agent processes via MCP background-job server.

This script acts as an MCP client to the background-job server, providing modes for
starting, waiting on, listing, and cancelling background jobs. It replaces poll_agents.py
with a more robust solution that handles all polling in Python.

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
"""

from __future__ import annotations

import argparse
import contextlib
import json
import select
import subprocess
import sys
import threading
import time
from typing import Any


class MCPClientError(Exception):
    """Raised when MCP communication fails."""

    pass


class MCPClient:
    """Minimal MCP client for background-job server using JSON-RPC 2.0."""

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

        # Start background thread to drain stderr (prevents pipe blocking)
        self._stderr_buffer = bytearray()
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True
        )
        self._stderr_thread.start()

        # Wait for server to become ready (poll until startup_timeout)
        deadline = time.monotonic() + startup_timeout
        while time.monotonic() < deadline:
            poll_result = self.proc.poll()
            if poll_result is not None:
                # Server exited - clean up and raise
                self._cleanup_failed_process()
                raise MCPClientError(
                    f"MCP server exited immediately with code {poll_result}: "
                    f"{bytes(self._stderr_buffer).decode(errors='replace')}"
                )
            # Server is still running - consider it ready
            # (MCP servers are ready when they accept stdin)
            return
        # Timeout waiting for startup
        self._cleanup_failed_process()
        raise MCPClientError(
            f"MCP server did not become ready within {startup_timeout}s"
        )

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

    def _cleanup_failed_process(self) -> None:
        """Clean up process resources after startup failure."""
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
        # Reap the process to avoid zombies
        with contextlib.suppress(OSError):
            self.proc.wait(timeout=1)

    def _read_response(self, timeout: float) -> dict[str, Any]:
        """Read a JSON-RPC response with Content-Length header.

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
        header_data = b""

        # Read headers until we get Content-Length
        content_length = -1
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MCPClientError(f"MCP call timed out after {timeout}s")

            # Check if data is available
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

            header_data += byte

            # Check for end of headers (double CRLF)
            if header_data.endswith(b"\r\n\r\n"):
                # Parse Content-Length from headers
                header_str = header_data.decode("utf-8", errors="replace")
                for line in header_str.split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        try:
                            content_length = int(line.split(":", 1)[1].strip())
                        except ValueError:
                            raise MCPClientError(
                                f"Invalid Content-Length header: {line}"
                            ) from None
                        break
                break

        if content_length < 0:
            raise MCPClientError(
                f"Missing Content-Length header in response: {header_data!r}"
            )

        # Read the body
        body_data = b""
        while len(body_data) < content_length:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MCPClientError(f"MCP call timed out after {timeout}s")

            ready, _, _ = select.select([self.proc.stdout], [], [], min(remaining, 0.1))
            if not ready:
                if self.proc.poll() is not None:
                    raise MCPClientError("MCP server exited unexpectedly")
                continue

            chunk = self.proc.stdout.read(content_length - len(body_data))
            if not chunk:
                if self.proc.poll() is not None:
                    raise MCPClientError("MCP server exited unexpectedly")
                continue
            body_data += chunk

        try:
            text = body_data.decode("utf-8")
            return json.loads(text)
        except UnicodeDecodeError as e:
            raise MCPClientError(
                f"Invalid UTF-8 in response body: {e} - {body_data[:200]!r}"
            ) from e
        except json.JSONDecodeError as e:
            raise MCPClientError(
                f"Invalid JSON response: {e} - {body_data[:200]!r}"
            ) from e

    def call_tool(
        self, name: str, arguments: dict[str, Any], timeout: float = 30.0
    ) -> dict[str, Any]:
        """Call an MCP tool and return result.

        Args:
            name: Tool name (e.g., "execute", "status").
            arguments: Tool arguments dict.
            timeout: Per-call timeout in seconds.

        Returns:
            Result dict from tool call.

        Raises:
            MCPClientError: On JSON-RPC error, timeout, or unexpected process exit.
        """
        if self.proc.stdin is None:
            raise MCPClientError("MCP server stdin not available")

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }

        # Send request with Content-Length header
        body = json.dumps(request).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode()

        try:
            self.proc.stdin.write(header + body)
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise MCPClientError(f"Failed to send request: {e}") from e

        # Read response
        response = self._read_response(timeout)

        # Validate JSON-RPC response
        if "error" in response:
            code = response["error"].get("code", -1)
            message = response["error"].get("message", "Unknown error")
            raise MCPClientError(f"JSON-RPC error {code}: {message}")

        if "result" not in response:
            raise MCPClientError("Invalid JSON-RPC response: missing 'result'")

        return response["result"]

    def close(self) -> None:
        """Terminate MCP server subprocess."""
        if self.proc.poll() is None:
            with contextlib.suppress(OSError, ProcessLookupError):
                self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(OSError, ProcessLookupError):
                    self.proc.kill()
                self.proc.wait()


def cmd_start(client: MCPClient, command: str) -> dict[str, Any]:
    """Start a job and return immediately.

    Args:
        client: MCP client instance.
        command: Shell command to execute.

    Returns:
        Result dict with status and job_id.
    """
    try:
        result = client.call_tool("execute", {"command": command})
        return {"status": "started", "job_id": result.get("job_id", result.get("id"))}
    except MCPClientError as e:
        return {"status": "failed", "error": str(e)}


def cmd_wait(
    client: MCPClient,
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
    # Validate poll_interval (handles negative and NaN)
    if not (poll_interval >= 0):
        return {
            "status": "failed",
            "job_id": job_id,
            "error": "Invalid poll_interval; must be >= 0",
        }

    try:
        if command:
            result = client.call_tool("execute", {"command": command})
            job_id = result.get("job_id", result.get("id"))

        if not job_id:
            return {"status": "failed", "error": "No job_id available"}

        deadline = time.monotonic() + max_seconds

        while True:
            if time.monotonic() > deadline:
                # Kill job on timeout (best effort)
                with contextlib.suppress(MCPClientError):
                    client.call_tool("kill", {"job_id": job_id})
                return {
                    "status": "timeout",
                    "job_id": job_id,
                    "error": f"Job exceeded {max_seconds}s timeout and was killed",
                }

            status_res = client.call_tool("status", {"job_id": job_id})
            job_status = status_res.get("status", "unknown")

            if job_status in ("completed", "failed", "killed"):
                output_res = client.call_tool("output", {"job_id": job_id})
                return {
                    "status": job_status,
                    "job_id": job_id,
                    "exit_code": status_res.get("exit_code"),
                    "stdout": output_res.get("stdout", ""),
                    "stderr": output_res.get("stderr", ""),
                }

            time.sleep(poll_interval)

    except MCPClientError as e:
        return {"status": "failed", "job_id": job_id, "error": str(e)}


def cmd_list(client: MCPClient) -> dict[str, Any]:
    """List all jobs.

    Args:
        client: MCP client instance.

    Returns:
        Result dict with status and jobs list.
    """
    try:
        result = client.call_tool("list", {})
        return {"status": "completed", "jobs": result.get("jobs", [])}
    except MCPClientError as e:
        return {"status": "failed", "error": str(e)}


def cmd_cancel(client: MCPClient, job_id: str) -> dict[str, Any]:
    """Cancel a running job.

    Args:
        client: MCP client instance.
        job_id: ID of job to cancel.

    Returns:
        Result dict with status.
    """
    try:
        client.call_tool("kill", {"job_id": job_id})
    except MCPClientError as e:
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
            return int(exit_code)
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
    start_parser.add_argument(
        "--command", required=True, help="Shell command to execute"
    )

    # Wait mode
    wait_parser = subparsers.add_parser(
        "wait", help="Start a job and wait for completion"
    )
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
        client = MCPClient()

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

    except KeyboardInterrupt:
        result = {"status": "failed", "error": "Interrupted by user"}
        print(json.dumps(result, indent=2))
        return 130

    finally:
        if client:
            client.close()


if __name__ == "__main__":
    sys.exit(main())
