"""FastAPI application factory for MCP Bridge."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

from fastapi import FastAPI

from app.api.routes import create_router
from app.core.config import (
    ConfigError,
    MCPConfig,
    SSEServerConfig,
    StdioServerConfig,
    load_config,
)
from app.services.manager import MCPClient, MCPError, MCPStdioManager
from app.services.sse_client import MCPSSEClient, MCPSSEError

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AppState:
    """Application state holder."""

    def __init__(self) -> None:
        """Initialize empty state."""
        self.config: MCPConfig | None = None
        self.clients: dict[str, MCPClient] = {}


def _create_client(
    name: str, server_config: StdioServerConfig | SSEServerConfig
) -> MCPClient:
    """Create an MCP client for the given server configuration."""
    if isinstance(server_config, StdioServerConfig):
        for key, value in server_config.env.items():
            os.environ[key] = value

        full_command = server_config.get_full_command()
        startup_timeout = 120.0 if "mcp-remote" in full_command else 10.0

        return MCPStdioManager(
            command=full_command,
            startup_timeout=startup_timeout,
        )

    if isinstance(server_config, SSEServerConfig):
        return MCPSSEClient(
            url=server_config.url,
            headers=server_config.headers,
        )

    raise ConfigError(f"Unknown server type for '{name}'")


def create_app() -> FastAPI:
    """Create and configure the MCP Bridge FastAPI application.

    Returns:
        Configured FastAPI application.
    """
    state = AppState()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Manage application lifespan - load config and initialize clients."""
        try:
            config_path = os.environ.get("MCP_CONFIG_PATH")
            if config_path:
                logger.info(f"Loading MCP configuration from {config_path}")
            else:
                logger.info("Searching for MCP configuration file...")

            try:
                state.config = load_config(config_path)
                logger.info(f"Loaded {len(state.config.servers)} server(s) from config")
            except ConfigError as e:
                logger.warning(f"Failed to load config: {e}. Starting with no servers.")
                state.config = MCPConfig()

            if not state.config.servers:
                legacy_command = os.environ.get("MCP_COMMAND")
                if legacy_command:
                    logger.info(f"Using legacy MCP_COMMAND: {legacy_command}")
                    state.config.servers["default"] = StdioServerConfig(
                        name="default",
                        command=legacy_command,
                    )

            for name, server_config in state.config.servers.items():
                try:
                    logger.info(f"Initializing MCP server '{name}'...")
                    client = _create_client(name, server_config)
                    state.clients[name] = client
                    logger.info(f"MCP server '{name}' initialized successfully")
                except (MCPError, MCPSSEError, ConfigError) as e:
                    logger.error(f"Failed to initialize server '{name}': {e}")

            logger.info(f"MCP Bridge started with {len(state.clients)} server(s)")
            yield

        finally:
            for name, client in state.clients.items():
                try:
                    logger.info(f"Shutting down MCP server '{name}'...")
                    client.close()
                except Exception as e:
                    logger.error(f"Error closing client '{name}': {e}")

            state.clients.clear()
            state.config = None
            logger.info("MCP Bridge shut down")

    app = FastAPI(
        title="MCP Bridge",
        description="REST-to-MCP bridge server that exposes MCP tools via HTTP. "
        "Supports multiple MCP servers configured via mcp-servers.json.",
        version="2.0.0",
        lifespan=lifespan,
    )

    def get_config() -> MCPConfig | None:
        return state.config

    def get_clients() -> dict[str, MCPClient]:
        return state.clients

    router = create_router(get_config, get_clients)
    app.include_router(router)

    return app


__all__ = ["create_app"]
