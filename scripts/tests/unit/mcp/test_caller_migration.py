import pytest


class TestCallerMigration:
    def test_socket_client_env_var_support(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify socket client respects MCP_BRIDGE_SOCKET env var."""
        from scripts.servers.mcp.client import MCPSocketClient

        env_socket = "/tmp/env-test.sock"
        monkeypatch.setenv("MCP_BRIDGE_SOCKET", env_socket)
        client = MCPSocketClient()
        assert client.socket_path == env_socket

    def test_socket_path_takes_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify socket_path argument takes precedence over env vars."""
        from scripts.servers.mcp.client import MCPSocketClient

        explicit_path = "/tmp/explicit.sock"
        env_path = "/tmp/env.sock"

        monkeypatch.setenv("MCP_BRIDGE_SOCKET", env_path)
        monkeypatch.setenv("MCP_BRIDGE_URL", "http://example.com:9000")
        client = MCPSocketClient(socket_path=explicit_path)
        assert client.socket_path == explicit_path

    def test_mcp_bridge_socket_precedence_over_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify MCP_BRIDGE_SOCKET env var takes precedence over MCP_BRIDGE_URL."""
        from scripts.servers.mcp.client import MCPSocketClient

        socket_path = "/tmp/socket-env.sock"

        monkeypatch.setenv("MCP_BRIDGE_SOCKET", socket_path)
        monkeypatch.setenv("MCP_BRIDGE_URL", "http://example.com:9000")
        client = MCPSocketClient()
        assert client.socket_path == socket_path
