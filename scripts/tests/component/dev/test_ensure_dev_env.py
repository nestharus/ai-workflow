from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

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


class TestEnsureSingleSocketDirectory:
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
    def test_returns_empty_when_timeout_is_zero(self) -> None:
        """Should return empty string when timeout is zero or negative."""
        status = get_container_health("test-container", timeout=0)
        assert status == ""

        status = get_container_health("test-container", timeout=-1)
        assert status == ""


class TestMain:
    def test_does_not_crash_on_top_level_exception(self) -> None:
        """Should catch exceptions at top level and return EXIT_COMPOSE_FAILED."""
        with patch.object(ensure_dev_env, "acquire_lock", side_effect=RuntimeError("Fatal error")):
            result = main()

        assert result == EXIT_COMPOSE_FAILED
