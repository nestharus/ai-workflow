import os
from unittest.mock import MagicMock, patch

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from scripts.servers.mcp.app.core.config import (
    ConfigError,
    MCPConfig,
    SSEServerConfig,
    StdioServerConfig,
)
from scripts.servers.mcp.app.core.factory import (
    AppState,
    _create_client,
    create_app,
)
from scripts.servers.mcp.app.services.manager import MCPError, MCPStdioManager
from scripts.servers.mcp.app.services.sse_client import MCPSSEClient, MCPSSEError


def _mock_create_router(*args, **kwargs):
    """Create a mock router that can be included in FastAPI."""
    return APIRouter()


class TestCreateApp:
    def test_creates_fastapi_app(self) -> None:
        """create_app returns a FastAPI application."""
        with patch(
            "scripts.servers.mcp.app.core.factory.create_router", side_effect=_mock_create_router
        ):
            app = create_app()
            assert isinstance(app, FastAPI)
            assert app.title == "MCP Bridge"


class TestLifespan:
    def test_lifespan_loads_config_from_env_path(self) -> None:
        """Lifespan loads config from MCP_CONFIG_PATH environment variable."""
        mock_config = MCPConfig(servers={})

        env_backup = os.environ.get("MCP_CONFIG_PATH")
        try:
            os.environ["MCP_CONFIG_PATH"] = "/path/to/config.yml"
            with (
                patch(
                    "scripts.servers.mcp.app.core.factory.load_config", return_value=mock_config
                ) as mock_load,
                patch(
                    "scripts.servers.mcp.app.core.factory.create_router",
                    side_effect=_mock_create_router,
                ),
            ):
                app = create_app()

                # Create test client which triggers lifespan
                with TestClient(app):
                    mock_load.assert_called_once_with("/path/to/config.yml")
        finally:
            if env_backup is None:
                os.environ.pop("MCP_CONFIG_PATH", None)
            else:
                os.environ["MCP_CONFIG_PATH"] = env_backup

    def test_lifespan_loads_config_without_env_path(self) -> None:
        """Lifespan searches for config when MCP_CONFIG_PATH not set."""
        mock_config = MCPConfig(servers={})

        env_backup = os.environ.get("MCP_CONFIG_PATH")
        env_backup2 = os.environ.get("MCP_COMMAND")
        try:
            os.environ.pop("MCP_CONFIG_PATH", None)
            os.environ.pop("MCP_COMMAND", None)
            with (
                patch(
                    "scripts.servers.mcp.app.core.factory.load_config", return_value=mock_config
                ) as mock_load,
                patch(
                    "scripts.servers.mcp.app.core.factory.create_router",
                    side_effect=_mock_create_router,
                ),
            ):
                app = create_app()

                with TestClient(app):
                    mock_load.assert_called_once_with(None)
        finally:
            if env_backup is not None:
                os.environ["MCP_CONFIG_PATH"] = env_backup
            if env_backup2 is not None:
                os.environ["MCP_COMMAND"] = env_backup2

    def test_lifespan_handles_config_error_gracefully(self) -> None:
        """Lifespan starts with empty config when load_config raises ConfigError."""
        env_backup = os.environ.get("MCP_COMMAND")
        try:
            os.environ.pop("MCP_COMMAND", None)
            with (
                patch(
                    "scripts.servers.mcp.app.core.factory.load_config",
                    side_effect=ConfigError("Config not found"),
                ),
                patch(
                    "scripts.servers.mcp.app.core.factory.create_router",
                    side_effect=_mock_create_router,
                ),
            ):
                app = create_app()

                # Should not raise - starts with empty config
                with TestClient(app):
                    pass
        finally:
            if env_backup is not None:
                os.environ["MCP_COMMAND"] = env_backup

    def test_lifespan_uses_legacy_mcp_command_when_no_servers(self) -> None:
        """Lifespan falls back to MCP_COMMAND env var when no servers configured."""
        empty_config = MCPConfig(servers={})

        env_backup = os.environ.get("MCP_COMMAND")
        try:
            os.environ["MCP_COMMAND"] = "uvx mcp-test"
            with (
                patch(
                    "scripts.servers.mcp.app.core.factory.load_config", return_value=empty_config
                ),
                patch(
                    "scripts.servers.mcp.app.core.factory.create_router",
                    side_effect=_mock_create_router,
                ),
                patch.object(MCPStdioManager, "__init__", return_value=None),
                patch.object(MCPStdioManager, "close"),
            ):
                app = create_app()

                with TestClient(app):
                    pass
        finally:
            if env_backup is None:
                os.environ.pop("MCP_COMMAND", None)
            else:
                os.environ["MCP_COMMAND"] = env_backup

    def test_lifespan_initializes_stdio_clients(self) -> None:
        """Lifespan initializes stdio clients from config."""
        config = MCPConfig(
            servers={
                "test-server": StdioServerConfig(
                    name="test-server",
                    command="echo",
                )
            }
        )

        with (
            patch("scripts.servers.mcp.app.core.factory.load_config", return_value=config),
            patch(
                "scripts.servers.mcp.app.core.factory.create_router",
                side_effect=_mock_create_router,
            ),
            patch.object(MCPStdioManager, "__init__", return_value=None),
            patch.object(MCPStdioManager, "close"),
        ):
            app = create_app()

            with TestClient(app):
                pass

    def test_lifespan_initializes_sse_clients(self) -> None:
        """Lifespan initializes SSE clients from config."""
        config = MCPConfig(
            servers={
                "linear": SSEServerConfig(
                    name="linear",
                    url="https://mcp.linear.app/sse",
                )
            }
        )

        with (
            patch("scripts.servers.mcp.app.core.factory.load_config", return_value=config),
            patch(
                "scripts.servers.mcp.app.core.factory.create_router",
                side_effect=_mock_create_router,
            ),
        ):
            app = create_app()

            with TestClient(app):
                pass

    def test_lifespan_handles_client_initialization_error(self) -> None:
        """Lifespan continues when client initialization fails."""
        config = MCPConfig(
            servers={
                "test-server": StdioServerConfig(
                    name="test-server",
                    command="nonexistent-command",
                )
            }
        )

        with (
            patch("scripts.servers.mcp.app.core.factory.load_config", return_value=config),
            patch(
                "scripts.servers.mcp.app.core.factory.create_router",
                side_effect=_mock_create_router,
            ),
            patch(
                "scripts.servers.mcp.app.core.factory._create_client",
                side_effect=MCPError("Failed to start"),
            ),
        ):
            app = create_app()

            # Should not raise - server initialization failure is logged but not fatal
            with TestClient(app):
                pass

    def test_lifespan_handles_sse_client_initialization_error(self) -> None:
        """Lifespan continues when SSE client initialization fails."""
        config = MCPConfig(
            servers={
                "linear": SSEServerConfig(
                    name="linear",
                    url="https://mcp.linear.app/sse",
                )
            }
        )

        with (
            patch("scripts.servers.mcp.app.core.factory.load_config", return_value=config),
            patch(
                "scripts.servers.mcp.app.core.factory.create_router",
                side_effect=_mock_create_router,
            ),
            patch(
                "scripts.servers.mcp.app.core.factory._create_client",
                side_effect=MCPSSEError("Connection failed"),
            ),
        ):
            app = create_app()

            # Should not raise
            with TestClient(app):
                pass

    def test_lifespan_closes_clients_on_shutdown(self) -> None:
        """Lifespan closes all clients on shutdown."""
        mock_client = MagicMock()
        config = MCPConfig(
            servers={
                "test-server": StdioServerConfig(
                    name="test-server",
                    command="echo",
                )
            }
        )

        with (
            patch("scripts.servers.mcp.app.core.factory.load_config", return_value=config),
            patch(
                "scripts.servers.mcp.app.core.factory.create_router",
                side_effect=_mock_create_router,
            ),
            patch("scripts.servers.mcp.app.core.factory._create_client", return_value=mock_client),
        ):
            app = create_app()

            with TestClient(app):
                pass

            mock_client.close.assert_called_once()

    def test_lifespan_handles_close_error(self) -> None:
        """Lifespan handles errors when closing clients."""
        mock_client = MagicMock()
        mock_client.close.side_effect = Exception("Close failed")
        config = MCPConfig(
            servers={
                "test-server": StdioServerConfig(
                    name="test-server",
                    command="echo",
                )
            }
        )

        with (
            patch("scripts.servers.mcp.app.core.factory.load_config", return_value=config),
            patch(
                "scripts.servers.mcp.app.core.factory.create_router",
                side_effect=_mock_create_router,
            ),
            patch("scripts.servers.mcp.app.core.factory._create_client", return_value=mock_client),
        ):
            app = create_app()

            # Should not raise - close errors are logged but not fatal
            with TestClient(app):
                pass

    def test_lifespan_handles_config_error_initialization(self) -> None:
        """Lifespan handles ConfigError during client creation."""
        config = MCPConfig(
            servers={
                "test-server": StdioServerConfig(
                    name="test-server",
                    command="echo",
                )
            }
        )

        with (
            patch("scripts.servers.mcp.app.core.factory.load_config", return_value=config),
            patch(
                "scripts.servers.mcp.app.core.factory.create_router",
                side_effect=_mock_create_router,
            ),
            patch(
                "scripts.servers.mcp.app.core.factory._create_client",
                side_effect=ConfigError("Invalid config"),
            ),
        ):
            app = create_app()

            # Should not raise
            with TestClient(app):
                pass


