"""Pydantic schemas for MCP Bridge API requests and responses."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MCPCallRequest(BaseModel):
    """Request body for the /mcp/{server}/call endpoint."""

    model_config = {"populate_by_name": True}

    tool: str = Field(..., description="Name of the MCP tool to call")
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments to pass to the tool",
    )
    timeout_seconds: float = Field(
        default=30.0,
        ge=0.1,
        le=600.0,
        alias="timeout",  # Backward compatibility with existing code using 'timeout'
        description="Timeout in seconds for the MCP call",
    )


class MCPCallResponse(BaseModel):
    """Response body for successful /mcp/{server}/call endpoint."""

    result: dict[str, Any] = Field(..., description="Tool result dict (unwrapped from JSON-RPC)")


class ErrorType(str, Enum):
    """Error types for the error envelope."""

    BAD_REQUEST = "BAD_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    JSONRPC_ERROR = "JSONRPC_ERROR"
    TIMEOUT = "TIMEOUT"
    BUSY = "BUSY"
    PROVIDER_CRASHED = "PROVIDER_CRASHED"
    INTERNAL = "INTERNAL"


class ErrorDetail(BaseModel):
    """Error detail for the error envelope."""

    type: ErrorType = Field(..., description="Error type code")
    message: str = Field(..., description="Human readable error summary")
    details: dict[str, Any] | None = Field(default=None, description="Optional additional details")


class ErrorEnvelope(BaseModel):
    """Error response envelope per NES-47 specification."""

    error: ErrorDetail = Field(..., description="Error information")


class ErrorResponse(BaseModel):
    """Legacy error response body for failed requests (deprecated)."""

    error: str = Field(..., description="Error message")
    details: Any | None = Field(default=None, description="Additional error details")


class HealthResponse(BaseModel):
    """Response body for the /health endpoint per NES-47 specification."""

    status: str = Field(..., description="Health status: 'ok' or 'degraded'")
    provider: str = Field(default="running", description="Provider status: 'running' or 'down'")


class ServerInfo(BaseModel):
    """Information about a configured MCP server."""

    name: str = Field(..., description="Server name")
    transport: str = Field(..., description="Transport type (stdio or sse)")
    healthy: bool = Field(..., description="Whether the server is connected")


class ServersResponse(BaseModel):
    """Response body for the /mcp/servers endpoint."""

    servers: list[ServerInfo] = Field(..., description="List of configured servers")


__all__ = [
    "ErrorDetail",
    "ErrorEnvelope",
    "ErrorResponse",
    "ErrorType",
    "HealthResponse",
    "MCPCallRequest",
    "MCPCallResponse",
    "ServerInfo",
    "ServersResponse",
]
