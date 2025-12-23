"""Tests for MCP Bridge API routes."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from scripts.servers.mcp.app.api.routes import create_router
from scripts.servers.mcp.app.contracts.schemas import (
    ErrorType,
)
from scripts.servers.mcp.app.core.config import (
    MCPConfig,
    StdioServerConfig,
    TransportType,
)
from scripts.servers.mcp.app.services.manager import (
    MCPBusyError,
    MCPClient,
    MCPError,
    MCPProviderCrashedError,
    MCPTimeoutError,
)
from scripts.servers.mcp.app.services.sse_client import MCPSSEError


class MockMCPClient:
    """Mock MCP client for testing."""

    def __init__(
        self,
        alive: bool = True,
        tools: list[dict[str, Any]] | None = None,
        call_result: dict[str, Any] | None = None,
        call_error: Exception | None = None,
        list_tools_error: Exception | None = None,
    ):
        self._alive = alive
        self._tools = tools or []
        self._call_result = call_result or {"status": "ok"}
        self._call_error = call_error
        self._list_tools_error = list_tools_error

    def is_alive(self) -> bool:
        return self._alive

    def list_tools(self, timeout: float = 30.0) -> dict[str, Any]:
        if self._list_tools_error:
            raise self._list_tools_error
        return {"tools": self._tools}

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        if self._call_error:
            raise self._call_error
        return self._call_result

    def close(self) -> None:
        pass


@pytest.fixture
def mock_client() -> MockMCPClient:
    """Create a mock MCP client."""
    return MockMCPClient()


@pytest.fixture
def mock_config() -> MCPConfig:
    """Create a mock MCP config."""
    return MCPConfig(
        servers={
            "test-server": StdioServerConfig(
                name="test-server",
                command="echo",
                args=["hello"],
                transport=TransportType.STDIO,
            ),
        }
    )


@pytest.fixture
def test_client(mock_client: MockMCPClient, mock_config: MCPConfig) -> TestClient:
    """Create a test client with mock dependencies."""
    from fastapi import FastAPI

    app = FastAPI()

    clients: dict[str, MCPClient] = {"test-server": mock_client}  # type: ignore[dict-item]

    def get_config() -> MCPConfig | None:
        return mock_config

    def get_clients() -> dict[str, MCPClient]:
        return clients  # type: ignore[return-value]

    api_router = create_router(get_config, get_clients)
    app.include_router(api_router)

    return TestClient(app)


class TestListServers:
    """Tests for the list_servers endpoint."""

    def test_list_servers_with_config(
        self, test_client: TestClient, mock_client: MockMCPClient, mock_config: MCPConfig
    ):
        """Test listing servers with config returns server info including transport type."""
        response = test_client.get("/mcp/servers")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "servers" in data
        assert len(data["servers"]) == 1
        server = data["servers"][0]
        assert server["name"] == "test-server"
        assert server["transport"] == "stdio"
        assert server["healthy"] is True

    def test_list_servers_no_config(self):
        """Test listing servers when get_config returns None."""
        from fastapi import FastAPI

        app = FastAPI()

        mock_client = MockMCPClient()
        clients: dict[str, MCPClient] = {"test-server": mock_client}  # type: ignore[dict-item]

        def get_config() -> MCPConfig | None:
            return None

        def get_clients() -> dict[str, MCPClient]:
            return clients  # type: ignore[return-value]

        api_router = create_router(get_config, get_clients)
        app.include_router(api_router)

        client = TestClient(app)
        response = client.get("/mcp/servers")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "servers" in data
        assert len(data["servers"]) == 1
        server = data["servers"][0]
        assert server["name"] == "test-server"
        # When config is None, transport should be "unknown"
        assert server["transport"] == "unknown"

    def test_list_servers_config_missing_server(self):
        """Test listing servers when server not in config (server_config is None)."""
        from fastapi import FastAPI

        app = FastAPI()

        mock_client = MockMCPClient()
        clients: dict[str, MCPClient] = {"other-server": mock_client}  # type: ignore[dict-item]

        # Config has different server than clients
        config = MCPConfig(
            servers={
                "different-server": StdioServerConfig(
                    name="different-server",
                    command="echo",
                ),
            }
        )

        def get_config() -> MCPConfig | None:
            return config

        def get_clients() -> dict[str, MCPClient]:
            return clients  # type: ignore[return-value]

        api_router = create_router(get_config, get_clients)
        app.include_router(api_router)

        client = TestClient(app)
        response = client.get("/mcp/servers")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["servers"]) == 1
        server = data["servers"][0]
        assert server["name"] == "other-server"
        # When server not in config, transport should be "unknown"
        assert server["transport"] == "unknown"


class TestGetServerTool:
    """Tests for the get_server_tool endpoint."""

    def test_get_server_tool_found(self, test_client: TestClient, mock_client: MockMCPClient):
        """Test getting a specific tool that exists."""
        mock_client._tools = [
            {"name": "my_tool", "description": "A test tool"},
            {"name": "other_tool", "description": "Another tool"},
        ]
        response = test_client.get("/mcp/test-server/tools/my_tool")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "my_tool"
        assert data["description"] == "A test tool"

    def test_get_server_tool_not_found(self, test_client: TestClient, mock_client: MockMCPClient):
        """Test getting a tool that doesn't exist returns 404."""
        mock_client._tools = [{"name": "other_tool", "description": "Another tool"}]
        response = test_client.get("/mcp/test-server/tools/nonexistent")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert data["error"]["type"] == ErrorType.NOT_FOUND.value
        assert "nonexistent" in data["error"]["message"]

    def test_get_server_tool_server_not_found(self, test_client: TestClient):
        """Test getting a tool from a nonexistent server returns 404."""
        response = test_client.get("/mcp/nonexistent-server/tools/any_tool")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert data["error"]["type"] == ErrorType.NOT_FOUND.value
        assert "nonexistent-server" in data["error"]["message"]

    def test_get_server_tool_mcp_error(self, test_client: TestClient, mock_client: MockMCPClient):
        """Test that MCPError in get_server_tool returns 502."""
        mock_client._list_tools_error = MCPError("Connection failed")
        response = test_client.get("/mcp/test-server/tools/any_tool")
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        data = response.json()
        assert data["error"]["type"] == ErrorType.JSONRPC_ERROR.value

    def test_get_server_tool_sse_error(self, test_client: TestClient, mock_client: MockMCPClient):
        """Test that MCPSSEError in get_server_tool returns 502."""
        mock_client._list_tools_error = MCPSSEError("SSE connection failed")
        response = test_client.get("/mcp/test-server/tools/any_tool")
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        data = response.json()
        assert data["error"]["type"] == ErrorType.JSONRPC_ERROR.value


