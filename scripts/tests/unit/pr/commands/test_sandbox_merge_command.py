"""Tests for sandbox_merge_command function."""

from __future__ import annotations

from unittest.mock import patch

from scripts.pr.commands.sandbox_merge_command import sandbox_merge_command
from scripts.servers.sandbox.protocol import (
    ConflictResponse,
    ErrorResponse,
    SuccessResponse,
)


class TestSandboxMergeCommand:
    """Tests for sandbox_merge_command function."""

    def test_uses_default_socket_path(self, mock_sandbox_git_dao_refs_match) -> None:
        """Should use DEFAULT_SOCKET_PATH when socket_path is None."""
        mock_response = SuccessResponse(request_id="test-123", result={"message": "ok"})

        with patch("scripts.pr.commands.sandbox_merge_command.send_merge") as mock_send:
            mock_send.return_value = mock_response
            sandbox_merge_command("feature", "main", socket_path=None)

        # Verify DEFAULT_SOCKET_PATH was used
        call_kwargs = mock_send.call_args[1]
        from scripts.servers.sandbox.client import DEFAULT_SOCKET_PATH

        assert call_kwargs["socket_path"] == DEFAULT_SOCKET_PATH

    def test_returns_zero_on_success(self, capsys, mock_sandbox_git_dao_refs_match) -> None:
        """Should return 0 for SuccessResponse."""
        mock_response = SuccessResponse(request_id="test-123", result={"message": "Merged"})

        with patch("scripts.pr.commands.sandbox_merge_command.send_merge") as mock_send:
            mock_send.return_value = mock_response
            result = sandbox_merge_command("feature", "main")

        assert result == 0
        captured = capsys.readouterr()
        assert "SUCCESS" in captured.out

    def test_returns_two_on_conflict(self, capsys, mock_sandbox_git_dao_refs_match) -> None:
        """Should return 2 for ConflictResponse."""
        mock_response = ConflictResponse(request_id="test-123", files=["file1.py", "file2.py"])

        with patch("scripts.pr.commands.sandbox_merge_command.send_merge") as mock_send:
            mock_send.return_value = mock_response
            result = sandbox_merge_command("feature", "main")

        assert result == 2
        captured = capsys.readouterr()
        assert "CONFLICT" in captured.out
        assert "file1.py" in captured.out

    def test_returns_one_on_error_response(self, capsys, mock_sandbox_git_dao_refs_match) -> None:
        """Should return 1 for ErrorResponse."""
        mock_response = ErrorResponse(request_id="test-123", message="Something went wrong")

        with patch("scripts.pr.commands.sandbox_merge_command.send_merge") as mock_send:
            mock_send.return_value = mock_response
            result = sandbox_merge_command("feature", "main")

        assert result == 1
        captured = capsys.readouterr()
        assert "ERROR" in captured.out

    def test_returns_one_on_client_error(self, capsys, mock_sandbox_git_dao_refs_match) -> None:
        """Should return 1 on SandboxClientError."""
        from scripts.servers.sandbox.client import SandboxClientError

        with patch("scripts.pr.commands.sandbox_merge_command.send_merge") as mock_send:
            mock_send.side_effect = SandboxClientError("Connection refused")
            result = sandbox_merge_command("feature", "main")

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: Connection refused" in captured.err

    def test_passes_correct_parameters(self, mock_sandbox_git_dao_refs_match) -> None:
        """Should pass branch, target, socket_path, wait, and verbose correctly."""
        mock_response = SuccessResponse(request_id="test-123", result={})

        with patch("scripts.pr.commands.sandbox_merge_command.send_merge") as mock_send:
            mock_send.return_value = mock_response
            sandbox_merge_command(
                branch="my-branch",
                target="develop",
                socket_path="/custom/socket",
                verbose=True,
            )

        mock_send.assert_called_once_with(
            branch="my-branch",
            target="develop",
            socket_path="/custom/socket",
            wait=True,
            verbose=True,
        )

    def test_prints_formatted_response(self, capsys, mock_sandbox_git_dao_refs_match) -> None:
        """Should print formatted response."""
        mock_response = SuccessResponse(request_id="test-123", result={"message": "Merge complete"})

        with patch("scripts.pr.commands.sandbox_merge_command.send_merge") as mock_send:
            mock_send.return_value = mock_response
            sandbox_merge_command("feature", "main")

        captured = capsys.readouterr()
        assert "SUCCESS" in captured.out
        assert "Merge complete" in captured.out
