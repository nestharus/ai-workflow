"""Tests for LanguageTool linter configuration patterns.

This module tests that the include/exclude configuration behaviors for the
LanguageTool linter work correctly. It validates that configuration patterns
are properly applied and that the dictionary filtering works as expected.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


# --- Test Fixtures ---


@pytest.fixture
def fake_repo(fs: FakeFilesystem) -> Path:
    """Create a fake repository root for testing."""
    repo_root = Path("/fake/repo")
    fs.create_dir(str(repo_root))
    return repo_root


@pytest.fixture
def languagetool_config(fake_repo: Path, fs: FakeFilesystem) -> Path:
    """Create LanguageTool configuration file."""
    config = fake_repo / ".lint.languagetool.yaml"
    fs.create_file(
        str(config),
        contents=(
            "language: en-US\n"
            "use_public_api: true\n"
            "include_paths:\n"
            "  - README.md\n"
            "  - AGENTS.md\n"
            "  - docs/**/*.md\n"
            "  - '!.tmp/**'\n"
            "  - '!.worktrees/**'\n"
            "disabled_categories:\n"
            "  - TYPOGRAPHY\n"
            "disabled_rules:\n"
            "  - UPPERCASE_SENTENCE_START\n"
            "dictionary:\n"
            "  - pymarkdown\n"
            "  - yamllint\n"
        ),
    )
    return config


def create_mock_match(
    rule_issue_type: str = "grammar",
    matched_text: str = "test",
    category: str = "GRAMMAR",
    rule_id: str = "TEST_RULE",
    message: str = "Test message",
    context: str = "...test context...",
    offset: int = 0,
    replacements: list[str] | None = None,
) -> MagicMock:
    """Create a mock LanguageTool Match object."""
    match = MagicMock()
    match.rule_issue_type = rule_issue_type
    match.matched_text = matched_text
    match.category = category
    match.rule_id = rule_id
    match.message = message
    match.context = context
    match.offset = offset
    match.replacements = replacements or []
    return match


# --- LanguageToolLinter Tests ---


class TestLanguageToolLinter:
    """Tests for LanguageToolLinter configuration patterns."""

    def test_excludes_tmp_directory(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        languagetool_config: Path,
    ) -> None:
        """Should exclude files in .tmp directory."""
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Create test files
        fs.create_file(str(fake_repo / "README.md"), contents="# Test README")
        fs.create_dir(str(fake_repo / ".tmp"))
        fs.create_file(
            str(fake_repo / ".tmp" / "excluded.md"),
            contents="# Excluded file",
        )

        mock_tool = MagicMock()
        mock_tool.check.return_value = []

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                languagetool_config,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            # Run with a mix of included and excluded files
            result = linter.run(files=["README.md", ".tmp/excluded.md"])

        # Verify result is successful
        assert result.success is True

        # Check that the mock was only called for README.md, not for .tmp/excluded.md
        # Since .tmp is excluded, only one file should be checked
        assert mock_tool.check.call_count == 1

    def test_excludes_worktrees_directory(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        languagetool_config: Path,
    ) -> None:
        """Should exclude files in .worktrees directory."""
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Create test files
        fs.create_file(str(fake_repo / "README.md"), contents="# Test README")
        fs.create_dir(str(fake_repo / ".worktrees" / "branch"))
        fs.create_file(
            str(fake_repo / ".worktrees" / "branch" / "README.md"),
            contents="# Worktree README",
        )

        mock_tool = MagicMock()
        mock_tool.check.return_value = []

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                languagetool_config,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            result = linter.run(files=["README.md", ".worktrees/branch/README.md"])

        assert result.success is True
        # Only README.md should be checked, not the worktrees one
        assert mock_tool.check.call_count == 1

    def test_files_parameter_filters_to_md_only(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        languagetool_config: Path,
    ) -> None:
        """Should only process .md files when files parameter is provided."""
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Create various test files
        fs.create_file(str(fake_repo / "README.md"), contents="# Test README")
        fs.create_file(str(fake_repo / "script.py"), contents="print('hello')")
        fs.create_file(str(fake_repo / "config.yaml"), contents="key: value")
        fs.create_file(str(fake_repo / "notes.txt"), contents="Some notes")

        mock_tool = MagicMock()
        mock_tool.check.return_value = []

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                languagetool_config,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            # Pass a mix of file types
            result = linter.run(files=["README.md", "script.py", "config.yaml", "notes.txt"])

        assert result.success is True
        # Only the .md file should be checked
        assert mock_tool.check.call_count == 1

    def test_files_parameter_short_circuits_when_no_md_files(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        languagetool_config: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should not call API when no .md files in the files list."""
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Create only non-.md files
        fs.create_file(str(fake_repo / "script.py"), contents="print('hello')")
        fs.create_file(str(fake_repo / "config.yaml"), contents="key: value")

        mock_tool = MagicMock()
        mock_tool.check.return_value = []

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                languagetool_config,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            # Pass only non-.md files
            result = linter.run(files=["script.py", "config.yaml"])

        # Should return success without making API calls
        assert result.success is True
        assert mock_tool.check.call_count == 0

        # Should print the short-circuit message
        captured = capsys.readouterr()
        assert "No Markdown files to check" in captured.out

    def test_includes_project_markdown_files(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        languagetool_config: Path,
    ) -> None:
        """Should include README.md and AGENTS.md as per config targets."""
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Create target files from config
        fs.create_file(str(fake_repo / "README.md"), contents="# Test README")
        fs.create_file(str(fake_repo / "AGENTS.md"), contents="# Test AGENTS")

        mock_tool = MagicMock()
        mock_tool.check.return_value = []

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                languagetool_config,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            # Run without files parameter - should use config targets
            result = linter.run()

        assert result.success is True
        # Both README.md and AGENTS.md should be checked
        assert mock_tool.check.call_count == 2

    def test_disabled_rules_applied(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        languagetool_config: Path,
    ) -> None:
        """Disabled rules should not trigger matches."""
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        fs.create_file(str(fake_repo / "README.md"), contents="# Test README")

        # Create a match for a disabled rule
        disabled_rule_match = create_mock_match(
            rule_id="UPPERCASE_SENTENCE_START",
            category="CASING",
            matched_text="test",
        )

        mock_tool = MagicMock()
        mock_tool.check.return_value = [disabled_rule_match]

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                languagetool_config,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            result = linter.run(files=["README.md"])

        # Should succeed because disabled rule matches are filtered out
        assert result.success is True

    def test_language_setting_used(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        languagetool_config: Path,
    ) -> None:
        """Correct language should be passed to LanguageTool."""
        import sys

        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        fs.create_file(str(fake_repo / "README.md"), contents="# Test README")

        # Create mock for language_tool_python module
        mock_ltp = MagicMock()
        mock_public_api = MagicMock()
        mock_public_api.check.return_value = []
        mock_ltp.LanguageToolPublicAPI.return_value = mock_public_api

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                languagetool_config,
            ),
            patch.dict(sys.modules, {"language_tool_python": mock_ltp}),
        ):
            linter = LanguageToolLinter()
            linter.run(files=["README.md"])

        # Verify LanguageToolPublicAPI was called with en-US
        mock_ltp.LanguageToolPublicAPI.assert_called_once_with("en-US")

    def test_spelling_error_detected(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        languagetool_config: Path,
    ) -> None:
        """Misspelled words should be detected and returned as LintError objects."""
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        fs.create_file(str(fake_repo / "README.md"), contents="Teh quick brown fox")

        # Create a misspelling match for "teh"
        misspelling_match = create_mock_match(
            rule_issue_type="misspelling",
            matched_text="teh",
            category="TYPOS",
            rule_id="MORFOLOGIK_RULE_EN_US",
            message="Possible spelling mistake found",
            replacements=["the", "tech"],
        )

        mock_tool = MagicMock()
        mock_tool.check.return_value = [misspelling_match]

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                languagetool_config,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            result = linter.run(files=["README.md"])

        # Should fail because "teh" is not in dictionary
        assert result.success is False
        assert result.message is not None and "1 issue" in result.message

        # Verify LintError structure
        assert len(result.errors) == 1
        error = result.errors[0]
        assert error.file == "README.md"
        assert error.line == 1
        assert error.code == "MORFOLOGIK_RULE_EN_US"
        assert "Possible spelling mistake found" in error.message
        assert error.fix_available is True
        assert error.fix_message == "the"

    def test_dictionary_words_not_flagged(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        languagetool_config: Path,
    ) -> None:
        """Words in the project dictionary should not be flagged as misspellings."""
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        fs.create_file(
            str(fake_repo / "README.md"),
            contents="Use pymarkdown and yamllint for linting.",
        )

        # Create misspelling matches for dictionary words
        pymarkdown_match = create_mock_match(
            rule_issue_type="misspelling",
            matched_text="pymarkdown",
            category="TYPOS",
            rule_id="MORFOLOGIK_RULE_EN_US",
        )
        yamllint_match = create_mock_match(
            rule_issue_type="misspelling",
            matched_text="yamllint",
            category="TYPOS",
            rule_id="MORFOLOGIK_RULE_EN_US",
        )

        mock_tool = MagicMock()
        mock_tool.check.return_value = [pymarkdown_match, yamllint_match]

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                languagetool_config,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            result = linter.run(files=["README.md"])

        # Should succeed because dictionary words are filtered out
        assert result.success is True

    def test_dictionary_filtering_case_insensitive(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        languagetool_config: Path,
    ) -> None:
        """Capitalized dictionary terms should be accepted (case-insensitive matching)."""
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        fs.create_file(
            str(fake_repo / "README.md"),
            contents="Pymarkdown is a linter.",  # Capital P at sentence start
        )

        # Create a misspelling match for capitalized "Pymarkdown"
        capitalized_match = create_mock_match(
            rule_issue_type="misspelling",
            matched_text="Pymarkdown",  # Capitalized version
            category="TYPOS",
            rule_id="MORFOLOGIK_RULE_EN_US",
        )

        mock_tool = MagicMock()
        mock_tool.check.return_value = [capitalized_match]

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                languagetool_config,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            result = linter.run(files=["README.md"])

        # Should succeed because "Pymarkdown" matches lowercase "pymarkdown" in dictionary
        assert result.success is True

    def test_dictionary_filtering_preserves_other_matches(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        languagetool_config: Path,
    ) -> None:
        """Dictionary filtering should only remove spelling matches, not grammar matches."""
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        fs.create_file(
            str(fake_repo / "README.md"),
            contents="This are a grammar error.",
        )

        # Create a grammar match (not misspelling)
        grammar_match = create_mock_match(
            rule_issue_type="grammar",  # Not "misspelling"
            matched_text="This are",
            category="GRAMMAR",
            rule_id="THIS_NNS",
            message="Consider using 'These are' instead",
        )

        # Create a misspelling match for a dictionary word (should be filtered)
        dictionary_misspelling = create_mock_match(
            rule_issue_type="misspelling",
            matched_text="pymarkdown",
            category="TYPOS",
            rule_id="MORFOLOGIK_RULE_EN_US",
        )

        mock_tool = MagicMock()
        mock_tool.check.return_value = [grammar_match, dictionary_misspelling]

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                languagetool_config,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            result = linter.run(files=["README.md"])

        # Should fail because grammar match is preserved
        assert result.success is False
        # Only 1 issue (grammar) - the dictionary misspelling was filtered
        assert result.message is not None and "1 issue" in result.message

        # Verify LintError structure
        assert len(result.errors) == 1
        error = result.errors[0]
        assert error.file == "README.md"
        assert error.code == "THIS_NNS"
        assert "Consider using 'These are' instead" in error.message

    def test_explicit_yaml_null_values_handled(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """Explicit YAML null values should be treated as empty lists, not cause errors.

        When YAML config has `dictionary: null`, dict.get("dictionary", []) returns
        None (not the default []), so we must use `get(key) or []` pattern.
        """
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Create config with explicit null values for all list fields
        config_with_nulls = fake_repo / ".lint.languagetool.yaml"
        fs.create_file(
            str(config_with_nulls),
            contents=(
                "language: en-US\n"
                "use_public_api: true\n"
                "include_paths: null\n"
                "disabled_categories: null\n"
                "disabled_rules: null\n"
                "dictionary: null\n"
            ),
        )

        fs.create_file(str(fake_repo / "README.md"), contents="# Test README")

        mock_tool = MagicMock()
        mock_tool.check.return_value = []

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                config_with_nulls,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            # Should not raise TypeError when iterating over null config values
            # With files=None, include_paths=null means empty patterns -> no files to check
            result = linter.run()

        # Should succeed with no files to check
        assert result.success is True

    def test_explicit_yaml_null_dictionary_with_misspellings(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """Dictionary filtering should work when dictionary is explicit null."""
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Config with null dictionary - should still filter/iterate without error
        config_with_null_dict = fake_repo / ".lint.languagetool.yaml"
        fs.create_file(
            str(config_with_null_dict),
            contents=(
                "language: en-US\n"
                "use_public_api: true\n"
                "include_paths:\n"
                "  - README.md\n"
                "dictionary: null\n"  # Explicit null
            ),
        )

        fs.create_file(str(fake_repo / "README.md"), contents="# Test README")

        # Create a misspelling match
        misspelling_match = create_mock_match(
            rule_issue_type="misspelling",
            matched_text="teh",
            category="TYPOS",
            rule_id="MORFOLOGIK_RULE_EN_US",
        )

        mock_tool = MagicMock()
        mock_tool.check.return_value = [misspelling_match]

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                config_with_null_dict,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            # Should not raise TypeError when dictionary is null
            result = linter.run(files=["README.md"])

        # Should fail because misspelling is detected (not in any dictionary)
        assert result.success is False
        assert result.message is not None and "1 issue" in result.message

        # Verify LintError structure
        assert len(result.errors) == 1
        assert result.errors[0].code == "MORFOLOGIK_RULE_EN_US"

    def test_match_to_lint_error_handles_path_outside_repo(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        languagetool_config: Path,
    ) -> None:
        """_match_to_lint_error should not crash for absolute paths outside the repo root.

        When file_path.relative_to(REPO_ROOT) raises ValueError (path is outside repo),
        _match_to_lint_error should gracefully fall back to using the original path.
        """
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Create a file OUTSIDE the fake repo
        external_path = Path("/external/location/test.md")
        fs.create_file(str(external_path), contents="# External file content")

        # Create a match for the external file
        match = create_mock_match(
            rule_issue_type="grammar",
            matched_text="test",
            category="GRAMMAR",
            rule_id="TEST_RULE",
            message="Test message",
            context="test context",
            offset=0,
        )

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                languagetool_config,
            ),
        ):
            linter = LanguageToolLinter()

            # This should NOT raise ValueError
            lint_error = linter._match_to_lint_error(
                match, external_path, "# External file content"
            )

        # Should contain the path (either original or some fallback)
        assert "external" in lint_error.file or "test.md" in lint_error.file
        # Should contain the rule info
        assert lint_error.code == "TEST_RULE"

    def test_api_failure_continues_and_reports_file_errors(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        languagetool_config: Path,
    ) -> None:
        """API failures should be accumulated and reported, continuing with remaining files."""
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        fs.create_file(str(fake_repo / "README.md"), contents="# Test README")
        fs.create_file(str(fake_repo / "AGENTS.md"), contents="# Test AGENTS")

        mock_tool = MagicMock()
        # First file fails, second file succeeds
        mock_tool.check.side_effect = [
            ConnectionError("LanguageTool API unavailable"),
            [],  # Second file succeeds with no issues
        ]

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                languagetool_config,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            result = linter.run(files=["README.md", "AGENTS.md"])

        # Should FAIL due to file error, but continue processing
        assert result.success is False
        assert result.message is not None and "file error" in result.message
        # Should have attempted both files (second call succeeded)
        assert mock_tool.check.call_count == 2

    def test_file_read_error_continues_and_reports(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        languagetool_config: Path,
    ) -> None:
        """File I/O errors should be accumulated and reported, continuing with remaining files."""
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolCheckError,
            LanguageToolLinter,
        )

        # Create files
        fs.create_file(str(fake_repo / "README.md"), contents="# Test README")
        fs.create_file(str(fake_repo / "AGENTS.md"), contents="# Test AGENTS")

        mock_tool = MagicMock()
        mock_tool.check.return_value = []

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                languagetool_config,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            # Mock _check_file to fail on first file, succeed on second
            call_count = [0]
            original_check_file = linter._check_file

            def mock_check_file(file_path: Path) -> tuple[list[Any], str]:
                call_count[0] += 1
                if call_count[0] == 1:
                    raise LanguageToolCheckError(f"Could not read {file_path}: Permission denied")
                return original_check_file(file_path)

            with patch.object(linter, "_check_file", side_effect=mock_check_file):
                result = linter.run(files=["README.md", "AGENTS.md"])

        # Should FAIL due to file error
        assert result.success is False
        assert result.message is not None and "file error" in result.message

    def test_check_file_raises_on_api_error(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        languagetool_config: Path,
    ) -> None:
        """_check_file should raise LanguageToolCheckError on API failure."""
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolCheckError,
            LanguageToolLinter,
        )

        fs.create_file(str(fake_repo / "README.md"), contents="# Test README")

        mock_tool = MagicMock()
        mock_tool.check.side_effect = TimeoutError("Request timed out")

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                languagetool_config,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            with pytest.raises(LanguageToolCheckError) as exc_info:
                linter._check_file(fake_repo / "README.md")

        assert "LanguageTool check failed" in str(exc_info.value)
        assert "Request timed out" in str(exc_info.value)

    def test_check_file_raises_on_file_read_error(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
        languagetool_config: Path,
    ) -> None:
        """_check_file should raise LanguageToolCheckError on file read failure."""
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolCheckError,
            LanguageToolLinter,
        )

        # Don't create the file - it will fail to read
        # fs.create_file(str(fake_repo / "README.md"), contents="# Test README")

        mock_tool = MagicMock()
        mock_tool.check.return_value = []

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                languagetool_config,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            with pytest.raises(LanguageToolCheckError) as exc_info:
                linter._check_file(fake_repo / "README.md")

        assert "Could not read" in str(exc_info.value)

    def test_overlapping_targets_deduplicated(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """Overlapping config include_paths should not result in duplicate file checks.

        When include_paths contain patterns that match the same file (e.g., 'docs/README.md'
        and 'docs/**/*.md'), the file should only be checked once.
        """
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Config with overlapping include_paths
        overlapping_config = fake_repo / ".lint.languagetool.yaml"
        fs.create_file(
            str(overlapping_config),
            contents=(
                "language: en-US\n"
                "use_public_api: true\n"
                "include_paths:\n"
                "  - docs/README.md\n"  # Explicit file
                "  - docs/**/*.md\n"  # Glob that also matches docs/README.md
                "dictionary: null\n"
            ),
        )

        # Create the file that will be matched by both patterns
        fs.create_dir(str(fake_repo / "docs"))
        fs.create_file(str(fake_repo / "docs" / "README.md"), contents="# Docs README")

        mock_tool = MagicMock()
        mock_tool.check.return_value = []

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                overlapping_config,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            result = linter.run()

        assert result.success is True
        # File should only be checked ONCE, not twice despite being matched by both patterns
        assert mock_tool.check.call_count == 1

    def test_dictionary_with_non_string_entries_handled(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """Dictionary with None or non-string entries should not raise AttributeError.

        YAML configs can have invalid entries like `- null` or `- 123` in dictionary lists.
        These should be filtered out rather than causing .lower() to fail.
        """
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Config with mixed valid and invalid dictionary entries
        config_with_mixed_dict = fake_repo / ".lint.languagetool.yaml"
        fs.create_file(
            str(config_with_mixed_dict),
            contents=(
                "language: en-US\n"
                "use_public_api: true\n"
                "include_paths:\n"
                "  - README.md\n"
                "dictionary:\n"
                "  - pymarkdown\n"
                "  - null\n"  # Explicit null entry
                "  - 123\n"  # Numeric entry
                "  - yamllint\n"
            ),
        )

        fs.create_file(str(fake_repo / "README.md"), contents="# Test README")

        # Create misspelling matches for valid dictionary words
        pymarkdown_match = create_mock_match(
            rule_issue_type="misspelling",
            matched_text="pymarkdown",
            category="TYPOS",
            rule_id="MORFOLOGIK_RULE_EN_US",
        )

        mock_tool = MagicMock()
        mock_tool.check.return_value = [pymarkdown_match]

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                config_with_mixed_dict,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            # Should NOT raise AttributeError from None.lower()
            result = linter.run(files=["README.md"])

        # Should succeed because valid dictionary word "pymarkdown" is filtered
        assert result.success is True

    def test_dictionary_as_string_instead_of_list(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """Dictionary config as a string (not list) should be wrapped, not iterated by char.

        If the YAML config has `dictionary: pymarkdown` instead of `dictionary: [pymarkdown]`,
        the string should be treated as a single-item list, not iterated character by character.
        """
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Config with dictionary as a plain string (not a list)
        config_with_string_dict = fake_repo / ".lint.languagetool.yaml"
        fs.create_file(
            str(config_with_string_dict),
            contents=(
                "language: en-US\n"
                "use_public_api: true\n"
                "include_paths:\n"
                "  - README.md\n"
                "dictionary: pymarkdown\n"  # String, not a list
            ),
        )

        fs.create_file(str(fake_repo / "README.md"), contents="# Test README")

        # Create misspelling match for the dictionary word
        pymarkdown_match = create_mock_match(
            rule_issue_type="misspelling",
            matched_text="pymarkdown",
            category="TYPOS",
            rule_id="MORFOLOGIK_RULE_EN_US",
        )

        mock_tool = MagicMock()
        mock_tool.check.return_value = [pymarkdown_match]

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                config_with_string_dict,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            result = linter.run(files=["README.md"])

        # Should succeed because "pymarkdown" is treated as a dictionary entry
        # (NOT iterated as individual characters p, y, m, a, r, k, d, o, w, n)
        assert result.success is True

    def test_explicit_yaml_null_config_field(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """Explicit YAML null for 'config' field should be treated as empty dict.

        When YAML has `config: null`, dict.get("config", {}) returns None (not {}),
        so we must use `get("config") or {}` pattern to handle this case.
        """
        import sys

        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Config with explicit null for the 'config' field (LanguageTool options)
        config_with_null_config = fake_repo / ".lint.languagetool.yaml"
        fs.create_file(
            str(config_with_null_config),
            contents=(
                "language: en-US\n"
                "use_public_api: false\n"  # Use local server to test config passing
                "config: null\n"  # Explicit null for lt_config
                "include_paths:\n"
                "  - README.md\n"
            ),
        )

        fs.create_file(str(fake_repo / "README.md"), contents="# Test README")

        # Mock language_tool_python module
        mock_ltp = MagicMock()
        mock_local_tool = MagicMock()
        mock_local_tool.check.return_value = []
        mock_ltp.LanguageTool.return_value = mock_local_tool

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                config_with_null_config,
            ),
            patch.dict(sys.modules, {"language_tool_python": mock_ltp}),
        ):
            linter = LanguageToolLinter()
            result = linter.run(files=["README.md"])

        # Should not raise TypeError when config is null
        assert result.success is True
        # LanguageTool should have been called with empty dict, not None
        mock_ltp.LanguageTool.assert_called_once_with("en-US", config={})

    def test_include_paths_with_exclusion_patterns(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """Exclusion patterns with ! prefix should exclude matching files."""
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Config with glob inclusion and ! exclusion patterns
        config_with_exclusions = fake_repo / ".lint.languagetool.yaml"
        fs.create_file(
            str(config_with_exclusions),
            contents=(
                "language: en-US\n"
                "use_public_api: true\n"
                "include_paths:\n"
                "  - '**/*.md'\n"
                "  - '!docs/plans/**'\n"
                "  - '!.tmp/**'\n"
            ),
        )

        # Create files - some should be included, some excluded
        fs.create_file(str(fake_repo / "README.md"), contents="# README")
        fs.create_dir(str(fake_repo / "docs" / "plans"))
        fs.create_file(
            str(fake_repo / "docs" / "plans" / "plan.md"),
            contents="# Plan (should be excluded)",
        )
        fs.create_dir(str(fake_repo / ".tmp"))
        fs.create_file(
            str(fake_repo / ".tmp" / "temp.md"),
            contents="# Temp (should be excluded)",
        )

        mock_tool = MagicMock()
        mock_tool.check.return_value = []

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                config_with_exclusions,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            result = linter.run()

        assert result.success is True
        # Only README.md should be checked, not docs/plans/plan.md or .tmp/temp.md
        assert mock_tool.check.call_count == 1

    def test_include_paths_exclusion_with_files_parameter(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """Exclusion patterns should apply when files parameter is provided."""
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Config with exclusion patterns
        config_with_exclusions = fake_repo / ".lint.languagetool.yaml"
        fs.create_file(
            str(config_with_exclusions),
            contents=(
                "language: en-US\n"
                "use_public_api: true\n"
                "include_paths:\n"
                "  - '**/*.md'\n"
                "  - '!.worktrees/**'\n"
            ),
        )

        # Create files
        fs.create_file(str(fake_repo / "README.md"), contents="# README")
        fs.create_dir(str(fake_repo / ".worktrees" / "branch"))
        fs.create_file(
            str(fake_repo / ".worktrees" / "branch" / "README.md"),
            contents="# Worktree README",
        )

        mock_tool = MagicMock()
        mock_tool.check.return_value = []

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                config_with_exclusions,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            # Pass both files - exclusion should filter out the worktrees one
            result = linter.run(files=["README.md", ".worktrees/branch/README.md"])

        assert result.success is True
        # Only README.md should be checked
        assert mock_tool.check.call_count == 1

    def test_disabled_categories_as_string_instead_of_list(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """disabled_categories as a string should be wrapped, not iterated by char.

        If the YAML config has `disabled_categories: TYPOGRAPHY` instead of
        `disabled_categories: [TYPOGRAPHY]`, the string should be treated as a
        single-item set, not iterated character by character.
        """
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Config with disabled_categories as a plain string (not a list)
        config_with_string_categories = fake_repo / ".lint.languagetool.yaml"
        fs.create_file(
            str(config_with_string_categories),
            contents=(
                "language: en-US\n"
                "use_public_api: true\n"
                "include_paths:\n"
                "  - README.md\n"
                "disabled_categories: TYPOGRAPHY\n"  # String, not a list
            ),
        )

        fs.create_file(str(fake_repo / "README.md"), contents="# Test README")

        # Create a match for the TYPOGRAPHY category (should be filtered)
        typography_match = create_mock_match(
            rule_issue_type="typographical",
            matched_text="...",
            category="TYPOGRAPHY",
            rule_id="ELLIPSIS",
            message="Consider using ellipsis character",
        )

        mock_tool = MagicMock()
        mock_tool.check.return_value = [typography_match]

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                config_with_string_categories,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            result = linter.run(files=["README.md"])

        # Should succeed because TYPOGRAPHY category is disabled
        # (NOT iterated as individual characters T, Y, P, O, G, R, A, P, H, Y)
        assert result.success is True

    def test_disabled_rules_as_string_instead_of_list(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """disabled_rules as a string should be wrapped, not iterated by char.

        If the YAML config has `disabled_rules: UPPERCASE_SENTENCE_START` instead of
        `disabled_rules: [UPPERCASE_SENTENCE_START]`, the string should be treated as
        a single-item set, not iterated character by character.
        """
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Config with disabled_rules as a plain string (not a list)
        config_with_string_rules = fake_repo / ".lint.languagetool.yaml"
        fs.create_file(
            str(config_with_string_rules),
            contents=(
                "language: en-US\n"
                "use_public_api: true\n"
                "include_paths:\n"
                "  - README.md\n"
                "disabled_rules: UPPERCASE_SENTENCE_START\n"  # String, not a list
            ),
        )

        fs.create_file(str(fake_repo / "README.md"), contents="# Test README")

        # Create a match for the disabled rule (should be filtered)
        casing_match = create_mock_match(
            rule_issue_type="grammar",
            matched_text="test",
            category="CASING",
            rule_id="UPPERCASE_SENTENCE_START",
            message="Sentence should start with uppercase",
        )

        mock_tool = MagicMock()
        mock_tool.check.return_value = [casing_match]

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                config_with_string_rules,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            result = linter.run(files=["README.md"])

        # Should succeed because UPPERCASE_SENTENCE_START rule is disabled
        # (NOT iterated as individual characters)
        assert result.success is True

    def test_include_paths_as_string_instead_of_list(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """include_paths as a string should be wrapped, not iterated by char.

        If the YAML config has `include_paths: README.md` instead of
        `include_paths: [README.md]`, the string should be treated as a
        single-item list, not iterated character by character.
        """
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Config with include_paths as a plain string (not a list)
        config_with_string_paths = fake_repo / ".lint.languagetool.yaml"
        fs.create_file(
            str(config_with_string_paths),
            contents=(
                "language: en-US\n"
                "use_public_api: true\n"
                "include_paths: README.md\n"  # String, not a list
            ),
        )

        fs.create_file(str(fake_repo / "README.md"), contents="# Test README")

        mock_tool = MagicMock()
        mock_tool.check.return_value = []

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                config_with_string_paths,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            # Run without files parameter - should use config targets
            result = linter.run()

        # Should succeed because README.md is treated as a single pattern
        # (NOT iterated as individual characters R, E, A, D, M, E, ., m, d)
        assert result.success is True
        # README.md should be checked
        assert mock_tool.check.call_count == 1

    def test_glob_metacharacters_question_mark(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """Patterns with ? glob metacharacter should be treated as globs.

        The ? metacharacter matches any single character, so patterns like
        'docs/file?.md' should be processed as globs, not literal paths.
        """
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Config with ? glob pattern
        config_with_question = fake_repo / ".lint.languagetool.yaml"
        fs.create_file(
            str(config_with_question),
            contents=(
                "language: en-US\n"
                "use_public_api: true\n"
                "include_paths:\n"
                "  - 'docs/file?.md'\n"  # Should match file1.md, file2.md, etc.
            ),
        )

        # Create files that match the pattern
        fs.create_dir(str(fake_repo / "docs"))
        fs.create_file(str(fake_repo / "docs" / "file1.md"), contents="# File 1")
        fs.create_file(str(fake_repo / "docs" / "file2.md"), contents="# File 2")
        # This should NOT match (multiple chars after 'file')
        fs.create_file(str(fake_repo / "docs" / "file10.md"), contents="# File 10")

        mock_tool = MagicMock()
        mock_tool.check.return_value = []

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                config_with_question,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            result = linter.run()

        assert result.success is True
        # Should check file1.md and file2.md (not file10.md)
        assert mock_tool.check.call_count == 2

    def test_glob_metacharacters_brackets(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """Patterns with [] glob metacharacter should be treated as globs.

        The [] metacharacter matches any character in the set, so patterns like
        'docs/file[123].md' should be processed as globs, not literal paths.
        """
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Config with [] glob pattern
        config_with_brackets = fake_repo / ".lint.languagetool.yaml"
        fs.create_file(
            str(config_with_brackets),
            contents=(
                "language: en-US\n"
                "use_public_api: true\n"
                "include_paths:\n"
                "  - 'docs/file[12].md'\n"  # Should match file1.md and file2.md
            ),
        )

        # Create files that match the pattern
        fs.create_dir(str(fake_repo / "docs"))
        fs.create_file(str(fake_repo / "docs" / "file1.md"), contents="# File 1")
        fs.create_file(str(fake_repo / "docs" / "file2.md"), contents="# File 2")
        # This should NOT match (3 is not in [12])
        fs.create_file(str(fake_repo / "docs" / "file3.md"), contents="# File 3")

        mock_tool = MagicMock()
        mock_tool.check.return_value = []

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                config_with_brackets,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            result = linter.run()

        assert result.success is True
        # Should check file1.md and file2.md (not file3.md)
        assert mock_tool.check.call_count == 2

    def test_disabled_categories_with_non_hashable_entries(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """disabled_categories with non-hashable entries should not raise TypeError.

        YAML configs can have nested structures like `- [nested, list]` or `- {key: value}`
        in disabled_categories lists. These should be filtered out rather than causing
        set() to fail with TypeError.
        """
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Config with mixed valid strings and non-hashable entries in disabled_categories
        # Note: We simulate this by injecting the parsed config directly
        config_with_nested = fake_repo / ".lint.languagetool.yaml"
        fs.create_file(
            str(config_with_nested),
            contents=(
                "language: en-US\n"
                "use_public_api: true\n"
                "include_paths:\n"
                "  - README.md\n"
                "disabled_categories:\n"
                "  - TYPOGRAPHY\n"  # Valid string
            ),
        )

        fs.create_file(str(fake_repo / "README.md"), contents="# Test README")

        # Create a match for the TYPOGRAPHY category (should be filtered)
        typography_match = create_mock_match(
            rule_issue_type="typographical",
            matched_text="...",
            category="TYPOGRAPHY",
            rule_id="ELLIPSIS",
            message="Consider using ellipsis character",
        )

        mock_tool = MagicMock()
        mock_tool.check.return_value = [typography_match]

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                config_with_nested,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            # Inject non-hashable items into the config directly to simulate bad YAML
            linter._config = {
                "language": "en-US",
                "use_public_api": True,
                "include_paths": ["README.md"],
                "disabled_categories": [
                    "TYPOGRAPHY",  # Valid string
                    ["nested", "list"],  # Non-hashable list
                    {"key": "value"},  # Non-hashable dict
                    None,  # None entry
                    123,  # Numeric entry
                ],
                "disabled_rules": [],
            }

            # Should NOT raise TypeError when building set from non-hashable items
            result = linter.run(files=["README.md"])

        # Should succeed because TYPOGRAPHY category is disabled
        assert result.success is True

    def test_disabled_rules_with_non_hashable_entries(
        self,
        fake_repo: Path,
        fs: FakeFilesystem,
    ) -> None:
        """disabled_rules with non-hashable entries should not raise TypeError.

        YAML configs can have nested structures like `- [nested, list]` or `- {key: value}`
        in disabled_rules lists. These should be filtered out rather than causing
        set() to fail with TypeError.
        """
        from scripts.dev.linter.linters.languagetool import (
            LINT_LANGUAGETOOL_CONFIG,
            LanguageToolLinter,
        )

        # Config file (we'll override with injected config)
        config_file = fake_repo / ".lint.languagetool.yaml"
        fs.create_file(
            str(config_file),
            contents=("language: en-US\nuse_public_api: true\ninclude_paths:\n  - README.md\n"),
        )

        fs.create_file(str(fake_repo / "README.md"), contents="# Test README")

        # Create a match for the disabled rule
        casing_match = create_mock_match(
            rule_issue_type="grammar",
            matched_text="test",
            category="CASING",
            rule_id="UPPERCASE_SENTENCE_START",
            message="Sentence should start with uppercase",
        )

        mock_tool = MagicMock()
        mock_tool.check.return_value = [casing_match]

        with (
            patch("scripts.dev.linter.linters.languagetool.REPO_ROOT", fake_repo),
            patch.object(
                type(LINT_LANGUAGETOOL_CONFIG),
                "exists",
                return_value=True,
            ),
            patch(
                "scripts.dev.linter.linters.languagetool.LINT_LANGUAGETOOL_CONFIG",
                config_file,
            ),
        ):
            linter = LanguageToolLinter()
            linter._tool = mock_tool

            # Inject non-hashable items into the config directly
            linter._config = {
                "language": "en-US",
                "use_public_api": True,
                "include_paths": ["README.md"],
                "disabled_categories": [],
                "disabled_rules": [
                    "UPPERCASE_SENTENCE_START",  # Valid string
                    ["nested", "list"],  # Non-hashable list
                    {"key": "value"},  # Non-hashable dict
                    None,  # None entry
                ],
            }

            # Should NOT raise TypeError when building set from non-hashable items
            result = linter.run(files=["README.md"])

        # Should succeed because UPPERCASE_SENTENCE_START rule is disabled
        assert result.success is True
