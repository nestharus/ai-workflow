"""Tests for scripts/dev/linter/lint_cli.py - main function."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest
import yaml

from scripts.dev.linter.base import LinterResult


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
            mock_args.return_value = MagicMock(linters=[], files=None)

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
            mock_args.return_value = MagicMock(linters=["linter1"], files=None)

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
        ):
            mock_args.return_value = MagicMock(linters=["no_filter"], files=["file.py"])

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
        ):
            mock_args.return_value = MagicMock(linters=["with_filter"], files=["file.py"])

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
            mock_args.return_value = MagicMock(linters=[], files=None)

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
            mock_args.return_value = MagicMock(linters=["known"], files=None)

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
            mock_args.return_value = MagicMock(linters=[], files=None)

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
            mock_args.return_value = MagicMock(linters=[], files=None)

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
            mock_args.return_value = MagicMock(linters=[], files=None)

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
            mock_args.return_value = MagicMock(linters=[], files=None)

            from scripts.dev.linter.lint_cli import main

            result = main()

            assert result == 1
            captured = capsys.readouterr()
            assert "YAML configuration error" in captured.err
