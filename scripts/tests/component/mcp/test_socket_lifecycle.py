"""Tests for MCP Socket Server lifecycle handling (Category F).

This module tests the socket file lifecycle including:
- Server creates parent directory if missing
- Server unlinks stale socket before binding (handles restart after crash)
- Server sets socket permissions to 0o777 for cross-user access
- Server cleans up socket file on graceful shutdown
- Server can restart multiple times without "Address already in use" errors

These tests verify the server handles socket file lifecycle correctly for
reliable startup/restart, matching patterns from scripts/servers/sandbox/server.py.
"""

from __future__ import annotations

import os
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest


class TestSocketFileLifecycle:
    """Tests for socket file lifecycle handling.

    These tests verify that the server correctly:
    - Creates parent directories if missing
    - Unlinks stale socket files before binding
    - Sets correct permissions on socket file
    - Cleans up socket file on shutdown
    - Handles restart scenarios without errors
    """

    @pytest.fixture
    def server_script(self) -> str:
        """Path to the socket server script."""
        return str(
            Path(__file__).parent.parent.parent.parent / "servers" / "mcp" / "server_impl.py"
        )

    @pytest.fixture
    def socket_dir(self, tmp_path: Path) -> Path:
        """Provide a temporary directory for socket files."""
        sock_dir = tmp_path / "mcp-sockets"
        # Don't create it - let tests verify server creates it
        return sock_dir

    def _start_server(
        self, server_script: str, socket_path: str, timeout: float = 10.0
    ) -> subprocess.Popen:
        """Start server and wait until it's ready."""
        # Include PYTHONPATH so server_impl.py can import from scripts.*
        # Go up 4 levels: mcp/ -> component/ -> tests/ -> scripts/ -> repo root
        repo_root = str(Path(__file__).resolve().parents[4])
        existing_pythonpath = os.environ.get("PYTHONPATH", "")
        pythonpath = f"{repo_root}:{existing_pythonpath}" if existing_pythonpath else repo_root

        proc = subprocess.Popen(
            [sys.executable, server_script],
            env={
                **os.environ,
                "MCP_BRIDGE_SOCKET": socket_path,
                "PYTHONPATH": pythonpath,
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for server to be ready
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if Path(socket_path).exists():
                try:
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                        sock.settimeout(1.0)
                        sock.connect(socket_path)
                        sock.sendall(b'{"method": "health", "id": "startup-check"}\n')
                        response = sock.recv(4096)
                        if response and b'"status"' in response:
                            return proc
                except (ConnectionRefusedError, FileNotFoundError, TimeoutError):
                    pass
            time.sleep(0.05)

        # Server didn't start - clean up and fail
        proc.terminate()
        proc.wait(timeout=5)
        pytest.fail(f"Server did not become ready within {timeout}s.")

    def _stop_server(self, proc: subprocess.Popen) -> None:
        """Stop server gracefully with SIGTERM."""
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    def test_server_creates_parent_directory(self, server_script: str, socket_dir: Path) -> None:
        """Test server creates parent directory if it doesn't exist."""
        socket_path = str(socket_dir / "mcp-bridge.sock")

        # Verify directory doesn't exist
        assert not socket_dir.exists()

        proc = self._start_server(server_script, socket_path)
        try:
            # Verify directory was created
            assert socket_dir.exists()
            assert socket_dir.is_dir()
        finally:
            self._stop_server(proc)

    def test_server_unlinks_stale_socket(self, server_script: str, socket_dir: Path) -> None:
        """Test server unlinks stale socket file from previous run."""
        socket_dir.mkdir(parents=True)
        socket_path = str(socket_dir / "mcp-bridge.sock")

        # Create a stale socket file (simulating crashed server)
        stale_socket = socket_dir / "mcp-bridge.sock"
        stale_socket.touch()

        # Start server - should unlink stale socket and bind successfully
        proc = self._start_server(server_script, socket_path)
        try:
            # Verify socket is now a real socket, not a regular file
            assert Path(socket_path).exists()
            mode = os.stat(socket_path).st_mode
            assert stat.S_ISSOCK(mode), "Socket file should be a Unix socket"
        finally:
            self._stop_server(proc)

    def test_server_sets_socket_permissions(self, server_script: str, socket_dir: Path) -> None:
        """Test server sets socket file permissions to 0o777."""
        socket_dir.mkdir(parents=True)
        socket_path = str(socket_dir / "mcp-bridge.sock")

        proc = self._start_server(server_script, socket_path)
        try:
            # Verify socket permissions
            mode = os.stat(socket_path).st_mode
            perms = stat.S_IMODE(mode)
            assert perms == 0o777, f"Socket permissions should be 0o777, got {oct(perms)}"
        finally:
            self._stop_server(proc)

    def test_server_cleans_up_socket_on_shutdown(
        self, server_script: str, socket_dir: Path
    ) -> None:
        """Test server removes socket file on graceful shutdown."""
        socket_dir.mkdir(parents=True)
        socket_path = str(socket_dir / "mcp-bridge.sock")

        proc = self._start_server(server_script, socket_path)

        # Verify socket exists while running
        assert Path(socket_path).exists()

        # Stop server gracefully
        self._stop_server(proc)

        # Poll for socket removal with timeout
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if not Path(socket_path).exists():
                return  # Success
            time.sleep(0.05)

        pytest.fail("Socket file should be removed on shutdown")

    def test_server_restart_with_stale_socket(self, server_script: str, socket_dir: Path) -> None:
        """Test server can restart when previous socket file exists."""
        socket_dir.mkdir(parents=True)
        socket_path = str(socket_dir / "mcp-bridge.sock")

        # Start and stop server (simulating previous run)
        proc1 = self._start_server(server_script, socket_path)
        # Kill without graceful shutdown to leave stale socket
        proc1.kill()
        proc1.wait(timeout=5)

        # Socket file may or may not exist (depends on timing)
        # Create one to ensure test covers stale socket case
        if not Path(socket_path).exists():
            Path(socket_path).touch()

        # Start server again - should work despite stale socket
        proc2 = self._start_server(server_script, socket_path)
        try:
            # Verify server is working
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(5.0)
                sock.connect(socket_path)
                sock.sendall(b'{"method": "health", "id": "restart-check"}\n')
                response = sock.recv(4096)
                assert b'"status": "success"' in response or b'"status":"success"' in response
        finally:
            self._stop_server(proc2)

    def test_multiple_rapid_restarts(self, server_script: str, socket_dir: Path) -> None:
        """Test server can be restarted multiple times without Address already in use errors."""
        socket_dir.mkdir(parents=True)
        socket_path = str(socket_dir / "mcp-bridge.sock")

        for i in range(3):
            proc = self._start_server(server_script, socket_path)
            try:
                # Verify server is working
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.settimeout(5.0)
                    sock.connect(socket_path)
                    sock.sendall(f'{{"method": "health", "id": "restart-{i}"}}\n'.encode())
                    response = sock.recv(4096)
                    assert b'"status"' in response
            finally:
                self._stop_server(proc)

    def test_parent_directory_permissions_set(self, server_script: str, socket_dir: Path) -> None:
        """Test server sets parent directory permissions to 0o777."""
        socket_path = str(socket_dir / "mcp-bridge.sock")

        # Verify directory doesn't exist
        assert not socket_dir.exists()

        proc = self._start_server(server_script, socket_path)
        try:
            # Verify parent directory permissions
            mode = os.stat(socket_dir).st_mode
            perms = stat.S_IMODE(mode)
            assert perms == 0o777, f"Parent directory permissions should be 0o777, got {oct(perms)}"
        finally:
            self._stop_server(proc)

    def test_nested_directory_creation(self, server_script: str, tmp_path: Path) -> None:
        """Test server creates nested parent directories."""
        nested_dir = tmp_path / "deep" / "nested" / "dir"
        socket_path = str(nested_dir / "mcp-bridge.sock")

        # Verify nested directory doesn't exist
        assert not nested_dir.exists()

        proc = self._start_server(server_script, socket_path)
        try:
            # Verify all directories were created
            assert nested_dir.exists()
            assert Path(socket_path).exists()
        finally:
            self._stop_server(proc)
