"""Tests for sandbox client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts.servers.sandbox.client import (
    SandboxClientError,
    _connect,
    _send_request,
    _wait_for_completion,
    format_response,
    get_status,
    send_merge,
    send_rebase,
)
from scripts.servers.sandbox.protocol import (
    ConflictResponse,
    ErrorResponse,
    ProgressResponse,
    QueuedResponse,
    SuccessResponse,
)


class TestConnect:
    """Tests for _connect function."""

    def test_raises_on_missing_socket(self) -> None:
        """Raise SandboxClientError when socket file doesn't exist."""
        with patch("socket.socket") as mock_socket_class:
            mock_socket = MagicMock()
            mock_socket.connect.side_effect = FileNotFoundError()
            mock_socket_class.return_value = mock_socket

            with pytest.raises(SandboxClientError, match="not found"):
                _connect("/tmp/test.sock")

    def test_raises_on_connection_refused(self) -> None:
        """Raise SandboxClientError when connection is refused."""
        with patch("socket.socket") as mock_socket_class:
            mock_socket = MagicMock()
            mock_socket.connect.side_effect = ConnectionRefusedError()
            mock_socket_class.return_value = mock_socket

            with pytest.raises(SandboxClientError, match="refused"):
                _connect("/tmp/test.sock")

    def test_closes_socket_on_connect_failure(self) -> None:
        """Close socket when connect fails to prevent socket leak."""
        with patch("socket.socket") as mock_socket_class:
            mock_socket = MagicMock()
            mock_socket.connect.side_effect = ConnectionRefusedError()
            mock_socket_class.return_value = mock_socket

            with pytest.raises(SandboxClientError):
                _connect("/tmp/test.sock")

            mock_socket.close.assert_called_once()

    def test_closes_socket_on_settimeout_failure(self) -> None:
        """Close socket when settimeout fails to prevent socket leak."""
        with patch("socket.socket") as mock_socket_class:
            mock_socket = MagicMock()
            mock_socket.settimeout.side_effect = OSError("timeout error")
            mock_socket_class.return_value = mock_socket

            with pytest.raises(SandboxClientError):
                _connect("/tmp/test.sock")

            mock_socket.close.assert_called_once()


class TestSendRequest:
    """Tests for _send_request function."""

    def test_sends_and_receives(self) -> None:
        """Send request and receive response."""
        mock_socket = MagicMock()
        mock_socket.recv.return_value = b'{"status": "success", "request_id": "test"}\n'

        response = _send_request(mock_socket, '{"command": "status"}')

        mock_socket.sendall.assert_called_once()
        assert "success" in response

    def test_raises_on_empty_response(self) -> None:
        """Raise SandboxClientError when no response."""
        mock_socket = MagicMock()
        mock_socket.recv.return_value = b""

        with pytest.raises(SandboxClientError, match="No response"):
            _send_request(mock_socket, '{"command": "status"}')

    def test_raises_on_timeout(self) -> None:
        """Raise SandboxClientError on socket timeout."""
        mock_socket = MagicMock()
        mock_socket.recv.side_effect = TimeoutError()

        with pytest.raises(SandboxClientError, match="timeout"):
            _send_request(mock_socket, '{"command": "status"}')

    def test_raises_on_connection_closed_before_newline(self) -> None:
        """Raise SandboxClientError when connection closes before newline."""
        mock_socket = MagicMock()
        # Simulate partial data received, then connection closed
        mock_socket.recv.side_effect = [b'{"status": "succ', b""]

        with pytest.raises(SandboxClientError, match="Connection closed before newline"):
            _send_request(mock_socket, '{"command": "status"}')

    def test_excludes_bytes_after_newline(self) -> None:
        """Return only the first message when extra bytes follow the newline."""
        mock_socket = MagicMock()
        # Simulate receiving a complete message plus bytes from next message
        mock_socket.recv.return_value = (
            b'{"status": "success", "request_id": "test"}\n{"status": "next_msg"}'
        )

        response = _send_request(mock_socket, '{"command": "status"}')

        # Should only contain the first message, not the extra bytes
        assert response == '{"status": "success", "request_id": "test"}'
        assert "next_msg" not in response

    def test_raises_on_invalid_utf8(self) -> None:
        """Raise SandboxClientError when response contains invalid UTF-8."""
        mock_socket = MagicMock()
        # Invalid UTF-8 bytes (0xff is not valid in UTF-8)
        mock_socket.recv.return_value = b"\xff\xfe\n"

        with pytest.raises(SandboxClientError, match="Invalid UTF-8"):
            _send_request(mock_socket, '{"command": "status"}')


