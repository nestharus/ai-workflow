"""Tests for scripts.servers.mcp.client.http_client module."""

from __future__ import annotations

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from scripts.servers.mcp.client.http_client import (
    HttpMCPClient,
    MCPClientError,
    _validate_and_encode_server,
)


class TestValidateAndEncodeServer:
    """Tests for _validate_and_encode_server function."""

    def test_returns_encoded_server_name(self) -> None:
        """Should return URL-encoded server name."""
        result = _validate_and_encode_server("my-server")
        assert result == "my-server"

    def test_encodes_special_characters(self) -> None:
        """Should URL-encode special characters."""
        result = _validate_and_encode_server("my/server#1")
        assert result == "my%2Fserver%231"

    def test_strips_whitespace(self) -> None:
        """Should strip whitespace from server name."""
        result = _validate_and_encode_server("  my-server  ")
        assert result == "my-server"

    def test_raises_for_non_string(self) -> None:
        """Should raise MCPClientError for non-string input."""
        with pytest.raises(MCPClientError, match="must be a non-empty string"):
            _validate_and_encode_server(123)  # type: ignore[arg-type]

    def test_raises_for_empty_string(self) -> None:
        """Should raise MCPClientError for empty string."""
        with pytest.raises(MCPClientError, match="must be a non-empty string"):
            _validate_and_encode_server("")

    def test_raises_for_whitespace_only(self) -> None:
        """Should raise MCPClientError for whitespace-only string."""
        with pytest.raises(MCPClientError, match="must be a non-empty string"):
            _validate_and_encode_server("   ")


class TestHttpMCPClientInit:
    """Tests for HttpMCPClient.__init__ method."""

    def test_uses_socket_path_from_argument(self) -> None:
        """Should use socket_path from constructor argument."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        assert client.socket_path == "/tmp/test.sock"
        assert client.base_url == "http://localhost"

    def test_uses_socket_path_from_env(self) -> None:
        """Should use socket_path from MCP_BRIDGE_SOCKET env var."""
        with patch.dict(os.environ, {"MCP_BRIDGE_SOCKET": "/tmp/env.sock"}, clear=True):
            client = HttpMCPClient()

        assert client.socket_path == "/tmp/env.sock"
        assert client.base_url == "http://localhost"

    def test_uses_base_url_from_argument(self) -> None:
        """Should use base_url from constructor argument."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://example.com:9000")

        assert client.socket_path is None
        assert client.base_url == "http://example.com:9000"

    def test_uses_base_url_from_env(self) -> None:
        """Should use base_url from MCP_BRIDGE_URL env var."""
        with patch.dict(os.environ, {"MCP_BRIDGE_URL": "http://env.example.com"}, clear=True):
            client = HttpMCPClient()

        assert client.socket_path is None
        assert client.base_url == "http://env.example.com"

    def test_uses_default_base_url(self) -> None:
        """Should use default base_url when not provided."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient()

        assert client.socket_path is None
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
        assert client.base_url == "http://localhost"  # Dummy URL for socket mode

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


class TestHttpMCPClientListServers:
    """Tests for HttpMCPClient.list_servers method."""

    def test_calls_correct_endpoint(self) -> None:
        """Should call /mcp/servers endpoint."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        mock_response = {"servers": [{"name": "test-server", "healthy": True}]}
        with patch.object(client, "_request_json", return_value=mock_response) as mock_req:
            result = client.list_servers()

        mock_req.assert_called_once_with(
            "GET", "http://localhost:8080/mcp/servers", payload=None, timeout=5.0
        )
        assert result == mock_response


