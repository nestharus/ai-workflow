import os
from unittest.mock import MagicMock, patch

import pytest

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


class TestAppState:
    def test_initial_state(self) -> None:
        """AppState initializes with empty config and clients."""
        state = AppState()

        assert state.config is None
        assert state.clients == {}


class TestCreateClient:
    def test_creates_stdio_client(self) -> None:
        """Create MCPStdioManager for stdio server config."""
        config = StdioServerConfig(
            name="test-server",
            command="echo",
            args=["hello"],
        )

        with patch.object(MCPStdioManager, "__init__", return_value=None):
            client = _create_client("test-server", config)
            assert isinstance(client, MCPStdioManager)

    def test_creates_sse_client(self) -> None:
        """Create MCPSSEClient for SSE server config."""
        config = SSEServerConfig(
            name="test-server",
            url="https://example.com/sse",
            headers={"Authorization": "Bearer token"},
        )

        client = _create_client("test-server", config)
        assert isinstance(client, MCPSSEClient)
        client.close()

    def test_sets_env_vars_for_stdio(self) -> None:
        """Set environment variables from stdio config."""
        config = StdioServerConfig(
            name="test-server",
            command="echo",
            env={"TEST_VAR": "test_value"},
        )

        with patch.object(MCPStdioManager, "__init__", return_value=None):
            _create_client("test-server", config)
            assert os.environ.get("TEST_VAR") == "test_value"

        # Clean up
        os.environ.pop("TEST_VAR", None)

    def test_increases_timeout_for_mcp_remote(self) -> None:
        """Use longer startup timeout for mcp-remote commands."""
        config = StdioServerConfig(
            name="test-server",
            command="npx",
            args=["-y", "mcp-remote", "https://example.com"],
        )

        with patch.object(MCPStdioManager, "__init__", return_value=None) as mock_init:
            _create_client("test-server", config)
            # Check that startup_timeout was set to 120.0 for mcp-remote
            mock_init.assert_called_once()
            call_kwargs = mock_init.call_args[1]
            assert call_kwargs["startup_timeout"] == 120.0

    def test_raises_config_error_for_unknown_type(self) -> None:
        """Raise ConfigError for unknown server type."""
        # Create a mock config that is neither StdioServerConfig nor SSEServerConfig
        mock_config = MagicMock()
        mock_config.__class__ = type("UnknownConfig", (), {})

        with pytest.raises(ConfigError, match="Unknown server type"):
            _create_client("test-server", mock_config)  # type: ignore[arg-type]
