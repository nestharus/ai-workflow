from unittest.mock import MagicMock, patch

import pytest

from scripts.app.start_server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    HEALTH_CHECK_RETRIES,
    HealthCheckStatusError,
    HealthPayloadTypeError,
    HealthUrlSchemeError,
    _build_uvicorn_command,
    _ensure_process_running,
    _format_health_probe_host,
    _handle_probe_error,
    _handle_unexpected_payload,
    _install_signal_handlers,
    _is_ipv6_host,
    _launch_uvicorn,
    _normalize_host_value,
    _request_health_payload,
    _resolve_host,
    _resolve_port,
    _terminate_process,
    _wait_for_process,
    build_parser,
    main,
    parse_args,
    perform_health_check,
)


class TestRequestHealthPayload:
    def test_raises_for_non_200_status(self) -> None:
        """Should raise HealthCheckStatusError for non-200 status."""
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.read.return_value = b'{"status": "error"}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch("urllib.request.urlopen", return_value=mock_response),
            pytest.raises(HealthCheckStatusError),
        ):
            _request_health_payload("http://localhost:8000/health")

    def test_raises_for_non_object_payload(self) -> None:
        """Should raise HealthPayloadTypeError for non-object payload."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'"just a string"'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch("urllib.request.urlopen", return_value=mock_response),
            pytest.raises(HealthPayloadTypeError),
        ):
            _request_health_payload("http://localhost:8000/health")

    def test_returns_payload_on_success(self) -> None:
        """Should return payload dict on success."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"status": "ok"}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = _request_health_payload("http://localhost:8000/health")

        assert result == {"status": "ok"}


class TestHandleProbeError:
    def test_sleeps_on_early_attempt(self) -> None:
        """Should sleep and continue on early attempts."""
        mock_process = MagicMock()
        exc = RuntimeError("Connection refused")

        with patch("time.sleep") as mock_sleep:
            # Attempt 1 of 5 (not last)
            _handle_probe_error(1, exc, mock_process)

        mock_sleep.assert_called_once()
        mock_process.terminate.assert_not_called()


class TestHandleUnexpectedPayload:
    def test_sleeps_on_early_attempt(self) -> None:
        """Should sleep and continue on early attempts."""
        mock_process = MagicMock()

        with patch("time.sleep") as mock_sleep:
            _handle_unexpected_payload(1, mock_process)

        mock_sleep.assert_called_once()


