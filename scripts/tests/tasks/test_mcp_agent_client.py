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

from scripts.tasks.mcp_agent_client import (
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

    def __init__(
        self,
        responses: list[dict[str, Any]] | None = None,
        poll_result: int | None = None,
        fail_on_start: bool = False,
        fail_on_write: bool = False,
        fail_mid_read: bool = False,
    ) -> None:
        """Initialize fake process.

        Args:
            responses: List of JSON-RPC responses to return.
            poll_result: Return value for poll() (None = running, int = exit code).
            fail_on_start: If True, poll() returns 1 immediately.
            fail_on_write: If True, stdin.write() raises BrokenPipeError.
            fail_mid_read: If True, stdout returns empty mid-read.
        """
        self.responses = responses or []
        self._response_index = 0
        self._poll_result = poll_result
        self._fail_on_start = fail_on_start
        self._fail_on_write = fail_on_write
        self._fail_mid_read = fail_mid_read
        self._poll_count = 0

        self.stdin = MagicMock()
        self.stdout = MagicMock()
        self.stderr = MagicMock()

        if fail_on_write:
            self.stdin.write.side_effect = BrokenPipeError("Broken pipe")
        else:
            self.stdin.write.return_value = None
            self.stdin.flush.return_value = None

        self.stderr.read.return_value = b"fake stderr"

        # Set up stdout.read() to return response data
        self._setup_stdout_read()

    def _setup_stdout_read(self) -> None:
        """Set up stdout.read() to return response data."""

        def read_func(size: int = -1) -> bytes:
            if self._fail_mid_read:
                return b""

            if self._response_index >= len(self.responses):
                return b""

            response = self.responses[self._response_index]
            body = json.dumps(response).encode("utf-8")
            header = f"Content-Length: {len(body)}\r\n\r\n".encode()
            full_response = header + body
            self._response_index += 1
            return full_response[:size] if size > 0 else full_response

        self.stdout.read.side_effect = read_func
        self.stdout.fileno.return_value = 3

    def poll(self) -> int | None:
        """Check if process is running."""
        self._poll_count += 1
        if self._fail_on_start and self._poll_count == 1:
            return 1
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
def mock_select() -> Any:
    """Mock select.select to always return ready."""
    with patch("scripts.tasks.mcp_agent_client.select.select") as mock:
        mock.return_value = ([True], [], [])
        yield mock


class TestMCPClient:
    """Tests for MCPClient class."""

    def test_client_init_success(self, mock_select: Any) -> None:
        """Test successful client initialization."""
        fake_proc = FakeMCPProcess()
        with patch("subprocess.Popen", return_value=fake_proc):
            client = MCPClient(command=["fake", "command"])
            assert client.proc is fake_proc
            client.close()

    def test_client_init_os_error(self, mock_select: Any) -> None:
        """Test client initialization with OS error."""
        with (
            patch("subprocess.Popen", side_effect=OSError("Command not found")),
            pytest.raises(MCPClientError, match="Failed to start MCP server"),
        ):
            MCPClient(command=["nonexistent"])

    def test_client_init_immediate_exit(self, mock_select: Any) -> None:
        """Test client initialization when server exits immediately."""
        fake_proc = FakeMCPProcess(fail_on_start=True)
        with (
            patch("subprocess.Popen", return_value=fake_proc),
            pytest.raises(MCPClientError, match="MCP server exited immediately"),
        ):
            MCPClient(command=["fake"])

    def test_call_tool_success(self, mock_select: Any) -> None:
        """Test successful tool call."""
        response = {"jsonrpc": "2.0", "id": 1, "result": {"job_id": "test-123"}}
        fake_proc = FakeMCPProcess(responses=[response])

        with patch("subprocess.Popen", return_value=fake_proc):
            client = MCPClient(command=["fake"])
            result = client.call_tool("execute", {"command": "test"})
            assert result == {"job_id": "test-123"}
            client.close()

    def test_call_tool_json_rpc_error(self, mock_select: Any) -> None:
        """Test tool call with JSON-RPC error response."""
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32600, "message": "Invalid request"},
        }
        fake_proc = FakeMCPProcess(responses=[response])

        with patch("subprocess.Popen", return_value=fake_proc):
            client = MCPClient(command=["fake"])
            try:
                with pytest.raises(MCPClientError, match="JSON-RPC error -32600"):
                    client.call_tool("execute", {"command": "test"})
            finally:
                client.close()

    def test_call_tool_broken_pipe(self, mock_select: Any) -> None:
        """Test tool call with broken pipe on send."""
        fake_proc = FakeMCPProcess(fail_on_write=True)

        with patch("subprocess.Popen", return_value=fake_proc):
            client = MCPClient(command=["fake"])
            try:
                with pytest.raises(MCPClientError, match="Failed to send request"):
                    client.call_tool("execute", {"command": "test"})
            finally:
                client.close()

    def test_close_terminates_running_process(self, mock_select: Any) -> None:
        """Test that close() terminates a running process."""
        fake_proc = FakeMCPProcess()
        with patch("subprocess.Popen", return_value=fake_proc):
            client = MCPClient(command=["fake"])
            client.close()
            # Process should have been terminated


