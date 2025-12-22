"""Tests for linter configuration patterns.

This module tests that the include/exclude configuration behaviors for each linter
work correctly. It validates that configuration patterns are properly applied.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.linter.base import is_path_excluded
from scripts.dev.linter.linters.actionlint import ActionlintLinter
from scripts.dev.linter.linters.detect_secrets import DetectSecretsLinter
from scripts.dev.linter.linters.dotenvlint import DotenvlintLinter
from scripts.dev.linter.linters.gitleaks import GitleaksLinter
from scripts.dev.linter.linters.yamllint import YamllintLinter

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


# --- Test Fixtures ---


@pytest.fixture
def fake_repo(fs: FakeFilesystem) -> Path:
    """Create a fake repository root for testing."""
    repo_root = Path("/fake/repo")
    fs.create_dir(str(repo_root))
    return repo_root


# --- is_path_excluded Tests ---


class TestIsPathExcluded:
    """Tests for the is_path_excluded helper function."""

    def test_path_in_excluded_directory(self) -> None:
        """Should return True when path is under an excluded directory."""
        exclude_paths = {Path("/repo/.tmp"), Path("/repo/.worktrees")}
        path = Path("/repo/.tmp/test.yaml")
        assert is_path_excluded(path, exclude_paths) is True

    def test_path_not_in_excluded_directory(self) -> None:
        """Should return False when path is not under an excluded directory."""
        exclude_paths = {Path("/repo/.tmp"), Path("/repo/.worktrees")}
        path = Path("/repo/config.yaml")
        assert is_path_excluded(path, exclude_paths) is False

    def test_nested_excluded_path(self) -> None:
        """Should return True when path is deeply nested under excluded directory."""
        exclude_paths = {Path("/repo/.tmp")}
        path = Path("/repo/.tmp/deep/nested/file.yaml")
        assert is_path_excluded(path, exclude_paths) is True

    def test_path_equals_excluded_directory(self) -> None:
        """Should return True when path exactly equals an excluded directory."""
        exclude_paths = {Path("/repo/.tmp")}
        path = Path("/repo/.tmp")
        assert is_path_excluded(path, exclude_paths) is True


# --- YamllintLinter Tests ---


class TestRunYamllint:
    """Tests for YamllintLinter configuration patterns."""

    @pytest.fixture
    def yamllint_config(self, fake_repo: Path, fs: FakeFilesystem) -> Path:
        """Create yamllint configuration files."""
        lint_config = fake_repo / ".lint.yamllint.yaml"
        fs.create_file(
            str(lint_config),
            contents="exclude_dirs:\n  - .tmp\n  - .worktrees\n  - .github\n",
        )
        yamllint_config = fake_repo / ".yamllint.yaml"
        fs.create_file(str(yamllint_config), contents="")
        return lint_config

    def test_excludes_tmp_directory(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        yamllint_config: Path,
    ) -> None:
        """Should exclude files in .tmp directory."""
        # Create test files
        fs.create_file(str(fake_repo / "config.yml"), contents="key: value")
        fs.create_dir(str(fake_repo / ".tmp"))
        fs.create_file(str(fake_repo / ".tmp" / "excluded.yml"), contents="key: value")

        with (
            patch("scripts.dev.linter.linters.yamllint.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.yamllint.LINT_YAMLLINT_CONFIG", yamllint_config),
            patch(
                "scripts.dev.linter.linters.yamllint.get_executable",
                return_value="/usr/bin/uv",
            ),
            patch("scripts.dev.linter.linters.yamllint.run_checked") as mock_run_checked,
        ):
            linter = YamllintLinter()
            linter.run()

        # Verify run_checked was called
        assert mock_run_checked.called
        # Get the command that was passed
        cmd = mock_run_checked.call_args[0][0]
        # Assert .tmp/excluded.yml is NOT in the command
        assert not any(".tmp" in arg for arg in cmd), "Files in .tmp should be excluded"
        # Assert config.yml IS in the command
        assert any("config.yml" in arg for arg in cmd), "Root YAML files should be included"

    def test_excludes_worktrees_directory(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        yamllint_config: Path,
    ) -> None:
        """Should exclude files in .worktrees directory."""
        fs.create_file(str(fake_repo / "config.yml"), contents="key: value")
        fs.create_dir(str(fake_repo / ".worktrees" / "branch" / "config"))
        fs.create_file(
            str(fake_repo / ".worktrees" / "branch" / "config" / "test.yaml"),
            contents="key: value",
        )

        with (
            patch("scripts.dev.linter.linters.yamllint.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.yamllint.LINT_YAMLLINT_CONFIG", yamllint_config),
            patch(
                "scripts.dev.linter.linters.yamllint.get_executable",
                return_value="/usr/bin/uv",
            ),
            patch("scripts.dev.linter.linters.yamllint.run_checked") as mock_run_checked,
        ):
            linter = YamllintLinter()
            linter.run()

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        assert not any(".worktrees" in arg for arg in cmd), "Files in .worktrees should be excluded"

    def test_excludes_github_directory(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        yamllint_config: Path,
    ) -> None:
        """Should exclude files in .github directory (handled by actionlint)."""
        fs.create_file(str(fake_repo / "config.yml"), contents="key: value")
        fs.create_dir(str(fake_repo / ".github" / "workflows"))
        fs.create_file(
            str(fake_repo / ".github" / "workflows" / "ci.yml"),
            contents="name: CI",
        )

        with (
            patch("scripts.dev.linter.linters.yamllint.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.yamllint.LINT_YAMLLINT_CONFIG", yamllint_config),
            patch(
                "scripts.dev.linter.linters.yamllint.get_executable",
                return_value="/usr/bin/uv",
            ),
            patch("scripts.dev.linter.linters.yamllint.run_checked") as mock_run_checked,
        ):
            linter = YamllintLinter()
            linter.run()

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        assert not any(".github" in arg for arg in cmd), "Files in .github should be excluded"

    def test_includes_project_root_yaml(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        yamllint_config: Path,
    ) -> None:
        """Should include YAML files in project root."""
        # .yamllint.yaml is already created by the fixture
        fs.create_file(str(fake_repo / "config.yml"), contents="key: value")
        fs.create_file(str(fake_repo / "settings.yaml"), contents="setting: true")

        with (
            patch("scripts.dev.linter.linters.yamllint.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.yamllint.LINT_YAMLLINT_CONFIG", yamllint_config),
            patch(
                "scripts.dev.linter.linters.yamllint.get_executable",
                return_value="/usr/bin/uv",
            ),
            patch("scripts.dev.linter.linters.yamllint.run_checked") as mock_run_checked,
        ):
            linter = YamllintLinter()
            linter.run()

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        # Check that root yaml files are included
        yaml_files = [arg for arg in cmd if arg.endswith((".yml", ".yaml"))]
        assert len(yaml_files) > 0, "Root YAML files should be included"

    def test_files_parameter_filters_to_yaml_only(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        yamllint_config: Path,
    ) -> None:
        """Should only pass YAML files when files parameter is provided."""
        # Create test files
        fs.create_file(str(fake_repo / "config.yml"), contents="key: value")
        fs.create_file(str(fake_repo / "settings.yaml"), contents="setting: true")
        fs.create_file(str(fake_repo / "script.py"), contents="print('hello')")
        fs.create_file(str(fake_repo / "README.md"), contents="# Readme")

        with (
            patch("scripts.dev.linter.linters.yamllint.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.yamllint.LINT_YAMLLINT_CONFIG", yamllint_config),
            patch(
                "scripts.dev.linter.linters.yamllint.get_executable",
                return_value="/usr/bin/uv",
            ),
            patch("scripts.dev.linter.linters.yamllint.run_checked") as mock_run_checked,
        ):
            linter = YamllintLinter()
            # Pass a mix of YAML and non-YAML files
            linter.run(files=["config.yml", "settings.yaml", "script.py", "README.md"])

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        # Get files passed after the yamllint config flag
        config_index = cmd.index("-c")
        files_passed = cmd[config_index + 2 :]  # Skip -c and config path

        # Only YAML files should be passed
        assert "config.yml" in files_passed, "config.yml should be included"
        assert "settings.yaml" in files_passed, "settings.yaml should be included"
        assert "script.py" not in files_passed, "script.py should NOT be included"
        assert "README.md" not in files_passed, "README.md should NOT be included"
        assert len(files_passed) == 2, "Only 2 YAML files should be passed"

    def test_files_parameter_short_circuits_when_no_yaml_files(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        yamllint_config: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should not call run_checked when no YAML files in the files list."""
        # Create test files (non-YAML files only)
        fs.create_file(str(fake_repo / "script.py"), contents="print('hello')")
        fs.create_file(str(fake_repo / "README.md"), contents="# Readme")

        with (
            patch("scripts.dev.linter.linters.yamllint.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.yamllint.LINT_YAMLLINT_CONFIG", yamllint_config),
            patch(
                "scripts.dev.linter.linters.yamllint.get_executable",
                return_value="/usr/bin/uv",
            ),
            patch("scripts.dev.linter.linters.yamllint.run_checked") as mock_run_checked,
        ):
            linter = YamllintLinter()
            # Pass only non-YAML files
            result = linter.run(files=["script.py", "README.md"])

        # run_checked should NOT be called
        assert not mock_run_checked.called, "run_checked should not be called when no YAML files"
        # Should return success
        assert result.success is True
        # Should print the short-circuit message
        captured = capsys.readouterr()
        assert "No YAML files to check" in captured.out


