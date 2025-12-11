"""Tests for scripts.dev.ensure_dev_env module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev import ensure_dev_env
from scripts.dev.ensure_dev_env import (
    EXIT_COMPOSE_FAILED,
    EXIT_DOCKER_NOT_AVAILABLE,
    EXIT_HEALTH_TIMEOUT,
    EXIT_SUCCESS,
    _check_stale_lock,
    _ensure_single_socket_directory,
    _try_atomic_create_lock,
    acquire_lock,
    check_docker_available,
    ensure_socket_directories,
    get_container_health,
    is_pid_running,
    main,
    release_lock,
    start_compose,
    wait_for_healthy,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


@pytest.fixture
def lock_file_path(fs: FakeFilesystem) -> Path:
    """Create the lock file directory structure in the fake filesystem."""
    lock_dir = Path("/fake/repo/.claude/.tmp")
    fs.create_dir(str(lock_dir))
    return lock_dir / "ensure-dev-env.lock"


@pytest.fixture
def mock_lock_file(lock_file_path: Path) -> Path:
    """Patch the module's LOCK_FILE to use our fake path."""
    with patch.object(ensure_dev_env, "LOCK_FILE", lock_file_path):
        yield lock_file_path


class TestIsPidRunning:
    """Tests for is_pid_running function."""

    def test_returns_true_for_running_pid(self) -> None:
        """Should return True when os.kill(pid, 0) succeeds."""
        with patch("os.kill") as mock_kill:
            assert is_pid_running(1234) is True
            mock_kill.assert_called_once_with(1234, 0)

    def test_returns_false_for_nonexistent_pid(self) -> None:
        """Should return False when process does not exist."""
        with patch("os.kill") as mock_kill:
            mock_kill.side_effect = ProcessLookupError()
            assert is_pid_running(1234) is False

    def test_returns_true_for_permission_error(self) -> None:
        """Should return True when we lack permission (process exists)."""
        with patch("os.kill") as mock_kill:
            mock_kill.side_effect = PermissionError()
            assert is_pid_running(1234) is True

    def test_returns_false_for_other_os_error(self) -> None:
        """Should return False for other OS errors."""
        with patch("os.kill") as mock_kill:
            mock_kill.side_effect = OSError("Some other error")
            assert is_pid_running(1234) is False


class TestTryAtomicCreateLock:
    """Tests for _try_atomic_create_lock function."""

    def test_creates_lock_when_not_exists(self, fs: FakeFilesystem, mock_lock_file: Path) -> None:
        """Should create lock file and return True when it doesn't exist."""
        with patch("os.getpid", return_value=1234), patch("time.time", return_value=1000.0):
            result = _try_atomic_create_lock()

        assert result is True
        assert mock_lock_file.exists()
        content = mock_lock_file.read_text()
        assert content == "1234:1000.0"

    def test_returns_false_when_exists(self, fs: FakeFilesystem, mock_lock_file: Path) -> None:
        """Should return False when lock file already exists."""
        fs.create_file(str(mock_lock_file), contents="9999:500.0")

        result = _try_atomic_create_lock()

        assert result is False


