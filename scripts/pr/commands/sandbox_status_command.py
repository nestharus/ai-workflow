"""Sandbox status command for retrieving sandbox operation status."""

from __future__ import annotations

import sys


def sandbox_status_command(
    request_id: str | None = None,
    socket_path: str | None = None,
) -> int:
    """Get status of sandbox operations.

    Args:
        request_id: Specific request ID, or None for all operations.
        socket_path: Path to the sandbox server socket (defaults to DEFAULT_SOCKET_PATH).

    Returns:
        Exit code:
        - 0 when status retrieval succeeds
        - 1 when an error response is returned or a client error occurs
    """
    from scripts.servers.sandbox.client import (
        DEFAULT_SOCKET_PATH,
        SandboxClientError,
        format_response,
        get_status,
    )
    from scripts.servers.sandbox.protocol import ErrorResponse

    if socket_path is None:
        socket_path = DEFAULT_SOCKET_PATH

    try:
        response = get_status(request_id=request_id, socket_path=socket_path)
        print(format_response(response))

        # Return 1 for error responses to maintain consistency with other commands
        if isinstance(response, ErrorResponse):
            return 1
        return 0

    except SandboxClientError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
