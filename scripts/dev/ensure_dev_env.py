#!/usr/bin/env python3
"""Ensure dev environment services are running and healthy.

Exit codes:
    0  - Success (services healthy) or another process already running
    10 - Docker daemon not available
    11 - Compose start failed or unexpected orchestration error
    12 - Health timeout exceeded
"""

import contextlib
import os
import subprocess
import time
from pathlib import Path

# Constants
DOCKER_TIMEOUT = 5  # seconds for docker info
COMPOSE_TIMEOUT = 60  # seconds for docker compose up
INSPECT_TIMEOUT = 10  # seconds for docker inspect
HEALTH_POLL_INTERVAL = 2  # seconds between health checks
HEALTH_TIMEOUT = 20  # total seconds to wait for healthy
CONTAINER_NAME = "ai-workflow-mcp-bridge-dev"
COMPOSE_FILE = "docker-compose.dev.yml"
PROJECT_NAME = "ai-workflow-devtools"
LOCK_STALE_SECONDS = 300  # 5 minutes
SOCKET_DIR = Path("/tmp/mcp-sockets")  # Host socket directory for targeted mount

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOCK_FILE = PROJECT_ROOT / ".claude" / ".tmp" / "ensure-dev-env.lock"

# Exit codes
EXIT_SUCCESS = 0
EXIT_DOCKER_NOT_AVAILABLE = 10
EXIT_COMPOSE_FAILED = 11
EXIT_HEALTH_TIMEOUT = 12


def log(message: str) -> None:
    """Log message with DEVENV prefix."""
    print(f"[DEVENV] {message}", flush=True)


def is_pid_running(pid: int) -> bool:
    """Check if a process with given PID is running."""
    try:
        os.kill(pid, 0)  # Signal 0 doesn't kill, just checks existence
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _try_atomic_create_lock() -> bool:
    """Attempt to atomically create the lock file.

    Returns:
        True if lock file was created, False if it already exists.
    """
    try:
        # O_CREAT | O_EXCL ensures atomic creation - fails if file exists
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, f"{os.getpid()}:{time.time()}".encode())
        finally:
            os.close(fd)
        return True
    except FileExistsError:
        return False


def _check_stale_lock() -> bool:
    """Check if existing lock is stale and remove it if so.

    Returns:
        True if lock was stale and removed, False otherwise.
    """
    try:
        content = LOCK_FILE.read_text().strip()
        pid_str, timestamp_str = content.split(":")
        pid = int(pid_str)
        timestamp = float(timestamp_str)

        age_seconds = time.time() - timestamp
        pid_running = is_pid_running(pid)

        if pid_running:
            log("Another ensure-dev-env process is running; exiting")
            return False

        if age_seconds < LOCK_STALE_SECONDS:
            log("Lock is recent; assuming another process may still be running; exiting")
            return False

        log("Stale ensure-dev-env lock detected; cleaning up")
        LOCK_FILE.unlink()
        return True

    except (ValueError, OSError) as e:
        log(f"Invalid lock file, removing: {e}")
        with contextlib.suppress(OSError):
            LOCK_FILE.unlink()
        return True


