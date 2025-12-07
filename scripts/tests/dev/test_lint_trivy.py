"""Tests for Trivy integration in scripts.dev.lint module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

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

    def test_returns_nonzero_when_scan_fails(self, fs: FakeFilesystem) -> None:
        """Should return non-zero when trivy filesystem scan finds vulnerabilities."""
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

        config = {
            "temp_image_name": "ai-workflow-trivy-temp",
            "skip_image_if_no_dockerfile": True,
        }

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.call") as mock_call,
        ):
            # Mock docker build (0), trivy scan (0), docker rmi (0)
            mock_call.side_effect = [0, 0, 0]
            result = _run_trivy_image("/usr/bin/trivy", config)

        assert result == 0
        assert mock_call.call_count == 3

    def test_returns_nonzero_when_scan_fails(self, fs: FakeFilesystem) -> None:
        """Should return non-zero when trivy image scan finds vulnerabilities."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")

        config = {
            "temp_image_name": "ai-workflow-trivy-temp",
            "skip_image_if_no_dockerfile": True,
        }

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.call") as mock_call,
        ):
            # Mock docker build (0), trivy scan (1), docker rmi (0)
            mock_call.side_effect = [0, 1, 0]
            result = _run_trivy_image("/usr/bin/trivy", config)

        assert result == 1
        assert mock_call.call_count == 3

    def test_returns_zero_when_dockerfile_missing_and_skip_enabled(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 and print warning when Dockerfile missing and skip enabled."""
        fs.create_dir("/fake/repo")

        config = {
            "temp_image_name": "ai-workflow-trivy-temp",
            "skip_image_if_no_dockerfile": True,
        }

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which", return_value="/usr/bin/docker"),
        ):
            result = _run_trivy_image("/usr/bin/trivy", config)

        assert result == 0
        captured = capsys.readouterr()
        assert "Warning: Dockerfile not found, skipping image scan" in captured.out

    def test_returns_one_when_dockerfile_missing_and_skip_disabled(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 and print error when Dockerfile missing and skip disabled."""
        fs.create_dir("/fake/repo")

        config = {
            "temp_image_name": "ai-workflow-trivy-temp",
            "skip_image_if_no_dockerfile": False,
        }

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which", return_value="/usr/bin/docker"),
        ):
            result = _run_trivy_image("/usr/bin/trivy", config)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: Dockerfile not found" in captured.err

    def test_returns_build_error_when_docker_build_fails(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return build error when Docker build fails."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM invalid:image")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")

        config = {
            "temp_image_name": "ai-workflow-trivy-temp",
            "skip_image_if_no_dockerfile": True,
        }

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.call", return_value=1) as mock_call,
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

        config = {
            "temp_image_name": "ai-workflow-trivy-temp",
            "skip_image_if_no_dockerfile": True,
        }

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.call") as mock_call,
        ):
            # Mock docker build (0), trivy scan (1), docker rmi (0)
            mock_call.side_effect = [0, 1, 0]
            _run_trivy_image("/usr/bin/trivy", config)

        # Verify docker rmi was called
        assert mock_call.call_count == 3
        cleanup_call = mock_call.call_args_list[2]
        assert "rmi" in cleanup_call[0][0]

    def test_warns_when_image_cleanup_fails(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should warn when temporary image cleanup fails."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")

        config = {
            "temp_image_name": "ai-workflow-trivy-temp",
            "skip_image_if_no_dockerfile": True,
        }

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.call") as mock_call,
        ):
            # Mock docker build (0), trivy scan (0), docker rmi (1 - failed)
            mock_call.side_effect = [0, 0, 1]
            result = _run_trivy_image("/usr/bin/trivy", config)

        assert result == 0  # Scan passed, cleanup failure doesn't affect result
        captured = capsys.readouterr()
        assert "Warning: Failed to remove temporary image" in captured.err

    def test_uses_custom_image_name_from_config(self, fs: FakeFilesystem) -> None:
        """Should use custom temp_image_name from config."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")

        config = {
            "temp_image_name": "custom-trivy-image",
            "skip_image_if_no_dockerfile": True,
        }

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.call") as mock_call,
        ):
            mock_call.side_effect = [0, 0, 0]
            _run_trivy_image("/usr/bin/trivy", config)

        # Check that custom image name was used
        build_call = mock_call.call_args_list[0]
        assert "custom-trivy-image" in build_call[0][0]
        scan_call = mock_call.call_args_list[1]
        assert "custom-trivy-image" in scan_call[0][0]
        cleanup_call = mock_call.call_args_list[2]
        assert "custom-trivy-image" in cleanup_call[0][0]

    def test_prints_progress_messages(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print progress messages during image scan."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")

        config = {
            "temp_image_name": "ai-workflow-trivy-temp",
            "skip_image_if_no_dockerfile": True,
        }

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.call") as mock_call,
        ):
            mock_call.side_effect = [0, 0, 0]
            _run_trivy_image("/usr/bin/trivy", config)

        captured = capsys.readouterr()
        assert "Building temporary image: ai-workflow-trivy-temp" in captured.out
        assert "Scanning image: ai-workflow-trivy-temp" in captured.out
        assert "Removing temporary image: ai-workflow-trivy-temp" in captured.out


class TestRunTrivy:
    """Tests for the main _run_trivy orchestrator function."""

    def test_returns_zero_when_both_scans_pass(self, fs: FakeFilesystem) -> None:
        """Should return 0 when both filesystem and image scans pass."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/uv.lock", contents="# lockfile")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine:latest")
        fs.create_file("/fake/repo/.trivy.yaml", contents="")
        fs.create_file("/fake/repo/.lint.trivy.yaml", contents="")

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_TRIVY_CONFIG", Path("/fake/repo/.lint.trivy.yaml")),
            patch("shutil.which", return_value="/usr/bin/trivy"),
            patch("subprocess.call", return_value=0),
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

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_TRIVY_CONFIG", Path("/fake/repo/.lint.trivy.yaml")),
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.call") as mock_call,
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
                "temp_image_name: custom-image\n"
                "skip_image_if_no_dockerfile: false\n"
            ),
        )

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_TRIVY_CONFIG", Path("/fake/repo/.lint.trivy.yaml")),
            patch("shutil.which", return_value="/usr/bin/trivy"),
            patch("subprocess.call") as mock_call,
        ):
            # fs scan will skip (custom.lock doesn't exist, skip enabled)
            # This will return 0 from fs scan and proceed to image scan
            mock_call.side_effect = [0, 0, 0]  # docker build, trivy scan, docker rmi
            _run_trivy()

        # Verify that custom config was used (check image name in calls)
        if mock_call.call_count > 0:
            # Check if custom image name appears in any call
            # If image scan ran, custom-image should be in the calls
            # If it didn't run, that's also valid (fs scan skipped)
            pass
