"""Tests for scripts.servers.mcp.app.services.manager module."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from unittest import mock

import pytest

from scripts.servers.mcp.app.services.manager import (
    MCPBusyError,
    MCPError,
    MCPProviderCrashedError,
    MCPStdioManager,
    MCPTimeoutError,
)


class MockProcess:
    """Mock subprocess for testing MCP manager."""

    def __init__(
        self,
        responses: list[dict[str, Any]] | None = None,
        poll_result: int | None = None,
        crash_on_call: int = 0,
    ) -> None:
        """Initialize mock process.

        Args:
            responses: List of JSON-RPC responses to return.
            poll_result: Return value for poll() - None means running, int means exited.
            crash_on_call: If > 0, crash after this many read calls.
        """
        self.responses = responses or []
        self.response_index = 0
        self._poll_result = poll_result
        self.crash_on_call = crash_on_call
        self.read_count = 0
        self.stdin = BytesIO()
        self._stdout_data = b""
        self.stdout = self._create_stdout()
        self.stderr = BytesIO()
        self.terminated = False
        self.killed = False
        self._wait_called = False

    def _create_stdout(self) -> Any:
        """Create mock stdout that returns responses."""
        mock_stdout = mock.MagicMock()

        def read_one_byte(n: int = 1) -> bytes:
            self.read_count += 1
            if self.crash_on_call > 0 and self.read_count > self.crash_on_call:
                self._poll_result = 1  # Simulate crash
                return b""

            if self.response_index >= len(self.responses):
                return b""

            response = self.responses[self.response_index]
            data = (json.dumps(response) + "\n").encode("utf-8")

            if not hasattr(self, "_current_response_data"):
                self._current_response_data = data
                self._current_response_pos = 0

            if self._current_response_pos < len(self._current_response_data):
                byte = self._current_response_data[
                    self._current_response_pos : self._current_response_pos + 1
                ]
                self._current_response_pos += 1
                return byte
            else:
                self.response_index += 1
                if hasattr(self, "_current_response_data"):
                    delattr(self, "_current_response_data")
                    delattr(self, "_current_response_pos")
                return self.read_one_byte(n)

        mock_stdout.read = read_one_byte
        mock_stdout.fileno = mock.MagicMock(return_value=1)
        return mock_stdout

    def poll(self) -> int | None:
        """Return poll result."""
        return self._poll_result

    def terminate(self) -> None:
        """Mark as terminated."""
        self.terminated = True

    def kill(self) -> None:
        """Mark as killed."""
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        """Wait for process."""
        self._wait_called = True
        return self._poll_result or 0

    def read_one_byte(self, n: int = 1) -> bytes:
        """Read one byte from stdout mock."""
        return self.stdout.read(n)


class TestMCPBusyError:
    """Tests for MCPBusyError."""

    def test_default_message_and_retry(self) -> None:
        """Should have default message and retry_after_ms."""
        error = MCPBusyError()
        assert str(error) == "Provider is busy"
        assert error.retry_after_ms == 1000

    def test_custom_message_and_retry(self) -> None:
        """Should accept custom message and retry_after_ms."""
        error = MCPBusyError("Custom busy", retry_after_ms=5000)
        assert str(error) == "Custom busy"
        assert error.retry_after_ms == 5000


class TestMCPProviderCrashedError:
    """Tests for MCPProviderCrashedError."""

    def test_default_message(self) -> None:
        """Should have default crash message."""
        error = MCPProviderCrashedError()
        assert "crashed and was restarted" in str(error)

    def test_custom_message(self) -> None:
        """Should accept custom message."""
        error = MCPProviderCrashedError("Custom crash message")
        assert str(error) == "Custom crash message"


class TestMCPStdioManagerInit:
    """Tests for MCPStdioManager __init__."""

    def test_init_catches_non_mcp_exception(self) -> None:
        """Should wrap non-MCPError exceptions during init."""
        with mock.patch("subprocess.Popen", side_effect=RuntimeError("Test runtime error")), pytest.raises(
            MCPError
        ) as exc_info:
            MCPStdioManager(command="echo test")

        assert "Failed to start MCP server" in str(exc_info.value)
        assert "Test runtime error" in str(exc_info.value)

    def test_init_reraises_mcp_error(self) -> None:
        """Should re-raise MCPError without wrapping."""
        mock_proc = MockProcess(poll_result=1)  # Exit immediately

        with mock.patch("subprocess.Popen", return_value=mock_proc), pytest.raises(MCPError) as exc_info:
            MCPStdioManager(command="echo test", startup_timeout=0.1)

        assert "exited immediately" in str(exc_info.value)


class TestMCPStdioManagerCallTool:
    """Tests for MCPStdioManager.call_tool method."""

    @pytest.fixture
    def mock_manager(self) -> MCPStdioManager:
        """Create a mock manager with successful initialization."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}, "serverInfo": {"name": "test", "version": "1.0"}},
        }

        mock_proc = MockProcess(responses=[init_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)
            # Reset for call_tool tests
            mock_proc.responses = []
            mock_proc.response_index = 0
            return manager

    def test_call_tool_busy_error(self, mock_manager: MCPStdioManager) -> None:
        """Should raise MCPBusyError when lock is held."""
        # Hold the lock in another thread
        mock_manager._lock.acquire()

        try:
            # Temporarily reduce lock timeout
            original_timeout = mock_manager.LOCK_ACQUIRE_TIMEOUT
            mock_manager.LOCK_ACQUIRE_TIMEOUT = 0.01

            with pytest.raises(MCPBusyError) as exc_info:
                mock_manager.call_tool("test_tool", {})

            assert exc_info.value.retry_after_ms == 10  # 0.01 * 1000
        finally:
            mock_manager._lock.release()
            mock_manager.LOCK_ACQUIRE_TIMEOUT = original_timeout

    def test_call_tool_restarts_dead_provider(self, mock_manager: MCPStdioManager) -> None:
        """Should detect dead provider and raise MCPProviderCrashedError."""
        # Kill the process
        mock_manager._proc._poll_result = 1

        # Set up restart responses
        init_response = {
            "jsonrpc": "2.0",
            "id": 2,  # Next request ID
            "result": {"capabilities": {}},
        }

        with mock.patch.object(mock_manager, "_start_subprocess"), mock.patch.object(
            mock_manager, "_do_initialize_unlocked"
        ), pytest.raises(MCPProviderCrashedError):
            mock_manager.call_tool("test_tool", {})

    def test_call_tool_returns_result(self) -> None:
        """Should return tool result on success."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }
        tool_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"type": "text", "text": "success"}]},
        }

        mock_proc = MockProcess(responses=[init_response, tool_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)
            result = manager.call_tool("test_tool", {"arg": "value"})

        assert result["content"][0]["text"] == "success"

    def test_call_tool_handles_json_rpc_error(self) -> None:
        """Should raise MCPError for JSON-RPC error response."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }
        error_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {"code": -32600, "message": "Invalid request"},
        }

        mock_proc = MockProcess(responses=[init_response, error_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)

            with pytest.raises(MCPError) as exc_info:
                manager.call_tool("test_tool", {})

        assert "-32600" in str(exc_info.value)
        assert "Invalid request" in str(exc_info.value)

    def test_call_tool_handles_invalid_error_type(self) -> None:
        """Should raise MCPError for non-dict error in response."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }
        error_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "error": "string error",  # Invalid: should be dict
        }

        mock_proc = MockProcess(responses=[init_response, error_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)

            with pytest.raises(MCPError) as exc_info:
                manager.call_tool("test_tool", {})

        assert "Invalid JSON-RPC error type" in str(exc_info.value)

    def test_call_tool_handles_missing_result(self) -> None:
        """Should raise MCPError for response without result."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }
        bad_response = {
            "jsonrpc": "2.0",
            "id": 2,
            # Missing "result" key
        }

        mock_proc = MockProcess(responses=[init_response, bad_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)

            with pytest.raises(MCPError) as exc_info:
                manager.call_tool("test_tool", {})

        assert "missing 'result'" in str(exc_info.value)

    def test_call_tool_handles_non_dict_result(self) -> None:
        """Should raise MCPError for non-dict result."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }
        bad_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": "string result",  # Invalid: should be dict
        }

        mock_proc = MockProcess(responses=[init_response, bad_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)

            with pytest.raises(MCPError) as exc_info:
                manager.call_tool("test_tool", {})

        assert "Invalid JSON-RPC result type" in str(exc_info.value)


class TestMCPStdioManagerListTools:
    """Tests for MCPStdioManager.list_tools method."""

    def test_list_tools_busy_error(self) -> None:
        """Should raise MCPBusyError when lock is held."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }

        mock_proc = MockProcess(responses=[init_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)

            # Hold the lock
            manager._lock.acquire()
            try:
                original_timeout = manager.LOCK_ACQUIRE_TIMEOUT
                manager.LOCK_ACQUIRE_TIMEOUT = 0.01

                with pytest.raises(MCPBusyError):
                    manager.list_tools()
            finally:
                manager._lock.release()
                manager.LOCK_ACQUIRE_TIMEOUT = original_timeout

    def test_list_tools_restarts_dead_provider(self) -> None:
        """Should detect dead provider and raise MCPProviderCrashedError."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }

        mock_proc = MockProcess(responses=[init_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)

            # Kill the process
            mock_proc._poll_result = 1

            with mock.patch.object(manager, "_start_subprocess"), mock.patch.object(
                manager, "_do_initialize_unlocked"
            ), pytest.raises(MCPProviderCrashedError):
                manager.list_tools()

    def test_list_tools_returns_tools(self) -> None:
        """Should return tools list on success."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }
        tools_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"tools": [{"name": "tool1"}, {"name": "tool2"}]},
        }

        mock_proc = MockProcess(responses=[init_response, tools_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)
            result = manager.list_tools()

        assert "tools" in result
        assert len(result["tools"]) == 2

    def test_list_tools_handles_crash_during_request(self) -> None:
        """Should restart and raise MCPProviderCrashedError on crash."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }

        mock_proc = MockProcess(responses=[init_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)

            # Make _send_request_unlocked raise and then crash
            def mock_send(*args: Any, **kwargs: Any) -> None:
                mock_proc._poll_result = 1  # Crash
                raise MCPError("Simulated error")

            with mock.patch.object(manager, "_send_request_unlocked", side_effect=mock_send), mock.patch.object(
                manager, "_start_subprocess"
            ), mock.patch.object(manager, "_do_initialize_unlocked"), pytest.raises(
                MCPProviderCrashedError
            ):
                manager.list_tools()

    def test_list_tools_reraises_error_if_alive(self) -> None:
        """Should re-raise error if server is still alive."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }

        mock_proc = MockProcess(responses=[init_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)

            # Make _send_request_unlocked raise but keep server alive
            with mock.patch.object(
                manager, "_send_request_unlocked", side_effect=MCPError("Simulated error")
            ), pytest.raises(MCPError) as exc_info:
                manager.list_tools()

            assert "Simulated error" in str(exc_info.value)


class TestMCPStdioManagerClose:
    """Tests for MCPStdioManager.close method."""

    def test_close_shutdowns_process(self) -> None:
        """Should shutdown the subprocess."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }

        mock_proc = MockProcess(responses=[init_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)
            manager.close()

        assert mock_proc.terminated or mock_proc.killed or mock_proc._wait_called


class TestCallToolCrashRecovery:
    """Tests for call_tool crash recovery and error handling."""

    def test_call_tool_restart_failure_during_crash(self) -> None:
        """Test call_tool when restart fails after detecting dead provider (lines 553-555)."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }

        mock_proc = MockProcess(responses=[init_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)

            # Kill the process
            mock_proc._poll_result = 1

            # Make restart fail
            def failing_start() -> None:
                raise MCPError("Restart failed")

            with mock.patch.object(manager, "_start_subprocess", side_effect=failing_start), pytest.raises(
                MCPError
            ) as exc_info:
                manager.call_tool("test_tool", {})

            assert "Restart failed" in str(exc_info.value)

    def test_call_tool_handles_stdin_not_available(self) -> None:
        """Test call_tool when stdin is not available (lines 560-561)."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }

        mock_proc = MockProcess(responses=[init_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)

            # Set stdin to None
            manager._proc.stdin = None

            with pytest.raises(MCPError) as exc_info:
                manager.call_tool("test_tool", {})

            assert "stdin not available" in str(exc_info.value)

    def test_call_tool_handles_serialization_error(self) -> None:
        """Test call_tool when JSON serialization fails (lines 574-576)."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }

        mock_proc = MockProcess(responses=[init_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)

            # Try to serialize something that can't be JSON serialized
            # Create an object that will fail json.dumps
            class NonSerializable:
                pass

            with mock.patch("json.dumps", side_effect=TypeError("Not serializable")), pytest.raises(
                MCPError
            ) as exc_info:
                manager.call_tool("test_tool", {"bad": NonSerializable()})

            assert "Failed to serialize request" in str(exc_info.value)

    def test_call_tool_handles_partial_write(self) -> None:
        """Test call_tool when partial write occurs (lines 583-584)."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }
        tool_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"success": True},
        }

        mock_proc = MockProcess(responses=[init_response, tool_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)

            # Mock stdin.write to return 0 (partial write)
            manager._proc.stdin.write = mock.MagicMock(return_value=0)

            with pytest.raises(MCPError) as exc_info:
                manager.call_tool("test_tool", {})

            assert "partial write" in str(exc_info.value)

    def test_call_tool_handles_broken_pipe(self) -> None:
        """Test call_tool when BrokenPipeError occurs (lines 587-588)."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }

        mock_proc = MockProcess(responses=[init_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)

            # Mock stdin.write to raise BrokenPipeError
            manager._proc.stdin.write = mock.MagicMock(side_effect=BrokenPipeError())

            with pytest.raises(MCPError) as exc_info:
                manager.call_tool("test_tool", {})

            assert "Failed to send request" in str(exc_info.value)

    def test_call_tool_timeout(self) -> None:
        """Test call_tool when timeout occurs (lines 593-594)."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }

        mock_proc = MockProcess(responses=[init_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)

            # Make _read_response always timeout
            def timeout_read(*args: Any, **kwargs: Any) -> None:
                raise MCPTimeoutError("Timed out")

            with mock.patch.object(manager, "_read_response", side_effect=timeout_read), pytest.raises(
                MCPTimeoutError
            ):
                manager.call_tool("test_tool", {}, timeout=0.1)

    def test_call_tool_invalid_response_type(self) -> None:
        """Test call_tool when response is not a dict (lines 596-600)."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }

        mock_proc = MockProcess(responses=[init_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)

            # Make _read_response return a non-dict
            with mock.patch.object(manager, "_read_response", return_value="not a dict"), pytest.raises(
                MCPError
            ) as exc_info:
                manager.call_tool("test_tool", {})

            assert "Invalid JSON-RPC response type" in str(exc_info.value)

    def test_call_tool_skips_notifications(self) -> None:
        """Test call_tool skips notification responses (lines 602-603)."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }
        notification = {
            "jsonrpc": "2.0",
            "method": "notification",  # No "id" field
        }
        tool_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"success": True},
        }

        mock_proc = MockProcess(responses=[init_response, notification, tool_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)

            # Make _read_response return notification first, then tool response
            responses = iter([notification, tool_response])

            with mock.patch.object(
                manager, "_read_response", side_effect=lambda t: next(responses)
            ):
                result = manager.call_tool("test_tool", {})

            assert result["success"] is True

    def test_call_tool_skips_mismatched_id(self) -> None:
        """Test call_tool skips responses with mismatched ID (lines 604-605)."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }
        wrong_id_response = {
            "jsonrpc": "2.0",
            "id": 999,  # Wrong ID
            "result": {"wrong": True},
        }
        tool_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"success": True},
        }

        mock_proc = MockProcess(responses=[init_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)

            # Make _read_response return wrong ID first, then correct ID
            responses = iter([wrong_id_response, tool_response])

            with mock.patch.object(
                manager, "_read_response", side_effect=lambda t: next(responses)
            ):
                result = manager.call_tool("test_tool", {})

            assert result["success"] is True

    def test_call_tool_crash_during_request_recovery(self) -> None:
        """Test call_tool crash recovery during request (lines 615-617)."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }

        mock_proc = MockProcess(responses=[init_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)

            # Make _read_response fail with MCPError, then crash the process
            def crash_and_error(*args: Any, **kwargs: Any) -> None:
                mock_proc._poll_result = 1  # Crash
                raise MCPError("I/O error")

            with mock.patch.object(manager, "_read_response", side_effect=crash_and_error), mock.patch.object(
                manager, "_start_subprocess"
            ), mock.patch.object(manager, "_do_initialize_unlocked"), pytest.raises(
                MCPProviderCrashedError
            ):
                manager.call_tool("test_tool", {})

    def test_call_tool_crash_restart_failure(self) -> None:
        """Test call_tool when restart fails after crash during request (lines 615-617)."""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"capabilities": {}},
        }

        mock_proc = MockProcess(responses=[init_response])

        with mock.patch("subprocess.Popen", return_value=mock_proc), mock.patch(
            "select.select", return_value=([mock_proc.stdout], [], [])
        ):
            manager = MCPStdioManager(command="echo test", startup_timeout=0.1)

            # Make _read_response fail with MCPError, crash the process
            def crash_and_error(*args: Any, **kwargs: Any) -> None:
                mock_proc._poll_result = 1
                raise MCPError("I/O error")

            # Make restart fail
            def failing_start() -> None:
                raise MCPError("Restart failed")

            with mock.patch.object(manager, "_read_response", side_effect=crash_and_error), mock.patch.object(
                manager, "_start_subprocess", side_effect=failing_start
            ), pytest.raises(MCPError) as exc_info:
                manager.call_tool("test_tool", {})

            assert "Restart failed" in str(exc_info.value)
