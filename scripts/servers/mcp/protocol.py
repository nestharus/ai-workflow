"""Protocol definitions for MCP Bridge socket server communication.

Defines request and response dataclasses for the MCP bridge socket server,
mirroring the HTTP API schemas from `app/contracts/schemas.py` for compatibility.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


def _generate_request_id() -> str:
    """Generate a unique request ID."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Error Types (matching schemas.ErrorType)
# ---------------------------------------------------------------------------


class ErrorType(str, Enum):
    """Error types for the error envelope.

    These match the ErrorType enum in schemas.py for compatibility.
    """

    BAD_REQUEST = "BAD_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    JSONRPC_ERROR = "JSONRPC_ERROR"
    TIMEOUT = "TIMEOUT"
    BUSY = "BUSY"
    PROVIDER_CRASHED = "PROVIDER_CRASHED"
    INTERNAL = "INTERNAL"


# ---------------------------------------------------------------------------
# Request Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ListServersRequest:
    """Request to list all configured MCP servers.

    Corresponds to GET /mcp/servers.
    """

    id: str = field(default_factory=_generate_request_id)
    method: str = field(default="list_servers", init=False)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ListServersRequest:
        """Create from dictionary."""
        return cls(id=data.get("id") or _generate_request_id())


@dataclass
class ListToolsRequest:
    """Request to list tools for a specific MCP server.

    Corresponds to GET /mcp/{server}/tools.
    """

    server: str
    id: str = field(default_factory=_generate_request_id)
    method: str = field(default="list_tools", init=False)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ListToolsRequest:
        """Create from dictionary."""
        server = data.get("server")
        if server is None:
            raise ValueError("Missing 'server' in list_tools request")
        return cls(
            server=server,
            id=data.get("id") or _generate_request_id(),
        )


@dataclass
class GetServerToolRequest:
    """Request to get information about a specific tool on a server.

    Corresponds to GET /mcp/{server}/tools/{tool_name}.
    """

    server: str
    tool_name: str
    id: str = field(default_factory=_generate_request_id)
    method: str = field(default="get_server_tool", init=False)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GetServerToolRequest:
        """Create from dictionary."""
        server = data.get("server")
        if server is None:
            raise ValueError("Missing 'server' in get_server_tool request")
        tool_name = data.get("tool_name")
        if tool_name is None:
            raise ValueError("Missing 'tool_name' in get_server_tool request")
        return cls(
            server=server,
            tool_name=tool_name,
            id=data.get("id") or _generate_request_id(),
        )


@dataclass
class CallToolRequest:
    """Request to call an MCP tool on a specific server.

    Corresponds to POST /mcp/{server}/call with MCPCallRequest body.
    """

    server: str
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    id: str = field(default_factory=_generate_request_id)
    method: str = field(default="call_tool", init=False)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CallToolRequest:
        """Create from dictionary."""
        server = data.get("server")
        if server is None:
            raise ValueError("Missing 'server' in call_tool request")
        tool = data.get("tool")
        if tool is None:
            raise ValueError("Missing 'tool' in call_tool request")
        arguments = data.get("arguments")
        timeout_seconds_raw = data.get("timeout_seconds")
        if timeout_seconds_raw is None:
            timeout_seconds = 30.0
        else:
            try:
                timeout_seconds = float(timeout_seconds_raw)
            except (TypeError, ValueError) as e:
                raise ValueError(
                    f"Invalid 'timeout_seconds' value: {timeout_seconds_raw!r}; "
                    "expected a numeric value"
                ) from e
        return cls(
            server=server,
            tool=tool,
            arguments=arguments if arguments is not None else {},
            timeout_seconds=timeout_seconds,
            id=data.get("id") or _generate_request_id(),
        )


@dataclass
class HealthRequest:
    """Request to check health status of the MCP bridge.

    Corresponds to GET /health.
    """

    id: str = field(default_factory=_generate_request_id)
    method: str = field(default="health", init=False)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HealthRequest:
        """Create from dictionary."""
        return cls(id=data.get("id") or _generate_request_id())


# Type alias for all request types
Request = (
    ListServersRequest | ListToolsRequest | GetServerToolRequest | CallToolRequest | HealthRequest
)


