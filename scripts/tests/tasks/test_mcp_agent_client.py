"""Tests for MCP Agent Client.

This module tests the MCP agent client script including:
- Happy path tests for start, wait, list, and cancel modes
- Error/edge case tests with mocked HTTP client
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from scripts.dev.mcp_agent_client import (
    _MCP_SERVER,
    _format_bridge_error,
    cmd_cancel,
    cmd_list,
    cmd_start,
    cmd_wait,
    get_exit_code,
    get_mcp_client,
    main,
)
from scripts.servers.mcp.client.http_client import HttpMCPClient, MCPClientError


class FakeHttpMCPClient:
    """Fake HTTP MCP client for testing."""

    def __init__(
        self,
        tool_responses: list[dict[str, Any]] | None = None,
        raise_on_call: Exception | None = None,
    ) -> None:
        """Initialize fake client.

        Args:
            tool_responses: List of responses to return from call_server_tool().
                           Each call pops the first response.
            raise_on_call: If set, raise this exception on call_server_tool().
        """
        self.tool_responses = list(tool_responses or [])
        self.raise_on_call = raise_on_call
        self.calls: list[tuple[str, str, dict[str, Any], float]] = []

    def call_server_tool(
        self,
        server: str,
        name: str,
        arguments: dict[str, Any],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Mock call_server_tool method."""
        self.calls.append((server, name, arguments, timeout))

        if self.raise_on_call:
            raise self.raise_on_call

        if not self.tool_responses:
            return {}

        return self.tool_responses.pop(0)


@pytest.fixture
def mock_time_sleep(mocker: Any) -> Any:
    """Mock time.sleep to not actually sleep."""
    return mocker.patch("scripts.dev.mcp_agent_client.time.sleep")


class TestGetMCPClient:
    """Tests for get_mcp_client function."""

    def test_returns_http_client(self) -> None:
        """Test that get_mcp_client returns an HttpMCPClient."""
        client = get_mcp_client()
        assert isinstance(client, HttpMCPClient)

    def test_accepts_base_url_parameter(self, monkeypatch: Any) -> None:
        """Test that get_mcp_client accepts base_url parameter."""
        # Ensure bridge env vars don't override the explicit base_url in this test.
        monkeypatch.delenv("MCP_BRIDGE_SOCKET", raising=False)
        monkeypatch.delenv("MCP_BRIDGE_URL", raising=False)
        client = get_mcp_client(base_url="http://custom:9000")
        assert isinstance(client, HttpMCPClient)
        assert client.base_url == "http://custom:9000"

    def test_accepts_socket_path_parameter(self) -> None:
        """Test that get_mcp_client accepts socket_path parameter."""
        client = get_mcp_client(socket_path="/tmp/custom.sock")
        assert isinstance(client, HttpMCPClient)
        assert client.socket_path == "/tmp/custom.sock"

    def test_socket_path_takes_precedence_over_base_url(self) -> None:
        """Test that socket_path takes precedence over base_url."""
        client = get_mcp_client(base_url="http://custom:9000", socket_path="/tmp/custom.sock")
        assert client.socket_path == "/tmp/custom.sock"
        # When socket_path is set, base_url becomes http://localhost for curl
        assert client.base_url == "http://localhost"

    def test_none_parameters_use_defaults(self) -> None:
        """Test that None parameters fall back to env vars or defaults."""
        client = get_mcp_client(base_url=None, socket_path=None)
        assert isinstance(client, HttpMCPClient)


class TestCmdStart:
    """Tests for cmd_start function."""

    def test_start_returns_job_id(self) -> None:
        """Test that start mode returns job_id immediately."""
        fake_client = FakeHttpMCPClient(tool_responses=[{"job_id": "abc-123"}])
        result = cmd_start(fake_client, "echo hello")  # type: ignore[arg-type]
        assert result["status"] == "started"
        assert result["job_id"] == "abc-123"

    def test_start_normalizes_id_to_job_id(self) -> None:
        """Test that 'id' field is normalized to 'job_id'."""
        fake_client = FakeHttpMCPClient(tool_responses=[{"id": "provider-id-123"}])
        result = cmd_start(fake_client, "echo hello")  # type: ignore[arg-type]
        assert result["status"] == "started"
        assert result["job_id"] == "provider-id-123"

    def test_start_extracts_from_structured_content(self) -> None:
        """Test that job_id is extracted from structuredContent wrapper."""
        fake_client = FakeHttpMCPClient(
            tool_responses=[{"structuredContent": {"job_id": "wrapped-123"}}]
        )
        result = cmd_start(fake_client, "echo hello")  # type: ignore[arg-type]
        assert result["status"] == "started"
        assert result["job_id"] == "wrapped-123"

    def test_start_handles_error(self) -> None:
        """Test that start mode handles errors gracefully."""
        fake_client = FakeHttpMCPClient(raise_on_call=MCPClientError("Connection failed"))
        result = cmd_start(fake_client, "echo hello")  # type: ignore[arg-type]
        assert result["status"] == "failed"
        assert "Connection failed" in result["error"]

    def test_start_handles_no_job_id(self) -> None:
        """Test that start mode fails gracefully when no job_id returned."""
        fake_client = FakeHttpMCPClient(tool_responses=[{}])
        result = cmd_start(fake_client, "echo hello")  # type: ignore[arg-type]
        assert result["status"] == "failed"
        assert "No job_id" in result["error"]

    def test_start_handles_invalid_structured_content(self) -> None:
        """Test that start mode handles non-dict structuredContent."""
        # When structuredContent is present but not a dict, it should fail
        fake_client = FakeHttpMCPClient(tool_responses=[{"structuredContent": "not a dict"}])
        result = cmd_start(fake_client, "echo hello")  # type: ignore[arg-type]
        assert result["status"] == "failed"
        assert "Invalid response format" in result["error"]


