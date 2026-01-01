import json
from typing import Any
from unittest.mock import patch

import pytest

from scripts.servers.mcp.client.http_client import (
    MCPClientError,
    MCPSocketClient,
)


class FakeSocket:
    """Fake socket for testing MCPSocketClient."""

    def __init__(
        self,
        response: dict[str, Any] | None = None,
        connect_error: Exception | None = None,
        recv_error: Exception | None = None,
        timeout_on_recv: bool = False,
    ) -> None:
        """Initialize fake socket."""
        self._response = response
        self._connect_error = connect_error
        self._recv_error = recv_error
        self._timeout_on_recv = timeout_on_recv
        self._sent_data: list[bytes] = []
        self._connected = False
        self._timeout: float | None = None

    def settimeout(self, timeout: float) -> None:
        """Set socket timeout."""
        self._timeout = timeout

    def connect(self, address: str) -> None:
        """Connect to socket path."""
        if self._connect_error:
            raise self._connect_error
        self._connected = True

    def sendall(self, data: bytes) -> None:
        """Send data."""
        self._sent_data.append(data)

    def recv(self, bufsize: int) -> bytes:
        """Receive data."""
        if self._timeout_on_recv:
            raise TimeoutError("timed out")
        if self._recv_error:
            raise self._recv_error
        if self._response is None:
            return b""
        # Return response as JSONL (JSON + newline)
        return json.dumps(self._response).encode("utf-8") + b"\n"

    def close(self) -> None:
        """Close socket."""
        pass

    @property
    def last_timeout(self) -> float | None:
        """Get the last timeout that was set."""
        return self._timeout


class TimeoutTrackingFakeSocket(FakeSocket):
    """Fake socket that tracks timeout values for testing."""

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        """Initialize with response."""
        super().__init__(response=response)
        self.all_timeouts: list[float] = []

    def settimeout(self, timeout: float) -> None:
        """Track timeout and set it."""
        self.all_timeouts.append(timeout)
        super().settimeout(timeout)


class ChunkedFakeSocket(FakeSocket):
    """Fake socket that returns response in chunks to simulate partial reads."""

    def __init__(self, response: dict[str, Any], chunk_size: int = 10) -> None:
        """Initialize chunked socket.

        Args:
            response: The response dict to return.
            chunk_size: Maximum bytes to return per recv call.
        """
        super().__init__(response=response)
        self._chunk_size = chunk_size
        self._response_bytes: bytes | None = None
        self._offset = 0

    def recv(self, bufsize: int) -> bytes:
        """Return response in chunks, limited by chunk_size and bufsize."""
        if self._timeout_on_recv:
            raise TimeoutError("timed out")
        if self._recv_error:
            raise self._recv_error

        # Lazily initialize response bytes
        if self._response_bytes is None:
            if self._response is None:
                return b""
            self._response_bytes = json.dumps(self._response).encode("utf-8") + b"\n"

        # Return empty bytes when all data consumed
        if self._offset >= len(self._response_bytes):
            return b""

        # Return chunk limited by both bufsize and chunk_size
        end = self._offset + min(bufsize, self._chunk_size)
        chunk = self._response_bytes[self._offset : end]
        self._offset += len(chunk)
        return chunk


class TestSocketClientParameterValidation:
    def test_invalid_timeout_zero_raises_error(self) -> None:
        """Test timeout == 0 raises MCPClientError."""
        response = {"id": "test", "status": "success", "result": {"result": {}}}
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match="Invalid timeout"):
                client.call_server_tool("test-server", "tool", {}, timeout=0)

    def test_invalid_timeout_negative_raises_error(self) -> None:
        """Test timeout < 0 raises MCPClientError."""
        response = {"id": "test", "status": "success", "result": {"result": {}}}
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match="Invalid timeout"):
                client.call_server_tool("test-server", "tool", {}, timeout=-1)


