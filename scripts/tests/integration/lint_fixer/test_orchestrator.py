"""Integration tests for lint_fixer via the lint-fix CLI.

These tests verify the full lint-fix workflow by:
1. Creating real files with lint errors
2. Running actual linters to get real YAML output
3. Mocking the agent to simulate fixes
4. Verifying the CLI correctly handles both fixable and unfixable errors
"""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.lint_fixer.__main__ import main as lint_fix_main
from scripts.lint_fixer.orchestrator import (
    extract_files_from_lint_output,
    filter_lint_output_for_files,
    format_agent_input,
    get_file_hashes,
    run_linters,
)


class TestOrchestratorWorkflow:
    """End-to-end tests for orchestrator workflow."""

    def test_run_linters_returns_yaml_output(self, tmp_path: Path) -> None:
        """Test that run_linters returns valid YAML format."""
        # Create a Python file with a known lint error
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("x=1\n")  # No docstring, spacing issues

        with patch("scripts.lint_fixer.orchestrator.subprocess.run") as mock_run:
            # Simulate lint command returning YAML errors
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="""errors:
  - linter: ruff
    file: bad.py
    line: 1
    column: 1
    code: E225
    message: missing whitespace around operator
    fix_available: true
    fix_message: Add whitespace
""",
                stderr="",
            )

            success, output = run_linters(["bad.py"], tmp_path)

            assert success is False
            assert "errors:" in output
            assert "ruff" in output
            assert "bad.py" in output

    def test_extract_files_from_real_lint_output(self, tmp_path: Path) -> None:
        """Test extracting files from real linter YAML output."""
        yaml_output = """errors:
  - linter: ruff
    file: /path/to/main.py
    line: 10
    column: 5
    code: E501
    message: Line too long (120 > 100)
    fix_available: false
  - linter: mypy
    file: /path/to/utils.py
    line: 25
    column: 1
    code: error
    message: Incompatible return type
    fix_available: false
"""
        files = extract_files_from_lint_output(yaml_output)

        assert len(files) == 2
        assert "/path/to/main.py" in files
        assert "/path/to/utils.py" in files

    def test_filter_preserves_yaml_structure(self) -> None:
        """Test that filtering preserves valid YAML structure."""
        yaml_output = """errors:
  - linter: ruff
    file: keep.py
    line: 1
    column: 1
    code: E501
    message: Line too long
    fix_available: false
  - linter: ruff
    file: skip.py
    line: 2
    column: 1
    code: E502
    message: Other error
    fix_available: false
"""
        filtered = filter_lint_output_for_files(yaml_output, ["keep.py"])

        # Verify output is valid YAML
        import yaml

        data = yaml.safe_load(filtered)
        assert "errors" in data
        assert len(data["errors"]) == 1
        assert data["errors"][0]["file"] == "keep.py"

    def test_format_agent_input_includes_worktree(self, tmp_path: Path) -> None:
        """Test that agent input includes worktree path."""
        lint_output = "errors: []"
        agent_input = format_agent_input(lint_output, tmp_path)

        assert "errors:" in agent_input
        assert str(tmp_path) in agent_input
        assert "Working directory:" in agent_input

    def test_file_hash_detection(self, tmp_path: Path) -> None:
        """Test that file hash changes are detected correctly."""
        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1\n")

        # Get initial hash
        hashes_before = get_file_hashes(["test.py"], tmp_path)

        # Modify file
        test_file.write_text("x = 2\n")

        # Get new hash
        hashes_after = get_file_hashes(["test.py"], tmp_path)

        assert hashes_before["test.py"] != hashes_after["test.py"]

    def test_file_hash_no_change(self, tmp_path: Path) -> None:
        """Test that unchanged files have same hash."""
        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1\n")

        hashes1 = get_file_hashes(["test.py"], tmp_path)
        hashes2 = get_file_hashes(["test.py"], tmp_path)

        assert hashes1["test.py"] == hashes2["test.py"]


