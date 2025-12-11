#!/usr/bin/env python3
"""MCP Agent Client - HTTP-based bridge client for managing long-running background jobs.

This client acts as a CLI and programmatic interface to the REST-to-MCP bridge,
which manages background job processes. It normalizes provider-native job payloads
from tools like `execute_command`, `get_job_status`, `get_job_output`, `list_jobs`,
and `kill_job` into a stable JSON schema for consistent downstream consumption.

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

The module is designed to work across platforms by relying on the MCP bridge for
process management, avoiding platform-specific process APIs.

Configuration:
    The bridge endpoint is configured with the following precedence:
    1. --socket-path CLI flag (highest priority)
    2. MCP_BRIDGE_SOCKET environment variable
    3. --server-url CLI flag
    4. MCP_BRIDGE_URL environment variable
    5. Default: http://localhost:8080 (lowest priority)

    When a socket path is configured (via flag or env), all URL settings are ignored.

    To start the bridge server:
        uv run agent.mcp bridge start

    To start with Unix socket:
        export MCP_BRIDGE_SOCKET=/tmp/mcp-sockets/mcp-bridge.sock
        uv run agent.mcp bridge start --socket $MCP_BRIDGE_SOCKET

Usage:
    # Using environment variables (existing behavior):
    export MCP_BRIDGE_SOCKET=/tmp/mcp-sockets/mcp-bridge.sock
    uv run agent.mcp list

    # Using explicit CLI flags (new):
    uv run agent.mcp --socket-path /tmp/mcp-sockets/mcp-bridge.sock list
    uv run agent.mcp --server-url http://localhost:8080 start --command "..."

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
import os
import sys
import time
from typing import Any

from scripts.servers.mcp.client.http_client import HttpMCPClient, MCPClientError

# Default server name for HTTP transport (configurable via MCP_SERVER env var)
_MCP_SERVER = os.environ.get("MCP_SERVER", "background-job")


def _format_bridge_error(e: MCPClientError) -> str:
    """Format bridge errors with consistent, user-friendly messages.

    This helper operates purely on the string message from MCPClientError,
    detecting specific failure patterns via substring matching and optionally
    wrapping or prefixing the message with human-oriented guidance.

    IMPORTANT: This function MUST NOT:
    - Remove or obscure technical details from the original error message
    - Set status values or influence exit codes (that's cmd_* responsibility)
    - Return anything other than a string
    - Perform timeout detection for status determination

    Note on timeout semantics: The status="timeout" (exit code 124) is ONLY
    returned when cmd_wait() explicitly detects that the client-side max_seconds
    deadline has been exceeded and calls kill_job. Transport-level or bridge-level
    timeouts (e.g., HTTP request timeouts during get_job_status/get_job_output)
    result in status="failed" (exit code 1) because the underlying job may still
    be running. This helper only formats error messages; it does NOT influence
    status selection.

    The original MCPClientError error message is always preserved in the output.

    Note: Currently all code paths return the original error_msg unchanged.
    This is intentional - HttpMCPClient already provides well-formatted error
    messages. The structure is kept for future extensibility if custom
    formatting is needed for specific error patterns.

    Args:
        e: The MCPClientError exception.

    Returns:
        Formatted error message string containing the original error details.
    """
    error_msg = str(e)

    # Connection failures: already have actionable guidance from HttpMCPClient
    # Pattern: "Cannot connect to mcp-bridge at ..."
    if "Cannot connect to mcp-bridge" in error_msg:
        # Preserve as-is - HttpMCPClient already includes setup instructions
        return error_msg

    # Timeout errors: already formatted by HttpMCPClient
    # Pattern: "Request timed out after {timeout}s" or similar
    if "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
        return error_msg

    # HTTP 4xx/5xx errors: HttpMCPClient formats as "[ERROR_TYPE] message"
    # or "HTTP request failed: ..." - preserve the structured format
    if error_msg.startswith("[") or "HTTP request failed" in error_msg:
        return error_msg

    # For any other errors, return as-is (already formatted by HttpMCPClient)
    return error_msg


def get_mcp_client(
    base_url: str | None = None,
    socket_path: str | None = None,
) -> HttpMCPClient:
    """Get HTTP MCP client for bridge communication.

    This function delegates to HttpMCPClient, which implements the transport
    mode resolution logic. The arguments are passed directly to the
    HttpMCPClient constructor.

    Args:
        base_url: Bridge server URL (from --server-url CLI flag).
        socket_path: Unix socket path (from --socket-path CLI flag).

    Returns:
        Configured HttpMCPClient instance.

    Precedence (highest to lowest):
        1. socket_path argument (--socket-path CLI flag)
        2. MCP_BRIDGE_SOCKET environment variable
        3. base_url argument (--server-url CLI flag)
        4. MCP_BRIDGE_URL environment variable
        5. Default: http://localhost:8080

    When socket_path is set (via arg or env), URL settings are ignored.
    CLI flags override their corresponding environment variables.

    See Also:
        scripts.servers.mcp.client.http_client.HttpMCPClient: The definitive
        source for transport mode precedence rules and connection behavior.
    """
    # Delegates to HttpMCPClient which owns the precedence logic.
    # See: scripts.servers.mcp.client.http_client.HttpMCPClient
    return HttpMCPClient(base_url=base_url, socket_path=socket_path)


def call_mcp_tool(
    client: HttpMCPClient,
    name: str,
    arguments: dict[str, Any],
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Call an MCP tool using the HTTP client.

    Args:
        client: HTTP MCP client instance.
        name: Tool name.
        arguments: Tool arguments.
        timeout: Request timeout in seconds.

    Returns:
        Result dict from tool call.

    Raises:
        MCPClientError: On communication failure.
    """
    return client.call_server_tool(
        server=_MCP_SERVER, name=name, arguments=arguments, timeout=timeout
    )


def cmd_start(client: HttpMCPClient, command: str) -> dict[str, Any]:
    """Start a job and return immediately.

    Args:
        client: HTTP MCP client instance.
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
    except MCPClientError as e:
        return {"status": "failed", "error": _format_bridge_error(e)}
    else:
        if not job_id:
            return {"status": "failed", "error": "No job_id returned by server"}
        return {"status": "started", "job_id": job_id}


def cmd_wait(
    client: HttpMCPClient,
    command: str | None,
    job_id: str | None,
    max_seconds: int,
    poll_interval: float,
) -> dict[str, Any]:
    """Start a job (or attach to existing) and wait for completion.

    Args:
        client: HTTP MCP client instance.
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
            """Get the exact remaining time budget before deadline, clamped at 0.0.

            This function calculates the precise remaining seconds until the
            max_seconds deadline. Every call to get_job_status() or get_job_output()
            uses this value as its HTTP request timeout, ensuring that no individual
            request can cause the total wait time to exceed the client's max_seconds
            budget.

            Returns:
                - 0.0 if deadline has passed (remaining <= 0)
                - Exact remaining seconds otherwise (never negative)

            The clamping to 0.0 ensures callers receive a non-negative value even
            when the deadline has already elapsed.
            """
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return 0.0
            return remaining

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
                # Kill job on timeout (best effort, with very short timeout).
                # The 1.0s timeout below is a separate, best-effort cleanup budget
                # and is NOT counted against the client's max_seconds SLA. By this
                # point the max_seconds deadline has already been exceeded.
                with contextlib.suppress(MCPClientError):
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

    except MCPClientError as e:
        # Transport/bridge-level errors (including HTTP timeouts during polling)
        # are NOT client-side max_seconds deadline expiry.
        # Only the branches above that return status='timeout' (deadline checks before
        # starting, during polling, and when fetching output) represent true timeouts.
        # All other MCPClientError exceptions return status='failed'.
        return {"status": "failed", "job_id": job_id, "error": _format_bridge_error(e)}


def cmd_list(client: HttpMCPClient) -> dict[str, Any]:
    """List all jobs.

    Args:
        client: HTTP MCP client instance.

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
    except MCPClientError as e:
        return {"status": "failed", "error": _format_bridge_error(e)}


def cmd_cancel(client: HttpMCPClient, job_id: str) -> dict[str, Any]:
    """Cancel a running job.

    Args:
        client: HTTP MCP client instance.
        job_id: ID of job to cancel.

    Returns:
        Result dict with status.
    """
    try:
        call_mcp_tool(client, "kill_job", {"job_id": job_id})
    except MCPClientError as e:
        return {"status": "failed", "job_id": job_id, "error": _format_bridge_error(e)}
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

    # Top-level arguments for bridge configuration (apply to all subcommands)
    parser.add_argument(
        "--server-url",
        help="MCP bridge server URL (overrides MCP_BRIDGE_URL env var)",
    )
    parser.add_argument(
        "--socket-path",
        help=(
            "Unix socket path for MCP bridge "
            "(overrides MCP_BRIDGE_SOCKET env var, takes precedence over --server-url)"
        ),
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

    try:
        client = get_mcp_client(
            base_url=args.server_url,
            socket_path=args.socket_path,
        )

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
        result = {"status": "failed", "error": _format_bridge_error(e)}
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


if __name__ == "__main__":
    sys.exit(main())
