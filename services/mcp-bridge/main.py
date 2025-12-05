"""FastAPI application for the MCP Bridge service.

This module provides a REST-to-MCP bridge that exposes MCP tools via HTTP endpoints,
allowing any process to query MCP tools without needing a direct stdio connection.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from mcp_manager import MCPError, MCPStdioManager

logger = logging.getLogger(__name__)


class MCPCallRequest(BaseModel):
    """Request body for the /mcp/call endpoint."""

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


# Global manager instance
_manager: MCPStdioManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifespan - initialize and cleanup MCP manager."""
    global _manager
    try:
        logger.info("Starting MCP stdio manager...")
        _manager = MCPStdioManager()
        logger.info("MCP stdio manager started successfully")
        yield
    finally:
        if _manager is not None:
            logger.info("Shutting down MCP stdio manager...")
            _manager.close()
            _manager = None
            logger.info("MCP stdio manager shut down")


app = FastAPI(
    title="MCP Bridge",
    description="REST-to-MCP bridge server that exposes MCP tools via HTTP",
    version="1.0.0",
    lifespan=lifespan,
)


@app.post(
    "/mcp/call",
    summary="Call an MCP tool",
    description="Execute an MCP tool and return the result",
    responses={
        status.HTTP_200_OK: {
            "description": "Tool executed successfully",
            "content": {"application/json": {"example": {"job_id": "abc123"}}},
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponse,
            "description": "Internal server error",
        },
        status.HTTP_502_BAD_GATEWAY: {
            "model": ErrorResponse,
            "description": "MCP server communication error",
        },
    },
)
async def mcp_call(request: MCPCallRequest) -> dict[str, Any]:
    """Call an MCP tool and return the raw result.

    Args:
        request: The MCP call request containing tool name, arguments, and timeout.

    Returns:
        Raw MCP result dict (no wrapper).

    Raises:
        HTTPException: 502 for MCP communication errors, 500 for internal errors.
    """
    if _manager is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "MCP manager not initialized", "details": None},
        )

    try:
        result = _manager.call_tool(
            name=request.tool,
            arguments=request.arguments,
            timeout=request.timeout,
        )
        return result
    except MCPError as e:
        logger.exception("MCP communication error")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": str(e), "details": None},
        ) from e
    except Exception as e:
        logger.exception("Unexpected error during MCP call")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Internal server error", "details": str(e)},
        ) from e


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Check if the MCP bridge is ready (MCP subprocess is alive)",
    responses={
        status.HTTP_200_OK: {
            "model": HealthResponse,
            "description": "Bridge is healthy",
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": HealthResponse,
            "description": "Bridge is unhealthy (MCP subprocess is dead)",
        },
    },
)
async def health_check() -> HealthResponse:
    """Check if the MCP bridge is healthy.

    Returns:
        HealthResponse with status 'healthy' (200) or 'unhealthy' (503).
    """
    if _manager is not None and _manager.is_alive():
        return HealthResponse(status="healthy")

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=HealthResponse(status="unhealthy").model_dump(),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
