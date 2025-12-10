"""ASGI entry point for the MCP Bridge service. Uses factory pattern for app creation."""

from .core.factory import create_app

app = create_app()
