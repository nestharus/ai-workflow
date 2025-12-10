"""CLI client for sandbox socket server communication.

Provides synchronous functions to communicate with the sandbox server
via Unix domain socket.
"""

from __future__ import annotations

import json
import socket
import sys
import time

from scripts.pr.sandbox.constants import DEFAULT_SOCKET_PATH
from scripts.pr.sandbox.protocol import (
    ConflictResponse,
    ErrorResponse,
    MergeRequest,
    ProgressResponse,
    QueuedResponse,
    RebaseRequest,
    Response,
    StatusRequest,
    SuccessResponse,
    parse_response,
)

# Timeout for socket operations (seconds)
SOCKET_TIMEOUT = 30.0

# Initial polling interval when waiting for operation (seconds)
POLL_INTERVAL = 1.0

# Maximum polling interval for backoff (seconds)
MAX_POLL_INTERVAL = 10.0

# Backoff multiplier for increasing poll interval
POLL_BACKOFF_MULTIPLIER = 1.5

# Maximum wait time for polling operations (seconds)
MAX_WAIT_TIME = 300.0  # 5 minutes


class SandboxClientError(Exception):
    """Error communicating with sandbox server."""


def _connect(socket_path: str) -> socket.socket:
    """Connect to the sandbox server.

    Args:
        socket_path: Path to the Unix domain socket.

    Returns:
        Connected socket.

    Raises:
        SandboxClientError: If connection fails.
    """
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(SOCKET_TIMEOUT)
            sock.connect(socket_path)
            return sock
        except Exception:
            sock.close()
            raise
    except FileNotFoundError:
        raise SandboxClientError(
            f"Sandbox server socket not found at {socket_path}. Is the server running?"
        ) from None
    except ConnectionRefusedError:
        raise SandboxClientError(
            f"Connection refused to {socket_path}. Is the server running?"
        ) from None
    except TimeoutError:
        raise SandboxClientError(f"Connection timeout to {socket_path}.") from None
    except OSError as e:
        raise SandboxClientError(f"Socket error: {e}") from e


def _send_request(sock: socket.socket, request_json: str) -> str:
    """Send a request and receive a response.

    Args:
        sock: Connected socket.
        request_json: JSON string to send.

    Returns:
        Response JSON string.

    Raises:
        SandboxClientError: If communication fails.
    """
    try:
        # Send request with newline delimiter
        sock.sendall(request_json.encode() + b"\n")

        # Receive response (read until newline)
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break

        if not data:
            raise SandboxClientError("No response from server")

        if b"\n" not in data:
            raise SandboxClientError("Connection closed before newline")

        try:
            return data.split(b"\n", 1)[0].decode()
        except UnicodeDecodeError as e:
            raise SandboxClientError("Invalid UTF-8 in response") from e

    except TimeoutError:
        raise SandboxClientError("Request timeout") from None
    except OSError as e:
        raise SandboxClientError(f"Socket error: {e}") from e


def send_rebase(
    branch: str,
    target: str,
    socket_path: str = DEFAULT_SOCKET_PATH,
    wait: bool = True,
    verbose: bool = False,
) -> Response:
    """Send a rebase request to the sandbox server.

    Args:
        branch: Branch to rebase.
        target: Target branch to rebase onto.
        socket_path: Path to the Unix domain socket.
        wait: If True, wait for operation to complete.
        verbose: If True, print progress messages.

    Returns:
        Response from server.

    Raises:
        SandboxClientError: If communication fails.
    """
    request = RebaseRequest(branch=branch, target=target)

    sock = _connect(socket_path)
    try:
        # Send rebase request
        response_json = _send_request(sock, request.to_json())
        try:
            response = parse_response(response_json)
        except (ValueError, TypeError) as e:
            raise SandboxClientError(f"Invalid response from server: {e}") from e

        # If not waiting or got a final response, return immediately
        if not wait or isinstance(response, (SuccessResponse, ConflictResponse, ErrorResponse)):
            return response

        # If queued or in progress, wait for completion
        if isinstance(response, QueuedResponse):
            if verbose:
                print(f"Operation queued at position {response.position}")

            # Poll for status
            return _wait_for_completion(sock, request.request_id, socket_path, verbose)

        if isinstance(response, ProgressResponse):
            if verbose:
                print(f"In progress: {response.message}")
            return _wait_for_completion(sock, request.request_id, socket_path, verbose)

        return response

    finally:
        sock.close()