class TestCmdWait:
    """Tests for cmd_wait function."""

    def test_wait_polls_until_complete(self, mock_time_sleep: Any) -> None:
        """Test that wait mode polls and returns final result."""
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                {"job_id": "job-1"},  # execute_command response
                {"status": "completed", "exit_code": 0},  # get_job_status response
                {"stdout": "hello world", "stderr": ""},  # get_job_output response
            ]
        )
        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command="echo hello",
            job_id=None,
            max_seconds=60,
            poll_interval=0.01,
        )
        assert result["status"] == "completed"
        assert result["job_id"] == "job-1"
        assert result["stdout"] == "hello world"

    def test_wait_handles_timeout(self, mock_time_sleep: Any) -> None:
        """Test that wait mode returns timeout status when max_seconds exceeded."""
        # Create client that always returns "running" status
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                {"job_id": "job-1"},  # execute_command response
                {"status": "running"},  # get_job_status response
                {"status": "running"},  # get_job_status response
                {"status": "running"},  # get_job_status response
                {},  # kill_job response
            ]
        )

        # Mock time to advance past deadline quickly
        call_count = [0]

        def mock_monotonic() -> float:
            call_count[0] += 1
            # First few calls (during execute_command) stay within deadline
            if call_count[0] <= 4:
                return 100.0
            # After that, exceed deadline to trigger timeout
            return 200.0

        with patch(
            "scripts.dev.mcp_agent_client.time.monotonic",
            side_effect=mock_monotonic,
        ):
            result = cmd_wait(
                fake_client,  # type: ignore[arg-type]
                command="sleep 100",
                job_id=None,
                max_seconds=10,
                poll_interval=0.01,
            )
        assert result["status"] == "timeout"
        assert result["job_id"] == "job-1"

    def test_wait_with_existing_job_id(self, mock_time_sleep: Any) -> None:
        """Test waiting on an existing job by ID."""
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                {"status": "completed", "exit_code": 0},  # get_job_status response
                {"stdout": "done", "stderr": ""},  # get_job_output response
            ]
        )
        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command=None,
            job_id="existing-job",
            max_seconds=60,
            poll_interval=0.01,
        )
        assert result["status"] == "completed"
        assert result["job_id"] == "existing-job"

    def test_wait_no_job_id(self) -> None:
        """Test wait mode fails gracefully when no job_id available."""
        fake_client = FakeHttpMCPClient(tool_responses=[{}])
        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command="echo test",
            job_id=None,
            max_seconds=60,
            poll_interval=0.01,
        )
        assert result["status"] == "failed"
        assert "No job_id" in result.get("error", "")

    def test_wait_polls_running_until_completed(self, mock_time_sleep: Any) -> None:
        """Test that wait mode keeps polling while job is running."""
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                {"status": "running"},  # First status check
                {"status": "running"},  # Second status check
                {"status": "completed", "exit_code": 0},  # Third status check
                {"stdout": "output", "stderr": ""},  # get_job_output response
            ]
        )
        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command=None,
            job_id="job-1",
            max_seconds=60,
            poll_interval=0.01,
        )
        assert result["status"] == "completed"
        assert result["job_id"] == "job-1"

    def test_wait_handles_failed_status(self, mock_time_sleep: Any) -> None:
        """Test that wait mode returns failed job status."""
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                {"status": "failed", "exit_code": 1},  # get_job_status response
                {"stdout": "", "stderr": "error occurred"},  # get_job_output response
            ]
        )
        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command=None,
            job_id="job-1",
            max_seconds=60,
            poll_interval=0.01,
        )
        assert result["status"] == "failed"
        assert result["stderr"] == "error occurred"

    def test_wait_handles_killed_status(self, mock_time_sleep: Any) -> None:
        """Test that wait mode returns killed job status."""
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                {"status": "killed", "exit_code": 137},  # get_job_status response
                {"stdout": "", "stderr": ""},  # get_job_output response
            ]
        )
        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command=None,
            job_id="job-1",
            max_seconds=60,
            poll_interval=0.01,
        )
        assert result["status"] == "killed"
        assert result["exit_code"] == 137

    def test_wait_immediate_completion_on_existing_job(self, mock_time_sleep: Any) -> None:
        """Test idempotent wait: attaching to already-completed job returns immediately.

        When waiting on an existing job_id that is already in a terminal state,
        the function should return immediately without polling.
        """
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                # First get_job_status returns completed immediately
                {"status": "completed", "exit_code": 0},
                # get_job_output response
                {"stdout": "already done", "stderr": ""},
            ]
        )
        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command=None,
            job_id="already-completed-job",
            max_seconds=60,
            poll_interval=0.01,
        )
        assert result["status"] == "completed"
        assert result["job_id"] == "already-completed-job"
        assert result["stdout"] == "already done"
        # Verify only 2 calls were made (get_job_status + get_job_output)
        assert len(fake_client.calls) == 2

    def test_wait_transient_get_job_status_error_fails(self, mock_time_sleep: Any) -> None:
        """Test behavior when get_job_status raises MCPClientError.

        The current implementation exits immediately on any error (no retry).
        This documents the current behavior.
        """
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                # execute_command response
                {"job_id": "job-transient"},
            ]
        )

        # Create a wrapper that raises error on second call
        call_count = [0]
        original_call = fake_client.call_server_tool

        def call_with_error(
            server: str, name: str, arguments: dict[str, Any], timeout: float = 30.0
        ) -> dict[str, Any]:
            call_count[0] += 1
            if call_count[0] == 2:  # Second call (get_job_status)
                raise MCPClientError("Connection reset by peer")
            return original_call(server, name, arguments, timeout)

        fake_client.call_server_tool = call_with_error  # type: ignore[method-assign]

        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command="echo test",
            job_id=None,
            max_seconds=60,
            poll_interval=0.01,
        )
        # Current behavior: error causes failed status
        assert result["status"] == "failed"
        assert result["job_id"] == "job-transient"
        assert "Connection reset" in result.get("error", "")

    def test_wait_get_job_output_failure_after_completed(self, mock_time_sleep: Any) -> None:
        """Test error reporting when get_job_output fails after terminal status.

        When get_job_status returns 'completed' but get_job_output subsequently
        raises MCPClientError, the result should include the job status
        and an error field explaining the output retrieval failure.
        """
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                # execute_command response
                {"job_id": "job-output-fail"},
                # get_job_status returns completed
                {"status": "completed", "exit_code": 0},
            ]
        )

        # Create error handler for third call
        call_count = [0]
        original_call = fake_client.call_server_tool

        def call_with_error(
            server: str, name: str, arguments: dict[str, Any], timeout: float = 30.0
        ) -> dict[str, Any]:
            call_count[0] += 1
            if call_count[0] == 3:  # Third call (get_job_output)
                raise MCPClientError("Failed to retrieve output: storage unavailable")
            return original_call(server, name, arguments, timeout)

        fake_client.call_server_tool = call_with_error  # type: ignore[method-assign]

        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command="echo test",
            job_id=None,
            max_seconds=60,
            poll_interval=0.01,
        )
        # Current behavior: error during output retrieval causes failed status
        assert result["status"] == "failed"
        assert result["job_id"] == "job-output-fail"
        assert "Failed to retrieve output" in result.get(
            "error", ""
        ) or "storage unavailable" in result.get("error", "")


class TestCmdList:
    """Tests for cmd_list function."""

    def test_list_returns_all_jobs(self) -> None:
        """Test that list mode shows all jobs and their statuses."""
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                {
                    "jobs": [
                        {"id": "job-1", "status": "running"},
                        {"id": "job-2", "status": "completed"},
                    ]
                }
            ]
        )
        result = cmd_list(fake_client)  # type: ignore[arg-type]
        assert result["status"] == "completed"
        assert len(result["jobs"]) == 2

    def test_list_handles_error(self) -> None:
        """Test that list mode handles errors gracefully."""
        fake_client = FakeHttpMCPClient(raise_on_call=MCPClientError("Connection failed"))
        result = cmd_list(fake_client)  # type: ignore[arg-type]
        assert result["status"] == "failed"
        assert "Connection failed" in result["error"]

    def test_list_handles_empty_jobs(self) -> None:
        """Test that list mode handles empty jobs list."""
        fake_client = FakeHttpMCPClient(tool_responses=[{"jobs": []}])
        result = cmd_list(fake_client)  # type: ignore[arg-type]
        assert result["status"] == "completed"
        assert result["jobs"] == []


