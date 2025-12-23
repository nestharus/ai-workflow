"""Tests for sandbox_status_command function."""

from __future__ import annotations

from unittest.mock import patch

from scripts.pr.commands.sandbox_status_command import sandbox_status_command
from scripts.servers.sandbox.client import DEFAULT_SOCKET_PATH
from scripts.servers.sandbox.protocol import (
    ErrorResponse,
    ProgressResponse,
    QueuedResponse,
    SuccessResponse,
)


class TestSandboxStatusCommand:
    """Tests for sandbox_status_command function."""

    def test_uses_default_socket_path(self) -> None:
        """Should use DEFAULT_SOCKET_PATH when socket_path is None."""
        mock_response = SuccessResponse(request_id="test-123", result={"status": "ok"})

        with patch("scripts.servers.sandbox.client.get_status") as mock_get:
            mock_get.return_value = mock_response
            sandbox_status_command(request_id=None, socket_path=None)

        # Verify DEFAULT_SOCKET_PATH was used
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["socket_path"] == DEFAULT_SOCKET_PATH

    def test_returns_zero_on_success(self, capsys) -> None:
        """Should return 0 for SuccessResponse."""
        mock_response = SuccessResponse(request_id="test-123", result={"status": "done"})

        with patch("scripts.servers.sandbox.client.get_status") as mock_get:
            mock_get.return_value = mock_response
            result = sandbox_status_command()

        assert result == 0
        captured = capsys.readouterr()
        assert "SUCCESS" in captured.out

    def test_returns_one_on_error_response(self, capsys) -> None:
        """Should return 1 for ErrorResponse."""
        mock_response = ErrorResponse(request_id="test-123", message="Not found")

        with patch("scripts.servers.sandbox.client.get_status") as mock_get:
            mock_get.return_value = mock_response
            result = sandbox_status_command()

        assert result == 1
        captured = capsys.readouterr()
        assert "ERROR" in captured.out

    def test_returns_one_on_client_error(self, capsys) -> None:
        """Should return 1 on SandboxClientError."""
        from scripts.servers.sandbox.client import SandboxClientError

        with patch("scripts.servers.sandbox.client.get_status") as mock_get:
            mock_get.side_effect = SandboxClientError("Socket not found")
            result = sandbox_status_command()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: Socket not found" in captured.err

    def test_passes_request_id_correctly(self) -> None:
        """Should pass request_id to get_status."""
        mock_response = SuccessResponse(request_id="specific-req", result={})

        with patch("scripts.servers.sandbox.client.get_status") as mock_get:
            mock_get.return_value = mock_response
            sandbox_status_command(request_id="specific-req")

        mock_get.assert_called_once_with(
            request_id="specific-req",
            socket_path=mock_get.call_args[1]["socket_path"],
        )

    def test_passes_none_request_id_for_all_status(self) -> None:
        """Should pass None request_id for all operations status."""
        mock_response = SuccessResponse(request_id="all", result={})

        with patch("scripts.servers.sandbox.client.get_status") as mock_get:
            mock_get.return_value = mock_response
            sandbox_status_command(request_id=None)

        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["request_id"] is None

    def test_prints_formatted_response(self, capsys) -> None:
        """Should print formatted response."""
        mock_response = SuccessResponse(
            request_id="test-123", result={"message": "Operation complete"}
        )

        with patch("scripts.servers.sandbox.client.get_status") as mock_get:
            mock_get.return_value = mock_response
            sandbox_status_command()

        captured = capsys.readouterr()
        assert "SUCCESS" in captured.out

    def test_returns_zero_for_queued_response(self, capsys) -> None:
        """Should return 0 for QueuedResponse (not an error)."""
        mock_response = QueuedResponse(request_id="test-123", position=2)

        with patch("scripts.servers.sandbox.client.get_status") as mock_get:
            mock_get.return_value = mock_response
            result = sandbox_status_command()

        assert result == 0
        captured = capsys.readouterr()
        assert "QUEUED" in captured.out

    def test_returns_zero_for_progress_response(self, capsys) -> None:
        """Should return 0 for ProgressResponse (not an error)."""
        mock_response = ProgressResponse(request_id="test-123", message="Working...")

        with patch("scripts.servers.sandbox.client.get_status") as mock_get:
            mock_get.return_value = mock_response
            result = sandbox_status_command()

        assert result == 0
        captured = capsys.readouterr()
        assert "IN PROGRESS" in captured.out
