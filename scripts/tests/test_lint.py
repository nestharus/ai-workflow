"""Tests for scripts.lint module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts.dev import lint
from scripts.dev.lint import (
    LINT_ACTIONLINT_CONFIG,
    LINT_MARKDOWN_RESTRICTION_CONFIG,
    LINTER_NAMES,
    LINTER_RUNNERS_NO_FILES,
    LINTER_RUNNERS_WITH_FILES,
    InvalidCommandError,
    _actionlint,
    _hadolint,
    _load_yaml_config,
    _parse_args,
    _run_actionlint,
    _run_checked,
    _run_checkov,
    _run_hadolint,
    _run_markdown_restriction,
    _run_mypy,
    _run_pymarkdown,
    _run_ruff,
    _run_scripts,
    _run_yamldocs,
    _run_yamllint,
    _uv,
    main,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestInvalidCommandError:
    """Tests for InvalidCommandError exception."""

    def test_has_standard_message(self) -> None:
        """Should have standard validation message."""
        error = InvalidCommandError()
        assert "non-empty list of strings" in str(error)


class TestUv:
    """Tests for _uv function."""

    def test_returns_uv_path_when_found(self) -> None:
        """Should return uv executable path when available."""
        with patch("shutil.which", return_value="/usr/bin/uv"):
            result = _uv()
            assert result == "/usr/bin/uv"

    def test_raises_when_not_found(self) -> None:
        """Should raise RuntimeError when uv not found."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError) as exc_info:
                _uv()
            assert "uv CLI required" in str(exc_info.value)


class TestHadolint:
    """Tests for _hadolint function."""

    def test_returns_hadolint_path_when_found(self) -> None:
        """Should return hadolint executable path when available."""
        with patch("shutil.which", return_value="/usr/bin/hadolint"):
            result = _hadolint()
            assert result == "/usr/bin/hadolint"

    def test_raises_when_not_found(self) -> None:
        """Should raise RuntimeError when hadolint not found."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError) as exc_info:
                _hadolint()
            assert "hadolint CLI required" in str(exc_info.value)


class TestActionlint:
    """Tests for _actionlint function."""

    def test_returns_actionlint_path_when_found(self) -> None:
        """Should return actionlint executable path when available."""
        with patch("shutil.which", return_value="/usr/bin/actionlint"):
            result = _actionlint()
            assert result == "/usr/bin/actionlint"

    def test_raises_when_not_found(self) -> None:
        """Should raise RuntimeError when actionlint not found."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError) as exc_info:
                _actionlint()
            assert "actionlint CLI required" in str(exc_info.value)


class TestRunChecked:
    """Tests for _run_checked function."""

    def test_calls_subprocess_with_valid_command(self) -> None:
        """Should call subprocess.check_call with valid command."""
        with patch("subprocess.check_call") as mock_check_call:
            _run_checked(["echo", "test"])
            mock_check_call.assert_called_once_with(["echo", "test"])

    def test_raises_for_empty_command(self) -> None:
        """Should raise InvalidCommandError for empty command."""
        with pytest.raises(InvalidCommandError):
            _run_checked([])

    def test_raises_for_non_list_command(self) -> None:
        """Should raise InvalidCommandError for non-list command."""
        with pytest.raises(InvalidCommandError):
            _run_checked("echo test")  # type: ignore[arg-type]

    def test_raises_for_non_string_elements(self) -> None:
        """Should raise InvalidCommandError for non-string elements."""
        with pytest.raises(InvalidCommandError):
            _run_checked(["echo", 123])  # type: ignore[list-item]

    def test_propagates_subprocess_error(self) -> None:
        """Should propagate CalledProcessError from subprocess."""
        with patch("subprocess.check_call") as mock_check_call:
            mock_check_call.side_effect = subprocess.CalledProcessError(1, ["false"])
            with pytest.raises(subprocess.CalledProcessError):
                _run_checked(["false"])


class TestLoadYamlConfig:
    """Tests for _load_yaml_config function."""

    def test_loads_yaml_file(self, fs: FakeFilesystem) -> None:
        """Should load and parse YAML file."""
        fs.create_file("/config.yaml", contents="key: value\nlist:\n  - item1\n  - item2")
        result = _load_yaml_config(Path("/config.yaml"))
        assert result == {"key": "value", "list": ["item1", "item2"]}

    def test_returns_empty_dict_for_empty_file(self, fs: FakeFilesystem) -> None:
        """Should return empty dict for empty YAML file."""
        fs.create_file("/config.yaml", contents="")
        result = _load_yaml_config(Path("/config.yaml"))
        assert result == {}