class TestCmdCancel:
    """Tests for cmd_cancel function."""

    def test_cancel_kills_job(self) -> None:
        """Test that cancel mode terminates job."""
        fake_client = FakeHttpMCPClient(tool_responses=[{}])
        result = cmd_cancel(fake_client, "job-to-kill")  # type: ignore[arg-type]
        assert result["status"] == "killed"
        assert result["job_id"] == "job-to-kill"

    def test_cancel_handles_error(self) -> None:
        """Test that cancel mode handles errors gracefully."""
        fake_client = FakeHttpMCPClient(raise_on_call=MCPClientError("Job not found"))
        result = cmd_cancel(fake_client, "missing-job")  # type: ignore[arg-type]
        assert result["status"] == "failed"
        assert "Job not found" in result["error"]


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

    def test_completed_without_exit_code(self) -> None:
        """Test exit code defaults to 0 when not provided."""
        result = {"status": "completed"}
        assert get_exit_code(result) == 0

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

    def test_unknown_status(self) -> None:
        """Test exit code 1 for unknown status."""
        result = {"status": "unknown"}
        assert get_exit_code(result) == 1

    def test_invalid_exit_code_string(self) -> None:
        """Test that invalid exit_code string is handled."""
        result = {"status": "completed", "exit_code": "not-a-number"}
        assert get_exit_code(result) == 0


class TestJSONOutputFormat:
    """Tests for JSON output format compliance."""

    def test_json_output_format(self) -> None:
        """Test that output is valid JSON matching expected schema."""
        fake_client = FakeHttpMCPClient(tool_responses=[{"job_id": "test-job"}])
        result = cmd_start(fake_client, "echo test")  # type: ignore[arg-type]

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


class TestErrorEdgeCases:
    """Tests for error conditions and edge cases."""

    def test_invalid_poll_interval_negative(self) -> None:
        """Test that negative poll_interval returns error."""
        fake_client = FakeHttpMCPClient()
        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command="echo test",
            job_id=None,
            max_seconds=60,
            poll_interval=-1.0,
        )
        assert result["status"] == "failed"
        assert "poll_interval" in result["error"]

    def test_invalid_poll_interval_nan(self) -> None:
        """Test that NaN poll_interval returns error."""
        fake_client = FakeHttpMCPClient()
        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command="echo test",
            job_id=None,
            max_seconds=60,
            poll_interval=float("nan"),
        )
        assert result["status"] == "failed"
        assert "poll_interval" in result["error"]

    def test_invalid_max_seconds_negative(self) -> None:
        """Test that negative max_seconds returns error."""
        fake_client = FakeHttpMCPClient()
        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command="echo test",
            job_id=None,
            max_seconds=-1,
            poll_interval=0.01,
        )
        assert result["status"] == "failed"
        assert "max_seconds" in result["error"]

    def test_invalid_max_seconds_zero(self) -> None:
        """Test that zero max_seconds with no immediate result times out."""
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                {"job_id": "job-1"},  # execute_command response
                {},  # kill_job response
            ]
        )
        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command="echo test",
            job_id=None,
            max_seconds=0,
            poll_interval=0.01,
        )
        # With max_seconds=0, it should timeout immediately
        assert result["status"] == "timeout"

    def test_transport_timeout_error_returns_failed_status(self) -> None:
        """Test that transport-level timeout errors return status='failed'.

        Transport-level timeouts (e.g., HTTP request timeouts during get_job_status)
        should return status='failed' because the underlying job may still be running.
        Only client-side max_seconds deadline expiry returns status='timeout'.
        """
        fake_client = FakeHttpMCPClient(raise_on_call=MCPClientError("Request timed out after 30s"))
        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command="echo test",
            job_id=None,
            max_seconds=60,
            poll_interval=0.01,
        )
        assert result["status"] == "failed"
        assert get_exit_code(result) == 1
        assert "timed out" in result["error"]

    def test_structuredcontent_null_handling(self) -> None:
        """Test that null structuredContent is handled."""
        fake_client = FakeHttpMCPClient(
            tool_responses=[{"structuredContent": None, "job_id": "job-1"}]
        )
        result = cmd_start(fake_client, "echo hello")  # type: ignore[arg-type]
        assert result["status"] == "started"
        assert result["job_id"] == "job-1"

    def test_calls_correct_server(self) -> None:
        """Test that calls are made to the correct server."""
        fake_client = FakeHttpMCPClient(tool_responses=[{"job_id": "job-1"}])
        cmd_start(fake_client, "echo hello")  # type: ignore[arg-type]

        assert len(fake_client.calls) == 1
        server, name, arguments, _timeout = fake_client.calls[0]
        assert server == _MCP_SERVER
        assert name == "execute_command"
        assert arguments == {"command": "echo hello"}


