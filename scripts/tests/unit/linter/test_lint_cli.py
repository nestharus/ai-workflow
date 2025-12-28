"""Tests for scripts/dev/linter/lint_cli.py - main function."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from scripts.dev.linter.base import LinterResult


class TestFilterExistingFiles:
    """Tests for _filter_existing_files function."""

    def test_returns_only_files_that_exist(self, tmp_path: Path) -> None:
        """Test filters out files that don't exist."""
        # Create one file, leave others missing
        existing = tmp_path / "exists.py"
        existing.touch()

        from scripts.dev.linter.lint_cli import _filter_existing_files

        with patch("scripts.dev.linter.lint_cli.Path") as mock_path:
            # Configure the mock to check if files exist
            def mock_exists(path: str) -> MagicMock:
                mock = MagicMock()
                mock.exists.return_value = path == "exists.py"
                return mock

            mock_path.side_effect = mock_exists

            result = _filter_existing_files(["exists.py", "missing.py", "also_missing.py"])

        assert result == ["exists.py"]

    def test_returns_empty_when_no_files_exist(self) -> None:
        """Test returns empty list when no files exist."""
        from scripts.dev.linter.lint_cli import _filter_existing_files

        with patch("scripts.dev.linter.lint_cli.Path") as mock_path:
            mock_path.return_value.exists.return_value = False

            result = _filter_existing_files(["missing1.py", "missing2.py"])

        assert result == []

    def test_returns_all_files_when_all_exist(self) -> None:
        """Test returns all files when all exist."""
        from scripts.dev.linter.lint_cli import _filter_existing_files

        with patch("scripts.dev.linter.lint_cli.Path") as mock_path:
            mock_path.return_value.exists.return_value = True

            result = _filter_existing_files(["file1.py", "file2.py"])

        assert result == ["file1.py", "file2.py"]

    def test_returns_empty_for_empty_input(self) -> None:
        """Test returns empty list for empty input."""
        from scripts.dev.linter.lint_cli import _filter_existing_files

        result = _filter_existing_files([])

        assert result == []


