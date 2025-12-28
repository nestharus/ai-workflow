"""Tests for scripts/dev/linter/linters/actionlint.py - run function branches."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.dev.linter.linters.actionlint import ActionlintLinter


class TestActionlintLinterRun:
    """Tests for ActionlintLinter.run method covering branches."""

    def test_returns_success_when_no_workflow_files_in_file_filter(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test run returns success when filtered files have no workflow files."""
        linter = ActionlintLinter()

        with (
            patch.object(linter, "run", wraps=linter.run),
            patch(
                "scripts.dev.linter.linters.actionlint.get_executable",
                return_value="/usr/bin/actionlint",
            ),
            patch(
                "scripts.dev.linter.linters.actionlint.load_yaml_config",
                return_value={
                    "ignore": [],
                    "included_paths": [".github/workflows/*.yml", ".github/workflows/*.yaml"],
                },
            ),
            patch("scripts.dev.linter.linters.actionlint.REPO_ROOT", tmp_path),
        ):
            # Create workflows dir but pass non-workflow files
            (tmp_path / ".github" / "workflows").mkdir(parents=True)

            result = linter.run(files=["src/main.py", "README.md"])

            assert result.success is True
            captured = capsys.readouterr()
            assert "No GitHub Actions workflow files" in captured.out

    def test_returns_success_when_workflows_dir_not_exists(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test run returns success when no .github/workflows dir."""
        linter = ActionlintLinter()

        with (
            patch(
                "scripts.dev.linter.linters.actionlint.get_executable",
                return_value="/usr/bin/actionlint",
            ),
            patch(
                "scripts.dev.linter.linters.actionlint.load_yaml_config",
                return_value={
                    "ignore": [],
                    "included_paths": [".github/workflows/*.yml", ".github/workflows/*.yaml"],
                },
            ),
            patch("scripts.dev.linter.linters.actionlint.REPO_ROOT", tmp_path),
        ):
            # Don't create .github/workflows directory

            result = linter.run()  # No files specified

            assert result.success is True
            captured = capsys.readouterr()
            assert "No .github/workflows/ directory" in captured.out

    def test_returns_success_when_no_workflow_files_found(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test run returns success when workflows dir exists but is empty."""
        linter = ActionlintLinter()

        with (
            patch(
                "scripts.dev.linter.linters.actionlint.get_executable",
                return_value="/usr/bin/actionlint",
            ),
            patch(
                "scripts.dev.linter.linters.actionlint.load_yaml_config",
                return_value={
                    "ignore": [],
                    "included_paths": [".github/workflows/*.yml", ".github/workflows/*.yaml"],
                },
            ),
            patch("scripts.dev.linter.linters.actionlint.REPO_ROOT", tmp_path),
        ):
            # Create empty workflows directory
            (tmp_path / ".github" / "workflows").mkdir(parents=True)

            result = linter.run()

            assert result.success is True
            captured = capsys.readouterr()
            assert "No workflow files found" in captured.out

    def test_runs_actionlint_with_ignore_patterns(self, tmp_path: Path) -> None:
        """Test run passes ignore patterns to actionlint."""
        linter = ActionlintLinter()

        with (
            patch(
                "scripts.dev.linter.linters.actionlint.get_executable",
                return_value="/usr/bin/actionlint",
            ),
            patch(
                "scripts.dev.linter.linters.actionlint.load_yaml_config",
                return_value={
                    "ignore": ["SC2086", "SC2034"],
                    "included_paths": [".github/workflows/*.yml", ".github/workflows/*.yaml"],
                },
            ),
            patch("scripts.dev.linter.linters.actionlint.REPO_ROOT", tmp_path),
            patch("scripts.dev.linter.linters.actionlint.run_checked") as mock_run,
            patch(
                "scripts.dev.linter.linters.actionlint.is_path_included",
                return_value=True,
            ),
        ):
            # Create workflow file
            workflows_dir = tmp_path / ".github" / "workflows"
            workflows_dir.mkdir(parents=True)
            (workflows_dir / "ci.yml").touch()

            result = linter.run()

            assert result.success is True
            # Check that ignore patterns were passed
            call_args = mock_run.call_args[0][0]
            assert "-ignore" in call_args
            assert "SC2086" in call_args
            assert "SC2034" in call_args

    def test_filters_by_included_paths_in_file_mode(self, tmp_path: Path) -> None:
        """Test run filters files by included_paths patterns."""
        linter = ActionlintLinter()

        with (
            patch(
                "scripts.dev.linter.linters.actionlint.get_executable",
                return_value="/usr/bin/actionlint",
            ),
            patch(
                "scripts.dev.linter.linters.actionlint.load_yaml_config",
                return_value={
                    "ignore": [],
                    "included_paths": [".github/workflows/*.yml", ".github/workflows/*.yaml"],
                },
            ),
            patch("scripts.dev.linter.linters.actionlint.REPO_ROOT", tmp_path),
            patch("scripts.dev.linter.linters.actionlint.run_checked") as mock_run,
            patch(
                "scripts.dev.linter.linters.actionlint.is_path_included",
                return_value=True,
            ),
        ):
            # Create workflow file
            workflows_dir = tmp_path / ".github" / "workflows"
            workflows_dir.mkdir(parents=True)
            (workflows_dir / "ci.yml").touch()

            # Pass a workflow file that matches included_paths
            result = linter.run(files=[".github/workflows/ci.yml"])

            assert result.success is True
            mock_run.assert_called_once()

    def test_scans_yaml_and_yml_files(self, tmp_path: Path) -> None:
        """Test run scans both .yml and .yaml files."""
        linter = ActionlintLinter()

        with (
            patch(
                "scripts.dev.linter.linters.actionlint.get_executable",
                return_value="/usr/bin/actionlint",
            ),
            patch(
                "scripts.dev.linter.linters.actionlint.load_yaml_config",
                return_value={
                    "ignore": [],
                    "included_paths": [".github/workflows/*.yml", ".github/workflows/*.yaml"],
                },
            ),
            patch("scripts.dev.linter.linters.actionlint.REPO_ROOT", tmp_path),
            patch("scripts.dev.linter.linters.actionlint.run_checked") as mock_run,
            patch(
                "scripts.dev.linter.linters.actionlint.is_path_included",
                return_value=True,
            ),
        ):
            # Create workflow files with both extensions
            workflows_dir = tmp_path / ".github" / "workflows"
            workflows_dir.mkdir(parents=True)
            (workflows_dir / "ci.yml").touch()
            (workflows_dir / "deploy.yaml").touch()

            result = linter.run()

            assert result.success is True
            call_args = mock_run.call_args[0][0]
            # Both files should be included
            assert any("ci.yml" in str(arg) for arg in call_args)
            assert any("deploy.yaml" in str(arg) for arg in call_args)

    def test_runs_with_file_filter_for_workflows(self, tmp_path: Path) -> None:
        """Test run works with file filter for workflow files."""
        linter = ActionlintLinter()

        with (
            patch(
                "scripts.dev.linter.linters.actionlint.get_executable",
                return_value="/usr/bin/actionlint",
            ),
            patch(
                "scripts.dev.linter.linters.actionlint.load_yaml_config",
                return_value={
                    "ignore": [],
                    "included_paths": [".github/workflows/*.yml", ".github/workflows/*.yaml"],
                },
            ),
            patch("scripts.dev.linter.linters.actionlint.REPO_ROOT", tmp_path),
            patch("scripts.dev.linter.linters.actionlint.run_checked") as mock_run,
            patch(
                "scripts.dev.linter.linters.actionlint.is_path_included",
                return_value=True,
            ),
        ):
            # Create workflow file
            workflows_dir = tmp_path / ".github" / "workflows"
            workflows_dir.mkdir(parents=True)
            (workflows_dir / "ci.yml").touch()

            result = linter.run(files=[".github/workflows/ci.yml"])

            assert result.success is True
            mock_run.assert_called_once()