class TestBridgeErrorHandling:
    """Tests for HTTP bridge-specific error handling."""

    def test_start_connection_failure_exit_code(self) -> None:
        """Test that connection failures result in exit code 1."""
        fake_client = FakeHttpMCPClient(
            raise_on_call=MCPClientError("Cannot connect to mcp-bridge")
        )
        result = cmd_start(fake_client, "echo test")  # type: ignore[arg-type]
        assert get_exit_code(result) == 1

    def test_wait_transport_timeout_error_exit_code(self) -> None:
        """Test that HTTP transport timeout in wait mode results in exit code 1.

        Transport-level timeouts (e.g., HTTP request timeouts) return status='failed'
        and exit code 1 because the underlying job may still be running.
        """
        fake_client = FakeHttpMCPClient(raise_on_call=MCPClientError("Request timed out after 30s"))
        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command="echo test",
            job_id=None,
            max_seconds=60,
            poll_interval=0.01,
        )
        assert result["status"] == "failed"
        assert get_exit_code(result) == 1

    def test_list_connection_failure(self) -> None:
        """Test list mode handles connection failures."""
        fake_client = FakeHttpMCPClient(
            raise_on_call=MCPClientError("Cannot connect to mcp-bridge")
        )
        result = cmd_list(fake_client)  # type: ignore[arg-type]
        assert result["status"] == "failed"
        assert "Cannot connect" in result["error"]

    def test_cancel_connection_failure(self) -> None:
        """Test cancel mode handles connection failures."""
        fake_client = FakeHttpMCPClient(
            raise_on_call=MCPClientError("Cannot connect to mcp-bridge")
        )
        result = cmd_cancel(fake_client, "job-123")  # type: ignore[arg-type]
        assert result["status"] == "failed"
        assert result["job_id"] == "job-123"
        assert "Cannot connect" in result["error"]

    def test_transport_timeout_errors_return_failed_with_preserved_message(self) -> None:
        """Test that transport timeout errors return status='failed' and preserve error message.

        Various timeout-related error messages from the transport layer should all
        result in status='failed' (not 'timeout') because the underlying job may
        still be running. The error message should be preserved for debugging.
        """
        test_cases = [
            "Request timed out after 30s",
            "Connection TIMED OUT",
            "Timeout exceeded",
            "TIMEOUT during request",
        ]
        for error_msg in test_cases:
            fake_client = FakeHttpMCPClient(raise_on_call=MCPClientError(error_msg))
            result = cmd_wait(
                fake_client,  # type: ignore[arg-type]
                command="echo test",
                job_id=None,
                max_seconds=60,
                poll_interval=0.01,
            )
            assert result["status"] == "failed", f"Failed for: {error_msg}"
            assert get_exit_code(result) == 1, f"Wrong exit code for: {error_msg}"
            # Error message should be preserved
            assert error_msg.lower() in result["error"].lower(), (
                f"Error not preserved for: {error_msg}"
            )

    def test_server_error_response_preserved(self) -> None:
        """Test that server error messages are preserved in result."""
        fake_client = FakeHttpMCPClient(
            raise_on_call=MCPClientError("[MCP_ERROR] Tool execution failed: command not found")
        )
        result = cmd_start(fake_client, "nonexistent-cmd")  # type: ignore[arg-type]
        assert result["status"] == "failed"
        assert "MCP_ERROR" in result["error"]
        assert "command not found" in result["error"]

    def test_socket_not_available_error(self) -> None:
        """Test handling of socket not available."""
        fake_client = FakeHttpMCPClient(
            raise_on_call=MCPClientError(
                "Cannot connect to mcp-bridge at /tmp/mcp-sockets/mcp-bridge.sock. "
                "Socket not available. Ensure mcp-bridge container is running."
            )
        )
        result = cmd_start(fake_client, "echo test")  # type: ignore[arg-type]
        assert result["status"] == "failed"
        assert "Socket not available" in result["error"]

    def test_http_4xx_error(self) -> None:
        """Test handling of HTTP 4xx client errors."""
        fake_client = FakeHttpMCPClient(
            raise_on_call=MCPClientError("[NOT_FOUND] Server 'unknown-server' not found")
        )
        result = cmd_start(fake_client, "echo test")  # type: ignore[arg-type]
        assert result["status"] == "failed"
        assert "NOT_FOUND" in result["error"]

    def test_http_5xx_error(self) -> None:
        """Test handling of HTTP 5xx server errors."""
        fake_client = FakeHttpMCPClient(
            raise_on_call=MCPClientError("HTTP request failed: Internal Server Error")
        )
        result = cmd_start(fake_client, "echo test")  # type: ignore[arg-type]
        assert result["status"] == "failed"
        assert "HTTP request failed" in result["error"]


class TestCLIArguments:
    """Tests for CLI argument parsing."""

    def test_server_url_flag_passed_to_get_mcp_client(self, mocker: Any) -> None:
        """Test that --server-url flag is passed to get_mcp_client."""
        mock_get_client = mocker.patch(
            "scripts.dev.mcp_agent_client.get_mcp_client",
            return_value=FakeHttpMCPClient(tool_responses=[{"jobs": []}]),
        )
        mocker.patch("sys.argv", ["mcp_agent_client", "--server-url", "http://custom:9000", "list"])

        main()

        mock_get_client.assert_called_once_with(
            base_url="http://custom:9000",
            socket_path=None,
        )

    def test_socket_path_flag_passed_to_get_mcp_client(self, mocker: Any) -> None:
        """Test that --socket-path flag is passed to get_mcp_client."""
        mock_get_client = mocker.patch(
            "scripts.dev.mcp_agent_client.get_mcp_client",
            return_value=FakeHttpMCPClient(tool_responses=[{"jobs": []}]),
        )
        mocker.patch("sys.argv", ["mcp_agent_client", "--socket-path", "/tmp/custom.sock", "list"])

        main()

        mock_get_client.assert_called_once_with(
            base_url=None,
            socket_path="/tmp/custom.sock",
        )

    def test_both_flags_passed_to_get_mcp_client(self, mocker: Any) -> None:
        """Test that both --server-url and --socket-path flags are passed."""
        mock_get_client = mocker.patch(
            "scripts.dev.mcp_agent_client.get_mcp_client",
            return_value=FakeHttpMCPClient(tool_responses=[{"jobs": []}]),
        )
        mocker.patch(
            "sys.argv",
            [
                "mcp_agent_client",
                "--server-url",
                "http://custom:9000",
                "--socket-path",
                "/tmp/custom.sock",
                "list",
            ],
        )

        main()

        mock_get_client.assert_called_once_with(
            base_url="http://custom:9000",
            socket_path="/tmp/custom.sock",
        )

    def test_no_flags_uses_none(self, mocker: Any) -> None:
        """Test that no flags results in None parameters."""
        mock_get_client = mocker.patch(
            "scripts.dev.mcp_agent_client.get_mcp_client",
            return_value=FakeHttpMCPClient(tool_responses=[{"jobs": []}]),
        )
        mocker.patch("sys.argv", ["mcp_agent_client", "list"])

        main()

        mock_get_client.assert_called_once_with(
            base_url=None,
            socket_path=None,
        )

    def test_flags_work_with_start_mode(self, mocker: Any) -> None:
        """Test that flags work with start mode."""
        mock_get_client = mocker.patch(
            "scripts.dev.mcp_agent_client.get_mcp_client",
            return_value=FakeHttpMCPClient(tool_responses=[{"job_id": "test-123"}]),
        )
        mocker.patch(
            "sys.argv",
            [
                "mcp_agent_client",
                "--server-url",
                "http://custom:9000",
                "start",
                "--command",
                "echo hello",
            ],
        )

        main()

        mock_get_client.assert_called_once_with(
            base_url="http://custom:9000",
            socket_path=None,
        )

    def test_flags_work_with_wait_mode(self, mocker: Any) -> None:
        """Test that flags work with wait mode."""
        mock_get_client = mocker.patch(
            "scripts.dev.mcp_agent_client.get_mcp_client",
            return_value=FakeHttpMCPClient(
                tool_responses=[
                    {"status": "completed", "exit_code": 0},
                    {"stdout": "", "stderr": ""},
                ]
            ),
        )
        mocker.patch(
            "sys.argv",
            [
                "mcp_agent_client",
                "--socket-path",
                "/tmp/test.sock",
                "wait",
                "--job-id",
                "test-job",
            ],
        )

        main()

        mock_get_client.assert_called_once_with(
            base_url=None,
            socket_path="/tmp/test.sock",
        )

    def test_flags_work_with_cancel_mode(self, mocker: Any) -> None:
        """Test that flags work with cancel mode."""
        mock_get_client = mocker.patch(
            "scripts.dev.mcp_agent_client.get_mcp_client",
            return_value=FakeHttpMCPClient(tool_responses=[{}]),
        )
        mocker.patch(
            "sys.argv",
            [
                "mcp_agent_client",
                "--server-url",
                "http://localhost:9999",
                "cancel",
                "--job-id",
                "cancel-me",
            ],
        )

        main()

        mock_get_client.assert_called_once_with(
            base_url="http://localhost:9999",
            socket_path=None,
        )