class TestGetChangedFiles:
    """Tests for _get_changed_files function."""

    def test_returns_uncommitted_staged_files(self) -> None:
        """Test returns staged files when present."""
        with patch("scripts.dev.linter.lint_cli.subprocess.run") as mock_run:
            # staged returns files, unstaged returns empty
            mock_run.side_effect = [
                MagicMock(stdout="file1.py\nfile2.py", returncode=0),
                MagicMock(stdout="", returncode=0),
            ]

            from scripts.dev.linter.lint_cli import _get_changed_files

            result = _get_changed_files()

            assert result == ["file1.py", "file2.py"]

    def test_returns_uncommitted_unstaged_files(self) -> None:
        """Test returns unstaged files when no staged."""
        with patch("scripts.dev.linter.lint_cli.subprocess.run") as mock_run:
            # staged returns empty, unstaged returns files
            mock_run.side_effect = [
                MagicMock(stdout="", returncode=0),
                MagicMock(stdout="file3.py\nfile4.py", returncode=0),
            ]

            from scripts.dev.linter.lint_cli import _get_changed_files

            result = _get_changed_files()

            assert result == ["file3.py", "file4.py"]

    def test_deduplicates_staged_and_unstaged(self) -> None:
        """Test deduplicates files in both staged and unstaged."""
        with patch("scripts.dev.linter.lint_cli.subprocess.run") as mock_run:
            # same file in both staged and unstaged
            mock_run.side_effect = [
                MagicMock(stdout="common.py\nstaged.py", returncode=0),
                MagicMock(stdout="common.py\nunstaged.py", returncode=0),
            ]

            from scripts.dev.linter.lint_cli import _get_changed_files

            result = _get_changed_files()

            assert result == ["common.py", "staged.py", "unstaged.py"]

    def test_falls_back_to_last_commit(self) -> None:
        """Test falls back to last commit when no uncommitted."""
        with patch("scripts.dev.linter.lint_cli.subprocess.run") as mock_run:
            # no uncommitted changes, last commit has files
            mock_run.side_effect = [
                MagicMock(stdout="", returncode=0),
                MagicMock(stdout="", returncode=0),
                MagicMock(stdout="last_commit.py\nother.py", returncode=0),
            ]

            from scripts.dev.linter.lint_cli import _get_changed_files

            result = _get_changed_files()

            assert result == ["last_commit.py", "other.py"]

    def test_returns_empty_when_no_changes(self) -> None:
        """Test returns empty list when no changes anywhere."""
        with patch("scripts.dev.linter.lint_cli.subprocess.run") as mock_run:
            # no changes anywhere
            mock_run.side_effect = [
                MagicMock(stdout="", returncode=0),
                MagicMock(stdout="", returncode=0),
                MagicMock(stdout="", returncode=0),
            ]

            from scripts.dev.linter.lint_cli import _get_changed_files

            result = _get_changed_files()

            assert result == []

    def test_returns_empty_on_git_error(self) -> None:
        """Test returns empty list when git fails."""
        with patch("scripts.dev.linter.lint_cli.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "git")

            from scripts.dev.linter.lint_cli import _get_changed_files

            result = _get_changed_files()

            assert result == []

    def test_returns_files_from_specific_commit(self) -> None:
        """Test returns files from a specific commit when commit is provided."""
        with patch("scripts.dev.linter.lint_cli.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="commit_file.py\nother.py", returncode=0)

            from scripts.dev.linter.lint_cli import _get_changed_files

            result = _get_changed_files(commit="abc123")

            assert result == ["commit_file.py", "other.py"]
            mock_run.assert_called_once_with(
                ["git", "diff", "--name-only", "--diff-filter=ACMRTUX", "abc123~1..abc123"],
                capture_output=True,
                text=True,
                check=True,
            )

    def test_returns_empty_when_commit_has_no_files(self) -> None:
        """Test returns empty list when specified commit has no files."""
        with patch("scripts.dev.linter.lint_cli.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)

            from scripts.dev.linter.lint_cli import _get_changed_files

            result = _get_changed_files(commit="abc123")

            assert result == []


class TestExpandLinterSpec:
    """Tests for _expand_linter_spec function."""

    def test_returns_single_linter_without_operator(self) -> None:
        """Test returns single linter when no operator provided."""
        with patch(
            "scripts.dev.linter.lint_cli.LINTER_NAMES",
            ["scripts", "ruff", "mypy", "yamllint"],
        ):
            from scripts.dev.linter.lint_cli import _expand_linter_spec

            result = _expand_linter_spec("ruff")

            assert result == ["ruff"]

    def test_greater_than_or_equal_returns_linter_and_after(self) -> None:
        """Test >= operator returns specified linter and all after it."""
        with patch(
            "scripts.dev.linter.lint_cli.LINTER_NAMES",
            ["scripts", "ruff", "mypy", "yamllint"],
        ):
            from scripts.dev.linter.lint_cli import _expand_linter_spec

            result = _expand_linter_spec(">=mypy")

            assert result == ["mypy", "yamllint"]

    def test_greater_than_returns_linters_after(self) -> None:
        """Test > operator returns only linters after specified one."""
        with patch(
            "scripts.dev.linter.lint_cli.LINTER_NAMES",
            ["scripts", "ruff", "mypy", "yamllint"],
        ):
            from scripts.dev.linter.lint_cli import _expand_linter_spec

            result = _expand_linter_spec(">ruff")

            assert result == ["mypy", "yamllint"]

    def test_less_than_or_equal_returns_linter_and_before(self) -> None:
        """Test <= operator returns linters up to and including specified one."""
        with patch(
            "scripts.dev.linter.lint_cli.LINTER_NAMES",
            ["scripts", "ruff", "mypy", "yamllint"],
        ):
            from scripts.dev.linter.lint_cli import _expand_linter_spec

            result = _expand_linter_spec("<=mypy")

            assert result == ["scripts", "ruff", "mypy"]

    def test_less_than_returns_linters_before(self) -> None:
        """Test < operator returns only linters before specified one."""
        with patch(
            "scripts.dev.linter.lint_cli.LINTER_NAMES",
            ["scripts", "ruff", "mypy", "yamllint"],
        ):
            from scripts.dev.linter.lint_cli import _expand_linter_spec

            result = _expand_linter_spec("<mypy")

            assert result == ["scripts", "ruff"]

    def test_returns_none_for_invalid_linter(self) -> None:
        """Test returns None when linter name is invalid."""
        with patch(
            "scripts.dev.linter.lint_cli.LINTER_NAMES",
            ["scripts", "ruff", "mypy"],
        ):
            from scripts.dev.linter.lint_cli import _expand_linter_spec

            result = _expand_linter_spec("invalid")

            assert result is None

    def test_returns_none_for_invalid_linter_with_operator(self) -> None:
        """Test returns None when linter name with operator is invalid."""
        with patch(
            "scripts.dev.linter.lint_cli.LINTER_NAMES",
            ["scripts", "ruff", "mypy"],
        ):
            from scripts.dev.linter.lint_cli import _expand_linter_spec

            result = _expand_linter_spec(">=invalid")

            assert result is None

    def test_greater_than_last_linter_returns_empty(self) -> None:
        """Test > on last linter returns empty list."""
        with patch(
            "scripts.dev.linter.lint_cli.LINTER_NAMES",
            ["scripts", "ruff", "mypy"],
        ):
            from scripts.dev.linter.lint_cli import _expand_linter_spec

            result = _expand_linter_spec(">mypy")

            assert result == []

    def test_less_than_first_linter_returns_empty(self) -> None:
        """Test < on first linter returns empty list."""
        with patch(
            "scripts.dev.linter.lint_cli.LINTER_NAMES",
            ["scripts", "ruff", "mypy"],
        ):
            from scripts.dev.linter.lint_cli import _expand_linter_spec

            result = _expand_linter_spec("<scripts")

            assert result == []


class TestLintCliMain:
    """Tests for main function covering lines 35-91."""

    def test_main_runs_all_linters_by_default(self) -> None:
        """Test main runs all linters when none specified (lines 41-44)."""
        mock_linter = MagicMock()
        mock_linter.name = "test_linter"
        mock_linter.supports_file_filtering = False
        mock_linter.run.return_value = LinterResult(success=True)

        with (
            patch("scripts.dev.linter.lint_cli._parse_args") as mock_args,
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", ["test_linter"]),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", {"test_linter": mock_linter}),
        ):
            mock_args.return_value = MagicMock(
                linters=[], files=None, changed_only=False, commit=None
            )

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 0
            mock_linter.run.assert_called_once()

    def test_main_runs_specified_linters(self) -> None:
        """Test main runs only specified linters (lines 41-42)."""
        mock_linter1 = MagicMock()
        mock_linter1.name = "linter1"
        mock_linter1.supports_file_filtering = False
        mock_linter1.run.return_value = LinterResult(success=True)

        mock_linter2 = MagicMock()
        mock_linter2.name = "linter2"
        mock_linter2.supports_file_filtering = False
        mock_linter2.run.return_value = LinterResult(success=True)

        with (
            patch("scripts.dev.linter.lint_cli._parse_args") as mock_args,
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", ["linter1", "linter2"]),
            patch(
                "scripts.dev.linter.lint_cli.LINTER_MAP",
                {"linter1": mock_linter1, "linter2": mock_linter2},
            ),
        ):
            mock_args.return_value = MagicMock(
                linters=["linter1"], files=None, changed_only=False, commit=None
            )

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 0
            mock_linter1.run.assert_called_once()
            mock_linter2.run.assert_not_called()

    def test_main_with_files_warns_when_no_filtering_support(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main warns when --files used with non-filtering linters (lines 48-60)."""
        mock_linter = MagicMock()
        mock_linter.name = "no_filter"
        mock_linter.supports_file_filtering = False
        mock_linter.run.return_value = LinterResult(success=True)

        with (
            patch("scripts.dev.linter.lint_cli._parse_args") as mock_args,
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", ["no_filter"]),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", {"no_filter": mock_linter}),
            patch(
                "scripts.dev.linter.lint_cli._filter_existing_files",
                side_effect=lambda x: x,
            ),
        ):
            mock_args.return_value = MagicMock(
                linters=["no_filter"], files=["file.py"], changed_only=False, commit=None
            )

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 0
            captured = capsys.readouterr()
            assert "Warning" in captured.err
            assert "file-filtering" in captured.err

    def test_main_runs_linter_with_file_filtering(self) -> None:
        """Test main passes files to linter that supports filtering (line 74)."""
        mock_linter = MagicMock()
        mock_linter.name = "with_filter"
        mock_linter.supports_file_filtering = True
        mock_linter.run.return_value = LinterResult(success=True)

        with (
            patch("scripts.dev.linter.lint_cli._parse_args") as mock_args,
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", ["with_filter"]),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", {"with_filter": mock_linter}),
            patch(
                "scripts.dev.linter.lint_cli._filter_existing_files",
                side_effect=lambda x: x,
            ),
        ):
            mock_args.return_value = MagicMock(
                linters=["with_filter"], files=["file.py"], changed_only=False, commit=None
            )

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 0
            mock_linter.run.assert_called_once_with(["file.py"])

    def test_main_returns_one_on_linter_failure(self) -> None:
        """Test main returns 1 when linter fails (lines 76-77)."""
        mock_linter = MagicMock()
        mock_linter.name = "failing"
        mock_linter.supports_file_filtering = False
        mock_linter.run.return_value = LinterResult(success=False)

        with (
            patch("scripts.dev.linter.lint_cli._parse_args") as mock_args,
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", ["failing"]),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", {"failing": mock_linter}),
        ):
            mock_args.return_value = MagicMock(
                linters=[], files=None, changed_only=False, commit=None
            )

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 1

    def test_main_returns_one_for_unknown_linter(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main returns 1 for unknown linter (lines 68-71)."""
        with (
            patch("scripts.dev.linter.lint_cli._parse_args") as mock_args,
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", ["known"]),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", {}),  # Empty map
        ):
            mock_args.return_value = MagicMock(
                linters=["known"], files=None, changed_only=False, commit=None
            )

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 1
            captured = capsys.readouterr()
            assert "Unknown linter" in captured.err

    def test_main_handles_runtime_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main returns 1 on RuntimeError (lines 79-81)."""
        mock_linter = MagicMock()
        mock_linter.name = "error_linter"
        mock_linter.supports_file_filtering = False
        mock_linter.run.side_effect = RuntimeError("Linter executable not found")

        with (
            patch("scripts.dev.linter.lint_cli._parse_args") as mock_args,
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", ["error_linter"]),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", {"error_linter": mock_linter}),
        ):
            mock_args.return_value = MagicMock(
                linters=[], files=None, changed_only=False, commit=None
            )

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 1
            captured = capsys.readouterr()
            assert "Linter executable not found" in captured.err

    def test_main_handles_called_process_error(self) -> None:
        """Test main returns exit code from CalledProcessError (lines 82-83)."""
        mock_linter = MagicMock()
        mock_linter.name = "proc_error"
        mock_linter.supports_file_filtering = False
        mock_linter.run.side_effect = subprocess.CalledProcessError(2, "linter cmd")

        with (
            patch("scripts.dev.linter.lint_cli._parse_args") as mock_args,
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", ["proc_error"]),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", {"proc_error": mock_linter}),
        ):
            mock_args.return_value = MagicMock(
                linters=[], files=None, changed_only=False, commit=None
            )

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 2

    def test_main_handles_os_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main returns 1 on OSError (lines 84-86)."""
        mock_linter = MagicMock()
        mock_linter.name = "os_error"
        mock_linter.supports_file_filtering = False
        mock_linter.run.side_effect = OSError("Permission denied")

        with (
            patch("scripts.dev.linter.lint_cli._parse_args") as mock_args,
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", ["os_error"]),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", {"os_error": mock_linter}),
        ):
            mock_args.return_value = MagicMock(
                linters=[], files=None, changed_only=False, commit=None
            )

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 1
            captured = capsys.readouterr()
            assert "OS error" in captured.err

    def test_main_handles_yaml_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main returns 1 on YAMLError (lines 87-89)."""
        mock_linter = MagicMock()
        mock_linter.name = "yaml_error"
        mock_linter.supports_file_filtering = False
        mock_linter.run.side_effect = yaml.YAMLError("Invalid YAML")

        with (
            patch("scripts.dev.linter.lint_cli._parse_args") as mock_args,
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", ["yaml_error"]),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", {"yaml_error": mock_linter}),
        ):
            mock_args.return_value = MagicMock(
                linters=[], files=None, changed_only=False, commit=None
            )

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 1
            captured = capsys.readouterr()
            assert "YAML configuration error" in captured.err

    def test_main_errors_when_multiple_file_options_specified(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main returns 1 when multiple file options used."""
        with patch("scripts.dev.linter.lint_cli._parse_args") as mock_args:
            mock_args.return_value = MagicMock(
                linters=[],
                files=["file.py"],
                changed_only=True,
                commit=None,
            )

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 1
            captured = capsys.readouterr()
            assert "mutually exclusive" in captured.err

    def test_main_returns_zero_when_no_changed_files(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main returns 0 early when no changed files."""
        with (
            patch("scripts.dev.linter.lint_cli._parse_args") as mock_args,
            patch("scripts.dev.linter.lint_cli._get_changed_files", return_value=[]),
        ):
            mock_args.return_value = MagicMock(
                linters=[],
                files=None,
                changed_only=True,
                commit=None,
            )

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 0
            captured = capsys.readouterr()
            assert "No changed files to lint" in captured.out

    def test_main_prints_changed_files_before_linting(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main prints list of changed files."""
        mock_linter = MagicMock()
        mock_linter.name = "test_linter"
        mock_linter.supports_file_filtering = True
        mock_linter.run.return_value = LinterResult(success=True)

        with (
            patch("scripts.dev.linter.lint_cli._parse_args") as mock_args,
            patch(
                "scripts.dev.linter.lint_cli._get_changed_files",
                return_value=["file1.py", "file2.py"],
            ),
            patch(
                "scripts.dev.linter.lint_cli._filter_existing_files",
                side_effect=lambda x: x,
            ),
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", ["test_linter"]),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", {"test_linter": mock_linter}),
        ):
            mock_args.return_value = MagicMock(
                linters=[],
                files=None,
                changed_only=True,
                commit=None,
            )

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 0
            captured = capsys.readouterr()
            assert "Linting 2 changed file(s)" in captured.out
            assert "file1.py" in captured.out
            assert "file2.py" in captured.out
            mock_linter.run.assert_called_once_with(["file1.py", "file2.py"])

    def test_main_passes_changed_files_to_linter(self) -> None:
        """Test main passes changed files to linter run method."""
        mock_linter = MagicMock()
        mock_linter.name = "test_linter"
        mock_linter.supports_file_filtering = True
        mock_linter.run.return_value = LinterResult(success=True)

        with (
            patch("scripts.dev.linter.lint_cli._parse_args") as mock_args,
            patch(
                "scripts.dev.linter.lint_cli._get_changed_files",
                return_value=["changed.py"],
            ),
            patch(
                "scripts.dev.linter.lint_cli._filter_existing_files",
                side_effect=lambda x: x,
            ),
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", ["test_linter"]),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", {"test_linter": mock_linter}),
        ):
            mock_args.return_value = MagicMock(
                linters=[],
                files=None,
                changed_only=True,
                commit=None,
            )

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 0
            mock_linter.run.assert_called_once_with(["changed.py"])

    def test_main_with_commit_flag_gets_files_from_commit(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main with --commit flag gets files from specific commit."""
        mock_linter = MagicMock()
        mock_linter.name = "test_linter"
        mock_linter.supports_file_filtering = True
        mock_linter.run.return_value = LinterResult(success=True)

        with (
            patch("scripts.dev.linter.lint_cli._parse_args") as mock_args,
            patch(
                "scripts.dev.linter.lint_cli._get_changed_files",
                return_value=["commit_file.py"],
            ) as mock_get_files,
            patch(
                "scripts.dev.linter.lint_cli._filter_existing_files",
                side_effect=lambda x: x,
            ),
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", ["test_linter"]),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", {"test_linter": mock_linter}),
        ):
            mock_args.return_value = MagicMock(
                linters=[],
                files=None,
                changed_only=False,
                commit="abc123",
            )

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 0
            mock_get_files.assert_called_once_with("abc123")
            captured = capsys.readouterr()
            assert "from commit abc123" in captured.out
            mock_linter.run.assert_called_once_with(["commit_file.py"])

    def test_main_returns_zero_when_commit_has_no_files(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main returns 0 when specified commit has no files."""
        with (
            patch("scripts.dev.linter.lint_cli._parse_args") as mock_args,
            patch("scripts.dev.linter.lint_cli._get_changed_files", return_value=[]),
        ):
            mock_args.return_value = MagicMock(
                linters=[],
                files=None,
                changed_only=False,
                commit="abc123",
            )

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 0
            captured = capsys.readouterr()
            assert "No files changed in commit abc123" in captured.out

    def test_main_returns_zero_when_no_specified_files_exist(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main returns 0 when --files specified but none exist."""
        with (
            patch("scripts.dev.linter.lint_cli._parse_args") as mock_args,
            patch(
                "scripts.dev.linter.lint_cli._filter_existing_files",
                return_value=[],
            ),
        ):
            mock_args.return_value = MagicMock(
                linters=[],
                files=["nonexistent.py", "also_missing.py"],
                changed_only=False,
                commit=None,
            )

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 0
            captured = capsys.readouterr()
            assert "No specified files exist" in captured.out

    def test_main_expands_linter_range_operator(self) -> None:
        """Test main expands linter range operators like >=ruff."""
        mock_linter1 = MagicMock()
        mock_linter1.name = "ruff"
        mock_linter1.supports_file_filtering = False
        mock_linter1.run.return_value = LinterResult(success=True)

        mock_linter2 = MagicMock()
        mock_linter2.name = "mypy"
        mock_linter2.supports_file_filtering = False
        mock_linter2.run.return_value = LinterResult(success=True)

        with (
            patch("scripts.dev.linter.lint_cli._parse_args") as mock_args,
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", ["scripts", "ruff", "mypy"]),
            patch(
                "scripts.dev.linter.lint_cli.LINTER_MAP",
                {"scripts": MagicMock(), "ruff": mock_linter1, "mypy": mock_linter2},
            ),
        ):
            mock_args.return_value = MagicMock(
                linters=[">=ruff"],
                files=None,
                changed_only=False,
                commit=None,
            )

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 0
            mock_linter1.run.assert_called_once()
            mock_linter2.run.assert_called_once()

    def test_main_errors_on_invalid_linter_spec(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main returns 1 for invalid linter specification."""
        with (
            patch("scripts.dev.linter.lint_cli._parse_args") as mock_args,
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", ["ruff", "mypy"]),
        ):
            mock_args.return_value = MagicMock(
                linters=[">=invalid"],
                files=None,
                changed_only=False,
                commit=None,
            )

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 1
            captured = capsys.readouterr()
            assert "Invalid linter specification" in captured.err
