import json
import os
import tempfile
import time
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from scripts.servers.mcp.app.contracts.schemas import (
    ErrorEnvelope,
    ErrorType,
    HealthResponse,
    MCPCallRequest,
    MCPCallResponse,
)
from scripts.servers.mcp.app.core.config import (
    ConfigError,
    MCPConfig,
    SSEServerConfig,
    StdioServerConfig,
    load_config,
)
from scripts.servers.mcp.client.http_client import (
    HttpMCPClient,
    MCPClientError,
)


class TestConfig:
    def test_load_yaml_config(self) -> None:
        """Test loading .mcp.yml config file."""
        config_content = """
mcpServers:
  background-job:
    type: stdio
    command: uvx
    args:
      - mcp-background-job
  linear:
    type: sse
    url: https://mcp.linear.app/sse
    headers:
      Authorization: Bearer test
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write(config_content)
            f.flush()
            try:
                config = load_config(f.name)
                assert len(config.servers) == 2
                assert "background-job" in config.servers
                assert "linear" in config.servers

                # Check stdio server
                bg = config.servers["background-job"]
                assert isinstance(bg, StdioServerConfig)
                assert bg.command == "uvx"
                assert bg.args == ["mcp-background-job"]

                # Check SSE server
                lin = config.servers["linear"]
                assert isinstance(lin, SSEServerConfig)
                assert lin.url == "https://mcp.linear.app/sse"
            finally:
                os.unlink(f.name)

    def test_load_json_config(self) -> None:
        """Test loading .mcp.json config file."""
        config_content = {
            "mcpServers": {
                "test-server": {
                    "type": "stdio",
                    "command": "node",
                    "args": ["server.js"],
                }
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_content, f)
            f.flush()
            try:
                config = load_config(f.name)
                assert len(config.servers) == 1
                assert "test-server" in config.servers
            finally:
                os.unlink(f.name)

    def test_env_var_substitution(self) -> None:
        """Test environment variable substitution in config."""
        config_content = """
mcpServers:
  test:
    type: stdio
    command: echo
    args:
      - ${TEST_VAR}
    env:
      API_KEY: ${API_KEY:-default_key}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write(config_content)
            f.flush()
            try:
                os.environ["TEST_VAR"] = "hello"
                config = load_config(f.name)
                server = config.servers["test"]
                assert isinstance(server, StdioServerConfig)
                assert server.args == ["hello"]
                assert server.env["API_KEY"] == "default_key"
            finally:
                os.environ.pop("TEST_VAR", None)
                os.unlink(f.name)

    def test_disabled_server_skipped(self) -> None:
        """Test disabled servers are not loaded."""
        config_content = """
mcpServers:
  enabled-server:
    type: stdio
    command: echo
  disabled-server:
    type: stdio
    command: echo
    disabled: true
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write(config_content)
            f.flush()
            try:
                config = load_config(f.name)
                assert len(config.servers) == 1
                assert "enabled-server" in config.servers
                assert "disabled-server" not in config.servers
            finally:
                os.unlink(f.name)

    def test_missing_command_raises_error(self) -> None:
        """Test missing required 'command' field raises ConfigError."""
        config_content = """
mcpServers:
  bad-server:
    type: stdio
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write(config_content)
            f.flush()
            try:
                with pytest.raises(ConfigError, match="missing required 'command'"):
                    load_config(f.name)
            finally:
                os.unlink(f.name)


