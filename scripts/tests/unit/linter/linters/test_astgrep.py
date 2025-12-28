"""Tests for AstgrepLinter.

This module tests the ast-grep structural code linter implementation,
with particular focus on exclude handling in both scan modes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts.dev.linter.linters.astgrep import AstgrepLinter

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


# Standard include paths for ast-grep scanning (glob patterns)
STANDARD_INCLUDES = [
    # Root-level Python files
    "*.py",
    "*.pyi",
    # app/ directory (direct and nested)
    "app/*.py",
    "app/*.pyi",
    "app/**/*.py",
    "app/**/*.pyi",
    # tests/ directory (direct and nested)
    "tests/*.py",
    "tests/*.pyi",
    "tests/**/*.py",
    "tests/**/*.pyi",
    # scripts/ directory (direct and nested)
    "scripts/*.py",
    "scripts/*.pyi",
    "scripts/**/*.py",
    "scripts/**/*.pyi",
]


# --- Test Fixtures ---


@pytest.fixture
def fake_repo(fs: FakeFilesystem) -> Path:
    """Create a fake repository root for testing."""
    repo_root = Path("/fake/repo")
    fs.create_dir(str(repo_root))
    return repo_root


@pytest.fixture
def astgrep_config(fake_repo: Path, fs: FakeFilesystem) -> Path:
    """Create ast-grep configuration files."""
    # Build config content from constants
    includes_yaml = "\n".join(f'  - "{p}"' for p in STANDARD_INCLUDES)
    config_content = f"""included_paths:
{includes_yaml}
"""
    # Create .lint.astgrep.yaml with include patterns
    lint_config = fake_repo / ".lint.astgrep.yaml"
    fs.create_file(str(lint_config), contents=config_content)
    # Create sgconfig.yml (required for ast-grep to run)
    sgconfig = fake_repo / "sgconfig.yml"
    fs.create_file(
        str(sgconfig),
        contents="ruleDirs:\n  - ast-grep-rules\n",
    )
    return lint_config


# --- Test AstgrepLinter ---


class TestAstgrepLinterFailsWithoutConfig:
    """Tests for AstgrepLinter behavior when sgconfig.yml is missing."""

    def test_run_fails_without_sgconfig(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """Should fail when sgconfig.yml not found to prevent silent skip."""
        # No sgconfig.yml created
        with (
            patch("scripts.dev.linter.linters.astgrep.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.astgrep.LINT_ASTGREP_CONFIG",
                fake_repo / ".lint.astgrep.yaml",
            ),
            patch(
                "scripts.dev.linter.linters.astgrep.get_executable",
                return_value="/usr/bin/ast-grep",
            ),
            patch("subprocess.run") as mock_run,
        ):
            linter = AstgrepLinter()
            result = linter.run()

        # Should return failure without calling subprocess
        assert result.success is False
        assert result.message is not None
        assert "sgconfig.yml" in result.message
        mock_run.assert_not_called()


class TestAstgrepLinterValidConfig:
    """Tests for AstgrepLinter with valid configuration."""

    def test_run_with_valid_config(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        astgrep_config: Path,
    ) -> None:
        """Should run ast-grep when sgconfig.yml exists."""
        # Create some Python files
        fs.create_file(str(fake_repo / "main.py"), contents="print('hello')")

        with (
            patch("scripts.dev.linter.linters.astgrep.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.astgrep.LINT_ASTGREP_CONFIG", astgrep_config),
            patch(
                "scripts.dev.linter.linters.astgrep.get_executable",
                return_value="/usr/bin/ast-grep",
            ),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                ),
            ) as mock_run,
        ):
            linter = AstgrepLinter()
            result = linter.run()

        assert result.success is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/bin/ast-grep"
        assert cmd[1] == "scan"

    def test_run_returns_failure_on_nonzero_exit(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        astgrep_config: Path,
    ) -> None:
        """Should return failure when ast-grep exits with non-zero code."""
        fs.create_file(str(fake_repo / "main.py"), contents="print('hello')")

        with (
            patch("scripts.dev.linter.linters.astgrep.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.astgrep.LINT_ASTGREP_CONFIG", astgrep_config),
            patch(
                "scripts.dev.linter.linters.astgrep.get_executable",
                return_value="/usr/bin/ast-grep",
            ),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=1, stdout="error: found issues", stderr=""
                ),
            ) as mock_run,
        ):
            linter = AstgrepLinter()
            result = linter.run()

        assert result.success is False
        assert result.message == "error: found issues"
        mock_run.assert_called_once()

    def test_run_combines_stdout_and_stderr_in_message(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        astgrep_config: Path,
    ) -> None:
        """Should combine stdout and stderr in message for complete diagnostics."""
        fs.create_file(str(fake_repo / "main.py"), contents="print('hello')")

        with (
            patch("scripts.dev.linter.linters.astgrep.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.astgrep.LINT_ASTGREP_CONFIG", astgrep_config),
            patch(
                "scripts.dev.linter.linters.astgrep.get_executable",
                return_value="/usr/bin/ast-grep",
            ),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[],
                    returncode=1,
                    stdout="rule violations found",
                    stderr="warning: deprecated config",
                ),
            ) as mock_run,
        ):
            linter = AstgrepLinter()
            result = linter.run()

        assert result.success is False
        # Both stdout and stderr should be combined in the message
        assert "rule violations found" in result.message
        assert "warning: deprecated config" in result.message
        assert result.message == "rule violations found\nwarning: deprecated config"
        mock_run.assert_called_once()


class TestAstgrepLinterFileFiltering:
    """Tests for file filtering behavior."""

    def test_filters_python_files_only(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        astgrep_config: Path,
    ) -> None:
        """Should only pass Python files (.py and .pyi) to ast-grep in file-filtered mode."""
        # Create various files
        fs.create_file(str(fake_repo / "main.py"), contents="print('hello')")
        fs.create_file(str(fake_repo / "types.pyi"), contents="def foo() -> None: ...")
        fs.create_file(str(fake_repo / "config.yaml"), contents="key: value")
        fs.create_file(str(fake_repo / "readme.md"), contents="# Readme")
        fs.create_file(str(fake_repo / "script.js"), contents="console.log('hi')")

        with (
            patch("scripts.dev.linter.linters.astgrep.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.astgrep.LINT_ASTGREP_CONFIG", astgrep_config),
            patch(
                "scripts.dev.linter.linters.astgrep.get_executable",
                return_value="/usr/bin/ast-grep",
            ),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                ),
            ) as mock_run,
        ):
            linter = AstgrepLinter()
            # Pass mixed files
            result = linter.run(
                files=["main.py", "types.pyi", "config.yaml", "readme.md", "script.js"]
            )

        assert result.success is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        # Only .py and .pyi files should be in command
        assert "main.py" in cmd
        assert "types.pyi" in cmd
        assert "config.yaml" not in cmd
        assert "readme.md" not in cmd
        assert "script.js" not in cmd

    def test_skips_when_no_python_files(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        astgrep_config: Path,
    ) -> None:
        """Should skip gracefully when no Python files are provided."""
        with (
            patch("scripts.dev.linter.linters.astgrep.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.astgrep.LINT_ASTGREP_CONFIG", astgrep_config),
            patch(
                "scripts.dev.linter.linters.astgrep.get_executable",
                return_value="/usr/bin/ast-grep",
            ),
            patch("subprocess.run") as mock_run,
        ):
            linter = AstgrepLinter()
            result = linter.run(files=["config.yaml", "readme.md"])

        # Should return success with message without calling subprocess
        assert result.success is True
        assert result.message == "No Python files to scan with ast-grep"
        mock_run.assert_not_called()


class TestGlobToRegex:
    """Tests for the _glob_to_regex helper function."""

    def test_double_star_slash_regex(self) -> None:
        """Verify **/ is converted to regex matching zero or more directories."""
        from scripts.dev.linter.linters.astgrep import _glob_to_regex

        regex = _glob_to_regex("app/**/*.py")
        # Should match direct children
        assert regex.match("app/test.py") is not None
        # Should match nested files
        assert regex.match("app/sub/test.py") is not None
        assert regex.match("app/a/b/c/test.py") is not None
        # Should NOT match outside app/
        assert regex.match("test.py") is None
        assert regex.match("other/test.py") is None

    def test_special_characters_escaped(self) -> None:
        """Verify special regex characters are properly escaped."""
        from scripts.dev.linter.linters.astgrep import _glob_to_regex

        # Pattern with a dot (common in file extensions)
        regex = _glob_to_regex("*.py")
        assert regex.match("test.py") is not None
        assert regex.match("testXpy") is None  # . should match literal dot only

    def test_caching(self) -> None:
        """Verify the regex is cached for repeated calls."""
        from scripts.dev.linter.linters.astgrep import _glob_to_regex

        # Clear cache first to ensure clean state
        _glob_to_regex.cache_clear()

        pattern = "app/**/*.py"
        regex1 = _glob_to_regex(pattern)
        regex2 = _glob_to_regex(pattern)

        # Should return same cached object
        assert regex1 is regex2
        # Verify cache was hit
        assert _glob_to_regex.cache_info().hits == 1

    def test_bracket_character_class_simple(self) -> None:
        """Verify [abc] matches any single character in the set."""
        from scripts.dev.linter.linters.astgrep import _glob_to_regex

        regex = _glob_to_regex("[CB]at.py")
        assert regex.match("Cat.py") is not None
        assert regex.match("Bat.py") is not None
        assert regex.match("cat.py") is None  # lowercase c not in [CB]
        assert regex.match("Rat.py") is None  # R not in [CB]

    def test_bracket_character_range(self) -> None:
        """Verify [a-z] matches any character in the range."""
        from scripts.dev.linter.linters.astgrep import _glob_to_regex

        regex = _glob_to_regex("app/**/[a-z]*.py")
        # Should match files starting with lowercase letter
        assert regex.match("app/foo.py") is not None
        assert regex.match("app/bar.py") is not None
        assert regex.match("app/sub/test.py") is not None
        # Should NOT match files starting with uppercase or number
        assert regex.match("app/Foo.py") is None
        assert regex.match("app/123.py") is None

    def test_bracket_negation_with_exclamation(self) -> None:
        """Verify [!abc] matches any character NOT in the set."""
        from scripts.dev.linter.linters.astgrep import _glob_to_regex

        regex = _glob_to_regex("[!0-9]*.py")
        # Should match files NOT starting with a digit
        assert regex.match("foo.py") is not None
        assert regex.match("bar.py") is not None
        # Should NOT match files starting with a digit
        assert regex.match("1foo.py") is None
        assert regex.match("9bar.py") is None

    def test_bracket_negation_with_caret(self) -> None:
        """Verify [^abc] also works for negation (common extension)."""
        from scripts.dev.linter.linters.astgrep import _glob_to_regex

        regex = _glob_to_regex("[^A-Z]*.py")
        # Should match files NOT starting with uppercase
        assert regex.match("foo.py") is not None
        # Should NOT match files starting with uppercase
        assert regex.match("Foo.py") is None

    def test_unclosed_bracket_treated_as_literal(self) -> None:
        """Verify unclosed bracket is treated as literal character."""
        from scripts.dev.linter.linters.astgrep import _glob_to_regex

        regex = _glob_to_regex("test[.py")
        # The '[' should be escaped and treated literally
        assert regex.match("test[.py") is not None
        assert regex.match("testa.py") is None

    def test_empty_brackets_treated_as_literal(self) -> None:
        """Verify empty brackets [] are treated as literal characters."""
        from scripts.dev.linter.linters.astgrep import _glob_to_regex

        regex = _glob_to_regex("test[].py")
        # Empty brackets should be escaped
        assert regex.match("test[].py") is not None

    def test_bracket_with_path_pattern(self) -> None:
        """Verify bracket expressions work with full path patterns."""
        from scripts.dev.linter.linters.astgrep import _glob_to_regex

        # Real-world pattern: match lowercase Python files in app/
        regex = _glob_to_regex("app/**/[a-z_]*.py")
        assert regex.match("app/utils.py") is not None
        assert regex.match("app/sub/helper.py") is not None
        assert regex.match("app/_private.py") is not None
        # Should NOT match uppercase starts
        assert regex.match("app/Utils.py") is None


class TestMatchesGlobPattern:
    """Tests for the _matches_glob_pattern helper function."""

    def test_single_star_does_not_match_across_directories(self) -> None:
        """Verify that * in patterns does not match across directory separators.

        This is a critical security/correctness test: patterns like 'app/*/test.py'
        should match 'app/sub/test.py' but NOT 'app/sub/deep/test.py'.
        """
        from scripts.dev.linter.linters.astgrep import _matches_glob_pattern

        # Pattern with single * should only match one directory level
        pattern = "app/*/test.py"

        # Should match: exactly one directory between app/ and test.py
        assert _matches_glob_pattern("app/sub/test.py", pattern) is True

        # Should NOT match: multiple directories between app/ and test.py
        assert _matches_glob_pattern("app/sub/deep/test.py", pattern) is False
        assert _matches_glob_pattern("app/a/b/test.py", pattern) is False
        assert _matches_glob_pattern("app/a/b/c/test.py", pattern) is False

    def test_pattern_enforces_full_path_matching_not_right_match(self) -> None:
        """Verify patterns match from the start of the path, not from the right.

        This prevents "app/*.py" from incorrectly matching "vendor/app/foo.py".
        Path.match() matches from the right, but we need full-path matching.
        """
        from scripts.dev.linter.linters.astgrep import _matches_glob_pattern

        pattern = "app/*.py"

        # Should match: file directly under app/
        assert _matches_glob_pattern("app/foo.py", pattern) is True
        assert _matches_glob_pattern("app/bar.py", pattern) is True

        # Should NOT match: paths that end with app/*.py but have a different prefix
        assert _matches_glob_pattern("vendor/app/foo.py", pattern) is False
        assert _matches_glob_pattern("other/app/bar.py", pattern) is False
        assert _matches_glob_pattern("some/deep/path/app/test.py", pattern) is False

    def test_double_star_matches_zero_or_more_directories(self) -> None:
        """Verify that ** in patterns matches zero or more directories.

        Per standard glob semantics, ** should match zero or more path components,
        so app/**/*.py should match both direct children and nested files.
        """
        from scripts.dev.linter.linters.astgrep import _matches_glob_pattern

        pattern = "app/**/*.py"

        # Should match direct children (** matches zero directories)
        assert _matches_glob_pattern("app/test.py", pattern) is True
        assert _matches_glob_pattern("app/bar.py", pattern) is True

        # Should match nested files (** matches one or more directories)
        assert _matches_glob_pattern("app/sub/test.py", pattern) is True
        assert _matches_glob_pattern("app/foo/bar.py", pattern) is True
        assert _matches_glob_pattern("app/a/b/c/test.py", pattern) is True

        # Should NOT match files outside app/
        assert _matches_glob_pattern("test.py", pattern) is False
        assert _matches_glob_pattern("other/test.py", pattern) is False


class TestAstgrepLinterIncludeHandling:
    """Tests for include pattern handling."""

    def test_file_filtered_scan_only_includes_matching_paths(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        astgrep_config: Path,
    ) -> None:
        """Should only include files that match include patterns in file-filtered mode."""
        # Create files in various locations
        fs.create_file(str(fake_repo / "main.py"), contents="print('hello')")
        fs.create_dir(str(fake_repo / "app"))
        fs.create_file(str(fake_repo / "app" / "service.py"), contents="# service")
        fs.create_dir(str(fake_repo / ".venv" / "lib"))
        fs.create_file(str(fake_repo / ".venv" / "lib" / "module.py"), contents="# venv module")
        fs.create_dir(str(fake_repo / "random_dir"))
        fs.create_file(str(fake_repo / "random_dir" / "code.py"), contents="# random")

        with (
            patch("scripts.dev.linter.linters.astgrep.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.astgrep.LINT_ASTGREP_CONFIG", astgrep_config),
            patch(
                "scripts.dev.linter.linters.astgrep.get_executable",
                return_value="/usr/bin/ast-grep",
            ),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                ),
            ) as mock_run,
        ):
            linter = AstgrepLinter()
            # Pass files - only those matching include patterns should be scanned
            result = linter.run(
                files=[
                    "main.py",  # matches *.py
                    "app/service.py",  # matches app/**/*.py
                    ".venv/lib/module.py",  # does NOT match any include pattern
                    "random_dir/code.py",  # does NOT match any include pattern
                ]
            )

        assert result.success is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        # Only files matching include patterns should be in command
        assert "main.py" in cmd, "main.py matches *.py"
        assert "app/service.py" in cmd, "app/service.py matches app/**/*.py"
        assert not any(".venv" in arg for arg in cmd), "Files in .venv don't match include patterns"
        assert not any("random_dir" in arg for arg in cmd), (
            "Files in random_dir don't match include patterns"
        )

    def test_whole_repo_scan_applies_include_globs(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        astgrep_config: Path,
    ) -> None:
        """Should pass --globs include patterns in whole-repo mode."""
        fs.create_file(str(fake_repo / "main.py"), contents="print('hello')")

        with (
            patch("scripts.dev.linter.linters.astgrep.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.astgrep.LINT_ASTGREP_CONFIG", astgrep_config),
            patch(
                "scripts.dev.linter.linters.astgrep.get_executable",
                return_value="/usr/bin/ast-grep",
            ),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                ),
            ) as mock_run,
        ):
            linter = AstgrepLinter()
            # No files arg means whole-repo scan
            result = linter.run()

        assert result.success is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]

        # Verify include globs are present
        assert "--globs" in cmd, "Should include --globs flags"
        assert "*.py" in cmd, "Should include *.py pattern"
        assert "app/**/*.py" in cmd, "Should include app/**/*.py pattern"
        assert "scripts/**/*.py" in cmd, "Should include scripts/**/*.py pattern"
        # Last argument should be "." for repo root
        assert cmd[-1] == "."

    def test_whole_repo_scan_without_lint_config(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """Should run without errors when .lint.astgrep.yaml is missing."""
        # Create sgconfig.yml but not .lint.astgrep.yaml
        sgconfig = fake_repo / "sgconfig.yml"
        fs.create_file(
            str(sgconfig),
            contents="ruleDirs:\n  - ast-grep-rules\n",
        )
        fs.create_file(str(fake_repo / "main.py"), contents="print('hello')")

        with (
            patch("scripts.dev.linter.linters.astgrep.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.astgrep.LINT_ASTGREP_CONFIG",
                fake_repo / ".lint.astgrep.yaml",  # Does not exist
            ),
            patch(
                "scripts.dev.linter.linters.astgrep.get_executable",
                return_value="/usr/bin/ast-grep",
            ),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                ),
            ) as mock_run,
        ):
            linter = AstgrepLinter()
            result = linter.run()

        assert result.success is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        # Verify essential command structure without being too strict
        assert cmd[0] == "/usr/bin/ast-grep"
        assert cmd[1] == "scan"
        assert cmd[-1] == "."
        # Verify no --globs flags are present when .lint.astgrep.yaml is missing
        assert "--globs" not in cmd

    def test_normalizes_string_included_paths_to_list(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """Should normalize a string included_paths to a single-item list."""
        # Create config with included_paths as a string instead of list
        lint_config = fake_repo / ".lint.astgrep.yaml"
        fs.create_file(str(lint_config), contents='included_paths: "app/**/*.py"\n')
        sgconfig = fake_repo / "sgconfig.yml"
        fs.create_file(
            str(sgconfig),
            contents="ruleDirs:\n  - ast-grep-rules\n",
        )
        fs.create_file(str(fake_repo / "main.py"), contents="print('hello')")

        with (
            patch("scripts.dev.linter.linters.astgrep.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.astgrep.LINT_ASTGREP_CONFIG", lint_config),
            patch(
                "scripts.dev.linter.linters.astgrep.get_executable",
                return_value="/usr/bin/ast-grep",
            ),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                ),
            ) as mock_run,
        ):
            linter = AstgrepLinter()
            result = linter.run()

        assert result.success is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        # Should have exactly one --globs flag with the full pattern (not characters)
        assert cmd.count("--globs") == 1
        # Verify the string wasn't iterated character-by-character
        # (which would add individual characters like 'a', 'p', '*' as globs)
        globs_index = cmd.index("--globs")
        # Only "app/**/*.py" should follow --globs, not individual characters
        assert cmd[globs_index + 1] == "app/**/*.py"

    def test_handles_null_included_paths(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """Should handle null/None included_paths gracefully."""
        # Create config with included_paths explicitly set to null
        lint_config = fake_repo / ".lint.astgrep.yaml"
        fs.create_file(str(lint_config), contents="included_paths: null\n")
        sgconfig = fake_repo / "sgconfig.yml"
        fs.create_file(
            str(sgconfig),
            contents="ruleDirs:\n  - ast-grep-rules\n",
        )
        fs.create_file(str(fake_repo / "main.py"), contents="print('hello')")

        with (
            patch("scripts.dev.linter.linters.astgrep.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.astgrep.LINT_ASTGREP_CONFIG", lint_config),
            patch(
                "scripts.dev.linter.linters.astgrep.get_executable",
                return_value="/usr/bin/ast-grep",
            ),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                ),
            ) as mock_run,
        ):
            linter = AstgrepLinter()
            result = linter.run()

        assert result.success is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        # Should run without --globs flags when included_paths is null
        assert "--globs" not in cmd

    def test_handles_non_list_non_string_included_paths(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """Should handle non-list/non-string included_paths (e.g., True, 1) gracefully."""
        # Create config with included_paths set to boolean (could happen in YAML)
        lint_config = fake_repo / ".lint.astgrep.yaml"
        fs.create_file(str(lint_config), contents="included_paths: true\n")
        sgconfig = fake_repo / "sgconfig.yml"
        fs.create_file(
            str(sgconfig),
            contents="ruleDirs:\n  - ast-grep-rules\n",
        )
        fs.create_file(str(fake_repo / "main.py"), contents="print('hello')")

        with (
            patch("scripts.dev.linter.linters.astgrep.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.astgrep.LINT_ASTGREP_CONFIG", lint_config),
            patch(
                "scripts.dev.linter.linters.astgrep.get_executable",
                return_value="/usr/bin/ast-grep",
            ),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                ),
            ) as mock_run,
        ):
            linter = AstgrepLinter()
            result = linter.run()

        assert result.success is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        # Should run without --globs flags when included_paths is invalid type
        assert "--globs" not in cmd

    def test_filters_non_string_elements_from_included_paths_list(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """Should filter out non-string elements from included_paths list."""
        # Create config with mixed types in included_paths list
        lint_config = fake_repo / ".lint.astgrep.yaml"
        fs.create_file(
            str(lint_config),
            contents='included_paths:\n  - "app/**/*.py"\n  - 123\n  - true\n  - "tests/**/*.py"\n',
        )
        sgconfig = fake_repo / "sgconfig.yml"
        fs.create_file(
            str(sgconfig),
            contents="ruleDirs:\n  - ast-grep-rules\n",
        )
        fs.create_file(str(fake_repo / "main.py"), contents="print('hello')")

        with (
            patch("scripts.dev.linter.linters.astgrep.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.astgrep.LINT_ASTGREP_CONFIG", lint_config),
            patch(
                "scripts.dev.linter.linters.astgrep.get_executable",
                return_value="/usr/bin/ast-grep",
            ),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                ),
            ) as mock_run,
        ):
            linter = AstgrepLinter()
            result = linter.run()

        assert result.success is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        # Should only have the valid string patterns
        assert cmd.count("--globs") == 2
        assert "app/**/*.py" in cmd
        assert "tests/**/*.py" in cmd
        # Should not have the non-string values
        assert "123" not in cmd
        assert "True" not in cmd


class TestAstgrepLinterPatternConsistency:
    """Tests for consistency of include patterns."""

    def test_config_contains_all_include_patterns(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        astgrep_config: Path,
    ) -> None:
        """Verify the config file contains all standard include patterns."""
        # Read the config content we created
        config_content = astgrep_config.read_text()

        # Verify each standard include is present
        for include in STANDARD_INCLUDES:
            assert include in config_content, (
                f"Standard include '{include}' should be in .lint.astgrep.yaml"
            )

    def test_globs_count_matches_include_patterns(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        astgrep_config: Path,
    ) -> None:
        """Verify that globs count matches include pattern count."""
        fs.create_file(str(fake_repo / "main.py"), contents="print('hello')")

        with (
            patch("scripts.dev.linter.linters.astgrep.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.astgrep.LINT_ASTGREP_CONFIG", astgrep_config),
            patch(
                "scripts.dev.linter.linters.astgrep.get_executable",
                return_value="/usr/bin/ast-grep",
            ),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                ),
            ) as mock_run,
        ):
            linter = AstgrepLinter()
            result = linter.run()

        assert result.success is True
        cmd = mock_run.call_args[0][0]

        # Count --globs occurrences
        globs_count = cmd.count("--globs")
        # Should have one --globs per include pattern
        expected_count = len(STANDARD_INCLUDES)
        assert globs_count == expected_count, (
            f"Expected {expected_count} --globs flags, got {globs_count}"
        )


class TestAstgrepLinterLinterProperties:
    """Tests for AstgrepLinter class properties."""

    def test_linter_name(self) -> None:
        """Should have correct name property."""
        linter = AstgrepLinter()
        assert linter.name == "astgrep"

    def test_supports_file_filtering(self) -> None:
        """Should support file filtering."""
        linter = AstgrepLinter()
        assert linter.supports_file_filtering is True


class TestAstgrepLinterTestMethod:
    """Tests for the ast-grep rule test method."""

    def test_test_method_exists(self) -> None:
        """Should have a test method for running rule tests."""
        linter = AstgrepLinter()
        assert hasattr(linter, "test")
        assert callable(linter.test)

    def test_test_fails_without_sgconfig(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """Should fail when sgconfig.yml not found during test."""
        # No sgconfig.yml created
        with (
            patch("scripts.dev.linter.linters.astgrep.REPO_ROOT", fake_repo),
            patch(
                "scripts.dev.linter.linters.astgrep.LINT_ASTGREP_CONFIG",
                fake_repo / ".lint.astgrep.yaml",
            ),
            patch(
                "scripts.dev.linter.linters.astgrep.get_executable",
                return_value="/usr/bin/ast-grep",
            ),
            patch("subprocess.run") as mock_run,
        ):
            linter = AstgrepLinter()
            result = linter.test()

        # Should return failure without calling subprocess
        assert result.success is False
        assert "sgconfig.yml" in result.message
        mock_run.assert_not_called()

    def test_test_runs_ast_grep_test_command(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        astgrep_config: Path,
    ) -> None:
        """Should run 'ast-grep test' command when testing rules."""
        with (
            patch("scripts.dev.linter.linters.astgrep.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.astgrep.LINT_ASTGREP_CONFIG", astgrep_config),
            patch(
                "scripts.dev.linter.linters.astgrep.get_executable",
                return_value="/usr/bin/ast-grep",
            ),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="All tests passed", stderr=""
                ),
            ) as mock_run,
        ):
            linter = AstgrepLinter()
            result = linter.test()

        assert result.success is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/bin/ast-grep"
        assert cmd[1] == "test"

    def test_test_returns_failure_on_nonzero_exit(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        astgrep_config: Path,
    ) -> None:
        """Should return failure when ast-grep test exits with non-zero code."""
        with (
            patch("scripts.dev.linter.linters.astgrep.REPO_ROOT", fake_repo),
            patch("scripts.dev.linter.linters.astgrep.LINT_ASTGREP_CONFIG", astgrep_config),
            patch(
                "scripts.dev.linter.linters.astgrep.get_executable",
                return_value="/usr/bin/ast-grep",
            ),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=1, stdout="", stderr="Test failed"
                ),
            ),
        ):
            linter = AstgrepLinter()
            result = linter.test()

        assert result.success is False
        assert "failed" in result.message
