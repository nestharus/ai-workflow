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
    def test_get_server_tool_server_not_found(self, test_client: TestClient):
        """Test getting a tool from a nonexistent server returns 404."""
        response = test_client.get("/mcp/nonexistent-server/tools/any_tool")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert data["error"]["type"] == ErrorType.NOT_FOUND.value
        assert "nonexistent-server" in data["error"]["message"]


class TestCallServerTool:
    def test_call_server_tool_server_not_found(self, test_client: TestClient):
        """Test calling a tool on a nonexistent server returns 404."""
        response = test_client.post(
            "/mcp/nonexistent-server/call",
            json={"tool": "my_tool", "arguments": {}},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert data["error"]["type"] == ErrorType.NOT_FOUND.value


class TestHealthCheck:
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