class TestSocketClientErrorMessagePatterns:
    def test_connection_failure_message_includes_socket_path(self) -> None:
        """Test connection failure error includes socket path."""
        fake_socket = FakeSocket(connect_error=OSError("Connection refused"))

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/missing.sock")
            with pytest.raises(MCPClientError) as exc_info:
                client.list_servers()
            assert "/tmp/missing.sock" in str(exc_info.value)
            assert "Socket not available" in str(exc_info.value)

    def test_timeout_error_message_includes_timed_out(self) -> None:
        """Test timeout error message includes 'timed out'."""
        fake_socket = FakeSocket(timeout_on_recv=True)

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError) as exc_info:
                client.call_server_tool("server", "tool", {}, timeout=5.0)
            assert "timed out" in str(exc_info.value).lower()

    def test_error_envelope_parsed_to_bracketed_format(self) -> None:
        """Test error envelope is parsed to [ERROR_TYPE] message format."""
        error_response = {
            "id": "test",
            "status": "error",
            "error": {
                "type": "NOT_FOUND",
                "message": "Server 'xyz' not found",
            },
        }
        fake_socket = FakeSocket(response=error_response)

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match=r"\[NOT_FOUND\] Server 'xyz' not found"):
                client.list_server_tools("xyz")

    def test_all_error_types_produce_bracketed_format(self) -> None:
        """Test all error types produce [ERROR_TYPE] message format."""
        error_types = [
            ("BAD_REQUEST", "Invalid arguments"),
            ("NOT_FOUND", "Server not found"),
            ("JSONRPC_ERROR", "MCP protocol error"),
            ("TIMEOUT", "Request timed out"),
            ("BUSY", "Server busy"),
            ("PROVIDER_CRASHED", "Provider crashed and was restarted"),
            ("INTERNAL", "Internal error"),
        ]

        for error_type, message in error_types:
            error_response = {
                "id": "test",
                "status": "error",
                "error": {"type": error_type, "message": message},
            }
            fake_socket = FakeSocket(response=error_response)

            with patch("socket.socket", return_value=fake_socket):
                client = MCPSocketClient(socket_path="/tmp/test.sock")
                with pytest.raises(MCPClientError) as exc_info:
                    client.list_servers()
                assert f"[{error_type}]" in str(exc_info.value), (
                    f"Failed for error type: {error_type}"
                )
                assert message in str(exc_info.value), f"Failed for message: {message}"


class TestSocketClientResponseExtraction:
    def test_call_server_tool_extracts_result_key(self) -> None:
        """Test call_server_tool extracts result key from response envelope."""
        response = {
            "id": "test",
            "status": "success",
            "result": {"result": {"job_id": "123"}},
        }
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            result = client.call_server_tool("server", "tool", {})
            assert result == {"job_id": "123"}

    def test_call_server_tool_fallback_when_no_result_key(self) -> None:
        """Test call_server_tool returns full response when result key missing."""
        response = {
            "id": "test",
            "status": "success",
            "result": {"status": "ok", "data": "value"},
        }
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            result = client.call_server_tool("server", "tool", {})
            assert result == {"status": "ok", "data": "value"}

    def test_call_server_tool_invalid_result_type_raises_error(self) -> None:
        """Test call_server_tool raises error when result is not a dict."""
        response = {
            "id": "test",
            "status": "success",
            "result": {"result": "not a dict"},
        }
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match="Invalid result type"):
                client.call_server_tool("server", "tool", {})

    def test_empty_response_raises_error(self) -> None:
        """Test empty response raises MCPClientError."""
        fake_socket = FakeSocket(response=None)  # Returns empty bytes

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match="Empty response from server"):
                client.list_servers()

    def test_invalid_json_response_raises_error(self) -> None:
        """Test invalid JSON response raises MCPClientError."""

        class BadJsonSocket(FakeSocket):
            def recv(self, bufsize: int) -> bytes:
                return b"{bad json\n"

        fake_socket = BadJsonSocket()

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match="Invalid JSON response"):
                client.list_servers()

    def test_non_dict_response_raises_error(self) -> None:
        """Test non-dict JSON response raises MCPClientError."""

        class ArrayResponseSocket(FakeSocket):
            def recv(self, bufsize: int) -> bytes:
                return b"[]\n"

        fake_socket = ArrayResponseSocket()

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match="Invalid response type"):
                client.list_servers()


