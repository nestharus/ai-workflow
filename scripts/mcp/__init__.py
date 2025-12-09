"""MCP (Model Context Protocol) tools and utilities.

This package contains:
- app/ - MCP bridge FastAPI server for REST-to-MCP translation
- client/ - MCP HTTP client for communicating with the bridge

Usage:
    # Start the bridge server (HTTP mode for host-based development):
    uvicorn scripts.mcp.app.main:app --host 127.0.0.1 --port 8080

    # Or use the dev-tools compose stack (Unix socket mode, preferred for Docker):
    #   uv run dev.ensure-env   # preferred, orchestrated startup
    # or explicitly:
    docker compose -p ai-workflow-devtools -f docker-compose.dev.yml up -d mcp-bridge
    # Socket will be at /tmp/mcp-sockets/mcp-bridge.sock on the host
    # (mapped to /tmp/mcp-bridge.sock inside the container).
    # The main application stack uses: docker compose up (against docker-compose.yml)

    # Use the HTTP client - HTTP mode (for non-Docker host usage):
    from scripts.mcp.client import HttpMCPClient
    client = HttpMCPClient("http://localhost:8080")

    # Use the HTTP client - Unix socket mode (preferred for Docker):
    from scripts.mcp.client import HttpMCPClient
    client = HttpMCPClient(socket_path="/path/to/mcp-bridge.sock")
    # Or via environment: export MCP_BRIDGE_SOCKET=/path/to/mcp-bridge.sock

    # Multi-server pattern (works in both modes):
    servers = client.list_servers()  # Discover available servers
    result = client.call_server_tool("background-job", "execute", {"command": "ls"})
"""