class TestHttpMCPClient:
    def test_list_server_tools_empty_server(self) -> None:
        """Test list_server_tools raises MCPClientError for empty server string."""
        client = HttpMCPClient("http://localhost:8080")
        with pytest.raises(MCPClientError, match="server parameter must be a non-empty string"):
            client.list_server_tools("")

    def test_get_server_tool_empty_server(self) -> None:
        """Test get_server_tool raises MCPClientError for empty server string."""
        client = HttpMCPClient("http://localhost:8080")
        with pytest.raises(MCPClientError, match="server parameter must be a non-empty string"):
            client.get_server_tool("", "test-tool")

    def test_get_server_tool_empty_tool_name(self) -> None:
        """Test get_server_tool raises MCPClientError for empty tool_name string."""
        client = HttpMCPClient("http://localhost:8080")
        with pytest.raises(MCPClientError, match="tool_name parameter must be a non-empty string"):
            client.get_server_tool("test-server", "")

    def test_call_server_tool_empty_server(self) -> None:
        """Test call_server_tool raises MCPClientError for empty server string."""
        client = HttpMCPClient("http://localhost:8080")
        with pytest.raises(MCPClientError, match="server parameter must be a non-empty string"):
            client.call_server_tool("", "execute", {})

    def test_call_server_tool_empty_name(self) -> None:
        """Test call_server_tool raises MCPClientError for empty name string."""
        client = HttpMCPClient("http://localhost:8080")
        with pytest.raises(MCPClientError, match="name parameter must be a non-empty string"):
            client.call_server_tool("test-server", "", {})

    def test_init_with_socket_path_argument(self) -> None:
        """Test HttpMCPClient initialization with socket_path argument."""
        client = HttpMCPClient(socket_path="/tmp/test.sock")
        assert client.socket_path == "/tmp/test.sock"
        assert client.base_url == "http://localhost"

    def test_init_with_socket_env_var(self) -> None:
        """Test HttpMCPClient initialization with MCP_BRIDGE_SOCKET env var."""
        with patch.dict(os.environ, {"MCP_BRIDGE_SOCKET": "/tmp/env.sock"}):
            client = HttpMCPClient()
            assert client.socket_path == "/tmp/env.sock"
            assert client.base_url == "http://localhost"

    def test_socket_path_takes_precedence_over_base_url(self) -> None:
        """Test socket_path takes precedence over base_url argument."""
        client = HttpMCPClient(base_url="http://example.com:9000", socket_path="/tmp/test.sock")
        assert client.socket_path == "/tmp/test.sock"
        assert client.base_url == "http://localhost"

    def test_socket_env_takes_precedence_over_url_env(self) -> None:
        """Test MCP_BRIDGE_SOCKET takes precedence over MCP_BRIDGE_URL."""
        with patch.dict(
            os.environ,
            {"MCP_BRIDGE_SOCKET": "/tmp/env.sock", "MCP_BRIDGE_URL": "http://example.com:9000"},
        ):
            client = HttpMCPClient()
            assert client.socket_path == "/tmp/env.sock"
            assert client.base_url == "http://localhost"

    def test_http_mode_without_socket_env(self) -> None:
        """Test HTTP mode works when no MCP_BRIDGE_SOCKET is set."""
        # Ensure no socket env var is set by using an empty override
        env_without_socket = {k: v for k, v in os.environ.items() if k != "MCP_BRIDGE_SOCKET"}
        with patch.dict(os.environ, env_without_socket, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")
            assert client.socket_path is None
            assert client.base_url == "http://localhost:8080"

    def test_http_mode_uses_mcp_bridge_url_env(self) -> None:
        """Test HTTP mode uses MCP_BRIDGE_URL when no socket is configured."""
        env_with_url = {"MCP_BRIDGE_URL": "http://custom:9000"}
        # Clear MCP_BRIDGE_SOCKET if it exists
        with patch.dict(os.environ, env_with_url, clear=True):
            client = HttpMCPClient()
            assert client.socket_path is None
            assert client.base_url == "http://custom:9000"

    def test_server_validation_rejects_empty_string(self) -> None:
        """Test that empty server name is rejected."""
        from scripts.servers.mcp.client.http_client import MCPClientError as ClientError
        from scripts.servers.mcp.client.http_client import _validate_and_encode_server

        with pytest.raises(ClientError, match="non-empty string"):
            _validate_and_encode_server("")

    def test_server_validation_rejects_whitespace_only(self) -> None:
        """Test that whitespace-only server name is rejected after stripping."""
        from scripts.servers.mcp.client.http_client import MCPClientError as ClientError
        from scripts.servers.mcp.client.http_client import _validate_and_encode_server

        with pytest.raises(ClientError, match="non-empty string"):
            _validate_and_encode_server("   ")

    def test_server_validation_rejects_none(self) -> None:
        """Test that None server name is rejected."""
        from scripts.servers.mcp.client.http_client import MCPClientError as ClientError
        from scripts.servers.mcp.client.http_client import _validate_and_encode_server

        with pytest.raises(ClientError, match="non-empty string"):
            _validate_and_encode_server(None)  # type: ignore[arg-type]

    def test_server_validation_strips_whitespace(self) -> None:
        """Test that leading/trailing whitespace is stripped from server name."""
        from scripts.servers.mcp.client.http_client import _validate_and_encode_server

        result = _validate_and_encode_server("  background-job  ")
        assert result == "background-job"

    def test_server_validation_encodes_special_chars(self) -> None:
        """Test that URL-unsafe characters are encoded."""
        from scripts.servers.mcp.client.http_client import _validate_and_encode_server

        # Slash should be encoded
        result = _validate_and_encode_server("server/name")
        assert result == "server%2Fname"

        # Hash should be encoded
        result = _validate_and_encode_server("server#comment")
        assert result == "server%23comment"

        # Percent should be encoded
        result = _validate_and_encode_server("server%20name")
        assert result == "server%2520name"

        # Question mark should be encoded
        result = _validate_and_encode_server("server?query")
        assert result == "server%3Fquery"

        # Space should be encoded
        result = _validate_and_encode_server("server name")
        assert result == "server%20name"

    def test_server_validation_allows_safe_chars(self) -> None:
        """Test that normal server names pass through unchanged."""
        from scripts.servers.mcp.client.http_client import _validate_and_encode_server

        assert _validate_and_encode_server("background-job") == "background-job"
        assert _validate_and_encode_server("my_server_v2") == "my_server_v2"
        assert _validate_and_encode_server("server.name") == "server.name"


class TestAPIRoutes:
    @pytest.fixture
    def mock_clients(self) -> dict[str, Any]:
        """Create mock MCP clients."""
        mock_client = MagicMock()
        mock_client.is_alive.return_value = True
        mock_client.call_tool.return_value = {"job_id": "test-123"}
        mock_client.list_tools.return_value = {"tools": []}
        return {"default": mock_client}

    @pytest.fixture
    def app(self, mock_clients: dict[str, Any]) -> Any:
        """Create FastAPI app with mocked clients."""
        from fastapi import FastAPI

        from scripts.servers.mcp.app.api.routes import create_router

        app = FastAPI()
        config = MCPConfig()

        def get_config() -> MCPConfig:
            return config

        def get_clients() -> dict[str, Any]:
            return mock_clients

        router = create_router(get_config, get_clients)
        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app: Any) -> TestClient:
        """Create test client."""
        return TestClient(app)