class TestSocketClientDefaultTimeouts:
    def test_list_servers_uses_5s_default_timeout(self) -> None:
        """Test list_servers uses 5 second default timeout."""
        response = {"id": "test", "status": "success", "result": {"servers": []}}
        fake_socket = TimeoutTrackingFakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            client.list_servers()
            assert fake_socket.last_timeout == 5.0

    def test_list_server_tools_uses_10s_default_timeout(self) -> None:
        """Test list_server_tools uses 10 second default timeout."""
        response = {"id": "test", "status": "success", "result": {"tools": []}}
        fake_socket = TimeoutTrackingFakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            client.list_server_tools("server")
            assert fake_socket.last_timeout == 10.0

    def test_get_server_tool_uses_10s_default_timeout(self) -> None:
        """Test get_server_tool uses 10 second default timeout."""
        response = {"id": "test", "status": "success", "result": {"name": "tool"}}
        fake_socket = TimeoutTrackingFakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            client.get_server_tool("server", "tool")
            assert fake_socket.last_timeout == 10.0

    def test_call_server_tool_uses_30s_default_timeout(self) -> None:
        """Test call_server_tool uses 30 second default timeout."""
        response = {"id": "test", "status": "success", "result": {"result": {}}}
        fake_socket = TimeoutTrackingFakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            client.call_server_tool("server", "tool", {})
            assert fake_socket.last_timeout == 30.0

    def test_health_check_uses_5s_default_timeout(self) -> None:
        """Test health_check uses 5 second default timeout."""
        response = {"id": "test", "status": "success", "result": {"status": "ok"}}
        fake_socket = TimeoutTrackingFakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            client.health_check()
            assert fake_socket.last_timeout == 5.0

    def test_call_server_tool_custom_timeout_is_used(self) -> None:
        """Test call_server_tool uses custom timeout when provided."""
        response = {"id": "test", "status": "success", "result": {"result": {}}}
        fake_socket = TimeoutTrackingFakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            client.call_server_tool("server", "tool", {}, timeout=45.0)
            assert fake_socket.last_timeout == 45.0


class TestSocketClientClientLevelFailures:
    def test_socket_not_available_raises_mcp_client_error(self) -> None:
        """Test socket not available raises MCPClientError with socket path."""
        fake_socket = FakeSocket(connect_error=FileNotFoundError("No such file"))

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/nonexistent.sock")
            with pytest.raises(MCPClientError) as exc_info:
                client.list_servers()
            assert "/tmp/nonexistent.sock" in str(exc_info.value)
            assert "Socket not available" in str(exc_info.value)

    def test_connection_refused_raises_mcp_client_error(self) -> None:
        """Test connection refused raises MCPClientError."""
        fake_socket = FakeSocket(connect_error=ConnectionRefusedError("Connection refused"))

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError) as exc_info:
                client.list_servers()
            assert "Cannot connect" in str(exc_info.value)

    def test_server_timeout_raises_mcp_client_error_with_duration(self) -> None:
        """Test server timeout raises MCPClientError with timeout info."""
        fake_socket = FakeSocket(timeout_on_recv=True)

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError) as exc_info:
                client.call_server_tool("server", "tool", {}, timeout=5.0)
            assert "timed out" in str(exc_info.value).lower()

    def test_empty_response_raises_mcp_client_error(self) -> None:
        """Test empty response raises MCPClientError with descriptive message."""
        fake_socket = FakeSocket(response=None)

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match="Empty response from server"):
                client.list_servers()

    def test_invalid_json_raises_mcp_client_error(self) -> None:
        """Test invalid JSON raises MCPClientError with parse error."""

        class BadJsonSocket(FakeSocket):
            def recv(self, bufsize: int) -> bytes:
                return b"{invalid\n"

        fake_socket = BadJsonSocket()

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match="Invalid JSON response"):
                client.list_servers()

    def test_non_dict_json_raises_mcp_client_error(self) -> None:
        """Test non-dict JSON raises MCPClientError with type error."""

        class ArraySocket(FakeSocket):
            def recv(self, bufsize: int) -> bytes:
                return b'["array"]\n'

        fake_socket = ArraySocket()

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match="Invalid response type"):
                client.list_servers()