class TestCheckStaleLock:
    """Tests for _check_stale_lock function."""

    def test_returns_false_when_owner_pid_running(
        self, fs: FakeFilesystem, mock_lock_file: Path
    ) -> None:
        """Should return False when the lock owner PID is still running."""
        fs.create_file(str(mock_lock_file), contents="1234:1000.0")

        with (
            patch.object(ensure_dev_env, "is_pid_running", return_value=True),
            patch("time.time", return_value=1100.0),
        ):
            result = _check_stale_lock()

        assert result is False
        assert mock_lock_file.exists()  # Lock file should remain

    def test_returns_false_when_lock_recent_but_pid_dead(
        self, fs: FakeFilesystem, mock_lock_file: Path
    ) -> None:
        """Should return False when lock is recent, even if PID is dead."""
        fs.create_file(str(mock_lock_file), contents="1234:1000.0")

        with (
            patch.object(ensure_dev_env, "is_pid_running", return_value=False),
            patch("time.time", return_value=1100.0),  # Only 100 seconds old
        ):
            result = _check_stale_lock()

        assert result is False

    def test_returns_true_and_removes_stale_lock(
        self, fs: FakeFilesystem, mock_lock_file: Path
    ) -> None:
        """Should return True and remove lock when stale (old + PID dead)."""
        fs.create_file(str(mock_lock_file), contents="1234:1000.0")

        with (
            patch.object(ensure_dev_env, "is_pid_running", return_value=False),
            patch("time.time", return_value=1500.0),  # 500 seconds old (> LOCK_STALE_SECONDS)
        ):
            result = _check_stale_lock()

        assert result is True
        assert not mock_lock_file.exists()  # Lock file should be removed

    def test_removes_corrupted_lock_file(self, fs: FakeFilesystem, mock_lock_file: Path) -> None:
        """Should remove lock file with invalid content and return True."""
        fs.create_file(str(mock_lock_file), contents="garbage_content")

        result = _check_stale_lock()

        assert result is True
        assert not mock_lock_file.exists()

    def test_removes_lock_with_invalid_pid(self, fs: FakeFilesystem, mock_lock_file: Path) -> None:
        """Should remove lock file with non-integer PID."""
        fs.create_file(str(mock_lock_file), contents="notanumber:1000.0")

        result = _check_stale_lock()

        assert result is True
        assert not mock_lock_file.exists()


class TestAcquireLock:
    """Tests for acquire_lock function."""

    def test_acquires_fresh_lock(self, fs: FakeFilesystem, mock_lock_file: Path) -> None:
        """Should acquire lock when no lock file exists."""
        with patch("os.getpid", return_value=1234), patch("time.time", return_value=1000.0):
            result = acquire_lock()

        assert result is True
        assert mock_lock_file.exists()

    def test_returns_false_when_another_process_owns_lock(
        self, fs: FakeFilesystem, mock_lock_file: Path
    ) -> None:
        """Should return False when another process holds a valid lock."""
        fs.create_file(str(mock_lock_file), contents="9999:1000.0")

        with (
            patch.object(ensure_dev_env, "is_pid_running", return_value=True),
            patch("time.time", return_value=1100.0),
        ):
            result = acquire_lock()

        assert result is False

    def test_acquires_lock_after_stale_removal(
        self, fs: FakeFilesystem, mock_lock_file: Path
    ) -> None:
        """Should acquire lock after removing a stale lock."""
        fs.create_file(str(mock_lock_file), contents="9999:1000.0")

        with (
            patch.object(ensure_dev_env, "is_pid_running", return_value=False),
            patch("time.time", return_value=1500.0),  # Stale (500s old)
            patch("os.getpid", return_value=1234),
        ):
            result = acquire_lock()

        assert result is True
        assert mock_lock_file.exists()
        content = mock_lock_file.read_text()
        assert "1234:" in content


class TestReleaseLock:
    """Tests for release_lock function."""

    def test_removes_existing_lock(self, fs: FakeFilesystem, mock_lock_file: Path) -> None:
        """Should remove the lock file when it exists."""
        fs.create_file(str(mock_lock_file), contents="1234:1000.0")

        release_lock()

        assert not mock_lock_file.exists()

    def test_does_not_raise_when_lock_missing(
        self, fs: FakeFilesystem, mock_lock_file: Path
    ) -> None:
        """Should not raise when lock file does not exist."""
        release_lock()  # Should not raise


