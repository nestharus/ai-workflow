"""Tests for scripts.servers.mcp.client.http_client module."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from scripts.servers.mcp.client.http_client import (
    HttpMCPClient,
    MCPClientError,
)


class TestValidateServer:
    """Tests for _validate_server function."""

    def test_returns_stripped_server_name(self) -> None:
        """Should return stripped server name."""
        from scripts.servers.mcp.client.http_client import _validate_server

        result = _validate_server("my-server")
        assert result == "my-server"

    def test_strips_whitespace(self) -> None:
        """Should strip whitespace from server name."""
        from scripts.servers.mcp.client.http_client import _validate_server

        result = _validate_server("  my-server  ")
        assert result == "my-server"

    def test_raises_for_non_string(self) -> None:
        """Should raise MCPClientError for non-string input."""
        from scripts.servers.mcp.client.http_client import _validate_server

        with pytest.raises(MCPClientError, match="parameter must be a non-empty string"):
            _validate_server(123)  # type: ignore[arg-type]

    def test_raises_for_empty_string(self) -> None:
        """Should raise MCPClientError for empty string."""
        from scripts.servers.mcp.client.http_client import _validate_server

        with pytest.raises(MCPClientError, match="parameter must be a non-empty string"):
            _validate_server("")

    def test_raises_for_whitespace_only(self) -> None:
        """Should raise MCPClientError for whitespace-only string."""
        from scripts.servers.mcp.client.http_client import _validate_server

        with pytest.raises(MCPClientError, match="parameter must be a non-empty string"):
            _validate_server("   ")


class TestHttpMCPClientInit:
    """Tests for HttpMCPClient.__init__ method."""

    def test_uses_socket_path_from_argument(self) -> None:
        """Should use socket_path from constructor argument."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        assert client.socket_path == "/tmp/test.sock"
        # base_url defaults to http://localhost:8080 when not provided
        assert client.base_url == "http://localhost:8080"

    def test_uses_socket_path_from_env(self) -> None:
        """Should use socket_path from MCP_BRIDGE_SOCKET env var."""
        with patch.dict(os.environ, {"MCP_BRIDGE_SOCKET": "/tmp/env.sock"}, clear=True):
            client = HttpMCPClient()

        assert client.socket_path == "/tmp/env.sock"
        # base_url defaults to http://localhost:8080 when not provided
        assert client.base_url == "http://localhost:8080"

    def test_uses_base_url_from_argument(self) -> None:
        """Should use base_url from constructor argument."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://example.com:9000")

        # socket_path defaults to /tmp/mcp-bridge.sock when not provided
        assert client.socket_path == "/tmp/mcp-bridge.sock"
        assert client.base_url == "http://example.com:9000"

    def test_uses_base_url_from_env(self) -> None:
        """Should use base_url from MCP_BRIDGE_URL env var."""
        with patch.dict(os.environ, {"MCP_BRIDGE_URL": "http://env.example.com"}, clear=True):
            client = HttpMCPClient()

        # socket_path defaults to /tmp/mcp-bridge.sock when not provided
        assert client.socket_path == "/tmp/mcp-bridge.sock"
        assert client.base_url == "http://env.example.com"

    def test_uses_default_base_url(self) -> None:
        """Should use default base_url when not provided."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient()

        # Default socket path is used when no socket_path provided
        assert client.socket_path == "/tmp/mcp-bridge.sock"
        assert client.base_url == "http://localhost:8080"

    def test_strips_trailing_slash_from_base_url(self) -> None:
        """Should strip trailing slash from base_url."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://example.com/")

        assert client.base_url == "http://example.com"

    def test_socket_path_takes_precedence_over_base_url(self) -> None:
        """Should use socket_path when both socket_path and base_url are provided."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://example.com", socket_path="/tmp/test.sock")

        assert client.socket_path == "/tmp/test.sock"
        # base_url is still set from the argument
        assert client.base_url == "http://example.com"

    def test_raises_for_non_string_socket_path(self) -> None:
        """Should raise MCPClientError when socket_path is not a string."""
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(MCPClientError, match="socket_path must be a string path"),
        ):
            HttpMCPClient(socket_path=123)  # type: ignore[arg-type]

    def test_raises_for_non_string_base_url(self) -> None:
        """Should raise MCPClientError when base_url is not a string."""
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(MCPClientError, match="base_url must be a string URL"),
        ):
            HttpMCPClient(base_url=123)  # type: ignore[arg-type]

    def test_raises_for_empty_base_url(self) -> None:
        """Should raise MCPClientError when base_url is empty after stripping."""
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(MCPClientError, match="Invalid base_url: empty"),
        ):
            HttpMCPClient(base_url="   ")


