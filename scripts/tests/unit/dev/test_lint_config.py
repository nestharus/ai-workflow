from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.linter.linters.actionlint import ActionlintLinter
from scripts.dev.linter.linters.detect_secrets import DetectSecretsLinter
from scripts.dev.linter.linters.dotenvlint import DotenvlintLinter
from scripts.dev.linter.linters.gitleaks import GitleaksLinter
from scripts.dev.linter.linters.shellcheck import ShellcheckLinter
from scripts.dev.linter.linters.yamllint import YamllintLinter

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


@pytest.fixture
def fake_repo(fs: FakeFilesystem) -> Path:
    """Create a fake repository root for testing."""
    repo_root = Path("/fake/repo")
    fs.create_dir(str(repo_root))
    return repo_root


class TestRunYamllint:
    @pytest.fixture
    def yamllint_config(self, fake_repo: Path, fs: FakeFilesystem) -> tuple[Path, Path]:
        """Create yamllint configuration files.

        Returns:
            Tuple of (lint_config_path, yamllint_config_path).
        """
        lint_config = fake_repo / ".lint.yamllint.yaml"
        # Use included_paths format to match actual config structure
        fs.create_file(
            str(lint_config),
            contents="included_paths:\n  - '*.yaml'\n  - '*.yml'\n",
        )
        yamllint_config = fake_repo / ".yamllint.yaml"
        fs.create_file(str(yamllint_config), contents="")
        return lint_config, yamllint_config

    def test_only_includes_files_matching_patterns(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        yamllint_config: tuple[Path, Path],
    ) -> None:
        """Should only include files matching included_paths patterns."""
        lint_config, yamllint_cfg = yamllint_config
        # Create test files - root YAML is included via *.yaml pattern
        fs.create_file(str(fake_repo / "config.yml"), contents="key: value")
        # These are outside of included patterns (only root *.yaml/*.yml in fixture)
        fs.create_dir(str(fake_repo / ".tmp"))
        fs.create_file(str(fake_repo / ".tmp" / "excluded.yml"), contents="key: value")
        fs.create_dir(str(fake_repo / ".worktrees" / "branch"))
        fs.create_file(
            str(fake_repo / ".worktrees" / "branch" / "test.yaml"),
            contents="key: value",
        )

        with (
            patch("scripts.dev.linter.linters.yamllint.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.yamllint.LINT_YAMLLINT_CONFIG", lint_config),
            patch("scripts.dev.linter.linters.yamllint.YAMLLINT_CONFIG", yamllint_cfg),
            patch(
                "scripts.dev.linter.linters.yamllint.YAMLLINT_CONFIG",
                fake_repo / ".yamllint.yaml",
            ),
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
        # Assert .tmp/excluded.yml is NOT in the command (not in included patterns)
        assert not any(".tmp" in arg for arg in cmd), "Files in .tmp should not be included"
        # Assert .worktrees files are NOT in the command
        assert not any(".worktrees" in arg for arg in cmd), (
            "Files in .worktrees should not be included"
        )
        # Assert config.yml IS in the command (matches *.yml)
        assert any("config.yml" in arg for arg in cmd), "Root YAML files should be included"

    def test_includes_project_root_yaml(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        yamllint_config: tuple[Path, Path],
    ) -> None:
        """Should include YAML files in project root."""
        lint_config, yamllint_cfg = yamllint_config
        # .yamllint.yaml is already created by the fixture
        fs.create_file(str(fake_repo / "config.yml"), contents="key: value")
        fs.create_file(str(fake_repo / "settings.yaml"), contents="setting: true")

        with (
            patch("scripts.dev.linter.linters.yamllint.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.yamllint.LINT_YAMLLINT_CONFIG", lint_config),
            patch("scripts.dev.linter.linters.yamllint.YAMLLINT_CONFIG", yamllint_cfg),
            patch(
                "scripts.dev.linter.linters.yamllint.YAMLLINT_CONFIG",
                fake_repo / ".yamllint.yaml",
            ),
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

    def test_files_parameter_filters_to_yaml_and_included_paths(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        yamllint_config: tuple[Path, Path],
    ) -> None:
        """Should only pass YAML files matching included_paths when files parameter is provided."""
        lint_config, yamllint_cfg = yamllint_config
        # Create test files
        fs.create_file(str(fake_repo / "config.yml"), contents="key: value")
        fs.create_file(str(fake_repo / "settings.yaml"), contents="setting: true")
        fs.create_file(str(fake_repo / "script.py"), contents="print('hello')")
        fs.create_file(str(fake_repo / "README.md"), contents="# Readme")

        with (
            patch("scripts.dev.linter.linters.yamllint.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.yamllint.LINT_YAMLLINT_CONFIG", lint_config),
            patch("scripts.dev.linter.linters.yamllint.YAMLLINT_CONFIG", yamllint_cfg),
            patch(
                "scripts.dev.linter.linters.yamllint.YAMLLINT_CONFIG",
                fake_repo / ".yamllint.yaml",
            ),
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

        # Only YAML files matching included_paths should be passed
        assert any("config.yml" in f for f in files_passed), "config.yml should be included"
        assert any("settings.yaml" in f for f in files_passed), "settings.yaml should be included"
        assert not any("script.py" in f for f in files_passed), "script.py should NOT be included"
        assert not any("README.md" in f for f in files_passed), "README.md should NOT be included"

    def test_files_parameter_short_circuits_when_no_yaml_files(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        yamllint_config: tuple[Path, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should not call run_checked when no YAML files in the files list."""
        lint_config, yamllint_cfg = yamllint_config
        # Create test files (non-YAML files only)
        fs.create_file(str(fake_repo / "script.py"), contents="print('hello')")
        fs.create_file(str(fake_repo / "README.md"), contents="# Readme")

        with (
            patch("scripts.dev.linter.linters.yamllint.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.yamllint.LINT_YAMLLINT_CONFIG", lint_config),
            patch("scripts.dev.linter.linters.yamllint.YAMLLINT_CONFIG", yamllint_cfg),
            patch(
                "scripts.dev.linter.linters.yamllint.YAMLLINT_CONFIG",
                fake_repo / ".yamllint.yaml",
            ),
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
        assert "No YAML files found for yamllint scan" in captured.out


class TestRunDotenvlint:
    @pytest.fixture
    def dotenvlint_config(self, fake_repo: Path, fs: FakeFilesystem) -> Path:
        """Create dotenvlint configuration file."""
        config = fake_repo / ".lint.dotenvlint.yaml"
        # Use included_paths format to match actual config structure
        fs.create_file(
            str(config),
            contents=("included_paths:\n  - '.env'\n  - '.env.*'\n"),
        )
        return config

    def test_only_includes_env_files_matching_patterns(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        dotenvlint_config: Path,
    ) -> None:
        """Should only scan .env files matching included_paths patterns."""
        # Create test files that match *.env patterns
        fs.create_file(str(fake_repo / ".env"), contents="KEY=value")
        fs.create_file(str(fake_repo / ".env.production"), contents="KEY=value")
        # These are outside of included patterns (nested dirs not in patterns)
        fs.create_dir(str(fake_repo / ".tmp"))
        fs.create_file(str(fake_repo / ".tmp" / ".env"), contents="KEY=value")
        fs.create_dir(str(fake_repo / ".worktrees" / "branch"))
        fs.create_file(
            str(fake_repo / ".worktrees" / "branch" / ".env"),
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
        # Get the files passed to the linter (after 'check' argument)
        check_index = cmd.index("check")
        files_passed = cmd[check_index + 1 :]

        # Root .env files should be included (matching patterns)
        assert any(
            ".env" in f and ".tmp" not in f and ".worktrees" not in f for f in files_passed
        ), "Root .env should be scanned"
        # .tmp files should NOT be included (not in included patterns)
        assert not any(".tmp" in f for f in files_passed), ".tmp files should NOT be scanned"
        # .worktrees files should NOT be included (not in included patterns)
        assert not any(".worktrees" in f for f in files_passed), (
            ".worktrees files should NOT be scanned"
        )

    def test_files_parameter_filters_to_env_and_included_paths(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        dotenvlint_config: Path,
    ) -> None:
        """Should only pass .env files matching included_paths when files parameter is provided."""
        # Create test files
        fs.create_file(str(fake_repo / ".env"), contents="KEY=value")
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
            linter.run(files=[".env", ".env.production", "config.yaml", "script.py"])

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        # Get files passed after 'check' argument
        check_index = cmd.index("check")
        files_passed = cmd[check_index + 1 :]

        # Only .env* files matching included_paths should be passed
        assert any(".env" in f for f in files_passed), ".env should be included"
        assert any(".env.production" in f for f in files_passed), (
            ".env.production should be included"
        )
        assert not any("config.yaml" in f for f in files_passed), (
            "config.yaml should NOT be included"
        )
        assert not any("script.py" in f for f in files_passed), "script.py should NOT be included"

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
        assert "No .env files to check with dotenv-linter" in captured.out


class TestRunDetectSecrets:
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
            patch(
                "scripts.dev.linter.linters.detect_secrets.subprocess.run"
            ) as mock_subprocess_run,
        ):
            mock_subprocess_run.return_value = MagicMock(returncode=0)
            linter = DetectSecretsLinter()
            # Test with file filtering (the path that uses excluded_extensions)
            linter.run(files=["script.py", "script.pyc", "image.png", "data.db"])

        assert mock_subprocess_run.called
        cmd = mock_subprocess_run.call_args[0][0]
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
            patch(
                "scripts.dev.linter.linters.detect_secrets.subprocess.run"
            ) as mock_subprocess_run,
        ):
            mock_subprocess_run.return_value = MagicMock(returncode=0)
            linter = DetectSecretsLinter()
            linter.run(files=["pyproject.toml", "uv.lock", ".secrets.baseline"])

        assert mock_subprocess_run.called
        cmd = mock_subprocess_run.call_args[0][0]
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
            patch(
                "scripts.dev.linter.linters.detect_secrets.subprocess.run"
            ) as mock_subprocess_run,
        ):
            mock_subprocess_run.return_value = MagicMock(returncode=0)
            linter = DetectSecretsLinter()
            linter.run(files=["pyproject.toml", "config.yaml", "settings.json", "script.sh"])

        assert mock_subprocess_run.called
        cmd = mock_subprocess_run.call_args[0][0]
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


class TestRunActionlint:
    @pytest.fixture
    def actionlint_config(self, fake_repo: Path, fs: FakeFilesystem) -> Path:
        """Create actionlint configuration file."""
        config = fake_repo / ".lint.actionlint.yaml"
        # Use included_paths format to match actual config structure
        fs.create_file(
            str(config),
            contents=(
                "included_paths:\n"
                "  - '.github/workflows/*.yml'\n"
                "  - '.github/workflows/*.yaml'\n"
                "ignore: []\n"
            ),
        )
        return config

    def test_only_includes_main_github_workflows(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        actionlint_config: Path,
    ) -> None:
        """Should only include workflow files matching included_paths pattern."""
        # Create main workflow directory
        fs.create_dir(str(fake_repo / ".github" / "workflows"))
        fs.create_file(
            str(fake_repo / ".github" / "workflows" / "ci.yml"),
            contents="name: CI\non: push",
        )
        fs.create_file(
            str(fake_repo / ".github" / "workflows" / "deploy.yaml"),
            contents="name: Deploy\non: push",
        )
        # Create workflows in directories not matching included_paths
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
        assert any("deploy.yaml" in arg for arg in cmd), "Main workflows should be linted"
        # Other directory workflows should NOT be included (not in included_paths)
        assert not any(".tmp" in arg for arg in cmd), "Files in .tmp should not be included"
        assert not any(".worktrees" in arg for arg in cmd), (
            "Files in .worktrees should not be included"
        )
        assert not any(".tasks" in arg for arg in cmd), "Files in .tasks should not be included"
        assert not any(".git-rewrite" in arg for arg in cmd), (
            "Files in .git-rewrite should not be included"
        )

    def test_file_filtering_uses_included_paths(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        actionlint_config: Path,
    ) -> None:
        """Should filter files by included_paths when using files parameter."""
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
        # Create workflows in directories not matching included_paths
        fs.create_dir(str(fake_repo / ".tmp" / ".github" / "workflows"))
        fs.create_file(
            str(fake_repo / ".tmp" / ".github" / "workflows" / "test.yml"),
            contents="name: Test\non: push",
        )

        # Prepare files list with mix of valid and non-matching paths
        files = [
            ".github/workflows/ci.yml",
            ".github/workflows/deploy.yaml",
            ".tmp/.github/workflows/test.yml",
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
        # Non-matching paths should not be present
        assert ".tmp" not in cmd_str, "Files in .tmp should not be included"


class TestRunGitleaks:
    @pytest.fixture
    def gitleaks_config(self, fake_repo: Path, fs: FakeFilesystem) -> Path:
        """Create gitleaks configuration files."""
        lint_config = fake_repo / ".lint.gitleaks.yaml"
        # Use included_paths format to match actual config structure
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
                "included_paths:\n"
                "  - '*'\n"
                "  - 'app/**'\n"
                "  - 'scripts/**'\n"
                "  - 'tests/**'\n"
            ),
        )
        gitleaks_toml = fake_repo / ".gitleaks.toml"
        fs.create_file(str(gitleaks_toml), contents="[[ rules ]]")
        return gitleaks_toml

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

    def test_only_includes_paths_matching_patterns(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        gitleaks_config: Path,
    ) -> None:
        """Should only include files matching included_paths patterns."""
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
        # main.py should be included (matches * pattern)
        assert any("main.py" in arg for arg in cmd), "Root files should be scanned"
        # Files in directories not in included_paths should not be present
        assert not any(".tmp" in arg for arg in cmd), "Files in .tmp should not be included"
        assert not any(".worktrees" in arg for arg in cmd), (
            "Files in .worktrees should not be included"
        )
        assert not any(".venv" in arg for arg in cmd), "Files in .venv should not be included"

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


# --- ShellcheckLinter Tests ---


class TestRunShellcheck:
    """Tests for ShellcheckLinter configuration patterns."""

    @pytest.fixture
    def shellcheck_config(self, fake_repo: Path, fs: FakeFilesystem) -> Path:
        """Create shellcheck configuration file."""
        config = fake_repo / ".lint.shellcheck.yaml"
        # Use included_paths format to match actual config structure
        fs.create_file(
            str(config),
            contents=("included_paths:\n  - '*.sh'\n  - 'scripts/**/*.sh'\n  - 'bin/**/*.sh'\n"),
        )
        return config

    def test_only_includes_files_matching_patterns(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        shellcheck_config: Path,
    ) -> None:
        """Should only include shell scripts matching included_paths patterns."""
        # Create test files matching patterns
        fs.create_file(str(fake_repo / "scripts" / "setup.sh"), contents="#!/bin/bash\necho hello")
        # Create files NOT matching patterns (not in included_paths)
        fs.create_dir(str(fake_repo / ".tmp"))
        fs.create_file(
            str(fake_repo / ".tmp" / "excluded.sh"),
            contents="#!/bin/bash\necho excluded",
        )
        fs.create_dir(str(fake_repo / ".worktrees" / "branch"))
        fs.create_file(
            str(fake_repo / ".worktrees" / "branch" / "test.sh"),
            contents="#!/bin/bash\necho worktree",
        )

        with (
            patch("scripts.dev.linter.linters.shellcheck.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.shellcheck.LINT_SHELLCHECK_CONFIG", shellcheck_config
            ),
            patch(
                "scripts.dev.linter.linters.shellcheck.get_executable",
                return_value="/usr/bin/shellcheck",
            ),
            patch("scripts.dev.linter.linters.shellcheck.run_checked") as mock_run_checked,
        ):
            linter = ShellcheckLinter()
            linter.run()

        # Verify run_checked was called
        assert mock_run_checked.called
        # Get the command that was passed
        cmd = mock_run_checked.call_args[0][0]
        # Assert .tmp/excluded.sh is NOT in the command (not in included patterns)
        assert not any(".tmp" in arg for arg in cmd), "Files in .tmp should not be included"
        # Assert .worktrees files are NOT in the command
        assert not any(".worktrees" in arg for arg in cmd), (
            "Files in .worktrees should not be included"
        )
        # Assert scripts/setup.sh IS in the command (matches scripts/**/*.sh)
        assert any("setup.sh" in arg for arg in cmd), "Valid shell scripts should be included"

    def test_includes_project_shell_scripts(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        shellcheck_config: Path,
    ) -> None:
        """Should include shell scripts matching included_paths patterns."""
        fs.create_file(str(fake_repo / "scripts" / "setup.sh"), contents="#!/bin/bash\necho setup")
        fs.create_file(str(fake_repo / "bin" / "run.sh"), contents="#!/bin/bash\necho run")
        fs.create_file(str(fake_repo / "install.sh"), contents="#!/bin/bash\necho install")

        with (
            patch("scripts.dev.linter.linters.shellcheck.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.shellcheck.LINT_SHELLCHECK_CONFIG", shellcheck_config
            ),
            patch(
                "scripts.dev.linter.linters.shellcheck.get_executable",
                return_value="/usr/bin/shellcheck",
            ),
            patch("scripts.dev.linter.linters.shellcheck.run_checked") as mock_run_checked,
        ):
            linter = ShellcheckLinter()
            linter.run()

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        # Check that matching shell scripts are included
        shell_files = [arg for arg in cmd if arg.endswith(".sh")]
        # install.sh matches *.sh, scripts/setup.sh matches scripts/**/*.sh,
        # bin/run.sh matches bin/**/*.sh
        assert len(shell_files) == 3, "All 3 shell scripts should be included"

    def test_files_parameter_filters_to_sh_and_included_paths(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        shellcheck_config: Path,
    ) -> None:
        """Should only pass .sh files matching included_paths when files parameter is provided."""
        # Create test files
        fs.create_file(str(fake_repo / "setup.sh"), contents="#!/bin/bash\necho setup")
        fs.create_file(str(fake_repo / "scripts" / "build.sh"), contents="#!/bin/bash\necho build")
        fs.create_file(str(fake_repo / "script.py"), contents="print('hello')")
        fs.create_file(str(fake_repo / "README.md"), contents="# Readme")

        with (
            patch("scripts.dev.linter.linters.shellcheck.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.shellcheck.LINT_SHELLCHECK_CONFIG", shellcheck_config
            ),
            patch(
                "scripts.dev.linter.linters.shellcheck.get_executable",
                return_value="/usr/bin/shellcheck",
            ),
            patch("scripts.dev.linter.linters.shellcheck.run_checked") as mock_run_checked,
        ):
            linter = ShellcheckLinter()
            # Pass a mix of shell and non-shell files
            linter.run(files=["setup.sh", "scripts/build.sh", "script.py", "README.md"])

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        # Get files passed after the shellcheck executable
        files_passed = cmd[1:]  # Skip the executable

        # Only shell files matching included_paths should be passed
        assert any("setup.sh" in f for f in files_passed), "setup.sh should be included"
        assert any("build.sh" in f for f in files_passed), "scripts/build.sh should be included"
        assert not any("script.py" in f for f in files_passed), "script.py should NOT be included"
        assert not any("README.md" in f for f in files_passed), "README.md should NOT be included"
        assert len(files_passed) == 2, "Only 2 shell scripts should be passed"

    def test_files_parameter_short_circuits_when_no_sh_files(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        shellcheck_config: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should not call run_checked when no .sh files in the files list."""
        # Create test files (non-shell files only)
        fs.create_file(str(fake_repo / "script.py"), contents="print('hello')")
        fs.create_file(str(fake_repo / "README.md"), contents="# Readme")

        with (
            patch("scripts.dev.linter.linters.shellcheck.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.shellcheck.LINT_SHELLCHECK_CONFIG", shellcheck_config
            ),
            patch(
                "scripts.dev.linter.linters.shellcheck.get_executable",
                return_value="/usr/bin/shellcheck",
            ),
            patch("scripts.dev.linter.linters.shellcheck.run_checked") as mock_run_checked,
        ):
            linter = ShellcheckLinter()
            # Pass only non-shell files
            result = linter.run(files=["script.py", "README.md"])

        # run_checked should NOT be called
        assert not mock_run_checked.called, "run_checked should not be called when no .sh files"
        # Should return success
        assert result.success is True
        # Should print the short-circuit message
        captured = capsys.readouterr()
        assert "No shell scripts to check" in captured.out

    def test_missing_shellcheck_binary_returns_failure(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        shellcheck_config: Path,
    ) -> None:
        """Should return failure with message when shellcheck binary is not found."""
        from scripts.dev.linter.linters.shellcheck import SHELLCHECK_CLI_REQUIRED

        fs.create_file(str(fake_repo / "test.sh"), contents="#!/bin/bash\necho hello")

        with (
            patch("scripts.dev.linter.linters.shellcheck.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.shellcheck.LINT_SHELLCHECK_CONFIG", shellcheck_config
            ),
            patch(
                "scripts.dev.linter.linters.shellcheck.get_executable",
                side_effect=RuntimeError(SHELLCHECK_CLI_REQUIRED),
            ),
        ):
            linter = ShellcheckLinter()
            result = linter.run(files=["test.sh"])

        # Linter must return failure (not raise exception) with actionable message
        assert result.success is False
        assert "shellcheck CLI required to run lint" in result.message

    def test_files_parameter_filters_by_included_paths(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        shellcheck_config: Path,
    ) -> None:
        """Should filter files by included_paths when --files parameter is provided."""
        # Create files in both included and non-included directories
        fs.create_dir(str(fake_repo / ".tmp"))
        fs.create_file(str(fake_repo / ".tmp" / "script.sh"), contents="#!/bin/bash\necho tmp")
        fs.create_dir(str(fake_repo / "scripts"))
        fs.create_file(str(fake_repo / "scripts" / "valid.sh"), contents="#!/bin/bash\necho valid")

        with (
            patch("scripts.dev.linter.linters.shellcheck.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.shellcheck.LINT_SHELLCHECK_CONFIG", shellcheck_config
            ),
            patch(
                "scripts.dev.linter.linters.shellcheck.get_executable",
                return_value="/usr/bin/shellcheck",
            ),
            patch("scripts.dev.linter.linters.shellcheck.run_checked") as mock_run_checked,
        ):
            linter = ShellcheckLinter()
            linter.run(files=[".tmp/script.sh", "scripts/valid.sh"])

        assert mock_run_checked.called
        cmd = mock_run_checked.call_args[0][0]
        # Only scripts/valid.sh should be passed (matches scripts/**/*.sh)
        assert any("valid.sh" in arg for arg in cmd), "scripts/valid.sh should be passed"
        # .tmp paths should not be included (not in included_paths)
        assert not any(".tmp" in arg for arg in cmd), ".tmp paths should not be included"

    def test_files_parameter_short_circuits_when_no_matching_paths(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        shellcheck_config: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should short-circuit when no files match included_paths patterns."""
        # Create files only in directories not matching included_paths
        fs.create_dir(str(fake_repo / ".tmp"))
        fs.create_file(str(fake_repo / ".tmp" / "test.sh"), contents="#!/bin/bash\necho tmp")
        fs.create_dir(str(fake_repo / ".worktrees" / "branch"))
        fs.create_file(
            str(fake_repo / ".worktrees" / "branch" / "check.sh"),
            contents="#!/bin/bash\necho worktree",
        )

        with (
            patch("scripts.dev.linter.linters.shellcheck.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.shellcheck.LINT_SHELLCHECK_CONFIG", shellcheck_config
            ),
            patch(
                "scripts.dev.linter.linters.shellcheck.get_executable",
                return_value="/usr/bin/shellcheck",
            ),
            patch("scripts.dev.linter.linters.shellcheck.run_checked") as mock_run_checked,
        ):
            linter = ShellcheckLinter()
            result = linter.run(files=[".tmp/test.sh", ".worktrees/branch/check.sh"])

        # run_checked should NOT be called when no files match included_paths
        assert not mock_run_checked.called, (
            "run_checked should not be called when no files match patterns"
        )

        # Should print the short-circuit message
        captured = capsys.readouterr()
        assert "No shell scripts to check" in captured.out

        # Result should indicate success
        assert result.success is True

    def test_invalid_lint_config_returns_failure(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should return failure with clear error when .lint.shellcheck.yaml is invalid YAML.

        This ensures that malformed config files don't crash the linter with an unhandled
        exception but instead return a LinterResult with success=False and clear message.
        """
        fs.create_file(str(fake_repo / "test.sh"), contents="#!/bin/bash\necho hello")

        # Create invalid YAML config
        invalid_config = fake_repo / ".lint.shellcheck.yaml"
        fs.create_file(str(invalid_config), contents="invalid: yaml: content: [")

        with (
            patch("scripts.dev.linter.linters.shellcheck.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.shellcheck.LINT_SHELLCHECK_CONFIG", invalid_config),
            patch(
                "scripts.dev.linter.linters.shellcheck.get_executable",
                return_value="/usr/bin/shellcheck",
            ),
            patch("scripts.dev.linter.linters.shellcheck.run_checked") as mock_run_checked,
        ):
            linter = ShellcheckLinter()
            result = linter.run(files=["test.sh"])

        # run_checked should NOT be called when config is invalid
        assert not mock_run_checked.called, "run_checked should not be called when config invalid"

        # Linter should return failure with actionable message
        assert result.success is False
        assert ".lint.shellcheck.yaml" in result.message

        # Should also print to stderr
        captured = capsys.readouterr()
        assert ".lint.shellcheck.yaml" in captured.err
