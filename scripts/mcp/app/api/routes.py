"""API routes for MCP Bridge."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Path, status
from fastapi.responses import JSONResponse

from ..contracts.schemas import (
    ErrorDetail,
    ErrorEnvelope,
    ErrorType,
    HealthResponse,
    MCPCallRequest,
    MCPCallResponse,
    ServerInfo,
    ServersResponse,
)
from ..services.manager import (
    MCPBusyError,
    MCPClient,
    MCPError,
    MCPProviderCrashedError,
    MCPTimeoutError,
)
from ..services.sse_client import MCPSSEError

if TYPE_CHECKING:
    from ..core.config import MCPConfig

logger = logging.getLogger(__name__)


def _create_error_response(
    error_type: ErrorType,
    message: str,
    http_status: int,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """Create a standardized error response per NES-47 specification.

    Args:
        error_type: The error type enum value.
        message: Human-readable error message.
        http_status: HTTP status code.
        details: Optional additional details dict.

    Returns:
        JSONResponse with error envelope.
    """
    envelope = ErrorEnvelope(
        error=ErrorDetail(
            type=error_type,
            message=message,
            details=details,
        )
    )
    return JSONResponse(
        status_code=http_status,
        content=envelope.model_dump(),
    )


router = APIRouter()


def _get_client(
    server_name: str,
    clients: dict[str, MCPClient],
) -> MCPClient | JSONResponse:
    """Get the MCP client for the given server name.

    Returns:
        The MCPClient if found, or a JSONResponse with ErrorEnvelope if not found.
    """
    if server_name not in clients:
        return _create_error_response(
            error_type=ErrorType.NOT_FOUND,
            message=f"Server '{server_name}' not found",
            http_status=status.HTTP_404_NOT_FOUND,
        )
    return clients[server_name]


def _get_default_client(clients: dict[str, MCPClient]) -> MCPClient | JSONResponse:
    """Get the default MCP client for legacy endpoints.

    Returns:
        The MCPClient if found, or a JSONResponse with ErrorEnvelope if no servers configured.
    """
    if "default" in clients:
        return clients["default"]
    if clients:
        return next(iter(clients.values()))
    return _create_error_response(
        error_type=ErrorType.INTERNAL,
        message="No MCP servers configured",
        http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def create_router(
    get_config: Callable[[], MCPConfig | None],
    get_clients: Callable[[], dict[str, MCPClient]],
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
        response_model=None,
        summary="List available MCP tools for a server",
        description="Query the specified MCP server for available tools",
        responses={
            status.HTTP_200_OK: {"description": "List of available tools"},
            status.HTTP_404_NOT_FOUND: {
                "model": ErrorEnvelope,
                "description": "Server not found",
            },
            status.HTTP_502_BAD_GATEWAY: {
                "model": ErrorEnvelope,
                "description": "MCP server communication error",
            },
        },
    )
    async def list_server_tools(
        server: str = Path(..., description="Name of the MCP server"),
    ) -> dict[str, Any] | JSONResponse:
        """List available MCP tools for a specific server."""
        clients = get_clients()
        client_or_error = _get_client(server, clients)
        if isinstance(client_or_error, JSONResponse):
            return client_or_error
        client = client_or_error

        try:
            result = client.list_tools()
        except (MCPError, MCPSSEError) as e:
            logger.exception(f"MCP communication error with server '{server}'")
            return _create_error_response(
                error_type=ErrorType.JSONRPC_ERROR,
                message=str(e),
                http_status=status.HTTP_502_BAD_GATEWAY,
            )
        else:
            return result

    @api_router.get(
        "/mcp/{server}/tools/{tool_name}",
        response_model=None,
        summary="Get information about a specific MCP tool",
        description="Query the specified MCP server for details about a specific tool",
        responses={
            status.HTTP_200_OK: {"description": "Tool information"},
            status.HTTP_404_NOT_FOUND: {
                "model": ErrorEnvelope,
                "description": "Server or tool not found",
            },
            status.HTTP_502_BAD_GATEWAY: {
                "model": ErrorEnvelope,
                "description": "MCP server communication error",
            },
        },
    )
    async def get_server_tool(
        server: str = Path(..., description="Name of the MCP server"),
        tool_name: str = Path(..., description="Name of the tool"),
    ) -> dict[str, Any] | JSONResponse:
        """Get information about a specific tool on a server."""
        clients = get_clients()
        client_or_error = _get_client(server, clients)
        if isinstance(client_or_error, JSONResponse):
            return client_or_error
        client = client_or_error

        try:
            result = client.list_tools()
            tools = result.get("tools", [])
            for tool in tools:
                if tool.get("name") == tool_name:
                    return tool  # type: ignore[no-any-return]
            return _create_error_response(
                error_type=ErrorType.NOT_FOUND,
                message=f"Tool '{tool_name}' not found on server '{server}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        except (MCPError, MCPSSEError) as e:
            logger.exception(f"MCP communication error with server '{server}'")
            return _create_error_response(
                error_type=ErrorType.JSONRPC_ERROR,
                message=str(e),
                http_status=status.HTTP_502_BAD_GATEWAY,
            )

    @api_router.post(
        "/mcp/{server}/call",
        response_model=MCPCallResponse,
        summary="Call an MCP tool on a specific server",
        description="Execute an MCP tool on the specified server and return the result",
        responses={
            status.HTTP_200_OK: {
                "model": MCPCallResponse,
                "description": "Tool executed successfully",
            },
            status.HTTP_400_BAD_REQUEST: {
                "model": ErrorEnvelope,
                "description": "Invalid request (malformed JSON, missing tool, invalid arguments)",
            },
            status.HTTP_404_NOT_FOUND: {
                "model": ErrorEnvelope,
                "description": "Server not found",
            },
            status.HTTP_502_BAD_GATEWAY: {
                "model": ErrorEnvelope,
                "description": "JSON-RPC error from provider",
            },
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": ErrorEnvelope,
                "description": "Provider busy or crashed",
            },
            status.HTTP_504_GATEWAY_TIMEOUT: {
                "model": ErrorEnvelope,
                "description": "Request timed out",
            },
        },
    )
    async def call_server_tool(
        request: MCPCallRequest,
        server: str = Path(..., description="Name of the MCP server"),
    ) -> MCPCallResponse | JSONResponse:
        """Call an MCP tool on a specific server."""
        clients = get_clients()
        client_or_error = _get_client(server, clients)
        if isinstance(client_or_error, JSONResponse):
            return client_or_error
        client = client_or_error

        try:
            result = client.call_tool(
                name=request.tool,
                arguments=request.arguments,
                timeout=request.timeout_seconds,
            )
            return MCPCallResponse(result=result)
        except MCPBusyError as e:
            logger.warning(f"Provider busy for server '{server}': {e}")
            return _create_error_response(
                error_type=ErrorType.BUSY,
                message=str(e),
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                details={"retry_after_ms": e.retry_after_ms},
            )
        except MCPProviderCrashedError as e:
            logger.exception(f"Provider crashed for server '{server}'")
            return _create_error_response(
                error_type=ErrorType.PROVIDER_CRASHED,
                message=str(e),
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except MCPTimeoutError as e:
            logger.warning(f"Request timed out for server '{server}': {e}")
            return _create_error_response(
                error_type=ErrorType.TIMEOUT,
                message=str(e),
                http_status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except (MCPError, MCPSSEError) as e:
            logger.exception(f"MCP communication error with server '{server}'")
            return _create_error_response(
                error_type=ErrorType.JSONRPC_ERROR,
                message=str(e),
                http_status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception as e:
            logger.exception(f"Unexpected error calling server '{server}'")
            return _create_error_response(
                error_type=ErrorType.INTERNAL,
                message=f"Internal error: {e}",
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @api_router.post(
        "/mcp/call",
        response_model=MCPCallResponse,
        summary="Call an MCP tool (legacy)",
        description="Execute an MCP tool on the default server. "
        "Use /mcp/{server}/call for multi-server setups.",
        responses={
            status.HTTP_200_OK: {
                "model": MCPCallResponse,
                "description": "Tool executed successfully",
            },
            status.HTTP_400_BAD_REQUEST: {
                "model": ErrorEnvelope,
                "description": "Invalid request",
            },
            status.HTTP_502_BAD_GATEWAY: {
                "model": ErrorEnvelope,
                "description": "JSON-RPC error from provider",
            },
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": ErrorEnvelope,
                "description": "Provider busy or crashed",
            },
            status.HTTP_504_GATEWAY_TIMEOUT: {
                "model": ErrorEnvelope,
                "description": "Request timed out",
            },
        },
    )
    async def mcp_call(request: MCPCallRequest) -> MCPCallResponse | JSONResponse:
        """Call an MCP tool on the default server (legacy endpoint)."""
        clients = get_clients()
        client_or_error = _get_default_client(clients)
        if isinstance(client_or_error, JSONResponse):
            return client_or_error
        client = client_or_error

        try:
            result = client.call_tool(
                name=request.tool,
                arguments=request.arguments,
                timeout=request.timeout_seconds,
            )
            return MCPCallResponse(result=result)
        except MCPBusyError as e:
            logger.warning(f"Provider busy: {e}")
            return _create_error_response(
                error_type=ErrorType.BUSY,
                message=str(e),
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                details={"retry_after_ms": e.retry_after_ms},
            )
        except MCPProviderCrashedError as e:
            logger.exception("Provider crashed")
            return _create_error_response(
                error_type=ErrorType.PROVIDER_CRASHED,
                message=str(e),
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except MCPTimeoutError as e:
            logger.warning(f"Request timed out: {e}")
            return _create_error_response(
                error_type=ErrorType.TIMEOUT,
                message=str(e),
                http_status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except (MCPError, MCPSSEError) as e:
            logger.exception("MCP communication error")
            return _create_error_response(
                error_type=ErrorType.JSONRPC_ERROR,
                message=str(e),
                http_status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception as e:
            logger.exception("Unexpected error calling MCP")
            return _create_error_response(
                error_type=ErrorType.INTERNAL,
                message=f"Internal error: {e}",
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @api_router.get(
        "/mcp/tools",
        response_model=None,
        summary="List available MCP tools (legacy)",
        description="Query the default MCP server for available tools. "
        "Use /mcp/{server}/tools for multi-server setups.",
        responses={
            status.HTTP_200_OK: {"description": "List of available tools"},
            status.HTTP_500_INTERNAL_SERVER_ERROR: {
                "model": ErrorEnvelope,
                "description": "No MCP servers configured",
            },
            status.HTTP_502_BAD_GATEWAY: {
                "model": ErrorEnvelope,
                "description": "MCP server communication error",
            },
        },
    )
    async def list_tools() -> dict[str, Any] | JSONResponse:
        """List available MCP tools on the default server (legacy endpoint)."""
        clients = get_clients()
        client_or_error = _get_default_client(clients)
        if isinstance(client_or_error, JSONResponse):
            return client_or_error
        client = client_or_error

        try:
            result = client.list_tools()
        except (MCPError, MCPSSEError) as e:
            logger.exception("MCP communication error")
            return _create_error_response(
                error_type=ErrorType.JSONRPC_ERROR,
                message=str(e),
                http_status=status.HTTP_502_BAD_GATEWAY,
            )
        else:
            return result

    @api_router.get(
        "/health",
        response_model=HealthResponse,
        summary="Health check",
        description="Check if the MCP bridge is ready (at least one server is alive). "
        "Per NES-47: returns status='ok' and provider='running' when healthy, "
        "or status='degraded' and provider='down' when unhealthy.",
        responses={
            status.HTTP_200_OK: {
                "model": HealthResponse,
                "description": "Bridge is healthy (status='ok', provider='running')",
            },
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": HealthResponse,
                "description": "Bridge is unhealthy (status='degraded', provider='down')",
            },
        },
    )
    async def health_check() -> HealthResponse | JSONResponse:
        """Check if the MCP bridge is healthy.

        Returns:
            200: {"status": "ok", "provider": "running"} when at least one provider is alive
            503: {"status": "degraded", "provider": "down"} when no providers are alive
        """
        clients = get_clients()
        if any(client.is_alive() for client in clients.values()):
            return HealthResponse(status="ok", provider="running")

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=HealthResponse(status="degraded", provider="down").model_dump(),
        )

    return api_router


__all__ = ["create_router", "router"]