class TestMCPSocketClientListServers:
    """Tests for MCPSocketClient.list_servers method."""

    def test_calls_correct_method(self) -> None:
        """Should call 'list_servers' method with correct params."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        mock_response = {"servers": [{"name": "test-server", "healthy": True}]}
        with patch.object(client, "_request_jsonl", return_value=mock_response) as mock_req:
            result = client.list_servers()

        mock_req.assert_called_once_with("list_servers", timeout=5.0)
        assert result == mock_response


class TestMCPSocketClientListServerTools:
    """Tests for MCPSocketClient.list_server_tools method."""

    def test_calls_correct_method(self) -> None:
        """Should call 'list_tools' method with server param."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        mock_response = {"tools": [{"name": "test-tool"}]}
        with patch.object(client, "_request_jsonl", return_value=mock_response) as mock_req:
            result = client.list_server_tools("my-server")

        mock_req.assert_called_once_with("list_tools", params={"server": "my-server"}, timeout=10.0)
        assert result == mock_response


class TestMCPSocketClientGetServerTool:
    """Tests for MCPSocketClient.get_server_tool method."""

    def test_calls_correct_method(self) -> None:
        """Should call 'get_server_tool' method with correct params."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        mock_response = {"name": "test-tool", "description": "A test tool"}
        with patch.object(client, "_request_jsonl", return_value=mock_response) as mock_req:
            result = client.get_server_tool("my-server", "test-tool")

        mock_req.assert_called_once_with(
            "get_server_tool",
            params={"server": "my-server", "tool_name": "test-tool"},
            timeout=10.0,
        )
        assert result == mock_response

    def test_raises_for_empty_tool_name(self) -> None:
        """Should raise MCPClientError for empty tool_name."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        with pytest.raises(MCPClientError, match="tool_name parameter must be a non-empty string"):
            client.get_server_tool("my-server", "")


