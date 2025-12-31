import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from scripts.dev.linter.base import (
    BaseLinter,
    InvalidCommandError,
    LinterResult,
    _run_linter_safe,
    calculate_fileset,
    execute_phase,
    filter_files_with_config,
    get_executable,
    run_checked,
    schedule_linters,
)


class TestGetExecutable:
    def test_get_executable_found(self) -> None:
        """Test get_executable when executable exists."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/python"
            result = get_executable("python", "Python not found")
            assert result == "/usr/bin/python"
            mock_which.assert_called_once_with("python")

    def test_get_executable_not_found_raises_runtime_error(self) -> None:
        """Test get_executable raises RuntimeError when executable not found (lines 77-80)."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = None  # Simulates executable not found
            with pytest.raises(RuntimeError) as exc_info:
                get_executable("nonexistent_tool", "Custom error: tool not found")
            assert str(exc_info.value) == "Custom error: tool not found"
            mock_which.assert_called_once_with("nonexistent_tool")

    def test_get_executable_not_found_with_different_messages(self) -> None:
        """Test get_executable with different error messages."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = None

            # Test with detailed error message
            with pytest.raises(RuntimeError) as exc_info:
                get_executable(
                    "gitleaks", "gitleaks not found. Install with: brew install gitleaks"
                )
            assert "gitleaks not found" in str(exc_info.value)

    def test_get_executable_returns_string_path(self) -> None:
        """Test that get_executable returns a string path."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/local/bin/ruff"
            result = get_executable("ruff", "ruff not found")
            assert isinstance(result, str)
            assert result == "/usr/local/bin/ruff"


class TestRunChecked:
    def test_run_checked_success(self) -> None:
        """Test run_checked with a successful command."""
        with patch("subprocess.check_call") as mock_check_call:
            mock_check_call.return_value = 0
            run_checked(["echo", "hello"])
            mock_check_call.assert_called_once_with(["echo", "hello"], cwd=None)

    def test_run_checked_with_cwd(self) -> None:
        """Test run_checked with a working directory."""
        with patch("subprocess.check_call") as mock_check_call:
            mock_check_call.return_value = 0
            cwd = Path("/tmp")
            run_checked(["ls", "-la"], cwd=cwd)
            mock_check_call.assert_called_once_with(["ls", "-la"], cwd=cwd)

    def test_run_checked_subprocess_error_propagates(self) -> None:
        """Test that subprocess errors propagate correctly."""
        with patch("subprocess.check_call") as mock_check_call:
            mock_check_call.side_effect = subprocess.CalledProcessError(1, "test")
            with pytest.raises(subprocess.CalledProcessError):
                run_checked(["failing_command"])