class TestSendRebase:
    """Tests for send_rebase function."""

    def test_returns_success_response(self) -> None:
        """Return success response from server."""
        with patch("scripts.servers.sandbox.client._connect") as mock_connect:
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            # Mock immediate success (not queued)
            success_json = '{"status": "success", "request_id": "test", "result": {}}\n'
            mock_socket.recv.return_value = success_json.encode()

            response = send_rebase(
                branch="feature-x",
                target="main",
                socket_path="/tmp/test.sock",
                wait=False,
            )

            assert isinstance(response, SuccessResponse)
            mock_socket.close.assert_called_once()

    def test_returns_conflict_response(self) -> None:
        """Return conflict response from server."""
        with patch("scripts.servers.sandbox.client._connect") as mock_connect:
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            conflict_json = '{"status": "conflict", "request_id": "test", "files": ["file.py"]}\n'
            mock_socket.recv.return_value = conflict_json.encode()

            response = send_rebase(
                branch="feature-x",
                target="main",
                socket_path="/tmp/test.sock",
                wait=False,
            )

            assert isinstance(response, ConflictResponse)
            assert response.files == ["file.py"]


class TestSendRebaseWait:
    """Tests for send_rebase when wait=True."""

    def test_waits_for_progress_response(self) -> None:
        """Wait for completion when server returns ProgressResponse."""
        with (
            patch("scripts.servers.sandbox.client._connect") as mock_connect,
            patch("scripts.servers.sandbox.client._wait_for_completion") as mock_wait,
        ):
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            # Server returns ProgressResponse (operation already in progress)
            progress_json = (
                '{"status": "in_progress", "request_id": "test", "message": "Working"}\n'
            )
            mock_socket.recv.return_value = progress_json.encode()

            # _wait_for_completion returns success
            mock_wait.return_value = SuccessResponse(request_id="test", result={"message": "done"})

            response = send_rebase(
                branch="feature-x",
                target="main",
                socket_path="/tmp/test.sock",
                wait=True,
            )

            assert isinstance(response, SuccessResponse)
            mock_wait.assert_called_once()

    def test_waits_for_queued_response(self) -> None:
        """Wait for completion when server returns QueuedResponse."""
        with (
            patch("scripts.servers.sandbox.client._connect") as mock_connect,
            patch("scripts.servers.sandbox.client._wait_for_completion") as mock_wait,
        ):
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            queued_json = '{"status": "queued", "request_id": "test", "position": 2}\n'
            mock_socket.recv.return_value = queued_json.encode()

            mock_wait.return_value = SuccessResponse(request_id="test", result={"message": "done"})

            response = send_rebase(
                branch="feature-x",
                target="main",
                socket_path="/tmp/test.sock",
                wait=True,
            )

            assert isinstance(response, SuccessResponse)
            mock_wait.assert_called_once()

    def test_returns_progress_response_when_not_waiting(self) -> None:
        """Return ProgressResponse immediately when wait=False."""
        with patch("scripts.servers.sandbox.client._connect") as mock_connect:
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            progress_json = (
                '{"status": "in_progress", "request_id": "test", "message": "Working"}\n'
            )
            mock_socket.recv.return_value = progress_json.encode()

            response = send_rebase(
                branch="feature-x",
                target="main",
                socket_path="/tmp/test.sock",
                wait=False,
            )

            assert isinstance(response, ProgressResponse)

    def test_verbose_output_for_queued_response(self, capsys) -> None:
        """Print queued position when verbose=True."""
        with (
            patch("scripts.servers.sandbox.client._connect") as mock_connect,
            patch("scripts.servers.sandbox.client._wait_for_completion") as mock_wait,
        ):
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            queued_json = '{"status": "queued", "request_id": "test", "position": 5}\n'
            mock_socket.recv.return_value = queued_json.encode()

            mock_wait.return_value = SuccessResponse(request_id="test", result={})

            send_rebase(
                branch="feature-x",
                target="main",
                socket_path="/tmp/test.sock",
                wait=True,
                verbose=True,
            )

            captured = capsys.readouterr()
            assert "queued" in captured.out.lower()
            assert "5" in captured.out

    def test_verbose_output_for_progress_response(self, capsys) -> None:
        """Print progress message when verbose=True."""
        with (
            patch("scripts.servers.sandbox.client._connect") as mock_connect,
            patch("scripts.servers.sandbox.client._wait_for_completion") as mock_wait,
        ):
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            progress_json = (
                '{"status": "in_progress", "request_id": "test", "message": "Rebasing..."}\n'
            )
            mock_socket.recv.return_value = progress_json.encode()

            mock_wait.return_value = SuccessResponse(request_id="test", result={})

            send_rebase(
                branch="feature-x",
                target="main",
                socket_path="/tmp/test.sock",
                wait=True,
                verbose=True,
            )

            captured = capsys.readouterr()
            assert "Rebasing" in captured.out


