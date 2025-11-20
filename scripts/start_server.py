"""Launch the AI Workflow API server with CLI controls and health validation."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import suppress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

# Bind to loopback by default for safer local development; pass --host 0.0.0.0
# (or another interface) explicitly when exposing the service outside localhost.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
HEALTH_CHECK_DELAY = 5
HEALTH_CHECK_RETRIES = 3
HEALTH_CHECK_INTERVAL = 2


class HealthCheckStatusError(RuntimeError):
    """Raised when the health endpoint returns a non-200 status."""

    def __init__(self, status: int) -> None:
        """Store the unexpected status code."""
        super().__init__(f"Unexpected status {status}")


class HealthPayloadTypeError(TypeError):
    """Raised when the health endpoint payload is not a JSON object."""

    _MESSAGE = "Unexpected non-object payload"

    def __str__(self) -> str:  # pragma: no cover - trivial
        """Return the validation message."""
        return self._MESSAGE


class HealthUrlSchemeError(ValueError):
    """Raised when a health probe URL uses an unsupported scheme."""

    _MESSAGE = "Health URL must use http or https"

    def __str__(self) -> str:  # pragma: no cover - trivial
        """Return the validation message."""
        return self._MESSAGE


def _format_health_probe_host(host: str) -> str:
    """Return a host suitable for health-check URLs, normalizing wildcards."""
    hostname = host.strip() or "localhost"
    if hostname == "0.0.0.0":  # noqa: S104
        hostname = "127.0.0.1"
    elif hostname in {"::", "[::]"}:
        hostname = "::1"

    if _is_ipv6_host(hostname):
        bracketed_input = hostname.startswith("[") and hostname.endswith("]")
        inner_host = hostname[1:-1] if bracketed_input else hostname
        # Link-local zone IDs need URL-safe encoding: accept bracketed/unbracketed
        # input, replace "%25" with "%" to support already-encoded hosts, then
        # unquote and re-quote the zone id with safe="" and prefix "%25" so the
        # separator stays encoded while producing a URL-safe suffix.
        split_target = inner_host.replace("%25", "%")

        zone_suffix = ""
        address = split_target
        if "%" in split_target:
            address, zone_id = split_target.split("%", 1)
            normalized_zone = urllib.parse.quote(urllib.parse.unquote(zone_id), safe="")
            zone_suffix = f"%25{normalized_zone}"

        return f"[{address}{zone_suffix}]"

    if ":" in hostname:
        if hostname.startswith("[") and hostname.endswith("]"):
            return hostname
        return f"[{hostname}]"

    return hostname


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser for the start-server script."""
    parser = argparse.ArgumentParser(
        description="Launch the AI Workflow API server via Uvicorn with health checks."
    )
    parser.add_argument(
        "--host",
        help=(
            "Server bind address (default: env HOST or 127.0.0.1 for local runs; "
            "pass 0.0.0.0 to listen on all interfaces)."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Server port (default: env PORT or 8000).",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--reload",
        action="store_true",
        help="Enable autoreload; useful for development.",
    )
    group.add_argument(
        "--no-reload",
        action="store_true",
        help="Explicitly disable autoreload.",
    )
    parser.add_argument(
        "--skip-health-check",
        action="store_true",
        help="Skip the post-start health probe (not recommended).",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse and validate CLI arguments."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    with suppress(OSError):
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        with suppress(OSError):
            process.kill()
        with suppress(subprocess.TimeoutExpired, OSError):
            process.wait(timeout=5)


def _ensure_process_running(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        return
    print("Uvicorn process exited before health check completed.", file=sys.stderr)
    sys.exit(process.returncode)


def _request_health_payload(url: str) -> dict[str, Any]:
    # url is always a fixed http://.../health endpoint, so urllib here is safe.
    if not url.startswith(("http://", "https://")):
        raise HealthUrlSchemeError()

    with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310
        if response.status != 200:
            raise HealthCheckStatusError(response.status)
        payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise HealthPayloadTypeError()
        return payload


def _handle_probe_error(attempt: int, exc: Exception, process: subprocess.Popen[bytes]) -> None:
    if attempt == HEALTH_CHECK_RETRIES:
        print(
            f"Health check failed after {HEALTH_CHECK_RETRIES} attempts: {exc}",
            file=sys.stderr,
        )
        _terminate_process(process)
        sys.exit(1)
    time.sleep(HEALTH_CHECK_INTERVAL)


def _handle_unexpected_payload(attempt: int, process: subprocess.Popen[bytes]) -> None:
    print("Health endpoint returned unexpected payload.", file=sys.stderr)
    if attempt == HEALTH_CHECK_RETRIES:
        _terminate_process(process)
        sys.exit(1)
    time.sleep(HEALTH_CHECK_INTERVAL)


def _normalize_host_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _is_ipv6_host(host: str) -> bool:
    candidate = host.strip()
    if ":" not in candidate:
        return False

    inner_host = (
        candidate[1:-1] if candidate.startswith("[") and candidate.endswith("]") else candidate
    )
    split_target = inner_host.replace("%25", "%")
    address = split_target.split("%", 1)[0]
    try:
        ipaddress.IPv6Address(address)
    except ValueError:
        return False
    return True


def _resolve_host(args: argparse.Namespace, env: dict[str, str]) -> str:
    cli_host = _normalize_host_value(getattr(args, "host", None))
    env_host = _normalize_host_value(env.get("HOST"))
    host = cli_host or env_host or DEFAULT_HOST

    if ":" in host and not _is_ipv6_host(host):
        print(
            "Host value must not include a port; use --port or the PORT environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    return host


def _resolve_port(args: argparse.Namespace, env: dict[str, str]) -> int:
    arg_port = getattr(args, "port", None)
    if arg_port is not None:
        port = int(arg_port)
    else:
        env_port = env.get("PORT")
        if env_port is None:
            port = DEFAULT_PORT
        else:
            try:
                port = int(env_port)
            except ValueError:
                print("PORT environment variable must be an integer.", file=sys.stderr)
                sys.exit(1)

    if not (1 <= port <= 65535):
        print("Port must be between 1 and 65535 (health check cannot use 0).", file=sys.stderr)
        sys.exit(1)

    return port


def _build_uvicorn_command(host: str, port: int, *, reload_enabled: bool) -> list[str]:
    bind_host = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    command = [
        "uvicorn",
        "app.main:app",
        "--host",
        bind_host,
        "--port",
        str(port),
    ]
    if reload_enabled:
        command.append("--reload")
    return command


def _launch_uvicorn(command: list[str], env: dict[str, str]) -> subprocess.Popen[bytes]:
    try:
        return subprocess.Popen(command, env=env)  # noqa: S603
    except FileNotFoundError as exc:
        print(
            f"uvicorn executable not found: {exc}. Install uvicorn in the active environment.",
            file=sys.stderr,
        )
        sys.exit(1)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Failed to launch uvicorn: {exc}", file=sys.stderr)
        sys.exit(1)


def _install_signal_handlers(process: subprocess.Popen[bytes]) -> None:
    def forward_signal(signum: int, _frame: object) -> None:
        if process.poll() is None:
            with suppress(OSError):
                process.send_signal(signum)

    signal.signal(signal.SIGINT, forward_signal)
    signal.signal(signal.SIGTERM, forward_signal)


def _wait_for_process(process: subprocess.Popen[bytes]) -> int:
    try:
        exit_code: int = process.wait()
        return exit_code
    finally:
        if process.poll() is None:
            _terminate_process(process)


def perform_health_check(
    host: str,
    port: int,
    process: subprocess.Popen[bytes],
) -> None:
    """Probe the health endpoint until success or retry exhaustion."""
    time.sleep(HEALTH_CHECK_DELAY)
    probe_host = _format_health_probe_host(host)
    url = f"http://{probe_host}:{port}/health"
    for attempt in range(1, HEALTH_CHECK_RETRIES + 1):
        _ensure_process_running(process)
        try:
            payload = _request_health_payload(url)
        except (
            RuntimeError,
            TypeError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            OSError,
        ) as exc:
            _handle_probe_error(attempt, exc, process)
            continue
        if payload.get("status") == "ok":
            print("Service healthy; continuing to run.")
            return
        _handle_unexpected_payload(attempt, process)


def main(argv: Sequence[str] | None = None) -> None:
    """Entrypoint to launch uvicorn and optionally wait for health readiness."""
    args = parse_args(argv)
    env = os.environ.copy()
    host = _resolve_host(args, env)
    port = _resolve_port(args, env)
    reload_enabled = args.reload
    command = _build_uvicorn_command(host, port, reload_enabled=reload_enabled)
    process = _launch_uvicorn(command, env)

    _install_signal_handlers(process)

    if not args.skip_health_check:
        perform_health_check(host, port, process)

    exit_code = _wait_for_process(process)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