class TestFormatBridgeError:
    """Tests for _format_bridge_error helper function."""

    def test_bridge_not_running_socket_error_preserved(self) -> None:
        """Test that 'bridge not running' errors preserve full technical detail."""
        original_msg = (
            "Cannot connect to mcp-bridge at /tmp/mcp-sockets/mcp-bridge.sock. "
            "Socket not available. Ensure mcp-bridge container is running "
            "and socket is mounted."
        )
        error = MCPClientError(original_msg)
        result = _format_bridge_error(error)

        # Original message must be fully preserved
        assert original_msg in result
        # Helper returns a string, not a dict
        assert isinstance(result, str)

    def test_bridge_not_running_http_error_preserved(self) -> None:
        """Test that HTTP connection refused errors preserve full technical detail."""
        original_msg = (
            "Cannot connect to mcp-bridge at http://localhost:8080. "
            "Ensure the MCP bridge is running. For local development, run "
            "'uv run dev.ensure-env' (preferred) or "
            "'docker compose -p ai-workflow-devtools "
            "-f docker-compose.dev.yml up -d mcp-bridge'."
        )
        error = MCPClientError(original_msg)
        result = _format_bridge_error(error)

        # Original message must be fully preserved
        assert original_msg in result
        assert isinstance(result, str)

    def test_http_4xx_error_preserved(self) -> None:
        """Test that HTTP 4xx client errors preserve structured error format."""
        original_msg = "[NOT_FOUND] Server 'unknown-server' not found"
        error = MCPClientError(original_msg)
        result = _format_bridge_error(error)

        # Structured error format [TYPE] message must be preserved
        assert "[NOT_FOUND]" in result
        assert "unknown-server" in result
        assert isinstance(result, str)

    def test_http_5xx_error_preserved(self) -> None:
        """Test that HTTP 5xx server errors preserve error details."""
        original_msg = "HTTP request failed: Internal Server Error"
        error = MCPClientError(original_msg)
        result = _format_bridge_error(error)

        # HTTP error format must be preserved
        assert "HTTP request failed" in result
        assert "Internal Server Error" in result
        assert isinstance(result, str)

    def test_timeout_error_preserved(self) -> None:
        """Test that timeout errors preserve the timeout duration."""
        original_msg = "Request timed out after 30s"
        error = MCPClientError(original_msg)
        result = _format_bridge_error(error)

        # Timeout message with duration must be preserved
        assert "timed out" in result.lower()
        assert "30s" in result
        assert isinstance(result, str)

    def test_helper_does_not_return_dict(self) -> None:
        """Test that helper returns string, not dict - status is cmd_* responsibility."""
        error = MCPClientError("Any error message")
        result = _format_bridge_error(error)

        # MUST return string only - status/exit-code is cmd_* responsibility
        assert isinstance(result, str)
        assert not isinstance(result, dict)


class TestErrorStatusExitCodeMapping:
    """Tests verifying cmd_* functions set status/exit-code, not _format_bridge_error."""

    def test_cmd_start_sets_failed_status_for_connection_error(self) -> None:
        """Test that cmd_start sets status='failed' for connection errors."""
        fake_client = FakeHttpMCPClient(
            raise_on_call=MCPClientError(
                "Cannot connect to mcp-bridge at /tmp/mcp-sockets/mcp-bridge.sock. "
                "Socket not available."
            )
        )
        result = cmd_start(fake_client, "echo test")  # type: ignore[arg-type]

        # cmd_start is responsible for setting status
        assert result["status"] == "failed"
        # Exit code mapping
        assert get_exit_code(result) == 1
        # Error message preserved
        assert "Cannot connect to mcp-bridge" in result["error"]

    def test_cmd_wait_sets_failed_status_for_transport_timeout_error(self) -> None:
        """Test that cmd_wait sets status='failed' for transport-level timeout errors.

        Transport-level timeouts (e.g., HTTP request timeouts during get_job_status)
        return status='failed' because the underlying job may still be running.
        Only explicit max_seconds deadline expiry (with kill_job) returns status='timeout'.
        """
        fake_client = FakeHttpMCPClient(raise_on_call=MCPClientError("Request timed out after 30s"))
        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command="echo test",
            job_id=None,
            max_seconds=60,
            poll_interval=0.01,
        )

        # Transport-level timeout errors get status='failed'
        assert result["status"] == "failed"
        # Exit code 1 for failed
        assert get_exit_code(result) == 1
        # Error message preserved
        assert "timed out" in result["error"]

    def test_cmd_wait_sets_failed_status_for_4xx_error(self) -> None:
        """Test that cmd_wait sets status='failed' for HTTP 4xx errors."""
        fake_client = FakeHttpMCPClient(
            raise_on_call=MCPClientError("[NOT_FOUND] Server 'background-job' not found")
        )
        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command="echo test",
            job_id=None,
            max_seconds=60,
            poll_interval=0.01,
        )

        # Non-timeout errors get status='failed'
        assert result["status"] == "failed"
        # Exit code 1 for failed
        assert get_exit_code(result) == 1
        # Structured error format preserved
        assert "[NOT_FOUND]" in result["error"]