class TestFilterFilesWithConfig:
    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_config_file_not_found(
        self,
        mock_load_yaml_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test when config file is not found."""
        mock_load_yaml_config.side_effect = FileNotFoundError("Config not found")

        files, error = filter_files_with_config(["test.py"], Path("/fake/config.yaml"), "mypy")

        assert files == []
        assert error is not None
        assert error.success is False
        assert error.message == "Config file not found"
        captured = capsys.readouterr()
        assert "Mypy config file not found" in captured.out

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_config_yaml_parse_error(
        self,
        mock_load_yaml_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test when config file has YAML parse errors."""
        mock_load_yaml_config.side_effect = yaml.YAMLError("invalid YAML syntax")

        files, error = filter_files_with_config(["test.py"], Path("/fake/config.yaml"), "ruff")

        assert files == []
        assert error is not None
        assert error.success is False
        assert "Config parse error" in (error.message or "")
        captured = capsys.readouterr()
        assert "Failed to parse ruff config" in captured.out
        assert "invalid YAML syntax" in captured.out

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_config_permission_error(
        self,
        mock_load_yaml_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test when config file has permission issues."""
        mock_load_yaml_config.side_effect = PermissionError("Permission denied")

        files, error = filter_files_with_config(["test.py"], Path("/fake/config.yaml"), "mypy")

        assert files == []
        assert error is not None
        assert error.success is False
        assert "Config permission error" in (error.message or "")
        captured = capsys.readouterr()
        assert "Permission denied reading mypy config" in captured.out

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_unexpected_exception_propagates(
        self,
        mock_load_yaml_config: MagicMock,
    ) -> None:
        """Test that unexpected exceptions propagate instead of being swallowed."""
        mock_load_yaml_config.side_effect = RuntimeError("Unexpected error")

        with pytest.raises(RuntimeError, match="Unexpected error"):
            filter_files_with_config(["test.py"], Path("/fake/config.yaml"), "ruff")

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_included_paths_invalid_type(
        self,
        mock_load_yaml_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test when included_paths is not a list."""
        mock_load_yaml_config.return_value = {"included_paths": "not-a-list"}

        files, error = filter_files_with_config(["test.py"], Path("/fake/config.yaml"), "mypy")

        assert files == []
        assert error is not None
        assert error.success is False
        assert error.message == "Invalid included_paths config"
        captured = capsys.readouterr()
        assert "Invalid included_paths in mypy config" in captured.out
        assert "expected list" in captured.out

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_no_included_paths_returns_all_files(
        self,
        mock_load_yaml_config: MagicMock,
    ) -> None:
        """Test when config has no included_paths - all files returned."""
        mock_load_yaml_config.return_value = {}

        files, error = filter_files_with_config(
            ["app/main.py", "tests/test_main.py"], Path("/fake/config.yaml"), "mypy"
        )

        assert files == ["app/main.py", "tests/test_main.py"]
        assert error is None

    @patch("scripts.dev.linter.base.load_yaml_config")
    @patch("scripts.dev.linter.base.is_path_included")
    def test_filters_files_by_included_paths(
        self,
        mock_is_included: MagicMock,
        mock_load_yaml_config: MagicMock,
    ) -> None:
        """Test filtering files with included_paths patterns."""
        mock_load_yaml_config.return_value = {"included_paths": ["app/**/*.py"]}
        mock_is_included.side_effect = lambda path, patterns: path.startswith("app/")

        files, error = filter_files_with_config(
            ["app/main.py", "tests/test_main.py", "app/utils.py"],
            Path("/fake/config.yaml"),
            "mypy",
        )

        assert files == ["app/main.py", "app/utils.py"]
        assert error is None

    @patch("scripts.dev.linter.base.load_yaml_config")
    @patch("scripts.dev.linter.base.is_path_included")
    def test_all_files_filtered_returns_empty_list(
        self,
        mock_is_included: MagicMock,
        mock_load_yaml_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test when all files are filtered out."""
        mock_load_yaml_config.return_value = {"included_paths": ["app/**/*.py"]}
        mock_is_included.return_value = False

        files, error = filter_files_with_config(
            ["tests/test_main.py", "tests/test_utils.py"],
            Path("/fake/config.yaml"),
            "mypy",
        )

        assert files == []
        assert error is None
        captured = capsys.readouterr()
        assert "No Python files match mypy included_paths filter" in captured.out

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_empty_included_paths_list_returns_all_files(
        self,
        mock_load_yaml_config: MagicMock,
    ) -> None:
        """Test when included_paths is empty list - all files returned."""
        mock_load_yaml_config.return_value = {"included_paths": []}

        files, error = filter_files_with_config(
            ["app/main.py", "tests/test_main.py"], Path("/fake/config.yaml"), "ruff"
        )

        assert files == ["app/main.py", "tests/test_main.py"]
        assert error is None


class TestCalculateFileset:
    """Tests for the calculate_fileset function."""

    def test_returns_none_when_files_is_none(self) -> None:
        """Test that calculate_fileset returns None for whole-repo scan."""
        from scripts.dev.linter.linters.ruff import RuffLinter

        linter = RuffLinter()
        result = calculate_fileset(linter, None)
        assert result is None

    @patch("scripts.dev.linter.base.filter_files_with_config")
    def test_ruff_filters_by_py_extension(self, mock_filter: MagicMock) -> None:
        """Test ruff linter filters for .py files."""
        from scripts.dev.linter.linters.ruff import RuffLinter

        mock_filter.return_value = (["app/main.py"], None)
        linter = RuffLinter()
        files = ["app/main.py", "README.md", "Dockerfile"]

        result = calculate_fileset(linter, files)

        assert result == {"app/main.py"}
        # Verify only .py files were passed to filter_files_with_config
        call_args = mock_filter.call_args[0]
        assert call_args[0] == ["app/main.py"]

    @patch("scripts.dev.linter.base.filter_files_with_config")
    def test_ruff_returns_empty_set_when_no_py_files(self, mock_filter: MagicMock) -> None:
        """Test ruff returns empty set when no Python files in input."""
        from scripts.dev.linter.linters.ruff import RuffLinter

        linter = RuffLinter()
        files = ["README.md", "Dockerfile", "config.yaml"]

        result = calculate_fileset(linter, files)

        assert result == set()
        mock_filter.assert_not_called()

    @patch("scripts.dev.linter.base.filter_files_with_config")
    def test_ruff_returns_py_files_on_config_error(self, mock_filter: MagicMock) -> None:
        """Test ruff returns all py files when config loading fails.

        This ensures the linter runs and surfaces the config error.
        """
        from scripts.dev.linter.linters.ruff import RuffLinter

        mock_filter.return_value = ([], LinterResult(success=False, message="Config error"))
        linter = RuffLinter()
        files = ["app/main.py"]

        result = calculate_fileset(linter, files)

        assert result == {"app/main.py"}

    @patch("scripts.dev.linter.base.filter_files_with_config")
    def test_mypy_filters_by_py_extension(self, mock_filter: MagicMock) -> None:
        """Test mypy linter filters for .py files."""
        from scripts.dev.linter.linters.mypy import MypyLinter

        mock_filter.return_value = (["app/utils.py", "app/main.py"], None)
        linter = MypyLinter()
        files = ["app/utils.py", "app/main.py", "tests/conftest.py", "README.md"]

        result = calculate_fileset(linter, files)

        assert result == {"app/utils.py", "app/main.py"}

    @patch("scripts.dev.linter.base.load_yaml_config")
    @patch("scripts.dev.linter.base.is_path_included")
    def test_astgrep_filters_py_and_pyi_files(
        self, mock_is_included: MagicMock, mock_load_config: MagicMock
    ) -> None:
        """Test astgrep filters for .py and .pyi files."""
        from scripts.dev.linter.linters.astgrep import AstgrepLinter

        mock_load_config.return_value = {"included_paths": ["app/**/*.py"]}
        mock_is_included.return_value = True
        linter = AstgrepLinter()
        files = ["app/main.py", "app/types.pyi", "README.md", "config.yaml"]

        result = calculate_fileset(linter, files)

        assert result == {"app/main.py", "app/types.pyi"}

    @patch("scripts.dev.linter.base.load_yaml_config")
    @patch("scripts.dev.linter.base.is_path_included")
    def test_shellcheck_filters_sh_files(
        self, mock_is_included: MagicMock, mock_load_config: MagicMock
    ) -> None:
        """Test shellcheck filters for .sh files."""
        from scripts.dev.linter.linters.shellcheck import ShellcheckLinter

        mock_load_config.return_value = {"included_paths": ["scripts/**/*.sh"]}
        mock_is_included.return_value = True
        linter = ShellcheckLinter()
        files = ["scripts/build.sh", "scripts/test.sh", "README.md"]

        result = calculate_fileset(linter, files)

        assert result == {"scripts/build.sh", "scripts/test.sh"}

    @patch("scripts.dev.linter.base.load_yaml_config")
    @patch("scripts.dev.linter.base.is_path_included")
    def test_yamllint_filters_yaml_files(
        self, mock_is_included: MagicMock, mock_load_config: MagicMock
    ) -> None:
        """Test yamllint filters for .yaml and .yml files."""
        from scripts.dev.linter.linters.yamllint import YamllintLinter

        mock_load_config.return_value = {"included_paths": ["**/*.yaml", "**/*.yml"]}
        mock_is_included.return_value = True
        linter = YamllintLinter()
        files = ["config.yaml", ".github/workflows/ci.yml", "README.md"]

        result = calculate_fileset(linter, files)

        assert result == {"config.yaml", ".github/workflows/ci.yml"}

    @patch("scripts.dev.linter.base.load_yaml_config")
    @patch("scripts.dev.linter.base.is_path_included")
    def test_hadolint_filters_dockerfile_by_name(
        self, mock_is_included: MagicMock, mock_load_config: MagicMock
    ) -> None:
        """Test hadolint filters for files named Dockerfile."""
        from scripts.dev.linter.linters.hadolint import HadolintLinter

        mock_load_config.return_value = {"included_paths": ["**/Dockerfile"]}
        mock_is_included.return_value = True
        linter = HadolintLinter()
        files = ["Dockerfile", "docker/Dockerfile", "Dockerfile.bak", "README.md"]

        result = calculate_fileset(linter, files)

        # Only exact Dockerfile matches, not Dockerfile.bak
        assert result == {"Dockerfile", "docker/Dockerfile"}

    @patch("scripts.dev.linter.base.load_yaml_config")
    @patch("scripts.dev.linter.base.is_path_included")
    def test_pymarkdown_filters_md_files(
        self, mock_is_included: MagicMock, mock_load_config: MagicMock
    ) -> None:
        """Test pymarkdown filters for .md files."""
        from scripts.dev.linter.linters.pymarkdown import PymarkdownLinter

        mock_load_config.return_value = {"included_paths": ["**/*.md"]}
        mock_is_included.return_value = True
        linter = PymarkdownLinter()
        files = ["README.md", "docs/guide.md", "main.py"]

        result = calculate_fileset(linter, files)

        assert result == {"README.md", "docs/guide.md"}

    @patch("scripts.dev.linter.base.load_yaml_config")
    @patch("scripts.dev.linter.base.is_path_included")
    def test_actionlint_filters_workflow_yaml_files(
        self, mock_is_included: MagicMock, mock_load_config: MagicMock
    ) -> None:
        """Test actionlint filters for .yml/.yaml workflow files."""
        from scripts.dev.linter.linters.actionlint import ActionlintLinter

        mock_load_config.return_value = {
            "included_paths": [".github/workflows/**/*.yml", ".github/workflows/**/*.yaml"]
        }
        mock_is_included.return_value = True
        linter = ActionlintLinter()
        files = [".github/workflows/ci.yml", ".github/workflows/deploy.yaml", "config.yml"]

        result = calculate_fileset(linter, files)

        assert result == {".github/workflows/ci.yml", ".github/workflows/deploy.yaml", "config.yml"}

    @patch("scripts.dev.linter.base.load_yaml_config")
    @patch("scripts.dev.linter.base.is_path_included")
    def test_dotenvlint_filters_env_files(
        self, mock_is_included: MagicMock, mock_load_config: MagicMock
    ) -> None:
        """Test dotenvlint filters for .env* files."""
        from scripts.dev.linter.linters.dotenvlint import DotenvlintLinter

        mock_load_config.return_value = {"included_paths": ["**/.env*"]}
        mock_is_included.return_value = True
        linter = DotenvlintLinter()
        files = [".env", ".env.local", ".env.production", "config.yaml"]

        result = calculate_fileset(linter, files)

        assert result == {".env", ".env.local", ".env.production"}

    @patch("scripts.dev.linter.base.load_yaml_config")
    @patch("scripts.dev.linter.base.is_path_included")
    def test_detect_secrets_applies_exclusions(
        self, mock_is_included: MagicMock, mock_load_config: MagicMock
    ) -> None:
        """Test detect-secrets applies exclusion patterns."""
        from scripts.dev.linter.linters.detect_secrets import DetectSecretsLinter

        mock_load_config.return_value = {
            "included_paths": [],
            "excluded_extensions": [".pyc", ".log"],
            "excluded_names": ["uv.lock"],
        }
        mock_is_included.return_value = True
        linter = DetectSecretsLinter()
        files = ["app/main.py", "cache/test.pyc", "debug.log", "uv.lock", "README.md"]

        result = calculate_fileset(linter, files)

        assert result == {"app/main.py", "README.md"}

    @patch("scripts.dev.linter.base.load_yaml_config")
    @patch("scripts.dev.linter.base.is_path_included")
    def test_gitleaks_applies_exclusions(
        self, mock_is_included: MagicMock, mock_load_config: MagicMock
    ) -> None:
        """Test gitleaks applies exclusion patterns."""
        from scripts.dev.linter.linters.gitleaks import GitleaksLinter

        mock_load_config.return_value = {
            "included_paths": [],
            "excluded_extensions": [".bin"],
            "excluded_names": [".gitignore"],
        }
        mock_is_included.return_value = True
        linter = GitleaksLinter()
        files = ["app/main.py", "data.bin", ".gitignore", "README.md"]

        result = calculate_fileset(linter, files)

        assert result == {"app/main.py", "README.md"}

    def test_scripts_linter_only_matches_pyproject_toml(self) -> None:
        """Test scripts linter only matches pyproject.toml files."""
        from scripts.dev.linter.linters.scripts import ScriptsLinter

        linter = ScriptsLinter()
        files = ["pyproject.toml", "app/main.py", "README.md", "package.json"]

        result = calculate_fileset(linter, files)

        assert result == {"pyproject.toml"}

    def test_scripts_linter_returns_empty_when_no_pyproject(self) -> None:
        """Test scripts linter returns empty set when no pyproject.toml."""
        from scripts.dev.linter.linters.scripts import ScriptsLinter

        linter = ScriptsLinter()
        files = ["app/main.py", "README.md", "package.json"]

        result = calculate_fileset(linter, files)

        assert result == set()

    def test_trivy_matches_uv_lock_and_dockerfile(self) -> None:
        """Test trivy matches uv.lock and Dockerfile files."""
        from scripts.dev.linter.linters.trivy import TrivyLinter

        linter = TrivyLinter()
        files = ["uv.lock", "Dockerfile", "docker/Dockerfile", "app/main.py"]

        result = calculate_fileset(linter, files)

        assert result == {"uv.lock", "Dockerfile", "docker/Dockerfile"}

    def test_trivy_returns_empty_when_no_relevant_files(self) -> None:
        """Test trivy returns empty set when no uv.lock or Dockerfile."""
        from scripts.dev.linter.linters.trivy import TrivyLinter

        linter = TrivyLinter()
        files = ["app/main.py", "README.md", "requirements.txt"]

        result = calculate_fileset(linter, files)

        assert result == set()

    def test_checkov_matches_openapi_json(self) -> None:
        """Test checkov matches openapi.json files."""
        from scripts.dev.linter.linters.checkov import CheckovLinter

        linter = CheckovLinter()
        files = ["openapi/openapi.json", "api/openapi.json", "config.json", "app/main.py"]

        result = calculate_fileset(linter, files)

        assert result == {"openapi/openapi.json", "api/openapi.json"}

    def test_checkov_returns_empty_when_no_openapi(self) -> None:
        """Test checkov returns empty set when no openapi.json files."""
        from scripts.dev.linter.linters.checkov import CheckovLinter

        linter = CheckovLinter()
        files = ["app/main.py", "config.json", "README.md"]

        result = calculate_fileset(linter, files)

        assert result == set()

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_handles_yaml_error_returns_type_files(self, mock_load_config: MagicMock) -> None:
        """Test that config errors return type-appropriate files.

        This ensures the linter runs and surfaces the config error.
        """
        from scripts.dev.linter.linters.yamllint import YamllintLinter

        mock_load_config.side_effect = yaml.YAMLError("parse error")
        linter = YamllintLinter()
        files = ["config.yaml"]

        result = calculate_fileset(linter, files)

        assert result == {"config.yaml"}

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_handles_os_error_returns_type_files(self, mock_load_config: MagicMock) -> None:
        """Test that OS errors return type-appropriate files.

        This ensures the linter runs and surfaces the config error.
        """
        from scripts.dev.linter.linters.hadolint import HadolintLinter

        mock_load_config.side_effect = FileNotFoundError("config not found")
        linter = HadolintLinter()
        files = ["Dockerfile"]

        result = calculate_fileset(linter, files)

        assert result == {"Dockerfile"}

    def test_unknown_linter_returns_all_files(self) -> None:
        """Test that unknown linter returns all input files."""
        from scripts.dev.linter.base import BaseLinter

        class UnknownLinter(BaseLinter):
            name = "unknown-test-linter"

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=True)

        linter = UnknownLinter()
        files = ["a.py", "b.txt", "c.md"]

        result = calculate_fileset(linter, files)

        assert result == {"a.py", "b.txt", "c.md"}


class TestScheduleLinters:
    """Tests for the schedule_linters function."""

    def _create_mock_linter(self, name: str, mutates_files: bool = False) -> BaseLinter:
        """Create a mock linter for testing."""

        class MockLinter(BaseLinter):
            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=True)

        linter = MockLinter()
        linter.name = name
        linter.mutates_files = mutates_files
        return linter

    @patch("scripts.dev.linter.base.calculate_fileset")
    def test_whole_repo_scan_with_one_mutating_linter(self, mock_calculate: MagicMock) -> None:
        """Test scheduling with whole-repo scan and one mutating linter."""
        # Create linters: one mutating, two read-only
        mutating = self._create_mock_linter("ruff", mutates_files=True)
        read_only1 = self._create_mock_linter("mypy")
        read_only2 = self._create_mock_linter("astgrep")

        # Whole-repo scan returns None for all linters
        mock_calculate.return_value = None

        phases = schedule_linters([mutating, read_only1, read_only2], None)

        assert len(phases) == 2
        assert phases[0] == ["ruff"]
        assert phases[1] == ["mypy", "astgrep"]

    @patch("scripts.dev.linter.base.calculate_fileset")
    def test_filtered_scan_skips_empty_filesets(self, mock_calculate: MagicMock) -> None:
        """Test that linters with empty filesets are skipped."""
        mutating = self._create_mock_linter("ruff", mutates_files=True)
        read_only1 = self._create_mock_linter("mypy")
        read_only2 = self._create_mock_linter("hadolint")

        # ruff and mypy have files, hadolint has empty fileset
        def fileset_side_effect(linter: BaseLinter, files: list[str] | None) -> set[str]:
            if linter.name == "hadolint":
                return set()
            return {"app/main.py"}

        mock_calculate.side_effect = fileset_side_effect

        phases = schedule_linters(
            [mutating, read_only1, read_only2],
            ["app/main.py", "tests/test_main.py"],
        )

        assert len(phases) == 2
        assert phases[0] == ["ruff"]
        assert phases[1] == ["mypy"]
        # hadolint should be skipped due to empty fileset

    @patch("scripts.dev.linter.base.calculate_fileset")
    def test_no_mutating_linters_returns_single_phase(self, mock_calculate: MagicMock) -> None:
        """Test scheduling when no mutating linters have files."""
        mutating = self._create_mock_linter("ruff", mutates_files=True)
        read_only1 = self._create_mock_linter("hadolint")
        read_only2 = self._create_mock_linter("pymarkdown")

        # mutating linter has no files, read-only linters have files
        def fileset_side_effect(linter: BaseLinter, files: list[str] | None) -> set[str]:
            if linter.name == "ruff":
                return set()
            return {"README.md", "Dockerfile"}

        mock_calculate.side_effect = fileset_side_effect

        phases = schedule_linters(
            [mutating, read_only1, read_only2],
            ["README.md", "Dockerfile"],
        )

        # Only one phase with read-only linters
        assert len(phases) == 1
        assert phases[0] == ["hadolint", "pymarkdown"]

    @patch("scripts.dev.linter.base.calculate_fileset")
    def test_all_linters_empty_filesets_returns_empty_list(self, mock_calculate: MagicMock) -> None:
        """Test that empty phases list is returned when all linters have empty filesets."""
        linter1 = self._create_mock_linter("linter1")
        linter2 = self._create_mock_linter("linter2")

        mock_calculate.return_value = set()

        phases = schedule_linters([linter1, linter2], ["nonexistent.xyz"])

        assert phases == []

    @patch("scripts.dev.linter.base.calculate_fileset")
    def test_multiple_mutating_linters_run_sequentially(self, mock_calculate: MagicMock) -> None:
        """Test that multiple mutating linters each get their own phase."""
        mutating1 = self._create_mock_linter("mutating1", mutates_files=True)
        mutating2 = self._create_mock_linter("mutating2", mutates_files=True)
        read_only1 = self._create_mock_linter("read_only1")
        read_only2 = self._create_mock_linter("read_only2")

        mock_calculate.return_value = None

        phases = schedule_linters([mutating1, mutating2, read_only1, read_only2], None)

        assert len(phases) == 3
        assert phases[0] == ["mutating1"]
        assert phases[1] == ["mutating2"]
        assert phases[2] == ["read_only1", "read_only2"]

    @patch("scripts.dev.linter.base.calculate_fileset")
    def test_preserves_linter_order(self, mock_calculate: MagicMock) -> None:
        """Test that read-only linters preserve input order."""
        linters = [
            self._create_mock_linter("zebra"),
            self._create_mock_linter("alpha"),
            self._create_mock_linter("beta"),
        ]

        mock_calculate.return_value = None

        phases = schedule_linters(linters, None)

        assert len(phases) == 1
        assert phases[0] == ["zebra", "alpha", "beta"]

    @patch("scripts.dev.linter.base.calculate_fileset")
    def test_none_fileset_includes_linter(self, mock_calculate: MagicMock) -> None:
        """Test that linters with None fileset (whole-repo) are included."""
        linter1 = self._create_mock_linter("linter1")
        linter2 = self._create_mock_linter("linter2")

        # First linter returns None (whole-repo), second returns empty set
        def fileset_side_effect(linter: BaseLinter, files: list[str] | None) -> set[str] | None:
            if linter.name == "linter1":
                return None
            return set()

        mock_calculate.side_effect = fileset_side_effect

        phases = schedule_linters([linter1, linter2], None)

        # Only linter1 should be included
        assert len(phases) == 1
        assert phases[0] == ["linter1"]

    @patch("scripts.dev.linter.base.calculate_fileset")
    def test_only_mutating_linters_no_read_only_phase(self, mock_calculate: MagicMock) -> None:
        """Test scheduling when only mutating linters have files."""
        mutating1 = self._create_mock_linter("mutating1", mutates_files=True)
        mutating2 = self._create_mock_linter("mutating2", mutates_files=True)

        mock_calculate.return_value = {"file.py"}

        phases = schedule_linters([mutating1, mutating2], ["file.py"])

        assert len(phases) == 2
        assert phases[0] == ["mutating1"]
        assert phases[1] == ["mutating2"]

    @patch("scripts.dev.linter.base.calculate_fileset")
    def test_empty_linters_list_returns_empty_phases(self, mock_calculate: MagicMock) -> None:
        """Test that empty linters list returns empty phases."""
        phases = schedule_linters([], None)

        assert phases == []
        mock_calculate.assert_not_called()


class TestRunLinterSafe:
    """Tests for the _run_linter_safe helper function."""

    def test_successful_run_with_file_filtering(self) -> None:
        """Test successful run when linter supports file filtering."""
        mock_linter = MagicMock()
        mock_linter.supports_file_filtering = True
        mock_linter.run.return_value = LinterResult(success=True, message="OK")

        result = _run_linter_safe(mock_linter, ["file.py"])

        assert result.success is True
        assert result.message == "OK"
        mock_linter.run.assert_called_once_with(["file.py"])

    def test_successful_run_without_file_filtering(self) -> None:
        """Test successful run when linter does not support file filtering."""
        mock_linter = MagicMock()
        mock_linter.supports_file_filtering = False
        mock_linter.run.return_value = LinterResult(success=True)

        result = _run_linter_safe(mock_linter, ["file.py"])

        assert result.success is True
        mock_linter.run.assert_called_once_with()

    def test_catches_called_process_error(self) -> None:
        """Test CalledProcessError is caught and converted to LinterResult."""
        mock_linter = MagicMock()
        mock_linter.supports_file_filtering = True
        mock_linter.run.side_effect = subprocess.CalledProcessError(1, "cmd")

        result = _run_linter_safe(mock_linter, None)

        assert result.success is False
        assert "Process error" in (result.message or "")

    def test_catches_runtime_error(self) -> None:
        """Test RuntimeError is caught and converted to LinterResult."""
        mock_linter = MagicMock()
        mock_linter.supports_file_filtering = True
        mock_linter.run.side_effect = RuntimeError("tool not found")

        result = _run_linter_safe(mock_linter, None)

        assert result.success is False
        assert result.message == "tool not found"

    def test_catches_os_error(self) -> None:
        """Test OSError is caught and converted to LinterResult."""
        mock_linter = MagicMock()
        mock_linter.supports_file_filtering = True
        mock_linter.run.side_effect = OSError("permission denied")

        result = _run_linter_safe(mock_linter, None)

        assert result.success is False
        assert "OS error" in (result.message or "")

    def test_catches_yaml_error(self) -> None:
        """Test yaml.YAMLError is caught and converted to LinterResult."""
        mock_linter = MagicMock()
        mock_linter.supports_file_filtering = True
        mock_linter.run.side_effect = yaml.YAMLError("invalid yaml")

        result = _run_linter_safe(mock_linter, None)

        assert result.success is False
        assert "YAML error" in (result.message or "")

    def test_catches_unexpected_exception(self) -> None:
        """Test unexpected exceptions are caught and converted to LinterResult."""
        mock_linter = MagicMock()
        mock_linter.supports_file_filtering = True
        mock_linter.run.side_effect = ValueError("unexpected")

        result = _run_linter_safe(mock_linter, None)

        assert result.success is False
        assert "Unexpected error" in (result.message or "")


class TestExecutePhase:
    """Tests for the execute_phase function."""

    def test_empty_phase_returns_empty_dict(self) -> None:
        """Test empty phase returns empty dictionary."""
        result = execute_phase([])

        assert result == {}

    @patch("scripts.dev.linter.linters.LINTER_MAP", new_callable=dict)
    def test_single_linter_executes_sequentially(
        self, mock_linter_map: dict[str, BaseLinter]
    ) -> None:
        """Test single linter executes sequentially."""
        mock_linter = MagicMock()
        mock_linter.name = "test-linter"
        mock_linter.supports_file_filtering = True
        mock_linter.run.return_value = LinterResult(success=True)
        mock_linter_map["test-linter"] = mock_linter

        results = execute_phase(["test-linter"], None)

        assert len(results) == 1
        assert results["test-linter"].success is True
        mock_linter.run.assert_called_once_with(None)

    @patch("scripts.dev.linter.linters.LINTER_MAP", new_callable=dict)
    def test_multiple_linters_execute_in_parallel(
        self, mock_linter_map: dict[str, BaseLinter]
    ) -> None:
        """Test multiple linters execute in parallel and return all results."""
        mock_linter1 = MagicMock()
        mock_linter1.name = "linter1"
        mock_linter1.supports_file_filtering = True
        mock_linter1.run.return_value = LinterResult(success=True, message="linter1 OK")

        mock_linter2 = MagicMock()
        mock_linter2.name = "linter2"
        mock_linter2.supports_file_filtering = True
        mock_linter2.run.return_value = LinterResult(success=True, message="linter2 OK")

        mock_linter3 = MagicMock()
        mock_linter3.name = "linter3"
        mock_linter3.supports_file_filtering = True
        mock_linter3.run.return_value = LinterResult(success=False, message="linter3 failed")

        mock_linter_map["linter1"] = mock_linter1
        mock_linter_map["linter2"] = mock_linter2
        mock_linter_map["linter3"] = mock_linter3

        results = execute_phase(["linter1", "linter2", "linter3"], None)

        assert len(results) == 3
        assert results["linter1"].success is True
        assert results["linter2"].success is True
        assert results["linter3"].success is False
        assert results["linter3"].message == "linter3 failed"

    @patch("scripts.dev.linter.linters.LINTER_MAP", new_callable=dict)
    def test_unknown_linter_returns_error_result(
        self, mock_linter_map: dict[str, BaseLinter]
    ) -> None:
        """Test unknown linter name returns error result."""
        results = execute_phase(["nonexistent-linter"], None)

        assert len(results) == 1
        assert results["nonexistent-linter"].success is False
        assert "Unknown linter" in (results["nonexistent-linter"].message or "")

    @patch("scripts.dev.linter.linters.LINTER_MAP", new_callable=dict)
    def test_linter_exception_returns_error_result(
        self, mock_linter_map: dict[str, BaseLinter]
    ) -> None:
        """Test linter exception is caught and returned as error result."""
        mock_linter = MagicMock()
        mock_linter.name = "error-linter"
        mock_linter.supports_file_filtering = True
        mock_linter.run.side_effect = RuntimeError("test error")
        mock_linter_map["error-linter"] = mock_linter

        results = execute_phase(["error-linter"], None)

        assert len(results) == 1
        assert results["error-linter"].success is False
        assert "test error" in (results["error-linter"].message or "")

    @patch("scripts.dev.linter.linters.LINTER_MAP", new_callable=dict)
    def test_subprocess_error_handled_gracefully(
        self, mock_linter_map: dict[str, BaseLinter]
    ) -> None:
        """Test CalledProcessError is handled gracefully."""
        mock_linter = MagicMock()
        mock_linter.name = "process-error-linter"
        mock_linter.supports_file_filtering = True
        mock_linter.run.side_effect = subprocess.CalledProcessError(1, "failing-cmd")
        mock_linter_map["process-error-linter"] = mock_linter

        results = execute_phase(["process-error-linter"], None)

        assert len(results) == 1
        assert results["process-error-linter"].success is False
        assert "Process error" in (results["process-error-linter"].message or "")

    @patch("scripts.dev.linter.linters.LINTER_MAP", new_callable=dict)
    def test_os_error_handled_gracefully(self, mock_linter_map: dict[str, BaseLinter]) -> None:
        """Test OSError is handled gracefully."""
        mock_linter = MagicMock()
        mock_linter.name = "os-error-linter"
        mock_linter.supports_file_filtering = True
        mock_linter.run.side_effect = OSError("permission denied")
        mock_linter_map["os-error-linter"] = mock_linter

        results = execute_phase(["os-error-linter"], None)

        assert len(results) == 1
        assert results["os-error-linter"].success is False
        assert "OS error" in (results["os-error-linter"].message or "")

    @patch("scripts.dev.linter.linters.LINTER_MAP", new_callable=dict)
    def test_yaml_error_handled_gracefully(self, mock_linter_map: dict[str, BaseLinter]) -> None:
        """Test yaml.YAMLError is handled gracefully."""
        mock_linter = MagicMock()
        mock_linter.name = "yaml-error-linter"
        mock_linter.supports_file_filtering = True
        mock_linter.run.side_effect = yaml.YAMLError("invalid config")
        mock_linter_map["yaml-error-linter"] = mock_linter

        results = execute_phase(["yaml-error-linter"], None)

        assert len(results) == 1
        assert results["yaml-error-linter"].success is False
        assert "YAML error" in (results["yaml-error-linter"].message or "")

    @patch("scripts.dev.linter.linters.LINTER_MAP", new_callable=dict)
    def test_file_filtering_respected(self, mock_linter_map: dict[str, BaseLinter]) -> None:
        """Test files are passed to linter when supports_file_filtering is True."""
        mock_linter = MagicMock()
        mock_linter.name = "filter-linter"
        mock_linter.supports_file_filtering = True
        mock_linter.run.return_value = LinterResult(success=True)
        mock_linter_map["filter-linter"] = mock_linter

        results = execute_phase(["filter-linter"], ["file1.py", "file2.py"])

        assert results["filter-linter"].success is True
        mock_linter.run.assert_called_once_with(["file1.py", "file2.py"])

    @patch("scripts.dev.linter.linters.LINTER_MAP", new_callable=dict)
    def test_no_file_filtering_ignores_files(self, mock_linter_map: dict[str, BaseLinter]) -> None:
        """Test files are not passed when supports_file_filtering is False."""
        mock_linter = MagicMock()
        mock_linter.name = "no-filter-linter"
        mock_linter.supports_file_filtering = False
        mock_linter.run.return_value = LinterResult(success=True)
        mock_linter_map["no-filter-linter"] = mock_linter

        results = execute_phase(["no-filter-linter"], ["file1.py", "file2.py"])

        assert results["no-filter-linter"].success is True
        mock_linter.run.assert_called_once_with()

    @patch("scripts.dev.linter.linters.LINTER_MAP", new_callable=dict)
    def test_parallel_execution_all_succeed(self, mock_linter_map: dict[str, BaseLinter]) -> None:
        """Test parallel execution with all linters succeeding."""
        for i in range(3):
            mock_linter = MagicMock()
            mock_linter.name = f"success-linter-{i}"
            mock_linter.supports_file_filtering = True
            mock_linter.run.return_value = LinterResult(success=True, message=f"OK-{i}")
            mock_linter_map[f"success-linter-{i}"] = mock_linter

        results = execute_phase(["success-linter-0", "success-linter-1", "success-linter-2"], None)

        assert len(results) == 3
        assert all(r.success for r in results.values())

    @patch("scripts.dev.linter.linters.LINTER_MAP", new_callable=dict)
    def test_parallel_execution_some_fail(self, mock_linter_map: dict[str, BaseLinter]) -> None:
        """Test parallel execution with some linters failing."""
        mock_success = MagicMock()
        mock_success.name = "success"
        mock_success.supports_file_filtering = True
        mock_success.run.return_value = LinterResult(success=True)
        mock_linter_map["success"] = mock_success

        mock_fail = MagicMock()
        mock_fail.name = "fail"
        mock_fail.supports_file_filtering = True
        mock_fail.run.return_value = LinterResult(success=False, message="failed")
        mock_linter_map["fail"] = mock_fail

        mock_error = MagicMock()
        mock_error.name = "error"
        mock_error.supports_file_filtering = True
        mock_error.run.side_effect = RuntimeError("crashed")
        mock_linter_map["error"] = mock_error

        results = execute_phase(["success", "fail", "error"], None)

        assert len(results) == 3
        assert results["success"].success is True
        assert results["fail"].success is False
        assert results["fail"].message == "failed"
        assert results["error"].success is False
        assert "crashed" in (results["error"].message or "")

    @patch("scripts.dev.linter.linters.LINTER_MAP", new_callable=dict)
    def test_parallel_execution_preserves_linter_names(
        self, mock_linter_map: dict[str, BaseLinter]
    ) -> None:
        """Test that result dict keys match input linter names."""
        linter_names = ["alpha-linter", "beta-linter", "gamma-linter"]

        for name in linter_names:
            mock_linter = MagicMock()
            mock_linter.name = name
            mock_linter.supports_file_filtering = True
            mock_linter.run.return_value = LinterResult(success=True)
            mock_linter_map[name] = mock_linter

        results = execute_phase(linter_names, None)

        assert set(results.keys()) == set(linter_names)

    @patch("scripts.dev.linter.linters.LINTER_MAP", new_callable=dict)
    def test_parallel_unknown_linter_mixed_with_valid(
        self, mock_linter_map: dict[str, BaseLinter]
    ) -> None:
        """Test parallel execution with mix of valid and unknown linters."""
        mock_valid = MagicMock()
        mock_valid.name = "valid-linter"
        mock_valid.supports_file_filtering = True
        mock_valid.run.return_value = LinterResult(success=True)
        mock_linter_map["valid-linter"] = mock_valid

        results = execute_phase(["valid-linter", "unknown-linter"], None)

        assert len(results) == 2
        assert results["valid-linter"].success is True
        assert results["unknown-linter"].success is False
        assert "Unknown linter" in (results["unknown-linter"].message or "")
