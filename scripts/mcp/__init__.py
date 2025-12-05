"""MCP (Model Context Protocol) tools and utilities.

This package contains:
- app/ - MCP bridge FastAPI server for REST-to-MCP translation
- client/ - MCP HTTP client for communicating with the bridge

Usage:
    # Start the bridge server
    uvicorn scripts.mcp.app.main:app --host 0.0.0.0 --port 8080

    # Or use the generic start script
    uv run app.start --app scripts.mcp.app.main:app --port 8080

    # Use the HTTP client
    from scripts.mcp.client import HttpMCPClient
    client = HttpMCPClient("http://localhost:8080")
    result = client.call_tool("execute", {"command": "echo hello"})
"""
