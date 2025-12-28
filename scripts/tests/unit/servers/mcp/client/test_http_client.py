import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from scripts.servers.mcp.client.http_client import (
    HttpMCPClient,
    MCPClientError,
    _validate_and_encode_server,
)


class TestHttpMCPClientHealthCheck:
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
