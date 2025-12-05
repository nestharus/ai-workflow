"""Pydantic schemas for MCP Bridge API requests and responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MCPCallRequest(BaseModel):
    """Request body for the /mcp/{server}/call endpoint."""

    tool: str = Field(..., description="Name of the MCP tool to call")
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments to pass to the tool",
    )
    timeout: float = Field(
        default=30.0,
        ge=0.1,
        le=600.0,
        description="Timeout in seconds for the MCP call",
    )


class ErrorResponse(BaseModel):
    """Error response body for failed requests."""

    error: str = Field(..., description="Error message")
    details: Any | None = Field(default=None, description="Additional error details")


class HealthResponse(BaseModel):
    """Response body for the /health endpoint."""

    status: str = Field(..., description="Health status: 'healthy' or 'unhealthy'")


class ServerInfo(BaseModel):
    """Information about a configured MCP server."""

    name: str = Field(..., description="Server name")
    transport: str = Field(..., description="Transport type (stdio or sse)")
    healthy: bool = Field(..., description="Whether the server is connected")


class ServersResponse(BaseModel):
    """Response body for the /mcp/servers endpoint."""

    servers: list[ServerInfo] = Field(..., description="List of configured servers")


__all__ = [
    "ErrorResponse",
    "HealthResponse",
    "MCPCallRequest",
    "ServerInfo",
    "ServersResponse",
]
