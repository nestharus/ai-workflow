"""Tests for Docker healthcheck script."""

from __future__ import annotations

import json
import socket
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator

# Import the healthcheck module
from scripts.servers.mcp import healthcheck


class TestHealthcheck:
    """Tests for healthcheck.main() function."""

    @pytest.fixture
    def socket_path(self) -> Generator[str]:
        """Create a temporary socket path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield str(Path(tmpdir) / "test.sock")

    def _run_mock_server(
        self,
        socket_path: str,
        response: dict | None = None,
        raw_response: bytes | None = None,
        close_immediately: bool = False,
        chunk_size: int | None = None,
    ) -> threading.Event:
        """Run a mock Unix socket server that sends a response.

        Parameter priority (evaluated in order):
            1. close_immediately: If True, close connection without sending anything.
            2. raw_response: If provided, send these raw bytes.
            3. response: If provided, JSON-encode and send as bytes.
            4. None of the above: Close connection without sending data.

        The chunk_size parameter only affects how the chosen response is sent;
        it does not influence which response is selected.

        Args:
            socket_path: Path to the Unix socket.
            response: Dict to JSON-encode and send.
            raw_response: Raw bytes to send (takes precedence over response).
            close_immediately: Close connection without sending response.
            chunk_size: If set, send response in chunks of this size.
                Must be a positive integer if provided.

        Returns:
            Event that is set when server is ready.

        Raises:
            ValueError: If chunk_size is provided but is not a positive integer.
        """
        if chunk_size is not None and (
            isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0
        ):
            raise ValueError(f"chunk_size must be a positive integer, got {chunk_size!r}")

        ready_event = threading.Event()

        def server_thread() -> None:
            server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server_sock.bind(socket_path)
            server_sock.listen(1)
            server_sock.settimeout(5)
            ready_event.set()

            try:
                conn, _ = server_sock.accept()
                if close_immediately:
                    conn.close()
                else:
                    # Read request
                    conn.recv(4096)
                    # Determine what to send
                    if raw_response is not None:
                        data = raw_response
                    elif response is not None:
                        data = json.dumps(response).encode() + b"\n"
                    else:
                        data = None

                    if data is not None:
                        if chunk_size is not None:
                            # Send in chunks to simulate partial reads
                            for i in range(0, len(data), chunk_size):
                                conn.sendall(data[i : i + chunk_size])
                        else:
                            conn.sendall(data)
                    conn.close()
            except TimeoutError:
                pass
            finally:
                server_sock.close()

        thread = threading.Thread(target=server_thread, daemon=True)
        thread.start()
        ready_event.wait(timeout=5)
        return ready_event

    def test_healthy_response_returns_zero(
        self, socket_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Return 0 when server responds with healthy status."""
        monkeypatch.setenv("MCP_BRIDGE_SOCKET", socket_path)

        response = {"status": "success", "result": {"status": "ok"}}
        self._run_mock_server(socket_path, response)

        result = healthcheck.main()

        assert result == 0

    def test_unhealthy_response_returns_one(
        self, socket_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Return 1 when server responds with unhealthy status."""
        monkeypatch.setenv("MCP_BRIDGE_SOCKET", socket_path)

        response = {"status": "success", "result": {"status": "degraded"}}
        self._run_mock_server(socket_path, response)

        result = healthcheck.main()

        assert result == 1

    def test_error_status_returns_one(
        self, socket_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Return 1 when server responds with error status."""
        monkeypatch.setenv("MCP_BRIDGE_SOCKET", socket_path)

        response = {"status": "error", "error": {"message": "error"}}
        self._run_mock_server(socket_path, response)

        result = healthcheck.main()

        assert result == 1

    def test_connection_refused_returns_one(
        self, socket_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Return 1 when socket does not exist."""
        monkeypatch.setenv("MCP_BRIDGE_SOCKET", socket_path)

        # No server running, socket does not exist

        result = healthcheck.main()

        assert result == 1

    def test_default_socket_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Use default socket path when env var not set."""
        monkeypatch.delenv("MCP_BRIDGE_SOCKET", raising=False)

        # Will fail to connect, but tests the default path is used
        result = healthcheck.main()

        assert result == 1

    def test_invalid_json_response_returns_one(
        self, socket_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Return 1 when server sends invalid JSON."""
        monkeypatch.setenv("MCP_BRIDGE_SOCKET", socket_path)

        self._run_mock_server(socket_path, raw_response=b"not valid json\n")

        result = healthcheck.main()

        assert result == 1

    def test_null_result_returns_one(
        self, socket_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Return 1 when server responds with null result (no AttributeError)."""
        monkeypatch.setenv("MCP_BRIDGE_SOCKET", socket_path)

        response = {"status": "success", "result": None}
        self._run_mock_server(socket_path, response)

        result = healthcheck.main()

        assert result == 1

    def test_partial_read_handles_chunked_response(
        self, socket_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Return 0 when server sends response in multiple chunks."""
        monkeypatch.setenv("MCP_BRIDGE_SOCKET", socket_path)

        response = {"status": "success", "result": {"status": "ok"}}
        self._run_mock_server(socket_path, response, chunk_size=10)

        result = healthcheck.main()

        assert result == 0

    @pytest.mark.parametrize("invalid_chunk_size", [True, False])
    def test_chunk_size_rejects_booleans(self, socket_path: str, invalid_chunk_size: bool) -> None:
        """Raise ValueError when chunk_size is a boolean."""
        response = {"status": "success", "result": {"status": "ok"}}

        with pytest.raises(ValueError, match="chunk_size must be a positive integer"):
            self._run_mock_server(socket_path, response, chunk_size=invalid_chunk_size)

    def test_response_exceeds_max_size_returns_one(
        self, socket_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Return 1 when response exceeds maximum buffer size."""
        monkeypatch.setenv("MCP_BRIDGE_SOCKET", socket_path)
        # Set a small max response size for testing
        monkeypatch.setattr(healthcheck, "MAX_RESPONSE_SIZE", 100)

        # Send a response larger than the limit without a newline
        large_response = b"x" * 200
        self._run_mock_server(socket_path, raw_response=large_response)

        result = healthcheck.main()

        assert result == 1
