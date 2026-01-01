"""MCP Bridge client for socket-based communication.

Provides the MCPSocketClient (aliased as HttpMCPClient for backward compatibility)
for communicating with the MCP Bridge server via Unix sockets using JSONL protocol.
"""

from scripts.servers.mcp.client.http_client import (
    DEFAULT_SOCKET_PATH,
    HttpMCPClient,
    MCPClientError,
    MCPSocketClient,
)

__all__ = [
    "DEFAULT_SOCKET_PATH",
    "HttpMCPClient",
    "MCPClientError",
    "MCPSocketClient",
]
