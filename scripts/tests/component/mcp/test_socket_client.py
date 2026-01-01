import os
from unittest.mock import patch

import pytest

from scripts.servers.mcp.client.http_client import (
    MCPClientError,
    MCPSocketClient,
)


class TestSocketClientParameterValidation:
    def test_init_socket_path_must_be_string(self) -> None:
        """Test socket_path must be string, raises MCPClientError."""
        with pytest.raises(MCPClientError, match="socket_path must be a string path"):
            MCPSocketClient(socket_path=123)  # type: ignore[arg-type]

    def test_init_base_url_must_be_string(self) -> None:
        """Test base_url must be string, raises MCPClientError."""
        with pytest.raises(MCPClientError, match="base_url must be a string URL"):
            MCPSocketClient(base_url=123)  # type: ignore[arg-type]

    def test_init_empty_base_url_raises_error(self) -> None:
        """Test empty base_url raises MCPClientError."""
        with pytest.raises(MCPClientError, match="Invalid base_url: empty or missing host"):
            MCPSocketClient(base_url="")

    def test_base_url_accepted_for_backward_compatibility(self) -> None:
        """Test base_url is accepted but socket mode is used by default.

        Note: base_url validation is minimal because socket mode is the default
        and base_url is retained only for backward compatibility.
        """
        # base_url is accepted but socket mode is still used
        client = MCPSocketClient(base_url="http://example.com:8080")
        assert client.socket_path == "/tmp/mcp-bridge.sock"

    def test_server_param_empty_string_raises_error(self) -> None:
        """Test empty server parameter raises MCPClientError."""
        client = MCPSocketClient(socket_path="/tmp/test.sock")
        with pytest.raises(MCPClientError, match="server parameter must be a non-empty string"):
            client.list_server_tools("")

    def test_server_param_whitespace_only_raises_error(self) -> None:
        """Test whitespace-only server parameter raises MCPClientError after stripping."""
        client = MCPSocketClient(socket_path="/tmp/test.sock")
        with pytest.raises(MCPClientError, match="server parameter must be a non-empty string"):
            client.list_server_tools("   ")

    def test_server_param_none_raises_error(self) -> None:
        """Test None server parameter raises MCPClientError."""
        client = MCPSocketClient(socket_path="/tmp/test.sock")
        with pytest.raises(MCPClientError, match="server parameter must be a non-empty string"):
            client.list_server_tools(None)  # type: ignore[arg-type]

    def test_tool_name_param_empty_raises_error(self) -> None:
        """Test empty tool_name parameter raises MCPClientError."""
        client = MCPSocketClient(socket_path="/tmp/test.sock")
        with pytest.raises(MCPClientError, match="tool_name parameter must be a non-empty string"):
            client.get_server_tool("test-server", "")

    def test_tool_name_param_whitespace_only_raises_error(self) -> None:
        """Test whitespace-only tool_name parameter raises MCPClientError after stripping."""
        client = MCPSocketClient(socket_path="/tmp/test.sock")
        with pytest.raises(MCPClientError, match="tool_name parameter must be a non-empty string"):
            client.get_server_tool("test-server", "   ")

    def test_name_param_empty_raises_error(self) -> None:
        """Test empty name parameter in call_server_tool raises MCPClientError."""
        client = MCPSocketClient(socket_path="/tmp/test.sock")
        with pytest.raises(MCPClientError, match="name parameter must be a non-empty string"):
            client.call_server_tool("test-server", "", {})

    def test_name_param_whitespace_only_raises_error(self) -> None:
        """Test whitespace-only name raises MCPClientError after stripping."""
        client = MCPSocketClient(socket_path="/tmp/test.sock")
        with pytest.raises(MCPClientError, match="name parameter must be a non-empty string"):
            client.call_server_tool("test-server", "   ", {})


class TestSocketClientTransportPrecedence:
    def test_socket_path_arg_takes_precedence_over_env(self) -> None:
        """Test socket_path argument takes precedence over MCP_BRIDGE_SOCKET env."""
        with patch.dict(os.environ, {"MCP_BRIDGE_SOCKET": "/tmp/env.sock"}):
            client = MCPSocketClient(socket_path="/tmp/arg.sock")
            assert client.socket_path == "/tmp/arg.sock"

    def test_socket_env_takes_precedence_over_base_url_arg(self) -> None:
        """Test MCP_BRIDGE_SOCKET env takes precedence over base_url argument."""
        with patch.dict(os.environ, {"MCP_BRIDGE_SOCKET": "/tmp/env.sock"}):
            client = MCPSocketClient(base_url="http://example.com:9000")
            assert client.socket_path == "/tmp/env.sock"

    def test_socket_env_takes_precedence_over_url_env(self) -> None:
        """Test MCP_BRIDGE_SOCKET takes precedence over MCP_BRIDGE_URL."""
        with patch.dict(
            os.environ,
            {
                "MCP_BRIDGE_SOCKET": "/tmp/env.sock",
                "MCP_BRIDGE_URL": "http://example.com:9000",
            },
        ):
            client = MCPSocketClient()
            assert client.socket_path == "/tmp/env.sock"

    def test_default_socket_path_when_no_config(self) -> None:
        """Test default socket path is used when no config provided."""
        # Clear environment variables for complete isolation
        env_without_mcp_vars = {
            k: v for k, v in os.environ.items() if k not in ("MCP_BRIDGE_SOCKET", "MCP_BRIDGE_URL")
        }
        with patch.dict(os.environ, env_without_mcp_vars, clear=True):
            client = MCPSocketClient()
            assert client.socket_path == "/tmp/mcp-bridge.sock"