class TestMCPSocketClientCallServerTool:
    """Tests for MCPSocketClient.call_server_tool method."""

    def test_calls_correct_method_with_payload(self) -> None:
        """Should call 'call_tool' method with correct payload."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        mock_response = {"result": {"output": "success"}}
        with patch.object(client, "_request_jsonl", return_value=mock_response) as mock_req:
            result = client.call_server_tool("my-server", "test-tool", {"arg1": "value1"})

        mock_req.assert_called_once_with(
            "call_tool",
            params={
                "server": "my-server",
                "tool": "test-tool",
                "arguments": {"arg1": "value1"},
                "timeout_seconds": 30.0,
            },
            timeout=30.0,
        )
        assert result == {"output": "success"}

    def test_returns_response_when_no_result_key(self) -> None:
        """Should return full response when 'result' key not present."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        mock_response = {"data": "some data"}
        with patch.object(client, "_request_jsonl", return_value=mock_response):
            result = client.call_server_tool("my-server", "test-tool", {})

        assert result == mock_response

    def test_raises_for_empty_tool_name(self) -> None:
        """Should raise MCPClientError for empty name parameter."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        with pytest.raises(MCPClientError, match="name parameter must be a non-empty string"):
            client.call_server_tool("my-server", "", {})

    def test_raises_for_non_dict_result(self) -> None:
        """Should raise MCPClientError when result is not a dict."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        mock_response = {"result": "string instead of dict"}
        with (
            patch.object(client, "_request_jsonl", return_value=mock_response),
            pytest.raises(MCPClientError, match=r"Invalid result type.*expected dict.*got str"),
        ):
            client.call_server_tool("my-server", "test-tool", {})

    def test_raises_for_list_result(self) -> None:
        """Should raise MCPClientError when result is a list instead of dict."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        mock_response = {"result": ["item1", "item2"]}
        with (
            patch.object(client, "_request_jsonl", return_value=mock_response),
            pytest.raises(MCPClientError, match=r"Invalid result type.*expected dict.*got list"),
        ):
            client.call_server_tool("my-server", "test-tool", {})


class TestMCPSocketClientHealthCheck:
    """Tests for MCPSocketClient.health_check method."""

    def test_returns_true_on_ok_status(self) -> None:
        """Should return True when health endpoint returns status=ok."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        mock_response = {"status": "ok", "provider": "running"}
        with patch.object(client, "_request_jsonl", return_value=mock_response):
            result = client.health_check()

        assert result is True

    def test_returns_false_on_non_ok_status(self) -> None:
        """Should return False when health endpoint returns non-ok status."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        mock_response = {"status": "error"}
        with patch.object(client, "_request_jsonl", return_value=mock_response):
            result = client.health_check()

        assert result is False

    def test_returns_false_on_timeout(self) -> None:
        """Should return False when health check times out."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        with patch.object(client, "_request_jsonl", side_effect=MCPClientError("timeout")):
            result = client.health_check()

        assert result is False

    def test_returns_false_on_connection_error(self) -> None:
        """Should return False when connection error occurs."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        with patch.object(
            client, "_request_jsonl", side_effect=MCPClientError("Socket not available")
        ):
            result = client.health_check()

        assert result is False


class TestMCPSocketClientRequestJsonl:
    """Tests for MCPSocketClient._request_jsonl method."""

    def test_raises_for_invalid_timeout(self) -> None:
        """Should raise MCPClientError for invalid timeout values."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        with pytest.raises(MCPClientError, match="Invalid timeout"):
            client._request_jsonl("test_method", timeout=0)

        with pytest.raises(MCPClientError, match="Invalid timeout"):
            client._request_jsonl("test_method", timeout=-1)

    def test_raises_for_empty_response(self) -> None:
        """Should raise MCPClientError for empty response body."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [b"", b""]  # Empty response
        with (
            patch("socket.socket", return_value=mock_sock),
            pytest.raises(MCPClientError, match="Empty response"),
        ):
            client._request_jsonl("test_method")

    def test_raises_for_invalid_json(self) -> None:
        """Should raise MCPClientError for invalid JSON response."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        mock_sock = MagicMock()
        mock_sock.recv.return_value = b"not valid json\n"
        with (
            patch("socket.socket", return_value=mock_sock),
            pytest.raises(MCPClientError, match="Invalid JSON response"),
        ):
            client._request_jsonl("test_method")

    def test_raises_for_non_dict_response(self) -> None:
        """Should raise MCPClientError for non-object JSON response."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        mock_sock = MagicMock()
        mock_sock.recv.return_value = b'["list", "not", "object"]\n'
        with (
            patch("socket.socket", return_value=mock_sock),
            pytest.raises(MCPClientError, match="Invalid response type"),
        ):
            client._request_jsonl("test_method")

    def test_returns_result_on_success(self) -> None:
        """Should return result dict on success response."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        mock_sock = MagicMock()
        mock_sock.recv.return_value = (
            b'{"id": "123", "status": "success", "result": {"data": "value"}}\n'
        )
        with patch("socket.socket", return_value=mock_sock):
            result = client._request_jsonl("test_method")

        assert result == {"data": "value"}

    def test_raises_on_error_response(self) -> None:
        """Should raise MCPClientError on error response."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        mock_sock = MagicMock()
        mock_sock.recv.return_value = b'{"id": "123", "status": "error", "error": {"type": "TEST_ERROR", "message": "test error"}}\n'
        with (
            patch("socket.socket", return_value=mock_sock),
            pytest.raises(MCPClientError, match="\\[TEST_ERROR\\] test error"),
        ):
            client._request_jsonl("test_method")

    def test_raises_on_error_status_without_error_payload(self) -> None:
        """Should raise MCPClientError when status is error but no error payload is present."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        mock_sock = MagicMock()
        mock_sock.recv.return_value = b'{"id": "123", "status": "error"}\n'
        with (
            patch("socket.socket", return_value=mock_sock),
            pytest.raises(MCPClientError, match="Server returned error status without details"),
        ):
            client._request_jsonl("test_method")