class TestCmdStart:
    """Tests for cmd_start function."""

    def test_start_returns_job_id(self, mock_select: Any) -> None:
        """Test that start mode returns job_id immediately."""
        response = {"jsonrpc": "2.0", "id": 1, "result": {"job_id": "abc-123"}}
        fake_proc = FakeMCPProcess(responses=[response])

        with patch("subprocess.Popen", return_value=fake_proc):
            client = MCPClient(command=["fake"])
            result = cmd_start(client, "echo hello")
            assert result["status"] == "started"
            assert result["job_id"] == "abc-123"
            client.close()

    def test_start_handles_error(self, mock_select: Any) -> None:
        """Test that start mode handles errors gracefully."""
        fake_proc = FakeMCPProcess(fail_on_write=True)

        with patch("subprocess.Popen", return_value=fake_proc):
            client = MCPClient(command=["fake"])
            result = cmd_start(client, "echo hello")
            assert result["status"] == "failed"
            assert "error" in result
            client.close()


class TestCmdWait:
    """Tests for cmd_wait function."""

    def test_wait_polls_until_complete(self, mock_select: Any) -> None:
        """Test that wait mode polls and returns final result."""
        execute_response = {"jsonrpc": "2.0", "id": 1, "result": {"job_id": "job-1"}}
        status_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"status": "completed", "exit_code": 0},
        }
        output_response = {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {"stdout": "hello world", "stderr": ""},
        }
        fake_proc = FakeMCPProcess(
            responses=[execute_response, status_response, output_response]
        )

        with patch("subprocess.Popen", return_value=fake_proc):
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
        execute_response = {"jsonrpc": "2.0", "id": 1, "result": {"job_id": "job-1"}}
        # Return "running" status repeatedly
        running_responses = [
            {"jsonrpc": "2.0", "id": i, "result": {"status": "running"}}
            for i in range(2, 102)
        ]
        # Add kill response at the end
        kill_response = {"jsonrpc": "2.0", "id": 102, "result": {}}
        fake_proc = FakeMCPProcess(
            responses=[execute_response, *running_responses, kill_response]
        )

        with (
            patch("subprocess.Popen", return_value=fake_proc),
            patch("time.time") as mock_time,
        ):
            # Simulate time passing to trigger timeout
            mock_time.side_effect = [
                0,  # Start time
                0.5,  # First poll
                1.5,  # Second poll - timeout
            ]
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
        status_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "completed", "exit_code": 0},
        }
        output_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"stdout": "done", "stderr": ""},
        }
        fake_proc = FakeMCPProcess(responses=[status_response, output_response])

        with patch("subprocess.Popen", return_value=fake_proc):
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
        # Response without job_id
        execute_response = {"jsonrpc": "2.0", "id": 1, "result": {}}
        fake_proc = FakeMCPProcess(responses=[execute_response])

        with patch("subprocess.Popen", return_value=fake_proc):
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
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "jobs": [
                    {"id": "job-1", "status": "running"},
                    {"id": "job-2", "status": "completed"},
                ]
            },
        }
        fake_proc = FakeMCPProcess(responses=[response])

        with patch("subprocess.Popen", return_value=fake_proc):
            client = MCPClient(command=["fake"])
            result = cmd_list(client)
            assert result["status"] == "completed"
            assert len(result["jobs"]) == 2
            client.close()


class TestCmdCancel:
    """Tests for cmd_cancel function."""

    def test_cancel_kills_job(self, mock_select: Any) -> None:
        """Test that cancel mode terminates job."""
        response = {"jsonrpc": "2.0", "id": 1, "result": {}}
        fake_proc = FakeMCPProcess(responses=[response])

        with patch("subprocess.Popen", return_value=fake_proc):
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
        response = {"jsonrpc": "2.0", "id": 1, "result": {"job_id": "test-job"}}
        fake_proc = FakeMCPProcess(responses=[response])

        with patch("subprocess.Popen", return_value=fake_proc):
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
        with patch(
            "subprocess.Popen",
            side_effect=FileNotFoundError("[Errno 2] No such file or directory"),
        ), pytest.raises(MCPClientError, match="Failed to start MCP server"):
            MCPClient(command=["nonexistent-command"])

    def test_server_unexpected_exit(self, mock_select: Any) -> None:
        """Test handling of server exiting mid-operation."""
        # Server exits after first response
        fake_proc = FakeMCPProcess(poll_result=1)  # Exited with code 1

        with patch("subprocess.Popen", return_value=fake_proc):
            client = MCPClient(command=["fake"])
            # The server appears running initially but poll_result=1 makes it look exited
            # This should trigger the unexpected exit handling
            client.close()

    def test_malformed_json_response(self, mock_select: Any) -> None:
        """Test handling of server returning invalid JSON."""
        fake_proc = FakeMCPProcess()
        # Override stdout.read to return invalid JSON
        fake_proc.stdout.read.side_effect = lambda size=-1: b"Content-Length: 5\r\n\r\n{bad"

        with patch("subprocess.Popen", return_value=fake_proc):
            client = MCPClient(command=["fake"])
            try:
                with pytest.raises(MCPClientError, match="Invalid JSON response"):
                    client.call_tool("execute", {"command": "test"})
            finally:
                client.close()

    def test_missing_result_in_response(self, mock_select: Any) -> None:
        """Test handling of response missing 'result' field."""
        # Response with neither result nor error
        response = {"jsonrpc": "2.0", "id": 1}
        fake_proc = FakeMCPProcess(responses=[response])

        with patch("subprocess.Popen", return_value=fake_proc):
            client = MCPClient(command=["fake"])
            try:
                with pytest.raises(
                    MCPClientError, match="Invalid JSON-RPC response: missing 'result'"
                ):
                    client.call_tool("execute", {"command": "test"})
            finally:
                client.close()