class TestCallServerTool:
    """Tests for the call_server_tool endpoint."""

    def test_call_server_tool_success(self, test_client: TestClient, mock_client: MockMCPClient):
        """Test successful tool call."""
        mock_client._call_result = {"output": "success"}
        response = test_client.post(
            "/mcp/test-server/call",
            json={"tool": "my_tool", "arguments": {"arg1": "value1"}},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["result"]["output"] == "success"

    def test_call_server_tool_server_not_found(self, test_client: TestClient):
        """Test calling a tool on a nonexistent server returns 404."""
        response = test_client.post(
            "/mcp/nonexistent-server/call",
            json={"tool": "my_tool", "arguments": {}},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert data["error"]["type"] == ErrorType.NOT_FOUND.value

    def test_call_server_tool_busy_error(self, test_client: TestClient, mock_client: MockMCPClient):
        """Test that MCPBusyError returns 503 with retry_after_ms."""
        mock_client._call_error = MCPBusyError("Provider is busy", retry_after_ms=2000)
        response = test_client.post(
            "/mcp/test-server/call",
            json={"tool": "my_tool", "arguments": {}},
        )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        data = response.json()
        assert data["error"]["type"] == ErrorType.BUSY.value
        assert data["error"]["details"]["retry_after_ms"] == 2000

    def test_call_server_tool_provider_crashed(
        self, test_client: TestClient, mock_client: MockMCPClient
    ):
        """Test that MCPProviderCrashedError returns 503."""
        mock_client._call_error = MCPProviderCrashedError("Provider crashed and was restarted")
        response = test_client.post(
            "/mcp/test-server/call",
            json={"tool": "my_tool", "arguments": {}},
        )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        data = response.json()
        assert data["error"]["type"] == ErrorType.PROVIDER_CRASHED.value

    def test_call_server_tool_timeout_error(
        self, test_client: TestClient, mock_client: MockMCPClient
    ):
        """Test that MCPTimeoutError returns 504."""
        mock_client._call_error = MCPTimeoutError("Request timed out")
        response = test_client.post(
            "/mcp/test-server/call",
            json={"tool": "my_tool", "arguments": {}},
        )
        assert response.status_code == status.HTTP_504_GATEWAY_TIMEOUT
        data = response.json()
        assert data["error"]["type"] == ErrorType.TIMEOUT.value

    def test_call_server_tool_mcp_error(self, test_client: TestClient, mock_client: MockMCPClient):
        """Test that MCPError returns 502."""
        mock_client._call_error = MCPError("JSON-RPC error")
        response = test_client.post(
            "/mcp/test-server/call",
            json={"tool": "my_tool", "arguments": {}},
        )
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        data = response.json()
        assert data["error"]["type"] == ErrorType.JSONRPC_ERROR.value

    def test_call_server_tool_sse_error(self, test_client: TestClient, mock_client: MockMCPClient):
        """Test that MCPSSEError returns 502."""
        mock_client._call_error = MCPSSEError("SSE connection failed")
        response = test_client.post(
            "/mcp/test-server/call",
            json={"tool": "my_tool", "arguments": {}},
        )
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        data = response.json()
        assert data["error"]["type"] == ErrorType.JSONRPC_ERROR.value

    def test_call_server_tool_unexpected_error(
        self, test_client: TestClient, mock_client: MockMCPClient
    ):
        """Test that unexpected exceptions return 500."""
        mock_client._call_error = RuntimeError("Unexpected error")
        response = test_client.post(
            "/mcp/test-server/call",
            json={"tool": "my_tool", "arguments": {}},
        )
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        data = response.json()
        assert data["error"]["type"] == ErrorType.INTERNAL.value
        assert "Unexpected error" in data["error"]["message"]


class TestListServerTools:
    """Tests for the list_server_tools endpoint."""

    def test_list_server_tools_success(self, test_client: TestClient, mock_client: MockMCPClient):
        """Test listing tools returns the tools list."""
        mock_client._tools = [
            {"name": "tool1", "description": "First tool"},
            {"name": "tool2", "description": "Second tool"},
        ]
        response = test_client.get("/mcp/test-server/tools")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "tools" in data
        assert len(data["tools"]) == 2

    def test_list_server_tools_mcp_error(self, test_client: TestClient, mock_client: MockMCPClient):
        """Test that MCPError returns 502."""
        mock_client._list_tools_error = MCPError("Connection failed")
        response = test_client.get("/mcp/test-server/tools")
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        data = response.json()
        assert data["error"]["type"] == ErrorType.JSONRPC_ERROR.value


class TestHealthCheck:
    """Tests for the health_check endpoint."""

    def test_health_check_healthy(self, test_client: TestClient, mock_client: MockMCPClient):
        """Test health check when at least one client is alive."""
        mock_client._alive = True
        response = test_client.get("/health")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "ok"
        assert data["provider"] == "running"

    def test_health_check_unhealthy(self):
        """Test health check when no clients are alive."""
        from fastapi import FastAPI

        app = FastAPI()

        mock_client = MockMCPClient(alive=False)
        clients: dict[str, MCPClient] = {"test-server": mock_client}  # type: ignore[dict-item]

        def get_config() -> MCPConfig | None:
            return MCPConfig()

        def get_clients() -> dict[str, MCPClient]:
            return clients  # type: ignore[return-value]

        api_router = create_router(get_config, get_clients)
        app.include_router(api_router)

        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        data = response.json()
        assert data["status"] == "degraded"
        assert data["provider"] == "down"