class TestGetConfigAndGetClients:
    def test_get_config_returns_loaded_config(self) -> None:
        """get_config returns the loaded MCPConfig."""
        expected_config = MCPConfig(
            servers={"test": StdioServerConfig(name="test", command="echo")}
        )

        captured_get_config = None

        def capturing_mock_create_router(get_config, get_clients):
            nonlocal captured_get_config
            captured_get_config = get_config
            return APIRouter()

        with (
            patch("scripts.servers.mcp.app.core.factory.load_config", return_value=expected_config),
            patch(
                "scripts.servers.mcp.app.core.factory.create_router",
                side_effect=capturing_mock_create_router,
            ),
            patch.object(MCPStdioManager, "__init__", return_value=None),
            patch.object(MCPStdioManager, "close"),
        ):
            app = create_app()

            # Before lifespan, config should be None
            assert captured_get_config() is None

            with TestClient(app):
                # During lifespan, config should be loaded
                config = captured_get_config()
                assert config is not None
                assert "test" in config.servers

    def test_get_clients_returns_initialized_clients(self) -> None:
        """get_clients returns initialized MCP clients."""
        mock_client = MagicMock()
        config = MCPConfig(
            servers={
                "test-server": StdioServerConfig(
                    name="test-server",
                    command="echo",
                )
            }
        )

        captured_get_clients = None

        def capturing_mock_create_router(get_config, get_clients):
            nonlocal captured_get_clients
            captured_get_clients = get_clients
            return APIRouter()

        with (
            patch("scripts.servers.mcp.app.core.factory.load_config", return_value=config),
            patch(
                "scripts.servers.mcp.app.core.factory.create_router",
                side_effect=capturing_mock_create_router,
            ),
            patch("scripts.servers.mcp.app.core.factory._create_client", return_value=mock_client),
        ):
            app = create_app()

            # Before lifespan, clients should be empty
            assert captured_get_clients() == {}

            with TestClient(app):
                # During lifespan, clients should be initialized
                clients = captured_get_clients()
                assert "test-server" in clients
                assert clients["test-server"] is mock_client
