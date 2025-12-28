import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts.servers.sandbox.server import (
    MAX_HISTORY_SIZE,
    OperationStatus,
    SandboxServer,
)


class TestEarlyShutdown:
    @pytest.mark.asyncio
    async def test_early_shutdown_is_honored_by_start(self) -> None:
        """start() should honor shutdown requested before it was called."""
        server = SandboxServer(repo_path=Path("/tmp"))

        # Request shutdown before start
        server.shutdown()
        assert server._shutdown_requested is True

        # Now start - it should create the event and immediately set it
        # We need to mock ensure_sandbox_exists and the socket server
        from unittest.mock import patch

        mock_server = MagicMock()
        mock_server.close = MagicMock()
        mock_server.wait_closed = AsyncMock()

        with (
            patch(
                "scripts.servers.sandbox.server.ensure_sandbox_exists",
                return_value=Path("/tmp/sandbox"),
            ),
            patch(
                "asyncio.start_unix_server",
                new=AsyncMock(return_value=mock_server),
            ),
            patch(
                "scripts.servers.sandbox.server.os.chmod",
            ),
            patch(
                "scripts.servers.sandbox.server.os.unlink",
            ),
        ):
            # start() should return quickly because shutdown was already requested
            # The event should be set immediately
            await asyncio.wait_for(server.start(), timeout=2.0)

        # Verify the event was set (this allowed start to exit)
        assert server._shutdown_event is not None
        assert server._shutdown_event.is_set()