def acquire_lock() -> bool:
    """Acquire the lock file atomically.

    Uses O_CREAT | O_EXCL for atomic file creation to prevent race conditions
    where two processes could both pass an exists() check and both acquire the lock.

    Returns:
        True if lock acquired, False if another process owns it.
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)

    # First attempt: try atomic creation
    if _try_atomic_create_lock():
        return True

    # Lock file exists - check if it's stale
    if not _check_stale_lock():
        return False

    # Stale lock was removed, retry atomic creation
    return _try_atomic_create_lock()


def release_lock() -> None:
    """Remove the lock file."""
    with contextlib.suppress(OSError):
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()


def ensure_socket_directory() -> None:
    """Create the socket directory if it doesn't exist.

    Creates /tmp/mcp-sockets with world-writable permissions (1777)
    to allow the container's appuser (UID 10000) to create the socket.

    If the path exists but is not a directory (e.g., a regular file),
    it will be removed and recreated as a directory.
    """
    if not SOCKET_DIR.exists():
        log(f"Creating socket directory: {SOCKET_DIR}")
        SOCKET_DIR.mkdir(parents=True, exist_ok=True)
        SOCKET_DIR.chmod(0o1777)
    elif not SOCKET_DIR.is_dir():
        log(f"Socket path exists but is not a directory: {SOCKET_DIR}")
        with contextlib.suppress(OSError):
            SOCKET_DIR.unlink()
        SOCKET_DIR.mkdir(parents=True, exist_ok=True)
        SOCKET_DIR.chmod(0o1777)
    else:
        # Ensure correct permissions even if directory exists
        current_mode = SOCKET_DIR.stat().st_mode & 0o7777
        if current_mode != 0o1777:
            log(f"Fixing socket directory permissions: {oct(current_mode)} -> 0o1777")
            SOCKET_DIR.chmod(0o1777)


def check_docker_available() -> tuple[bool, str]:
    """Check if Docker daemon is available.

    Returns:
        Tuple of (success, stderr_message).
    """
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=DOCKER_TIMEOUT,
        )
        return result.returncode == 0, result.stderr
    except subprocess.TimeoutExpired:
        return False, "docker info timed out"
    except FileNotFoundError:
        return False, "docker command not found"


def start_compose() -> tuple[bool, str]:
    """Start the dev-tools compose stack.

    Returns:
        Tuple of (success, stderr_message).
    """
    try:
        result = subprocess.run(
            ["docker", "compose", "-p", PROJECT_NAME, "-f", COMPOSE_FILE, "up", "-d"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=COMPOSE_TIMEOUT,
        )
        return result.returncode == 0, result.stderr
    except subprocess.TimeoutExpired:
        return False, "docker compose up timed out"


def get_container_health(timeout: float | None = None) -> str:
    """Get container health status.

    Args:
        timeout: Maximum seconds to wait for inspect command.
                 Defaults to INSPECT_TIMEOUT if not specified.

    Returns:
        One of 'healthy', 'unhealthy', 'starting', or empty string.
    """
    effective_timeout = timeout if timeout is not None else INSPECT_TIMEOUT
    if effective_timeout <= 0:
        return ""
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", CONTAINER_NAME],
            capture_output=True,
            text=True,
            timeout=effective_timeout,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def wait_for_healthy() -> bool:
    """Poll for healthy status.

    Ensures wall time never exceeds HEALTH_TIMEOUT by capping each inspect
    call to the remaining time budget. Tracks the last-known health status
    to provide more informative logging on timeout.

    Returns:
        True if healthy within timeout.
    """
    start = time.monotonic()
    last_status: str = ""
    while True:
        remaining = HEALTH_TIMEOUT - (time.monotonic() - start)
        if remaining <= 0:
            status_msg = last_status if last_status else "unknown"
            log(f"Health check timed out; last known status: {status_msg}")
            return False

        status = get_container_health(timeout=remaining)
        if status:
            last_status = status
        if status == "healthy":
            return True

        remaining = HEALTH_TIMEOUT - (time.monotonic() - start)
        if remaining <= 0:
            status_msg = last_status if last_status else "unknown"
            log(f"Health check timed out; last known status: {status_msg}")
            return False

        time.sleep(min(HEALTH_POLL_INTERVAL, max(0.0, remaining)))


def main() -> int:
    """Entry point for ensuring dev environment is running.

    Returns:
        Exit code: 0 (success), 10 (no docker), 11 (compose failed or unexpected error),
        12 (health timeout).
    """
    try:
        # Step 1: Acquire lock (must be first)
        if not acquire_lock():
            return EXIT_SUCCESS  # Another process is handling it

        try:
            # Step 2: Check Docker daemon
            docker_ok, docker_stderr = check_docker_available()
            if not docker_ok:
                log(f"docker info failed: {docker_stderr.strip()[:200]}")
                return EXIT_DOCKER_NOT_AVAILABLE

            # Step 3: Ensure socket directory exists before starting compose
            ensure_socket_directory()

            # Step 4: Start compose stack
            success, stderr = start_compose()
            if not success:
                log(f"docker compose up failed: {stderr.strip()[:200]}")
                return EXIT_COMPOSE_FAILED

            # Step 5: Wait for healthy
            if not wait_for_healthy():
                log("Dev-tools stack not healthy after timeout")
                return EXIT_HEALTH_TIMEOUT

            # Step 6: Success
            log("Dev-tools environment ready")
            return EXIT_SUCCESS

        finally:
            # Always release lock
            release_lock()

    except Exception as exc:
        # Catch-all: never propagate exceptions, always return a code
        log(f"Unexpected error: {exc}")
        return EXIT_COMPOSE_FAILED  # Use 11 as generic failure code


if __name__ == "__main__":
    raise SystemExit(main())