class TestSchemas:
    def test_mcp_call_request_timeout_alias(self) -> None:
        """Test MCPCallRequest accepts both 'timeout' and 'timeout_seconds'."""
        # Using timeout (alias)
        req1 = MCPCallRequest(tool="test", arguments={}, timeout=60)
        assert req1.timeout_seconds == 60

        # Using timeout_seconds (actual field name)
        req2 = MCPCallRequest(tool="test", arguments={}, timeout_seconds=90)
        assert req2.timeout_seconds == 90

    def test_error_envelope_structure(self) -> None:
        """Test ErrorEnvelope has correct structure."""
        from scripts.servers.mcp.app.contracts.schemas import ErrorDetail

        envelope = ErrorEnvelope(
            error=ErrorDetail(
                type=ErrorType.JSONRPC_ERROR,
                message="Test error",
                details={"code": -32600},
            )
        )
        data = envelope.model_dump()
        assert data["error"]["type"] == "JSONRPC_ERROR"
        assert data["error"]["message"] == "Test error"
        assert data["error"]["details"]["code"] == -32600

    def test_health_response_structure(self) -> None:
        """Test HealthResponse has correct structure"""
        resp = HealthResponse(status="ok", provider="running")
        data = resp.model_dump()
        assert data["status"] == "ok"
        assert data["provider"] == "running"

    def test_mcp_call_response_structure(self) -> None:
        """Test MCPCallResponse wraps result correctly."""
        resp = MCPCallResponse(result={"job_id": "test-123"})
        data = resp.model_dump()
        assert "result" in data
        assert data["result"]["job_id"] == "test-123"


