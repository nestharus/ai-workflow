"""Entry point for running the MCP Bridge server as a module.

Usage:
    python -m scripts.servers.mcp.server
"""

from scripts.servers.mcp.server_impl import main

if __name__ == "__main__":
    main()
