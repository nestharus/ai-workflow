"""MCP Bridge socket server package.

This package provides a native asyncio socket server for the MCP Bridge,
replacing the FastAPI/uvicorn-based HTTP server with a lightweight JSONL-based
protocol over Unix sockets.
"""

from scripts.servers.mcp.server_impl import (
    DEFAULT_SOCKET_PATH,
    MCPSocketServer,
    main,
    run_server,
)

__all__ = [
    "DEFAULT_SOCKET_PATH",
    "MCPSocketServer",
    "main",
    "run_server",
]
