from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.linter.linters.trivy import TrivyLinter


class TestTrivyLinterInit:
    def test_name(self) -> None:
        """Test linter name attribute."""
        linter = TrivyLinter()
        assert linter.name == "trivy"

    def test_supports_file_filtering(self) -> None:
        """Test supports_file_filtering attribute."""
        linter = TrivyLinter()
        assert linter.supports_file_filtering is True


class TestTrivyLinterRunTrivyFsMethod:
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