class TestCheckDockerAvailable:
    """Tests for check_docker_available function."""

    def test_returns_true_when_docker_available(self) -> None:
        """Should return (True, stderr) when docker info succeeds."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            success, stderr = check_docker_available()

        assert success is True
        assert stderr == ""
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == ["docker", "info"]

    def test_returns_false_when_docker_fails(self) -> None:
        """Should return (False, stderr) when docker info fails."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Cannot connect to Docker daemon"

        with patch("subprocess.run", return_value=mock_result):
            success, stderr = check_docker_available()

        assert success is False
        assert "Cannot connect" in stderr

    def test_returns_false_on_timeout(self) -> None:
        """Should return (False, message) when docker info times out."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("docker", 5)
            success, stderr = check_docker_available()

        assert success is False
        assert "timed out" in stderr

    def test_returns_false_when_docker_not_found(self) -> None:
        """Should return (False, message) when docker command not found."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            success, stderr = check_docker_available()

        assert success is False
        assert "not found" in stderr


class TestStartCompose:
    """Tests for start_compose function."""

    def test_returns_true_on_success(self) -> None:
        """Should return (True, stderr) when compose up succeeds."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            success, stderr = start_compose()

        assert success is True
        assert stderr == ""
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert "docker" in call_args[0][0]
        assert "compose" in call_args[0][0]
        assert "up" in call_args[0][0]

    def test_returns_false_when_compose_fails(self) -> None:
        """Should return (False, stderr) when compose up fails."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Error starting containers"

        with patch("subprocess.run", return_value=mock_result):
            success, stderr = start_compose()

        assert success is False
        assert "Error" in stderr

    def test_returns_false_on_timeout(self) -> None:
        """Should return (False, message) when compose times out."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("docker compose", 60)
            success, stderr = start_compose()

        assert success is False
        assert "timed out" in stderr


class TestEnsureSingleSocketDirectory:
    """Tests for _ensure_single_socket_directory function."""

    def test_creates_directory_when_not_exists(self, fs: FakeFilesystem) -> None:
        """Should create the socket directory with correct permissions."""
        # pyfakefs already has /tmp; ensure mcp-sockets doesn't exist
        socket_dir = Path("/tmp/mcp-sockets")
        if socket_dir.exists():
            socket_dir.rmdir()

        _ensure_single_socket_directory(socket_dir)

        assert socket_dir.exists()
        assert socket_dir.is_dir()
        # Check permissions are 1777 (sticky bit + world-writable)
        mode = socket_dir.stat().st_mode & 0o7777
        assert mode == 0o1777

    def test_does_nothing_when_exists_with_correct_permissions(self, fs: FakeFilesystem) -> None:
        """Should not modify directory when it exists with correct permissions."""
        fs.create_dir("/tmp/mcp-sockets")
        Path("/tmp/mcp-sockets").chmod(0o1777)

        _ensure_single_socket_directory(Path("/tmp/mcp-sockets"))

        # Directory should still exist with correct permissions
        socket_dir = Path("/tmp/mcp-sockets")
        assert socket_dir.exists()
        mode = socket_dir.stat().st_mode & 0o7777
        assert mode == 0o1777

    def test_fixes_permissions_when_incorrect(self, fs: FakeFilesystem) -> None:
        """Should fix permissions when directory exists with wrong permissions."""
        fs.create_dir("/tmp/mcp-sockets")
        Path("/tmp/mcp-sockets").chmod(0o755)  # Wrong permissions

        _ensure_single_socket_directory(Path("/tmp/mcp-sockets"))

        # Permissions should be corrected
        socket_dir = Path("/tmp/mcp-sockets")
        mode = socket_dir.stat().st_mode & 0o7777
        assert mode == 0o1777

    def test_replaces_non_directory_with_directory(self, fs: FakeFilesystem) -> None:
        """Should remove non-directory and create directory when path exists as file."""
        # Create a regular file at the socket path
        fs.create_file("/tmp/mcp-sockets", contents="some content")
        socket_path = Path("/tmp/mcp-sockets")
        assert socket_path.exists()
        assert socket_path.is_file()

        _ensure_single_socket_directory(socket_path)

        # Should now be a directory with correct permissions
        assert socket_path.exists()
        assert socket_path.is_dir()
        mode = socket_path.stat().st_mode & 0o7777
        assert mode == 0o1777


class TestEnsureSocketDirectories:
    """Tests for ensure_socket_directories function."""

    def test_creates_all_socket_directories(self, fs: FakeFilesystem) -> None:
        """Should create socket directories for all containers in CONTAINERS."""
        # pyfakefs already creates /tmp by default, so we don't need to create it

        # Mock CONTAINERS to use test paths
        test_containers = [
            ("test-container-1", Path("/tmp/test-sockets-1")),
            ("test-container-2", Path("/tmp/test-sockets-2")),
        ]

        with patch.object(ensure_dev_env, "CONTAINERS", test_containers):
            ensure_socket_directories()

        # Verify all directories were created with correct permissions
        for _, socket_dir in test_containers:
            assert socket_dir.exists()
            assert socket_dir.is_dir()
            mode = socket_dir.stat().st_mode & 0o7777
            assert mode == 0o1777


class TestGetContainerHealth:
    """Tests for get_container_health function."""

    def test_returns_healthy_status(self) -> None:
        """Should return 'healthy' when container is healthy."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "healthy\n"

        with patch("subprocess.run", return_value=mock_result):
            status = get_container_health("test-container")

        assert status == "healthy"

    def test_returns_starting_status(self) -> None:
        """Should return 'starting' when container is starting."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "starting\n"

        with patch("subprocess.run", return_value=mock_result):
            status = get_container_health("test-container")

        assert status == "starting"

    def test_returns_empty_on_failure(self) -> None:
        """Should return empty string when inspect fails."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            status = get_container_health("test-container")

        assert status == ""

    def test_returns_empty_on_timeout(self) -> None:
        """Should return empty string when inspect times out."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("docker inspect", 10)
            status = get_container_health("test-container")

        assert status == ""

    def test_returns_empty_when_docker_not_found(self) -> None:
        """Should return empty string when docker command not found."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            status = get_container_health("test-container")

        assert status == ""

    def test_returns_empty_when_timeout_is_zero(self) -> None:
        """Should return empty string when timeout is zero or negative."""
        status = get_container_health("test-container", timeout=0)
        assert status == ""

        status = get_container_health("test-container", timeout=-1)
        assert status == ""