class TestLaunchUvicorn:
    def test_launches_process(self) -> None:
        """Should launch uvicorn process."""
        mock_popen = MagicMock()
        with patch("subprocess.Popen", return_value=mock_popen) as mock_popen_class:
            result = _launch_uvicorn(["uvicorn", "app:main"], {"PATH": "/usr/bin"})

        mock_popen_class.assert_called_once()
        assert result == mock_popen

    def test_exits_for_file_not_found(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should exit when uvicorn not found."""
        with (
            patch("subprocess.Popen", side_effect=FileNotFoundError("uvicorn")),
            pytest.raises(SystemExit),
        ):
            _launch_uvicorn(["uvicorn", "app:main"], {})

    def test_exits_for_os_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should exit on OS error."""
        with (
            patch("subprocess.Popen", side_effect=OSError("Permission denied")),
            pytest.raises(SystemExit),
        ):
            _launch_uvicorn(["uvicorn", "app:main"], {})


class TestPerformHealthCheck:
    def test_succeeds_on_healthy_response(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should succeed when health endpoint returns ok."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Running

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"status": "ok"}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("time.sleep"), patch("urllib.request.urlopen", return_value=mock_response):
            perform_health_check("127.0.0.1", 8000, mock_process)

        captured = capsys.readouterr()
        assert "healthy" in captured.out

    def test_retries_on_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should retry on connection errors."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Running

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"status": "ok"}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch("time.sleep"),
            patch(
                "urllib.request.urlopen",
                side_effect=[OSError("Connection refused"), mock_response],
            ),
        ):
            perform_health_check("127.0.0.1", 8000, mock_process)

    def test_handles_unexpected_payload(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should handle unexpected status in payload."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Running

        mock_response_bad = MagicMock()
        mock_response_bad.status = 200
        mock_response_bad.read.return_value = b'{"status": "error"}'
        mock_response_bad.__enter__ = MagicMock(return_value=mock_response_bad)
        mock_response_bad.__exit__ = MagicMock(return_value=False)

        mock_response_ok = MagicMock()
        mock_response_ok.status = 200
        mock_response_ok.read.return_value = b'{"status": "ok"}'
        mock_response_ok.__enter__ = MagicMock(return_value=mock_response_ok)
        mock_response_ok.__exit__ = MagicMock(return_value=False)

        with (
            patch("time.sleep"),
            patch(
                "urllib.request.urlopen",
                side_effect=[mock_response_bad, mock_response_ok],
            ),
        ):
            perform_health_check("127.0.0.1", 8000, mock_process)

    def test_handles_missing_status_key(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should handle payload with no status key (branch at line 334)."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Running

        # Response with no "status" key - triggers branch at 334 where status != "ok"
        mock_response_no_status = MagicMock()
        mock_response_no_status.status = 200
        mock_response_no_status.read.return_value = b'{"other": "data"}'
        mock_response_no_status.__enter__ = MagicMock(return_value=mock_response_no_status)
        mock_response_no_status.__exit__ = MagicMock(return_value=False)

        mock_response_ok = MagicMock()
        mock_response_ok.status = 200
        mock_response_ok.read.return_value = b'{"status": "ok"}'
        mock_response_ok.__enter__ = MagicMock(return_value=mock_response_ok)
        mock_response_ok.__exit__ = MagicMock(return_value=False)

        with (
            patch("time.sleep"),
            patch(
                "urllib.request.urlopen",
                side_effect=[mock_response_no_status, mock_response_ok],
            ),
        ):
            perform_health_check("127.0.0.1", 8000, mock_process)

        captured = capsys.readouterr()
        # Should still succeed after retry
        assert "healthy" in captured.out

    def test_loop_iterates_all_attempts_on_errors(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that the for loop at line 321 iterates through all attempts."""
        mock_process = MagicMock()
        mock_process.poll.side_effect = [None, None, 0]  # Running, then exit on final

        # All attempts fail with connection errors until exhausted
        with (
            patch("time.sleep"),
            patch(
                "urllib.request.urlopen",
                side_effect=[OSError("Connection refused")] * HEALTH_CHECK_RETRIES,
            ),
            pytest.raises(SystemExit),
        ):
            perform_health_check("127.0.0.1", 8000, mock_process)


class TestInstallSignalHandlers:
    def test_installs_sigint_handler(self) -> None:
        """Should install SIGINT handler."""

        mock_process = MagicMock()

        with patch("signal.signal") as mock_signal:
            _install_signal_handlers(mock_process)

        # Should be called for both SIGINT and SIGTERM
        assert mock_signal.call_count == 2

    def test_forward_signal_sends_to_running_process(self) -> None:
        """Should forward signal to running process."""
        import signal

        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Running

        # Capture the handler
        handlers: dict[int, object] = {}

        def capture_handler(signum: int, handler: object) -> None:
            handlers[signum] = handler

        with patch("signal.signal", side_effect=capture_handler):
            _install_signal_handlers(mock_process)

        # Call the handler
        assert callable(handlers[signal.SIGINT])
        handlers[signal.SIGINT](signal.SIGINT, None)  # type: ignore[operator]

        mock_process.send_signal.assert_called_once_with(signal.SIGINT)

    def test_forward_signal_skips_exited_process(self) -> None:
        """Should not send signal if process already exited."""
        import signal

        mock_process = MagicMock()
        mock_process.poll.return_value = 0  # Exited

        handlers: dict[int, object] = {}

        def capture_handler(signum: int, handler: object) -> None:
            handlers[signum] = handler

        with patch("signal.signal", side_effect=capture_handler):
            _install_signal_handlers(mock_process)

        assert callable(handlers[signal.SIGINT])
        handlers[signal.SIGINT](signal.SIGINT, None)  # type: ignore[operator]

        mock_process.send_signal.assert_not_called()


class TestMain:
    def test_launches_server_with_health_check(self) -> None:
        """Should launch server and perform health check."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.wait.return_value = 0

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"status": "ok"}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch("subprocess.Popen", return_value=mock_process),
            patch("signal.signal"),
            patch("time.sleep"),
            patch("urllib.request.urlopen", return_value=mock_response),
            pytest.raises(SystemExit) as exc_info,
        ):
            main([])

        assert exc_info.value.code == 0

    def test_skips_health_check_when_flag_set(self) -> None:
        """Should skip health check when --skip-health-check is set."""
        mock_process = MagicMock()
        mock_process.poll.return_value = 0
        mock_process.wait.return_value = 0

        with (
            patch("subprocess.Popen", return_value=mock_process),
            patch("signal.signal"),
            patch("urllib.request.urlopen") as mock_urlopen,
            pytest.raises(SystemExit),
        ):
            main(["--skip-health-check"])

        # Health check should not have been called
        mock_urlopen.assert_not_called()

    def test_exits_with_process_exit_code(self) -> None:
        """Should exit with the process exit code."""
        mock_process = MagicMock()
        mock_process.poll.return_value = 42
        mock_process.wait.return_value = 42

        with (
            patch("subprocess.Popen", return_value=mock_process),
            patch("signal.signal"),
            pytest.raises(SystemExit) as exc_info,
        ):
            main(["--skip-health-check"])

        assert exc_info.value.code == 42