class TestSendRebaseInvalidResponse:
    """Tests for send_rebase handling invalid server responses."""

    def test_raises_client_error_on_invalid_json(self) -> None:
        """Raise SandboxClientError when server returns invalid JSON."""
        with patch("scripts.servers.sandbox.client._connect") as mock_connect:
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            # Return invalid JSON
            mock_socket.recv.return_value = b"not valid json\n"

            with pytest.raises(SandboxClientError, match="Invalid response from server"):
                send_rebase(
                    branch="feature-x",
                    target="main",
                    socket_path="/tmp/test.sock",
                    wait=False,
                )

            mock_socket.close.assert_called_once()

    def test_raises_client_error_on_unknown_status(self) -> None:
        """Raise SandboxClientError when server returns unknown status."""
        with patch("scripts.servers.sandbox.client._connect") as mock_connect:
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            # Return valid JSON but unknown status
            mock_socket.recv.return_value = b'{"status": "unknown_status", "request_id": "test"}\n'

            with pytest.raises(SandboxClientError, match="Invalid response from server"):
                send_rebase(
                    branch="feature-x",
                    target="main",
                    socket_path="/tmp/test.sock",
                    wait=False,
                )


class TestSendMerge:
    """Tests for send_merge function."""

    def test_returns_success_response(self) -> None:
        """Return success response from server."""
        with patch("scripts.servers.sandbox.client._connect") as mock_connect:
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            success_json = '{"status": "success", "request_id": "test", "result": {}}\n'
            mock_socket.recv.return_value = success_json.encode()

            response = send_merge(
                branch="feature-x",
                target="main",
                socket_path="/tmp/test.sock",
                wait=False,
            )

            assert isinstance(response, SuccessResponse)