class TestWaitForHealthy:
    """Tests for wait_for_healthy function."""

    def test_returns_true_when_immediately_healthy(self) -> None:
        """Should return True when all containers are immediately healthy."""
        # Mock CONTAINERS to have a single container for simpler testing
        test_containers = [("test-container", Path("/tmp/test-sockets"))]

        with (
            patch.object(ensure_dev_env, "CONTAINERS", test_containers),
            patch.object(ensure_dev_env, "get_container_health", return_value="healthy"),
            patch("time.monotonic") as mock_monotonic,
            patch.object(ensure_dev_env, "log"),
        ):
            mock_monotonic.return_value = 0.0
            result = wait_for_healthy()

        assert result is True

    def test_returns_true_after_transition_to_healthy(self) -> None:
        """Should return True when container transitions from starting to healthy."""
        # Mock CONTAINERS to have a single container for simpler testing
        test_containers = [("test-container", Path("/tmp/test-sockets"))]
        health_sequence = ["starting", "starting", "healthy"]
        health_iter = iter(health_sequence)

        def mock_get_health(container_name: str, timeout: float | None = None) -> str:
            return next(health_iter, "healthy")

        # Provide enough monotonic values for the loop iterations
        # Each iteration: remaining check (line 266), loop iteration (line 292)
        monotonic_values = [0.0] * 20  # Enough values for multiple iterations
        monotonic_iter = iter(monotonic_values)

        with (
            patch.object(ensure_dev_env, "CONTAINERS", test_containers),
            patch.object(ensure_dev_env, "get_container_health", side_effect=mock_get_health),
            patch("time.monotonic", side_effect=lambda: next(monotonic_iter, 0.0)),
            patch("time.sleep"),
            patch.object(ensure_dev_env, "log"),
        ):
            result = wait_for_healthy()

        assert result is True

    def test_returns_false_on_timeout(self) -> None:
        """Should return False when health timeout is exceeded."""
        # Mock CONTAINERS to have a single container for simpler testing
        test_containers = [("test-container", Path("/tmp/test-sockets"))]

        # Time starts at 0, then jumps past timeout (HEALTH_TIMEOUT = 60)
        monotonic_values = [0.0, 0.0, 65.0]  # Start, first remaining check, then past timeout
        monotonic_iter = iter(monotonic_values)

        with (
            patch.object(ensure_dev_env, "CONTAINERS", test_containers),
            patch.object(ensure_dev_env, "get_container_health", return_value="starting"),
            patch("time.monotonic", side_effect=lambda: next(monotonic_iter, 100.0)),
            patch("time.sleep"),
            patch.object(ensure_dev_env, "log") as mock_log,
        ):
            result = wait_for_healthy()

        assert result is False
        # Should have logged a timeout message
        assert mock_log.called
        log_message = mock_log.call_args[0][0]
        assert "timed out" in log_message
        assert "starting" in log_message

    def test_logs_last_known_status_on_timeout(self) -> None:
        """Should log last known status when timeout is exceeded."""
        # Mock CONTAINERS to have a single container for simpler testing
        test_containers = [("test-container", Path("/tmp/test-sockets"))]
        # Sequence: returns "starting" then "" (empty)
        health_sequence = ["starting", ""]
        health_iter = iter(health_sequence)

        def mock_get_health(container_name: str, timeout: float | None = None) -> str:
            return next(health_iter, "")

        # Time: 0s start, 5s after first check, then past timeout
        monotonic_values = [0.0, 0.0, 5.0, 5.0, 65.0]
        monotonic_iter = iter(monotonic_values)

        with (
            patch.object(ensure_dev_env, "CONTAINERS", test_containers),
            patch.object(ensure_dev_env, "get_container_health", side_effect=mock_get_health),
            patch("time.monotonic", side_effect=lambda: next(monotonic_iter, 100.0)),
            patch("time.sleep"),
            patch.object(ensure_dev_env, "log") as mock_log,
        ):
            result = wait_for_healthy()

        assert result is False
        assert mock_log.called
        log_message = mock_log.call_args[0][0]
        assert "starting" in log_message  # Should report last-seen status

    def test_logs_empty_status_when_no_health_returned(self) -> None:
        """Should log empty status when no health status was ever returned."""
        # Mock CONTAINERS to have a single container for simpler testing
        test_containers = [("test-container", Path("/tmp/test-sockets"))]
        # Time immediately jumps past timeout
        monotonic_values = [0.0, 65.0]  # Start, then past timeout
        monotonic_iter = iter(monotonic_values)

        with (
            patch.object(ensure_dev_env, "CONTAINERS", test_containers),
            patch.object(ensure_dev_env, "get_container_health", return_value=""),
            patch("time.monotonic", side_effect=lambda: next(monotonic_iter, 100.0)),
            patch("time.sleep"),
            patch.object(ensure_dev_env, "log") as mock_log,
        ):
            result = wait_for_healthy()

        assert result is False
        assert mock_log.called
        log_message = mock_log.call_args[0][0]
        # When no health status is ever returned, last_statuses remains empty string
        assert "test-container=" in log_message
        assert "timed out" in log_message