class TestTimeoutSemantics:
    """Tests verifying correct timeout status semantics.

    The key distinction:
    - status='timeout' (exit 124): ONLY for client-side max_seconds deadline expiry
      where the client explicitly calls kill_job
    - status='failed' (exit 1): For transport/bridge-level timeouts during
      call_mcp_tool operations (the underlying job may still be running)
    """

    def test_max_seconds_deadline_expiry_returns_timeout_status(self, mock_time_sleep: Any) -> None:
        """Test that explicit max_seconds deadline expiry returns status='timeout'.

        When the client-side deadline is exceeded (remaining <= 0), the client
        calls kill_job and returns status='timeout' with exit code 124.
        """
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                {"job_id": "deadline-test-job"},  # execute_command response
                {"status": "running"},  # get_job_status response
                {},  # kill_job response (best effort)
            ]
        )

        # Mock time to exceed deadline after first status check
        call_count = [0]

        def mock_monotonic() -> float:
            call_count[0] += 1
            if call_count[0] <= 4:
                return 100.0  # Within deadline
            return 200.0  # Exceeds deadline (100 + 10 max_seconds)

        with patch(
            "scripts.dev.mcp_agent_client.time.monotonic",
            side_effect=mock_monotonic,
        ):
            result = cmd_wait(
                fake_client,  # type: ignore[arg-type]
                command="sleep 100",
                job_id=None,
                max_seconds=10,
                poll_interval=0.01,
            )

        # Client-side deadline expiry returns timeout status
        assert result["status"] == "timeout"
        assert result["job_id"] == "deadline-test-job"
        assert get_exit_code(result) == 124
        # Error message explains the timeout
        assert "exceeded" in result["error"] or "timeout" in result["error"].lower()

    def test_attach_mode_transport_timeout_returns_failed_status(
        self, mock_time_sleep: Any
    ) -> None:
        """Test that attach-mode transport timeouts return status='failed'.

        When waiting on an existing job_id (attach mode), if the HTTP client
        encounters a timeout during get_job_status, it should return status='failed'
        because the underlying job may still be running.
        """
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                {"status": "running"},  # First get_job_status succeeds
            ]
        )

        # Make the second call raise a timeout error
        call_count = [0]
        original_call = fake_client.call_server_tool

        def call_with_timeout_on_second(
            server: str, name: str, arguments: dict[str, Any], timeout: float = 30.0
        ) -> dict[str, Any]:
            call_count[0] += 1
            if call_count[0] == 2:
                raise MCPClientError("Request timed out after 30s")
            return original_call(server, name, arguments, timeout)

        fake_client.call_server_tool = call_with_timeout_on_second  # type: ignore[method-assign]

        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command=None,
            job_id="existing-job-123",
            max_seconds=600,
            poll_interval=0.01,
        )

        # Transport timeout returns failed, not timeout
        assert result["status"] == "failed"
        assert result["job_id"] == "existing-job-123"
        assert get_exit_code(result) == 1
        # Error message preserved
        assert "timed out" in result["error"]

    def test_get_job_output_timeout_returns_failed_status(self, mock_time_sleep: Any) -> None:
        """Test that timeout during get_job_output returns status='failed'.

        Even after job completes, if we get a transport timeout while fetching
        output, we should return status='failed' (job completed but output unknown).
        """
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                {"status": "completed", "exit_code": 0},  # get_job_status succeeds
            ]
        )

        # Make the get_job_output call raise a timeout
        call_count = [0]
        original_call = fake_client.call_server_tool

        def call_with_timeout_on_output(
            server: str, name: str, arguments: dict[str, Any], timeout: float = 30.0
        ) -> dict[str, Any]:
            call_count[0] += 1
            if call_count[0] == 2 and name == "get_job_output":
                raise MCPClientError("Request timed out while fetching output")
            return original_call(server, name, arguments, timeout)

        fake_client.call_server_tool = call_with_timeout_on_output  # type: ignore[method-assign]

        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command=None,
            job_id="job-output-timeout",
            max_seconds=600,
            poll_interval=0.01,
        )

        # Transport timeout returns failed
        assert result["status"] == "failed"
        assert result["job_id"] == "job-output-timeout"
        assert get_exit_code(result) == 1
        # Error message preserved
        assert "timed out" in result["error"]

    def test_execute_command_timeout_returns_failed_status(self) -> None:
        """Test that timeout during execute_command returns status='failed'.

        If the initial command fails to start due to transport timeout,
        we should return status='failed' since we don't have a job_id.
        """
        fake_client = FakeHttpMCPClient(
            raise_on_call=MCPClientError("Request timed out while starting command")
        )

        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command="echo test",
            job_id=None,
            max_seconds=600,
            poll_interval=0.01,
        )

        # Transport timeout returns failed
        assert result["status"] == "failed"
        assert get_exit_code(result) == 1
        # Error message preserved
        assert "timed out" in result["error"]

    def test_deadline_expiry_before_start_returns_timeout_status(self) -> None:
        """Test that deadline expiry before job starts returns status='timeout'.

        If max_seconds=0, the deadline expires immediately before execute_command
        can be called, resulting in status='timeout'.
        """
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                {"job_id": "wont-be-used"},
                {},  # kill_job response
            ]
        )

        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command="echo test",
            job_id=None,
            max_seconds=0,
            poll_interval=0.01,
        )

        # Deadline expiry returns timeout
        assert result["status"] == "timeout"
        assert get_exit_code(result) == 124

    def test_attach_mode_job_id_preserved_on_transport_error(self, mock_time_sleep: Any) -> None:
        """Test that job_id is preserved in result when transport error occurs.

        When waiting on an existing job and a transport error occurs,
        the job_id should be included in the result for debugging.
        """
        fake_client = FakeHttpMCPClient(raise_on_call=MCPClientError("Connection reset by peer"))

        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command=None,
            job_id="preserve-this-id",
            max_seconds=600,
            poll_interval=0.01,
        )

        # job_id should be preserved in the result
        assert result["status"] == "failed"
        assert result["job_id"] == "preserve-this-id"
        assert get_exit_code(result) == 1


