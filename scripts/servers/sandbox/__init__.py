"""Sandbox operations for isolated rebase/merge operations.

This package provides infrastructure for running git rebase and merge operations
in an isolated sandbox directory, separate from the user's main checkout.
"""

from __future__ import annotations

from scripts.servers.sandbox.constants import DEFAULT_SOCKET_PATH
from scripts.servers.sandbox.operations import (
    MergeResult,
    OperationResult,
    RebaseResult,
    ensure_sandbox_exists,
    get_conflicts,
    merge_in_sandbox,
    push_from_sandbox,
    rebase_in_sandbox,
    sync_sandbox_branch,
)
from scripts.servers.sandbox.protocol import (
    CancelRequest,
    ConflictResponse,
    ErrorResponse,
    MergeRequest,
    ProgressResponse,
    QueuedResponse,
    RebaseRequest,
    Request,
    Response,
    StatusRequest,
    SuccessResponse,
    parse_request,
    parse_response,
)

__all__ = [
    "DEFAULT_SOCKET_PATH",
    "CancelRequest",
    "ConflictResponse",
    "ErrorResponse",
    "MergeRequest",
    "MergeResult",
    "OperationResult",
    "ProgressResponse",
    "QueuedResponse",
    "RebaseRequest",
    "RebaseResult",
    "Request",
    "Response",
    "StatusRequest",
    "SuccessResponse",
    "ensure_sandbox_exists",
    "get_conflicts",
    "merge_in_sandbox",
    "parse_request",
    "parse_response",
    "push_from_sandbox",
    "rebase_in_sandbox",
    "sync_sandbox_branch",
]