class TestSendMergeWait:
    """Tests for send_merge when wait=True."""

    def test_waits_for_progress_response(self) -> None:
        """Wait for completion when server returns ProgressResponse."""
        with (
            patch("scripts.servers.sandbox.client._connect") as mock_connect,
            patch("scripts.servers.sandbox.client._wait_for_completion") as mock_wait,
        ):
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            # Server returns ProgressResponse (operation already in progress)
            progress_json = (
                '{"status": "in_progress", "request_id": "test", "message": "Working"}\n'
            )
            mock_socket.recv.return_value = progress_json.encode()

            # _wait_for_completion returns success
            mock_wait.return_value = SuccessResponse(request_id="test", result={"message": "done"})

            response = send_merge(
                branch="feature-x",
                target="main",
                socket_path="/tmp/test.sock",
                wait=True,
            )

            assert isinstance(response, SuccessResponse)
            mock_wait.assert_called_once()

    def test_waits_for_queued_response(self) -> None:
        """Wait for completion when server returns QueuedResponse."""
        with (
            patch("scripts.servers.sandbox.client._connect") as mock_connect,
            patch("scripts.servers.sandbox.client._wait_for_completion") as mock_wait,
        ):
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            queued_json = '{"status": "queued", "request_id": "test", "position": 2}\n'
            mock_socket.recv.return_value = queued_json.encode()

            mock_wait.return_value = SuccessResponse(request_id="test", result={"message": "done"})

            response = send_merge(
                branch="feature-x",
                target="main",
                socket_path="/tmp/test.sock",
                wait=True,
            )

            assert isinstance(response, SuccessResponse)
            mock_wait.assert_called_once()

    def test_returns_progress_response_when_not_waiting(self) -> None:
        """Return ProgressResponse immediately when wait=False."""
        with patch("scripts.servers.sandbox.client._connect") as mock_connect:
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            progress_json = (
                '{"status": "in_progress", "request_id": "test", "message": "Working"}\n'
            )
            mock_socket.recv.return_value = progress_json.encode()

            response = send_merge(
                branch="feature-x",
                target="main",
                socket_path="/tmp/test.sock",
                wait=False,
            )

            assert isinstance(response, ProgressResponse)

    def test_verbose_output_for_queued_response(self, capsys) -> None:
        """Print queued position when verbose=True."""
        with (
            patch("scripts.servers.sandbox.client._connect") as mock_connect,
            patch("scripts.servers.sandbox.client._wait_for_completion") as mock_wait,
        ):
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            queued_json = '{"status": "queued", "request_id": "test", "position": 3}\n'
            mock_socket.recv.return_value = queued_json.encode()

            mock_wait.return_value = SuccessResponse(request_id="test", result={})

            send_merge(
                branch="feature-x",
                target="main",
                socket_path="/tmp/test.sock",
                wait=True,
                verbose=True,
            )

            captured = capsys.readouterr()
            assert "queued" in captured.out.lower()
            assert "3" in captured.out

    def test_verbose_output_for_progress_response(self, capsys) -> None:
        """Print progress message when verbose=True."""
        with (
            patch("scripts.servers.sandbox.client._connect") as mock_connect,
            patch("scripts.servers.sandbox.client._wait_for_completion") as mock_wait,
        ):
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            progress_json = (
                '{"status": "in_progress", "request_id": "test", "message": "Merging..."}\n'
            )
            mock_socket.recv.return_value = progress_json.encode()

            mock_wait.return_value = SuccessResponse(request_id="test", result={})

            send_merge(
                branch="feature-x",
                target="main",
                socket_path="/tmp/test.sock",
                wait=True,
                verbose=True,
            )

            captured = capsys.readouterr()
            assert "Merging" in captured.out


class TestSendMergeInvalidResponse:
    """Tests for send_merge handling invalid server responses."""

    def test_raises_client_error_on_invalid_json(self) -> None:
        """Raise SandboxClientError when server returns invalid JSON."""
        with patch("scripts.servers.sandbox.client._connect") as mock_connect:
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            # Return invalid JSON
            mock_socket.recv.return_value = b"not valid json\n"

            with pytest.raises(SandboxClientError, match="Invalid response from server"):
                send_merge(
                    branch="feature-x",
                    target="main",
                    socket_path="/tmp/test.sock",
                    wait=False,
                )

            mock_socket.close.assert_called_once()


class TestNonObjectJsonResponse:
    """Tests for handling valid JSON that is not an object."""

    def test_send_rebase_raises_on_json_array(self) -> None:
        """Raise SandboxClientError when server returns JSON array instead of object."""
        with patch("scripts.servers.sandbox.client._connect") as mock_connect:
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            # Return valid JSON but not an object
            mock_socket.recv.return_value = b'["not", "an", "object"]\n'

            with pytest.raises(SandboxClientError, match="Invalid response from server"):
                send_rebase(
                    branch="feature-x",
                    target="main",
                    socket_path="/tmp/test.sock",
                    wait=False,
                )

            mock_socket.close.assert_called_once()

    def test_send_merge_raises_on_json_string(self) -> None:
        """Raise SandboxClientError when server returns JSON string instead of object."""
        with patch("scripts.servers.sandbox.client._connect") as mock_connect:
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            # Return valid JSON but a string
            mock_socket.recv.return_value = b'"just a string"\n'

            with pytest.raises(SandboxClientError, match="Invalid response from server"):
                send_merge(
                    branch="feature-x",
                    target="main",
                    socket_path="/tmp/test.sock",
                    wait=False,
                )

            mock_socket.close.assert_called_once()

    def test_get_status_raises_on_json_number(self) -> None:
        """Raise SandboxClientError when server returns JSON number instead of object."""
        with patch("scripts.servers.sandbox.client._connect") as mock_connect:
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            # Return valid JSON but a number
            mock_socket.recv.return_value = b"42\n"

            with pytest.raises(SandboxClientError, match="Invalid response from server"):
                get_status(socket_path="/tmp/test.sock")

            mock_socket.close.assert_called_once()


