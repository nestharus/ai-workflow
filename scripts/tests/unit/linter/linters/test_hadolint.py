from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.linter.linters.hadolint import HadolintLinter


class TestHadolintLinterRunWithFiles:
    @patch("scripts.dev.linter.linters.hadolint.is_path_included")
    @patch("scripts.dev.linter.linters.hadolint.run_checked")
    @patch("scripts.dev.linter.linters.hadolint.load_yaml_config")
    @patch("scripts.dev.linter.linters.hadolint.get_executable")
    def test_run_with_dockerfile_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
        mock_is_included: MagicMock,
    ) -> None:
        """Test run with Dockerfile specified."""
        mock_get_exe.return_value = "/usr/bin/hadolint"
        mock_load_config.return_value = {"included_paths": ["Dockerfile", "app/**/Dockerfile"]}
        mock_is_included.return_value = True

        linter = HadolintLinter()
        result = linter.run(files=["Dockerfile", "README.md", "app/Dockerfile"])

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        assert "/usr/bin/hadolint" in call_args
        assert "--config" in call_args

    @patch("scripts.dev.linter.linters.hadolint.is_path_included")
    @patch("scripts.dev.linter.linters.hadolint.load_yaml_config")
    @patch("scripts.dev.linter.linters.hadolint.get_executable")
    def test_run_with_no_dockerfiles(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_included: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when no Dockerfile in list."""
        mock_get_exe.return_value = "/usr/bin/hadolint"
        mock_load_config.return_value = {"included_paths": ["Dockerfile", "app/**/Dockerfile"]}
        mock_is_included.return_value = True

        linter = HadolintLinter()
        result = linter.run(files=["config.yaml", "test.py"])

        assert result.success is True
        captured = capsys.readouterr()
        assert "No Dockerfiles found for hadolint scan" in captured.out


class TestHadolintLinterRunWithoutFiles:
    @patch("scripts.dev.linter.linters.hadolint.REPO_ROOT")
    @patch("scripts.dev.linter.linters.hadolint.run_checked")
    @patch("scripts.dev.linter.linters.hadolint.is_path_included")
    @patch("scripts.dev.linter.linters.hadolint.load_yaml_config")
    @patch("scripts.dev.linter.linters.hadolint.get_executable")
    def test_run_finds_dockerfiles(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_included: MagicMock,
        mock_run_checked: MagicMock,
        mock_repo_root: MagicMock,
    ) -> None:
        """Test run with glob mode finding Dockerfiles."""
        mock_get_exe.return_value = "/usr/bin/hadolint"
        mock_load_config.return_value = {"included_paths": ["Dockerfile", "app/**/Dockerfile"]}
        mock_is_included.return_value = True  # All paths included

        mock_dockerfile = MagicMock(spec=Path)
        mock_dockerfile.is_file.return_value = True
        mock_dockerfile.relative_to.return_value = Path("Dockerfile")
        mock_dockerfile.__str__ = lambda self: "/repo/Dockerfile"

        mock_repo_root.rglob.return_value = [mock_dockerfile]
        mock_repo_root.__truediv__ = lambda self, x: Path(x)

        linter = HadolintLinter()
        result = linter.run(files=None)

        assert result.success is True
        mock_run_checked.assert_called_once()

    @patch("scripts.dev.linter.linters.hadolint.REPO_ROOT")
    @patch("scripts.dev.linter.linters.hadolint.load_yaml_config")
    @patch("scripts.dev.linter.linters.hadolint.get_executable")
    def test_run_no_dockerfiles_found(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_repo_root: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when no Dockerfiles found."""
        mock_get_exe.return_value = "/usr/bin/hadolint"
        mock_load_config.return_value = {"included_paths": ["Dockerfile", "app/**/Dockerfile"]}

        mock_repo_root.rglob.return_value = []
        mock_repo_root.__truediv__ = lambda self, x: Path(x)

        linter = HadolintLinter()
        result = linter.run(files=None)

        assert result.success is True
        captured = capsys.readouterr()
        assert "No Dockerfiles found for hadolint scan" in captured.out

    @patch("scripts.dev.linter.linters.hadolint.REPO_ROOT")
    @patch("scripts.dev.linter.linters.hadolint.is_path_included")
    @patch("scripts.dev.linter.linters.hadolint.load_yaml_config")
    @patch("scripts.dev.linter.linters.hadolint.get_executable")
    def test_run_dockerfile_not_in_included_paths(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_included: MagicMock,
        mock_repo_root: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when Dockerfile is not in included_paths."""
        mock_get_exe.return_value = "/usr/bin/hadolint"
        mock_load_config.return_value = {"included_paths": ["app/**/Dockerfile"]}
        mock_is_included.return_value = False  # Not in included paths

        mock_dockerfile = MagicMock(spec=Path)
        mock_dockerfile.is_file.return_value = True
        mock_dockerfile.relative_to.return_value = Path("node_modules/Dockerfile")

        mock_repo_root.rglob.return_value = [mock_dockerfile]
        mock_repo_root.__truediv__ = lambda self, x: Path(x)

        linter = HadolintLinter()
        result = linter.run(files=None)

        assert result.success is True
        captured = capsys.readouterr()
        assert "No Dockerfiles found for hadolint scan" in captured.out

    @patch("scripts.dev.linter.linters.hadolint.REPO_ROOT")
    @patch("scripts.dev.linter.linters.hadolint.load_yaml_config")
    @patch("scripts.dev.linter.linters.hadolint.get_executable")
    def test_run_dockerfile_not_file(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_repo_root: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when rglob returns directory."""
        mock_get_exe.return_value = "/usr/bin/hadolint"
        mock_load_config.return_value = {"included_paths": ["Dockerfile", "app/**/Dockerfile"]}

        mock_dockerfile = MagicMock(spec=Path)
        mock_dockerfile.is_file.return_value = False

        mock_repo_root.rglob.return_value = [mock_dockerfile]
        mock_repo_root.__truediv__ = lambda self, x: Path(x)

        linter = HadolintLinter()
        result = linter.run(files=None)

        assert result.success is True
        captured = capsys.readouterr()
        assert "No Dockerfiles found for hadolint scan" in captured.out


class TestHadolintLinterRunCheckedCall:
    @patch("scripts.dev.linter.linters.hadolint.HADOLINT_CONFIG", Path("/repo/.hadolint.yaml"))
    @patch("scripts.dev.linter.linters.hadolint.is_path_included")
    @patch("scripts.dev.linter.linters.hadolint.run_checked")
    @patch("scripts.dev.linter.linters.hadolint.load_yaml_config")
    @patch("scripts.dev.linter.linters.hadolint.get_executable")
    def test_run_checked_call_structure(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
        mock_is_included: MagicMock,
    ) -> None:
        """Test run_checked is called with correct structure."""
        mock_get_exe.return_value = "/usr/bin/hadolint"
        mock_load_config.return_value = {"included_paths": ["Dockerfile", "app/**/Dockerfile"]}
        mock_is_included.return_value = True

        linter = HadolintLinter()
        result = linter.run(files=["Dockerfile"])

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        assert call_args[0] == "/usr/bin/hadolint"
        assert "--config" in call_args
        assert "/repo/.hadolint.yaml" in call_args
