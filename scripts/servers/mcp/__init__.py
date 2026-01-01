r"""MCP (Model Context Protocol) tools and utilities.

This package contains:
- server_impl.py - Native Unix socket server for socket-to-MCP translation
- protocol.py - Request/response dataclasses for JSONL protocol
- manager.py - MCP STDIO subprocess management
- sse_client.py - SSE-based MCP client for HTTP servers
- config.py - Configuration loading from YAML/JSON
- client/ - Socket client for communicating with the bridge

The bridge uses a newline-delimited JSON (JSONL) protocol over Unix sockets,
NOT HTTP. This provides <500ms cold start time suitable for CLI hooks.

Usage:
    # Start the bridge server (Docker, preferred):
    #   uv run dev.ensure-env   # preferred, orchestrated startup
    # or explicitly:
    docker compose -p ai-workflow-devtools -f docker-compose.dev.yml up -d mcp-bridge
    # Socket will be at /tmp/mcp-sockets/mcp-bridge.sock on the host
    # (mapped to /tmp/mcp-bridge.sock inside the container).

    # Start the bridge server (non-Docker, for development):
    # Note: Use a simple path for non-Docker; Docker setup uses /tmp/mcp-sockets/ on host.
    MCP_BRIDGE_SOCKET=/tmp/mcp-bridge.sock python -m scripts.servers.mcp.server

    # Use the socket client:
    from scripts.servers.mcp.client import (  # socket client; name preserved for compatibility
        HttpMCPClient,
    )
    # Use the same socket path that the server is configured to use.
    # For Docker: server uses /tmp/mcp-bridge.sock inside container;
    # host accesses via /tmp/mcp-sockets/mcp-bridge.sock.
    # For non-Docker: both client and server use the same path (e.g., /tmp/mcp-bridge.sock).
    client = HttpMCPClient(socket_path="/tmp/mcp-sockets/mcp-bridge.sock")
    # Or via environment: export MCP_BRIDGE_SOCKET=/tmp/mcp-sockets/mcp-bridge.sock

    # Multi-server pattern:
    servers = client.list_servers()  # Discover available servers
    result = client.call_server_tool("background-job", "execute_command", {"command": "ls"})

Protocol:
    Request:  {"method": "...", "id": "...", ...params}\\n
    Response: {"id": "...", "status": "success", "result": {...}}\\n
    Error:    {"id": "...", "status": "error", "error": {"type": "...", "message": "..."}}\\n

Note: HTTP access is NOT provided by this bridge. If HTTP is needed, implement
a separate HTTP-to-socket proxy outside the bridge container.
"""