class TestGetStatus:
    """Tests for get_status function."""

    def test_gets_status_for_request_id(self) -> None:
        """Get status for specific request ID."""
        with patch("scripts.servers.sandbox.client._connect") as mock_connect:
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            status_json = '{"status": "success", "request_id": "test-id", "result": {}}\n'
            mock_socket.recv.return_value = status_json.encode()

            response = get_status(
                request_id="test-id",
                socket_path="/tmp/test.sock",
            )

            assert isinstance(response, SuccessResponse)
            assert response.request_id == "test-id"

    def test_gets_all_statuses(self) -> None:
        """Get status for all operations."""
        with patch("scripts.servers.sandbox.client._connect") as mock_connect:
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            status_json = (
                '{"status": "success", "request_id": "status", "result": {"queue_size": 0}}\n'
            )
            mock_socket.recv.return_value = status_json.encode()

            response = get_status(socket_path="/tmp/test.sock")

            assert isinstance(response, SuccessResponse)


class TestGetStatusInvalidResponse:
    """Tests for get_status handling invalid server responses."""

    def test_raises_client_error_on_invalid_json(self) -> None:
        """Raise SandboxClientError when server returns invalid JSON."""
        with patch("scripts.servers.sandbox.client._connect") as mock_connect:
            mock_socket = MagicMock()
            mock_connect.return_value = mock_socket

            # Return invalid JSON
            mock_socket.recv.return_value = b"not valid json\n"

            with pytest.raises(SandboxClientError, match="Invalid response from server"):
                get_status(socket_path="/tmp/test.sock")

            mock_socket.close.assert_called_once()


class TestFormatResponse:
    """Tests for format_response function."""

    def test_format_success(self) -> None:
        """Format success response."""
        response = SuccessResponse(
            request_id="test",
            result={"message": "done"},
        )

        output = format_response(response)

        assert "SUCCESS" in output
        assert "done" in output

    def test_format_success_without_message_field(self) -> None:
        """Format success response when result has no 'message' field."""
        response = SuccessResponse(
            request_id="test",
            result={"data": "some_value", "count": 42},
        )

        output = format_response(response)

        assert "SUCCESS" in output
        # Should JSON dump the result
        assert "data" in output
        assert "some_value" in output

    def test_format_conflict(self) -> None:
        """Format conflict response."""
        response = ConflictResponse(
            request_id="test",
            files=["file1.py", "file2.py"],
        )

        output = format_response(response)

        assert "CONFLICT" in output
        assert "file1.py" in output

    def test_format_queued(self) -> None:
        """Format queued response."""
        response = QueuedResponse(
            request_id="test",
            position=3,
        )

        output = format_response(response)

        assert "QUEUED" in output
        assert "3" in output

    def test_format_error(self) -> None:
        """Format error response."""
        response = ErrorResponse(
            request_id="test",
            message="Something failed",
        )

        output = format_response(response)

        assert "ERROR" in output
        assert "Something failed" in output

    def test_format_progress(self) -> None:
        """Format progress response."""
        response = ProgressResponse(
            request_id="test",
            message="Working on it",
        )

        output = format_response(response)

        assert "IN PROGRESS" in output
        assert "Working on it" in output

    def test_format_unknown_response_type(self) -> None:
        """Format unknown response type."""
        # Create a mock response that doesn't match any known type
        unknown_response = MagicMock()
        unknown_response.__class__.__name__ = "UnknownResponse"

        output = format_response(unknown_response)

        assert "UNKNOWN" in output


