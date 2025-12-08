"""Tests for Trivy integration in scripts.dev.lint module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev import lint
from scripts.dev.lint import (
    _docker,
    _run_trivy,
    _run_trivy_fs,
    _run_trivy_image,
    _trivy,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


# Sample image ID for testing (sha256 format returned by docker build --iidfile)
SAMPLE_IMAGE_ID = "sha256:abc123def456789012345678901234567890123456789012345678901234"


class TestTrivyCliDetection:
    """Tests for _trivy function."""

    def test_returns_trivy_path_when_found(self) -> None:
        """Should return trivy executable path when available."""
        with patch("shutil.which", return_value="/usr/bin/trivy"):
            result = _trivy()
            assert result == "/usr/bin/trivy"

    def test_raises_when_not_found(self) -> None:
        """Should raise RuntimeError when trivy not found."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError) as exc_info:
                _trivy()
            assert "trivy CLI required" in str(exc_info.value)


class TestDockerCliDetection:
    """Tests for _docker function."""

    def test_returns_docker_path_when_found(self) -> None:
        """Should return docker executable path when available."""
        with patch("shutil.which", return_value="/usr/bin/docker"):
            result = _docker()
            assert result == "/usr/bin/docker"

    def test_raises_when_not_found(self) -> None:
        """Should raise RuntimeError when docker not found."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError) as exc_info:
                _docker()
            assert "docker CLI required" in str(exc_info.value)


class TestRunTrivyFs:
    """Tests for _run_trivy_fs function."""

    def test_returns_zero_when_scan_passes(self, fs: FakeFilesystem) -> None:
        """Should return 0 when trivy filesystem scan passes."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/uv.lock", contents="# lockfile content")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")

        config = {"fs_target": "uv.lock", "skip_fs_if_no_lockfile": False}

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("subprocess.call", return_value=0) as mock_call,
        ):
            result = _run_trivy_fs("/usr/bin/trivy", config)

        assert result == 0
        mock_call.assert_called_once_with(
            ["/usr/bin/trivy", "fs", "--config", ".trivy.yaml", "uv.lock"],
            cwd="/fake/repo",
        )

    def test_returns_one_when_scan_fails(self, fs: FakeFilesystem) -> None:
        """Should return 1 when trivy filesystem scan finds vulnerabilities."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/uv.lock", contents="# lockfile content")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")

        config = {"fs_target": "uv.lock", "skip_fs_if_no_lockfile": False}

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("subprocess.call", return_value=1) as mock_call,
        ):
            result = _run_trivy_fs("/usr/bin/trivy", config)

        assert result == 1
        mock_call.assert_called_once()

    def test_normalizes_nonstandard_exit_codes_to_one(self, fs: FakeFilesystem) -> None:
        """Should normalize non-standard exit codes (e.g., 2, 3) to 1.

        Trivy and other tools can exit with various non-zero codes for different
        error conditions. The function should normalize any non-zero exit code
        to 1 to honor the documented 0/1 contract.
        """
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/uv.lock", contents="# lockfile content")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")

        config = {"fs_target": "uv.lock", "skip_fs_if_no_lockfile": False}

        # Test various non-standard exit codes that should all map to 1
        for exit_code in [2, 3, 127, 255]:
            with (
                patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
                patch("subprocess.call", return_value=exit_code),
            ):
                result = _run_trivy_fs("/usr/bin/trivy", config)

            assert result == 1, f"Exit code {exit_code} should be normalized to 1"

    def test_returns_zero_when_lockfile_missing_and_skip_enabled(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 and print warning when lockfile missing and skip enabled."""
        fs.create_dir("/fake/repo")

        config = {"fs_target": "uv.lock", "skip_fs_if_no_lockfile": True}

        with patch.object(lint, "REPO_ROOT", Path("/fake/repo")):
            result = _run_trivy_fs("/usr/bin/trivy", config)

        assert result == 0
        captured = capsys.readouterr()
        assert "Warning: uv.lock not found, skipping filesystem scan" in captured.out

    def test_returns_one_when_lockfile_missing_and_skip_disabled(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 and print error when lockfile missing and skip disabled."""
        fs.create_dir("/fake/repo")

        config = {"fs_target": "uv.lock", "skip_fs_if_no_lockfile": False}

        with patch.object(lint, "REPO_ROOT", Path("/fake/repo")):
            result = _run_trivy_fs("/usr/bin/trivy", config)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: uv.lock not found" in captured.err

    def test_uses_custom_fs_target_from_config(self, fs: FakeFilesystem) -> None:
        """Should use custom fs_target from config."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/requirements.txt", contents="flask==2.0.0")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")

        config = {"fs_target": "requirements.txt", "skip_fs_if_no_lockfile": False}

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("subprocess.call", return_value=0) as mock_call,
        ):
            result = _run_trivy_fs("/usr/bin/trivy", config)

        assert result == 0
        mock_call.assert_called_once_with(
            ["/usr/bin/trivy", "fs", "--config", ".trivy.yaml", "requirements.txt"],
            cwd="/fake/repo",
        )


