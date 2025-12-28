import json
import os
import subprocess
import threading
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from scripts.servers.mcp.app.core.config import (
    ConfigError,
    MCPConfig,
    SSEServerConfig,
    StdioServerConfig,
    load_config,
)
from scripts.servers.mcp.app.services.manager import (
    MCPBusyError,
    MCPError,
    MCPProviderCrashedError,
    MCPStdioManager,
    MCPTimeoutError,
)
from scripts.servers.mcp.client.http_client import (
    HttpMCPClient,
    MCPClientError,
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
    mock = mocker.patch("scripts.servers.mcp.app.services.manager.select.select")
    mocker.patch("scripts.servers.mcp.app.services.manager.time.sleep")
    mock.return_value = ([True], [], [])
    return mock


POPEN_PATCH_TARGET = "scripts.servers.mcp.app.services.manager.subprocess.Popen"


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
            patch("scripts.servers.mcp.app.services.manager.time.monotonic", side_effect=mono),
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


class TestHttpMCPClient:
    def test_health_check_uses_devnull(self) -> None:
        """Test health_check uses os.devnull for cross-platform compatibility."""
        captured_cmd: list[str] = []

        def run_mock(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            captured_cmd.extend(cmd)
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="200", stderr="")

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            result = client.health_check()
            assert result is True
            # Check that os.devnull was used (not hardcoded /dev/null)
            assert os.devnull in captured_cmd

    def test_list_servers_success(self) -> None:
        """Test list_servers returns dict on success."""
        response = {"servers": [{"name": "test-server"}]}

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=json.dumps(response), stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            result = client.list_servers()
            assert result == response

    def test_list_servers_connection_refused(self) -> None:
        """Test list_servers raises MCPClientError with 'Cannot connect' on curl exit 7."""

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=7, stdout="", stderr="Connection refused"
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            with pytest.raises(MCPClientError, match="Cannot connect"):
                client.list_servers()

    def test_list_servers_timeout(self) -> None:
        """Test list_servers raises MCPClientError with 'timed out' on curl exit 28."""

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args=cmd, returncode=28, stdout="", stderr="")

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            with pytest.raises(MCPClientError, match="timed out"):
                client.list_servers()

    def test_list_servers_error_envelope(self) -> None:
        """Test list_servers parses error envelope and raises MCPClientError."""
        error_response = {
            "error": {
                "type": "SERVER_ERROR",
                "message": "Internal server error",
                "details": None,
            }
        }

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=22, stdout=json.dumps(error_response), stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            with pytest.raises(MCPClientError, match=r"\[SERVER_ERROR\] Internal server error"):
                client.list_servers()

    def test_list_servers_malformed_json(self) -> None:
        """Test list_servers raises MCPClientError with 'Invalid JSON response'."""

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="{bad json", stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            with pytest.raises(MCPClientError, match="Invalid JSON response"):
                client.list_servers()

    def test_list_servers_non_dict_response(self) -> None:
        """Test list_servers raises MCPClientError with 'Invalid response type'."""

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="[]", stderr="")

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            with pytest.raises(MCPClientError, match="Invalid response type"):
                client.list_servers()

    def test_list_servers_url_construction(self) -> None:
        """Test list_servers constructs correct URL path /mcp/servers."""
        captured_cmd: list[str] = []

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            captured_cmd.extend(cmd)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout='{"servers": []}', stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            client.list_servers()
            assert "http://localhost:8080/mcp/servers" in captured_cmd

    def test_list_server_tools_success(self) -> None:
        """Test list_server_tools returns dict on success."""
        response = {"tools": [{"name": "test-tool"}]}

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=json.dumps(response), stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            result = client.list_server_tools("test-server")
            assert result == response

    def test_list_server_tools_server_not_found(self) -> None:
        """Test list_server_tools raises MCPClientError on 404 with NOT_FOUND type."""
        error_response = {
            "error": {
                "type": "NOT_FOUND",
                "message": "Server not found",
                "details": None,
            }
        }

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=22, stdout=json.dumps(error_response), stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            with pytest.raises(MCPClientError, match=r"\[NOT_FOUND\]"):
                client.list_server_tools("unknown-server")

    def test_list_server_tools_mcp_error(self) -> None:
        """Test list_server_tools raises MCPClientError on 502 with JSONRPC_ERROR type."""
        error_response = {
            "error": {
                "type": "JSONRPC_ERROR",
                "message": "MCP protocol error",
                "details": None,
            }
        }

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=22, stdout=json.dumps(error_response), stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            with pytest.raises(MCPClientError, match=r"\[JSONRPC_ERROR\]"):
                client.list_server_tools("test-server")

    def test_list_server_tools_url_construction(self) -> None:
        """Test list_server_tools constructs correct URL path /mcp/{server}/tools."""
        captured_cmd: list[str] = []

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            captured_cmd.extend(cmd)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout='{"tools": []}', stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            client.list_server_tools("my-server")
            assert "http://localhost:8080/mcp/my-server/tools" in captured_cmd

    def test_get_server_tool_success(self) -> None:
        """Test get_server_tool returns tool object on success."""
        response = {"name": "test-tool", "description": "A test tool"}

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=json.dumps(response), stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            result = client.get_server_tool("test-server", "test-tool")
            assert result == response

    def test_get_server_tool_tool_not_found(self) -> None:
        """Test get_server_tool raises MCPClientError on 404 for unknown tool."""
        error_response = {
            "error": {
                "type": "NOT_FOUND",
                "message": "Tool not found",
                "details": None,
            }
        }

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=22, stdout=json.dumps(error_response), stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            with pytest.raises(MCPClientError, match=r"\[NOT_FOUND\]"):
                client.get_server_tool("test-server", "unknown-tool")

    def test_get_server_tool_server_not_found(self) -> None:
        """Test get_server_tool raises MCPClientError on 404 for unknown server."""
        error_response = {
            "error": {
                "type": "NOT_FOUND",
                "message": "Server not found",
                "details": None,
            }
        }

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=22, stdout=json.dumps(error_response), stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            with pytest.raises(MCPClientError, match=r"\[NOT_FOUND\]"):
                client.get_server_tool("unknown-server", "test-tool")

    def test_get_server_tool_url_construction(self) -> None:
        """Test get_server_tool constructs correct URL path /mcp/{server}/tools/{tool_name}."""
        captured_cmd: list[str] = []

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            captured_cmd.extend(cmd)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout='{"name": "tool"}', stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            client.get_server_tool("my-server", "my-tool")
            assert "http://localhost:8080/mcp/my-server/tools/my-tool" in captured_cmd

    def test_call_server_tool_success(self) -> None:
        """Test call_server_tool returns result dict on success."""
        response = {"result": {"job_id": "test-123"}}

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=json.dumps(response), stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            result = client.call_server_tool("test-server", "execute", {"command": "test"})
            assert result == {"job_id": "test-123"}

    def test_call_server_tool_extracts_result(self) -> None:
        """Test call_server_tool extracts result from envelope."""
        response = {"result": {"status": "ok", "data": "value"}}

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=json.dumps(response), stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            result = client.call_server_tool("test-server", "execute", {})
            assert result == {"status": "ok", "data": "value"}
            assert "result" not in result

    def test_call_server_tool_no_result_key_fallback(self) -> None:
        """Test call_server_tool fallback when 'result' key is missing."""
        response = {"status": "ok", "data": "value"}

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=json.dumps(response), stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            result = client.call_server_tool("test-server", "execute", {})
            assert result == response

    def test_call_server_tool_server_not_found(self) -> None:
        """Test call_server_tool raises MCPClientError on 404 with NOT_FOUND type."""
        error_response = {
            "error": {
                "type": "NOT_FOUND",
                "message": "Server not found",
                "details": None,
            }
        }

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=22, stdout=json.dumps(error_response), stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            with pytest.raises(MCPClientError, match=r"\[NOT_FOUND\]"):
                client.call_server_tool("unknown-server", "execute", {})

    def test_call_server_tool_timeout_504(self) -> None:
        """Test call_server_tool raises MCPClientError on 504 with TIMEOUT type."""
        error_response = {
            "error": {
                "type": "TIMEOUT",
                "message": "Request timed out",
                "details": None,
            }
        }

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=22, stdout=json.dumps(error_response), stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            with pytest.raises(MCPClientError, match=r"\[TIMEOUT\]"):
                client.call_server_tool("test-server", "execute", {})

    def test_call_server_tool_busy_503(self) -> None:
        """Test call_server_tool raises MCPClientError on 503 with BUSY type."""
        error_response = {
            "error": {
                "type": "BUSY",
                "message": "Server busy",
                "details": {"retry_after_ms": 1000},
            }
        }

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=22, stdout=json.dumps(error_response), stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            with pytest.raises(MCPClientError, match=r"\[BUSY\]"):
                client.call_server_tool("test-server", "execute", {})

    def test_call_server_tool_jsonrpc_error_502(self) -> None:
        """Test call_server_tool raises MCPClientError on 502 with JSONRPC_ERROR type."""
        error_response = {
            "error": {
                "type": "JSONRPC_ERROR",
                "message": "MCP protocol error",
                "details": None,
            }
        }

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=22, stdout=json.dumps(error_response), stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            with pytest.raises(MCPClientError, match=r"\[JSONRPC_ERROR\]"):
                client.call_server_tool("test-server", "execute", {})

    def test_call_server_tool_bad_request_400(self) -> None:
        """Test call_server_tool raises MCPClientError on 400 with BAD_REQUEST type."""
        error_response = {
            "error": {
                "type": "BAD_REQUEST",
                "message": "Invalid arguments",
                "details": None,
            }
        }

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=22, stdout=json.dumps(error_response), stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            with pytest.raises(MCPClientError, match=r"\[BAD_REQUEST\]"):
                client.call_server_tool("test-server", "execute", {})

    def test_call_server_tool_connection_refused(self) -> None:
        """Test call_server_tool raises MCPClientError on curl exit code 7."""

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=7, stdout="", stderr="Connection refused"
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            with pytest.raises(MCPClientError, match="Cannot connect"):
                client.call_server_tool("test-server", "execute", {})

    def test_call_server_tool_curl_timeout(self) -> None:
        """Test call_server_tool raises MCPClientError on curl exit code 28."""

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args=cmd, returncode=28, stdout="", stderr="")

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            with pytest.raises(MCPClientError, match="timed out"):
                client.call_server_tool("test-server", "execute", {})

    def test_call_server_tool_url_construction(self) -> None:
        """Test call_server_tool constructs correct URL path /mcp/{server}/call."""
        captured_cmd: list[str] = []

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            captured_cmd.extend(cmd)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout='{"result": {}}', stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            client.call_server_tool("my-server", "execute", {})
            assert "http://localhost:8080/mcp/my-server/call" in captured_cmd

    def test_call_server_tool_timeout_field_name(self) -> None:
        """Test call_server_tool uses canonical 'timeout_seconds' field in JSON body."""
        captured_payload: list[str] = []

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            if input:
                captured_payload.append(input)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout='{"result": {}}', stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            client.call_server_tool("my-server", "execute", {"arg": "value"}, timeout=45.0)

            # Verify exactly one payload was captured
            assert len(captured_payload) == 1
            payload = json.loads(captured_payload[0])

            # Verify canonical field name 'timeout_seconds' is used (not 'timeout')
            assert "timeout_seconds" in payload
            assert "timeout" not in payload
            assert payload["timeout_seconds"] == 45.0
            assert payload["tool"] == "execute"
            assert payload["arguments"] == {"arg": "value"}

    def test_request_json_curl_command_construction(self) -> None:
        """Test _request_json constructs curl command with correct URL and --max-time."""
        captured_cmd: list[str] = []

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            captured_cmd.extend(cmd)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout='{"servers": []}', stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            client.list_servers()
            # Verify curl command includes expected flags
            assert "curl" in captured_cmd
            assert "-sS" in captured_cmd
            assert "--fail-with-body" in captured_cmd
            assert "--max-time" in captured_cmd
            # Verify timeout value (list_servers uses 5.0s timeout, so max-time should be 6)
            max_time_idx = captured_cmd.index("--max-time")
            assert captured_cmd[max_time_idx + 1] == "6"

    def test_request_json_includes_unix_socket_flag(self) -> None:
        """Test _request_json includes --unix-socket flag when socket_path is set."""
        captured_cmd: list[str] = []

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            captured_cmd.extend(cmd)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout='{"servers": []}', stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            client.list_servers()

            assert "--unix-socket" in captured_cmd
            socket_idx = captured_cmd.index("--unix-socket")
            assert captured_cmd[socket_idx + 1] == "/tmp/test.sock"

    def test_request_json_uses_dummy_base_url_in_socket_mode(self) -> None:
        """Test dummy base URL (http://localhost) is used in socket mode."""
        captured_cmd: list[str] = []

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            captured_cmd.extend(cmd)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout='{"servers": []}', stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            client.list_servers()

            assert "http://localhost/mcp/servers" in captured_cmd

    def test_connection_error_mentions_socket_path(self) -> None:
        """Test error message for returncode 7 mentions socket path in socket mode."""

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=7, stdout="", stderr="Connection refused"
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            with pytest.raises(MCPClientError) as exc_info:
                client.list_servers()

            assert "/tmp/test.sock" in str(exc_info.value)
            assert "Socket not available" in str(exc_info.value)

    def test_health_check_uses_unix_socket(self) -> None:
        """Test health_check includes --unix-socket when socket_path is set."""
        captured_cmd: list[str] = []

        def run_mock(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            captured_cmd.extend(cmd)
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="200", stderr="")

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient(socket_path="/tmp/test.sock")
            result = client.health_check()

            assert result is True
            assert "--unix-socket" in captured_cmd
            assert "/tmp/test.sock" in captured_cmd

    def test_call_server_tool_uses_encoded_server_name(self) -> None:
        """Test that call_server_tool uses URL-encoded server name in request URL."""
        captured_urls: list[str] = []

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            # Find the URL in the command (it's the argument after -X POST or the last arg)
            for arg in cmd:
                if arg.startswith("http://"):
                    captured_urls.append(arg)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout='{"result": {}}', stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            client.call_server_tool("server/name", "test_tool", {})

        assert len(captured_urls) == 1
        # URL should have encoded server name
        assert "server%2Fname" in captured_urls[0]

    def test_list_server_tools_uses_encoded_server_name(self) -> None:
        """Test that list_server_tools uses URL-encoded server name in request URL."""
        captured_urls: list[str] = []

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            for arg in cmd:
                if arg.startswith("http://"):
                    captured_urls.append(arg)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout='{"tools": []}', stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            client.list_server_tools("server#name")

        assert len(captured_urls) == 1
        assert "server%23name" in captured_urls[0]

    def test_get_server_tool_uses_encoded_server_name(self) -> None:
        """Test that get_server_tool uses URL-encoded server name in request URL."""
        captured_urls: list[str] = []

        def run_mock(
            cmd: list[str], input: str | None = None, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            for arg in cmd:
                if arg.startswith("http://"):
                    captured_urls.append(arg)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout='{"name": "tool"}', stderr=""
            )

        with patch("subprocess.run", side_effect=run_mock):
            client = HttpMCPClient("http://localhost:8080")
            client.get_server_tool("server?param=val", "my_tool")

        assert len(captured_urls) == 1
        assert "server%3Fparam%3Dval" in captured_urls[0]


