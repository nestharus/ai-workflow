"""Tests for scripts.dev.linter.linters.trivy module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.linter.linters.trivy import TrivyLinter


class TestTrivyLinterInit:
    """Tests for TrivyLinter class attributes."""

    def test_name(self) -> None:
        """Test linter name attribute."""
        linter = TrivyLinter()
        assert linter.name == "trivy"

    def test_supports_file_filtering(self) -> None:
        """Test supports_file_filtering attribute."""
        linter = TrivyLinter()
        assert linter.supports_file_filtering is False


class TestTrivyLinterRunScanConfiguration:
    """Tests for TrivyLinter.run scan enable/disable."""

    @patch("scripts.dev.linter.linters.trivy.load_yaml_config")
    @patch("scripts.dev.linter.linters.trivy.get_executable")
    def test_run_fs_scan_disabled(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run with filesystem scan disabled (lines 54, 58-59, branch 54 False)."""
        mock_get_exe.return_value = "/usr/bin/trivy"
        mock_load_config.return_value = {
            "enable_fs_scan": False,
            "enable_image_scan": False,
        }

        linter = TrivyLinter()
        result = linter.run()

        assert result.success is True
        captured = capsys.readouterr()
        assert "Filesystem scan disabled via enable_fs_scan: false" in captured.out

    @patch("scripts.dev.linter.linters.trivy.load_yaml_config")
    @patch("scripts.dev.linter.linters.trivy.get_executable")
    def test_run_image_scan_disabled(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run with image scan disabled (lines 62, 64-65, branch 62 False)."""
        mock_get_exe.return_value = "/usr/bin/trivy"
        mock_load_config.return_value = {
            "enable_fs_scan": False,
            "enable_image_scan": False,
        }

        linter = TrivyLinter()
        result = linter.run()

        assert result.success is True
        captured = capsys.readouterr()
        assert "Image scan disabled via enable_image_scan: false" in captured.out


class TestTrivyLinterRunFsScan:
    """Tests for TrivyLinter._run_trivy_fs method."""

    @patch("scripts.dev.linter.linters.trivy.subprocess.call")
    @patch("scripts.dev.linter.linters.trivy.REPO_ROOT", Path("/fake/repo"))
    @patch("scripts.dev.linter.linters.trivy.load_yaml_config")
    @patch("scripts.dev.linter.linters.trivy.get_executable")
    def test_run_fs_scan_success(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_subprocess_call: MagicMock,
    ) -> None:
        """Test filesystem scan success (lines 54-57, branch 56 False)."""
        mock_get_exe.return_value = "/usr/bin/trivy"
        mock_load_config.return_value = {
            "enable_fs_scan": True,
            "enable_image_scan": False,
            "fs_target": "uv.lock",
        }
        mock_subprocess_call.return_value = 0

        with patch.object(Path, "exists", return_value=True):
            linter = TrivyLinter()
            result = linter.run()

        assert result.success is True

    @patch("scripts.dev.linter.linters.trivy.subprocess.call")
    @patch("scripts.dev.linter.linters.trivy.REPO_ROOT", Path("/fake/repo"))
    @patch("scripts.dev.linter.linters.trivy.load_yaml_config")
    @patch("scripts.dev.linter.linters.trivy.get_executable")
    def test_run_fs_scan_failure(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_subprocess_call: MagicMock,
    ) -> None:
        """Test filesystem scan failure returns early (lines 55-57, branch 56 True)."""
        mock_get_exe.return_value = "/usr/bin/trivy"
        mock_load_config.return_value = {
            "enable_fs_scan": True,
            "enable_image_scan": True,
            "fs_target": "uv.lock",
        }
        mock_subprocess_call.return_value = 1  # Failure

        with patch.object(Path, "exists", return_value=True):
            linter = TrivyLinter()
            result = linter.run()

        assert result.success is False
        # Image scan should not run due to short-circuit
        assert mock_subprocess_call.call_count == 1


class TestTrivyLinterRunTrivyFsMethod:
    """Tests for TrivyLinter._run_trivy_fs internal method."""

    def test_run_trivy_fs_lockfile_missing_skip(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test _run_trivy_fs when lockfile missing and skip configured."""
        linter = TrivyLinter()

        with patch.object(Path, "exists", return_value=False):
            result = linter._run_trivy_fs(
                "/usr/bin/trivy",
                {"fs_target": "uv.lock", "skip_fs_if_no_lockfile": True},
            )

        assert result.success is True
        captured = capsys.readouterr()
        assert "uv.lock not found, skipping" in captured.out

    def test_run_trivy_fs_lockfile_missing_error(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test _run_trivy_fs when lockfile missing and skip not configured."""
        linter = TrivyLinter()

        with patch.object(Path, "exists", return_value=False):
            result = linter._run_trivy_fs(
                "/usr/bin/trivy",
                {"fs_target": "uv.lock", "skip_fs_if_no_lockfile": False},
            )

        assert result.success is False
        captured = capsys.readouterr()
        assert "uv.lock not found" in captured.out


class TestTrivyLinterRunTrivyImageMethod:
    """Tests for TrivyLinter._run_trivy_image internal method."""

    def test_run_trivy_image_dockerfile_missing_skip(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test _run_trivy_image when Dockerfile missing and skip configured."""
        linter = TrivyLinter()

        with patch.object(Path, "exists", return_value=False):
            result = linter._run_trivy_image(
                "/usr/bin/trivy",
                {"skip_image_if_no_dockerfile": True},
            )

        assert result.success is True
        captured = capsys.readouterr()
        assert "Dockerfile not found, skipping" in captured.out

    def test_run_trivy_image_dockerfile_missing_error(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test _run_trivy_image when Dockerfile missing and skip not configured."""
        linter = TrivyLinter()

        with patch.object(Path, "exists", return_value=False):
            result = linter._run_trivy_image(
                "/usr/bin/trivy",
                {"skip_image_if_no_dockerfile": False},
            )

        assert result.success is False
        captured = capsys.readouterr()
        assert "Dockerfile not found" in captured.out

    @patch("scripts.dev.linter.linters.trivy.subprocess.call")
    @patch("scripts.dev.linter.linters.trivy.get_executable")
    def test_run_trivy_image_build_failure(
        self,
        mock_get_exe: MagicMock,
        mock_subprocess_call: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test _run_trivy_image when Docker build fails."""
        mock_get_exe.return_value = "/usr/bin/docker"
        mock_subprocess_call.return_value = 1  # Build fails

        linter = TrivyLinter()

        with patch.object(Path, "exists", return_value=True):
            result = linter._run_trivy_image(
                "/usr/bin/trivy",
                {"skip_image_if_no_dockerfile": True},
            )

        assert result.success is False
        captured = capsys.readouterr()
        assert "Docker build failed" in captured.out