class TestMain:
    """Tests for main function."""

    def test_returns_success_when_lock_not_acquired(
        self, fs: FakeFilesystem, mock_lock_file: Path
    ) -> None:
        """Should return EXIT_SUCCESS when another process holds the lock."""
        fs.create_file(str(mock_lock_file), contents="9999:1000.0")

        with (
            patch.object(ensure_dev_env, "is_pid_running", return_value=True),
            patch("time.time", return_value=1100.0),
        ):
            result = main()

        assert result == EXIT_SUCCESS

    def test_returns_docker_not_available(self, fs: FakeFilesystem, mock_lock_file: Path) -> None:
        """Should return EXIT_DOCKER_NOT_AVAILABLE when docker is not available."""
        with (
            patch.object(ensure_dev_env, "acquire_lock", return_value=True),
            patch.object(ensure_dev_env, "release_lock"),
            patch.object(
                ensure_dev_env, "check_docker_available", return_value=(False, "Docker not running")
            ),
        ):
            result = main()

        assert result == EXIT_DOCKER_NOT_AVAILABLE

    def test_returns_compose_failed(self, fs: FakeFilesystem, mock_lock_file: Path) -> None:
        """Should return EXIT_COMPOSE_FAILED when compose up fails."""
        with (
            patch.object(ensure_dev_env, "acquire_lock", return_value=True),
            patch.object(ensure_dev_env, "release_lock"),
            patch.object(ensure_dev_env, "check_docker_available", return_value=(True, "")),
            patch.object(ensure_dev_env, "ensure_socket_directories"),
            patch.object(ensure_dev_env, "start_compose", return_value=(False, "Compose failed")),
        ):
            result = main()

        assert result == EXIT_COMPOSE_FAILED

    def test_returns_health_timeout(self, fs: FakeFilesystem, mock_lock_file: Path) -> None:
        """Should return EXIT_HEALTH_TIMEOUT when health check times out."""
        with (
            patch.object(ensure_dev_env, "acquire_lock", return_value=True),
            patch.object(ensure_dev_env, "release_lock"),
            patch.object(ensure_dev_env, "check_docker_available", return_value=(True, "")),
            patch.object(ensure_dev_env, "ensure_socket_directories"),
            patch.object(ensure_dev_env, "start_compose", return_value=(True, "")),
            patch.object(ensure_dev_env, "wait_for_healthy", return_value=False),
        ):
            result = main()

        assert result == EXIT_HEALTH_TIMEOUT

    def test_returns_success_when_healthy(self, fs: FakeFilesystem, mock_lock_file: Path) -> None:
        """Should return EXIT_SUCCESS when all steps succeed."""
        with (
            patch.object(ensure_dev_env, "acquire_lock", return_value=True),
            patch.object(ensure_dev_env, "release_lock") as mock_release,
            patch.object(ensure_dev_env, "check_docker_available", return_value=(True, "")),
            patch.object(ensure_dev_env, "ensure_socket_directories"),
            patch.object(ensure_dev_env, "start_compose", return_value=(True, "")),
            patch.object(ensure_dev_env, "wait_for_healthy", return_value=True),
        ):
            result = main()

        assert result == EXIT_SUCCESS
        mock_release.assert_called_once()

    def test_releases_lock_on_docker_failure(
        self, fs: FakeFilesystem, mock_lock_file: Path
    ) -> None:
        """Should release lock even when docker check fails."""
        with (
            patch.object(ensure_dev_env, "acquire_lock", return_value=True),
            patch.object(ensure_dev_env, "release_lock") as mock_release,
            patch.object(
                ensure_dev_env, "check_docker_available", return_value=(False, "No docker")
            ),
        ):
            main()

        mock_release.assert_called_once()

    def test_releases_lock_on_exception(self, fs: FakeFilesystem, mock_lock_file: Path) -> None:
        """Should release lock and return EXIT_COMPOSE_FAILED on unexpected exception."""
        with (
            patch.object(ensure_dev_env, "acquire_lock", return_value=True),
            patch.object(ensure_dev_env, "release_lock") as mock_release,
            patch.object(
                ensure_dev_env, "check_docker_available", side_effect=RuntimeError("Unexpected")
            ),
        ):
            result = main()

        assert result == EXIT_COMPOSE_FAILED
        mock_release.assert_called_once()

    def test_does_not_crash_on_top_level_exception(self) -> None:
        """Should catch exceptions at top level and return EXIT_COMPOSE_FAILED."""
        with patch.object(ensure_dev_env, "acquire_lock", side_effect=RuntimeError("Fatal error")):
            result = main()

        assert result == EXIT_COMPOSE_FAILED