class TestRunScripts:
    """Tests for _run_scripts function."""

    def test_returns_one_when_no_prefix_rules(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when no prefix_rules defined in config."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/.lint.scripts.yaml", contents="# empty config")
        fs.create_file("/fake/repo/pyproject.toml", contents="[project.scripts]")

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_SCRIPTS_CONFIG", Path("/fake/repo/.lint.scripts.yaml")),
        ):
            result = _run_scripts()

        assert result == 1
        captured = capsys.readouterr()
        assert "No prefix_rules defined" in captured.err

    def test_returns_one_when_pyproject_missing(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when pyproject.toml is missing."""
        fs.create_dir("/fake/repo")
        fs.create_file(
            "/fake/repo/.lint.scripts.yaml",
            contents="prefix_rules:\n  scripts.knowledge.: knowledge.",
        )

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_SCRIPTS_CONFIG", Path("/fake/repo/.lint.scripts.yaml")),
        ):
            result = _run_scripts()

        assert result == 1
        captured = capsys.readouterr()
        assert "pyproject.toml not found" in captured.err

    def test_returns_zero_when_all_scripts_valid(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 when all scripts follow naming conventions."""
        fs.create_dir("/fake/repo")
        fs.create_file(
            "/fake/repo/.lint.scripts.yaml",
            contents="prefix_rules:\n  scripts.knowledge.: knowledge.\n  scripts.app.: app.",
        )
        fs.create_file(
            "/fake/repo/pyproject.toml",
            contents="""[project.scripts]
"knowledge.extract" = "scripts.knowledge.extract:main"
"app.start" = "scripts.app.start:main"
""",
        )

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_SCRIPTS_CONFIG", Path("/fake/repo/.lint.scripts.yaml")),
        ):
            result = _run_scripts()

        assert result == 0
        captured = capsys.readouterr()
        assert "All script entry points follow naming conventions" in captured.out

    def test_returns_one_when_script_violates_convention(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when a script violates naming convention."""
        fs.create_dir("/fake/repo")
        fs.create_file(
            "/fake/repo/.lint.scripts.yaml",
            contents="prefix_rules:\n  scripts.knowledge.: knowledge.",
        )
        fs.create_file(
            "/fake/repo/pyproject.toml",
            contents="""[project.scripts]
"bad-name" = "scripts.knowledge.module:main"
""",
        )

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_SCRIPTS_CONFIG", Path("/fake/repo/.lint.scripts.yaml")),
        ):
            result = _run_scripts()

        assert result == 1
        captured = capsys.readouterr()
        assert "Script naming convention violations" in captured.err
        assert "bad-name" in captured.err
        assert "knowledge." in captured.err

    def test_detects_multiple_violations(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should detect multiple naming violations."""
        fs.create_dir("/fake/repo")
        fs.create_file(
            "/fake/repo/.lint.scripts.yaml",
            contents="prefix_rules:\n  scripts.knowledge.: knowledge.\n  scripts.app.: app.",
        )
        fs.create_file(
            "/fake/repo/pyproject.toml",
            contents="""[project.scripts]
"wrong-knowledge" = "scripts.knowledge.module:main"
"wrong-app" = "scripts.app.module:main"
"knowledge.correct" = "scripts.knowledge.other:main"
""",
        )

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_SCRIPTS_CONFIG", Path("/fake/repo/.lint.scripts.yaml")),
        ):
            result = _run_scripts()

        assert result == 1
        captured = capsys.readouterr()
        assert "wrong-knowledge" in captured.err
        assert "wrong-app" in captured.err
        assert "knowledge.correct" not in captured.err

    def test_ignores_scripts_without_matching_rules(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should ignore scripts that don't match any prefix rules."""
        fs.create_dir("/fake/repo")
        fs.create_file(
            "/fake/repo/.lint.scripts.yaml",
            contents="prefix_rules:\n  scripts.knowledge.: knowledge.",
        )
        fs.create_file(
            "/fake/repo/pyproject.toml",
            contents="""[project.scripts]
"arbitrary-name" = "some.other.module:main"
"knowledge.valid" = "scripts.knowledge.module:main"
""",
        )

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_SCRIPTS_CONFIG", Path("/fake/repo/.lint.scripts.yaml")),
        ):
            result = _run_scripts()

        assert result == 0

    def test_skips_comments_and_empty_lines(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should skip comments and empty lines in pyproject.toml."""
        fs.create_dir("/fake/repo")
        fs.create_file(
            "/fake/repo/.lint.scripts.yaml",
            contents="prefix_rules:\n  scripts.knowledge.: knowledge.",
        )
        fs.create_file(
            "/fake/repo/pyproject.toml",
            contents="""[project.scripts]
# This is a comment
"knowledge.valid" = "scripts.knowledge.module:main"

# Another comment
""",
        )

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_SCRIPTS_CONFIG", Path("/fake/repo/.lint.scripts.yaml")),
        ):
            result = _run_scripts()

        assert result == 0

    def test_handles_unquoted_script_names(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle unquoted script names in pyproject.toml."""
        fs.create_dir("/fake/repo")
        fs.create_file(
            "/fake/repo/.lint.scripts.yaml",
            contents="prefix_rules:\n  scripts.dev.: dev.",
        )
        fs.create_file(
            "/fake/repo/pyproject.toml",
            contents="""[project.scripts]
setup = "scripts.dev.setup:main"
""",
        )

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_SCRIPTS_CONFIG", Path("/fake/repo/.lint.scripts.yaml")),
        ):
            result = _run_scripts()

        assert result == 1
        captured = capsys.readouterr()
        assert "setup" in captured.err
        assert "dev." in captured.err

    def test_stops_at_next_section(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should stop parsing at next TOML section."""
        fs.create_dir("/fake/repo")
        fs.create_file(
            "/fake/repo/.lint.scripts.yaml",
            contents="prefix_rules:\n  scripts.knowledge.: knowledge.",
        )
        fs.create_file(
            "/fake/repo/pyproject.toml",
            contents="""[project.scripts]
"knowledge.valid" = "scripts.knowledge.module:main"

[tool.other]
bad-entry = "scripts.knowledge.other:main"
""",
        )

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_SCRIPTS_CONFIG", Path("/fake/repo/.lint.scripts.yaml")),
        ):
            result = _run_scripts()

        assert result == 0


class TestLinterConstants:
    """Tests for linter constants."""

    def test_linter_names_defined(self) -> None:
        """Should have all expected linter names."""
        expected = [
            "scripts",
            "markdown-restriction",
            "ruff",
            "mypy",
            "hadolint",
            "pymarkdown",
            "yamllint",
            "actionlint",
            "yamldocs",
            "checkov",
        ]
        assert expected == LINTER_NAMES

    def test_linter_runners_no_key_overlap(self) -> None:
        """Should have no overlapping keys between NO_FILES and WITH_FILES runners."""
        no_files_keys = set(LINTER_RUNNERS_NO_FILES.keys())
        with_files_keys = set(LINTER_RUNNERS_WITH_FILES.keys())
        overlap = no_files_keys & with_files_keys
        assert not overlap, f"Overlapping linter runner keys: {overlap}"

    def test_linter_runners_has_all_linters(self) -> None:
        """Should have runner for each linter name and no orphaned entries."""
        all_runners = {**LINTER_RUNNERS_NO_FILES, **LINTER_RUNNERS_WITH_FILES}
        # Check each linter name has a callable runner
        for name in LINTER_NAMES:
            assert name in all_runners
            assert callable(all_runners[name])
        # Check no orphaned runner entries (keys not in LINTER_NAMES)
        assert set(all_runners.keys()) == set(LINTER_NAMES), (
            f"Orphaned runner keys: {set(all_runners.keys()) - set(LINTER_NAMES)}"
        )

    def test_markdown_restriction_config_path(self) -> None:
        """Should have config path for markdown restriction linter."""
        assert LINT_MARKDOWN_RESTRICTION_CONFIG.name == ".lint.markdown-restriction.yaml"

    def test_markdown_restriction_execution_order(self) -> None:
        """Should have markdown-restriction after scripts and before ruff."""
        scripts_index = LINTER_NAMES.index("scripts")
        md_restriction_index = LINTER_NAMES.index("markdown-restriction")
        ruff_index = LINTER_NAMES.index("ruff")
        assert scripts_index < md_restriction_index < ruff_index

    def test_actionlint_in_with_files_runners(self) -> None:
        """Should have actionlint in LINTER_RUNNERS_WITH_FILES."""
        assert "actionlint" in LINTER_RUNNERS_WITH_FILES
        assert "actionlint" not in LINTER_RUNNERS_NO_FILES

    def test_actionlint_config_path(self) -> None:
        """Should have config path for actionlint linter."""
        assert LINT_ACTIONLINT_CONFIG.name == ".lint.actionlint.yaml"


class TestParseArgs:
    """Tests for _parse_args function."""

    def test_no_args_returns_empty_list(self) -> None:
        """Should return empty linters list when no args provided."""
        with patch("sys.argv", ["lint"]):
            args = _parse_args()
        assert args.linters == []

    def test_single_linter_arg(self) -> None:
        """Should parse single linter argument."""
        with patch("sys.argv", ["lint", "ruff"]):
            args = _parse_args()
        assert args.linters == ["ruff"]

    def test_multiple_linter_args(self) -> None:
        """Should parse multiple linter arguments."""
        with patch("sys.argv", ["lint", "ruff", "mypy", "yamllint"]):
            args = _parse_args()
        assert args.linters == ["ruff", "mypy", "yamllint"]

    def test_invalid_linter_raises_error(self) -> None:
        """Should raise SystemExit for invalid linter name."""
        with patch("sys.argv", ["lint", "invalid_linter"]), pytest.raises(SystemExit):
            _parse_args()


class TestRunRuff:
    """Tests for _run_ruff function."""

    def test_runs_format_and_check(self) -> None:
        """Should run ruff format and ruff check."""
        with (
            patch("shutil.which", return_value="/usr/bin/uv"),
            patch("subprocess.check_call") as mock_check,
        ):
            _run_ruff()

        assert mock_check.call_count == 2
        calls = mock_check.call_args_list
        assert calls[0][0][0] == ["/usr/bin/uv", "run", "ruff", "format", "."]
        assert calls[1][0][0] == ["/usr/bin/uv", "run", "ruff", "check", "--fix", "."]


class TestRunMypy:
    """Tests for _run_mypy function."""

    def test_runs_mypy(self) -> None:
        """Should run mypy."""
        with (
            patch("shutil.which", return_value="/usr/bin/uv"),
            patch("subprocess.check_call") as mock_check,
        ):
            _run_mypy()

        mock_check.assert_called_once_with(["/usr/bin/uv", "run", "mypy"])


class TestRunHadolint:
    """Tests for _run_hadolint function."""

    def test_prints_message_when_no_dockerfiles(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print message when no Dockerfiles found."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/.lint.hadolint.yaml", contents="exclude_dirs: []")

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_HADOLINT_CONFIG", Path("/fake/repo/.lint.hadolint.yaml")),
            patch("shutil.which", return_value="/usr/bin/hadolint"),
        ):
            _run_hadolint()

        captured = capsys.readouterr()
        assert "No Dockerfiles found" in captured.out

    def test_runs_hadolint_on_dockerfiles(self, fs: FakeFilesystem) -> None:
        """Should run hadolint on found Dockerfiles."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine")
        fs.create_file("/fake/repo/.hadolint.yaml", contents="")
        fs.create_file("/fake/repo/.lint.hadolint.yaml", contents="exclude_dirs: []")

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "HADOLINT_CONFIG", Path("/fake/repo/.hadolint.yaml")),
            patch.object(lint, "LINT_HADOLINT_CONFIG", Path("/fake/repo/.lint.hadolint.yaml")),
            patch("shutil.which", return_value="/usr/bin/hadolint"),
            patch("subprocess.check_call") as mock_check,
        ):
            _run_hadolint()

        mock_check.assert_called_once()
        call_args = mock_check.call_args[0][0]
        assert call_args[0] == "/usr/bin/hadolint"
        assert "--config" in call_args

    def test_excludes_directories_from_config(self, fs: FakeFilesystem) -> None:
        """Should exclude directories specified in config."""
        fs.create_dir("/fake/repo")
        fs.create_dir("/fake/repo/excluded")
        fs.create_file("/fake/repo/Dockerfile", contents="FROM alpine")
        fs.create_file("/fake/repo/excluded/Dockerfile", contents="FROM alpine")
        fs.create_file("/fake/repo/.hadolint.yaml", contents="")
        fs.create_file("/fake/repo/.lint.hadolint.yaml", contents="exclude_dirs:\n  - excluded")

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "HADOLINT_CONFIG", Path("/fake/repo/.hadolint.yaml")),
            patch.object(lint, "LINT_HADOLINT_CONFIG", Path("/fake/repo/.lint.hadolint.yaml")),
            patch("shutil.which", return_value="/usr/bin/hadolint"),
            patch("subprocess.check_call") as mock_check,
        ):
            _run_hadolint()

        mock_check.assert_called_once()
        call_args = mock_check.call_args[0][0]
        # Only the root Dockerfile should be included, not the excluded one
        dockerfile_args = [arg for arg in call_args if "Dockerfile" in arg]
        assert len(dockerfile_args) == 1
        assert "excluded" not in dockerfile_args[0]


