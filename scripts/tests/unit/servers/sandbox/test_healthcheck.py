"""Tests for Docker healthcheck script for Sandbox Server."""

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

from scripts.servers.sandbox import healthcheck


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
        send_partial_no_newline: bool = False,
    ) -> threading.Event:
        """Run a mock Unix socket server that sends a response.

        Parameter priority (evaluated in order):
            1. close_immediately: If True, close connection without sending anything.
            2. send_partial_no_newline: Send partial data without newline, then close.
            3. raw_response: If provided, send these raw bytes.
            4. response: If provided, JSON-encode and send as bytes.
            5. None of the above: Close connection without sending data.

        Args:
            socket_path: Path to the Unix socket.
            response: Dict to JSON-encode and send.
            raw_response: Raw bytes to send (takes precedence over response).
            close_immediately: Close connection without sending response.
            chunk_size: If set, send response in chunks of this size.
            send_partial_no_newline: Send partial data without newline (simulates EOF).

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
                elif send_partial_no_newline:
                    # Read request
                    conn.recv(4096)
                    # Send partial data without newline, then close
                    conn.sendall(b'{"status":"succ')
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
        """Return 0 when server responds with success status."""
        monkeypatch.setenv("SANDBOX_SOCKET_PATH", socket_path)

        response = {"status": "success"}
        self._run_mock_server(socket_path, response)

        result = healthcheck.main()

        assert result == 0

    def test_unhealthy_response_returns_one(
        self, socket_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Return 1 when server responds with non-success status."""
        monkeypatch.setenv("SANDBOX_SOCKET_PATH", socket_path)

        response = {"status": "error", "error": "something went wrong"}
        self._run_mock_server(socket_path, response)

        result = healthcheck.main()

        assert result == 1

    def test_connection_refused_returns_one(
        self, socket_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Return 1 when socket does not exist."""
        monkeypatch.setenv("SANDBOX_SOCKET_PATH", socket_path)

        # No server running, socket does not exist
        result = healthcheck.main()

        assert result == 1

    def test_default_socket_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Use default socket path when env var not set."""
        monkeypatch.delenv("SANDBOX_SOCKET_PATH", raising=False)

        # Will fail to connect, but tests the default path is used
        result = healthcheck.main()

        assert result == 1

    def test_invalid_json_response_returns_one(
        self, socket_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Return 1 when server sends invalid JSON."""
        monkeypatch.setenv("SANDBOX_SOCKET_PATH", socket_path)

        self._run_mock_server(socket_path, raw_response=b"not valid json\n")

        result = healthcheck.main()

        assert result == 1

    def test_partial_read_handles_chunked_response(
        self, socket_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Return 0 when server sends response in multiple chunks."""
        monkeypatch.setenv("SANDBOX_SOCKET_PATH", socket_path)

        response = {"status": "success"}
        self._run_mock_server(socket_path, response, chunk_size=10)

        result = healthcheck.main()

        assert result == 0

    def test_incomplete_response_eof_before_newline_returns_one(
        self, socket_path: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Return 1 when server sends partial data without newline (EOF before newline).

        This tests the fix for the issue where recv returns b'' (EOF) before
        a newline is received, which would previously cause an incomplete
        JSON parse attempt.
        """
        monkeypatch.setenv("SANDBOX_SOCKET_PATH", socket_path)

        self._run_mock_server(socket_path, send_partial_no_newline=True)

        result = healthcheck.main()

        assert result == 1
        captured = capsys.readouterr()
        assert "incomplete response" in captured.err
        assert "EOF before newline" in captured.err
        # Verify partial data is included for debugging
        assert '{"status":"succ' in captured.err

    def test_close_immediately_returns_one(
        self, socket_path: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Return 1 when server closes connection immediately.

        When connection is closed immediately, it typically results in a
        connection reset error rather than a clean EOF.
        """
        monkeypatch.setenv("SANDBOX_SOCKET_PATH", socket_path)

        self._run_mock_server(socket_path, close_immediately=True)

        result = healthcheck.main()

        assert result == 1
        captured = capsys.readouterr()
        assert "healthcheck failed" in captured.err