class TestTimeoutFloorBehavior:
    """Tests for timeout budget behavior in cmd_wait's get_remaining_timeout().

    The key behavior:
    - Timeouts are bounded by the remaining budget and never exceed max_seconds
    - When remaining > 0: return exact remaining time
    - When remaining <= 0: return 0.0 to trigger timeout path

    Tests verify:
    - Small remaining budgets yield timeouts below 1.0s
    - Large remaining budgets yield timeouts at or above 1.0s
    """

    def test_small_remaining_budget_uses_exact_time(self, mock_time_sleep: Any) -> None:
        """Test that small remaining budgets produce timeouts below 1.0s.

        When the remaining budget drops below 1 second, individual HTTP calls
        receive the exact remaining time (e.g., 0.5s), ensuring the overall
        timeout budget (max_seconds) is respected.
        """
        timeouts_received: list[float] = []
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                {"status": "running"},  # First get_job_status
                {"status": "running"},  # Second get_job_status
                {},  # kill_job response
            ]
        )

        # Capture the timeout passed to each call
        original_call = fake_client.call_server_tool

        def capturing_call(
            server: str, name: str, arguments: dict[str, Any], timeout: float = 30.0
        ) -> dict[str, Any]:
            timeouts_received.append(timeout)
            return original_call(server, name, arguments, timeout)

        fake_client.call_server_tool = capturing_call  # type: ignore[method-assign]

        # Mock time to have small remaining budget
        call_count = [0]

        def mock_monotonic() -> float:
            """Return time values that create a small remaining budget.

            Timeline (max_seconds=2):
            - Call 1 (start): time=100.0, deadline=102.0, remaining=2.0 -> timeout=2.0
            - Call 2 (status): time=101.5, deadline=102.0, remaining=0.5 -> timeout=0.5
            - Call 3 (status check for loop): time=102.5, remaining=-0.5 -> triggers timeout
            """
            call_count[0] += 1
            if call_count[0] <= 2:  # Initial setup
                return 100.0
            elif call_count[0] <= 4:  # First get_job_status
                return 101.5  # 0.5s remaining
            else:  # Deadline exceeded
                return 102.5

        with patch(
            "scripts.dev.mcp_agent_client.time.monotonic",
            side_effect=mock_monotonic,
        ):
            result = cmd_wait(
                fake_client,  # type: ignore[arg-type]
                command=None,
                job_id="test-small-budget",
                max_seconds=2,
                poll_interval=0.01,
            )

        # Verify timeout status
        assert result["status"] == "timeout"

        # Key assertion: when remaining was 0.5s, the timeout should be 0.5s, NOT 1.0s
        # The second call (first get_job_status) should have received ~0.5s timeout
        assert len(timeouts_received) >= 1
        small_timeouts = [t for t in timeouts_received if t < 1.0]
        assert len(small_timeouts) > 0, (
            f"Expected at least one timeout < 1.0s when budget is low, but got: {timeouts_received}"
        )

    def test_large_remaining_budget_produces_large_timeouts(self, mock_time_sleep: Any) -> None:
        """Test that large remaining budgets produce timeouts at or above 1.0s.

        When there's plenty of budget remaining (e.g., 60s), HTTP calls
        receive the full remaining time, which naturally exceeds 1.0s.
        """
        timeouts_received: list[float] = []
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                {"status": "completed", "exit_code": 0},  # get_job_status
                {"stdout": "done", "stderr": ""},  # get_job_output
            ]
        )

        original_call = fake_client.call_server_tool

        def capturing_call(
            server: str, name: str, arguments: dict[str, Any], timeout: float = 30.0
        ) -> dict[str, Any]:
            timeouts_received.append(timeout)
            return original_call(server, name, arguments, timeout)

        fake_client.call_server_tool = capturing_call  # type: ignore[method-assign]

        # Mock time with large remaining budget
        def mock_monotonic() -> float:
            """Return time values that keep large remaining budget.

            Timeline (max_seconds=60):
            - Always return 100.0, deadline=160.0, remaining=60.0
            """
            return 100.0

        with patch(
            "scripts.dev.mcp_agent_client.time.monotonic",
            side_effect=mock_monotonic,
        ):
            result = cmd_wait(
                fake_client,  # type: ignore[arg-type]
                command=None,
                job_id="test-large-budget",
                max_seconds=60,
                poll_interval=0.01,
            )

        assert result["status"] == "completed"

        # All timeouts should be at least 1.0s when budget is large
        for timeout in timeouts_received:
            assert timeout >= 1.0, f"Expected timeout >= 1.0s but got {timeout}"

    def test_cmd_wait_respects_max_seconds_with_small_budget(self, mock_time_sleep: Any) -> None:
        """Test that cmd_wait does not significantly exceed max_seconds.

        This is an integration test that verifies the overall behavior:
        when max_seconds is small (e.g., 2s), the total HTTP call timeouts
        for status/output calls should not add up to significantly more than
        max_seconds. Note: kill_job has a hardcoded 1.0s timeout which is
        excluded from this budget check.
        """
        timeouts_received: list[tuple[str, float]] = []
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                {"status": "running"},  # get_job_status
                {},  # kill_job
            ]
        )

        original_call = fake_client.call_server_tool

        def capturing_call(
            server: str, name: str, arguments: dict[str, Any], timeout: float = 30.0
        ) -> dict[str, Any]:
            timeouts_received.append((name, timeout))
            return original_call(server, name, arguments, timeout)

        fake_client.call_server_tool = capturing_call  # type: ignore[method-assign]

        # Simulate realistic time progression where remaining drops to 0.3s
        call_count = [0]

        def mock_monotonic() -> float:
            call_count[0] += 1
            # First calls: within budget
            if call_count[0] <= 2:
                return 100.0
            # After first status check: only 0.3s remaining
            elif call_count[0] <= 4:
                return 101.7  # max_seconds=2, deadline=102, remaining=0.3
            # Deadline passed
            else:
                return 102.1

        with patch(
            "scripts.dev.mcp_agent_client.time.monotonic",
            side_effect=mock_monotonic,
        ):
            result = cmd_wait(
                fake_client,  # type: ignore[arg-type]
                command=None,
                job_id="budget-test",
                max_seconds=2,
                poll_interval=0.01,
            )

        assert result["status"] == "timeout"

        # Exclude kill_job calls (they have hardcoded 1.0s timeout)
        status_timeouts = [t for name, t in timeouts_received if name != "kill_job"]

        # The key assertion: sum of status/output timeouts should not exceed max_seconds
        # With the fix, when remaining=0.3s, we get timeout=0.3s instead of 1.0s
        total_timeout_budget = sum(status_timeouts)
        max_seconds = 2
        # Allow some tolerance for timing overhead
        assert total_timeout_budget <= max_seconds + 0.5, (
            f"Total timeout budget ({total_timeout_budget}s) significantly exceeded "
            f"max_seconds ({max_seconds}s). Timeouts: {timeouts_received}"
        )

    def test_boundary_at_exactly_one_second(self, mock_time_sleep: Any) -> None:
        """Test behavior when remaining is exactly 1.0 second.

        When remaining == 1.0s, the exact value is returned unchanged.
        """
        timeouts_received: list[tuple[str, float]] = []
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                {"status": "completed", "exit_code": 0},
                {"stdout": "", "stderr": ""},
            ]
        )

        original_call = fake_client.call_server_tool

        def capturing_call(
            server: str, name: str, arguments: dict[str, Any], timeout: float = 30.0
        ) -> dict[str, Any]:
            timeouts_received.append((name, timeout))
            return original_call(server, name, arguments, timeout)

        fake_client.call_server_tool = capturing_call  # type: ignore[method-assign]

        # Mock time so remaining is exactly 1.0s for the get_job_status call
        # deadline = start_time + max_seconds
        # We want remaining = deadline - current_time = 1.0
        # So current_time = deadline - 1.0 = start_time + max_seconds - 1.0
        call_count = [0]
        start_time = 100.0
        max_seconds_val = 5

        def mock_monotonic() -> float:
            call_count[0] += 1
            # Call 1: deadline calculation (start_time)
            if call_count[0] == 1:
                return start_time
            # Call 2+: for get_remaining_timeout during get_job_status
            # Set to (deadline - 1.0) so remaining = 1.0
            return start_time + max_seconds_val - 1.0  # 104.0

        with patch(
            "scripts.dev.mcp_agent_client.time.monotonic",
            side_effect=mock_monotonic,
        ):
            result = cmd_wait(
                fake_client,  # type: ignore[arg-type]
                command=None,
                job_id="boundary-test",
                max_seconds=max_seconds_val,
                poll_interval=0.01,
            )

        assert result["status"] == "completed"

        # At boundary (remaining=1.0), should get exactly 1.0s
        # Find the get_job_status call
        status_calls = [(name, t) for name, t in timeouts_received if name == "get_job_status"]
        assert len(status_calls) >= 1, (
            f"Expected at least one get_job_status call, got: {timeouts_received}"
        )
        boundary_timeout = status_calls[0][1]
        assert abs(boundary_timeout - 1.0) < 0.1, (
            f"Expected timeout ~1.0s at boundary, got {boundary_timeout}"
        )