def send_merge(
    branch: str,
    target: str,
    socket_path: str = DEFAULT_SOCKET_PATH,
    wait: bool = True,
    verbose: bool = False,
) -> Response:
    """Send a merge request to the sandbox server.

    Args:
        branch: Branch to merge into.
        target: Target branch to merge from.
        socket_path: Path to the Unix domain socket.
        wait: If True, wait for operation to complete.
        verbose: If True, print progress messages.

    Returns:
        Response from server.

    Raises:
        SandboxClientError: If communication fails.
    """
    request = MergeRequest(branch=branch, target=target)

    sock = _connect(socket_path)
    try:
        # Send merge request
        response_json = _send_request(sock, request.to_json())
        try:
            response = parse_response(response_json)
        except (ValueError, TypeError) as e:
            raise SandboxClientError(f"Invalid response from server: {e}") from e

        # If not waiting or got a final response, return immediately
        if not wait or isinstance(response, (SuccessResponse, ConflictResponse, ErrorResponse)):
            return response

        # If queued or in progress, wait for completion
        if isinstance(response, QueuedResponse):
            if verbose:
                print(f"Operation queued at position {response.position}")

            # Poll for status
            return _wait_for_completion(sock, request.request_id, socket_path, verbose)

        if isinstance(response, ProgressResponse):
            if verbose:
                print(f"In progress: {response.message}")
            return _wait_for_completion(sock, request.request_id, socket_path, verbose)

        return response

    finally:
        sock.close()


def get_status(
    request_id: str | None = None,
    socket_path: str = DEFAULT_SOCKET_PATH,
) -> Response:
    """Get status of an operation or all operations.

    Args:
        request_id: Specific request ID, or None for all operations.
        socket_path: Path to the Unix domain socket.

    Returns:
        Status response from server.

    Raises:
        SandboxClientError: If communication fails.
    """
    request = StatusRequest(request_id=request_id)

    sock = _connect(socket_path)
    try:
        response_json = _send_request(sock, request.to_json())
        try:
            return parse_response(response_json)
        except (ValueError, TypeError) as e:
            raise SandboxClientError(f"Invalid response from server: {e}") from e
    finally:
        sock.close()


def _wait_for_completion(
    sock: socket.socket,
    request_id: str,
    socket_path: str,
    verbose: bool,
    max_wait: float = MAX_WAIT_TIME,
    initial_interval: float = POLL_INTERVAL,
) -> Response:
    """Wait for an operation to complete by polling status.

    Uses exponential backoff to reduce server load during long operations.
    The poll interval starts at `initial_interval` and increases by
    POLL_BACKOFF_MULTIPLIER each iteration, up to MAX_POLL_INTERVAL.

    Args:
        sock: Connected socket (may be closed, will reconnect).
        request_id: Request ID to wait for.
        socket_path: Path to socket for reconnection.
        verbose: If True, print progress messages.
        max_wait: Maximum time to wait in seconds (default 5 minutes).
        initial_interval: Starting poll interval (default POLL_INTERVAL).

    Returns:
        Final response (SuccessResponse, ConflictResponse, or ErrorResponse on timeout).
    """
    # Close the original socket since the server may need
    # to process other operations first
    sock.close()

    start_time = time.monotonic()
    current_interval = max(1e-3, initial_interval)

    while True:
        elapsed = time.monotonic() - start_time
        remaining = max_wait - elapsed
        if remaining <= 0:
            if verbose:
                print(f"Timeout waiting for operation after {max_wait} seconds")
            return ErrorResponse(
                request_id=request_id,
                message=f"Timeout waiting for operation after {max_wait} seconds",
            )

        # Sleep no longer than the remaining time to avoid overshooting max_wait
        sleep_time = min(current_interval, remaining)
        time.sleep(sleep_time)

        try:
            response = get_status(request_id, socket_path)

            if isinstance(response, (SuccessResponse, ConflictResponse, ErrorResponse)):
                return response
            elif isinstance(response, ProgressResponse) and verbose:
                print(f"In progress: {response.message}")
            elif isinstance(response, QueuedResponse) and verbose:
                print(f"Still queued at position {response.position}")

        except SandboxClientError as e:
            if verbose:
                print(f"Status check failed: {e}")
            # Continue polling

        # Increase interval with backoff (up to max)
        current_interval = min(
            current_interval * POLL_BACKOFF_MULTIPLIER,
            MAX_POLL_INTERVAL,
        )


