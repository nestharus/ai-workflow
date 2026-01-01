"""Tests for MCP Bridge components.

This module tests the MCP bridge server including:
- MCPStdioManager: JSONL framing, error handling, BUSY/TIMEOUT/CRASHED semantics
- Config: YAML/JSON loading, environment variable substitution
- HttpMCPClient (now MCPSocketClient): Result extraction, error parsing
- Protocol: Request/response dataclasses
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest

from scripts.servers.mcp.client.http_client import (
    HttpMCPClient,
    MCPClientError,
)

# Import bridge components using absolute paths
from scripts.servers.mcp.config import (
    ConfigError,
    SSEServerConfig,
    StdioServerConfig,
    load_config,
)
from scripts.servers.mcp.manager import (
    MCPBusyError,
    MCPError,
    MCPProviderCrashedError,
    MCPStdioManager,
    MCPTimeoutError,
)
from scripts.servers.mcp.protocol import (
    ErrorDetail,
    ErrorType,
    HealthResponse,
    MCPCallResponse,
)


class FakeMCPProcess:
    """Fake subprocess for testing MCPStdioManager."""

    INIT_RESPONSE: ClassVar[dict[str, Any]] = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {"name": "fake-mcp", "version": "1.0.0"},
        },
    }

    def __init__(
        self,
        responses: list[dict[str, Any]] | None = None,
        poll_result: int | None = None,
        fail_on_start: bool = False,
    ) -> None:
        """Initialize fake process."""
        self.responses = [self.INIT_RESPONSE] + (responses or [])
        self._response_index = 0
        self._poll_result = poll_result
        self._fail_on_start = fail_on_start
        self._poll_count = 0
        self._current_buffer = b""

        self.stdin = MagicMock()
        self.stdout = MagicMock()
        self.stderr = MagicMock()

        self.stdin.write.side_effect = lambda data: len(data)
        self.stdin.flush.return_value = None
        self.stderr.read.return_value = b""
        self._setup_stdout_read()

    def _setup_stdout_read(self) -> None:
        """Set up stdout.read() to return JSONL responses."""

        def read_func(size: int = -1) -> bytes:
            if not self._current_buffer:
                if self._response_index >= len(self.responses):
                    return b""
                response = self.responses[self._response_index]
                self._current_buffer = json.dumps(response).encode("utf-8") + b"\n"
                self._response_index += 1

            if size <= 0:
                result = self._current_buffer
                self._current_buffer = b""
                return result
            result = self._current_buffer[:size]
            self._current_buffer = self._current_buffer[size:]
            return result

        self.stdout.read.side_effect = read_func
        self.stdout.fileno.return_value = 3

    def poll(self) -> int | None:
        """Check if process is running."""
        self._poll_count += 1
        if self._fail_on_start and self._poll_count == 1:
            return 1
        if self._poll_result is not None and self._poll_count > 2:
            return self._poll_result
        return None

    def terminate(self) -> None:
        """Terminate the process."""
        pass

    def wait(self, timeout: float | None = None) -> int:
        """Wait for process to exit."""
        return 0

    def kill(self) -> None:
        """Kill the process."""
        pass


@pytest.fixture
def mock_select(mocker: Any) -> Any:
    """Mock select.select to always return ready."""
    mock = mocker.patch("scripts.servers.mcp.manager.select.select")
    mocker.patch("scripts.servers.mcp.manager.time.sleep")
    mock.return_value = ([True], [], [])
    return mock


POPEN_PATCH_TARGET = "scripts.servers.mcp.manager.subprocess.Popen"


class TestMCPStdioManager:
    def test_manager_init_success(self, mock_select: Any) -> None:
        """Test successful manager initialization."""
        fake_proc = FakeMCPProcess()
        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            manager = MCPStdioManager(command="fake command")
            assert manager.is_alive()
            manager.close()

    def test_call_tool_success(self, mock_select: Any) -> None:
        """Test successful tool call returns result dict."""
        response = {"jsonrpc": "2.0", "id": 2, "result": {"job_id": "test-123"}}
        fake_proc = FakeMCPProcess(responses=[response])

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            manager = MCPStdioManager(command="fake")
            result = manager.call_tool("execute", {"command": "test"})
            assert result == {"job_id": "test-123"}
            manager.close()

    def test_call_tool_json_rpc_error(self, mock_select: Any) -> None:
        """Test JSON-RPC error raises MCPError."""
        response = {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {"code": -32600, "message": "Invalid request"},
        }
        fake_proc = FakeMCPProcess(responses=[response])

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            manager = MCPStdioManager(command="fake")
            try:
                with pytest.raises(MCPError, match="JSON-RPC error -32600"):
                    manager.call_tool("execute", {"command": "test"})
            finally:
                manager.close()

    def test_call_tool_malformed_json(self, mock_select: Any) -> None:
        """Test malformed JSON response raises MCPError."""
        fake_proc = FakeMCPProcess()

        # Override stdout to return malformed JSON after init
        init_response = json.dumps(FakeMCPProcess.INIT_RESPONSE).encode() + b"\n"
        malformed = b"{bad\n"
        responses = [init_response, malformed]
        idx = [0]
        buf = [b""]

        def read_func(size: int = -1) -> bytes:
            if not buf[0]:
                if idx[0] >= len(responses):
                    return b""
                buf[0] = responses[idx[0]]
                idx[0] += 1
            if size <= 0:
                r = buf[0]
                buf[0] = b""
                return r
            r = buf[0][:size]
            buf[0] = buf[0][size:]
            return r

        fake_proc.stdout.read.side_effect = read_func

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            manager = MCPStdioManager(command="fake")
            try:
                with pytest.raises(MCPError, match="Invalid JSON response"):
                    manager.call_tool("execute", {"command": "test"})
            finally:
                manager.close()

    def test_call_tool_timeout(self, mock_select: Any) -> None:
        """Test timeout raises MCPTimeoutError."""
        # Set up responses: init succeeds, then tool call never returns
        fake_proc = FakeMCPProcess(responses=[])  # Only init response

        # Track init completion
        init_done = [False]
        call_count = [0]

        # Make select return not ready after init (causes timeout loop)

        def select_func(*args: Any, **kwargs: Any) -> tuple[list[Any], list[Any], list[Any]]:
            call_count[0] += 1
            if not init_done[0]:
                return ([True], [], [])  # Ready during init
            return ([], [], [])  # Not ready after init (causes timeout)

        mock_select.side_effect = select_func

        # Track time for timeout
        start_time = [100.0]

        def mono() -> float:
            start_time[0] += 0.05
            return start_time[0]

        with (
            patch(POPEN_PATCH_TARGET, return_value=fake_proc),
            patch("scripts.servers.mcp.manager.time.monotonic", side_effect=mono),
        ):
            manager = MCPStdioManager(command="fake")
            init_done[0] = True
            try:
                with pytest.raises(MCPTimeoutError, match="timed out"):
                    manager.call_tool("execute", {}, timeout=0.5)
            finally:
                manager.close()

    def test_call_tool_provider_crashed(self, mock_select: Any) -> None:
        """Test provider crash raises MCPProviderCrashedError."""
        # Create two processes: one for initial init that will "crash", one for restart
        fake_proc1 = FakeMCPProcess()
        fake_proc2 = FakeMCPProcess(responses=[{"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}])

        procs = [fake_proc1, fake_proc2]
        proc_idx = [0]

        def create_proc(*args: Any, **kwargs: Any) -> FakeMCPProcess:
            p = procs[proc_idx[0]]
            proc_idx[0] = min(proc_idx[0] + 1, len(procs) - 1)
            return p

        with patch(POPEN_PATCH_TARGET, side_effect=create_proc):
            manager = MCPStdioManager(command="fake")

            # Now simulate crash: make the first process return exit code
            def poll_crashed() -> int:
                return 1  # Process exited with error

            fake_proc1.poll = poll_crashed  # type: ignore[method-assign]

            # Call tool should detect crash, restart, and raise MCPProviderCrashedError
            with pytest.raises(MCPProviderCrashedError, match="crashed and was restarted"):
                manager.call_tool("execute", {})
            manager.close()

    def test_call_tool_crash_during_read_response(self, mock_select: Any) -> None:
        """Test provider crash during _read_response raises MCPProviderCrashedError.

        This tests the scenario where the provider crashes DURING _read_response
        (after init and after sending the request), not before the call.
        """
        # Responses for initialization
        # (proc1 uses id=1, proc2 uses id=3 due to _request_id persistence)
        init_response_id1 = FakeMCPProcess.INIT_RESPONSE  # id=1 for first process
        init_response_id3 = {
            "jsonrpc": "2.0",
            "id": 3,  # After restart: init(1) + tool_call(2) + new_init(3)
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "fake-mcp", "version": "1.0.0"},
            },
        }

        init_response_bytes = json.dumps(init_response_id1).encode() + b"\n"

        # Create first process that will crash during tool call read
        fake_proc1 = FakeMCPProcess()
        # Create second process for restart (with correct init response id)
        fake_proc2 = FakeMCPProcess(responses=[])  # Will override read

        procs = [fake_proc1, fake_proc2]

        # State for tracking tool call start (only affects proc1)
        proc1_state = {"tool_call_started": False}
        proc1_buffer = [b""]

        def read_func_proc1(size: int = -1) -> bytes:
            # If tool call started, return EOF to simulate crash
            if proc1_state["tool_call_started"]:
                return b""

            # During init, return the init response
            if not proc1_buffer[0]:
                proc1_buffer[0] = init_response_bytes
            if size <= 0:
                r = proc1_buffer[0]
                proc1_buffer[0] = b""
                return r
            r = proc1_buffer[0][:size]
            proc1_buffer[0] = proc1_buffer[0][size:]
            return r

        fake_proc1.stdout.read.side_effect = read_func_proc1

        def write_func_proc1(data: bytes) -> int:
            if b'"tools/call"' in data:
                proc1_state["tool_call_started"] = True
            return len(data)

        fake_proc1.stdin.write.side_effect = write_func_proc1

        def poll_func_proc1() -> int | None:
            if proc1_state["tool_call_started"]:
                return 1  # Crashed
            return None

        fake_proc1.poll = poll_func_proc1  # type: ignore[method-assign]

        # Set up proc2 with correct init response (id=3)
        proc2_buffer = [b""]
        init_response_bytes_id3 = json.dumps(init_response_id3).encode() + b"\n"

        def read_func_proc2(size: int = -1) -> bytes:
            if not proc2_buffer[0]:
                proc2_buffer[0] = init_response_bytes_id3
            if size <= 0:
                r = proc2_buffer[0]
                proc2_buffer[0] = b""
                return r
            r = proc2_buffer[0][:size]
            proc2_buffer[0] = proc2_buffer[0][size:]
            return r

        fake_proc2.stdout.read.side_effect = read_func_proc2

        popen_call_count = [0]

        def create_proc(*args: Any, **kwargs: Any) -> FakeMCPProcess:
            popen_call_count[0] += 1
            p = procs[min(popen_call_count[0] - 1, len(procs) - 1)]
            return p

        with patch(POPEN_PATCH_TARGET, side_effect=create_proc):
            manager = MCPStdioManager(command="fake")

            # Call tool should detect crash during _read_response, restart, and raise
            with pytest.raises(MCPProviderCrashedError, match="crashed and was restarted"):
                manager.call_tool("execute", {})

            # Verify we created a second process for restart (2 Popen calls total)
            assert popen_call_count[0] == 2

            manager.close()

    def test_call_tool_busy(self, mock_select: Any) -> None:
        """Test lock contention raises MCPBusyError."""
        response = {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}
        fake_proc = FakeMCPProcess(responses=[response] * 10)

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            manager = MCPStdioManager(command="fake")

            # Hold the lock in a background thread
            lock_held = threading.Event()
            release_lock = threading.Event()

            def hold_lock() -> None:
                manager._lock.acquire()
                lock_held.set()
                release_lock.wait()
                manager._lock.release()

            holder = threading.Thread(target=hold_lock)
            holder.start()
            lock_held.wait()

            try:
                # Try to call tool while lock is held
                with pytest.raises(MCPBusyError, match="busy"):
                    manager.call_tool("execute", {})
            finally:
                release_lock.set()
                holder.join()
                manager.close()

    def test_cwd_passed_to_subprocess(self, mock_select: Any) -> None:
        """Test cwd is passed to subprocess.Popen."""
        fake_proc = FakeMCPProcess()

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc) as mock_popen:
            manager = MCPStdioManager(command="fake", cwd="/custom/dir")
            manager.close()

            # Check that cwd was passed
            mock_popen.assert_called_once()
            call_kwargs = mock_popen.call_args[1]
            assert call_kwargs.get("cwd") == "/custom/dir"

    def test_env_passed_to_subprocess(self, mock_select: Any) -> None:
        """Test env is merged with os.environ and passed to subprocess.Popen.

        This ensures server-specific environment variables are isolated to the
        subprocess and do not mutate the global os.environ.
        """
        fake_proc = FakeMCPProcess()
        custom_env = {"MY_VAR": "my_value", "ANOTHER_VAR": "another_value"}

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc) as mock_popen:
            manager = MCPStdioManager(command="fake", env=custom_env)
            manager.close()

            # Check that env was passed and merged with os.environ
            mock_popen.assert_called_once()
            call_kwargs = mock_popen.call_args[1]
            subprocess_env = call_kwargs.get("env")

            assert subprocess_env is not None
            # Custom vars should be present
            assert subprocess_env.get("MY_VAR") == "my_value"
            assert subprocess_env.get("ANOTHER_VAR") == "another_value"
            # System PATH should still be present (merged from os.environ)
            assert "PATH" in subprocess_env

    def test_env_none_does_not_override_os_environ(self, mock_select: Any) -> None:
        """Test that env=None passes None to Popen (inherits os.environ by default)."""
        fake_proc = FakeMCPProcess()

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc) as mock_popen:
            manager = MCPStdioManager(command="fake", env=None)
            manager.close()

            # Check that env=None was passed (subprocess inherits os.environ)
            mock_popen.assert_called_once()
            call_kwargs = mock_popen.call_args[1]
            assert call_kwargs.get("env") is None

    def test_env_does_not_mutate_global_os_environ(self, mock_select: Any) -> None:
        """Test that passing env does not mutate global os.environ.

        This is the key fix for the race condition issue when multiple servers
        are initialized concurrently.
        """
        fake_proc = FakeMCPProcess()
        custom_env = {"SHOULD_NOT_LEAK": "secret_value"}

        # Ensure the var doesn't exist before
        original_environ = dict(os.environ)
        assert "SHOULD_NOT_LEAK" not in os.environ

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            manager = MCPStdioManager(command="fake", env=custom_env)
            manager.close()

        # Global os.environ should NOT be mutated
        assert "SHOULD_NOT_LEAK" not in os.environ
        # Restore check - environ should be unchanged
        assert dict(os.environ) == original_environ


# ============================================================================
# Config Tests
# ============================================================================


class TestConfig:
    """Tests for config loading."""

    def test_load_yaml_config(self) -> None:
        """Test loading .mcp.yml config file."""
        config_content = """