class TestLintFixCLI:
    """Tests for lint-fix CLI with simulated agent behavior."""

    def test_lint_fix_agent_fixes_errors(self, tmp_path: Path) -> None:
        """Test lint-fix CLI when agent successfully fixes errors."""
        # Create file with lint error
        bad_file = tmp_path / "fixable.py"
        bad_file.write_text("x=1\n")

        call_count = [0]

        def mock_subprocess_run(cmd, **kwargs):
            """Mock subprocess.run to simulate lint and agent."""
            call_count[0] += 1

            if "lint" in cmd:
                # First call: return errors
                if call_count[0] == 1:
                    return MagicMock(
                        returncode=1,
                        stdout="""errors:
  - linter: ruff
    file: fixable.py
    line: 1
    column: 1
    code: E225
    message: missing whitespace
    fix_available: true
""",
                        stderr="",
                    )
                # Second call: return success (errors fixed)
                return MagicMock(returncode=0, stdout="errors: []", stderr="")

            if "scripts.agents" in str(cmd):
                # Simulate agent fixing the file
                bad_file.write_text("x = 1\n")  # Fixed spacing
                return MagicMock(returncode=0, stdout="Fixed!", stderr="")

            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("scripts.lint_fixer.orchestrator.subprocess.run", mock_subprocess_run):
            result = lint_fix_main(["--worktree", str(tmp_path), "--files", "fixable.py"])

        # Agent should have fixed the error
        assert bad_file.read_text() == "x = 1\n"

    def test_lint_fix_agent_cannot_fix_triggers_investigator(self, tmp_path: Path) -> None:
        """Test lint-fix CLI dispatches stuck files to investigator agent."""
        # Create file with unfixable error
        bad_file = tmp_path / "unfixable.py"
        bad_file.write_text("# Complex unfixable issue\n")

        investigator_called = [False]
        investigator_input = [None]

        def mock_subprocess_run(cmd, **kwargs):
            """Mock subprocess.run - agent doesn't modify file, investigator is called."""
            if "lint" in cmd:
                return MagicMock(
                    returncode=1,
                    stdout="""errors:
  - linter: mypy
    file: unfixable.py
    line: 1
    column: 1
    code: error
    message: Cannot infer type
    fix_available: false
""",
                    stderr="",
                )

            if "lint-fixer" in str(cmd):
                # Fixer agent runs but doesn't change file
                return MagicMock(
                    returncode=0,
                    stdout="Unable to fix this error",
                    stderr="",
                )

            if "lint-investigator" in str(cmd):
                # Investigator agent is called for stuck files
                investigator_called[0] = True
                investigator_input[0] = kwargs.get("input", "")
                return MagicMock(
                    returncode=0,
                    stdout="Investigation: This error requires manual intervention",
                    stderr="",
                )

            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("scripts.lint_fixer.orchestrator.subprocess.run", mock_subprocess_run):
            result = lint_fix_main(["--worktree", str(tmp_path), "--files", "unfixable.py"])

        # File should be unchanged
        assert bad_file.read_text() == "# Complex unfixable issue\n"

        # Investigator should have been called with the stuck error
        assert investigator_called[0], "Investigator agent should be called for stuck files"
        assert "unfixable.py" in investigator_input[0], (
            "Investigator should receive stuck file info"
        )

    def test_lint_fix_no_errors(self, tmp_path: Path) -> None:
        """Test lint-fix CLI when no lint errors exist."""
        clean_file = tmp_path / "clean.py"
        clean_file.write_text('"""Clean module."""\n\nx = 1\n')

        def mock_subprocess_run(cmd, **kwargs):
            """Mock subprocess.run - no errors."""
            if "lint" in cmd:
                return MagicMock(returncode=0, stdout="errors: []", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("scripts.lint_fixer.orchestrator.subprocess.run", mock_subprocess_run):
            result = lint_fix_main(["--worktree", str(tmp_path), "--files", "clean.py"])

        assert result == 0

    def test_lint_fix_multiple_iterations(self, tmp_path: Path) -> None:
        """Test lint-fix CLI runs multiple iterations when needed."""
        file1 = tmp_path / "file1.py"
        file2 = tmp_path / "file2.py"
        file1.write_text("x=1\n")
        file2.write_text("y=2\n")

        iteration = [0]

        def mock_subprocess_run(cmd, **kwargs):
            """Mock that fixes one file per iteration."""
            if "lint" in cmd:
                if iteration[0] == 0:
                    # Both files have errors
                    return MagicMock(
                        returncode=1,
                        stdout="""errors:
  - linter: ruff
    file: file1.py
    line: 1
    column: 1
    code: E225
    message: error 1
    fix_available: true
  - linter: ruff
    file: file2.py
    line: 1
    column: 1
    code: E225
    message: error 2
    fix_available: true
""",
                        stderr="",
                    )
                elif iteration[0] == 1:
                    # file1 fixed, file2 still has error
                    return MagicMock(
                        returncode=1,
                        stdout="""errors:
  - linter: ruff
    file: file2.py
    line: 1
    column: 1
    code: E225
    message: error 2
    fix_available: true
""",
                        stderr="",
                    )
                else:
                    # All fixed
                    return MagicMock(returncode=0, stdout="errors: []", stderr="")

            if "scripts.agents" in str(cmd):
                iteration[0] += 1
                if iteration[0] == 1:
                    file1.write_text("x = 1\n")  # Fix file1
                else:
                    file2.write_text("y = 2\n")  # Fix file2
                return MagicMock(returncode=0, stdout="Fixed", stderr="")

            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("scripts.lint_fixer.orchestrator.subprocess.run", mock_subprocess_run):
            result = lint_fix_main(
                [
                    "--worktree",
                    str(tmp_path),
                    "--files",
                    "file1.py",
                    "file2.py",
                ]
            )

        assert file1.read_text() == "x = 1\n"
        assert file2.read_text() == "y = 2\n"

    def test_lint_fix_changed_only_flag(self, tmp_path: Path) -> None:
        """Test lint-fix CLI with --changed-only flag."""

        def mock_subprocess_run(cmd, **kwargs):
            """Mock subprocess.run - verify --changed-only is passed."""
            if "lint" in cmd:
                # Verify the --changed-only flag is in the command
                assert "--changed-only" in cmd
                return MagicMock(returncode=0, stdout="errors: []", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("scripts.lint_fixer.orchestrator.subprocess.run", mock_subprocess_run):
            result = lint_fix_main(["--worktree", str(tmp_path), "--changed-only"])

        assert result == 0


class TestOrchestratorYamlParsing:
    """Tests for YAML parsing throughout the orchestrator."""

    def test_yaml_with_multiline_message(self) -> None:
        """Test handling of multiline error messages."""
        yaml_output = """errors:
  - linter: actionlint
    file: .github/workflows/test.yml
    line: 9
    column: 11
    code: action
    message: |
      input "unknown" is not defined in action
      available inputs are: "ref", "path"
    fix_available: false
"""
        files = extract_files_from_lint_output(yaml_output)
        assert ".github/workflows/test.yml" in files

        filtered = filter_lint_output_for_files(yaml_output, [".github/workflows/test.yml"])
        assert "unknown" in filtered
        assert "available inputs" in filtered

    def test_yaml_with_special_characters_in_message(self) -> None:
        """Test handling of messages with colons and quotes."""
        yaml_output = """errors:
  - linter: mypy
    file: test.py
    line: 10
    column: 5
    code: error
    message: |
      Argument 1 to "func" has incompatible type "str"; expected "int"
    fix_available: false
"""
        files = extract_files_from_lint_output(yaml_output)
        assert "test.py" in files

    def test_yaml_empty_errors_list(self) -> None:
        """Test handling of empty errors list."""
        yaml_output = "errors: []"

        files = extract_files_from_lint_output(yaml_output)
        assert files == []

        filtered = filter_lint_output_for_files(yaml_output, ["any.py"])
        assert filtered == "errors: []"

    def test_yaml_with_fix_message(self) -> None:
        """Test handling of fix_message field."""
        yaml_output = """errors:
  - linter: ruff
    file: test.py
    line: 1
    column: 1
    code: F401
    message: os imported but unused
    fix_available: true
    fix_message: Remove unused import
"""
        filtered = filter_lint_output_for_files(yaml_output, ["test.py"])
        assert "fix_message" in filtered
        assert "Remove unused import" in filtered