class TestWaitForCompletion:
    """Tests for _wait_for_completion function."""

    def test_returns_success_on_immediate_completion(self) -> None:
        """Return success response when operation completes immediately."""
        mock_socket = MagicMock()

        with patch("scripts.servers.sandbox.client.get_status") as mock_get_status:
            mock_get_status.return_value = SuccessResponse(
                request_id="test-id",
                result={"message": "done"},
            )

            response = _wait_for_completion(
                sock=mock_socket,
                request_id="test-id",
                socket_path="/tmp/test.sock",
                verbose=False,
            )

            assert isinstance(response, SuccessResponse)
            mock_socket.close.assert_called_once()

    def test_returns_error_on_timeout(self) -> None:
        """Return error response when max_wait is exceeded."""
        mock_socket = MagicMock()

        with (
            patch("scripts.servers.sandbox.client.get_status") as mock_get_status,
            patch("scripts.servers.sandbox.client.time.sleep"),
            patch("scripts.servers.sandbox.client.time.monotonic") as mock_monotonic,
        ):
            # Simulate time progression: start at 0, then check at 6 seconds (past max_wait)
            mock_monotonic.side_effect = [0.0, 6.0]
            mock_get_status.return_value = ProgressResponse(
                request_id="test-id",
                message="Still working",
            )

            response = _wait_for_completion(
                sock=mock_socket,
                request_id="test-id",
                socket_path="/tmp/test.sock",
                verbose=False,
                max_wait=5.0,
            )

            assert isinstance(response, ErrorResponse)
            assert "Timeout" in response.message
            assert "5.0 seconds" in response.message

    def test_polls_until_success(self) -> None:
        """Poll status until success response is received."""
        mock_socket = MagicMock()

        with (
            patch("scripts.servers.sandbox.client.get_status") as mock_get_status,
            patch("scripts.servers.sandbox.client.time.sleep"),
            patch("scripts.servers.sandbox.client.time.monotonic") as mock_monotonic,
        ):
            # Simulate time: start, first check, second check
            mock_monotonic.side_effect = [0.0, 1.0, 2.0]
            mock_get_status.side_effect = [
                ProgressResponse(request_id="test-id", message="Working"),
                SuccessResponse(request_id="test-id", result={}),
            ]

            response = _wait_for_completion(
                sock=mock_socket,
                request_id="test-id",
                socket_path="/tmp/test.sock",
                verbose=False,
            )

            assert isinstance(response, SuccessResponse)
            assert mock_get_status.call_count == 2

    def test_returns_conflict_response(self) -> None:
        """Return conflict response when operation has conflicts."""
        mock_socket = MagicMock()

        with patch("scripts.servers.sandbox.client.get_status") as mock_get_status:
            mock_get_status.return_value = ConflictResponse(
                request_id="test-id",
                files=["file.py"],
            )

            response = _wait_for_completion(
                sock=mock_socket,
                request_id="test-id",
                socket_path="/tmp/test.sock",
                verbose=False,
            )

            assert isinstance(response, ConflictResponse)
            assert response.files == ["file.py"]

    def test_continues_polling_on_client_error(self) -> None:
        """Continue polling when get_status raises SandboxClientError."""
        mock_socket = MagicMock()

        with (
            patch("scripts.servers.sandbox.client.get_status") as mock_get_status,
            patch("scripts.servers.sandbox.client.time.sleep"),
            patch("scripts.servers.sandbox.client.time.monotonic") as mock_monotonic,
        ):
            mock_monotonic.side_effect = [0.0, 1.0, 2.0]
            mock_get_status.side_effect = [
                SandboxClientError("Connection failed"),
                SuccessResponse(request_id="test-id", result={}),
            ]

            response = _wait_for_completion(
                sock=mock_socket,
                request_id="test-id",
                socket_path="/tmp/test.sock",
                verbose=False,
            )

            assert isinstance(response, SuccessResponse)
            assert mock_get_status.call_count == 2

    def test_clamps_non_positive_initial_interval_to_minimum(self) -> None:
        """Clamp non-positive initial_interval to minimum to avoid busy-wait."""
        mock_socket = MagicMock()

        with (
            patch("scripts.servers.sandbox.client.get_status") as mock_get_status,
            patch("scripts.servers.sandbox.client.time.sleep") as mock_sleep,
        ):
            mock_get_status.return_value = SuccessResponse(
                request_id="test-id",
                result={},
            )

            response = _wait_for_completion(
                sock=mock_socket,
                request_id="test-id",
                socket_path="/tmp/test.sock",
                verbose=False,
                initial_interval=-5.0,  # Negative value should be clamped
            )

            assert isinstance(response, SuccessResponse)
            # First sleep call should use clamped value (1e-3), not negative or zero
            first_sleep_arg = mock_sleep.call_args_list[0][0][0]
            assert first_sleep_arg >= 1e-3

    def test_clamps_zero_initial_interval_to_minimum(self) -> None:
        """Clamp zero initial_interval to minimum to avoid busy-wait."""
        mock_socket = MagicMock()

        with (
            patch("scripts.servers.sandbox.client.get_status") as mock_get_status,
            patch("scripts.servers.sandbox.client.time.sleep") as mock_sleep,
        ):
            mock_get_status.return_value = SuccessResponse(
                request_id="test-id",
                result={},
            )

            response = _wait_for_completion(
                sock=mock_socket,
                request_id="test-id",
                socket_path="/tmp/test.sock",
                verbose=False,
                initial_interval=0.0,  # Zero should be clamped to avoid busy-wait
            )

            assert isinstance(response, SuccessResponse)
            # First sleep call should use clamped value (1e-3), not zero
            first_sleep_arg = mock_sleep.call_args_list[0][0][0]
            assert first_sleep_arg >= 1e-3