def format_response(response: Response) -> str:
    """Format a response for CLI output.

    Args:
        response: Response to format.

    Returns:
        Formatted string.
    """
    if isinstance(response, SuccessResponse):
        result = response.result
        if "message" in result:
            return f"SUCCESS: {result['message']}"
        return f"SUCCESS: {json.dumps(result)}"
    elif isinstance(response, ConflictResponse):
        files = ", ".join(map(str, response.files))
        return f"CONFLICT: {files}"
    elif isinstance(response, QueuedResponse):
        return f"QUEUED: position {response.position}"
    elif isinstance(response, ProgressResponse):
        return f"IN PROGRESS: {response.message}"
    elif isinstance(response, ErrorResponse):
        return f"ERROR: {response.message}"
    else:
        return f"UNKNOWN: {response}"


def main() -> int:
    """CLI entry point for sandbox client."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Sandbox server client",
    )
    parser.add_argument(
        "--socket",
        default=DEFAULT_SOCKET_PATH,
        help="Path to Unix domain socket",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print progress messages",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # rebase command
    rebase_parser = subparsers.add_parser(
        "rebase",
        help="Rebase a branch onto a target",
    )
    rebase_parser.add_argument(
        "--branch",
        required=True,
        help="Branch to rebase",
    )
    rebase_parser.add_argument(
        "--target",
        required=True,
        help="Target branch to rebase onto",
    )
    rebase_parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Don't wait for operation to complete",
    )

    # merge command
    merge_parser = subparsers.add_parser(
        "merge",
        help="Merge a target branch into a branch",
    )
    merge_parser.add_argument(
        "--branch",
        required=True,
        help="Branch to merge into",
    )
    merge_parser.add_argument(
        "--target",
        required=True,
        help="Target branch to merge from",
    )
    merge_parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Don't wait for operation to complete",
    )

    # status command
    status_parser = subparsers.add_parser(
        "status",
        help="Get status of operations",
    )
    status_parser.add_argument(
        "--request-id",
        default=None,
        help="Specific request ID (omit for all)",
    )

    args = parser.parse_args()

    try:
        if args.command == "rebase":
            response = send_rebase(
                branch=args.branch,
                target=args.target,
                socket_path=args.socket,
                wait=not args.no_wait,
                verbose=args.verbose,
            )
            print(format_response(response))
            if isinstance(response, SuccessResponse):
                return 0
            elif isinstance(response, ConflictResponse):
                return 2
            return 1

        elif args.command == "merge":
            response = send_merge(
                branch=args.branch,
                target=args.target,
                socket_path=args.socket,
                wait=not args.no_wait,
                verbose=args.verbose,
            )
            print(format_response(response))
            if isinstance(response, SuccessResponse):
                return 0
            elif isinstance(response, ConflictResponse):
                return 2
            return 1

        elif args.command == "status":
            response = get_status(
                request_id=args.request_id,
                socket_path=args.socket,
            )
            print(format_response(response))
            if isinstance(response, ErrorResponse):
                return 1
            return 0

        return 1

    except SandboxClientError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
