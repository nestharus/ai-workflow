"""Command to merge a target branch into a branch using the sandbox server."""

from __future__ import annotations

import sys

from scripts.pr.sandbox.client import (
    DEFAULT_SOCKET_PATH,
    SandboxClientError,
    format_response,
    send_merge,
)
from scripts.pr.sandbox.protocol import ConflictResponse, SuccessResponse


def sandbox_merge_command(
    branch: str,
    target: str,
    socket_path: str | None = None,
    verbose: bool = False,
) -> int:
    """Merge a target branch into a branch using the sandbox server.

    Args:
        branch: Branch to merge into.
        target: Target branch to merge from.
        socket_path: Path to the sandbox server socket (defaults to DEFAULT_SOCKET_PATH).
        verbose: If True, print progress messages.

    Returns:
        Exit code:
        - 0 on success
        - 2 when conflicts are detected
        - 1 on errors
    """
    if socket_path is None:
        socket_path = DEFAULT_SOCKET_PATH

    try:
        response = send_merge(
            branch=branch,
            target=target,
            socket_path=socket_path,
            wait=True,
            verbose=verbose,
        )
        print(format_response(response))

        if isinstance(response, SuccessResponse):
            return 0
        elif isinstance(response, ConflictResponse):
            # Return exit code 2 for conflicts (distinguishable from errors)
            return 2
        return 1

    except SandboxClientError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