class TestMainStatusExitCodes:
    """Tests for main() status command exit codes."""

    def test_status_returns_zero_on_success(self) -> None:
        """Return exit code 0 when status returns SuccessResponse."""
        from scripts.servers.sandbox.client import main

        with (
            patch("sys.argv", ["client", "status", "--request-id", "test-id"]),
            patch("scripts.servers.sandbox.client.get_status") as mock_get_status,
        ):
            mock_get_status.return_value = SuccessResponse(
                request_id="test-id",
                result={"message": "done"},
            )

            exit_code = main()

            assert exit_code == 0

    def test_status_returns_one_on_error(self) -> None:
        """Return exit code 1 when status returns ErrorResponse."""
        from scripts.servers.sandbox.client import main

        with (
            patch("sys.argv", ["client", "status", "--request-id", "unknown-id"]),
            patch("scripts.servers.sandbox.client.get_status") as mock_get_status,
        ):
            mock_get_status.return_value = ErrorResponse(
                request_id="unknown-id",
                message="Request ID not found",
            )

            exit_code = main()

            assert exit_code == 1

    def test_status_returns_zero_on_queued(self) -> None:
        """Return exit code 0 when status returns QueuedResponse."""
        from scripts.servers.sandbox.client import main

        with (
            patch("sys.argv", ["client", "status", "--request-id", "test-id"]),
            patch("scripts.servers.sandbox.client.get_status") as mock_get_status,
        ):
            mock_get_status.return_value = QueuedResponse(
                request_id="test-id",
                position=2,
            )

            exit_code = main()

            assert exit_code == 0

    def test_status_returns_zero_on_progress(self) -> None:
        """Return exit code 0 when status returns ProgressResponse."""
        from scripts.servers.sandbox.client import main

        with (
            patch("sys.argv", ["client", "status", "--request-id", "test-id"]),
            patch("scripts.servers.sandbox.client.get_status") as mock_get_status,
        ):
            mock_get_status.return_value = ProgressResponse(
                request_id="test-id",
                message="Working on it",
            )

            exit_code = main()

            assert exit_code == 0


class TestMainRebaseExitCodes:
    """Tests for main() rebase command exit codes."""

    def test_rebase_returns_zero_on_success(self) -> None:
        """Return exit code 0 when rebase returns SuccessResponse."""
        from scripts.servers.sandbox.client import main

        with (
            patch(
                "sys.argv",
                ["client", "rebase", "--branch", "feature", "--target", "main"],
            ),
            patch("scripts.servers.sandbox.client.send_rebase") as mock_send_rebase,
        ):
            mock_send_rebase.return_value = SuccessResponse(
                request_id="test-id",
                result={"message": "Rebase complete"},
            )

            exit_code = main()

            assert exit_code == 0

    def test_rebase_returns_two_on_conflict(self) -> None:
        """Return exit code 2 when rebase returns ConflictResponse."""
        from scripts.servers.sandbox.client import main

        with (
            patch(
                "sys.argv",
                ["client", "rebase", "--branch", "feature", "--target", "main"],
            ),
            patch("scripts.servers.sandbox.client.send_rebase") as mock_send_rebase,
        ):
            mock_send_rebase.return_value = ConflictResponse(
                request_id="test-id",
                files=["file.py"],
            )

            exit_code = main()

            assert exit_code == 2

    def test_rebase_returns_one_on_error(self) -> None:
        """Return exit code 1 when rebase returns ErrorResponse."""
        from scripts.servers.sandbox.client import main

        with (
            patch(
                "sys.argv",
                ["client", "rebase", "--branch", "feature", "--target", "main"],
            ),
            patch("scripts.servers.sandbox.client.send_rebase") as mock_send_rebase,
        ):
            mock_send_rebase.return_value = ErrorResponse(
                request_id="test-id",
                message="Rebase failed",
            )

            exit_code = main()

            assert exit_code == 1


