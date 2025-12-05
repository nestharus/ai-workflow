"""MCP Bridge request/response schemas."""

from app.contracts.schemas import (
    ErrorResponse,
    HealthResponse,
    MCPCallRequest,
    ServerInfo,
    ServersResponse,
)

__all__ = [
    "ErrorResponse",
    "HealthResponse",
    "MCPCallRequest",
    "ServerInfo",
    "ServersResponse",
]
