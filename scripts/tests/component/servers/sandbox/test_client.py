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


class TestSendRequest:
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


class TestFormatResponse:
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