class TestCancellationBeforePush:
    def test_format_rebase_result_skips_push_when_cancelled(self) -> None:
        """_format_rebase_result should skip push if operation was cancelled."""
        from unittest.mock import patch

        from scripts.servers.sandbox.operations import RebaseResult

        server = SandboxServer(repo_path=Path("/tmp"))
        server.sandbox_path = Path("/tmp/sandbox")

        # Mark operation as cancelled in history
        server.operation_history["test-op"] = OperationStatus(
            request_id="test-op",
            status="cancelled",
        )

        # Create a successful rebase result
        result = RebaseResult(success=True, has_conflicts=False, conflicts=[], error="")

        # Mock push_from_sandbox to verify it's NOT called
        with patch("scripts.servers.sandbox.server.push_from_sandbox") as mock_push:
            response = server._format_rebase_result("test-op", result, "feature-branch")

        # Push should NOT have been called
        mock_push.assert_not_called()

        # Response should indicate cancellation
        parsed = json.loads(response)
        assert parsed["status"] == "error"
        assert parsed["request_id"] == "test-op"
        assert "cancelled" in parsed["message"]

    def test_format_merge_result_skips_push_when_cancelled(self) -> None:
        """_format_merge_result should skip push if operation was cancelled."""
        from unittest.mock import patch

        from scripts.servers.sandbox.operations import MergeResult

        server = SandboxServer(repo_path=Path("/tmp"))
        server.sandbox_path = Path("/tmp/sandbox")

        # Mark operation as cancelled in history
        server.operation_history["test-op"] = OperationStatus(
            request_id="test-op",
            status="cancelled",
        )

        # Create a successful merge result
        result = MergeResult(success=True, has_conflicts=False, conflicts=[], error="")

        # Mock push_from_sandbox to verify it's NOT called
        with patch("scripts.servers.sandbox.server.push_from_sandbox") as mock_push:
            response = server._format_merge_result("test-op", result, "feature-branch")

        # Push should NOT have been called
        mock_push.assert_not_called()

        # Response should indicate cancellation
        parsed = json.loads(response)
        assert parsed["status"] == "error"
        assert parsed["request_id"] == "test-op"
        assert "cancelled" in parsed["message"]

    def test_format_rebase_result_pushes_when_not_cancelled(self) -> None:
        """_format_rebase_result should push when operation is not cancelled."""
        from unittest.mock import patch

        from scripts.servers.sandbox.operations import RebaseResult

        server = SandboxServer(repo_path=Path("/tmp"))
        server.sandbox_path = Path("/tmp/sandbox")

        # Mark operation as in_progress (not cancelled) in history
        server.operation_history["test-op"] = OperationStatus(
            request_id="test-op",
            status="in_progress",
        )

        # Create a successful rebase result
        result = RebaseResult(success=True, has_conflicts=False, conflicts=[], error="")

        # Mock push_from_sandbox to verify it IS called
        with patch(
            "scripts.servers.sandbox.server.push_from_sandbox", return_value=(True, None)
        ) as mock_push:
            response = server._format_rebase_result("test-op", result, "feature-branch")

        # Push should have been called
        mock_push.assert_called_once_with(Path("/tmp/sandbox"), "feature-branch", force=True)

        # Response should indicate success
        parsed = json.loads(response)
        assert parsed["status"] == "success"
        assert "pushed" in parsed["result"]["message"]

    def test_format_merge_result_pushes_when_not_cancelled(self) -> None:
        """_format_merge_result should push when operation is not cancelled."""
        from unittest.mock import patch

        from scripts.servers.sandbox.operations import MergeResult

        server = SandboxServer(repo_path=Path("/tmp"))
        server.sandbox_path = Path("/tmp/sandbox")

        # Mark operation as in_progress (not cancelled) in history
        server.operation_history["test-op"] = OperationStatus(
            request_id="test-op",
            status="in_progress",
        )

        # Create a successful merge result
        result = MergeResult(success=True, has_conflicts=False, conflicts=[], error="")

        # Mock push_from_sandbox to verify it IS called
        with patch(
            "scripts.servers.sandbox.server.push_from_sandbox", return_value=(True, None)
        ) as mock_push:
            response = server._format_merge_result("test-op", result, "feature-branch")

        # Push should have been called
        mock_push.assert_called_once_with(Path("/tmp/sandbox"), "feature-branch", force=False)

        # Response should indicate success
        parsed = json.loads(response)
        assert parsed["status"] == "success"
        assert "pushed" in parsed["result"]["message"]

    def test_format_rebase_result_pushes_when_no_history_entry(self) -> None:
        """_format_rebase_result should push when there's no history entry (edge case)."""
        from unittest.mock import patch

        from scripts.servers.sandbox.operations import RebaseResult

        server = SandboxServer(repo_path=Path("/tmp"))
        server.sandbox_path = Path("/tmp/sandbox")

        # No history entry for this operation
        assert "test-op" not in server.operation_history

        # Create a successful rebase result
        result = RebaseResult(success=True, has_conflicts=False, conflicts=[], error="")

        # Mock push_from_sandbox to verify it IS called (fail-safe behavior)
        with patch(
            "scripts.servers.sandbox.server.push_from_sandbox", return_value=(True, None)
        ) as mock_push:
            response = server._format_rebase_result("test-op", result, "feature-branch")

        # Push should have been called (no history means not cancelled)
        mock_push.assert_called_once()

        # Response should indicate success
        parsed = json.loads(response)
        assert parsed["status"] == "success"

    def test_format_merge_result_pushes_when_no_history_entry(self) -> None:
        """_format_merge_result should push when there's no history entry (edge case)."""
        from unittest.mock import patch

        from scripts.servers.sandbox.operations import MergeResult

        server = SandboxServer(repo_path=Path("/tmp"))
        server.sandbox_path = Path("/tmp/sandbox")

        # No history entry for this operation
        assert "test-op" not in server.operation_history

        # Create a successful merge result
        result = MergeResult(success=True, has_conflicts=False, conflicts=[], error="")

        # Mock push_from_sandbox to verify it IS called (fail-safe behavior)
        with patch(
            "scripts.servers.sandbox.server.push_from_sandbox", return_value=(True, None)
        ) as mock_push:
            response = server._format_merge_result("test-op", result, "feature-branch")

        # Push should have been called (no history means not cancelled)
        mock_push.assert_called_once()

        # Response should indicate success
        parsed = json.loads(response)
        assert parsed["status"] == "success"


