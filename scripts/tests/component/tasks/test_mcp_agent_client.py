import json
from typing import Any

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


class TestGetMCPClient:
    def test_returns_http_client(self) -> None:
        """Test that get_mcp_client returns an HttpMCPClient."""
        client = get_mcp_client()
        assert isinstance(client, HttpMCPClient)

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


class TestCmdList:
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


class TestFormatBridgeError:
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


class TestMissingCoverage:
    def test_cmd_list_invalid_structured_content(self) -> None:
        """Test cmd_list handles non-dict structuredContent (line 398-399).

        When structuredContent is present but not a dict, it should fail
        with an appropriate error message.
        """
        fake_client = FakeHttpMCPClient(tool_responses=[{"structuredContent": "not a dict"}])
        result = cmd_list(fake_client)  # type: ignore[arg-type]
        assert result["status"] == "failed"
        assert "Invalid response format" in result["error"]
