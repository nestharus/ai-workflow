"""Tests for MCP Agent Client.

This module tests the MCP agent client script including:
- Happy path tests for start, wait, list, and cancel modes
- Error/edge case tests with mocked MCP subprocess
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.mcp_agent_client import (
    MCPClient,
    MCPClientError,
    cmd_cancel,
    cmd_list,
    cmd_start,
    cmd_wait,
    get_exit_code,
)


class FakeMCPProcess:
    """Fake subprocess for testing MCP client."""

    # Standard MCP initialize response - auto-prepended to all response lists
    INIT_RESPONSE = {
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
        fail_on_write: bool = False,
        fail_mid_read: bool = False,
        skip_init_response: bool = False,
    ) -> None:
        """Initialize fake process.

        Args:
            responses: List of JSON-RPC responses to return (after init response).
            poll_result: Return value for poll() (None = running, int = exit code).
            fail_on_start: If True, poll() returns 1 immediately.
            fail_on_write: If True, stdin.write() raises BrokenPipeError.
            fail_mid_read: If True, stdout returns empty mid-read.
            skip_init_response: If True, don't prepend the init response.
        """
        # Prepend init response unless skipped
        if skip_init_response:
            self.responses = responses or []
        else:
            self.responses = [self.INIT_RESPONSE] + (responses or [])
        self._response_index = 0
        self._poll_result = poll_result
        self._fail_on_start = fail_on_start
        self._fail_on_write = fail_on_write
        self._fail_mid_read = fail_mid_read
        self._poll_count = 0
        self._current_buffer = b""  # Buffer for byte-by-byte reading

        self.stdin = MagicMock()
        self.stdout = MagicMock()
        self.stderr = MagicMock()

        if fail_on_write:
            self.stdin.write.side_effect = BrokenPipeError("Broken pipe")
        else:
            # Return the length of data written (for partial write loop support)
            self.stdin.write.side_effect = lambda data: len(data)
            self.stdin.flush.return_value = None

        # Return empty to stop stderr drain thread after first read
        self.stderr.read.return_value = b""

        # Set up stdout.read() to return response data
        self._setup_stdout_read()

    def _setup_stdout_read(self) -> None:
        """Set up stdout.read() to return response data in JSONL format."""

        def read_func(size: int = -1) -> bytes:
            if self._fail_mid_read:
                return b""

            # If buffer is empty, load next response
            if not self._current_buffer:
                if self._response_index >= len(self.responses):
                    return b""
                response = self.responses[self._response_index]
                # Use JSONL format (newline-delimited JSON)
                self._current_buffer = json.dumps(response).encode("utf-8") + b"\n"
                self._response_index += 1

            # Return requested amount from buffer
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
        # Allow poll_result to change after initial startup
        # Return None for first few polls to allow startup to succeed
        if self._poll_result is not None and self._poll_count <= 2:
            return None
        return self._poll_result

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
    """Mock select.select to always return ready, and mock time.sleep to not actually sleep."""
    mock = mocker.patch("scripts.dev.mcp_agent_client.select.select")
    mocker.patch("scripts.dev.mcp_agent_client.time.sleep")
    mock.return_value = ([True], [], [])
    return mock


# Patch target for subprocess.Popen - must patch where it's used, not where it's defined
POPEN_PATCH_TARGET = "scripts.dev.mcp_agent_client.subprocess.Popen"


class TestMCPClient:
    """Tests for MCPClient class."""

    def test_client_init_success(self, mock_select: Any) -> None:
        """Test successful client initialization."""
        fake_proc = FakeMCPProcess()
        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake", "command"])
            assert client.proc is fake_proc  # type: ignore[comparison-overlap]
            client.close()

    def test_client_init_os_error(self, mock_select: Any) -> None:
        """Test client initialization with OS error."""
        with (
            patch(POPEN_PATCH_TARGET, side_effect=OSError("Command not found")),
            pytest.raises(MCPClientError, match="Failed to start MCP server"),
        ):
            MCPClient(command=["nonexistent"])

    def test_client_init_immediate_exit(self, mock_select: Any) -> None:
        """Test client initialization when server exits immediately."""
        fake_proc = FakeMCPProcess(fail_on_start=True)
        with (
            patch(POPEN_PATCH_TARGET, return_value=fake_proc),
            pytest.raises(MCPClientError, match="MCP server exited immediately"),
        ):
            MCPClient(command=["fake"])

    def test_call_tool_success(self, mock_select: Any) -> None:
        """Test successful tool call."""
        # Response id=2 because init uses id=1
        response = {"jsonrpc": "2.0", "id": 2, "result": {"job_id": "test-123"}}
        fake_proc = FakeMCPProcess(responses=[response])

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            result = client.call_tool("execute", {"command": "test"})
            assert result == {"job_id": "test-123"}
            client.close()

    def test_call_tool_json_rpc_error(self, mock_select: Any) -> None:
        """Test tool call with JSON-RPC error response."""
        # Response id=2 because init uses id=1
        response = {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {"code": -32600, "message": "Invalid request"},
        }
        fake_proc = FakeMCPProcess(responses=[response])

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            try:
                with pytest.raises(MCPClientError, match="JSON-RPC error -32600"):
                    client.call_tool("execute", {"command": "test"})
            finally:
                client.close()

    def test_call_tool_broken_pipe(self, mock_select: Any) -> None:
        """Test tool call with broken pipe on send."""
        # Create a proc that succeeds during init but fails on subsequent writes
        fake_proc = FakeMCPProcess()

        # Track call count to fail only after init
        call_count = [0]
        original_write = fake_proc.stdin.write.side_effect

        def write_with_failure(data: bytes) -> int:
            call_count[0] += 1
            # Allow first 2 writes (init request and notification) to succeed
            if call_count[0] <= 2:
                return len(data)
            raise BrokenPipeError("Broken pipe")

        fake_proc.stdin.write.side_effect = write_with_failure

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            try:
                with pytest.raises(MCPClientError, match="Failed to send request"):
                    client.call_tool("execute", {"command": "test"})
            finally:
                client.close()

    def test_close_terminates_running_process(self, mock_select: Any) -> None:
        """Test that close() terminates a running process."""
        fake_proc = FakeMCPProcess()
        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            client.close()
            # Process should have been terminated


class TestCmdStart:
    """Tests for cmd_start function."""

    def test_start_returns_job_id(self, mock_select: Any) -> None:
        """Test that start mode returns job_id immediately."""
        # Response id=2 because init uses id=1
        response = {"jsonrpc": "2.0", "id": 2, "result": {"job_id": "abc-123"}}
        fake_proc = FakeMCPProcess(responses=[response])

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            result = cmd_start(client, "echo hello")
            assert result["status"] == "started"
            assert result["job_id"] == "abc-123"
            client.close()

    def test_start_handles_error(self, mock_select: Any) -> None:
        """Test that start mode handles errors gracefully."""
        # Create proc that succeeds during init but fails on subsequent writes
        fake_proc = FakeMCPProcess()

        # Track call count to fail only after init
        call_count = [0]

        def write_with_failure(data: bytes) -> int:
            call_count[0] += 1
            # Allow first 2 writes (init request and notification) to succeed
            if call_count[0] <= 2:
                return len(data)
            raise BrokenPipeError("Broken pipe")

        fake_proc.stdin.write.side_effect = write_with_failure

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            result = cmd_start(client, "echo hello")
            assert result["status"] == "failed"
            assert "error" in result
            client.close()


class TestCmdWait:
    """Tests for cmd_wait function."""

    def test_wait_polls_until_complete(self, mock_select: Any) -> None:
        """Test that wait mode polls and returns final result."""
        # Response IDs: init=1, execute=2, status=3, output=4
        execute_response = {"jsonrpc": "2.0", "id": 2, "result": {"job_id": "job-1"}}
        status_response = {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {"status": "completed", "exit_code": 0},
        }
        output_response = {
            "jsonrpc": "2.0",
            "id": 4,
            "result": {"stdout": "hello world", "stderr": ""},
        }
        fake_proc = FakeMCPProcess(responses=[execute_response, status_response, output_response])

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            result = cmd_wait(
                client,
                command="echo hello",
                job_id=None,
                max_seconds=60,
                poll_interval=0.01,
            )
            assert result["status"] == "completed"
            assert result["job_id"] == "job-1"
            assert result["stdout"] == "hello world"
            client.close()

    def test_wait_handles_timeout(self, mock_select: Any) -> None:
        """Test that wait mode returns timeout status when max_seconds exceeded."""
        # Response IDs: init=1, execute=2, status=3,4,5..., kill=N
        execute_response = {"jsonrpc": "2.0", "id": 2, "result": {"job_id": "job-1"}}
        # Return "running" status repeatedly (starting at id=3)
        running_responses = [
            {"jsonrpc": "2.0", "id": i, "result": {"status": "running"}} for i in range(3, 103)
        ]
        # Add kill response at the end
        kill_response = {"jsonrpc": "2.0", "id": 103, "result": {}}
        fake_proc = FakeMCPProcess(responses=[execute_response, *running_responses, kill_response])

        # Use a counter-based mock that returns steadily increasing time
        # This handles all the time.monotonic() calls in _read_response loops
        call_count = [0]

        def mock_monotonic_fn() -> float:
            call_count[0] += 1
            # Start at 100, increase by 0.05 each call
            # After 20+ calls (1 second worth), it should trigger timeout
            return 100.0 + (call_count[0] * 0.05)

        with (
            patch(POPEN_PATCH_TARGET, return_value=fake_proc),
            patch(
                "scripts.dev.mcp_agent_client.time.monotonic",
                side_effect=mock_monotonic_fn,
            ),
            patch("scripts.dev.mcp_agent_client.time.sleep"),
        ):
            client = MCPClient(command=["fake"])
            result = cmd_wait(
                client,
                command="sleep 100",
                job_id=None,
                max_seconds=1,
                poll_interval=0.01,
            )
            assert result["status"] == "timeout"
            assert result["job_id"] == "job-1"
            client.close()

    def test_wait_with_existing_job_id(self, mock_select: Any) -> None:
        """Test waiting on an existing job by ID."""
        # Response IDs: init=1, status=2, output=3
        status_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"status": "completed", "exit_code": 0},
        }
        output_response = {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {"stdout": "done", "stderr": ""},
        }
        fake_proc = FakeMCPProcess(responses=[status_response, output_response])

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            result = cmd_wait(
                client,
                command=None,
                job_id="existing-job",
                max_seconds=60,
                poll_interval=0.01,
            )
            assert result["status"] == "completed"
            assert result["job_id"] == "existing-job"
            client.close()

    def test_wait_no_job_id(self, mock_select: Any) -> None:
        """Test wait mode fails gracefully when no job_id available."""
        # Response without job_id (id=2 because init uses id=1)
        execute_response = {"jsonrpc": "2.0", "id": 2, "result": {}}
        fake_proc = FakeMCPProcess(responses=[execute_response])

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            result = cmd_wait(
                client,
                command="echo test",
                job_id=None,
                max_seconds=60,
                poll_interval=0.01,
            )
            assert result["status"] == "failed"
            assert "No job_id" in result.get("error", "")
            client.close()


class TestCmdList:
    """Tests for cmd_list function."""

    def test_list_returns_all_jobs(self, mock_select: Any) -> None:
        """Test that list mode shows all jobs and their statuses."""
        # Response id=2 because init uses id=1
        response = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "jobs": [
                    {"id": "job-1", "status": "running"},
                    {"id": "job-2", "status": "completed"},
                ]
            },
        }
        fake_proc = FakeMCPProcess(responses=[response])

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            result = cmd_list(client)
            assert result["status"] == "completed"
            assert len(result["jobs"]) == 2
            client.close()


class TestCmdCancel:
    """Tests for cmd_cancel function."""

    def test_cancel_kills_job(self, mock_select: Any) -> None:
        """Test that cancel mode terminates job."""
        # Response id=2 because init uses id=1
        response = {"jsonrpc": "2.0", "id": 2, "result": {}}
        fake_proc = FakeMCPProcess(responses=[response])

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            result = cmd_cancel(client, "job-to-kill")
            assert result["status"] == "killed"
            assert result["job_id"] == "job-to-kill"
            client.close()


class TestGetExitCode:
    """Tests for get_exit_code function."""

    def test_completed_success(self) -> None:
        """Test exit code for successful completion."""
        result = {"status": "completed", "exit_code": 0}
        assert get_exit_code(result) == 0

    def test_completed_with_error(self) -> None:
        """Test exit code for completion with error."""
        result = {"status": "completed", "exit_code": 5}
        assert get_exit_code(result) == 5

    def test_started(self) -> None:
        """Test exit code for started status."""
        result = {"status": "started"}
        assert get_exit_code(result) == 0

    def test_timeout(self) -> None:
        """Test exit code 124 for timeout."""
        result = {"status": "timeout"}
        assert get_exit_code(result) == 124

    def test_killed(self) -> None:
        """Test exit code 137 for killed."""
        result = {"status": "killed"}
        assert get_exit_code(result) == 137

    def test_failed(self) -> None:
        """Test exit code 1 for failed."""
        result = {"status": "failed"}
        assert get_exit_code(result) == 1


class TestJSONOutputFormat:
    """Tests for JSON output format compliance."""

    def test_json_output_format(self, mock_select: Any) -> None:
        """Test that output is valid JSON matching expected schema."""
        # Response id=2 because init uses id=1
        response = {"jsonrpc": "2.0", "id": 2, "result": {"job_id": "test-job"}}
        fake_proc = FakeMCPProcess(responses=[response])

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            result = cmd_start(client, "echo test")

            # Verify result is JSON serializable
            json_str = json.dumps(result)
            parsed = json.loads(json_str)

            # Verify expected fields
            assert "status" in parsed
            assert parsed["status"] in (
                "started",
                "completed",
                "failed",
                "killed",
                "timeout",
            )
            client.close()


class TestErrorEdgeCases:
    """Tests for error conditions and edge cases."""

    def test_server_startup_failure(self) -> None:
        """Test handling of server startup failure (command not found)."""
        with (
            patch(
                POPEN_PATCH_TARGET,
                side_effect=FileNotFoundError("[Errno 2] No such file or directory"),
            ),
            pytest.raises(MCPClientError, match="Failed to start MCP server"),
        ):
            MCPClient(command=["nonexistent-command"])

    def test_server_unexpected_exit(self, mock_select: Any) -> None:
        """Test handling of server exiting mid-operation."""
        # Server exits after first response
        fake_proc = FakeMCPProcess(poll_result=1)  # Exited with code 1

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            # The server appears running initially but poll_result=1 makes it look exited
            # This should trigger the unexpected exit handling
            client.close()

    def test_malformed_json_response(self, mock_select: Any) -> None:
        """Test handling of server returning invalid JSON."""
        fake_proc = FakeMCPProcess()

        # Create a response sequence: valid init response, then malformed JSON
        init_response = json.dumps(FakeMCPProcess.INIT_RESPONSE).encode("utf-8") + b"\n"
        malformed_response = b"{bad\n"
        responses = [init_response, malformed_response]
        response_index = [0]
        current_buffer = [b""]

        def read_with_malformed(size: int = -1) -> bytes:
            # Load next response if buffer empty
            if not current_buffer[0]:
                if response_index[0] >= len(responses):
                    return b""
                current_buffer[0] = responses[response_index[0]]
                response_index[0] += 1

            if size <= 0:
                result = current_buffer[0]
                current_buffer[0] = b""
                return result
            result = current_buffer[0][:size]
            current_buffer[0] = current_buffer[0][size:]
            return result

        fake_proc.stdout.read.side_effect = read_with_malformed

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            try:
                with pytest.raises(MCPClientError, match="Invalid JSON response"):
                    client.call_tool("execute", {"command": "test"})
            finally:
                client.close()

    def test_missing_result_in_response(self, mock_select: Any) -> None:
        """Test handling of response missing 'result' field."""
        # Response with neither result nor error (id=2 because init uses id=1)
        response = {"jsonrpc": "2.0", "id": 2}
        fake_proc = FakeMCPProcess(responses=[response])

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            try:
                with pytest.raises(
                    MCPClientError, match="Invalid JSON-RPC response: missing 'result'"
                ):
                    client.call_tool("execute", {"command": "test"})
            finally:
                client.close()

    def test_invalid_poll_interval_negative(self, mock_select: Any) -> None:
        """Test that negative poll_interval returns error."""
        fake_proc = FakeMCPProcess()

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            result = cmd_wait(
                client,
                command="echo test",
                job_id=None,
                max_seconds=60,
                poll_interval=-1.0,
            )
            assert result["status"] == "failed"
            assert "poll_interval" in result["error"]
            client.close()

    def test_invalid_poll_interval_nan(self, mock_select: Any) -> None:
        """Test that NaN poll_interval returns error."""
        fake_proc = FakeMCPProcess()

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            result = cmd_wait(
                client,
                command="echo test",
                job_id=None,
                max_seconds=60,
                poll_interval=float("nan"),
            )
            assert result["status"] == "failed"
            assert "poll_interval" in result["error"]
            client.close()

    def test_invalid_max_seconds_negative(self, mock_select: Any) -> None:
        """Test that negative max_seconds returns error."""
        fake_proc = FakeMCPProcess()

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            result = cmd_wait(
                client,
                command="echo test",
                job_id=None,
                max_seconds=-1,
                poll_interval=0.01,
            )
            assert result["status"] == "failed"
            assert "max_seconds" in result["error"]
            client.close()

    def test_invalid_max_seconds_zero(self, mock_select: Any) -> None:
        """Test that zero max_seconds with no immediate result times out."""
        # This test verifies that max_seconds=0 immediately times out
        # Response IDs: init=1, execute=2
        execute_response = {"jsonrpc": "2.0", "id": 2, "result": {"job_id": "job-1"}}
        # No status response - job will timeout immediately
        kill_response = {"jsonrpc": "2.0", "id": 3, "result": {}}
        fake_proc = FakeMCPProcess(responses=[execute_response, kill_response])

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            result = cmd_wait(
                client,
                command="echo test",
                job_id=None,
                max_seconds=0,
                poll_interval=0.01,
            )
            # With max_seconds=0, it should timeout immediately
            assert result["status"] == "timeout"
            client.close()

    def test_invalid_utf8_in_response(self, mock_select: Any) -> None:
        """Test handling of invalid UTF-8 in response body."""
        fake_proc = FakeMCPProcess()

        # Create a response sequence: valid init response, then invalid UTF-8
        init_response = json.dumps(FakeMCPProcess.INIT_RESPONSE).encode("utf-8") + b"\n"
        invalid_utf8_response = b"\xff\xfe\xfd\xfc\n"
        responses = [init_response, invalid_utf8_response]
        response_index = [0]
        current_buffer = [b""]

        def read_with_invalid_utf8(size: int = -1) -> bytes:
            # Load next response if buffer empty
            if not current_buffer[0]:
                if response_index[0] >= len(responses):
                    return b""
                current_buffer[0] = responses[response_index[0]]
                response_index[0] += 1

            if size <= 0:
                result = current_buffer[0]
                current_buffer[0] = b""
                return result
            result = current_buffer[0][:size]
            current_buffer[0] = current_buffer[0][size:]
            return result

        fake_proc.stdout.read.side_effect = read_with_invalid_utf8

        with patch(POPEN_PATCH_TARGET, return_value=fake_proc):
            client = MCPClient(command=["fake"])
            try:
                with pytest.raises(MCPClientError, match="Invalid UTF-8"):
                    client.call_tool("execute", {"command": "test"})
            finally:
                client.close()