class TestMainMergeExitCodes:
    """Tests for main() merge command exit codes."""

    def test_merge_returns_zero_on_success(self) -> None:
        """Return exit code 0 when merge returns SuccessResponse."""
        from scripts.servers.sandbox.client import main

        with (
            patch(
                "sys.argv",
                ["client", "merge", "--branch", "feature", "--target", "main"],
            ),
            patch("scripts.servers.sandbox.client.send_merge") as mock_send_merge,
        ):
            mock_send_merge.return_value = SuccessResponse(
                request_id="test-id",
                result={"message": "Merge complete"},
            )

            exit_code = main()

            assert exit_code == 0

    def test_merge_returns_two_on_conflict(self) -> None:
        """Return exit code 2 when merge returns ConflictResponse."""
        from scripts.servers.sandbox.client import main

        with (
            patch(
                "sys.argv",
                ["client", "merge", "--branch", "feature", "--target", "main"],
            ),
            patch("scripts.servers.sandbox.client.send_merge") as mock_send_merge,
        ):
            mock_send_merge.return_value = ConflictResponse(
                request_id="test-id",
                files=["file.py"],
            )

            exit_code = main()

            assert exit_code == 2

    def test_merge_returns_one_on_error(self) -> None:
        """Return exit code 1 when merge returns ErrorResponse."""
        from scripts.servers.sandbox.client import main

        with (
            patch(
                "sys.argv",
                ["client", "merge", "--branch", "feature", "--target", "main"],
            ),
            patch("scripts.servers.sandbox.client.send_merge") as mock_send_merge,
        ):
            mock_send_merge.return_value = ErrorResponse(
                request_id="test-id",
                message="Merge failed",
            )

            exit_code = main()

            assert exit_code == 1


class TestMainSandboxClientError:
    """Tests for main() handling SandboxClientError."""

    def test_rebase_returns_one_on_sandbox_client_error(self, capsys) -> None:
        """Return exit code 1 and print error when SandboxClientError is raised."""
        from scripts.servers.sandbox.client import main

        with (
            patch(
                "sys.argv",
                ["client", "rebase", "--branch", "feature", "--target", "main"],
            ),
            patch("scripts.servers.sandbox.client.send_rebase") as mock_send_rebase,
        ):
            mock_send_rebase.side_effect = SandboxClientError("Server not running")

            exit_code = main()

            assert exit_code == 1
            captured = capsys.readouterr()
            assert "Error" in captured.err
            assert "Server not running" in captured.err

    def test_merge_returns_one_on_sandbox_client_error(self, capsys) -> None:
        """Return exit code 1 and print error when SandboxClientError is raised."""
        from scripts.servers.sandbox.client import main

        with (
            patch(
                "sys.argv",
                ["client", "merge", "--branch", "feature", "--target", "main"],
            ),
            patch("scripts.servers.sandbox.client.send_merge") as mock_send_merge,
        ):
            mock_send_merge.side_effect = SandboxClientError("Connection refused")

            exit_code = main()

            assert exit_code == 1
            captured = capsys.readouterr()
            assert "Error" in captured.err
            assert "Connection refused" in captured.err

    def test_status_returns_one_on_sandbox_client_error(self, capsys) -> None:
        """Return exit code 1 and print error when SandboxClientError is raised."""
        from scripts.servers.sandbox.client import main

        with (
            patch("sys.argv", ["client", "status", "--request-id", "test-id"]),
            patch("scripts.servers.sandbox.client.get_status") as mock_get_status,
        ):
            mock_get_status.side_effect = SandboxClientError("Socket not found")

            exit_code = main()

            assert exit_code == 1
            captured = capsys.readouterr()
            assert "Error" in captured.err
            assert "Socket not found" in captured.err