class TestAPIRoutes:
    @pytest.fixture
    def mock_clients(self) -> dict[str, Any]:
        """Create mock MCP clients."""
        mock_client = MagicMock()
        mock_client.is_alive.return_value = True
        mock_client.call_tool.return_value = {"job_id": "test-123"}
        mock_client.list_tools.return_value = {"tools": []}
        return {"default": mock_client}

    @pytest.fixture
    def app(self, mock_clients: dict[str, Any]) -> Any:
        """Create FastAPI app with mocked clients."""
        from fastapi import FastAPI

        from scripts.servers.mcp.app.api.routes import create_router

        app = FastAPI()
        config = MCPConfig()

        def get_config() -> MCPConfig:
            return config

        def get_clients() -> dict[str, Any]:
            return mock_clients

        router = create_router(get_config, get_clients)
        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app: Any) -> TestClient:
        """Create test client."""
        return TestClient(app)

    def test_health_check_ok(self, client: TestClient, mock_clients: dict[str, Any]) -> None:
        """Test /health returns ok when provider is running."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["provider"] == "running"

    def test_health_check_degraded(self, client: TestClient, mock_clients: dict[str, Any]) -> None:
        """Test /health returns degraded when provider is down."""
        mock_clients["default"].is_alive.return_value = False

        response = client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["provider"] == "down"

    def test_server_call_returns_result_envelope(
        self, client: TestClient, mock_clients: dict[str, Any]
    ) -> None:
        """Test /mcp/{server}/call returns result in envelope."""
        response = client.post(
            "/mcp/default/call",
            json={"tool": "execute", "arguments": {"command": "test"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert "result" in data

    def test_server_not_found_returns_404_with_error_envelope(
        self, client: TestClient, mock_clients: dict[str, Any]
    ) -> None:
        """Test /mcp/{server}/call returns 404 with ErrorEnvelope for unknown server."""
        response = client.post(
            "/mcp/unknown-server/call",
            json={"tool": "execute", "arguments": {}},
        )
        assert response.status_code == 404
        data = response.json()
        # Verify ErrorEnvelope format
        assert "error" in data
        assert data["error"]["type"] == "NOT_FOUND"
        assert "Server 'unknown-server' not found" in data["error"]["message"]
        assert "details" in data["error"]

    def test_server_tools_not_found_returns_404_with_error_envelope(
        self, client: TestClient, mock_clients: dict[str, Any]
    ) -> None:
        """Test /mcp/{server}/tools returns 404 with ErrorEnvelope for unknown server."""
        response = client.get("/mcp/unknown-server/tools")
        assert response.status_code == 404
        data = response.json()
        # Verify ErrorEnvelope format
        assert "error" in data
        assert data["error"]["type"] == "NOT_FOUND"
        assert "Server 'unknown-server' not found" in data["error"]["message"]

    def test_tool_not_found_returns_404_with_error_envelope(
        self, client: TestClient, mock_clients: dict[str, Any]
    ) -> None:
        """Test /mcp/{server}/tools/{tool} returns 404 with ErrorEnvelope for unknown tool."""
        mock_clients["default"].list_tools.return_value = {"tools": []}
        response = client.get("/mcp/default/tools/nonexistent-tool")
        assert response.status_code == 404
        data = response.json()
        # Verify ErrorEnvelope format
        assert "error" in data
        assert data["error"]["type"] == "NOT_FOUND"
        assert "Tool 'nonexistent-tool' not found" in data["error"]["message"]

    def test_server_tools_error_returns_502_with_error_envelope(
        self, client: TestClient, mock_clients: dict[str, Any]
    ) -> None:
        """Test /mcp/{server}/tools returns 502 with ErrorEnvelope on MCP error."""
        mock_clients["default"].list_tools.side_effect = MCPError("Connection failed")
        response = client.get("/mcp/default/tools")
        assert response.status_code == 502
        data = response.json()
        # Verify ErrorEnvelope format
        assert "error" in data
        assert data["error"]["type"] == "JSONRPC_ERROR"
        assert "Connection failed" in data["error"]["message"]