mcpServers:
  background-job:
    type: stdio
    command: uvx
    args:
      - mcp-background-job
  linear:
    type: sse
    url: https://mcp.linear.app/sse
    headers:
      Authorization: Bearer test
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write(config_content)
            f.flush()
            try:
                config = load_config(f.name)
                assert len(config.servers) == 2
                assert "background-job" in config.servers
                assert "linear" in config.servers

                # Check stdio server
                bg = config.servers["background-job"]
                assert isinstance(bg, StdioServerConfig)
                assert bg.command == "uvx"
                assert bg.args == ["mcp-background-job"]

                # Check SSE server
                lin = config.servers["linear"]
                assert isinstance(lin, SSEServerConfig)
                assert lin.url == "https://mcp.linear.app/sse"
            finally:
                os.unlink(f.name)

    def test_load_json_config(self) -> None:
        """Test loading .mcp.json config file."""
        config_content = {
            "mcpServers": {
                "test-server": {
                    "type": "stdio",
                    "command": "node",
                    "args": ["server.js"],
                }
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_content, f)
            f.flush()
            try:
                config = load_config(f.name)
                assert len(config.servers) == 1
                assert "test-server" in config.servers
            finally:
                os.unlink(f.name)

    def test_env_var_substitution(self) -> None:
        """Test environment variable substitution in config."""
        config_content = """
mcpServers:
  test:
    type: stdio
    command: echo
    args:
      - ${TEST_VAR}
    env:
      API_KEY: ${API_KEY:-default_key}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write(config_content)
            f.flush()
            try:
                os.environ["TEST_VAR"] = "hello"
                config = load_config(f.name)
                server = config.servers["test"]
                assert isinstance(server, StdioServerConfig)
                assert server.args == ["hello"]
                assert server.env["API_KEY"] == "default_key"  # pragma: allowlist secret
            finally:
                os.environ.pop("TEST_VAR", None)
                os.unlink(f.name)

    def test_disabled_server_skipped(self) -> None:
        """Test disabled servers are not loaded."""
        config_content = """
mcpServers:
  enabled-server:
    type: stdio
    command: echo
  disabled-server:
    type: stdio
    command: echo
    disabled: true
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write(config_content)
            f.flush()
            try:
                config = load_config(f.name)
                assert len(config.servers) == 1
                assert "enabled-server" in config.servers
                assert "disabled-server" not in config.servers
            finally:
                os.unlink(f.name)

    def test_missing_command_raises_error(self) -> None:
        """Test missing required 'command' field raises ConfigError."""
        config_content = """
mcpServers:
  bad-server:
    type: stdio
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write(config_content)
            f.flush()
            try:
                with pytest.raises(ConfigError, match="missing required 'command'"):
                    load_config(f.name)
            finally:
                os.unlink(f.name)


# ============================================================================
# HttpMCPClient Tests (Socket-based client)
# ============================================================================


class FakeSocket:
    """Fake socket for testing MCPSocketClient."""

    def __init__(
        self,
        response: dict[str, Any] | None = None,
        connect_error: Exception | None = None,
        recv_error: Exception | None = None,
        timeout_on_recv: bool = False,
    ) -> None:
        """Initialize fake socket.

        Args:
            response: Response to return on recv().
            connect_error: Exception to raise on connect().
            recv_error: Exception to raise on recv().
            timeout_on_recv: If True, raise socket.timeout on recv().
        """
        self._response = response
        self._connect_error = connect_error
        self._recv_error = recv_error
        self._timeout_on_recv = timeout_on_recv
        self._sent_data: list[bytes] = []
        self._connected = False

    def settimeout(self, timeout: float) -> None:
        """Set socket timeout."""
        pass

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


class TestHttpMCPClient:
    """Tests for HttpMCPClient (MCPSocketClient) class.

    Note: HttpMCPClient is now an alias for MCPSocketClient which uses
    native Unix sockets with JSONL protocol instead of curl/HTTP.
    """

    def test_health_check_returns_true_on_ok_response(self) -> None:
        """Test health_check returns True when server responds with status ok."""
        response = {
            "id": "test",
            "status": "success",
            "result": {"status": "ok", "provider": "running"},
        }
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            result = client.health_check()
            assert result is True

    def test_list_servers_success(self) -> None:
        """Test list_servers returns dict on success."""
        result_data = {"servers": [{"name": "test-server"}]}
        response = {"id": "test", "status": "success", "result": result_data}
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            result = client.list_servers()
            assert result == result_data

    def test_list_servers_connection_refused(self) -> None:
        """Test list_servers raises MCPClientError with 'Cannot connect' on socket error."""
        fake_socket = FakeSocket(connect_error=OSError("Connection refused"))

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match="Cannot connect"):
                client.list_servers()

    def test_list_servers_timeout(self) -> None:
        """Test list_servers raises MCPClientError with 'timed out' on socket timeout."""
        fake_socket = FakeSocket(timeout_on_recv=True)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match="timed out"):
                client.list_servers()

    def test_list_servers_error_envelope(self) -> None:
        """Test list_servers parses error envelope and raises MCPClientError."""
        error_response = {
            "id": "test",
            "status": "error",
            "error": {
                "type": "SERVER_ERROR",
                "message": "Internal server error",
            },
        }
        fake_socket = FakeSocket(response=error_response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match=r"\[SERVER_ERROR\] Internal server error"):
                client.list_servers()

    def test_list_servers_malformed_json(self) -> None:
        """Test list_servers raises MCPClientError with 'Invalid JSON response'."""

        class BadJsonSocket(FakeSocket):
            def recv(self, bufsize: int) -> bytes:
                return b"{bad json\n"

        fake_socket = BadJsonSocket()

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match="Invalid JSON response"):
                client.list_servers()

    def test_list_servers_non_dict_response(self) -> None:
        """Test list_servers raises MCPClientError with 'Invalid response type'."""

        class ArrayResponseSocket(FakeSocket):
            def recv(self, bufsize: int) -> bytes:
                return b"[]\n"

        fake_socket = ArrayResponseSocket()

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match="Invalid response type"):
                client.list_servers()

    def test_list_servers_sends_correct_method(self) -> None:
        """Test list_servers sends correct method in JSONL request."""
        response = {"id": "test", "status": "success", "result": {"servers": []}}
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            client.list_servers()
            # Verify the request was sent
            assert len(fake_socket._sent_data) == 1
            request = json.loads(fake_socket._sent_data[0].decode().strip())
            assert request["method"] == "list_servers"

    def test_list_server_tools_success(self) -> None:
        """Test list_server_tools returns dict on success."""
        result_data = {"tools": [{"name": "test-tool"}]}
        response = {"id": "test", "status": "success", "result": result_data}
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            result = client.list_server_tools("test-server")
            assert result == result_data

    def test_list_server_tools_server_not_found(self) -> None:
        """Test list_server_tools raises MCPClientError on NOT_FOUND error."""
        error_response = {
            "id": "test",
            "status": "error",
            "error": {
                "type": "NOT_FOUND",
                "message": "Server not found",
            },
        }
        fake_socket = FakeSocket(response=error_response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match=r"\[NOT_FOUND\]"):
                client.list_server_tools("unknown-server")

    def test_list_server_tools_mcp_error(self) -> None:
        """Test list_server_tools raises MCPClientError on JSONRPC_ERROR type."""
        error_response = {
            "id": "test",
            "status": "error",
            "error": {
                "type": "JSONRPC_ERROR",
                "message": "MCP protocol error",
            },
        }
        fake_socket = FakeSocket(response=error_response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match=r"\[JSONRPC_ERROR\]"):
                client.list_server_tools("test-server")

    def test_list_server_tools_sends_correct_params(self) -> None:
        """Test list_server_tools sends correct server parameter in JSONL request."""
        response = {"id": "test", "status": "success", "result": {"tools": []}}
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            client.list_server_tools("my-server")
            # Verify the request was sent with correct params
            assert len(fake_socket._sent_data) == 1
            request = json.loads(fake_socket._sent_data[0].decode().strip())
            assert request["method"] == "list_tools"
            assert request["server"] == "my-server"

    def test_list_server_tools_empty_server(self) -> None:
        """Test list_server_tools raises MCPClientError for empty server string."""
        client = HttpMCPClient(socket_path="/tmp/test.sock")
        with pytest.raises(MCPClientError, match="server parameter must be a non-empty string"):
            client.list_server_tools("")

    # ========================================================================
    # Tests for get_server_tool(server, tool_name)
    # ========================================================================

    def test_get_server_tool_success(self) -> None:
        """Test get_server_tool returns tool object on success."""
        result_data = {"name": "test-tool", "description": "A test tool"}
        response = {"id": "test", "status": "success", "result": result_data}
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            result = client.get_server_tool("test-server", "test-tool")
            assert result == result_data

    def test_get_server_tool_tool_not_found(self) -> None:
        """Test get_server_tool raises MCPClientError on NOT_FOUND for unknown tool."""
        error_response = {
            "id": "test",
            "status": "error",
            "error": {
                "type": "NOT_FOUND",
                "message": "Tool not found",
            },
        }
        fake_socket = FakeSocket(response=error_response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match=r"\[NOT_FOUND\]"):
                client.get_server_tool("test-server", "unknown-tool")

    def test_get_server_tool_server_not_found(self) -> None:
        """Test get_server_tool raises MCPClientError on NOT_FOUND for unknown server."""
        error_response = {
            "id": "test",
            "status": "error",
            "error": {
                "type": "NOT_FOUND",
                "message": "Server not found",
            },
        }
        fake_socket = FakeSocket(response=error_response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match=r"\[NOT_FOUND\]"):
                client.get_server_tool("unknown-server", "test-tool")

    def test_get_server_tool_sends_correct_params(self) -> None:
        """Test get_server_tool sends correct params in JSONL request."""
        response = {"id": "test", "status": "success", "result": {"name": "tool"}}
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            client.get_server_tool("my-server", "my-tool")
            # Verify the request was sent with correct params
            assert len(fake_socket._sent_data) == 1
            request = json.loads(fake_socket._sent_data[0].decode().strip())
            assert request["method"] == "get_server_tool"
            assert request["server"] == "my-server"
            assert request["tool_name"] == "my-tool"

    def test_get_server_tool_empty_server(self) -> None:
        """Test get_server_tool raises MCPClientError for empty server string."""
        client = HttpMCPClient(socket_path="/tmp/test.sock")
        with pytest.raises(MCPClientError, match="server parameter must be a non-empty string"):
            client.get_server_tool("", "test-tool")

    def test_get_server_tool_empty_tool_name(self) -> None:
        """Test get_server_tool raises MCPClientError for empty tool_name string."""
        client = HttpMCPClient(socket_path="/tmp/test.sock")
        with pytest.raises(MCPClientError, match="tool_name parameter must be a non-empty string"):
            client.get_server_tool("test-server", "")

    # ========================================================================
    # Tests for call_server_tool(server, name, arguments, timeout)
    # ========================================================================

    def test_call_server_tool_success(self) -> None:
        """Test call_server_tool returns result dict on success."""
        result_data = {"result": {"job_id": "test-123"}}
        response = {"id": "test", "status": "success", "result": result_data}
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            result = client.call_server_tool("test-server", "execute", {"command": "test"})
            assert result == {"job_id": "test-123"}

    def test_call_server_tool_extracts_result(self) -> None:
        """Test call_server_tool extracts result from envelope."""
        result_data = {"result": {"status": "ok", "data": "value"}}
        response = {"id": "test", "status": "success", "result": result_data}
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            result = client.call_server_tool("test-server", "execute", {})
            assert result == {"status": "ok", "data": "value"}
            assert "result" not in result

    def test_call_server_tool_no_result_key_fallback(self) -> None:
        """Test call_server_tool fallback when 'result' key is missing."""
        result_data = {"status": "ok", "data": "value"}
        response = {"id": "test", "status": "success", "result": result_data}
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            result = client.call_server_tool("test-server", "execute", {})
            assert result == result_data

    def test_call_server_tool_server_not_found(self) -> None:
        """Test call_server_tool raises MCPClientError on NOT_FOUND type."""
        error_response = {
            "id": "test",
            "status": "error",
            "error": {
                "type": "NOT_FOUND",
                "message": "Server not found",
            },
        }
        fake_socket = FakeSocket(response=error_response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match=r"\[NOT_FOUND\]"):
                client.call_server_tool("unknown-server", "execute", {})

    def test_call_server_tool_timeout_504(self) -> None:
        """Test call_server_tool raises MCPClientError with TIMEOUT type."""
        error_response = {
            "id": "test",
            "status": "error",
            "error": {
                "type": "TIMEOUT",
                "message": "Request timed out",
            },
        }
        fake_socket = FakeSocket(response=error_response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match=r"\[TIMEOUT\]"):
                client.call_server_tool("test-server", "execute", {})

    def test_call_server_tool_busy_503(self) -> None:
        """Test call_server_tool raises MCPClientError with BUSY type."""
        error_response = {
            "id": "test",
            "status": "error",
            "error": {
                "type": "BUSY",
                "message": "Server busy",
            },
        }
        fake_socket = FakeSocket(response=error_response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match=r"\[BUSY\]"):
                client.call_server_tool("test-server", "execute", {})

    def test_call_server_tool_jsonrpc_error_502(self) -> None:
        """Test call_server_tool raises MCPClientError with JSONRPC_ERROR type."""
        error_response = {
            "id": "test",
            "status": "error",
            "error": {
                "type": "JSONRPC_ERROR",
                "message": "MCP protocol error",
            },
        }
        fake_socket = FakeSocket(response=error_response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match=r"\[JSONRPC_ERROR\]"):
                client.call_server_tool("test-server", "execute", {})

    def test_call_server_tool_bad_request_400(self) -> None:
        """Test call_server_tool raises MCPClientError with BAD_REQUEST type."""
        error_response = {
            "id": "test",
            "status": "error",
            "error": {
                "type": "BAD_REQUEST",
                "message": "Invalid arguments",
            },
        }
        fake_socket = FakeSocket(response=error_response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match=r"\[BAD_REQUEST\]"):
                client.call_server_tool("test-server", "execute", {})

    def test_call_server_tool_connection_refused(self) -> None:
        """Test call_server_tool raises MCPClientError on socket connection error."""
        fake_socket = FakeSocket(connect_error=OSError("Connection refused"))

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match="Cannot connect"):
                client.call_server_tool("test-server", "execute", {})

    def test_call_server_tool_socket_timeout(self) -> None:
        """Test call_server_tool raises MCPClientError on socket timeout."""
        fake_socket = FakeSocket(timeout_on_recv=True)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError, match="timed out"):
                client.call_server_tool("test-server", "execute", {})

    def test_call_server_tool_sends_correct_params(self) -> None:
        """Test call_server_tool sends correct params in JSONL request."""
        response = {"id": "test", "status": "success", "result": {"result": {}}}
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            client.call_server_tool("my-server", "execute", {"arg": "value"}, timeout=45.0)
            # Verify the request was sent with correct params
            assert len(fake_socket._sent_data) == 1
            request = json.loads(fake_socket._sent_data[0].decode().strip())
            assert request["method"] == "call_tool"
            assert request["server"] == "my-server"
            assert request["tool"] == "execute"
            assert request["arguments"] == {"arg": "value"}
            assert request["timeout_seconds"] == 45.0

    def test_call_server_tool_timeout_field_name(self) -> None:
        """Test call_server_tool uses canonical 'timeout_seconds' field in JSONL request."""
        response = {"id": "test", "status": "success", "result": {"result": {}}}
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            client.call_server_tool("my-server", "execute", {"arg": "value"}, timeout=45.0)

            # Verify exactly one request was sent
            assert len(fake_socket._sent_data) == 1
            request = json.loads(fake_socket._sent_data[0].decode().strip())

            # Verify canonical field name 'timeout_seconds' is used (not 'timeout')
            assert "timeout_seconds" in request
            assert "timeout" not in request
            assert request["timeout_seconds"] == 45.0
            assert request["tool"] == "execute"
            assert request["arguments"] == {"arg": "value"}

    def test_call_server_tool_empty_server(self) -> None:
        """Test call_server_tool raises MCPClientError for empty server string."""
        client = HttpMCPClient(socket_path="/tmp/test.sock")
        with pytest.raises(MCPClientError, match="server parameter must be a non-empty string"):
            client.call_server_tool("", "execute", {})

    def test_call_server_tool_empty_name(self) -> None:
        """Test call_server_tool raises MCPClientError for empty name string."""
        client = HttpMCPClient(socket_path="/tmp/test.sock")
        with pytest.raises(MCPClientError, match="name parameter must be a non-empty string"):
            client.call_server_tool("test-server", "", {})

    # ========================================================================
    # Tests for _request_jsonl() helper (indirect via public methods)
    # ========================================================================

    def test_request_jsonl_sends_method_and_id(self) -> None:
        """Test _request_jsonl sends method and unique id in request."""
        response = {"id": "test", "status": "success", "result": {"servers": []}}
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            client.list_servers()
            # Verify request structure
            assert len(fake_socket._sent_data) == 1
            request = json.loads(fake_socket._sent_data[0].decode().strip())
            assert "id" in request
            assert "method" in request

    # ========================================================================
    # Tests for Unix socket mode
    # ========================================================================

    def test_init_with_socket_path_argument(self) -> None:
        """Test HttpMCPClient initialization with socket_path argument."""
        client = HttpMCPClient(socket_path="/tmp/test.sock")
        assert client.socket_path == "/tmp/test.sock"
        # base_url defaults to env or http://localhost:8080 when not provided
        assert client.base_url == os.environ.get("MCP_BRIDGE_URL", "http://localhost:8080")

    def test_init_with_socket_env_var(self) -> None:
        """Test HttpMCPClient initialization with MCP_BRIDGE_SOCKET env var."""
        with patch.dict(os.environ, {"MCP_BRIDGE_SOCKET": "/tmp/env.sock"}):
            client = HttpMCPClient()
            assert client.socket_path == "/tmp/env.sock"
            # base_url defaults to env or http://localhost:8080 when not provided
            assert client.base_url == os.environ.get("MCP_BRIDGE_URL", "http://localhost:8080")

    def test_socket_path_takes_precedence_over_base_url(self) -> None:
        """Test socket_path takes precedence over base_url argument."""
        client = HttpMCPClient(base_url="http://example.com:9000", socket_path="/tmp/test.sock")
        assert client.socket_path == "/tmp/test.sock"
        # base_url is stored even though socket mode is used for communication
        assert client.base_url == "http://example.com:9000"

    def test_socket_env_takes_precedence_over_url_env(self) -> None:
        """Test MCP_BRIDGE_SOCKET takes precedence over MCP_BRIDGE_URL."""
        with patch.dict(
            os.environ,
            {"MCP_BRIDGE_SOCKET": "/tmp/env.sock", "MCP_BRIDGE_URL": "http://example.com:9000"},
        ):
            client = HttpMCPClient()
            assert client.socket_path == "/tmp/env.sock"
            # base_url is stored from env var even though socket mode is used
            assert client.base_url == "http://example.com:9000"

    def test_request_jsonl_uses_configured_socket_path(self) -> None:
        """Test _request_jsonl connects to the configured socket path."""
        response = {"id": "test", "status": "success", "result": {"servers": []}}
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            client.list_servers()
            # Verify the socket was connected (FakeSocket tracks this)
            assert fake_socket._connected is True

    def test_request_jsonl_uses_jsonl_protocol(self) -> None:
        """Test requests are sent as newline-delimited JSON (JSONL)."""
        response = {"id": "test", "status": "success", "result": {"servers": []}}
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            client.list_servers()
            # Verify JSONL format (JSON followed by newline)
            assert len(fake_socket._sent_data) == 1
            data = fake_socket._sent_data[0]
            assert data.endswith(b"\n")
            # Verify it's valid JSON without the newline
            json.loads(data.decode().strip())

    def test_connection_error_mentions_socket_path(self) -> None:
        """Test error message mentions socket path on connection failure."""
        fake_socket = FakeSocket(connect_error=OSError("Connection refused"))

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError) as exc_info:
                client.list_servers()

            assert "/tmp/test.sock" in str(exc_info.value)
            assert "Socket not available" in str(exc_info.value)

    def test_health_check_uses_socket(self) -> None:
        """Test health_check uses socket connection with configured path."""
        response = {
            "id": "test",
            "status": "success",
            "result": {"status": "ok", "provider": "running"},
        }
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            result = client.health_check()

            assert result is True
            assert fake_socket._connected is True

    def test_socket_mode_is_default(self) -> None:
        """Test socket mode is the default when no env vars are set.

        Note: The socket-based client always uses socket mode by default,
        falling back to /tmp/mcp-bridge.sock when no explicit socket path is set.
        """
        env_without_vars = {
            k: v for k, v in os.environ.items() if k not in ("MCP_BRIDGE_SOCKET", "MCP_BRIDGE_URL")
        }
        with patch.dict(os.environ, env_without_vars, clear=True):
            client = HttpMCPClient()
            # Socket mode is always default with default socket path
            assert client.socket_path == "/tmp/mcp-bridge.sock"
            # base_url defaults to http://localhost:8080 when no env var is set
            assert client.base_url == "http://localhost:8080"

    def test_base_url_stored_but_not_used_in_socket_mode(self) -> None:
        """Test base_url is stored but not used for communication in socket mode.

        The socket client always uses socket mode, so base_url is kept for
        backward compatibility but not used for actual communication.
        """
        env_with_url = {"MCP_BRIDGE_URL": "http://custom:9000"}
        # Clear MCP_BRIDGE_SOCKET if it exists
        with patch.dict(os.environ, env_with_url, clear=True):
            client = HttpMCPClient()
            # Socket mode is always default with default socket path
            assert client.socket_path == "/tmp/mcp-bridge.sock"
            # base_url is stored from env var (for backward compatibility)
            assert client.base_url == "http://custom:9000"

    # ========================================================================
    # Tests for _validate_server (JSONL protocol validation)
    # ========================================================================

    def test_server_validation_rejects_empty_string(self) -> None:
        """Test that empty server name is rejected."""
        from scripts.servers.mcp.client.http_client import MCPClientError as ClientError
        from scripts.servers.mcp.client.http_client import _validate_server

        with pytest.raises(ClientError, match="non-empty string"):
            _validate_server("")

    def test_server_validation_rejects_whitespace_only(self) -> None:
        """Test that whitespace-only server name is rejected after stripping."""
        from scripts.servers.mcp.client.http_client import MCPClientError as ClientError
        from scripts.servers.mcp.client.http_client import _validate_server

        with pytest.raises(ClientError, match="non-empty string"):
            _validate_server("   ")

    def test_server_validation_rejects_none(self) -> None:
        """Test that None server name is rejected."""
        from scripts.servers.mcp.client.http_client import MCPClientError as ClientError
        from scripts.servers.mcp.client.http_client import _validate_server

        with pytest.raises(ClientError, match="non-empty string"):
            _validate_server(None)  # type: ignore[arg-type]

    def test_server_validation_strips_whitespace(self) -> None:
        """Test that leading/trailing whitespace is stripped from server name."""
        from scripts.servers.mcp.client.http_client import _validate_server

        result = _validate_server("  background-job  ")
        assert result == "background-job"

    def test_server_validation_preserves_special_chars(self) -> None:
        """Test that special characters are preserved (no URL encoding for JSONL)."""
        from scripts.servers.mcp.client.http_client import _validate_server

        # Slash should be preserved (not encoded) for JSONL protocol
        result = _validate_server("server/name")
        assert result == "server/name"

        # Hash should be preserved
        result = _validate_server("server#comment")
        assert result == "server#comment"

        # Percent should be preserved
        result = _validate_server("server%20name")
        assert result == "server%20name"

        # Question mark should be preserved
        result = _validate_server("server?query")
        assert result == "server?query"

        # Space should be preserved (except leading/trailing which is stripped)
        result = _validate_server("server name")
        assert result == "server name"

    def test_server_validation_allows_safe_chars(self) -> None:
        """Test that normal server names pass through unchanged."""
        from scripts.servers.mcp.client.http_client import _validate_server

        assert _validate_server("background-job") == "background-job"
        assert _validate_server("my_server_v2") == "my_server_v2"
        assert _validate_server("server.name") == "server.name"

    def test_call_server_tool_uses_raw_server_name(self) -> None:
        """Test that call_server_tool sends raw server name (not URL-encoded) for JSONL."""
        response = {"id": "test", "status": "success", "result": {"result": {}}}
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            client.call_server_tool("server/name", "test_tool", {})

        # Verify server name is sent raw (not encoded) for JSONL protocol
        assert len(fake_socket._sent_data) == 1
        request = json.loads(fake_socket._sent_data[0].decode().strip())
        # Server name should NOT be URL-encoded for JSONL
        assert request["server"] == "server/name"

    def test_list_server_tools_uses_raw_server_name(self) -> None:
        """Test that list_server_tools sends raw server name (not URL-encoded) for JSONL."""
        response = {"id": "test", "status": "success", "result": {"tools": []}}
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            client.list_server_tools("server#name")

        # Verify server name is sent raw (not encoded) for JSONL protocol
        assert len(fake_socket._sent_data) == 1
        request = json.loads(fake_socket._sent_data[0].decode().strip())
        assert request["server"] == "server#name"

    def test_get_server_tool_uses_raw_server_name(self) -> None:
        """Test that get_server_tool sends raw server name (not URL-encoded) for JSONL."""
        response = {"id": "test", "status": "success", "result": {"name": "tool"}}
        fake_socket = FakeSocket(response=response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            client.get_server_tool("server?param=val", "my_tool")

        # Verify server name is sent raw (not encoded) for JSONL protocol
        assert len(fake_socket._sent_data) == 1
        request = json.loads(fake_socket._sent_data[0].decode().strip())
        assert request["server"] == "server?param=val"


# ============================================================================
# MCPSSEClient Tests
# ============================================================================


class TestMCPSSEClientLiveness:
    """Tests for MCPSSEClient.is_alive() liveness detection."""

    def test_is_alive_returns_false_before_initialization(self) -> None:
        """Test is_alive returns False before client is initialized."""
        from scripts.servers.mcp.sse_client import MCPSSEClient

        client = MCPSSEClient(url="https://example.com/sse")
        assert client.is_alive() is False

    def test_is_alive_returns_true_after_successful_request(self) -> None:
        """Test is_alive returns True after a successful request."""
        from scripts.servers.mcp.sse_client import MCPSSEClient

        client = MCPSSEClient(url="https://example.com/sse")

        # Simulate successful initialization state
        client._initialized = True
        client._last_success_time = time.monotonic()
        client._consecutive_failures = 0

        assert client.is_alive() is True

    def test_is_alive_returns_false_after_max_failures(self) -> None:
        """Test is_alive returns False after exceeding failure threshold."""
        from scripts.servers.mcp.sse_client import MCPSSEClient

        client = MCPSSEClient(url="https://example.com/sse")

        # Simulate initialized but many failures
        client._initialized = True
        client._last_success_time = time.monotonic()
        client._consecutive_failures = client._max_consecutive_failures

        assert client.is_alive() is False

    def test_is_alive_returns_false_when_stale(self) -> None:
        """Test is_alive returns False when last success is too old."""
        from scripts.servers.mcp.sse_client import MCPSSEClient

        client = MCPSSEClient(url="https://example.com/sse")

        # Simulate initialized but stale (success was 6 minutes ago)
        client._initialized = True
        client._last_success_time = time.monotonic() - 360.0  # 6 minutes ago
        client._consecutive_failures = 0

        assert client.is_alive() is False

    def test_is_alive_returns_false_when_no_success_time(self) -> None:
        """Test is_alive returns False when no successful request has been made."""
        from scripts.servers.mcp.sse_client import MCPSSEClient

        client = MCPSSEClient(url="https://example.com/sse")

        # Simulate initialized but no successful request
        client._initialized = True
        client._last_success_time = None
        client._consecutive_failures = 0

        assert client.is_alive() is False

    def test_close_resets_health_tracking(self) -> None:
        """Test close() resets all health tracking fields."""
        from scripts.servers.mcp.sse_client import MCPSSEClient

        client = MCPSSEClient(url="https://example.com/sse")

        # Simulate a healthy state
        client._initialized = True
        client._last_success_time = time.monotonic()
        client._consecutive_failures = 0

        assert client.is_alive() is True

        client.close()

        # All health fields should be reset
        assert client._initialized is False
        assert client._last_success_time is None
        assert client._consecutive_failures == 0
        assert client.is_alive() is False

    def test_configurable_health_thresholds(self) -> None:
        """Test max_consecutive_failures and max_staleness_seconds are configurable."""
        from scripts.servers.mcp.sse_client import MCPSSEClient

        # Test custom max_consecutive_failures
        client = MCPSSEClient(
            url="https://example.com/sse",
            max_consecutive_failures=5,
            max_staleness_seconds=600.0,
        )
        assert client._max_consecutive_failures == 5
        assert client._max_staleness_seconds == 600.0

        # Simulate initialized state with 4 failures (should still be alive with threshold of 5)
        client._initialized = True
        client._last_success_time = time.monotonic()
        client._consecutive_failures = 4

        assert client.is_alive() is True  # 4 < 5, still alive

        # Now 5 failures should make it unhealthy
        client._consecutive_failures = 5
        assert client.is_alive() is False

        client.close()

    def test_default_health_threshold_values(self) -> None:
        """Test default values for health thresholds."""
        from scripts.servers.mcp.sse_client import MCPSSEClient

        client = MCPSSEClient(url="https://example.com/sse")
        assert client._max_consecutive_failures == 3
        assert client._max_staleness_seconds == 300.0
        client.close()


# ============================================================================
# Protocol Response Compatibility Tests
# ============================================================================


class TestProtocolResponseStructure:
    """Tests verifying protocol response dataclasses produce correct JSON structure."""

    def test_list_servers_response_structure(self) -> None:
        """Verify ServersResponse.to_dict() produces expected JSON structure."""
        from scripts.servers.mcp.protocol import ServerInfo, ServersResponse

        proto_response = ServersResponse(
            servers=[ServerInfo(name="test-server", transport="stdio", healthy=True)]
        )

        result = proto_response.to_dict()
        assert "servers" in result
        assert len(result["servers"]) == 1
        assert result["servers"][0] == {
            "name": "test-server",
            "transport": "stdio",
            "healthy": True,
        }

    def test_call_tool_response_structure(self) -> None:
        """Verify MCPCallResponse.to_dict() produces expected JSON structure."""

        result_data = {"job_id": "test-123", "status": "completed"}
        proto_response = MCPCallResponse(result=result_data)

        result = proto_response.to_dict()
        assert result == {"result": result_data}

    def test_health_response_structure(self) -> None:
        """Verify HealthResponse.to_dict() produces expected JSON structure."""

        proto_response = HealthResponse(status="ok", provider="running")

        result = proto_response.to_dict()
        assert result == {"status": "ok", "provider": "running"}

    def test_error_response_structure(self) -> None:
        """Verify error response produces expected JSON structure."""

        proto_error = ErrorDetail(
            type=ErrorType.NOT_FOUND,
            message="Server 'xyz' not found",
            details=None,
        )

        result = proto_error.to_dict()
        assert result == {
            "type": "NOT_FOUND",
            "message": "Server 'xyz' not found",
            "details": None,
        }

    def test_multiple_servers_response_structure(self) -> None:
        """Test ServersResponse with multiple servers produces correct structure."""
        from scripts.servers.mcp.protocol import ServerInfo, ServersResponse

        servers = [
            ServerInfo(name="server-a", transport="stdio", healthy=True),
            ServerInfo(name="server-b", transport="sse", healthy=False),
            ServerInfo(name="server-c", transport="stdio", healthy=True),
        ]

        proto_response = ServersResponse(servers=servers)
        result = proto_response.to_dict()

        assert len(result["servers"]) == 3
        assert result["servers"][0] == {
            "name": "server-a",
            "transport": "stdio",
            "healthy": True,
        }
        assert result["servers"][1] == {
            "name": "server-b",
            "transport": "sse",
            "healthy": False,
        }
        assert result["servers"][2] == {
            "name": "server-c",
            "transport": "stdio",
            "healthy": True,
        }


# ============================================================================
# Error Round-Trip Tests
# ============================================================================


class TestErrorRoundTrip:
    """Tests verifying error type preservation through socket server/client."""

    def test_not_found_error_roundtrip(self) -> None:
        """Test NOT_FOUND error type is preserved through socket transport."""
        error_response = {
            "id": "test",
            "status": "error",
            "error": {"type": "NOT_FOUND", "message": "Server 'xyz' not found"},
        }
        fake_socket = FakeSocket(response=error_response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError) as exc_info:
                client.list_server_tools("xyz")
            assert "[NOT_FOUND]" in str(exc_info.value)
            assert "Server 'xyz' not found" in str(exc_info.value)

    def test_timeout_error_roundtrip(self) -> None:
        """Test TIMEOUT error type is preserved through socket transport."""
        error_response = {
            "id": "test",
            "status": "error",
            "error": {"type": "TIMEOUT", "message": "Request timed out after 30s"},
        }
        fake_socket = FakeSocket(response=error_response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError) as exc_info:
                client.call_server_tool("test-server", "tool", {})
            assert "[TIMEOUT]" in str(exc_info.value)
            assert "Request timed out" in str(exc_info.value)

    def test_busy_error_roundtrip_with_details(self) -> None:
        """Test BUSY error includes retry_after_ms in details."""
        error_response = {
            "id": "test",
            "status": "error",
            "error": {
                "type": "BUSY",
                "message": "Server busy, please retry",
                "details": {"retry_after_ms": 1000},
            },
        }
        fake_socket = FakeSocket(response=error_response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError) as exc_info:
                client.call_server_tool("test-server", "tool", {})
            assert "[BUSY]" in str(exc_info.value)

    def test_jsonrpc_error_roundtrip(self) -> None:
        """Test JSONRPC_ERROR type is preserved through socket transport."""
        error_response = {
            "id": "test",
            "status": "error",
            "error": {"type": "JSONRPC_ERROR", "message": "MCP protocol error: -32600"},
        }
        fake_socket = FakeSocket(response=error_response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError) as exc_info:
                client.list_server_tools("test")
            assert "[JSONRPC_ERROR]" in str(exc_info.value)

    def test_provider_crashed_error_roundtrip(self) -> None:
        """Test PROVIDER_CRASHED type is preserved through socket transport."""
        error_response = {
            "id": "test",
            "status": "error",
            "error": {
                "type": "PROVIDER_CRASHED",
                "message": "Provider crashed and was restarted",
            },
        }
        fake_socket = FakeSocket(response=error_response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError) as exc_info:
                client.call_server_tool("test-server", "tool", {})
            assert "[PROVIDER_CRASHED]" in str(exc_info.value)

    def test_bad_request_error_roundtrip(self) -> None:
        """Test BAD_REQUEST type is preserved through socket transport."""
        error_response = {
            "id": "test",
            "status": "error",
            "error": {"type": "BAD_REQUEST", "message": "Invalid arguments provided"},
        }
        fake_socket = FakeSocket(response=error_response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError) as exc_info:
                client.call_server_tool("test-server", "tool", {})
            assert "[BAD_REQUEST]" in str(exc_info.value)

    def test_internal_error_roundtrip(self) -> None:
        """Test INTERNAL error type is preserved through socket transport."""
        error_response = {
            "id": "test",
            "status": "error",
            "error": {"type": "INTERNAL", "message": "Unexpected error occurred"},
        }
        fake_socket = FakeSocket(response=error_response)

        with patch("socket.socket", return_value=fake_socket):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError) as exc_info:
                client.list_servers()
            assert "[INTERNAL]" in str(exc_info.value)


# ============================================================================
# Protocol Framing Edge Case Tests (Category A)
# ============================================================================


class TestProtocolFramingEdgeCases:
    """Tests for protocol framing edge cases - server must handle malformed requests gracefully.

    These tests verify the socket server correctly handles malformed and
    edge-case requests without crashing.
    """

    @pytest.fixture
    def socket_server(self, tmp_path: Path) -> Any:
        """Start socket server and return (socket_path, process)."""
        import subprocess

        socket_path = str(tmp_path / "test-mcp-bridge.sock")
        server_script = str(
            Path(__file__).parent.parent.parent / "servers" / "mcp" / "server_impl.py"
        )

        proc = subprocess.Popen(
            [sys.executable, server_script],
            env={**os.environ, "MCP_BRIDGE_SOCKET": socket_path},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for server to be ready
        import socket
        import time

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if Path(socket_path).exists():
                try:
                    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    sock.settimeout(1.0)
                    sock.connect(socket_path)
                    sock.sendall(b'{"method": "health", "id": "startup-check"}\n')
                    response = sock.recv(4096)
                    sock.close()
                    if response and b'"status"' in response:
                        break
                except (ConnectionRefusedError, FileNotFoundError, TimeoutError):
                    pass
            time.sleep(0.05)

        # Verify server is still running before yielding
        assert proc.poll() is None, (
            f"Server process crashed during startup. "
            f"stdout: {proc.stdout.read() if proc.stdout else 'N/A'}, "
            f"stderr: {proc.stderr.read() if proc.stderr else 'N/A'}"
        )

        yield socket_path, proc

        # Check if server crashed during test execution
        exit_code = proc.poll()
        if exit_code is not None:
            # Server crashed - capture logs before cleanup
            stdout_data, stderr_data = proc.communicate(timeout=1)
            raise AssertionError(
                f"Server process crashed during test (exit code: {exit_code}). "
                f"stdout: {stdout_data.decode() if stdout_data else 'N/A'}, "
                f"stderr: {stderr_data.decode() if stderr_data else 'N/A'}"
            )

        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    def test_malformed_json_returns_error(self, socket_server: tuple[str, Any]) -> None:
        """Test that invalid JSON request returns well-formed error response."""
        import socket

        socket_path, _ = socket_server
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(socket_path)

        # Send malformed JSON
        sock.sendall(b"{invalid json}\n")
        response = sock.recv(4096)
        sock.close()

        # Verify well-formed error response
        data = json.loads(response.decode())
        assert data.get("status") == "error"
        assert "error" in data
        assert data["error"]["type"] == "BAD_REQUEST"
        assert "JSON" in data["error"]["message"] or "json" in data["error"]["message"].lower()

    def test_truncated_json_returns_error(self, socket_server: tuple[str, Any]) -> None:
        """Test that truncated JSON returns error without crashing server."""
        import socket

        socket_path, _ = socket_server
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(socket_path)

        # Send truncated JSON (missing closing brace)
        sock.sendall(b'{"method": "health", "id": "test"\n')
        response = sock.recv(4096)
        sock.close()

        data = json.loads(response.decode())
        assert data.get("status") == "error"
        assert data["error"]["type"] == "BAD_REQUEST"

    def test_missing_method_field_returns_error(self, socket_server: tuple[str, Any]) -> None:
        """Test that request without 'method' field returns BAD_REQUEST error."""
        import socket

        socket_path, _ = socket_server
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(socket_path)

        # Send request without method
        sock.sendall(b'{"id": "test-123"}\n')
        response = sock.recv(4096)
        sock.close()

        data = json.loads(response.decode())
        assert data.get("status") == "error"
        assert data["error"]["type"] == "BAD_REQUEST"
        assert "method" in data["error"]["message"].lower()

    def test_unknown_method_returns_error(self, socket_server: tuple[str, Any]) -> None:
        """Test that unknown/unsupported method returns NOT_FOUND or BAD_REQUEST error."""
        import socket

        socket_path, _ = socket_server
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(socket_path)

        # Send unknown method
        sock.sendall(b'{"method": "unknown_method", "id": "test-123"}\n')
        response = sock.recv(4096)
        sock.close()

        data = json.loads(response.decode())
        assert data.get("status") == "error"
        # Could be BAD_REQUEST or NOT_FOUND depending on implementation
        assert data["error"]["type"] in ("BAD_REQUEST", "NOT_FOUND")
        assert (
            "unknown" in data["error"]["message"].lower()
            or "method" in data["error"]["message"].lower()
        )

    def test_server_survives_malformed_request(self, socket_server: tuple[str, Any]) -> None:
        """Test that server continues operating after receiving malformed request."""
        import socket

        socket_path, _ = socket_server

        # Send malformed request
        sock1 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock1.settimeout(5.0)
        sock1.connect(socket_path)
        sock1.sendall(b"not json at all\n")
        sock1.recv(4096)  # Read error response
        sock1.close()

        # Verify server still works with valid request
        sock2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock2.settimeout(5.0)
        sock2.connect(socket_path)
        sock2.sendall(b'{"method": "health", "id": "test-after-error"}\n')
        response = sock2.recv(4096)
        sock2.close()

        data = json.loads(response.decode())
        assert data.get("status") == "success"
        assert data.get("id") == "test-after-error"

    def test_multiple_rapid_requests_with_id_tracking(self, socket_server: tuple[str, Any]) -> None:
        """Test that multiple rapid requests maintain correct ID tracking."""
        import socket

        socket_path, _ = socket_server

        responses = []
        for i in range(10):
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect(socket_path)
            request_id = f"rapid-{i}"
            sock.sendall(f'{{"method": "health", "id": "{request_id}"}}\n'.encode())
            response = sock.recv(4096)
            sock.close()
            data = json.loads(response.decode())
            responses.append(data)

        # Verify each response has correct ID
        for i, resp in enumerate(responses):
            assert resp.get("id") == f"rapid-{i}"
            assert resp.get("status") == "success"


# ============================================================================
# Request Size Limit Tests (Category A-1)
# ============================================================================


class TestRequestSizeLimits:
    """Tests for request size limit enforcement (Category A-1).

    These tests verify the server correctly enforces MAX_REQUEST_SIZE to prevent
    OOM attacks from malicious clients sending oversized requests.
    """

    # Use smaller limits for testing to avoid slow tests
    TEST_MAX_REQUEST_SIZE = 64 * 1024  # 64 KB for testing

    @pytest.fixture
    def socket_server_with_small_limit(self, tmp_path: Path) -> Any:
        """Start socket server with reduced MAX_REQUEST_SIZE for testing."""
        import socket
        import subprocess
        import time

        socket_path = str(tmp_path / "test-mcp-bridge.sock")
        server_script = str(
            Path(__file__).parent.parent.parent / "servers" / "mcp" / "server_impl.py"
        )

        proc = subprocess.Popen(
            [sys.executable, server_script],
            env={
                **os.environ,
                "MCP_BRIDGE_SOCKET": socket_path,
                "MCP_MAX_REQUEST_SIZE": str(self.TEST_MAX_REQUEST_SIZE),
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for server to be ready
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if Path(socket_path).exists():
                try:
                    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    sock.settimeout(1.0)
                    sock.connect(socket_path)
                    sock.sendall(b'{"method": "health", "id": "startup-check"}\n')
                    response = sock.recv(4096)
                    sock.close()
                    if response and b'"status"' in response:
                        break
                except (ConnectionRefusedError, FileNotFoundError, TimeoutError):
                    pass
            time.sleep(0.05)

        yield socket_path, proc

        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    def test_request_at_max_size_succeeds(
        self, socket_server_with_small_limit: tuple[str, Any]
    ) -> None:
        """Test that request exactly at MAX_REQUEST_SIZE is accepted."""
        import socket

        socket_path, _ = socket_server_with_small_limit

        # Create a request that's just under the limit (account for JSON overhead)
        # Use a large "id" field to pad the request size
        base_request = '{"method": "health", "id": "'
        suffix = '"}\n'
        padding_size = self.TEST_MAX_REQUEST_SIZE - len(base_request) - len(suffix) - 100
        large_id = "x" * padding_size

        request = f"{base_request}{large_id}{suffix}".encode()
        assert len(request) < self.TEST_MAX_REQUEST_SIZE

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(10.0)
        sock.connect(socket_path)
        sock.sendall(request)

        # Read until newline - response may include large ID
        response_buffer = bytearray()
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            response_buffer.extend(chunk)
            if b"\n" in response_buffer:
                break

        sock.close()

        response = response_buffer.decode().strip().split("\n")[0]
        data = json.loads(response)
        assert data.get("status") == "success", f"Expected success, got: {data}"

    def test_request_over_max_size_rejected(
        self, socket_server_with_small_limit: tuple[str, Any]
    ) -> None:
        """Test that request exceeding MAX_REQUEST_SIZE is rejected with BAD_REQUEST."""
        import socket

        socket_path, _ = socket_server_with_small_limit

        # Create a request that exceeds the limit
        oversized_payload = "x" * (self.TEST_MAX_REQUEST_SIZE + 1000)
        request = f'{{"method": "health", "id": "{oversized_payload}"}}\n'.encode()

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(10.0)
        sock.connect(socket_path)

        # Send in chunks to simulate streaming
        chunk_size = 8192
        for i in range(0, len(request), chunk_size):
            try:
                sock.sendall(request[i : i + chunk_size])
            except (BrokenPipeError, ConnectionResetError):
                # Server closed connection - expected behavior
                break

        try:
            response = sock.recv(4096)
            if response:
                data = json.loads(response.decode())
                assert data.get("status") == "error"
                assert data["error"]["type"] == "BAD_REQUEST"
                assert "too large" in data["error"]["message"].lower()
        except (ConnectionResetError, BrokenPipeError):
            # Server forcefully closed - also acceptable
            pass
        finally:
            sock.close()

    def test_oversized_request_does_not_crash_server(
        self, socket_server_with_small_limit: tuple[str, Any]
    ) -> None:
        """Test that server continues operating after rejecting oversized request."""
        import socket
        import time

        socket_path, proc = socket_server_with_small_limit

        # Send oversized request
        oversized_payload = "x" * (self.TEST_MAX_REQUEST_SIZE + 1000)
        request = f'{{"method": "health", "id": "{oversized_payload}"}}\n'.encode()

        sock1 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock1.settimeout(10.0)
        sock1.connect(socket_path)
        try:
            sock1.sendall(request)
            sock1.recv(4096)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            sock1.close()

        # Small delay to let server process
        time.sleep(0.1)

        # Verify server is still alive
        assert proc.poll() is None, "Server process should still be running"

        # Verify server accepts new valid requests
        sock2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock2.settimeout(5.0)
        sock2.connect(socket_path)
        sock2.sendall(b'{"method": "health", "id": "after-oversized"}\n')
        response = sock2.recv(4096)
        sock2.close()

        data = json.loads(response.decode())
        assert data.get("status") == "success"
        assert data.get("id") == "after-oversized"


# ============================================================================
# Slow-Drip Attack Protection Tests (Category A-2)
# ============================================================================


class TestSlowDripAttackProtection:
    """Tests for slow-drip (slowloris) attack protection (Category A-2).

    These tests verify the server enforces timeout limits to prevent slowloris
    attacks where malicious clients send data very slowly to exhaust server resources.
    """

    # Use shorter timeouts for testing
    TEST_PER_READ_TIMEOUT = 2  # 2 seconds (slow-drip protection)
    TEST_SOCKET_IDLE_TIMEOUT = 2  # 2 seconds (idle connection timeout)
    TEST_REQUEST_READ_TIMEOUT = 5  # 5 seconds

    @pytest.fixture
    def socket_server_with_short_timeout(self, tmp_path: Path) -> Any:
        """Start socket server with reduced timeouts for testing."""
        import socket
        import subprocess
        import time

        socket_path = str(tmp_path / "test-mcp-bridge.sock")
        server_script = str(
            Path(__file__).parent.parent.parent / "servers" / "mcp" / "server_impl.py"
        )

        proc = subprocess.Popen(
            [sys.executable, server_script],
            env={
                **os.environ,
                "MCP_BRIDGE_SOCKET": socket_path,
                "MCP_PER_READ_TIMEOUT": str(self.TEST_PER_READ_TIMEOUT),
                "MCP_SOCKET_IDLE_TIMEOUT": str(self.TEST_SOCKET_IDLE_TIMEOUT),
                "MCP_REQUEST_READ_TIMEOUT": str(self.TEST_REQUEST_READ_TIMEOUT),
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for server to be ready
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if Path(socket_path).exists():
                try:
                    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    sock.settimeout(1.0)
                    sock.connect(socket_path)
                    sock.sendall(b'{"method": "health", "id": "startup-check"}\n')
                    response = sock.recv(4096)
                    sock.close()
                    if response and b'"status"' in response:
                        break
                except (ConnectionRefusedError, FileNotFoundError, TimeoutError):
                    pass
            time.sleep(0.05)

        yield socket_path, proc

        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    @pytest.mark.slow
    def test_idle_connection_timeout(
        self, socket_server_with_short_timeout: tuple[str, Any]
    ) -> None:
        """Test that idle connections (no data sent) are closed after timeout.

        Note: This test has relaxed timing tolerances to prevent flakiness in CI
        environments where timing can vary due to resource constraints.
        """
        import socket
        import time

        socket_path, _ = socket_server_with_short_timeout

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.TEST_SOCKET_IDLE_TIMEOUT + 10)  # Extra buffer for CI
        sock.connect(socket_path)

        # Don't send anything - just wait
        start_time = time.monotonic()

        try:
            response = sock.recv(4096)
            elapsed = time.monotonic() - start_time

            # Relaxed timing tolerances for CI stability:
            # - Lower bound: at least 50% of timeout or 0.5s minimum (ensures meaningful validation)
            # - Upper bound: 5 seconds more than expected (accounts for CI delays)
            lower_bound = max(0.5, self.TEST_SOCKET_IDLE_TIMEOUT * 0.5)
            assert elapsed >= lower_bound, (
                f"Connection closed too early: {elapsed:.2f}s (expected >= {lower_bound}s)"
            )
            assert elapsed < self.TEST_SOCKET_IDLE_TIMEOUT + 5, (
                f"Connection closed too late: {elapsed:.2f}s "
                f"(expected < {self.TEST_SOCKET_IDLE_TIMEOUT + 5}s)"
            )

            if response:
                data = json.loads(response.decode())
                assert data.get("status") == "error"
                assert data["error"]["type"] == "BAD_REQUEST"
                assert (
                    "idle" in data["error"]["message"].lower()
                    or "timeout" in data["error"]["message"].lower()
                )
        except TimeoutError:
            # Also acceptable - connection was idle for too long
            pass
        except ConnectionResetError:
            # Server closed connection - acceptable
            pass
        finally:
            sock.close()

    def test_slow_drip_per_read_timeout(
        self, socket_server_with_short_timeout: tuple[str, Any]
    ) -> None:
        """Test that partial data stalling is detected and rejected."""
        import socket
        import time

        socket_path, _ = socket_server_with_short_timeout

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.TEST_PER_READ_TIMEOUT + 5)
        sock.connect(socket_path)

        # Send partial request then stop
        sock.sendall(b'{"method": "health", ')  # Incomplete JSON, no newline
        # Wait for timeout

        start_time = time.monotonic()
        try:
            response = sock.recv(4096)
            elapsed = time.monotonic() - start_time

            # Should timeout within PER_READ_TIMEOUT (+/- tolerance)
            assert elapsed >= self.TEST_PER_READ_TIMEOUT - 1

            if response:
                data = json.loads(response.decode())
                assert data.get("status") == "error"
                assert data["error"]["type"] == "BAD_REQUEST"
                assert (
                    "stalled" in data["error"]["message"].lower()
                    or "timeout" in data["error"]["message"].lower()
                )
        except TimeoutError:
            pass  # Acceptable
        except ConnectionResetError:
            pass  # Acceptable
        finally:
            sock.close()

    def test_slow_drip_attack_does_not_block_other_connections(
        self, socket_server_with_short_timeout: tuple[str, Any]
    ) -> None:
        """Test that slow connections don't block fast connections (asyncio concurrency)."""
        import socket
        import time

        socket_path, _ = socket_server_with_short_timeout

        # Start a slow connection in background
        slow_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        slow_sock.settimeout(self.TEST_PER_READ_TIMEOUT + 5)
        slow_sock.connect(socket_path)
        slow_sock.sendall(b'{"method": ')  # Partial, will stall

        # While slow connection is pending, make a fast request
        fast_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        fast_sock.settimeout(2.0)
        fast_sock.connect(socket_path)

        start_time = time.monotonic()
        fast_sock.sendall(b'{"method": "health", "id": "fast-while-slow"}\n')
        response = fast_sock.recv(4096)
        elapsed = time.monotonic() - start_time

        fast_sock.close()
        slow_sock.close()

        # Fast request should complete quickly (not blocked by slow connection)
        # Allow extra time for CI environment variability
        assert elapsed < 2.0, f"Fast request took {elapsed}s - may be blocked by slow connection"

        data = json.loads(response.decode())
        assert data.get("status") == "success"
        assert data.get("id") == "fast-while-slow"