class TestRunTrivyImage:
    """Tests for _run_trivy_image function."""

    def test_returns_zero_when_scan_passes(self, fs: FakeFilesystem) -> None:
        """Should return 0 when trivy image scan passes."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")
        # Create iid file that will be written by docker build
        iid_file_path = "/tmp/test.iid"
        fs.create_file(iid_file_path, contents=SAMPLE_IMAGE_ID)

        config = {"skip_image_if_no_dockerfile": True}

        mock_tempfile = MagicMock()
        mock_tempfile.__enter__ = MagicMock(return_value=mock_tempfile)
        mock_tempfile.__exit__ = MagicMock(return_value=False)
        mock_tempfile.name = iid_file_path

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.call") as mock_call,
            patch("tempfile.NamedTemporaryFile", return_value=mock_tempfile),
        ):
            # Mock docker build (0), trivy scan (0), docker rmi (0)
            mock_call.side_effect = [0, 0, 0]
            result = _run_trivy_image("/usr/bin/trivy", config)

        assert result == 0
        assert mock_call.call_count == 3

    def test_returns_one_when_scan_fails(self, fs: FakeFilesystem) -> None:
        """Should return 1 when trivy image scan finds vulnerabilities."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")
        iid_file_path = "/tmp/test.iid"
        fs.create_file(iid_file_path, contents=SAMPLE_IMAGE_ID)

        config = {"skip_image_if_no_dockerfile": True}

        mock_tempfile = MagicMock()
        mock_tempfile.__enter__ = MagicMock(return_value=mock_tempfile)
        mock_tempfile.__exit__ = MagicMock(return_value=False)
        mock_tempfile.name = iid_file_path

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.call") as mock_call,
            patch("tempfile.NamedTemporaryFile", return_value=mock_tempfile),
        ):
            # Mock docker build (0), trivy scan (1), docker rmi (0)
            mock_call.side_effect = [0, 1, 0]
            result = _run_trivy_image("/usr/bin/trivy", config)

        assert result == 1
        assert mock_call.call_count == 3

    def test_normalizes_nonstandard_scan_exit_codes_to_one(self, fs: FakeFilesystem) -> None:
        """Should normalize non-standard trivy scan exit codes to 1.

        Trivy can exit with various non-zero codes for different error conditions.
        The function should normalize any non-zero scan exit code to 1 to honor
        the documented 0/1 contract.
        """
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")

        config = {"skip_image_if_no_dockerfile": True}

        # Test various non-standard exit codes that should all map to 1
        for exit_code in [2, 3, 127, 255]:
            # Recreate iid file for each iteration (cleanup deletes it)
            iid_file_path = "/tmp/test.iid"
            if fs.exists(iid_file_path):
                fs.remove(iid_file_path)
            fs.create_file(iid_file_path, contents=SAMPLE_IMAGE_ID)

            mock_tempfile = MagicMock()
            mock_tempfile.__enter__ = MagicMock(return_value=mock_tempfile)
            mock_tempfile.__exit__ = MagicMock(return_value=False)
            mock_tempfile.name = iid_file_path

            with (
                patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
                patch("shutil.which", return_value="/usr/bin/docker"),
                patch("subprocess.call") as mock_call,
                patch("tempfile.NamedTemporaryFile", return_value=mock_tempfile),
            ):
                # Mock docker build (0), trivy scan (exit_code), docker rmi (0)
                mock_call.side_effect = [0, exit_code, 0]
                result = _run_trivy_image("/usr/bin/trivy", config)

            assert result == 1, f"Scan exit code {exit_code} should be normalized to 1"

    def test_normalizes_nonstandard_build_exit_codes_to_one(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should normalize non-standard docker build exit codes to 1.

        Docker can exit with various non-zero codes for different error conditions.
        The function should normalize any non-zero build exit code to 1 to honor
        the documented 0/1 contract.
        """
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")
        iid_file_path = "/tmp/test.iid"
        fs.create_file(iid_file_path, contents="")  # Empty, build failed

        config = {"skip_image_if_no_dockerfile": True}

        mock_tempfile = MagicMock()
        mock_tempfile.__enter__ = MagicMock(return_value=mock_tempfile)
        mock_tempfile.__exit__ = MagicMock(return_value=False)
        mock_tempfile.name = iid_file_path

        # Test various non-standard exit codes that should all map to 1
        for exit_code in [2, 125, 126, 127]:
            with (
                patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
                patch("shutil.which", return_value="/usr/bin/docker"),
                patch("subprocess.call", return_value=exit_code) as mock_call,
                patch("tempfile.NamedTemporaryFile", return_value=mock_tempfile),
            ):
                result = _run_trivy_image("/usr/bin/trivy", config)

            assert result == 1, f"Build exit code {exit_code} should be normalized to 1"
            # Should only call docker build, not trivy scan or docker rmi
            assert mock_call.call_count == 1
            captured = capsys.readouterr()
            assert "Error: Docker build failed" in captured.err

    def test_returns_zero_when_dockerfile_missing_and_skip_enabled(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 and print warning when Dockerfile missing and skip enabled.

        Note: When Dockerfile is missing and skip is enabled, _docker() should NOT
        be called because we don't need Docker for skipping.
        """
        fs.create_dir("/fake/repo")

        config = {"skip_image_if_no_dockerfile": True}

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which") as mock_which,
        ):
            result = _run_trivy_image("/usr/bin/trivy", config)

        assert result == 0
        captured = capsys.readouterr()
        assert "Warning: Dockerfile not found, skipping image scan" in captured.out
        # Docker should not be checked when skipping due to missing Dockerfile
        mock_which.assert_not_called()

    def test_returns_one_when_dockerfile_missing_and_skip_disabled(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 and print error when Dockerfile missing and skip disabled.

        Note: When Dockerfile is missing, _docker() should NOT be called even when
        skip is disabled because we return early with an error.
        """
        fs.create_dir("/fake/repo")

        config = {"skip_image_if_no_dockerfile": False}

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which") as mock_which,
        ):
            result = _run_trivy_image("/usr/bin/trivy", config)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: Dockerfile not found" in captured.err
        # Docker should not be checked when Dockerfile is missing
        mock_which.assert_not_called()

    def test_returns_build_error_when_docker_build_fails(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return build error when Docker build fails."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM invalid:image")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")
        iid_file_path = "/tmp/test.iid"
        fs.create_file(iid_file_path, contents="")  # Empty, build failed

        config = {"skip_image_if_no_dockerfile": True}

        mock_tempfile = MagicMock()
        mock_tempfile.__enter__ = MagicMock(return_value=mock_tempfile)
        mock_tempfile.__exit__ = MagicMock(return_value=False)
        mock_tempfile.name = iid_file_path

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.call", return_value=1) as mock_call,
            patch("tempfile.NamedTemporaryFile", return_value=mock_tempfile),
        ):
            result = _run_trivy_image("/usr/bin/trivy", config)

        assert result == 1
        # Should only call docker build, not trivy scan or docker rmi
        assert mock_call.call_count == 1
        captured = capsys.readouterr()
        assert "Error: Docker build failed" in captured.err

    def test_cleans_up_image_even_when_scan_fails(self, fs: FakeFilesystem) -> None:
        """Should clean up temporary image even when scan fails."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")
        iid_file_path = "/tmp/test.iid"
        fs.create_file(iid_file_path, contents=SAMPLE_IMAGE_ID)

        config = {"skip_image_if_no_dockerfile": True}

        mock_tempfile = MagicMock()
        mock_tempfile.__enter__ = MagicMock(return_value=mock_tempfile)
        mock_tempfile.__exit__ = MagicMock(return_value=False)
        mock_tempfile.name = iid_file_path

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.call") as mock_call,
            patch("tempfile.NamedTemporaryFile", return_value=mock_tempfile),
        ):
            # Mock docker build (0), trivy scan (1), docker rmi (0)
            mock_call.side_effect = [0, 1, 0]
            _run_trivy_image("/usr/bin/trivy", config)

        # Verify docker rmi was called with image ID
        assert mock_call.call_count == 3
        cleanup_call = mock_call.call_args_list[2]
        assert "rmi" in cleanup_call[0][0]
        assert SAMPLE_IMAGE_ID in cleanup_call[0][0]

    def test_warns_when_image_cleanup_fails(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should warn when temporary image cleanup fails."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")
        iid_file_path = "/tmp/test.iid"
        fs.create_file(iid_file_path, contents=SAMPLE_IMAGE_ID)

        config = {"skip_image_if_no_dockerfile": True}

        mock_tempfile = MagicMock()
        mock_tempfile.__enter__ = MagicMock(return_value=mock_tempfile)
        mock_tempfile.__exit__ = MagicMock(return_value=False)
        mock_tempfile.name = iid_file_path

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.call") as mock_call,
            patch("tempfile.NamedTemporaryFile", return_value=mock_tempfile),
        ):
            # Mock docker build (0), trivy scan (0), docker rmi (1 - failed)
            mock_call.side_effect = [0, 0, 1]
            result = _run_trivy_image("/usr/bin/trivy", config)

        assert result == 0  # Scan passed, cleanup failure doesn't affect result
        captured = capsys.readouterr()
        assert "Warning: Failed to remove temporary image" in captured.err

    def test_uses_iidfile_to_capture_image_id(self, fs: FakeFilesystem) -> None:
        """Should use --iidfile to capture image ID and use it for scan/cleanup."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")
        iid_file_path = "/tmp/test.iid"
        fs.create_file(iid_file_path, contents=SAMPLE_IMAGE_ID)

        config = {"skip_image_if_no_dockerfile": True}

        mock_tempfile = MagicMock()
        mock_tempfile.__enter__ = MagicMock(return_value=mock_tempfile)
        mock_tempfile.__exit__ = MagicMock(return_value=False)
        mock_tempfile.name = iid_file_path

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.call") as mock_call,
            patch("tempfile.NamedTemporaryFile", return_value=mock_tempfile),
        ):
            mock_call.side_effect = [0, 0, 0]
            _run_trivy_image("/usr/bin/trivy", config)

        # Check that --iidfile was used in build command
        build_call = mock_call.call_args_list[0]
        assert "--iidfile" in build_call[0][0]
        # Check that image ID was used for scan
        scan_call = mock_call.call_args_list[1]
        assert SAMPLE_IMAGE_ID in scan_call[0][0]
        # Check that image ID was used for cleanup
        cleanup_call = mock_call.call_args_list[2]
        assert SAMPLE_IMAGE_ID in cleanup_call[0][0]

    def test_prints_progress_messages(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print progress messages during image scan."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")
        iid_file_path = "/tmp/test.iid"
        fs.create_file(iid_file_path, contents=SAMPLE_IMAGE_ID)

        config = {"skip_image_if_no_dockerfile": True}

        mock_tempfile = MagicMock()
        mock_tempfile.__enter__ = MagicMock(return_value=mock_tempfile)
        mock_tempfile.__exit__ = MagicMock(return_value=False)
        mock_tempfile.name = iid_file_path

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.call") as mock_call,
            patch("tempfile.NamedTemporaryFile", return_value=mock_tempfile),
        ):
            mock_call.side_effect = [0, 0, 0]
            _run_trivy_image("/usr/bin/trivy", config)

        captured = capsys.readouterr()
        assert "Building temporary image..." in captured.out
        # Image ID is truncated to first 12 chars for display
        assert "Scanning image: sha256:abc12" in captured.out
        assert "Removing temporary image: sha256:abc12" in captured.out

    def test_cleans_up_image_when_iid_read_fails_initially(self, fs: FakeFilesystem) -> None:
        """Should clean up image if initial IID read fails but cleanup can read it.

        This tests the robustness of cleanup: if the first read_text() raises,
        the finally block should retry reading the IID file to still clean up
        the temporary Docker image.
        """
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")
        iid_file_path = "/tmp/test.iid"
        fs.create_file(iid_file_path, contents=SAMPLE_IMAGE_ID)

        config = {"skip_image_if_no_dockerfile": True}

        mock_tempfile = MagicMock()
        mock_tempfile.__enter__ = MagicMock(return_value=mock_tempfile)
        mock_tempfile.__exit__ = MagicMock(return_value=False)
        mock_tempfile.name = iid_file_path

        # Track calls to read_text - we'll use a mock that tracks calls
        read_call_count = {"count": 0}

        def mock_read_text(*args: object, **kwargs: object) -> str:
            read_call_count["count"] += 1
            if read_call_count["count"] == 1:
                # First read fails (simulating transient error)
                raise OSError("Simulated read failure")
            # Second read (in cleanup) succeeds
            return SAMPLE_IMAGE_ID

        mock_path_class = MagicMock()
        mock_path_instance = MagicMock()
        mock_path_instance.read_text = mock_read_text
        mock_path_instance.unlink = MagicMock()
        mock_path_class.return_value = mock_path_instance

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.call") as mock_call,
            patch("tempfile.NamedTemporaryFile", return_value=mock_tempfile),
            patch("scripts.dev.lint.Path") as patched_path,
        ):
            # Configure Path to return our mock for the iid file path
            def path_side_effect(p: str) -> MagicMock | Path:
                if p == iid_file_path:
                    return mock_path_instance
                return Path(p)

            patched_path.side_effect = path_side_effect

            # docker build succeeds, docker rmi will be called in cleanup
            mock_call.side_effect = [0, 0]  # docker build, docker rmi
            with pytest.raises(OSError, match="Simulated read failure"):
                _run_trivy_image("/usr/bin/trivy", config)

        # Verify cleanup was attempted with the image ID
        rmi_calls = [c for c in mock_call.call_args_list if "rmi" in str(c)]
        assert len(rmi_calls) == 1
        assert SAMPLE_IMAGE_ID in rmi_calls[0][0][0]
        # Verify read_text was called twice (initial + cleanup retry)
        assert read_call_count["count"] == 2


class TestRunTrivy:
    """Tests for the main _run_trivy orchestrator function."""

    def test_returns_zero_when_both_scans_pass(self, fs: FakeFilesystem) -> None:
        """Should return 0 when both filesystem and image scans pass."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/uv.lock", contents="# lockfile")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")
        fs.create_file("/fake/repo/.lint.trivy.yaml", contents="")
        iid_file_path = "/tmp/test.iid"
        fs.create_file(iid_file_path, contents=SAMPLE_IMAGE_ID)

        mock_tempfile = MagicMock()
        mock_tempfile.__enter__ = MagicMock(return_value=mock_tempfile)
        mock_tempfile.__exit__ = MagicMock(return_value=False)
        mock_tempfile.name = iid_file_path

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_TRIVY_CONFIG", Path("/fake/repo/.lint.trivy.yaml")),
            patch("shutil.which", return_value="/usr/bin/trivy"),
            patch("subprocess.call", return_value=0),
            patch("tempfile.NamedTemporaryFile", return_value=mock_tempfile),
        ):
            result = _run_trivy()

        assert result == 0

    def test_short_circuits_when_fs_scan_fails(self, fs: FakeFilesystem) -> None:
        """Should return immediately when filesystem scan fails, skipping image scan."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/uv.lock", contents="# lockfile")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")
        fs.create_file("/fake/repo/.lint.trivy.yaml", contents="")

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_TRIVY_CONFIG", Path("/fake/repo/.lint.trivy.yaml")),
            patch("shutil.which", return_value="/usr/bin/trivy"),
            patch("subprocess.call") as mock_call,
        ):
            # First call (fs scan) returns 1, should not proceed to image scan
            mock_call.return_value = 1
            result = _run_trivy()

        assert result == 1
        # Only fs scan should be called, not image scan
        assert mock_call.call_count == 1

    def test_returns_image_scan_result_when_fs_passes(self, fs: FakeFilesystem) -> None:
        """Should return image scan result when filesystem scan passes."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/uv.lock", contents="# lockfile")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")
        fs.create_file("/fake/repo/.lint.trivy.yaml", contents="")
        iid_file_path = "/tmp/test.iid"
        fs.create_file(iid_file_path, contents=SAMPLE_IMAGE_ID)

        mock_tempfile = MagicMock()
        mock_tempfile.__enter__ = MagicMock(return_value=mock_tempfile)
        mock_tempfile.__exit__ = MagicMock(return_value=False)
        mock_tempfile.name = iid_file_path

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_TRIVY_CONFIG", Path("/fake/repo/.lint.trivy.yaml")),
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.call") as mock_call,
            patch("tempfile.NamedTemporaryFile", return_value=mock_tempfile),
        ):
            # fs scan (0), docker build (0), trivy scan (1), docker rmi (0)
            mock_call.side_effect = [0, 0, 1, 0]
            result = _run_trivy()

        assert result == 1

    def test_raises_when_trivy_not_installed(self) -> None:
        """Should raise RuntimeError when trivy is not installed."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError) as exc_info:
                _run_trivy()
            assert "trivy CLI required" in str(exc_info.value)

    def test_loads_config_from_lint_trivy_yaml(self, fs: FakeFilesystem) -> None:
        """Should load configuration from .lint.trivy.yaml."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/uv.lock", contents="# lockfile")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")
        fs.create_file(
            "/fake/repo/.lint.trivy.yaml",
            contents=(
                "fs_target: custom.lock\n"
                "skip_fs_if_no_lockfile: true\n"
                "skip_image_if_no_dockerfile: false\n"
            ),
        )
        iid_file_path = "/tmp/test.iid"
        fs.create_file(iid_file_path, contents=SAMPLE_IMAGE_ID)

        mock_tempfile = MagicMock()
        mock_tempfile.__enter__ = MagicMock(return_value=mock_tempfile)
        mock_tempfile.__exit__ = MagicMock(return_value=False)
        mock_tempfile.name = iid_file_path

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_TRIVY_CONFIG", Path("/fake/repo/.lint.trivy.yaml")),
            patch("shutil.which", return_value="/usr/bin/trivy"),
            patch("subprocess.call") as mock_call,
            patch("tempfile.NamedTemporaryFile", return_value=mock_tempfile),
        ):
            # fs scan will skip (custom.lock doesn't exist, skip enabled)
            # This will return 0 from fs scan and proceed to image scan
            mock_call.side_effect = [0, 0, 0]  # docker build, trivy scan, docker rmi
            _run_trivy()

        # Verify that calls proceeded (fs skipped, image scan ran)
        # The image scan uses iidfile now, not a custom image name
        # Verify docker build was called with --iidfile
        build_calls = [c for c in mock_call.call_args_list if "--iidfile" in str(c)]
        assert len(build_calls) > 0, "Expected image scan to run with --iidfile"

    def test_skips_fs_scan_when_enable_fs_scan_false(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should skip filesystem scan when enable_fs_scan is false."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/uv.lock", contents="# lockfile")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")
        fs.create_file(
            "/fake/repo/.lint.trivy.yaml",
            contents="enable_fs_scan: false\nenable_image_scan: true\n",
        )
        iid_file_path = "/tmp/test.iid"
        fs.create_file(iid_file_path, contents=SAMPLE_IMAGE_ID)

        mock_tempfile = MagicMock()
        mock_tempfile.__enter__ = MagicMock(return_value=mock_tempfile)
        mock_tempfile.__exit__ = MagicMock(return_value=False)
        mock_tempfile.name = iid_file_path

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_TRIVY_CONFIG", Path("/fake/repo/.lint.trivy.yaml")),
            patch("shutil.which", return_value="/usr/bin/trivy"),
            patch("subprocess.call") as mock_call,
            patch("tempfile.NamedTemporaryFile", return_value=mock_tempfile),
        ):
            # Only image scan should run: docker build (0), trivy scan (0), docker rmi (0)
            mock_call.side_effect = [0, 0, 0]
            result = _run_trivy()

        assert result == 0
        captured = capsys.readouterr()
        assert "Filesystem scan disabled via enable_fs_scan: false" in captured.out
        # Verify no trivy fs call was made (only docker build, trivy image, docker rmi)
        fs_calls = [c for c in mock_call.call_args_list if "fs" in str(c[0][0])]
        assert len(fs_calls) == 0

    def test_skips_image_scan_when_enable_image_scan_false(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should skip image scan when enable_image_scan is false."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/uv.lock", contents="# lockfile")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")
        fs.create_file(
            "/fake/repo/.lint.trivy.yaml",
            contents="enable_fs_scan: true\nenable_image_scan: false\n",
        )

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_TRIVY_CONFIG", Path("/fake/repo/.lint.trivy.yaml")),
            patch("shutil.which", return_value="/usr/bin/trivy"),
            patch("subprocess.call") as mock_call,
        ):
            # Only fs scan should run
            mock_call.return_value = 0
            result = _run_trivy()

        assert result == 0
        captured = capsys.readouterr()
        assert "Image scan disabled via enable_image_scan: false" in captured.out
        # Verify only fs scan was called (no docker build)
        assert mock_call.call_count == 1
        fs_call = mock_call.call_args_list[0]
        assert "fs" in fs_call[0][0]

    def test_skips_both_scans_when_both_disabled(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should skip both scans when both are disabled."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/uv.lock", contents="# lockfile")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")
        fs.create_file(
            "/fake/repo/.lint.trivy.yaml",
            contents="enable_fs_scan: false\nenable_image_scan: false\n",
        )

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_TRIVY_CONFIG", Path("/fake/repo/.lint.trivy.yaml")),
            patch("shutil.which", return_value="/usr/bin/trivy"),
            patch("subprocess.call") as mock_call,
        ):
            result = _run_trivy()

        assert result == 0
        captured = capsys.readouterr()
        assert "Filesystem scan disabled via enable_fs_scan: false" in captured.out
        assert "Image scan disabled via enable_image_scan: false" in captured.out
        # No subprocess calls should be made
        mock_call.assert_not_called()

    def test_defaults_enable_flags_to_true(self, fs: FakeFilesystem) -> None:
        """Should default enable_fs_scan and enable_image_scan to true if not specified."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/uv.lock", contents="# lockfile")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")
        # Config with no enable_* flags - they should default to True
        fs.create_file("/fake/repo/.lint.trivy.yaml", contents="fs_target: uv.lock\n")
        iid_file_path = "/tmp/test.iid"
        fs.create_file(iid_file_path, contents=SAMPLE_IMAGE_ID)

        mock_tempfile = MagicMock()
        mock_tempfile.__enter__ = MagicMock(return_value=mock_tempfile)
        mock_tempfile.__exit__ = MagicMock(return_value=False)
        mock_tempfile.name = iid_file_path

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_TRIVY_CONFIG", Path("/fake/repo/.lint.trivy.yaml")),
            patch("shutil.which", return_value="/usr/bin/trivy"),
            patch("subprocess.call") as mock_call,
            patch("tempfile.NamedTemporaryFile", return_value=mock_tempfile),
        ):
            # fs scan (0), docker build (0), trivy image (0), docker rmi (0)
            mock_call.side_effect = [0, 0, 0, 0]
            result = _run_trivy()

        assert result == 0
        # Both scans should run: 1 fs call + 3 image calls (build, scan, rmi)
        assert mock_call.call_count == 4