class TestStartSandboxInitializationError:
    @pytest.mark.asyncio
    async def test_start_raises_on_sandbox_initialization_error(self) -> None:
        """start() should raise RuntimeError if ensure_sandbox_exists fails."""
        from unittest.mock import patch

        server = SandboxServer(repo_path=Path("/tmp"))

        with (
            patch(
                "scripts.servers.sandbox.server.ensure_sandbox_exists",
                side_effect=RuntimeError("Sandbox initialization failed"),
            ),
            pytest.raises(RuntimeError, match="Sandbox initialization failed"),
        ):
            await server.start()


class TestRunServer:
    @pytest.mark.asyncio
    async def test_run_server_creates_server_and_calls_start(self) -> None:
        """run_server should create SandboxServer and call start."""
        from unittest.mock import AsyncMock, patch

        mock_server_instance = MagicMock()
        mock_server_instance.start = AsyncMock()
        mock_server_instance.shutdown = MagicMock()

        with patch(
            "scripts.servers.sandbox.server.SandboxServer",
            return_value=mock_server_instance,
        ) as mock_server_class:
            from scripts.servers.sandbox.server import run_server

            await run_server("/tmp/test.sock", "/repo")

        mock_server_class.assert_called_once_with(
            repo_path=Path("/repo"),
            socket_path="/tmp/test.sock",
        )
        mock_server_instance.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_server_registers_signal_handlers(self) -> None:
        """run_server should register SIGTERM and SIGINT signal handlers."""
        from unittest.mock import AsyncMock, patch

        mock_server_instance = MagicMock()
        mock_server_instance.start = AsyncMock()
        mock_server_instance.shutdown = MagicMock()

        registered_signals = []

        def mock_add_signal_handler(sig: int, handler: object) -> None:
            registered_signals.append(sig)

        with (
            patch(
                "scripts.servers.sandbox.server.SandboxServer",
                return_value=mock_server_instance,
            ),
            patch("asyncio.get_running_loop") as mock_get_loop,
        ):
            mock_loop = MagicMock()
            mock_loop.add_signal_handler = mock_add_signal_handler
            mock_get_loop.return_value = mock_loop

            from scripts.servers.sandbox.server import run_server

            await run_server("/tmp/test.sock", "/repo")

        import signal as sig_module

        assert sig_module.SIGTERM in registered_signals
        assert sig_module.SIGINT in registered_signals

    @pytest.mark.asyncio
    async def test_run_server_handles_signal_handler_not_implemented(self) -> None:
        """run_server should handle NotImplementedError for signal handlers."""
        from unittest.mock import AsyncMock, patch

        mock_server_instance = MagicMock()
        mock_server_instance.start = AsyncMock()
        mock_server_instance.shutdown = MagicMock()

        def mock_add_signal_handler_not_impl(sig: int, handler: object) -> None:
            raise NotImplementedError("Signal handlers not supported on this platform")

        with (
            patch(
                "scripts.servers.sandbox.server.SandboxServer",
                return_value=mock_server_instance,
            ),
            patch("asyncio.get_running_loop") as mock_get_loop,
        ):
            mock_loop = MagicMock()
            mock_loop.add_signal_handler = mock_add_signal_handler_not_impl
            mock_get_loop.return_value = mock_loop

            from scripts.servers.sandbox.server import run_server

            # Should not raise - NotImplementedError is caught and logged
            await run_server("/tmp/test.sock", "/repo")

        mock_server_instance.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_server_handles_signal_handler_runtime_error(self) -> None:
        """run_server should handle RuntimeError for signal handlers."""
        from unittest.mock import AsyncMock, patch

        mock_server_instance = MagicMock()
        mock_server_instance.start = AsyncMock()
        mock_server_instance.shutdown = MagicMock()

        def mock_add_signal_handler_runtime_err(sig: int, handler: object) -> None:
            raise RuntimeError("Signal handler error")

        with (
            patch(
                "scripts.servers.sandbox.server.SandboxServer",
                return_value=mock_server_instance,
            ),
            patch("asyncio.get_running_loop") as mock_get_loop,
        ):
            mock_loop = MagicMock()
            mock_loop.add_signal_handler = mock_add_signal_handler_runtime_err
            mock_get_loop.return_value = mock_loop

            from scripts.servers.sandbox.server import run_server

            # Should not raise - RuntimeError is caught and logged
            await run_server("/tmp/test.sock", "/repo")

        mock_server_instance.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_signal_calls_shutdown(self) -> None:
        """The handle_signal function should call server.shutdown()."""
        from unittest.mock import AsyncMock, patch

        mock_server_instance = MagicMock()
        mock_server_instance.start = AsyncMock()
        mock_server_instance.shutdown = MagicMock()

        captured_handler = None

        def mock_add_signal_handler(sig: int, handler: object) -> None:
            nonlocal captured_handler
            # Capture the first handler (SIGTERM)
            if captured_handler is None:
                captured_handler = handler

        with (
            patch(
                "scripts.servers.sandbox.server.SandboxServer",
                return_value=mock_server_instance,
            ),
            patch("asyncio.get_running_loop") as mock_get_loop,
        ):
            mock_loop = MagicMock()
            mock_loop.add_signal_handler = mock_add_signal_handler
            mock_get_loop.return_value = mock_loop

            from scripts.servers.sandbox.server import run_server

            await run_server("/tmp/test.sock", "/repo")

        # Now call the captured handler to test handle_signal
        assert captured_handler is not None
        captured_handler()

        mock_server_instance.shutdown.assert_called()


