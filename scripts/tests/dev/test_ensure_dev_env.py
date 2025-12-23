"""Tests for scripts.dev.ensure_dev_env module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar
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
        if socket_dir.is_dir():
            socket_dir.rmdir()
        elif socket_dir.exists():
            socket_dir.unlink()

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
        """Should iterate through CONTAINERS and create all socket directories."""
        # Define test containers with different socket paths
        test_containers = [
            ("container-1", Path("/tmp/sockets-1")),
            ("container-2", Path("/tmp/sockets-2")),
        ]

        # Clean up any existing directories
        for _, socket_dir in test_containers:
            if socket_dir.exists():
                socket_dir.rmdir()

        with patch.object(ensure_dev_env, "CONTAINERS", test_containers):
            ensure_socket_directories()

        # Verify both directories were created
        for _, socket_dir in test_containers:
            assert socket_dir.exists()
            assert socket_dir.is_dir()
            mode = socket_dir.stat().st_mode & 0o7777
            assert mode == 0o1777

    def test_calls_ensure_single_for_each_container(self, fs: FakeFilesystem) -> None:
        """Should call _ensure_single_socket_directory for each container."""
        test_containers = [
            ("mcp-bridge", Path("/tmp/mcp-sockets")),
            ("sandbox-server", Path("/tmp/sandbox-sockets")),
        ]

        with (
            patch.object(ensure_dev_env, "CONTAINERS", test_containers),
            patch.object(ensure_dev_env, "_ensure_single_socket_directory") as mock_ensure,
        ):
            ensure_socket_directories()

        # Verify _ensure_single_socket_directory was called for each socket path
        assert mock_ensure.call_count == 2
        mock_ensure.assert_any_call(Path("/tmp/mcp-sockets"))
        mock_ensure.assert_any_call(Path("/tmp/sandbox-sockets"))


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
    """Tests for wait_for_healthy function.

    Note: The wait_for_healthy function now checks multiple containers defined
    in CONTAINERS. These tests mock get_container_health to return statuses for
    all containers being polled.
    """

    # Use a single container for simpler testing
    TEST_CONTAINERS: ClassVar = [("test-container", Path("/tmp/test-sockets"))]

    def test_returns_true_when_immediately_healthy(self) -> None:
        """Should return True when container is immediately healthy."""
        with (
            patch.object(ensure_dev_env, "CONTAINERS", self.TEST_CONTAINERS),
            patch.object(ensure_dev_env, "get_container_health", return_value="healthy"),
            patch("time.monotonic") as mock_monotonic,
        ):
            mock_monotonic.return_value = 0.0
            result = wait_for_healthy()

        assert result is True

    def test_returns_true_after_transition_to_healthy(self) -> None:
        """Should return True when container transitions from starting to healthy."""
        health_sequence = ["starting", "starting", "healthy"]
        health_iter = iter(health_sequence)

        def mock_get_health(container_name: str, timeout: float | None = None) -> str:
            return next(health_iter)

        monotonic_values = [0.0, 0.0, 2.0, 2.0, 4.0, 4.0]  # Pairs for each loop iteration
        monotonic_iter = iter(monotonic_values)

        with (
            patch.object(ensure_dev_env, "CONTAINERS", self.TEST_CONTAINERS),
            patch.object(ensure_dev_env, "get_container_health", side_effect=mock_get_health),
            patch("time.monotonic", side_effect=lambda: next(monotonic_iter)),
            patch("time.sleep"),
        ):
            result = wait_for_healthy()

        assert result is True

    def test_returns_false_on_timeout(self) -> None:
        """Should return False when health timeout is exceeded."""
        # wait_for_healthy calls time.monotonic multiple times per iteration:
        # 1. start = time.monotonic() at initialization
        # 2. remaining = HEALTH_TIMEOUT - (time.monotonic() - start) before loop
        # 3. remaining = HEALTH_TIMEOUT - (time.monotonic() - start) after container check
        # We need the second remaining check (after health check) to be past timeout
        monotonic_values = [0.0, 0.0, 100.0]  # init, first remaining check, post-check timeout
        monotonic_iter = iter(monotonic_values)

        with (
            patch.object(ensure_dev_env, "CONTAINERS", self.TEST_CONTAINERS),
            patch.object(ensure_dev_env, "get_container_health", return_value="starting"),
            patch("time.monotonic", side_effect=lambda: next(monotonic_iter)),
            patch("time.sleep"),
            patch.object(ensure_dev_env, "log") as mock_log,
        ):
            result = wait_for_healthy()

        assert result is False
        mock_log.assert_called_once()
        log_message = mock_log.call_args[0][0]
        assert "timed out" in log_message
        assert "starting" in log_message

    def test_logs_last_known_status_on_timeout(self) -> None:
        """Should log last known status when timeout is exceeded."""
        # Sequence: returns "starting" then "" (empty), then timeout
        health_sequence = ["starting", ""]
        health_iter = iter(health_sequence)

        def mock_get_health(container_name: str, timeout: float | None = None) -> str:
            return next(health_iter)

        # Time pattern for two iterations:
        # Iter 1: init(0), remaining check(0), post-check(5), sleep(5)
        # Iter 2: remaining check(5), post-check(100 - timeout)
        monotonic_values = [0.0, 0.0, 5.0, 5.0, 5.0, 100.0]
        monotonic_iter = iter(monotonic_values)

        with (
            patch.object(ensure_dev_env, "CONTAINERS", self.TEST_CONTAINERS),
            patch.object(ensure_dev_env, "get_container_health", side_effect=mock_get_health),
            patch("time.monotonic", side_effect=lambda: next(monotonic_iter)),
            patch("time.sleep"),
            patch.object(ensure_dev_env, "log") as mock_log,
        ):
            result = wait_for_healthy()

        assert result is False
        mock_log.assert_called_once()
        log_message = mock_log.call_args[0][0]
        assert "starting" in log_message  # Should report last-seen status

    def test_logs_container_status_when_no_health_returned(self) -> None:
        """Should log container with empty status when no health status was ever returned."""
        # First remaining check passes, then timeout on second check
        monotonic_values = [0.0, 0.0, 100.0]  # init, first remaining check, post-check timeout
        monotonic_iter = iter(monotonic_values)

        with (
            patch.object(ensure_dev_env, "CONTAINERS", self.TEST_CONTAINERS),
            patch.object(ensure_dev_env, "get_container_health", return_value=""),
            patch("time.monotonic", side_effect=lambda: next(monotonic_iter)),
            patch("time.sleep"),
            patch.object(ensure_dev_env, "log") as mock_log,
        ):
            result = wait_for_healthy()

        assert result is False
        mock_log.assert_called_once()
        log_message = mock_log.call_args[0][0]
        # When no status was returned, the container is logged with its name and empty status
        assert "test-container=" in log_message
        assert "timed out" in log_message
        assert "=" in log_message  # Container names are shown with status

    def test_skips_already_healthy_containers(self) -> None:
        """Should skip health check for containers already marked as healthy."""
        # Use two containers - first becomes healthy immediately,
        # second becomes healthy on second iteration
        test_containers = [
            ("container-1", Path("/tmp/sockets-1")),
            ("container-2", Path("/tmp/sockets-2")),
        ]

        # Track which containers are checked
        health_check_calls: list[str] = []

        def mock_get_health(container_name: str, timeout: float | None = None) -> str:
            health_check_calls.append(container_name)
            # container-1 is immediately healthy
            # container-2 is starting first, healthy second time
            if container_name == "container-1":
                return "healthy"
            elif container_name == "container-2":
                # Return "starting" for first call, "healthy" for second
                count = sum(1 for c in health_check_calls if c == "container-2")
                return "healthy" if count > 1 else "starting"
            return ""

        # Time values for two loop iterations
        # Iteration 1: check both containers
        # Iteration 2: container-1 is skipped (already healthy), only container-2 checked
        monotonic_values = [0.0, 0.0, 2.0, 2.0, 2.0, 4.0, 4.0]
        monotonic_iter = iter(monotonic_values)

        with (
            patch.object(ensure_dev_env, "CONTAINERS", test_containers),
            patch.object(ensure_dev_env, "get_container_health", side_effect=mock_get_health),
            patch("time.monotonic", side_effect=lambda: next(monotonic_iter)),
            patch("time.sleep"),
            patch.object(ensure_dev_env, "log"),
        ):
            result = wait_for_healthy()

        assert result is True
        # container-1 should be checked once, then skipped
        # container-2 should be checked twice (starting, then healthy)
        assert health_check_calls.count("container-1") == 1
        assert health_check_calls.count("container-2") == 2


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
