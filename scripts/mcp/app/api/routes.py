"""API routes for MCP Bridge."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Path, status

from app.contracts.schemas import (
    ErrorResponse,
    HealthResponse,
    MCPCallRequest,
    ServerInfo,
    ServersResponse,
)
from app.services.manager import MCPClient, MCPError
from app.services.sse_client import MCPSSEError

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_client(
    server_name: str,
    clients: dict[str, MCPClient],
) -> MCPClient:
    """Get the MCP client for the given server name."""
    if server_name not in clients:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": f"Server '{server_name}' not found", "details": None},
        )
    return clients[server_name]


def _get_default_client(clients: dict[str, MCPClient]) -> MCPClient:
    """Get the default MCP client for legacy endpoints."""
    if "default" in clients:
        return clients["default"]
    if clients:
        return next(iter(clients.values()))
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"error": "No MCP servers configured", "details": None},
    )


def create_router(
    get_config: Any,
    get_clients: Any,
) -> APIRouter:
    """Create API router with injected dependencies.

    Args:
        get_config: Callable that returns the MCPConfig.
        get_clients: Callable that returns the clients dict.

    Returns:
        Configured APIRouter.
    """
    api_router = APIRouter()

    @api_router.get(
        "/mcp/servers",
        response_model=ServersResponse,
        summary="List configured MCP servers",
        description="Get a list of all configured MCP servers and their status",
    )
    async def list_servers() -> ServersResponse:
        """List all configured MCP servers."""
        config = get_config()
        clients = get_clients()
        servers = []
        for name, client in clients.items():
            server_config = config.servers.get(name) if config else None
            transport = "unknown"
            if server_config:
                transport = server_config.transport.value

            servers.append(
                ServerInfo(
                    name=name,
                    transport=transport,
                    healthy=client.is_alive(),
                )
            )
        return ServersResponse(servers=servers)

    @api_router.get(
        "/mcp/{server}/tools",
        summary="List available MCP tools for a server",
        description="Query the specified MCP server for available tools",
        responses={
            status.HTTP_200_OK: {"description": "List of available tools"},
            status.HTTP_404_NOT_FOUND: {
                "model": ErrorResponse,
                "description": "Server not found",
            },
            status.HTTP_502_BAD_GATEWAY: {
                "model": ErrorResponse,
                "description": "MCP server communication error",
            },
        },
    )
    async def list_server_tools(
        server: str = Path(..., description="Name of the MCP server"),
    ) -> dict[str, Any]:
        """List available MCP tools for a specific server."""
        clients = get_clients()
        client = _get_client(server, clients)

        try:
            result = client.list_tools()
            return result
        except (MCPError, MCPSSEError) as e:
            logger.exception(f"MCP communication error with server '{server}'")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"error": str(e), "details": None},
            ) from e

    @api_router.get(
        "/mcp/{server}/tools/{tool_name}",
        summary="Get information about a specific MCP tool",
        description="Query the specified MCP server for details about a specific tool",
        responses={
            status.HTTP_200_OK: {"description": "Tool information"},
            status.HTTP_404_NOT_FOUND: {
                "model": ErrorResponse,
                "description": "Server or tool not found",
            },
            status.HTTP_502_BAD_GATEWAY: {
                "model": ErrorResponse,
                "description": "MCP server communication error",
            },
        },
    )
    async def get_server_tool(
        server: str = Path(..., description="Name of the MCP server"),
        tool_name: str = Path(..., description="Name of the tool"),
    ) -> dict[str, Any]:
        """Get information about a specific tool on a server."""
        clients = get_clients()
        client = _get_client(server, clients)

        try:
            result = client.list_tools()
            tools = result.get("tools", [])
            for tool in tools:
                if tool.get("name") == tool_name:
                    return tool
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": f"Tool '{tool_name}' not found on server '{server}'", "details": None},
            )
        except (MCPError, MCPSSEError) as e:
            logger.exception(f"MCP communication error with server '{server}'")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"error": str(e), "details": None},
            ) from e

    @api_router.post(
        "/mcp/{server}/call",
        summary="Call an MCP tool on a specific server",
        description="Execute an MCP tool on the specified server and return the result",
        responses={
            status.HTTP_200_OK: {"description": "Tool executed successfully"},
            status.HTTP_404_NOT_FOUND: {
                "model": ErrorResponse,
                "description": "Server not found",
            },
            status.HTTP_502_BAD_GATEWAY: {
                "model": ErrorResponse,
                "description": "MCP server communication error",
            },
        },
    )
    async def call_server_tool(
        request: MCPCallRequest,
        server: str = Path(..., description="Name of the MCP server"),
    ) -> dict[str, Any]:
        """Call an MCP tool on a specific server."""
        clients = get_clients()
        client = _get_client(server, clients)

        try:
            result = client.call_tool(
                name=request.tool,
                arguments=request.arguments,
                timeout=request.timeout,
            )
            return result
        except (MCPError, MCPSSEError) as e:
            logger.exception(f"MCP communication error with server '{server}'")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"error": str(e), "details": None},
            ) from e

    @api_router.post(
        "/mcp/call",
        summary="Call an MCP tool (legacy)",
        description="Execute an MCP tool on the default server. "
        "Use /mcp/{server}/call for multi-server setups.",
        responses={
            status.HTTP_200_OK: {"description": "Tool executed successfully"},
            status.HTTP_502_BAD_GATEWAY: {
                "model": ErrorResponse,
                "description": "MCP server communication error",
            },
        },
    )
    async def mcp_call(request: MCPCallRequest) -> dict[str, Any]:
        """Call an MCP tool on the default server (legacy endpoint)."""
        clients = get_clients()
        client = _get_default_client(clients)

        try:
            result = client.call_tool(
                name=request.tool,
                arguments=request.arguments,
                timeout=request.timeout,
            )
            return result
        except (MCPError, MCPSSEError) as e:
            logger.exception("MCP communication error")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"error": str(e), "details": None},
            ) from e

    @api_router.get(
        "/mcp/tools",
        summary="List available MCP tools (legacy)",
        description="Query the default MCP server for available tools. "
        "Use /mcp/{server}/tools for multi-server setups.",
        responses={
            status.HTTP_200_OK: {"description": "List of available tools"},
            status.HTTP_502_BAD_GATEWAY: {
                "model": ErrorResponse,
                "description": "MCP server communication error",
            },
        },
    )
    async def list_tools() -> dict[str, Any]:
        """List available MCP tools on the default server (legacy endpoint)."""
        clients = get_clients()
        client = _get_default_client(clients)

        try:
            result = client.list_tools()
            return result
        except (MCPError, MCPSSEError) as e:
            logger.exception("MCP communication error")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"error": str(e), "details": None},
            ) from e

    @api_router.get(
        "/health",
        response_model=HealthResponse,
        summary="Health check",
        description="Check if the MCP bridge is ready (at least one server is alive)",
        responses={
            status.HTTP_200_OK: {
                "model": HealthResponse,
                "description": "Bridge is healthy",
            },
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": HealthResponse,
                "description": "Bridge is unhealthy (no MCP servers alive)",
            },
        },
    )
    async def health_check() -> HealthResponse:
        """Check if the MCP bridge is healthy."""
        clients = get_clients()
        if any(client.is_alive() for client in clients.values()):
            return HealthResponse(status="ok")

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=HealthResponse(status="unhealthy").model_dump(),
        )

    return api_router


__all__ = ["create_router", "router"]