class TestRunActionlint:
    """Tests for _run_actionlint function."""

    def test_prints_message_when_no_workflows_dir(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print message when .github/workflows/ doesn't exist."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/.lint.actionlint.yaml", contents="ignore: []\nexclude_dirs: []")

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_ACTIONLINT_CONFIG", Path("/fake/repo/.lint.actionlint.yaml")),
            patch("shutil.which", return_value="/usr/bin/actionlint"),
        ):
            _run_actionlint()

        captured = capsys.readouterr()
        assert "No .github/workflows/ directory found" in captured.out

    def test_runs_actionlint_on_workflows(self, fs: FakeFilesystem) -> None:
        """Should run actionlint on workflow files."""
        fs.create_dir("/fake/repo/.github/workflows")
        fs.create_file("/fake/repo/.github/workflows/ci.yml", contents="name: CI")
        fs.create_file("/fake/repo/.lint.actionlint.yaml", contents="ignore: []\nexclude_dirs: []")

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_ACTIONLINT_CONFIG", Path("/fake/repo/.lint.actionlint.yaml")),
            patch("shutil.which", return_value="/usr/bin/actionlint"),
            patch("subprocess.check_call") as mock_check,
        ):
            _run_actionlint()

        mock_check.assert_called_once()
        call_args = mock_check.call_args[0][0]
        assert call_args[0] == "/usr/bin/actionlint"

    def test_applies_ignore_patterns_from_config(self, fs: FakeFilesystem) -> None:
        """Should apply ignore patterns from configuration."""
        fs.create_dir("/fake/repo/.github/workflows")
        fs.create_file("/fake/repo/.github/workflows/ci.yml", contents="name: CI")
        fs.create_file(
            "/fake/repo/.lint.actionlint.yaml",
            contents=(
                "ignore:\n  - 'SC2086:'\n  - 'label \"self-hosted\" is unknown'\nexclude_dirs: []"
            ),
        )

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_ACTIONLINT_CONFIG", Path("/fake/repo/.lint.actionlint.yaml")),
            patch("shutil.which", return_value="/usr/bin/actionlint"),
            patch("subprocess.check_call") as mock_check,
        ):
            _run_actionlint()

        call_args = mock_check.call_args[0][0]
        assert "-ignore" in call_args
        assert "SC2086:" in call_args

    def test_excludes_directories_from_config(self, fs: FakeFilesystem) -> None:
        """Should exclude directories specified in config."""
        fs.create_dir("/fake/repo/.github/workflows")
        fs.create_dir("/fake/repo/.github/workflows/excluded")
        fs.create_file("/fake/repo/.github/workflows/ci.yml", contents="name: CI")
        fs.create_file("/fake/repo/.github/workflows/excluded/test.yml", contents="name: Test")
        fs.create_file(
            "/fake/repo/.lint.actionlint.yaml",
            contents="ignore: []\nexclude_dirs:\n  - .github/workflows/excluded",
        )

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_ACTIONLINT_CONFIG", Path("/fake/repo/.lint.actionlint.yaml")),
            patch("shutil.which", return_value="/usr/bin/actionlint"),
            patch("subprocess.check_call") as mock_check,
        ):
            _run_actionlint()

        mock_check.assert_called_once()
        call_args = mock_check.call_args[0][0]
        # Only ci.yml should be included, not the one in excluded/
        workflow_args = [arg for arg in call_args if arg.endswith(".yml")]
        assert len(workflow_args) == 1
        assert "excluded" not in workflow_args[0]

    def test_filters_workflow_files_when_files_specified(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should filter to only workflow files when files specified."""
        fs.create_dir("/fake/repo/.github/workflows")
        fs.create_file("/fake/repo/.lint.actionlint.yaml", contents="ignore: []\nexclude_dirs: []")

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_ACTIONLINT_CONFIG", Path("/fake/repo/.lint.actionlint.yaml")),
            patch("shutil.which", return_value="/usr/bin/actionlint"),
        ):
            # Pass non-workflow files
            _run_actionlint(files=["src/main.py", "config.yml"])

        captured = capsys.readouterr()
        assert "No GitHub Actions workflow files to check" in captured.out

    def test_propagates_subprocess_error(self, fs: FakeFilesystem) -> None:
        """Should propagate CalledProcessError from subprocess."""
        fs.create_dir("/fake/repo/.github/workflows")
        fs.create_file("/fake/repo/.github/workflows/ci.yml", contents="name: CI")
        fs.create_file("/fake/repo/.lint.actionlint.yaml", contents="ignore: []\nexclude_dirs: []")

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_ACTIONLINT_CONFIG", Path("/fake/repo/.lint.actionlint.yaml")),
            patch("shutil.which", return_value="/usr/bin/actionlint"),
            patch("subprocess.check_call") as mock_check,
        ):
            mock_check.side_effect = subprocess.CalledProcessError(1, ["actionlint"])
            with pytest.raises(subprocess.CalledProcessError):
                _run_actionlint()


class TestRunPymarkdown:
    """Tests for _run_pymarkdown function."""

    def test_runs_pymarkdown(self, fs: FakeFilesystem) -> None:
        """Should run pymarkdown with config and excludes."""
        fs.create_dir("/fake/repo")
        fs.create_file(
            "/fake/repo/.lint.pymarkdown.yaml",
            contents="targets:\n  - README.md\nexcludes:\n  - .venv",
        )

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_PYMARKDOWN_CONFIG", Path("/fake/repo/.lint.pymarkdown.yaml")),
            patch("shutil.which", return_value="/usr/bin/uv"),
            patch("subprocess.check_call") as mock_check,
        ):
            _run_pymarkdown()

        mock_check.assert_called_once()
        call_args = mock_check.call_args[0][0]
        assert "/usr/bin/uv" in call_args
        assert "pymarkdown" in call_args
        assert "-c" in call_args
        assert "README.md" in call_args
        assert "-e" in call_args
        assert ".venv" in call_args


class TestRunYamllint:
    """Tests for _run_yamllint function."""

    def test_runs_yamllint_when_yaml_files_exist(self, fs: FakeFilesystem) -> None:
        """Should run yamllint when YAML files exist."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/config.yml", contents="key: value")
        fs.create_file("/fake/repo/.yamllint.yaml", contents="")
        fs.create_file("/fake/repo/.lint.yamllint.yaml", contents="exclude_dirs: []")

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_YAMLLINT_CONFIG", Path("/fake/repo/.lint.yamllint.yaml")),
            patch("shutil.which", return_value="/usr/bin/uv"),
            patch("subprocess.check_call") as mock_check,
        ):
            _run_yamllint()

        mock_check.assert_called_once()
        call_args = mock_check.call_args[0][0]
        assert "yamllint" in call_args

    def test_skips_when_no_yaml_files(self, fs: FakeFilesystem) -> None:
        """Should not call yamllint when no YAML files exist."""
        fs.create_dir("/fake/repo")

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "_load_yaml_config", return_value={"exclude_dirs": []}),
            patch("shutil.which", return_value="/usr/bin/uv"),
            patch("subprocess.check_call") as mock_check,
        ):
            _run_yamllint()

        mock_check.assert_not_called()

    def test_excludes_directories_from_config(self, fs: FakeFilesystem) -> None:
        """Should exclude directories specified in config."""
        fs.create_dir("/fake/repo")
        fs.create_dir("/fake/repo/excluded")
        fs.create_file("/fake/repo/config.yml", contents="key: value")
        fs.create_file("/fake/repo/excluded/other.yml", contents="key: value")
        fs.create_file("/fake/repo/.yamllint.yaml", contents="")
        fs.create_file("/fake/repo/.lint.yamllint.yaml", contents="exclude_dirs:\n  - excluded")

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_YAMLLINT_CONFIG", Path("/fake/repo/.lint.yamllint.yaml")),
            patch("shutil.which", return_value="/usr/bin/uv"),
            patch("subprocess.check_call") as mock_check,
        ):
            _run_yamllint()

        mock_check.assert_called_once()
        call_args = mock_check.call_args[0][0]
        # Only config.yml should be included, not the one in excluded/
        yaml_file_args = [arg for arg in call_args if arg.endswith(".yml")]
        assert len(yaml_file_args) == 1
        assert "excluded" not in yaml_file_args[0]


