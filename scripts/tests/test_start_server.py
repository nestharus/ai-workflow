"""Tests for scripts.start_server module."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from scripts.start_server import (
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


class TestHealthCheckStatusError:
    """Tests for HealthCheckStatusError exception."""

    def test_includes_status_code(self) -> None:
        """Should include status code in message."""
        error = HealthCheckStatusError(500)
        assert "500" in str(error)


class TestHealthPayloadTypeError:
    """Tests for HealthPayloadTypeError exception."""

    def test_has_standard_message(self) -> None:
        """Should have standard message."""
        error = HealthPayloadTypeError()
        assert "non-object" in str(error)


class TestHealthUrlSchemeError:
    """Tests for HealthUrlSchemeError exception."""

    def test_has_standard_message(self) -> None:
        """Should have standard message."""
        error = HealthUrlSchemeError()
        assert "http" in str(error)


class TestIsIpv6Host:
    """Tests for _is_ipv6_host function."""

    def test_returns_true_for_ipv6(self) -> None:
        """Should return True for IPv6 addresses."""
        assert _is_ipv6_host("::1") is True
        assert _is_ipv6_host("[::1]") is True
        assert _is_ipv6_host("2001:db8::1") is True

    def test_returns_false_for_ipv4(self) -> None:
        """Should return False for IPv4 addresses."""
        assert _is_ipv6_host("127.0.0.1") is False
        assert _is_ipv6_host("192.168.1.1") is False

    def test_returns_false_for_hostname(self) -> None:
        """Should return False for hostnames."""
        assert _is_ipv6_host("localhost") is False
        assert _is_ipv6_host("example.com") is False

    def test_returns_false_for_host_with_port(self) -> None:
        """Should return False for hostname:port (not IPv6)."""
        # This looks like it could be IPv6, but isn't valid
        assert _is_ipv6_host("invalid:port") is False


class TestNormalizeHostValue:
    """Tests for _normalize_host_value function."""

    def test_returns_none_for_none(self) -> None:
        """Should return None for None input."""
        assert _normalize_host_value(None) is None

    def test_strips_whitespace(self) -> None:
        """Should strip whitespace."""
        assert _normalize_host_value("  127.0.0.1  ") == "127.0.0.1"

    def test_returns_none_for_empty_string(self) -> None:
        """Should return None for empty string."""
        assert _normalize_host_value("") is None
        assert _normalize_host_value("   ") is None


class TestFormatHealthProbeHost:
    """Tests for _format_health_probe_host function."""

    def test_normalizes_all_interfaces_ipv4(self) -> None:
        """Should normalize 0.0.0.0 to 127.0.0.1."""
        assert _format_health_probe_host("0.0.0.0") == "127.0.0.1"  # noqa: S104

    def test_normalizes_all_interfaces_ipv6(self) -> None:
        """Should normalize :: to ::1."""
        result = _format_health_probe_host("::")
        assert "::1" in result

    def test_returns_localhost_for_empty(self) -> None:
        """Should return localhost for empty string."""
        assert _format_health_probe_host("") == "localhost"

    def test_brackets_ipv6_address(self) -> None:
        """Should add brackets to IPv6 addresses."""
        result = _format_health_probe_host("::1")
        assert result.startswith("[")
        assert result.endswith("]")


class TestResolveHost:
    """Tests for _resolve_host function."""

    def test_uses_cli_host_first(self) -> None:
        """Should use CLI host over environment."""
        args = MagicMock()
        args.host = "192.168.1.1"
        env = {"HOST": "10.0.0.1"}

        result = _resolve_host(args, env)

        assert result == "192.168.1.1"

    def test_falls_back_to_env_host(self) -> None:
        """Should fall back to environment HOST."""
        args = MagicMock()
        args.host = None
        env = {"HOST": "10.0.0.1"}

        result = _resolve_host(args, env)

        assert result == "10.0.0.1"

    def test_falls_back_to_default(self) -> None:
        """Should fall back to default host."""
        args = MagicMock()
        args.host = None
        env: dict[str, str] = {}

        result = _resolve_host(args, env)

        assert result == DEFAULT_HOST

    def test_exits_for_host_with_port(self) -> None:
        """Should exit if host contains port (not IPv6)."""
        args = MagicMock()
        args.host = "localhost:8000"
        env: dict[str, str] = {}

        with pytest.raises(SystemExit):
            _resolve_host(args, env)


class TestResolvePort:
    """Tests for _resolve_port function."""

    def test_uses_cli_port_first(self) -> None:
        """Should use CLI port over environment."""
        args = MagicMock()
        args.port = 9000
        env = {"PORT": "8080"}

        result = _resolve_port(args, env)

        assert result == 9000

    def test_falls_back_to_env_port(self) -> None:
        """Should fall back to environment PORT."""
        args = MagicMock()
        args.port = None
        env = {"PORT": "8080"}

        result = _resolve_port(args, env)

        assert result == 8080

    def test_falls_back_to_default(self) -> None:
        """Should fall back to default port."""
        args = MagicMock()
        args.port = None
        env: dict[str, str] = {}

        result = _resolve_port(args, env)

        assert result == DEFAULT_PORT

    def test_exits_for_invalid_env_port(self) -> None:
        """Should exit for non-integer PORT environment variable."""
        args = MagicMock()
        args.port = None
        env = {"PORT": "invalid"}

        with pytest.raises(SystemExit):
            _resolve_port(args, env)

    def test_exits_for_out_of_range_port(self) -> None:
        """Should exit for port outside valid range."""
        args = MagicMock()
        args.port = 0
        env: dict[str, str] = {}

        with pytest.raises(SystemExit):
            _resolve_port(args, env)

        args.port = 70000
        with pytest.raises(SystemExit):
            _resolve_port(args, env)


class TestBuildUvicornCommand:
    """Tests for _build_uvicorn_command function."""

    def test_basic_command(self) -> None:
        """Should build basic uvicorn command."""
        cmd = _build_uvicorn_command("127.0.0.1", 8000, reload_enabled=False)

        assert "uvicorn" in cmd
        assert "app.main:app" in cmd
        assert "--host" in cmd
        assert "127.0.0.1" in cmd
        assert "--port" in cmd
        assert "8000" in cmd

    def test_includes_reload_flag(self) -> None:
        """Should include --reload when enabled."""
        cmd = _build_uvicorn_command("127.0.0.1", 8000, reload_enabled=True)

        assert "--reload" in cmd

    def test_strips_brackets_from_ipv6(self) -> None:
        """Should strip brackets from IPv6 for uvicorn bind."""
        cmd = _build_uvicorn_command("[::1]", 8000, reload_enabled=False)

        assert "::1" in cmd
        assert "[::1]" not in cmd


class TestBuildParser:
    """Tests for build_parser function."""

    def test_creates_parser(self) -> None:
        """Should create argument parser."""
        parser = build_parser()
        assert parser is not None

    def test_has_host_argument(self) -> None:
        """Should have --host argument."""
        parser = build_parser()
        args = parser.parse_args(["--host", "0.0.0.0"])  # noqa: S104
        assert args.host == "0.0.0.0"  # noqa: S104

    def test_has_port_argument(self) -> None:
        """Should have --port argument."""
        parser = build_parser()
        args = parser.parse_args(["--port", "9000"])
        assert args.port == 9000

    def test_reload_and_no_reload_mutually_exclusive(self) -> None:
        """Should have mutually exclusive --reload and --no-reload."""
        parser = build_parser()

        with pytest.raises(SystemExit):
            parser.parse_args(["--reload", "--no-reload"])


class TestParseArgs:
    """Tests for parse_args function."""

    def test_parses_empty_args(self) -> None:
        """Should parse empty arguments."""
        args = parse_args([])
        assert args.host is None
        assert args.port is None
        assert args.reload is False
        assert args.skip_health_check is False


class TestRequestHealthPayload:
    """Tests for _request_health_payload function."""

    def test_raises_for_non_http_url(self) -> None:
        """Should raise HealthUrlSchemeError for non-http URL."""
        with pytest.raises(HealthUrlSchemeError):
            _request_health_payload("ftp://example.com/health")

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


class TestFormatHealthProbeHostExtended:
    """Extended tests for _format_health_probe_host function."""

    def test_handles_ipv6_with_zone_id(self) -> None:
        """Should handle IPv6 address with zone ID."""
        result = _format_health_probe_host("fe80::1%eth0")
        assert "[" in result
        assert "fe80::1" in result

    def test_brackets_hostname_with_colon(self) -> None:
        """Should return hostname with colon as is if already bracketed."""
        result = _format_health_probe_host("[::1]")
        assert result == "[::1]"

    def test_handles_plain_ipv6(self) -> None:
        """Should add brackets to plain IPv6."""
        result = _format_health_probe_host("2001:db8::1")
        assert result == "[2001:db8::1]"


class TestTerminateProcess:
    """Tests for _terminate_process function."""

    def test_does_nothing_if_already_exited(self) -> None:
        """Should do nothing if process already exited."""
        mock_process = MagicMock()
        mock_process.poll.return_value = 0  # Already exited

        _terminate_process(mock_process)

        mock_process.terminate.assert_not_called()

    def test_terminates_running_process(self) -> None:
        """Should terminate running process."""
        mock_process = MagicMock()
        mock_process.poll.side_effect = [None, 0]  # First call: running, second: exited

        _terminate_process(mock_process)

        mock_process.terminate.assert_called_once()

    def test_kills_if_terminate_times_out(self) -> None:
        """Should kill if terminate times out."""
        mock_process = MagicMock()
        mock_process.poll.side_effect = [None, None, None, None]  # Always running
        mock_process.wait.side_effect = [subprocess.TimeoutExpired("cmd", 10), None]

        _terminate_process(mock_process)

        mock_process.kill.assert_called_once()


class TestEnsureProcessRunning:
    """Tests for _ensure_process_running function."""

    def test_does_nothing_if_running(self) -> None:
        """Should do nothing if process is still running."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Still running

        # Should not raise
        _ensure_process_running(mock_process)

    def test_exits_if_process_exited(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should exit if process has exited."""
        mock_process = MagicMock()
        mock_process.poll.return_value = 1  # Exited with code 1
        mock_process.returncode = 1

        with pytest.raises(SystemExit):
            _ensure_process_running(mock_process)


class TestHandleProbeError:
    """Tests for _handle_probe_error function."""

    def test_sleeps_on_early_attempt(self) -> None:
        """Should sleep and continue on early attempts."""
        mock_process = MagicMock()
        exc = RuntimeError("Connection refused")

        with patch("time.sleep") as mock_sleep:
            # Attempt 1 of 5 (not last)
            _handle_probe_error(1, exc, mock_process)

        mock_sleep.assert_called_once()
        mock_process.terminate.assert_not_called()

    def test_exits_on_final_attempt(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should exit on final attempt."""
        mock_process = MagicMock()
        mock_process.poll.side_effect = [None, 0]
        exc = RuntimeError("Connection refused")

        with pytest.raises(SystemExit):
            _handle_probe_error(HEALTH_CHECK_RETRIES, exc, mock_process)


class TestHandleUnexpectedPayload:
    """Tests for _handle_unexpected_payload function."""

    def test_sleeps_on_early_attempt(self) -> None:
        """Should sleep and continue on early attempts."""
        mock_process = MagicMock()

        with patch("time.sleep") as mock_sleep:
            _handle_unexpected_payload(1, mock_process)

        mock_sleep.assert_called_once()

    def test_exits_on_final_attempt(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should exit on final attempt."""
        mock_process = MagicMock()
        mock_process.poll.side_effect = [None, 0]

        with pytest.raises(SystemExit):
            _handle_unexpected_payload(HEALTH_CHECK_RETRIES, mock_process)


class TestLaunchUvicorn:
    """Tests for _launch_uvicorn function."""

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


class TestWaitForProcess:
    """Tests for _wait_for_process function."""

    def test_returns_exit_code(self) -> None:
        """Should return process exit code."""
        mock_process = MagicMock()
        mock_process.wait.return_value = 0
        mock_process.poll.return_value = 0  # Already exited

        result = _wait_for_process(mock_process)

        assert result == 0

    def test_terminates_running_process_in_finally(self) -> None:
        """Should terminate process if still running after wait."""
        mock_process = MagicMock()
        mock_process.wait.return_value = 0
        # First poll (in finally): running, second poll (in _terminate_process): still running
        # third poll (after terminate): exited
        mock_process.poll.side_effect = [None, None, 0]

        _wait_for_process(mock_process)

        mock_process.terminate.assert_called()


class TestPerformHealthCheck:
    """Tests for perform_health_check function."""

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


class TestFormatHealthProbeHostNonIpv6Colon:
    """Tests for non-IPv6 hosts with colons in _format_health_probe_host."""

    def test_returns_bracketed_host_as_is(self) -> None:
        """Should return already bracketed non-IPv6 host as-is."""
        # A bracketed hostname that isn't actually valid IPv6
        result = _format_health_probe_host("[some:host]")
        assert result == "[some:host]"

    def test_adds_brackets_to_host_with_colon(self) -> None:
        """Should add brackets to non-IPv6 host containing colon."""
        # This isn't valid IPv6, but has colon - will be bracketed
        # First we need a case that passes _is_ipv6_host check as False
        # but still has a colon
        result = _format_health_probe_host("[invalid:host:pattern]")
        assert result == "[invalid:host:pattern]"

    def test_brackets_unbracketed_host_with_colon(self) -> None:
        """Should add brackets to unbracketed host with colon."""
        # An unbracketed hostname with a colon that isn't valid IPv6
        result = _format_health_probe_host("host:port")
        assert result == "[host:port]"


class TestInstallSignalHandlers:
    """Tests for _install_signal_handlers function."""

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
    """Tests for main function."""

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
