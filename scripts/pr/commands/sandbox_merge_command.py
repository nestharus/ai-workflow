"""Command to merge a target branch into a branch using the sandbox server."""

from __future__ import annotations

import sys

from scripts.pr import git_dao
from scripts.servers.sandbox.client import (
    DEFAULT_SOCKET_PATH,
    SandboxClientError,
    format_response,
    send_merge,
)
from scripts.servers.sandbox.protocol import ConflictResponse, SuccessResponse


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
    # Verify refs match before merge
    if verbose:
        print(f"Verifying local and remote refs match for {branch}...")
    refs_match, local_sha, remote_sha = git_dao.check_refs_match(branch)
    if not refs_match:
        if local_sha and remote_sha:
            print(
                f"ERROR: Refs mismatch - local={local_sha[:8]} remote={remote_sha[:8]}",
                file=sys.stderr,
            )
            print("Push or pull to sync before merging.", file=sys.stderr)
        else:
            print(f"ERROR: {remote_sha}", file=sys.stderr)
        return 1
    if verbose:
        print(f"Refs match: {local_sha[:8]}")

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