# --- DotenvlintLinter Tests ---


class TestRunDotenvlint:
    """Tests for DotenvlintLinter configuration patterns."""

    @pytest.fixture
    def dotenvlint_config(self, fake_repo: Path, fs: FakeFilesystem) -> Path:
        """Create dotenvlint configuration file."""
        config = fake_repo / ".lint.dotenvlint.yaml"
        fs.create_file(
            str(config),
            contents=(
                "targets:\n"
                "  - .env.example\n"
                "  - .env.*.example\n"
                "exclude_patterns:\n"
                "  - .env.local\n"
                "  - .env.*.local\n"
                "exclude_dirs:\n"
                "  - .tmp\n"
                "  - .worktrees\n"
            ),
        )
        return config

    def test_only_scans_example_env_files(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        dotenvlint_config: Path,
    ) -> None:
        """Should only scan .env.example and .env.*.example files."""
        # Create test files
        fs.create_file(str(fake_repo / ".env.example"), contents="KEY=value")
        fs.create_file(str(fake_repo / ".env.production.example"), contents="KEY=value")
        fs.create_file(str(fake_repo / ".env"), contents="SECRET=hidden")
        fs.create_file(str(fake_repo / ".env.local"), contents="LOCAL=value")
        fs.create_file(str(fake_repo / ".env.development"), contents="DEV=value")

        with (
            patch("scripts.dev.linter.linters.dotenvlint.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.dotenvlint.LINT_DOTENVLINT_CONFIG", dotenvlint_config
            ),
            patch(
                "scripts.dev.linter.linters.dotenvlint.get_executable",
                return_value="/usr/bin/dotenv-linter",
            ),
            patch("scripts.dev.linter.linters.dotenvlint.run_checked") as mock_run_checked,
        ):
            linter = DotenvlintLinter()
            linter.run()

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        # Get the files passed to the linter (after 'check' argument)
        check_index = cmd.index("check")
        files_passed = cmd[check_index + 1 :]

        # .env.example and .env.*.example should be included
        assert any(".env.example" in f for f in files_passed), ".env.example should be scanned"
        assert any(".env.production.example" in f for f in files_passed), (
            ".env.*.example files should be scanned"
        )
        # .env should NOT be included
        assert not any(f.endswith("/.env") or f == ".env" for f in files_passed), (
            ".env should NOT be scanned"
        )
        # .env.local should NOT be included (excluded pattern), and non-example .env.* skipped
        assert not any(".env.local" in f for f in files_passed), ".env.local should NOT be scanned"
        assert not any(".env.development" in f for f in files_passed), (
            "non-example .env.* files should NOT be scanned"
        )

    def test_excludes_tmp_directory(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        dotenvlint_config: Path,
    ) -> None:
        """Should exclude .env files in .tmp directory."""
        fs.create_file(str(fake_repo / ".env.example"), contents="KEY=value")
        fs.create_dir(str(fake_repo / ".tmp"))
        fs.create_file(str(fake_repo / ".tmp" / ".env.example"), contents="KEY=value")

        with (
            patch("scripts.dev.linter.linters.dotenvlint.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.dotenvlint.LINT_DOTENVLINT_CONFIG", dotenvlint_config
            ),
            patch(
                "scripts.dev.linter.linters.dotenvlint.get_executable",
                return_value="/usr/bin/dotenv-linter",
            ),
            patch("scripts.dev.linter.linters.dotenvlint.run_checked") as mock_run_checked,
        ):
            linter = DotenvlintLinter()
            linter.run()

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        assert not any(".tmp" in arg for arg in cmd), "Files in .tmp should be excluded"

    def test_excludes_worktrees_directory(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        dotenvlint_config: Path,
    ) -> None:
        """Should exclude .env files in .worktrees directory."""
        fs.create_file(str(fake_repo / ".env.example"), contents="KEY=value")
        fs.create_dir(str(fake_repo / ".worktrees" / "branch"))
        fs.create_file(
            str(fake_repo / ".worktrees" / "branch" / ".env.production.example"),
            contents="KEY=value",
        )

        with (
            patch("scripts.dev.linter.linters.dotenvlint.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.dotenvlint.LINT_DOTENVLINT_CONFIG", dotenvlint_config
            ),
            patch(
                "scripts.dev.linter.linters.dotenvlint.get_executable",
                return_value="/usr/bin/dotenv-linter",
            ),
            patch("scripts.dev.linter.linters.dotenvlint.run_checked") as mock_run_checked,
        ):
            linter = DotenvlintLinter()
            linter.run()

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        assert not any(".worktrees" in arg for arg in cmd), "Files in .worktrees should be excluded"

    def test_excludes_local_env_files(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        dotenvlint_config: Path,
    ) -> None:
        """Should exclude .env.local files via exclude_patterns."""
        fs.create_file(str(fake_repo / ".env.example"), contents="KEY=value")
        fs.create_file(str(fake_repo / ".env.local"), contents="SECRET=hidden")
        fs.create_file(str(fake_repo / ".env.production.local"), contents="SECRET=hidden")

        with (
            patch("scripts.dev.linter.linters.dotenvlint.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.dotenvlint.LINT_DOTENVLINT_CONFIG", dotenvlint_config
            ),
            patch(
                "scripts.dev.linter.linters.dotenvlint.get_executable",
                return_value="/usr/bin/dotenv-linter",
            ),
            patch("scripts.dev.linter.linters.dotenvlint.run_checked") as mock_run_checked,
        ):
            linter = DotenvlintLinter()
            linter.run()

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        assert not any(".local" in arg for arg in cmd), ".local files should be excluded"

    def test_files_parameter_filters_to_env_files(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        dotenvlint_config: Path,
    ) -> None:
        """Should only pass .env files when files parameter is provided."""
        # Create test files
        fs.create_file(str(fake_repo / ".env.example"), contents="KEY=value")
        fs.create_file(str(fake_repo / ".env.production"), contents="PROD=value")
        fs.create_file(str(fake_repo / "config.yaml"), contents="key: value")
        fs.create_file(str(fake_repo / "script.py"), contents="print('hello')")

        with (
            patch("scripts.dev.linter.linters.dotenvlint.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.dotenvlint.LINT_DOTENVLINT_CONFIG", dotenvlint_config
            ),
            patch(
                "scripts.dev.linter.linters.dotenvlint.get_executable",
                return_value="/usr/bin/dotenv-linter",
            ),
            patch("scripts.dev.linter.linters.dotenvlint.run_checked") as mock_run_checked,
        ):
            linter = DotenvlintLinter()
            # Pass a mix of .env* and non-.env files
            linter.run(files=[".env.example", ".env.production", "config.yaml", "script.py"])

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        # Get files passed after 'check' argument
        check_index = cmd.index("check")
        files_passed = cmd[check_index + 1 :]

        # Only .env* files should be passed
        assert ".env.example" in files_passed, ".env.example should be included"
        assert ".env.production" in files_passed, ".env.production should be included"
        assert "config.yaml" not in files_passed, "config.yaml should NOT be included"
        assert "script.py" not in files_passed, "script.py should NOT be included"
        assert len(files_passed) == 2, "Only 2 .env files should be passed"

    def test_files_parameter_short_circuits_when_no_env_files(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        dotenvlint_config: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should not call run_checked when no .env files in the files list."""
        # Create test files (non-.env files only)
        fs.create_file(str(fake_repo / "config.yaml"), contents="key: value")
        fs.create_file(str(fake_repo / "script.py"), contents="print('hello')")

        with (
            patch("scripts.dev.linter.linters.dotenvlint.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.dotenvlint.LINT_DOTENVLINT_CONFIG", dotenvlint_config
            ),
            patch(
                "scripts.dev.linter.linters.dotenvlint.get_executable",
                return_value="/usr/bin/dotenv-linter",
            ),
            patch("scripts.dev.linter.linters.dotenvlint.run_checked") as mock_run_checked,
        ):
            linter = DotenvlintLinter()
            # Pass only non-.env files
            result = linter.run(files=["config.yaml", "script.py"])

        # run_checked should NOT be called
        assert not mock_run_checked.called, "run_checked should not be called when no .env files"
        # Should return success
        assert result.success is True
        # Should print the short-circuit message
        captured = capsys.readouterr()
        assert "No .env files to check" in captured.out


# --- DetectSecretsLinter Tests ---


class TestRunDetectSecrets:
    """Tests for DetectSecretsLinter configuration patterns."""

    @pytest.fixture
    def detect_secrets_config(self, fake_repo: Path, fs: FakeFilesystem) -> Path:
        """Create detect-secrets configuration and baseline files."""
        config = fake_repo / ".lint.detect-secrets.yaml"
        fs.create_file(
            str(config),
            contents=(
                "excluded_extensions:\n"
                "  - .pyc\n"
                "  - .png\n"
                "  - .jpg\n"
                "  - .db\n"
                "  - .sqlite\n"
                "  - .zip\n"
                "  - .tar\n"
                "  - .gz\n"
                "excluded_names:\n"
                "  - uv.lock\n"
                "  - .secrets.baseline\n"
            ),
        )
        baseline = fake_repo / ".secrets.baseline"
        fs.create_file(str(baseline), contents='{"version": "1.0.0"}')
        return config

    def test_excludes_binary_extensions(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        detect_secrets_config: Path,
    ) -> None:
        """Should exclude binary file extensions (.pyc, .png, .db, etc.)."""
        # Create test files
        fs.create_file(
            str(fake_repo / "script.py"),
            contents="API_KEY = 'test'",  # pragma: allowlist secret
        )
        fs.create_file(str(fake_repo / "script.pyc"), contents=b"\x00\x01\x02")
        fs.create_file(str(fake_repo / "image.png"), contents=b"\x89PNG")
        fs.create_file(str(fake_repo / "data.db"), contents=b"SQLite")

        with (
            patch("scripts.dev.linter.linters.detect_secrets.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.detect_secrets.SECRETS_BASELINE",
                fake_repo / ".secrets.baseline",
            ),
            patch(
                "scripts.dev.linter.linters.detect_secrets.LINT_DETECT_SECRETS_CONFIG",
                detect_secrets_config,
            ),
            patch(
                "scripts.dev.linter.linters.detect_secrets.get_executable",
                return_value="/usr/bin/uv",
            ),
            patch("scripts.dev.linter.linters.detect_secrets.run_checked") as mock_run_checked,
        ):
            linter = DetectSecretsLinter()
            # Test with file filtering (the path that uses excluded_extensions)
            linter.run(files=["script.py", "script.pyc", "image.png", "data.db"])

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        # script.py should be included
        assert any("script.py" in arg for arg in cmd), "Python source files should be scanned"
        # Binary files should be excluded
        assert not any(".pyc" in arg for arg in cmd), ".pyc files should be excluded"
        assert not any(".png" in arg for arg in cmd), ".png files should be excluded"
        assert not any(".db" in arg for arg in cmd), ".db files should be excluded"

    def test_excludes_specific_names(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        detect_secrets_config: Path,
    ) -> None:
        """Should exclude specific file names (uv.lock, .secrets.baseline)."""
        fs.create_file(str(fake_repo / "pyproject.toml"), contents="[project]")
        fs.create_file(str(fake_repo / "uv.lock"), contents="dependencies")

        with (
            patch("scripts.dev.linter.linters.detect_secrets.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.detect_secrets.SECRETS_BASELINE",
                fake_repo / ".secrets.baseline",
            ),
            patch(
                "scripts.dev.linter.linters.detect_secrets.LINT_DETECT_SECRETS_CONFIG",
                detect_secrets_config,
            ),
            patch(
                "scripts.dev.linter.linters.detect_secrets.get_executable",
                return_value="/usr/bin/uv",
            ),
            patch("scripts.dev.linter.linters.detect_secrets.run_checked") as mock_run_checked,
        ):
            linter = DetectSecretsLinter()
            linter.run(files=["pyproject.toml", "uv.lock", ".secrets.baseline"])

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        # Extract file arguments (those after --baseline and its value)
        baseline_idx = cmd.index("--baseline")
        file_args = cmd[baseline_idx + 2 :]  # Skip --baseline and its value
        # pyproject.toml should be included (handle bare names or full paths)
        assert any(arg.endswith("pyproject.toml") for arg in file_args), (
            "Config files should be scanned"
        )
        # Excluded names should not be present (handle bare names or full paths)
        assert not any(arg.endswith("uv.lock") for arg in file_args), "uv.lock should be excluded"
        assert not any(arg.endswith(".secrets.baseline") for arg in file_args), (
            ".secrets.baseline should be excluded"
        )

    def test_scans_text_config_files(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        detect_secrets_config: Path,
    ) -> None:
        """Should scan text configuration files like .yaml, .json, .toml."""
        fs.create_file(str(fake_repo / "pyproject.toml"), contents="[project]")
        fs.create_file(str(fake_repo / "config.yaml"), contents="key: value")
        fs.create_file(str(fake_repo / "settings.json"), contents='{"key": "value"}')
        fs.create_file(str(fake_repo / "script.sh"), contents="#!/bin/bash")

        with (
            patch("scripts.dev.linter.linters.detect_secrets.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.detect_secrets.SECRETS_BASELINE",
                fake_repo / ".secrets.baseline",
            ),
            patch(
                "scripts.dev.linter.linters.detect_secrets.LINT_DETECT_SECRETS_CONFIG",
                detect_secrets_config,
            ),
            patch(
                "scripts.dev.linter.linters.detect_secrets.get_executable",
                return_value="/usr/bin/uv",
            ),
            patch("scripts.dev.linter.linters.detect_secrets.run_checked") as mock_run_checked,
        ):
            linter = DetectSecretsLinter()
            linter.run(files=["pyproject.toml", "config.yaml", "settings.json", "script.sh"])

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        # All text config files should be included
        assert any("pyproject.toml" in arg for arg in cmd), "TOML files should be scanned"
        assert any("config.yaml" in arg for arg in cmd), "YAML files should be scanned"
        assert any("settings.json" in arg for arg in cmd), "JSON files should be scanned"
        assert any("script.sh" in arg for arg in cmd), "Shell scripts should be scanned"

    def test_no_scannable_files_short_circuits(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        detect_secrets_config: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should print message and skip scan when all files are excluded."""
        # Create only files that will be excluded (note: .secrets.baseline is
        # already created by the detect_secrets_config fixture)
        fs.create_file(str(fake_repo / "script.pyc"), contents=b"\x00\x01\x02")
        fs.create_file(str(fake_repo / "image.png"), contents=b"\x89PNG")
        fs.create_file(str(fake_repo / "data.db"), contents=b"SQLite")
        fs.create_file(str(fake_repo / "uv.lock"), contents="dependencies")

        with (
            patch("scripts.dev.linter.linters.detect_secrets.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.detect_secrets.SECRETS_BASELINE",
                fake_repo / ".secrets.baseline",
            ),
            patch(
                "scripts.dev.linter.linters.detect_secrets.LINT_DETECT_SECRETS_CONFIG",
                detect_secrets_config,
            ),
            patch(
                "scripts.dev.linter.linters.detect_secrets.get_executable",
                return_value="/usr/bin/uv",
            ),
            patch("scripts.dev.linter.linters.detect_secrets.run_checked") as mock_run_checked,
        ):
            linter = DetectSecretsLinter()
            result = linter.run(
                files=["script.pyc", "image.png", "data.db", "uv.lock", ".secrets.baseline"]
            )

        # run_checked should NOT be called when all files are excluded
        assert not mock_run_checked.called, (
            "run_checked should not be called with no scannable files"
        )

        # Verify the short-circuit message was printed
        captured = capsys.readouterr()
        assert "No scannable files for detect-secrets" in captured.out

        # Result should still indicate success
        assert result.success is True


# --- ActionlintLinter Tests ---


class TestRunActionlint:
    """Tests for ActionlintLinter configuration patterns."""

    @pytest.fixture
    def actionlint_config(self, fake_repo: Path, fs: FakeFilesystem) -> Path:
        """Create actionlint configuration file."""
        config = fake_repo / ".lint.actionlint.yaml"
        fs.create_file(
            str(config),
            contents=(
                "exclude_dirs:\n"
                "  - .tasks/store\n"
                "  - .tmp\n"
                "  - .worktrees\n"
                "  - .git-rewrite\n"
                "ignore: []\n"
            ),
        )
        return config

    def test_excludes_tmp_directory(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        actionlint_config: Path,
    ) -> None:
        """Should exclude workflow files in .tmp directory."""
        # Create main workflow directory
        fs.create_dir(str(fake_repo / ".github" / "workflows"))
        fs.create_file(
            str(fake_repo / ".github" / "workflows" / "ci.yml"),
            contents="name: CI\non: push",
        )
        # Create excluded workflow in .tmp
        fs.create_dir(str(fake_repo / ".tmp" / ".github" / "workflows"))
        fs.create_file(
            str(fake_repo / ".tmp" / ".github" / "workflows" / "test.yml"),
            contents="name: Test\non: push",
        )

        with (
            patch("scripts.dev.linter.linters.actionlint.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.actionlint.LINT_ACTIONLINT_CONFIG", actionlint_config
            ),
            patch(
                "scripts.dev.linter.linters.actionlint.get_executable",
                return_value="/usr/bin/actionlint",
            ),
            patch("scripts.dev.linter.linters.actionlint.run_checked") as mock_run_checked,
        ):
            linter = ActionlintLinter()
            linter.run()

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        # Main workflow should be included
        assert any("ci.yml" in arg for arg in cmd), "Main workflows should be linted"
        # .tmp workflows should be excluded
        assert not any(".tmp" in arg for arg in cmd), "Files in .tmp should be excluded"

    def test_excludes_worktrees_directory(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        actionlint_config: Path,
    ) -> None:
        """Should exclude workflow files in .worktrees directory."""
        fs.create_dir(str(fake_repo / ".github" / "workflows"))
        fs.create_file(
            str(fake_repo / ".github" / "workflows" / "ci.yml"),
            contents="name: CI\non: push",
        )
        fs.create_dir(str(fake_repo / ".worktrees" / "feature" / ".github" / "workflows"))
        fs.create_file(
            str(fake_repo / ".worktrees" / "feature" / ".github" / "workflows" / "ci.yml"),
            contents="name: CI\non: push",
        )

        with (
            patch("scripts.dev.linter.linters.actionlint.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.actionlint.LINT_ACTIONLINT_CONFIG", actionlint_config
            ),
            patch(
                "scripts.dev.linter.linters.actionlint.get_executable",
                return_value="/usr/bin/actionlint",
            ),
            patch("scripts.dev.linter.linters.actionlint.run_checked") as mock_run_checked,
        ):
            linter = ActionlintLinter()
            linter.run()

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        assert not any(".worktrees" in arg for arg in cmd), "Files in .worktrees should be excluded"

    def test_excludes_tasks_store_directory(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        actionlint_config: Path,
    ) -> None:
        """Should exclude workflow files in .tasks/store directory."""
        fs.create_dir(str(fake_repo / ".github" / "workflows"))
        fs.create_file(
            str(fake_repo / ".github" / "workflows" / "ci.yml"),
            contents="name: CI\non: push",
        )
        fs.create_dir(str(fake_repo / ".tasks" / "store" / ".github" / "workflows"))
        fs.create_file(
            str(fake_repo / ".tasks" / "store" / ".github" / "workflows" / "generated.yml"),
            contents="name: Generated\non: push",
        )

        with (
            patch("scripts.dev.linter.linters.actionlint.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.actionlint.LINT_ACTIONLINT_CONFIG", actionlint_config
            ),
            patch(
                "scripts.dev.linter.linters.actionlint.get_executable",
                return_value="/usr/bin/actionlint",
            ),
            patch("scripts.dev.linter.linters.actionlint.run_checked") as mock_run_checked,
        ):
            linter = ActionlintLinter()
            linter.run()

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        assert not any(".tasks/store" in arg or ".tasks\\store" in arg for arg in cmd), (
            "Files in .tasks/store should be excluded"
        )

    def test_excludes_git_rewrite_directory(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        actionlint_config: Path,
    ) -> None:
        """Should exclude workflow files in .git-rewrite directory."""
        fs.create_dir(str(fake_repo / ".github" / "workflows"))
        fs.create_file(
            str(fake_repo / ".github" / "workflows" / "ci.yml"),
            contents="name: CI\non: push",
        )
        fs.create_dir(str(fake_repo / ".git-rewrite" / ".github" / "workflows"))
        fs.create_file(
            str(fake_repo / ".git-rewrite" / ".github" / "workflows" / "temp.yml"),
            contents="name: Temp\non: push",
        )

        with (
            patch("scripts.dev.linter.linters.actionlint.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.actionlint.LINT_ACTIONLINT_CONFIG", actionlint_config
            ),
            patch(
                "scripts.dev.linter.linters.actionlint.get_executable",
                return_value="/usr/bin/actionlint",
            ),
            patch("scripts.dev.linter.linters.actionlint.run_checked") as mock_run_checked,
        ):
            linter = ActionlintLinter()
            linter.run()

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        assert not any(".git-rewrite" in arg for arg in cmd), (
            "Files in .git-rewrite should be excluded"
        )

    def test_includes_main_github_workflows(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        actionlint_config: Path,
    ) -> None:
        """Should include workflow files in main .github/workflows directory."""
        fs.create_dir(str(fake_repo / ".github" / "workflows"))
        fs.create_file(
            str(fake_repo / ".github" / "workflows" / "ci.yml"),
            contents="name: CI\non: push",
        )
        fs.create_file(
            str(fake_repo / ".github" / "workflows" / "deploy.yaml"),
            contents="name: Deploy\non: push",
        )

        with (
            patch("scripts.dev.linter.linters.actionlint.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.actionlint.LINT_ACTIONLINT_CONFIG", actionlint_config
            ),
            patch(
                "scripts.dev.linter.linters.actionlint.get_executable",
                return_value="/usr/bin/actionlint",
            ),
            patch("scripts.dev.linter.linters.actionlint.run_checked") as mock_run_checked,
        ):
            linter = ActionlintLinter()
            linter.run()

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        workflow_files = [arg for arg in cmd if arg.endswith((".yml", ".yaml"))]
        assert len(workflow_files) == 2, "Both workflow files should be included"

    def test_file_filtering_excludes_directories(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        actionlint_config: Path,
    ) -> None:
        """Should filter out excluded directories when using files parameter."""
        # Create main workflow directory with valid workflows
        fs.create_dir(str(fake_repo / ".github" / "workflows"))
        fs.create_file(
            str(fake_repo / ".github" / "workflows" / "ci.yml"),
            contents="name: CI\non: push",
        )
        fs.create_file(
            str(fake_repo / ".github" / "workflows" / "deploy.yaml"),
            contents="name: Deploy\non: push",
        )
        # Create workflows in excluded directories
        fs.create_dir(str(fake_repo / ".tmp" / ".github" / "workflows"))
        fs.create_file(
            str(fake_repo / ".tmp" / ".github" / "workflows" / "test.yml"),
            contents="name: Test\non: push",
        )
        fs.create_dir(str(fake_repo / ".worktrees" / "feature" / ".github" / "workflows"))
        fs.create_file(
            str(fake_repo / ".worktrees" / "feature" / ".github" / "workflows" / "ci.yml"),
            contents="name: CI\non: push",
        )
        fs.create_dir(str(fake_repo / ".tasks" / "store" / ".github" / "workflows"))
        fs.create_file(
            str(fake_repo / ".tasks" / "store" / ".github" / "workflows" / "generated.yml"),
            contents="name: Generated\non: push",
        )
        fs.create_dir(str(fake_repo / ".git-rewrite" / ".github" / "workflows"))
        fs.create_file(
            str(fake_repo / ".git-rewrite" / ".github" / "workflows" / "temp.yml"),
            contents="name: Temp\non: push",
        )

        # Prepare files list with mix of valid and excluded paths
        files = [
            ".github/workflows/ci.yml",
            ".github/workflows/deploy.yaml",
            ".tmp/.github/workflows/test.yml",
            ".worktrees/feature/.github/workflows/ci.yml",
            ".tasks/store/.github/workflows/generated.yml",
            ".git-rewrite/.github/workflows/temp.yml",
        ]

        with (
            patch("scripts.dev.linter.linters.actionlint.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.actionlint.LINT_ACTIONLINT_CONFIG", actionlint_config
            ),
            patch(
                "scripts.dev.linter.linters.actionlint.get_executable",
                return_value="/usr/bin/actionlint",
            ),
            patch("scripts.dev.linter.linters.actionlint.run_checked") as mock_run_checked,
        ):
            linter = ActionlintLinter()
            linter.run(files=files)

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        # Convert command args to string for easier checking
        cmd_str = " ".join(cmd)
        # Valid workflows should be included
        assert "ci.yml" in cmd_str, "Main workflow ci.yml should be included"
        assert "deploy.yaml" in cmd_str, "Main workflow deploy.yaml should be included"
        # Excluded paths should not be present (check both posix and windows separators)
        assert ".tmp" not in cmd_str, "Files in .tmp should be excluded"
        assert ".worktrees" not in cmd_str, "Files in .worktrees should be excluded"
        assert ".tasks/store" not in cmd_str and ".tasks\\store" not in cmd_str, (
            "Files in .tasks/store should be excluded"
        )
        assert ".git-rewrite" not in cmd_str, "Files in .git-rewrite should be excluded"
        # Verify only 2 workflow files passed (the main ones)
        workflow_args = [arg for arg in cmd if arg.endswith((".yml", ".yaml"))]
        assert len(workflow_args) == 2, (
            f"Only 2 main workflow files should be passed, got {len(workflow_args)}"
        )


# --- GitleaksLinter Tests ---


class TestRunGitleaks:
    """Tests for GitleaksLinter configuration patterns."""

    @pytest.fixture
    def gitleaks_config(self, fake_repo: Path, fs: FakeFilesystem) -> Path:
        """Create gitleaks configuration files."""
        lint_config = fake_repo / ".lint.gitleaks.yaml"
        fs.create_file(
            str(lint_config),
            contents=(
                "excluded_extensions:\n"
                "  - .pyc\n"
                "  - .png\n"
                "  - .jpg\n"
                "  - .db\n"
                "  - .sqlite\n"
                "  - .zip\n"
                "  - .tar\n"
                "  - .gz\n"
                "excluded_names:\n"
                "  - uv.lock\n"
                "  - .secrets.baseline\n"
                "excluded_dirs:\n"
                "  - .tmp\n"
                "  - .worktrees\n"
                "  - .venv\n"
            ),
        )
        gitleaks_toml = fake_repo / ".gitleaks.toml"
        fs.create_file(str(gitleaks_toml), contents="[[ rules ]]")
        return gitleaks_toml

    # --- Happy-path tests (exclusion patterns and short-circuit) ---

    def test_excludes_binary_extensions(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        gitleaks_config: Path,
    ) -> None:
        """Should exclude binary file extensions (.pyc, .png, .db, etc.)."""
        # Create test files
        fs.create_file(
            str(fake_repo / "script.py"),
            contents="API_KEY = 'test'",  # pragma: allowlist secret
        )
        fs.create_file(str(fake_repo / "script.pyc"), contents=b"\x00\x01\x02")
        fs.create_file(str(fake_repo / "image.png"), contents=b"\x89PNG")
        fs.create_file(str(fake_repo / "data.db"), contents=b"SQLite")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            patch("scripts.dev.linter.linters.gitleaks.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG", gitleaks_config),
            patch(
                "scripts.dev.linter.linters.gitleaks.LINT_GITLEAKS_CONFIG",
                fake_repo / ".lint.gitleaks.yaml",
            ),
            patch(
                "scripts.dev.linter.linters.gitleaks.get_executable",
                return_value="/usr/bin/gitleaks",
            ),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            linter = GitleaksLinter()
            linter.run(files=["script.py", "script.pyc", "image.png", "data.db"])

        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        # script.py should be included
        assert any("script.py" in arg for arg in cmd), "Python source files should be scanned"
        # Binary files should be excluded
        assert not any(".pyc" in arg for arg in cmd), ".pyc files should be excluded"
        assert not any(".png" in arg for arg in cmd), ".png files should be excluded"
        assert not any(".db" in arg for arg in cmd), ".db files should be excluded"

    def test_excludes_specific_names(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        gitleaks_config: Path,
    ) -> None:
        """Should exclude specific file names (uv.lock, .secrets.baseline)."""
        fs.create_file(str(fake_repo / "pyproject.toml"), contents="[project]")
        fs.create_file(str(fake_repo / "uv.lock"), contents="dependencies")
        fs.create_file(str(fake_repo / ".secrets.baseline"), contents='{"version": "1.0.0"}')

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            patch("scripts.dev.linter.linters.gitleaks.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG", gitleaks_config),
            patch(
                "scripts.dev.linter.linters.gitleaks.LINT_GITLEAKS_CONFIG",
                fake_repo / ".lint.gitleaks.yaml",
            ),
            patch(
                "scripts.dev.linter.linters.gitleaks.get_executable",
                return_value="/usr/bin/gitleaks",
            ),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            linter = GitleaksLinter()
            linter.run(files=["pyproject.toml", "uv.lock", ".secrets.baseline"])

        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        # pyproject.toml should be included
        assert any("pyproject.toml" in arg for arg in cmd), "Config files should be scanned"
        # Excluded names should not be present
        assert not any("uv.lock" in arg for arg in cmd), "uv.lock should be excluded"
        assert not any(".secrets.baseline" in arg for arg in cmd), (
            ".secrets.baseline should be excluded"
        )

    def test_excludes_directories(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        gitleaks_config: Path,
    ) -> None:
        """Should exclude files in excluded directories (.tmp, .worktrees, .venv)."""
        fs.create_file(str(fake_repo / "main.py"), contents="print('hello')")
        fs.create_dir(str(fake_repo / ".tmp"))
        fs.create_file(
            str(fake_repo / ".tmp" / "secret.py"),
            contents="API_KEY = 'test'",  # pragma: allowlist secret
        )
        fs.create_dir(str(fake_repo / ".worktrees" / "branch"))
        fs.create_file(
            str(fake_repo / ".worktrees" / "branch" / "config.py"),
            contents="SECRET = 'value'",  # pragma: allowlist secret
        )
        fs.create_dir(str(fake_repo / ".venv"))
        fs.create_file(str(fake_repo / ".venv" / "package.py"), contents="TOKEN = 'abc'")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            patch("scripts.dev.linter.linters.gitleaks.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG", gitleaks_config),
            patch(
                "scripts.dev.linter.linters.gitleaks.LINT_GITLEAKS_CONFIG",
                fake_repo / ".lint.gitleaks.yaml",
            ),
            patch(
                "scripts.dev.linter.linters.gitleaks.get_executable",
                return_value="/usr/bin/gitleaks",
            ),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            linter = GitleaksLinter()
            linter.run(
                files=[
                    "main.py",
                    ".tmp/secret.py",
                    ".worktrees/branch/config.py",
                    ".venv/package.py",
                ]
            )

        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        # main.py should be included
        assert any("main.py" in arg for arg in cmd), "Root files should be scanned"
        # Excluded directories should not be present
        assert not any(".tmp" in arg for arg in cmd), "Files in .tmp should be excluded"
        assert not any(".worktrees" in arg for arg in cmd), "Files in .worktrees should be excluded"
        assert not any(".venv" in arg for arg in cmd), "Files in .venv should be excluded"

    def test_file_filtering_works_correctly(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        gitleaks_config: Path,
    ) -> None:
        """Should filter files correctly when files parameter is provided."""
        fs.create_file(str(fake_repo / "app.py"), contents="print('app')")
        fs.create_file(str(fake_repo / "test.py"), contents="print('test')")
        fs.create_file(str(fake_repo / "config.toml"), contents="[config]")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            patch("scripts.dev.linter.linters.gitleaks.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG", gitleaks_config),
            patch(
                "scripts.dev.linter.linters.gitleaks.LINT_GITLEAKS_CONFIG",
                fake_repo / ".lint.gitleaks.yaml",
            ),
            patch(
                "scripts.dev.linter.linters.gitleaks.get_executable",
                return_value="/usr/bin/gitleaks",
            ),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            linter = GitleaksLinter()
            linter.run(files=["app.py", "test.py", "config.toml"])

        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        # All 3 files should be included
        assert any("app.py" in arg for arg in cmd), "app.py should be scanned"
        assert any("test.py" in arg for arg in cmd), "test.py should be scanned"
        assert any("config.toml" in arg for arg in cmd), "config.toml should be scanned"

    def test_short_circuit_when_no_scannable_files(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        gitleaks_config: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should not call subprocess.run when no scannable files remain after filtering."""
        # Create only files that will be excluded
        fs.create_file(str(fake_repo / "script.pyc"), contents=b"\x00\x01\x02")
        fs.create_file(str(fake_repo / "image.png"), contents=b"\x89PNG")
        fs.create_file(str(fake_repo / "uv.lock"), contents="dependencies")

        with (
            patch("scripts.dev.linter.linters.gitleaks.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG", gitleaks_config),
            patch(
                "scripts.dev.linter.linters.gitleaks.LINT_GITLEAKS_CONFIG",
                fake_repo / ".lint.gitleaks.yaml",
            ),
            patch(
                "scripts.dev.linter.linters.gitleaks.get_executable",
                return_value="/usr/bin/gitleaks",
            ),
            patch("subprocess.run") as mock_run,
        ):
            linter = GitleaksLinter()
            result = linter.run(files=["script.pyc", "image.png", "uv.lock"])

        # subprocess.run should NOT be called when all files are excluded
        assert not mock_run.called, "subprocess.run should not be called with no scannable files"

        # Verify the short-circuit message was printed
        captured = capsys.readouterr()
        assert "No scannable files for gitleaks" in captured.out

        # Result should indicate success
        assert result.success is True

    def test_missing_lint_config_uses_defaults(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """Should work without .lint.gitleaks.yaml by using empty defaults.

        This ensures consistent behavior between file-filtered mode (which loads
        exclusion config) and full-scan mode (which doesn't). When the config file
        is missing, file-filtered mode should proceed without exclusions rather
        than crashing.
        """
        # Create only .gitleaks.toml (not .lint.gitleaks.yaml)
        gitleaks_toml = fake_repo / ".gitleaks.toml"
        fs.create_file(str(gitleaks_toml), contents="[[ rules ]]")
        fs.create_file(str(fake_repo / "test.py"), contents="print('hello')")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        # Note: .lint.gitleaks.yaml does NOT exist
        missing_lint_config = fake_repo / ".lint.gitleaks.yaml"

        with (
            patch("scripts.dev.linter.linters.gitleaks.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG", gitleaks_toml),
            patch(
                "scripts.dev.linter.linters.gitleaks.LINT_GITLEAKS_CONFIG",
                missing_lint_config,
            ),
            patch(
                "scripts.dev.linter.linters.gitleaks.get_executable",
                return_value="/usr/bin/gitleaks",
            ),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            linter = GitleaksLinter()
            # Should NOT raise an exception when .lint.gitleaks.yaml is missing
            result = linter.run(files=["test.py"])

        # Should succeed and scan the file
        assert mock_run.called, "subprocess.run should be called"
        assert result.success is True
        cmd = mock_run.call_args[0][0]
        assert any("test.py" in arg for arg in cmd), "test.py should be scanned"

    def test_invalid_lint_config_returns_failure(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should return failure with clear error when .lint.gitleaks.yaml is invalid YAML.

        This ensures that malformed config files don't crash the linter with an unhandled
        exception but instead return a LinterResult with success=False and clear message.
        """
        # Create .gitleaks.toml (required)
        gitleaks_toml = fake_repo / ".gitleaks.toml"
        fs.create_file(str(gitleaks_toml), contents="[[ rules ]]")
        fs.create_file(str(fake_repo / "test.py"), contents="print('hello')")

        # Create invalid YAML config
        invalid_lint_config = fake_repo / ".lint.gitleaks.yaml"
        fs.create_file(str(invalid_lint_config), contents="invalid: yaml: content: [")

        with (
            patch("scripts.dev.linter.linters.gitleaks.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG", gitleaks_toml),
            patch(
                "scripts.dev.linter.linters.gitleaks.LINT_GITLEAKS_CONFIG",
                invalid_lint_config,
            ),
            patch(
                "scripts.dev.linter.linters.gitleaks.get_executable",
                return_value="/usr/bin/gitleaks",
            ),
            patch("subprocess.run") as mock_run,
        ):
            linter = GitleaksLinter()
            result = linter.run(files=["test.py"])

        # subprocess.run should NOT be called when config is invalid
        assert not mock_run.called, "subprocess.run should not be called when config is invalid"

        # Linter should return failure with actionable message
        assert result.success is False
        assert ".lint.gitleaks.yaml" in result.message

        # Should also print to stderr
        captured = capsys.readouterr()
        assert ".lint.gitleaks.yaml" in captured.err

    def test_unreadable_lint_config_returns_failure(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should return failure with clear error when .lint.gitleaks.yaml cannot be read.

        This ensures permission errors on the lint config file are handled gracefully
        rather than propagating as unhandled exceptions.
        """
        # Create .gitleaks.toml (required)
        gitleaks_toml = fake_repo / ".gitleaks.toml"
        fs.create_file(str(gitleaks_toml), contents="[[ rules ]]")
        fs.create_file(str(fake_repo / "test.py"), contents="print('hello')")

        # Create a mock config path that exists but raises PermissionError on load
        mock_lint_config = MagicMock()
        mock_lint_config.exists.return_value = True
        mock_lint_config.name = ".lint.gitleaks.yaml"

        with (
            patch("scripts.dev.linter.linters.gitleaks.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG", gitleaks_toml),
            patch(
                "scripts.dev.linter.linters.gitleaks.LINT_GITLEAKS_CONFIG",
                mock_lint_config,
            ),
            patch(
                "scripts.dev.linter.linters.gitleaks.get_executable",
                return_value="/usr/bin/gitleaks",
            ),
            patch(
                "scripts.dev.linter.linters.gitleaks.load_yaml_config",
                side_effect=PermissionError("Permission denied"),
            ),
            patch("subprocess.run") as mock_run,
        ):
            linter = GitleaksLinter()
            result = linter.run(files=["test.py"])

        # subprocess.run should NOT be called when config is unreadable
        assert not mock_run.called, "subprocess.run should not be called when config is unreadable"

        # Linter should return failure with actionable message
        assert result.success is False
        assert ".lint.gitleaks.yaml" in result.message

        # Should also print to stderr
        captured = capsys.readouterr()
        assert ".lint.gitleaks.yaml" in captured.err

    # --- Negative-path tests (configuration errors, binary availability, exit codes) ---

    def test_missing_gitleaks_binary_returns_failure_with_install_instructions(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        gitleaks_config: Path,
    ) -> None:
        """Should return failure with installation instructions when gitleaks binary is not found.

        This test validates that the linter handles missing binary gracefully by returning
        a LinterResult with success=False and a clear install-needed message, rather than
        propagating an unhandled exception.
        """
        from scripts.dev.linter.linters.gitleaks import GITLEAKS_CLI_NOT_FOUND

        fs.create_file(str(fake_repo / "test.py"), contents="print('hello')")

        with (
            patch("scripts.dev.linter.linters.gitleaks.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG", gitleaks_config),
            patch(
                "scripts.dev.linter.linters.gitleaks.get_executable",
                side_effect=RuntimeError(GITLEAKS_CLI_NOT_FOUND),
            ),
        ):
            linter = GitleaksLinter()
            result = linter.run(files=["test.py"])

        # Linter must return failure (not raise exception) with actionable message
        assert result.success is False
        assert "brew install gitleaks" in result.message
        assert "go install github.com/gitleaks/gitleaks/v8@v8.24.2" in result.message

    def test_missing_gitleaks_binary_subprocess_filenotfound(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        gitleaks_config: Path,
    ) -> None:
        """Should return failure when subprocess.run raises FileNotFoundError.

        This simulates the case where get_executable returns a path but the binary
        is not actually executable (e.g., removed after initial check).
        """
        fs.create_file(str(fake_repo / "test.py"), contents="print('hello')")

        with (
            patch("scripts.dev.linter.linters.gitleaks.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG", gitleaks_config),
            patch(
                "scripts.dev.linter.linters.gitleaks.LINT_GITLEAKS_CONFIG",
                fake_repo / ".lint.gitleaks.yaml",
            ),
            patch(
                "scripts.dev.linter.linters.gitleaks.get_executable",
                return_value="/usr/bin/gitleaks",
            ),
            patch(
                "subprocess.run",
                side_effect=FileNotFoundError("[Errno 2] No such file or directory: 'gitleaks'"),
            ),
        ):
            linter = GitleaksLinter()
            result = linter.run(files=["test.py"])

        # Linter must catch FileNotFoundError and return failure with install instructions
        assert result.success is False
        assert "gitleaks" in result.message.lower()
        # Should contain installation guidance
        assert "install" in result.message.lower() or "not found" in result.message.lower()

    def test_missing_gitleaks_config_returns_failure(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should return failure with helpful message when .gitleaks.toml is missing."""
        from scripts.dev.linter.linters.gitleaks import GITLEAKS_CONFIG_MISSING

        # Create lint config but NOT .gitleaks.toml
        lint_config = fake_repo / ".lint.gitleaks.yaml"
        fs.create_file(
            str(lint_config),
            contents="excluded_extensions: []\nexcluded_names: []\nexcluded_dirs: []\n",
        )
        fs.create_file(str(fake_repo / "test.py"), contents="print('hello')")

        # The gitleaks.toml file does not exist
        missing_config = fake_repo / ".gitleaks.toml"

        with (
            patch("scripts.dev.linter.linters.gitleaks.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG", missing_config),
            patch("scripts.dev.linter.linters.gitleaks.LINT_GITLEAKS_CONFIG", lint_config),
            patch(
                "scripts.dev.linter.linters.gitleaks.get_executable",
                return_value="/usr/bin/gitleaks",
            ),
            patch("subprocess.run") as mock_run,
        ):
            linter = GitleaksLinter()
            result = linter.run(files=["test.py"])

        # When config is missing, linter should NOT call subprocess.run
        assert not mock_run.called, "subprocess.run should not be called when config is missing"

        # Linter should return failure with actionable message
        assert result.success is False
        assert result.message == GITLEAKS_CONFIG_MISSING
        assert ".gitleaks.toml" in result.message
        assert "restore" in result.message.lower() or "create" in result.message.lower()

        # Should also print to stderr
        captured = capsys.readouterr()
        assert ".gitleaks.toml" in captured.err

    def test_unreadable_gitleaks_config_returns_failure(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should return failure with helpful message when .gitleaks.toml cannot be read."""
        from scripts.dev.linter.linters.gitleaks import GITLEAKS_CONFIG_UNREADABLE

        # Create lint config and .gitleaks.toml
        lint_config = fake_repo / ".lint.gitleaks.yaml"
        fs.create_file(
            str(lint_config),
            contents="excluded_extensions: []\nexcluded_names: []\nexcluded_dirs: []\n",
        )
        gitleaks_toml = fake_repo / ".gitleaks.toml"
        fs.create_file(str(gitleaks_toml), contents="[[ rules ]]")
        fs.create_file(str(fake_repo / "test.py"), contents="print('hello')")

        # Create a mock config path that exists but raises PermissionError on read
        mock_config = MagicMock()
        mock_config.exists.return_value = True
        mock_config.read_text.side_effect = PermissionError("Permission denied")
        mock_config.__str__ = MagicMock(return_value=str(gitleaks_toml))

        with (
            patch("scripts.dev.linter.linters.gitleaks.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG", mock_config),
            patch("scripts.dev.linter.linters.gitleaks.LINT_GITLEAKS_CONFIG", lint_config),
            patch(
                "scripts.dev.linter.linters.gitleaks.get_executable",
                return_value="/usr/bin/gitleaks",
            ),
            patch("subprocess.run") as mock_run,
        ):
            linter = GitleaksLinter()
            result = linter.run(files=["test.py"])

        # When config is unreadable, linter should NOT call subprocess.run
        assert not mock_run.called, "subprocess.run should not be called when config is unreadable"

        # Linter should return failure with actionable message
        assert result.success is False
        assert result.message == GITLEAKS_CONFIG_UNREADABLE
        assert "permission" in result.message.lower()

        # Should also print to stderr
        captured = capsys.readouterr()
        assert "permission" in captured.err.lower() or ".gitleaks.toml" in captured.err

    def test_exit_code_0_returns_success(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        gitleaks_config: Path,
    ) -> None:
        """Exit code 0 should indicate no secrets found (success)."""
        fs.create_file(str(fake_repo / "clean.py"), contents="print('no secrets here')")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            patch("scripts.dev.linter.linters.gitleaks.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG", gitleaks_config),
            patch(
                "scripts.dev.linter.linters.gitleaks.LINT_GITLEAKS_CONFIG",
                fake_repo / ".lint.gitleaks.yaml",
            ),
            patch(
                "scripts.dev.linter.linters.gitleaks.get_executable",
                return_value="/usr/bin/gitleaks",
            ),
            patch("subprocess.run", return_value=mock_result),
        ):
            linter = GitleaksLinter()
            result = linter.run(files=["clean.py"])

        assert result.success is True

    def test_exit_code_1_returns_failure_leaks_found(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        gitleaks_config: Path,
    ) -> None:
        """Exit code 1 should indicate secrets were found."""
        fs.create_file(
            str(fake_repo / "secret.py"),
            contents="API_KEY = 'secret'",  # pragma: allowlist secret
        )

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "Finding: API_KEY"
        mock_result.stderr = ""

        with (
            patch("scripts.dev.linter.linters.gitleaks.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG", gitleaks_config),
            patch(
                "scripts.dev.linter.linters.gitleaks.LINT_GITLEAKS_CONFIG",
                fake_repo / ".lint.gitleaks.yaml",
            ),
            patch(
                "scripts.dev.linter.linters.gitleaks.get_executable",
                return_value="/usr/bin/gitleaks",
            ),
            patch("subprocess.run", return_value=mock_result),
        ):
            linter = GitleaksLinter()
            result = linter.run(files=["secret.py"])

        assert result.success is False
        assert "secrets" in result.message.lower() or "leak" in result.message.lower()

    def test_exit_code_126_returns_failure_config_error(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        gitleaks_config: Path,
    ) -> None:
        """Exit code 126 should indicate configuration/flag error."""
        fs.create_file(str(fake_repo / "test.py"), contents="print('hello')")

        mock_result = MagicMock()
        mock_result.returncode = 126
        mock_result.stdout = ""
        mock_result.stderr = "unknown flag"

        with (
            patch("scripts.dev.linter.linters.gitleaks.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG", gitleaks_config),
            patch(
                "scripts.dev.linter.linters.gitleaks.LINT_GITLEAKS_CONFIG",
                fake_repo / ".lint.gitleaks.yaml",
            ),
            patch(
                "scripts.dev.linter.linters.gitleaks.get_executable",
                return_value="/usr/bin/gitleaks",
            ),
            patch("subprocess.run", return_value=mock_result),
        ):
            linter = GitleaksLinter()
            result = linter.run(files=["test.py"])

        assert result.success is False
        assert "configuration" in result.message.lower() or "flag" in result.message.lower()

    def test_unexpected_exit_code_returns_failure_with_version_hint(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        gitleaks_config: Path,
    ) -> None:
        """Unexpected exit code should return failure and suggest checking version compatibility."""
        fs.create_file(str(fake_repo / "test.py"), contents="print('hello')")

        mock_result = MagicMock()
        mock_result.returncode = 2  # Unexpected exit code
        mock_result.stdout = ""
        mock_result.stderr = "some error"

        with (
            patch("scripts.dev.linter.linters.gitleaks.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG", gitleaks_config),
            patch(
                "scripts.dev.linter.linters.gitleaks.LINT_GITLEAKS_CONFIG",
                fake_repo / ".lint.gitleaks.yaml",
            ),
            patch(
                "scripts.dev.linter.linters.gitleaks.get_executable",
                return_value="/usr/bin/gitleaks",
            ),
            patch("subprocess.run", return_value=mock_result),
        ):
            linter = GitleaksLinter()
            result = linter.run(files=["test.py"])

        assert result.success is False
        # Should mention version compatibility
        assert "version" in result.message.lower() or "v8" in result.message.lower()

    def test_timeout_returns_failure_with_timeout_message(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        gitleaks_config: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should return failure with clear message when gitleaks scan times out."""
        import subprocess

        from scripts.dev.linter.linters.gitleaks import GITLEAKS_TIMEOUT_MSG

        fs.create_file(str(fake_repo / "test.py"), contents="print('hello')")

        with (
            patch("scripts.dev.linter.linters.gitleaks.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG", gitleaks_config),
            patch(
                "scripts.dev.linter.linters.gitleaks.LINT_GITLEAKS_CONFIG",
                fake_repo / ".lint.gitleaks.yaml",
            ),
            patch(
                "scripts.dev.linter.linters.gitleaks.get_executable",
                return_value="/usr/bin/gitleaks",
            ),
            patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="gitleaks", timeout=300),
            ),
        ):
            linter = GitleaksLinter()
            result = linter.run(files=["test.py"])

        # Linter should return failure with timeout message
        assert result.success is False
        assert result.message == GITLEAKS_TIMEOUT_MSG
        assert "timed out" in result.message.lower()
        assert "5 minutes" in result.message

        # Should also print to stderr
        captured = capsys.readouterr()
        assert "timed out" in captured.err.lower()


# --- Cross-Tool Consistency Tests ---


class TestSecretScannerConsistency:
    """Tests to ensure gitleaks and detect-secrets have consistent exclusion patterns."""

    @pytest.fixture
    def gitleaks_config(self) -> dict:
        """Load .lint.gitleaks.yaml configuration."""
        import yaml

        config_path = Path(__file__).parents[3] / ".lint.gitleaks.yaml"
        with open(config_path) as f:
            return yaml.safe_load(f)

    @pytest.fixture
    def detect_secrets_config(self) -> dict:
        """Load .lint.detect-secrets.yaml configuration."""
        import yaml

        config_path = Path(__file__).parents[3] / ".lint.detect-secrets.yaml"
        with open(config_path) as f:
            return yaml.safe_load(f)

    def test_excluded_extensions_match(
        self, gitleaks_config: dict, detect_secrets_config: dict
    ) -> None:
        """Gitleaks excluded_extensions must match detect-secrets excluded_extensions."""
        gitleaks_exts = set(gitleaks_config.get("excluded_extensions", []))
        detect_secrets_exts = set(detect_secrets_config.get("excluded_extensions", []))
        assert gitleaks_exts == detect_secrets_exts, (
            f"Extension mismatch: gitleaks has {gitleaks_exts - detect_secrets_exts}, "
            f"detect-secrets has {detect_secrets_exts - gitleaks_exts}"
        )

    def test_excluded_names_match(self, gitleaks_config: dict, detect_secrets_config: dict) -> None:
        """Gitleaks excluded_names must match detect-secrets excluded_names."""
        gitleaks_names = set(gitleaks_config.get("excluded_names", []))
        detect_secrets_names = set(detect_secrets_config.get("excluded_names", []))
        assert gitleaks_names == detect_secrets_names, (
            f"Name mismatch: gitleaks has {gitleaks_names - detect_secrets_names}, "
            f"detect-secrets has {detect_secrets_names - gitleaks_names}"
        )

    def test_excluded_dirs_cover_precommit_patterns(self, gitleaks_config: dict) -> None:
        """Gitleaks excluded_dirs must cover all directories from pre-commit detect-secrets."""
        # Canonical directories from .pre-commit-config.yaml detect-secrets exclude.
        # MAINTAINER NOTE: Keep this set in sync with the detect-secrets hook's
        # exclude regex in .pre-commit-config.yaml. If that config changes,
        # update this set accordingly.
        canonical_dirs = {
            ".venv",
            "node_modules",
            "htmlcov",
            ".coverage",
            "openapi",
            ".review",
            ".tmp",
            ".worktrees",
            ".tasks/store",
            ".huggingface",
            ".serena",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".git-rewrite",
            "to_adapt",
            ".idea",
            "build",
            "dist",
        }
        gitleaks_dirs = set(gitleaks_config.get("excluded_dirs", []))
        missing = canonical_dirs - gitleaks_dirs
        assert not missing, f"Gitleaks missing canonical excluded dirs: {missing}"