class TestRunYamldocs:
    """Tests for _run_yamldocs function."""

    def test_returns_zero_when_no_errors(self, fs: FakeFilesystem) -> None:
        """Should return 0 when no documentation errors found."""
        from scripts.dev import lint_yaml_docs

        fs.create_dir("/fake/repo/docs")
        fs.create_file(
            "/fake/repo/docs/valid.yml",
            contents=(
                "doc_id: test-doc\ntitle: Test\nsections:\n  - id: section-1\n    text: content"
            ),
        )
        fs.create_file(
            "/fake/repo/.lint.yamldocs.yaml",
            contents="targets:\n  - docs/\nexclude_dirs: []",
        )

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint_yaml_docs, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_YAMLDOCS_CONFIG", Path("/fake/repo/.lint.yamldocs.yaml")),
        ):
            result = _run_yamldocs()

        assert result == 0

    def test_returns_one_when_errors_found(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when documentation errors found."""
        from scripts.dev import lint_yaml_docs

        fs.create_dir("/fake/repo/docs")
        # Missing required title
        fs.create_file(
            "/fake/repo/docs/invalid.yml",
            contents="doc_id: test-doc\nsections:\n  - id: section-1",
        )
        fs.create_file(
            "/fake/repo/.lint.yamldocs.yaml",
            contents="targets:\n  - docs/\nexclude_dirs: []",
        )

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint_yaml_docs, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_YAMLDOCS_CONFIG", Path("/fake/repo/.lint.yamldocs.yaml")),
        ):
            result = _run_yamldocs()

        assert result == 1
        captured = capsys.readouterr()
        assert "missing_required_field" in captured.out

    def test_excludes_directories_from_config(self, fs: FakeFilesystem) -> None:
        """Should exclude directories specified in config."""
        from scripts.dev import lint_yaml_docs

        fs.create_dir("/fake/repo/docs")
        fs.create_dir("/fake/repo/docs/excluded")
        fs.create_file(
            "/fake/repo/docs/valid.yml",
            contents="doc_id: test-doc\ntitle: Test\nsections:\n  - id: section-1",
        )
        # Invalid file in excluded dir should be ignored
        fs.create_file(
            "/fake/repo/docs/excluded/invalid.yml",
            contents="doc_id: bad-doc\nsections:\n  - no-id: true",
        )
        fs.create_file(
            "/fake/repo/.lint.yamldocs.yaml",
            contents="targets:\n  - docs/\nexclude_dirs:\n  - excluded",
        )

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint_yaml_docs, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_YAMLDOCS_CONFIG", Path("/fake/repo/.lint.yamldocs.yaml")),
        ):
            result = _run_yamldocs()

        assert result == 0

    def test_skips_nonexistent_targets(self, fs: FakeFilesystem) -> None:
        """Should skip targets that don't exist."""
        fs.create_dir("/fake/repo")
        fs.create_file(
            "/fake/repo/.lint.yamldocs.yaml",
            contents="targets:\n  - nonexistent/\nexclude_dirs: []",
        )

        with (
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "LINT_YAMLDOCS_CONFIG", Path("/fake/repo/.lint.yamldocs.yaml")),
        ):
            result = _run_yamldocs()

        assert result == 0


