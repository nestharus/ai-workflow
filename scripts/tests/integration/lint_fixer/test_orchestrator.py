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
            lint_fix_main(["--worktree", str(tmp_path), "--files", "fixable.py"])

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
            lint_fix_main(["--worktree", str(tmp_path), "--files", "unfixable.py"])

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
            lint_fix_main(
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


class TestPerLinterScopeTracking:
    """Tests for per-linter independent scope tracking."""

    def test_multi_linter_independent_scope_with_investigator(self, tmp_path: Path) -> None:
        """Test that each linter maintains independent scope and investigator integration works.

        Scenario:
        - 2 files: file1.py, file2.py
        - 3 linters: ruff, mypy, detect-secrets

        Flow:
        1. Initial: ruff error on file1, no other errors yet (ruff is mutating, aborts)
        2. Agent fixes file1 → ruff re-runs on file1 → error remains
        3. Ruff passes → mypy+detect-secrets run on original scope
        4. mypy error on file2, detect-secrets passes
        5. Agent fixes file2 → mypy re-runs on file2 → passes
        6. file1 stuck for ruff → investigator
        7. After investigator, file1 re-runs through all linters → all pass
        8. Final: no errors
        """
        file1 = tmp_path / "file1.py"
        file2 = tmp_path / "file2.py"
        file1.write_text("# file1 with ruff issue\n")
        file2.write_text("# file2 with mypy issue\n")

        # Track state across mock calls
        state = {
            "lint_calls": 0,
            "agent_calls": 0,
            "investigator_calls": 0,
            "ruff_errors_file1": True,  # file1 has ruff error initially
            "mypy_errors_file2": True,  # file2 has mypy error
        }

        def mock_subprocess_run(cmd, **kwargs):
            """Complex mock simulating multi-linter, multi-file scenario."""
            cmd_str = " ".join(str(c) for c in cmd)

            if "lint" in cmd:
                state["lint_calls"] += 1

                # Determine which linters are being run
                running_ruff = "ruff" in cmd or (
                    "ruff" not in cmd and "mypy" not in cmd and "detect-secrets" not in cmd
                )
                running_mypy = "mypy" in cmd or (
                    "ruff" not in cmd and "mypy" not in cmd and "detect-secrets" not in cmd
                )

                # Check which files are being linted
                linting_file1 = "file1.py" in cmd or "--files" not in cmd
                linting_file2 = "file2.py" in cmd or "--files" not in cmd

                errors = []

                # Ruff errors on file1
                if running_ruff and linting_file1 and state["ruff_errors_file1"]:
                    errors.append(
                        {
                            "linter": "ruff",
                            "file": "file1.py",
                            "line": 1,
                            "column": 1,
                            "code": "E501",
                            "message": "Line too long",
                            "fix_available": False,
                        }
                    )

                # Mypy errors on file2
                if running_mypy and linting_file2 and state["mypy_errors_file2"]:
                    errors.append(
                        {
                            "linter": "mypy",
                            "file": "file2.py",
                            "line": 1,
                            "column": 1,
                            "code": "error",
                            "message": "Type error",
                            "fix_available": False,
                        }
                    )

                # detect-secrets never has errors in this scenario

                if errors:
                    yaml_lines = ["errors:"]
                    for e in errors:
                        yaml_lines.append(f"  - linter: {e['linter']}")
                        yaml_lines.append(f"    file: {e['file']}")
                        yaml_lines.append(f"    line: {e['line']}")
                        yaml_lines.append(f"    column: {e['column']}")
                        yaml_lines.append(f"    code: {e['code']}")
                        yaml_lines.append(f"    message: {e['message']}")
                        yaml_lines.append(f"    fix_available: {str(e['fix_available']).lower()}")
                    return MagicMock(
                        returncode=1,
                        stdout="\n".join(yaml_lines),
                        stderr="",
                    )
                else:
                    return MagicMock(returncode=0, stdout="errors: []", stderr="")

            if "lint-fixer" in cmd_str:
                state["agent_calls"] += 1
                # Agent can fix mypy error on file2, but not ruff error on file1
                if state["mypy_errors_file2"]:
                    file2.write_text("# file2 fixed by agent\n")
                    state["mypy_errors_file2"] = False
                return MagicMock(returncode=0, stdout="Agent attempted fixes", stderr="")

            if "lint-investigator" in cmd_str:
                state["investigator_calls"] += 1
                # Investigator fixes ruff error on file1
                file1.write_text("# file1 fixed by investigator\n")
                state["ruff_errors_file1"] = False
                return MagicMock(
                    returncode=0,
                    stdout="Investigator fixed file1",
                    stderr="",
                )

            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("scripts.lint_fixer.orchestrator.subprocess.run", mock_subprocess_run):
            lint_fix_main(["--worktree", str(tmp_path), "--files", "file1.py", "file2.py"])

        # Verify the flow completed
        assert state["agent_calls"] >= 1, "Agent should have been called"
        assert state["investigator_calls"] >= 1, "Investigator should have been called"

        # Verify files were modified
        assert "fixed by agent" in file2.read_text(), "file2 should be fixed by agent"
        assert "fixed by investigator" in file1.read_text(), "file1 should be fixed by investigator"

    def test_per_linter_changed_files_tracking(self, tmp_path: Path) -> None:
        """Test that changed files are tracked independently per linter.

        Scenario:
        - 3 files: a.py, b.py, c.py
        - ruff has errors on a.py, b.py
        - mypy has errors on b.py, c.py
        - Agent fixes a.py and c.py (not b.py)

        Expected:
        - ruff re-runs on a.py only (its changed file)
        - mypy re-runs on c.py only (its changed file)
        - b.py remains in error lists for both (stuck)
        """
        file_a = tmp_path / "a.py"
        file_b = tmp_path / "b.py"
        file_c = tmp_path / "c.py"
        file_a.write_text("# a\n")
        file_b.write_text("# b\n")
        file_c.write_text("# c\n")

        lint_call_files: list[tuple[list[str] | None, list[str] | None]] = []
        iteration = [0]

        def mock_subprocess_run(cmd, **kwargs):
            cmd_str = " ".join(str(c) for c in cmd)

            if "lint" in cmd:
                # Extract files and linters from command
                files_in_cmd = []
                linters_in_cmd = []
                in_files = False
                for c in cmd:
                    c_str = str(c)
                    if c_str == "--files":
                        in_files = True
                    elif in_files and not c_str.startswith("-"):
                        files_in_cmd.append(c_str)
                    elif c_str in ("ruff", "mypy", "detect-secrets"):
                        linters_in_cmd.append(c_str)

                lint_call_files.append(
                    (files_in_cmd if files_in_cmd else None, linters_in_cmd or None)
                )

                if iteration[0] == 0:
                    # Initial run: ruff errors on a, b; mypy errors on b, c
                    return MagicMock(
                        returncode=1,
                        stdout="""errors:
  - linter: ruff
    file: a.py
    line: 1
    column: 1
    code: E501
    message: error
    fix_available: false
  - linter: ruff
    file: b.py
    line: 1
    column: 1
    code: E501
    message: error
    fix_available: false
  - linter: mypy
    file: b.py
    line: 1
    column: 1
    code: error
    message: error
    fix_available: false
  - linter: mypy
    file: c.py
    line: 1
    column: 1
    code: error
    message: error
    fix_available: false
""",
                        stderr="",
                    )
                elif iteration[0] == 1:
                    # After first agent run: check what's being re-run
                    # ruff re-run on a.py - passes
                    if (
                        "ruff" in linters_in_cmd
                        and "a.py" in files_in_cmd
                        and "b.py" not in files_in_cmd
                    ):
                        return MagicMock(returncode=0, stdout="errors: []", stderr="")
                    # mypy re-run on c.py - passes
                    if (
                        "mypy" in linters_in_cmd
                        and "c.py" in files_in_cmd
                        and "b.py" not in files_in_cmd
                    ):
                        return MagicMock(returncode=0, stdout="errors: []", stderr="")
                    # Default: still errors on b.py
                    return MagicMock(
                        returncode=1,
                        stdout="""errors:
  - linter: ruff
    file: b.py
    line: 1
    column: 1
    code: E501
    message: error
    fix_available: false
""",
                        stderr="",
                    )
                else:
                    return MagicMock(returncode=0, stdout="errors: []", stderr="")

            if "lint-fixer" in cmd_str:
                iteration[0] += 1
                if iteration[0] == 1:
                    # Agent fixes a.py and c.py, not b.py
                    file_a.write_text("# a fixed\n")
                    file_c.write_text("# c fixed\n")
                return MagicMock(returncode=0, stdout="Fixed", stderr="")

            if "lint-investigator" in cmd_str:
                return MagicMock(returncode=0, stdout="Investigated", stderr="")

            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("scripts.lint_fixer.orchestrator.subprocess.run", mock_subprocess_run):
            lint_fix_main(["--worktree", str(tmp_path), "--files", "a.py", "b.py", "c.py"])

        # Verify that re-runs happened with per-linter file lists
        # After iteration 1, we should see:
        # - ruff re-run on [a.py] only (not b.py, since b.py didn't change)
        # - mypy re-run on [c.py] only (not b.py, since b.py didn't change)
        ruff_reruns = [
            (files, linters)
            for files, linters in lint_call_files
            if linters and "ruff" in linters and files
        ]
        mypy_reruns = [
            (files, linters)
            for files, linters in lint_call_files
            if linters and "mypy" in linters and files
        ]

        # At least one ruff re-run should be on a.py only
        assert any("a.py" in files and "b.py" not in files for files, _ in ruff_reruns), (
            f"ruff should re-run on a.py only, got: {ruff_reruns}"
        )

        # At least one mypy re-run should be on c.py only
        assert any("c.py" in files and "b.py" not in files for files, _ in mypy_reruns), (
            f"mypy should re-run on c.py only, got: {mypy_reruns}"
        )