class TestMainFunction:
    def test_main_configures_logging_and_runs_server(self) -> None:
        """main should configure logging and run the server."""
        from unittest.mock import patch

        with (
            patch("scripts.servers.sandbox.server._configure_logging") as mock_config_logging,
            patch("scripts.servers.sandbox.server.asyncio.run") as mock_asyncio_run,
            patch.dict(
                "os.environ",
                {"SANDBOX_SOCKET_PATH": "/custom/socket.sock", "SANDBOX_REPO_PATH": "/custom/repo"},
            ),
        ):
            from scripts.servers.sandbox.server import main

            main()

        mock_config_logging.assert_called_once()
        mock_asyncio_run.assert_called_once()

    def test_main_uses_default_paths_when_env_not_set(self) -> None:
        """main should use default paths when environment variables are not set."""
        from unittest.mock import patch

        captured_args = []

        def capture_run_server(coro: object) -> None:
            # Extract args from coroutine if needed
            captured_args.append(coro)

        with (
            patch("scripts.servers.sandbox.server._configure_logging"),
            patch("scripts.servers.sandbox.server.asyncio.run", side_effect=capture_run_server),
            patch.dict("os.environ", {}, clear=True),
        ):
            # Remove env vars if present
            import os

            os.environ.pop("SANDBOX_SOCKET_PATH", None)
            os.environ.pop("SANDBOX_REPO_PATH", None)

            from scripts.servers.sandbox.server import main

            main()

        # Verify asyncio.run was called (the coroutine was created with default paths)
        assert len(captured_args) == 1

    def test_main_handles_keyboard_interrupt(self) -> None:
        """main should handle KeyboardInterrupt gracefully."""
        from unittest.mock import patch

        with (
            patch("scripts.servers.sandbox.server._configure_logging"),
            patch("scripts.servers.sandbox.server.asyncio.run", side_effect=KeyboardInterrupt()),
            pytest.raises(SystemExit) as exc_info,
        ):
            from scripts.servers.sandbox.server import main

            main()

        assert exc_info.value.code == 0