class TestRunMarkdownRestriction:
    """Tests for _run_markdown_restriction function."""

    def test_returns_zero_when_no_violations(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 0 when no forbidden markdown files found."""
        from pyfakefs.fake_filesystem_unittest import Patcher

        from scripts.dev import lint_markdown_restriction

        with Patcher(modules_to_reload=[lint_markdown_restriction]) as patcher:
            fs = patcher.fs
            assert fs is not None
            fs.create_dir("/fake/repo")
            fs.create_file("/fake/repo/README.md", contents="# README")
            fs.create_file("/fake/repo/AGENTS.md", contents="# AGENTS")
            fs.create_file(
                "/fake/repo/.lint.markdown-restriction.yaml",
                contents=(
                    "restricted_dirs:\n  - .\nallowed_files:\n"
                    "  - README.md\n  - AGENTS.md\nexclude_dirs: []"
                ),
            )

            with (
                patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
                patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")),
                patch.object(
                    lint,
                    "LINT_MARKDOWN_RESTRICTION_CONFIG",
                    Path("/fake/repo/.lint.markdown-restriction.yaml"),
                ),
            ):
                result = _run_markdown_restriction()

            assert result == 0
            captured = capsys.readouterr()
            assert "No forbidden markdown files found" in captured.out

    def test_returns_one_when_violations_found(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 when forbidden markdown files found."""
        from pyfakefs.fake_filesystem_unittest import Patcher

        from scripts.dev import lint_markdown_restriction

        with Patcher(modules_to_reload=[lint_markdown_restriction]) as patcher:
            fs = patcher.fs
            assert fs is not None
            fs.create_dir("/fake/repo")
            fs.create_dir("/fake/repo/docs")
            fs.create_file("/fake/repo/README.md", contents="# README")
            fs.create_file("/fake/repo/docs/guide.md", contents="# Guide")
            fs.create_file(
                "/fake/repo/.lint.markdown-restriction.yaml",
                contents=(
                    "restricted_dirs:\n  - .\n  - docs\nallowed_files:\n"
                    "  - README.md\n  - AGENTS.md\nexclude_dirs: []"
                ),
            )

            with (
                patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
                patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")),
                patch.object(
                    lint,
                    "LINT_MARKDOWN_RESTRICTION_CONFIG",
                    Path("/fake/repo/.lint.markdown-restriction.yaml"),
                ),
            ):
                result = _run_markdown_restriction()

            assert result == 1
            captured = capsys.readouterr()
            assert "forbidden_markdown_file" in captured.err
            assert "docs/guide.md" in captured.err

    def test_excludes_directories_from_config(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should exclude directories specified in config."""
        from pyfakefs.fake_filesystem_unittest import Patcher

        from scripts.dev import lint_markdown_restriction

        with Patcher(modules_to_reload=[lint_markdown_restriction]) as patcher:
            fs = patcher.fs
            assert fs is not None
            fs.create_dir("/fake/repo")
            fs.create_dir("/fake/repo/docs")
            fs.create_dir("/fake/repo/excluded")
            fs.create_file("/fake/repo/README.md", contents="# README")
            fs.create_file("/fake/repo/excluded/guide.md", contents="# Guide")
            fs.create_file(
                "/fake/repo/.lint.markdown-restriction.yaml",
                contents=(
                    "restricted_dirs:\n  - .\n  - excluded\nallowed_files:\n"
                    "  - README.md\n  - AGENTS.md\nexclude_dirs:\n  - excluded"
                ),
            )

            with (
                patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
                patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")),
                patch.object(
                    lint,
                    "LINT_MARKDOWN_RESTRICTION_CONFIG",
                    Path("/fake/repo/.lint.markdown-restriction.yaml"),
                ),
            ):
                result = _run_markdown_restriction()

            assert result == 0


class TestRunCheckov:
    """Tests for _run_checkov function."""

    def test_returns_one_when_schema_missing(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when OpenAPI schema is missing."""
        fs.create_dir("/fake/repo/openapi")

        with patch.object(lint, "OPENAPI_SCHEMA", Path("/fake/repo/openapi/openapi.json")):
            result = _run_checkov()

        assert result == 1
        captured = capsys.readouterr()
        assert "OpenAPI schema missing" in captured.err

    def test_returns_zero_on_success(self, fs: FakeFilesystem) -> None:
        """Should return 0 when checkov runs successfully."""
        fs.create_dir("/fake/repo/openapi")
        fs.create_file("/fake/repo/openapi/openapi.json", contents="{}")
        fs.create_file("/fake/repo/.checkov.yaml", contents="")

        with (
            patch.object(lint, "OPENAPI_SCHEMA", Path("/fake/repo/openapi/openapi.json")),
            patch.object(lint, "CHECKOV_CONFIG", Path("/fake/repo/.checkov.yaml")),
            patch("shutil.which", return_value="/usr/bin/uv"),
            patch("subprocess.check_call"),
        ):
            result = _run_checkov()

        assert result == 0


class TestMain:
    """Tests for main function."""

    def test_returns_one_when_uv_not_found(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 when uv is not found."""
        # Run specifically the ruff linter which requires uv
        with (
            patch("sys.argv", ["lint", "ruff"]),
            patch("shutil.which", return_value=None),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "uv CLI required" in captured.err

    def test_returns_one_when_openapi_missing(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when OpenAPI schema is missing."""
        from scripts.dev import lint_yaml_docs

        # Create minimal repo structure
        fs.create_dir("/fake/repo/openapi")
        fs.create_file(
            "/fake/repo/.lint.scripts.yaml",
            contents="prefix_rules:\n  scripts.knowledge.: knowledge.",
        )
        fs.create_file("/fake/repo/.lint.hadolint.yaml", contents="exclude_dirs: []")
        fs.create_file("/fake/repo/.lint.pymarkdown.yaml", contents="targets: []\nexcludes: []")
        fs.create_file("/fake/repo/.lint.yamllint.yaml", contents="exclude_dirs: []")
        fs.create_file("/fake/repo/.lint.yamldocs.yaml", contents="targets: []\nexclude_dirs: []")
        fs.create_file(
            "/fake/repo/.lint.markdown-restriction.yaml",
            contents="restrictions: []\nexclude_dirs: []",
        )
        fs.create_file("/fake/repo/pyproject.toml", contents="[project.scripts]")

        with (
            patch("sys.argv", ["lint"]),
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint_yaml_docs, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "OPENAPI_SCHEMA", Path("/fake/repo/openapi/openapi.json")),
            patch.object(lint, "LINT_SCRIPTS_CONFIG", Path("/fake/repo/.lint.scripts.yaml")),
            patch.object(lint, "LINT_HADOLINT_CONFIG", Path("/fake/repo/.lint.hadolint.yaml")),
            patch.object(lint, "LINT_PYMARKDOWN_CONFIG", Path("/fake/repo/.lint.pymarkdown.yaml")),
            patch.object(lint, "LINT_YAMLLINT_CONFIG", Path("/fake/repo/.lint.yamllint.yaml")),
            patch.object(lint, "LINT_YAMLDOCS_CONFIG", Path("/fake/repo/.lint.yamldocs.yaml")),
            patch.object(
                lint,
                "LINT_MARKDOWN_RESTRICTION_CONFIG",
                Path("/fake/repo/.lint.markdown-restriction.yaml"),
            ),
            patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}"),
            patch("subprocess.check_call"),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "OpenAPI schema missing" in captured.err

    def test_returns_one_on_subprocess_error(self) -> None:
        """Should return exit code from subprocess error."""
        # Run specifically ruff which uses subprocess.check_call
        with (
            patch("sys.argv", ["lint", "ruff"]),
            patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}"),
            patch("subprocess.check_call") as mock_check,
        ):
            mock_check.side_effect = subprocess.CalledProcessError(42, ["ruff"])
            result = main()

        assert result == 42

    def test_successful_run(self, fs: FakeFilesystem) -> None:
        """Should return 0 on successful run with all checks passing."""
        from scripts.dev import lint_yaml_docs

        # Create minimal repo structure with OpenAPI schema
        fs.create_dir("/fake/repo/openapi")
        fs.create_file("/fake/repo/openapi/openapi.json", contents="{}")
        fs.create_file("/fake/repo/.checkov.yaml", contents="")
        fs.create_file("/fake/repo/.hadolint.yaml", contents="")
        fs.create_file("/fake/repo/.pymarkdown.json", contents="{}")
        fs.create_file("/fake/repo/.yamllint.yaml", contents="")
        fs.create_file(
            "/fake/repo/.lint.scripts.yaml",
            contents="prefix_rules:\n  scripts.knowledge.: knowledge.",
        )
        fs.create_file("/fake/repo/.lint.hadolint.yaml", contents="exclude_dirs: []")
        fs.create_file("/fake/repo/.lint.pymarkdown.yaml", contents="targets: []\nexcludes: []")
        fs.create_file("/fake/repo/.lint.yamllint.yaml", contents="exclude_dirs: []")
        fs.create_file("/fake/repo/.lint.yamldocs.yaml", contents="targets: []\nexclude_dirs: []")
        fs.create_file(
            "/fake/repo/.lint.markdown-restriction.yaml",
            contents="restrictions: []\nexclude_dirs: []",
        )
        fs.create_file("/fake/repo/pyproject.toml", contents="[project.scripts]")

        with (
            patch("sys.argv", ["lint"]),
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint_yaml_docs, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "OPENAPI_SCHEMA", Path("/fake/repo/openapi/openapi.json")),
            patch.object(lint, "CHECKOV_CONFIG", Path("/fake/repo/.checkov.yaml")),
            patch.object(lint, "HADOLINT_CONFIG", Path("/fake/repo/.hadolint.yaml")),
            patch.object(lint, "LINT_SCRIPTS_CONFIG", Path("/fake/repo/.lint.scripts.yaml")),
            patch.object(lint, "LINT_HADOLINT_CONFIG", Path("/fake/repo/.lint.hadolint.yaml")),
            patch.object(lint, "LINT_PYMARKDOWN_CONFIG", Path("/fake/repo/.lint.pymarkdown.yaml")),
            patch.object(lint, "LINT_YAMLLINT_CONFIG", Path("/fake/repo/.lint.yamllint.yaml")),
            patch.object(lint, "LINT_YAMLDOCS_CONFIG", Path("/fake/repo/.lint.yamldocs.yaml")),
            patch.object(
                lint,
                "LINT_MARKDOWN_RESTRICTION_CONFIG",
                Path("/fake/repo/.lint.markdown-restriction.yaml"),
            ),
            patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}"),
            patch("subprocess.check_call"),
        ):
            result = main()

        assert result == 0

    def test_prints_no_dockerfiles_message(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print message when no Dockerfiles found."""
        from scripts.dev import lint_yaml_docs

        fs.create_dir("/fake/repo/openapi")
        fs.create_file("/fake/repo/openapi/openapi.json", contents="{}")
        fs.create_file("/fake/repo/.checkov.yaml", contents="")
        fs.create_file("/fake/repo/.hadolint.yaml", contents="")
        fs.create_file("/fake/repo/.pymarkdown.json", contents="{}")
        fs.create_file("/fake/repo/.yamllint.yaml", contents="")
        fs.create_file(
            "/fake/repo/.lint.scripts.yaml",
            contents="prefix_rules:\n  scripts.knowledge.: knowledge.",
        )
        fs.create_file("/fake/repo/.lint.hadolint.yaml", contents="exclude_dirs: []")
        fs.create_file("/fake/repo/.lint.pymarkdown.yaml", contents="targets: []\nexcludes: []")
        fs.create_file("/fake/repo/.lint.yamllint.yaml", contents="exclude_dirs: []")
        fs.create_file("/fake/repo/.lint.yamldocs.yaml", contents="targets: []\nexclude_dirs: []")
        fs.create_file(
            "/fake/repo/.lint.markdown-restriction.yaml",
            contents="restrictions: []\nexclude_dirs: []",
        )
        fs.create_file("/fake/repo/pyproject.toml", contents="[project.scripts]")

        with (
            patch("sys.argv", ["lint"]),
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint_yaml_docs, "REPO_ROOT", Path("/fake/repo")),
            patch.object(lint, "OPENAPI_SCHEMA", Path("/fake/repo/openapi/openapi.json")),
            patch.object(lint, "CHECKOV_CONFIG", Path("/fake/repo/.checkov.yaml")),
            patch.object(lint, "HADOLINT_CONFIG", Path("/fake/repo/.hadolint.yaml")),
            patch.object(lint, "LINT_SCRIPTS_CONFIG", Path("/fake/repo/.lint.scripts.yaml")),
            patch.object(lint, "LINT_HADOLINT_CONFIG", Path("/fake/repo/.lint.hadolint.yaml")),
            patch.object(lint, "LINT_PYMARKDOWN_CONFIG", Path("/fake/repo/.lint.pymarkdown.yaml")),
            patch.object(lint, "LINT_YAMLLINT_CONFIG", Path("/fake/repo/.lint.yamllint.yaml")),
            patch.object(lint, "LINT_YAMLDOCS_CONFIG", Path("/fake/repo/.lint.yamldocs.yaml")),
            patch.object(
                lint,
                "LINT_MARKDOWN_RESTRICTION_CONFIG",
                Path("/fake/repo/.lint.markdown-restriction.yaml"),
            ),
            patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}"),
            patch("subprocess.check_call"),
        ):
            main()

        captured = capsys.readouterr()
        assert "No Dockerfiles found" in captured.out

    def test_runs_only_specified_linter(self, fs: FakeFilesystem) -> None:
        """Should run only the specified linter when argument provided."""
        fs.create_dir("/fake/repo/openapi")
        fs.create_file("/fake/repo/openapi/openapi.json", contents="{}")

        with (
            patch("sys.argv", ["lint", "ruff"]),
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which", return_value="/usr/bin/uv"),
            patch("subprocess.check_call") as mock_check,
        ):
            result = main()

        assert result == 0
        # ruff runs format and check = 2 calls
        assert mock_check.call_count == 2

    def test_runs_multiple_specified_linters_in_order(self, fs: FakeFilesystem) -> None:
        """Should run multiple specified linters in canonical order."""
        fs.create_dir("/fake/repo/openapi")
        fs.create_file("/fake/repo/openapi/openapi.json", contents="{}")

        with (
            patch("sys.argv", ["lint", "mypy", "ruff"]),
            patch.object(lint, "REPO_ROOT", Path("/fake/repo")),
            patch("shutil.which", return_value="/usr/bin/uv"),
            patch("subprocess.check_call") as mock_check,
        ):
            result = main()

        assert result == 0
        # ruff (2 calls) + mypy (1 call) = 3 calls
        assert mock_check.call_count == 3
        # Verify order: ruff comes before mypy in LINTER_NAMES
        calls = mock_check.call_args_list
        # First two calls should be ruff
        assert "ruff" in str(calls[0])
        assert "ruff" in str(calls[1])
        # Third call should be mypy
        assert "mypy" in str(calls[2])