class TestSocketClientHealthCheck:
    def test_health_check_returns_true_on_ok_status(self) -> None:
        """Test health_check returns True when status is ok."""
        response = {
            "id": "test",
            "status": "success",
            "result": {"status": "ok", "provider": "running"},
        }
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            assert client.health_check() is True

    def test_health_check_returns_false_on_degraded_status(self) -> None:
        """Test health_check returns False when status is degraded."""
        response = {
            "id": "test",
            "status": "success",
            "result": {"status": "degraded", "provider": "down"},
        }
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            assert client.health_check() is False

    def test_health_check_returns_false_on_connection_error(self) -> None:
        """Test health_check returns False on connection error."""
        fake_socket = FakeSocket(connect_error=OSError("Connection refused"))

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            assert client.health_check() is False

    def test_health_check_returns_false_on_timeout(self) -> None:
        """Test health_check returns False on timeout."""
        fake_socket = FakeSocket(timeout_on_recv=True)

        with patch("socket.socket", return_value=fake_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            assert client.health_check() is False


class TestSocketClientPartialReads:
    def test_chunked_socket_returns_same_result_as_full_response(self) -> None:
        """Test that chunked socket reads produce identical results to full reads."""
        response = {
            "id": "test",
            "status": "success",
            "result": {"servers": [{"name": "test-server", "healthy": True}]},
        }

        # Full response socket
        full_socket = FakeSocket(response=response)
        with patch("socket.socket", return_value=full_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            full_result = client.list_servers()

        # Chunked response socket (10 bytes at a time)
        chunked_socket = ChunkedFakeSocket(response=response, chunk_size=10)
        with patch("socket.socket", return_value=chunked_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            chunked_result = client.list_servers()

        assert chunked_result == full_result

    def test_chunked_socket_with_very_small_chunks(self) -> None:
        """Test chunked reads with 1-byte chunks."""
        response = {
            "id": "test",
            "status": "success",
            "result": {"tools": [{"name": "tool1"}, {"name": "tool2"}]},
        }

        # 1-byte chunks (extreme case)
        chunked_socket = ChunkedFakeSocket(response=response, chunk_size=1)
        with patch("socket.socket", return_value=chunked_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            result = client.list_server_tools("test-server")

        assert result == {"tools": [{"name": "tool1"}, {"name": "tool2"}]}

    def test_chunked_socket_with_call_server_tool(self) -> None:
        """Test chunked reads with call_server_tool extracts result correctly."""
        response = {
            "id": "test",
            "status": "success",
            "result": {"result": {"job_id": "abc123", "status": "completed"}},
        }

        chunked_socket = ChunkedFakeSocket(response=response, chunk_size=15)
        with patch("socket.socket", return_value=chunked_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            result = client.call_server_tool("server", "tool", {"arg": "value"})

        # call_server_tool extracts the inner "result" key
        assert result == {"job_id": "abc123", "status": "completed"}

    def test_chunked_socket_handles_error_response(self) -> None:
        """Test chunked reads correctly parse error responses."""
        error_response = {
            "id": "test",
            "status": "error",
            "error": {"type": "NOT_FOUND", "message": "Server not found"},
        }

        chunked_socket = ChunkedFakeSocket(response=error_response, chunk_size=8)
        with patch("socket.socket", return_value=chunked_socket):
            client = MCPSocketClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match=r"\[NOT_FOUND\] Server not found"):
                client.list_servers()