class TestMCPSSEClientLiveness:
    def test_is_alive_returns_false_before_initialization(self) -> None:
        """Test is_alive returns False before client is initialized."""
        from scripts.servers.mcp.app.services.sse_client import MCPSSEClient

        client = MCPSSEClient(url="https://example.com/sse")
        assert client.is_alive() is False

    def test_is_alive_returns_true_after_successful_request(self) -> None:
        """Test is_alive returns True after a successful request."""
        from scripts.servers.mcp.app.services.sse_client import MCPSSEClient

        client = MCPSSEClient(url="https://example.com/sse")

        # Simulate successful initialization state
        client._initialized = True
        client._last_success_time = time.monotonic()
        client._consecutive_failures = 0

        assert client.is_alive() is True

    def test_is_alive_returns_false_after_max_failures(self) -> None:
        """Test is_alive returns False after exceeding failure threshold."""
        from scripts.servers.mcp.app.services.sse_client import MCPSSEClient

        client = MCPSSEClient(url="https://example.com/sse")

        # Simulate initialized but many failures
        client._initialized = True
        client._last_success_time = time.monotonic()
        client._consecutive_failures = client._max_consecutive_failures

        assert client.is_alive() is False

    def test_is_alive_returns_false_when_stale(self) -> None:
        """Test is_alive returns False when last success is too old."""
        from scripts.servers.mcp.app.services.sse_client import MCPSSEClient

        client = MCPSSEClient(url="https://example.com/sse")

        # Simulate initialized but stale (success was 6 minutes ago)
        client._initialized = True
        client._last_success_time = time.monotonic() - 360.0  # 6 minutes ago
        client._consecutive_failures = 0

        assert client.is_alive() is False

    def test_is_alive_returns_false_when_no_success_time(self) -> None:
        """Test is_alive returns False when no successful request has been made."""
        from scripts.servers.mcp.app.services.sse_client import MCPSSEClient

        client = MCPSSEClient(url="https://example.com/sse")

        # Simulate initialized but no successful request
        client._initialized = True
        client._last_success_time = None
        client._consecutive_failures = 0

        assert client.is_alive() is False

    def test_close_resets_health_tracking(self) -> None:
        """Test close() resets all health tracking fields."""
        from scripts.servers.mcp.app.services.sse_client import MCPSSEClient

        client = MCPSSEClient(url="https://example.com/sse")

        # Simulate a healthy state
        client._initialized = True
        client._last_success_time = time.monotonic()
        client._consecutive_failures = 0

        assert client.is_alive() is True

        client.close()

        # All health fields should be reset
        assert client._initialized is False
        assert client._last_success_time is None
        assert client._consecutive_failures == 0
        assert client.is_alive() is False

    def test_configurable_health_thresholds(self) -> None:
        """Test max_consecutive_failures and max_staleness_seconds are configurable."""
        from scripts.servers.mcp.app.services.sse_client import MCPSSEClient

        # Test custom max_consecutive_failures
        client = MCPSSEClient(
            url="https://example.com/sse",
            max_consecutive_failures=5,
            max_staleness_seconds=600.0,
        )
        assert client._max_consecutive_failures == 5
        assert client._max_staleness_seconds == 600.0

        # Simulate initialized state with 4 failures (should still be alive with threshold of 5)
        client._initialized = True
        client._last_success_time = time.monotonic()
        client._consecutive_failures = 4

        assert client.is_alive() is True  # 4 < 5, still alive

        # Now 5 failures should make it unhealthy
        client._consecutive_failures = 5
        assert client.is_alive() is False

        client.close()

    def test_default_health_threshold_values(self) -> None:
        """Test default values for health thresholds."""
        from scripts.servers.mcp.app.services.sse_client import MCPSSEClient

        client = MCPSSEClient(url="https://example.com/sse")
        assert client._max_consecutive_failures == 3
        assert client._max_staleness_seconds == 300.0
        client.close()
