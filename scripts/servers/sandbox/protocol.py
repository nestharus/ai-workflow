"""Protocol definitions for sandbox server communication.

Defines request and response dataclasses for the sandbox socket server,
along with JSON serialization/deserialization.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


def _generate_request_id() -> str:
    """Generate a unique request ID."""
    return str(uuid.uuid4())


@dataclass
class RebaseRequest:
    """Request to rebase a branch onto a target."""

    branch: str
    target: str
    request_id: str = field(default_factory=_generate_request_id)
    command: str = field(default="rebase", init=False)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RebaseRequest:
        """Create from dictionary."""
        branch = data.get("branch")
        if branch is None:
            raise ValueError("Missing 'branch' in rebase request")
        target = data.get("target")
        if target is None:
            raise ValueError("Missing 'target' in rebase request")
        return cls(
            branch=branch,
            target=target,
            request_id=data.get("request_id", _generate_request_id()),
        )


@dataclass
class MergeRequest:
    """Request to merge a target branch into a branch."""

    branch: str
    target: str
    request_id: str = field(default_factory=_generate_request_id)
    command: str = field(default="merge", init=False)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MergeRequest:
        """Create from dictionary."""
        branch = data.get("branch")
        if branch is None:
            raise ValueError("Missing 'branch' in merge request")
        target = data.get("target")
        if target is None:
            raise ValueError("Missing 'target' in merge request")
        return cls(
            branch=branch,
            target=target,
            request_id=data.get("request_id", _generate_request_id()),
        )


@dataclass
class StatusRequest:
    """Request for status of a specific operation or all operations."""

    request_id: str | None = None
    command: str = field(default="status", init=False)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StatusRequest:
        """Create from dictionary."""
        return cls(request_id=data.get("request_id"))


@dataclass
class CancelRequest:
    """Request to cancel an operation."""

    request_id: str
    command: str = field(default="cancel", init=False)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CancelRequest:
        """Create from dictionary."""
        request_id = data.get("request_id")
        if request_id is None:
            raise ValueError("Missing 'request_id' in cancel request")
        return cls(request_id=request_id)


@dataclass
class SuccessResponse:
    """Response indicating successful operation completion."""

    request_id: str
    result: dict[str, Any] = field(default_factory=dict)
    status: str = field(default="success", init=False)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SuccessResponse:
        """Create from dictionary."""
        request_id = data.get("request_id")
        if request_id is None:
            raise ValueError("Missing 'request_id' in success response")
        return cls(
            request_id=request_id,
            result=data.get("result", {}),
        )


@dataclass
class ConflictResponse:
    """Response indicating operation stopped due to conflicts."""

    request_id: str
    files: list[str]
    status: str = field(default="conflict", init=False)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConflictResponse:
        """Create from dictionary."""
        request_id = data.get("request_id")
        if request_id is None:
            raise ValueError("Missing 'request_id' in conflict response")
        files = data.get("files")
        if files is None:
            files = []
        elif not isinstance(files, list):
            raise ValueError("Invalid 'files' in conflict response: expected list")
        return cls(
            request_id=request_id,
            files=files,
        )


@dataclass
class QueuedResponse:
    """Response indicating operation has been queued."""

    request_id: str
    position: int
    status: str = field(default="queued", init=False)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueuedResponse:
        """Create from dictionary."""
        request_id = data.get("request_id")
        if request_id is None:
            raise ValueError("Missing 'request_id' in queued response")
        position = data.get("position")
        if position is None:
            raise ValueError("Missing 'position' in queued response")
        return cls(
            request_id=request_id,
            position=position,
        )


@dataclass
class ProgressResponse:
    """Response indicating operation is in progress."""

    request_id: str
    message: str
    status: str = field(default="in_progress", init=False)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProgressResponse:
        """Create from dictionary."""
        request_id = data.get("request_id")
        if request_id is None:
            raise ValueError("Missing 'request_id' in progress response")
        return cls(
            request_id=request_id,
            message=data.get("message", ""),
        )


@dataclass
class ErrorResponse:
    """Response indicating an error occurred."""

    request_id: str
    message: str
    status: str = field(default="error", init=False)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ErrorResponse:
        """Create from dictionary."""
        request_id = data.get("request_id")
        if request_id is None:
            raise ValueError("Missing 'request_id' in error response")
        return cls(
            request_id=request_id,
            message=data.get("message", "Unknown error"),
        )


@dataclass
class DiffMismatchResponse:
    """Response indicating rebase changed the PR diff unexpectedly."""

    request_id: str
    files: list[str]
    added_lines: int
    removed_lines: int
    status: str = field(default="diff_mismatch", init=False)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiffMismatchResponse:
        """Create from dictionary."""
        request_id = data.get("request_id")
        if request_id is None:
            raise ValueError("Missing 'request_id' in diff_mismatch response")
        files = data.get("files")
        if files is None:
            files = []
        elif not isinstance(files, list):
            raise ValueError("Invalid 'files' in diff_mismatch response: expected list")
        return cls(
            request_id=request_id,
            files=files,
            added_lines=data.get("added_lines", 0),
            removed_lines=data.get("removed_lines", 0),
        )


# Type alias for all request types
Request = RebaseRequest | MergeRequest | StatusRequest | CancelRequest

# Type alias for all response types
Response = (
    SuccessResponse
    | ConflictResponse
    | QueuedResponse
    | ProgressResponse
    | ErrorResponse
    | DiffMismatchResponse
)


def parse_request(data: str) -> Request:
    """Parse a JSON string into a request object.

    Args:
        data: JSON string.

    Returns:
        Appropriate request object.

    Raises:
        ValueError: If the request is invalid or has an unknown command.
        TypeError: If the JSON is not an object.
    """
    try:
        obj = json.loads(data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e

    if not isinstance(obj, dict):
        raise TypeError("Invalid request: expected JSON object")

    command = obj.get("command")
    if command is None:
        raise ValueError("Missing required field: 'command'")
    if command == "rebase":
        return RebaseRequest.from_dict(obj)
    elif command == "merge":
        return MergeRequest.from_dict(obj)
    elif command == "status":
        return StatusRequest.from_dict(obj)
    elif command == "cancel":
        return CancelRequest.from_dict(obj)
    else:
        raise ValueError(f"Unknown command: {command}")


def parse_response(data: str) -> Response:
    """Parse a JSON string into a response object.

    Args:
        data: JSON string.

    Returns:
        Appropriate response object.

    Raises:
        ValueError: If the response is invalid or has an unknown status.
        TypeError: If the JSON is not an object.
    """
    try:
        obj = json.loads(data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e

    if not isinstance(obj, dict):
        raise TypeError("Invalid response: expected JSON object")

    status = obj.get("status")
    if status is None:
        raise ValueError("Missing required field: 'status'")
    if status == "success":
        return SuccessResponse.from_dict(obj)
    elif status == "conflict":
        return ConflictResponse.from_dict(obj)
    elif status == "queued":
        return QueuedResponse.from_dict(obj)
    elif status == "in_progress":
        return ProgressResponse.from_dict(obj)
    elif status == "error":
        return ErrorResponse.from_dict(obj)
    elif status == "diff_mismatch":
        return DiffMismatchResponse.from_dict(obj)
    else:
        raise ValueError(f"Unknown status: {status}")