class TestHttpMCPClientListServerTools:
    """Tests for HttpMCPClient.list_server_tools method."""

    def test_calls_correct_endpoint(self) -> None:
        """Should call /mcp/{server}/tools endpoint."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        mock_response = {"tools": [{"name": "test-tool"}]}
        with patch.object(client, "_request_json", return_value=mock_response) as mock_req:
            result = client.list_server_tools("my-server")

        mock_req.assert_called_once_with(
            "GET", "http://localhost:8080/mcp/my-server/tools", payload=None, timeout=10.0
        )
        assert result == mock_response


class TestHttpMCPClientGetServerTool:
    """Tests for HttpMCPClient.get_server_tool method."""

    def test_calls_correct_endpoint(self) -> None:
        """Should call /mcp/{server}/tools/{tool} endpoint."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        mock_response = {"name": "test-tool", "description": "A test tool"}
        with patch.object(client, "_request_json", return_value=mock_response) as mock_req:
            result = client.get_server_tool("my-server", "test-tool")

        mock_req.assert_called_once_with(
            "GET",
            "http://localhost:8080/mcp/my-server/tools/test-tool",
            payload=None,
            timeout=10.0,
        )
        assert result == mock_response

    def test_raises_for_empty_tool_name(self) -> None:
        """Should raise MCPClientError for empty tool_name."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        with pytest.raises(MCPClientError, match="tool_name parameter must be a non-empty string"):
            client.get_server_tool("my-server", "")


class TestHttpMCPClientCallServerTool:
    """Tests for HttpMCPClient.call_server_tool method."""

    def test_calls_correct_endpoint_with_payload(self) -> None:
        """Should call /mcp/{server}/call endpoint with correct payload."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        mock_response = {"result": {"output": "success"}}
        with patch.object(client, "_request_json", return_value=mock_response) as mock_req:
            result = client.call_server_tool("my-server", "test-tool", {"arg1": "value1"})

        mock_req.assert_called_once_with(
            "POST",
            "http://localhost:8080/mcp/my-server/call",
            {"tool": "test-tool", "arguments": {"arg1": "value1"}, "timeout_seconds": 30.0},
            30.0,
        )
        assert result == {"output": "success"}

    def test_returns_response_when_no_result_key(self) -> None:
        """Should return full response when 'result' key not present."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        mock_response = {"data": "some data"}
        with patch.object(client, "_request_json", return_value=mock_response):
            result = client.call_server_tool("my-server", "test-tool", {})

        assert result == mock_response

    def test_raises_for_empty_tool_name(self) -> None:
        """Should raise MCPClientError for empty name parameter."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        with pytest.raises(MCPClientError, match="name parameter must be a non-empty string"):
            client.call_server_tool("my-server", "", {})

    def test_raises_for_non_dict_result(self) -> None:
        """Should raise MCPClientError when result is not a dict."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        mock_response = {"result": "string instead of dict"}
        with (
            patch.object(client, "_request_json", return_value=mock_response),
            pytest.raises(MCPClientError, match=r"Invalid result type.*expected dict.*got str"),
        ):
            client.call_server_tool("my-server", "test-tool", {})

    def test_raises_for_list_result(self) -> None:
        """Should raise MCPClientError when result is a list instead of dict."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        mock_response = {"result": ["item1", "item2"]}
        with (
            patch.object(client, "_request_json", return_value=mock_response),
            pytest.raises(MCPClientError, match=r"Invalid result type.*expected dict.*got list"),
        ):
            client.call_server_tool("my-server", "test-tool", {})