# ---------------------------------------------------------------------------
# Response Dataclasses (matching HTTP API response shapes)
# ---------------------------------------------------------------------------


@dataclass
class ServerInfo:
    """Information about a configured MCP server.

    Mirrors schemas.ServerInfo for JSON compatibility.
    """

    name: str
    transport: str
    healthy: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary matching Pydantic model_dump()."""
        return {
            "name": self.name,
            "transport": self.transport,
            "healthy": self.healthy,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServerInfo:
        """Create from dictionary."""
        name = data.get("name")
        if name is None:
            raise ValueError("Missing required field 'name' for ServerInfo")
        transport = data.get("transport")
        if transport is None:
            raise ValueError("Missing required field 'transport' for ServerInfo")
        healthy = data.get("healthy")
        if healthy is None:
            raise ValueError("Missing required field 'healthy' for ServerInfo")
        return cls(
            name=name,
            transport=transport,
            healthy=healthy,
        )


@dataclass
class ServersResponse:
    """Response containing list of MCP servers.

    Mirrors schemas.ServersResponse for JSON compatibility.
    """

    servers: list[ServerInfo]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary matching Pydantic model_dump()."""
        return {
            "servers": [s.to_dict() for s in self.servers],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServersResponse:
        """Create from dictionary."""
        servers = [ServerInfo.from_dict(s) for s in data.get("servers", [])]
        return cls(servers=servers)


@dataclass
class MCPCallResponse:
    """Response containing result from an MCP tool call.

    Mirrors schemas.MCPCallResponse for JSON compatibility.
    """

    result: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary matching Pydantic model_dump()."""
        return {
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MCPCallResponse:
        """Create from dictionary."""
        return cls(result=data.get("result", {}))


@dataclass
class HealthResponse:
    """Response containing health status.

    Mirrors schemas.HealthResponse for JSON compatibility.
    """

    status: str
    provider: str = "running"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary matching Pydantic model_dump()."""
        return {
            "status": self.status,
            "provider": self.provider,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HealthResponse:
        """Create from dictionary."""
        status = data.get("status")
        if status is None:
            raise ValueError("Missing required field 'status' for HealthResponse")
        return cls(
            status=status,
            provider=data.get("provider", "running"),
        )


@dataclass
class ErrorDetail:
    """Error detail for the error envelope.

    Mirrors schemas.ErrorDetail for JSON compatibility.
    """

    type: ErrorType
    message: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary matching Pydantic model_dump()."""
        return {
            "type": self.type.value,
            "message": self.message,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ErrorDetail:
        """Create from dictionary."""
        error_type = data.get("type")
        if error_type is None:
            raise ValueError("Missing 'type' in error detail")
        if isinstance(error_type, str):
            error_type = ErrorType(error_type)
        elif not isinstance(error_type, ErrorType):
            raise TypeError("Invalid 'type' in error detail; expected ErrorType or string")
        message = data.get("message")
        if message is None:
            raise ValueError("Missing 'message' in error detail")
        details = data.get("details")
        if details is not None and not isinstance(details, dict):
            raise ValueError("Invalid 'details' in error detail; expected dict or null")
        return cls(
            type=error_type,
            message=message,
            details=details,
        )


# ---------------------------------------------------------------------------
# Response Envelope (wraps all responses)
# ---------------------------------------------------------------------------


@dataclass
class SuccessEnvelope:
    """Success response envelope containing a result.

    Format: {"id": "...", "status": "success", "result": {...}}
    """

    id: str
    result: dict[str, Any]
    status: str = field(default="success", init=False)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "status": self.status,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SuccessEnvelope:
        """Create from dictionary."""
        request_id = data.get("id")
        if request_id is None:
            raise ValueError("Missing 'id' in success envelope")
        return cls(
            id=request_id,
            result=data.get("result", {}),
        )


@dataclass
class ErrorEnvelope:
    """Error response envelope containing error details.

    Format: {"id": "...", "status": "error", "error": {"type": "...", "message": "..."}}
    """

    id: str
    error: ErrorDetail
    status: str = field(default="error", init=False)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "status": self.status,
            "error": self.error.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ErrorEnvelope:
        """Create from dictionary."""
        request_id = data.get("id")
        if request_id is None:
            raise ValueError("Missing 'id' in error envelope")
        error_data = data.get("error")
        if error_data is None:
            raise ValueError("Missing 'error' in error envelope")
        return cls(
            id=request_id,
            error=ErrorDetail.from_dict(error_data),
        )


# Type alias for response envelopes
ResponseEnvelope = SuccessEnvelope | ErrorEnvelope


# ---------------------------------------------------------------------------
# Parsing Functions
# ---------------------------------------------------------------------------


def parse_request(data: str | dict[str, Any]) -> Request:
    """Parse a JSON string or dict into a request object.

    Args:
        data: JSON string or dictionary.

    Returns:
        Appropriate request object.

    Raises:
        ValueError: If the request is invalid or has an unknown method.
        TypeError: If the JSON is not an object.
    """
    if isinstance(data, str):
        try:
            obj = json.loads(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}") from e
    else:
        obj = data

    if not isinstance(obj, dict):
        raise TypeError("Invalid request: expected JSON object")

    method = obj.get("method")
    if method is None:
        raise ValueError("Missing required field: 'method'")

    if method == "list_servers":
        return ListServersRequest.from_dict(obj)
    elif method == "list_tools":
        return ListToolsRequest.from_dict(obj)
    elif method == "get_server_tool":
        return GetServerToolRequest.from_dict(obj)
    elif method == "call_tool":
        return CallToolRequest.from_dict(obj)
    elif method == "health":
        return HealthRequest.from_dict(obj)
    else:
        raise ValueError(f"Unknown method: {method}")


def parse_response(data: str | dict[str, Any]) -> ResponseEnvelope:
    """Parse a JSON string or dict into a response envelope.

    Args:
        data: JSON string or dictionary.

    Returns:
        SuccessEnvelope or ErrorEnvelope.

    Raises:
        ValueError: If the response is invalid or has an unknown status.
        TypeError: If the JSON is not an object.
    """
    if isinstance(data, str):
        try:
            obj = json.loads(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}") from e
    else:
        obj = data

    if not isinstance(obj, dict):
        raise TypeError("Invalid response: expected JSON object")

    status = obj.get("status")
    if status is None:
        raise ValueError("Missing required field: 'status'")

    if status == "success":
        return SuccessEnvelope.from_dict(obj)
    elif status == "error":
        return ErrorEnvelope.from_dict(obj)
    else:
        raise ValueError(f"Unknown status: {status}")


def to_json(response: ResponseEnvelope) -> str:
    """Serialize a response envelope to JSON string.

    Args:
        response: A SuccessEnvelope or ErrorEnvelope.

    Returns:
        JSON string representation.
    """
    return response.to_json()


# ---------------------------------------------------------------------------
# Helper Functions for Creating Responses
# ---------------------------------------------------------------------------


def create_success_response(
    request_id: str,
    result: dict[str, Any],
) -> SuccessEnvelope:
    """Create a success response envelope.

    Args:
        request_id: The request ID from the original request.
        result: The result dictionary (method-specific response data).

    Returns:
        SuccessEnvelope ready for serialization.
    """
    return SuccessEnvelope(id=request_id, result=result)


def create_error_response(
    request_id: str,
    error_type: ErrorType,
    message: str,
    details: dict[str, Any] | None = None,
) -> ErrorEnvelope:
    """Create an error response envelope.

    Args:
        request_id: The request ID from the original request.
        error_type: The error type enum value.
        message: Human-readable error message.
        details: Optional additional details dict.

    Returns:
        ErrorEnvelope ready for serialization.
    """
    return ErrorEnvelope(
        id=request_id,
        error=ErrorDetail(
            type=error_type,
            message=message,
            details=details,
        ),
    )


__all__ = [
    "CallToolRequest",
    "ErrorDetail",
    "ErrorEnvelope",
    "ErrorType",
    "GetServerToolRequest",
    "HealthRequest",
    "HealthResponse",
    "ListServersRequest",
    "ListToolsRequest",
    "MCPCallResponse",
    "Request",
    "ResponseEnvelope",
    "ServerInfo",
    "ServersResponse",
    "SuccessEnvelope",
    "create_error_response",
    "create_success_response",
    "parse_request",
    "parse_response",
    "to_json",
]