class TestMissingCoverage:
    """Tests to cover missing lines and branches for complete coverage."""

    def test_cmd_list_invalid_structured_content(self) -> None:
        """Test cmd_list handles non-dict structuredContent (line 398-399).

        When structuredContent is present but not a dict, it should fail
        with an appropriate error message.
        """
        fake_client = FakeHttpMCPClient(tool_responses=[{"structuredContent": "not a dict"}])
        result = cmd_list(fake_client)  # type: ignore[arg-type]
        assert result["status"] == "failed"
        assert "Invalid response format" in result["error"]

    def test_cmd_wait_execute_command_invalid_structured_content(
        self, mock_time_sleep: Any
    ) -> None:
        """Test cmd_wait handles non-dict structuredContent from execute_command (line 313-314).

        When execute_command returns non-dict structuredContent, it should fail
        with an appropriate error message.
        """
        fake_client = FakeHttpMCPClient(
            tool_responses=[{"structuredContent": ["not", "a", "dict"]}]
        )
        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command="echo test",
            job_id=None,
            max_seconds=60,
            poll_interval=0.01,
        )
        assert result["status"] == "failed"
        assert "Invalid response format" in result["error"]

    def test_cmd_wait_get_job_status_invalid_structured_content(self, mock_time_sleep: Any) -> None:
        """Test cmd_wait handles non-dict structuredContent from get_job_status (line 340-341).

        When get_job_status returns non-dict structuredContent, it should fail
        with an appropriate error message.
        """
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                {"job_id": "job-1"},  # execute_command response
                {"structuredContent": 12345},  # get_job_status with invalid content
            ]
        )
        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command="echo test",
            job_id=None,
            max_seconds=60,
            poll_interval=0.01,
        )
        assert result["status"] == "failed"
        assert result["job_id"] == "job-1"
        assert "Invalid response format" in result["error"]

    def test_cmd_wait_timeout_while_fetching_output(self, mock_time_sleep: Any) -> None:
        """Test cmd_wait timeout during get_job_output (line 350-351).

        When the deadline expires after job completes but before fetching output,
        it should return status='timeout'.

        Timeline of time.monotonic() calls in cmd_wait:
        1. Line 278: deadline = time.monotonic() + max_seconds -> 100.0 + 10 = 110.0
        2. Line 296 (in get_remaining_timeout via line 302): remaining = deadline - time.monotonic() -> 110.0 - 100.0 = 10.0
        3. Line 296 (in get_remaining_timeout via line 322): remaining = deadline - time.monotonic() -> 110.0 - 100.0 = 10.0
        4. Line 296 (in get_remaining_timeout via line 349): remaining = deadline - time.monotonic() -> 110.0 - 200.0 = -90 (expired!)

        Call 4 happens INSIDE the if block at line 348, which is checking remaining for get_job_output.
        """
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                {"job_id": "job-1"},  # execute_command response
                {"status": "completed", "exit_code": 0},  # get_job_status response
            ]
        )

        # Mock time to expire deadline right after get_job_status (when checking for get_job_output)
        call_count = [0]

        def mock_monotonic() -> float:
            call_count[0] += 1
            # Calls 1-3: within deadline (deadline calc, pre-execute check, pre-loop check)
            if call_count[0] <= 3:
                return 100.0
            # Call 4: get_remaining_timeout() for get_job_output (line 349) - deadline expired!
            return 200.0

        with patch(
            "scripts.dev.mcp_agent_client.time.monotonic",
            side_effect=mock_monotonic,
        ):
            result = cmd_wait(
                fake_client,  # type: ignore[arg-type]
                command="echo test",
                job_id=None,
                max_seconds=10,
                poll_interval=0.01,
            )

        assert result["status"] == "timeout"
        assert result["job_id"] == "job-1"
        assert "fetching output" in result["error"]

    def test_cmd_wait_get_job_output_invalid_structured_content(self, mock_time_sleep: Any) -> None:
        """Test cmd_wait handles non-dict structuredContent from get_job_output (line 359-360).

        When get_job_output returns non-dict structuredContent, it should fail
        with an appropriate error message.
        """
        fake_client = FakeHttpMCPClient(
            tool_responses=[
                {"job_id": "job-1"},  # execute_command response
                {"status": "completed", "exit_code": 0},  # get_job_status response
                {"structuredContent": True},  # get_job_output with invalid content
            ]
        )
        result = cmd_wait(
            fake_client,  # type: ignore[arg-type]
            command="echo test",
            job_id=None,
            max_seconds=60,
            poll_interval=0.01,
        )
        assert result["status"] == "failed"
        assert result["job_id"] == "job-1"
        assert "Invalid response format" in result["error"]

    def test_main_wait_mode_missing_args(self, mocker: Any) -> None:
        """Test main exits with error when wait mode has neither command nor job-id (line 510-511).

        When wait mode is called without --command or --job-id, parser.error should be called.
        """
        mocker.patch("sys.argv", ["mcp_agent_client", "wait"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        # parser.error causes SystemExit with code 2
        assert exc_info.value.code == 2

    def test_main_value_error_exception(self, mocker: Any) -> None:
        """Test main handles ValueError exception (lines 544-547).

        When a ValueError is raised during execution, it should be caught
        and return exit code 1.
        """
        mocker.patch(
            "scripts.dev.mcp_agent_client.get_mcp_client",
            side_effect=ValueError("Invalid configuration"),
        )
        mocker.patch("sys.argv", ["mcp_agent_client", "list"])

        exit_code = main()

        assert exit_code == 1

    def test_main_keyboard_interrupt(self, mocker: Any, capsys: Any) -> None:
        """Test main handles KeyboardInterrupt (lines 549-552).

        When KeyboardInterrupt is raised, it should return exit code 130.
        """
        mocker.patch(
            "scripts.dev.mcp_agent_client.get_mcp_client",
            side_effect=KeyboardInterrupt(),
        )
        mocker.patch("sys.argv", ["mcp_agent_client", "list"])

        exit_code = main()

        assert exit_code == 130
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["status"] == "failed"
        assert "Interrupted" in output["error"]

    def test_main_mcp_client_error_exception(self, mocker: Any, capsys: Any) -> None:
        """Test main handles MCPClientError at top level (lines 539-542).

        When MCPClientError is raised from get_mcp_client, it should be caught
        and return exit code 1.
        """
        mocker.patch(
            "scripts.dev.mcp_agent_client.get_mcp_client",
            side_effect=MCPClientError("Failed to initialize client"),
        )
        mocker.patch("sys.argv", ["mcp_agent_client", "list"])

        exit_code = main()

        assert exit_code == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["status"] == "failed"
        assert "Failed to initialize client" in output["error"]