class TestHttpMCPClientHealthCheck:
    """Tests for HttpMCPClient.health_check method."""

    def test_returns_true_on_200_status(self) -> None:
        """Should return True when health endpoint returns 200."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "200"

        with patch("subprocess.run", return_value=mock_result):
            result = client.health_check()

        assert result is True

    def test_returns_false_on_non_200_status(self) -> None:
        """Should return False when health endpoint returns non-200 status."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "503"

        with patch("subprocess.run", return_value=mock_result):
            result = client.health_check()

        assert result is False

    def test_returns_false_on_timeout(self) -> None:
        """Should return False when health check times out."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("curl", 10)
            result = client.health_check()

        assert result is False

    def test_returns_false_on_os_error(self) -> None:
        """Should return False when OSError occurs (e.g., curl not found)."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("No such file or directory: curl")
            result = client.health_check()

        assert result is False

    def test_returns_false_on_curl_failure(self) -> None:
        """Should return False when curl returns non-zero exit code."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        mock_result = MagicMock()
        mock_result.returncode = 7  # Connection refused
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            result = client.health_check()

        assert result is False

    def test_returns_false_on_invalid_status_code(self) -> None:
        """Should return False when status code cannot be parsed as integer."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not_a_number"

        with patch("subprocess.run", return_value=mock_result):
            result = client.health_check()

        assert result is False

    def test_uses_unix_socket_when_configured(self) -> None:
        """Should use --unix-socket option when socket_path is set."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "200"

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            client.health_check()

        call_args = mock_run.call_args[0][0]
        assert "--unix-socket" in call_args
        assert "/tmp/test.sock" in call_args


class TestHttpMCPClientRequestJson:
    """Tests for HttpMCPClient._request_json method."""

    def test_raises_for_invalid_timeout(self) -> None:
        """Should raise MCPClientError for invalid timeout values."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        with pytest.raises(MCPClientError, match="Invalid timeout"):
            client._request_json("GET", "http://localhost/test", timeout=0)

        with pytest.raises(MCPClientError, match="Invalid timeout"):
            client._request_json("GET", "http://localhost/test", timeout=-1)

    def test_raises_for_post_without_payload(self) -> None:
        """Should raise MCPClientError for POST without payload."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        with pytest.raises(MCPClientError, match="POST request requires payload"):
            client._request_json("POST", "http://localhost/test", payload=None)

    def test_raises_for_connection_refused_http(self) -> None:
        """Should raise MCPClientError with helpful message for connection refused (HTTP mode)."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        mock_result = MagicMock()
        mock_result.returncode = 7  # Connection refused

        with (
            patch("subprocess.run", return_value=mock_result),
            pytest.raises(MCPClientError, match="Cannot connect to mcp-bridge"),
        ):
            client._request_json("GET", "http://localhost:8080/test")

    def test_raises_for_connection_refused_socket(self) -> None:
        """Should raise MCPClientError with socket-specific message."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(socket_path="/tmp/test.sock")

        mock_result = MagicMock()
        mock_result.returncode = 7  # Connection refused

        with (
            patch("subprocess.run", return_value=mock_result),
            pytest.raises(MCPClientError, match="Socket not available"),
        ):
            client._request_json("GET", "http://localhost/test")

    def test_raises_for_timeout_exit_code(self) -> None:
        """Should raise MCPClientError for curl timeout exit code."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        mock_result = MagicMock()
        mock_result.returncode = 28  # Timeout

        with (
            patch("subprocess.run", return_value=mock_result),
            pytest.raises(MCPClientError, match="timed out"),
        ):
            client._request_json("GET", "http://localhost:8080/test")

    def test_raises_for_empty_response(self) -> None:
        """Should raise MCPClientError for empty response body."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with (
            patch("subprocess.run", return_value=mock_result),
            pytest.raises(MCPClientError, match="Empty response"),
        ):
            client._request_json("GET", "http://localhost:8080/test")

    def test_raises_for_invalid_json(self) -> None:
        """Should raise MCPClientError for invalid JSON response."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not valid json"

        with (
            patch("subprocess.run", return_value=mock_result),
            pytest.raises(MCPClientError, match="Invalid JSON response"),
        ):
            client._request_json("GET", "http://localhost:8080/test")

    def test_raises_for_non_dict_response(self) -> None:
        """Should raise MCPClientError for non-object JSON response."""
        with patch.dict(os.environ, {}, clear=True):
            client = HttpMCPClient(base_url="http://localhost:8080")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '["list", "not", "object"]'

        with (
            patch("subprocess.run", return_value=mock_result),
            pytest.raises(MCPClientError, match="Invalid response type"),
        ):
            client._request_json("GET", "http://localhost:8080/test")
