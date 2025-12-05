"""Tests for scripts.dev.lint_markdown_restriction module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts.dev import lint_markdown_restriction
from scripts.dev.lint_markdown_restriction import (
    find_markdown_files,
    format_violations,
    load_config,
    main,
    validate_markdown_files,
)
from scripts.dev.lint_markdown_restriction import (
    lint_markdown_restriction as lint_md_restriction_func,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_success(self, fs: FakeFilesystem) -> None:
        """Should load valid configuration file."""
        fs.create_file(
            "/fake/repo/.lint.markdown-restriction.yaml",
            contents=(
                "restricted_dirs:\n  - .\n  - docs\n"
                "allowed_files:\n  - README.md\n  - AGENTS.md\n"
                "exclude_dirs:\n  - .venv\n  - node_modules"
            ),
        )

        config = load_config(Path("/fake/repo/.lint.markdown-restriction.yaml"))

        assert config["restricted_dirs"] == [".", "docs"]
        assert config["allowed_files"] == ["README.md", "AGENTS.md"]
        assert config["exclude_dirs"] == [".venv", "node_modules"]

    def test_load_config_missing_file(self, fs: FakeFilesystem) -> None:
        """Should raise FileNotFoundError for missing config file."""
        fs.create_dir("/fake/repo")

        with pytest.raises(FileNotFoundError):
            load_config(Path("/fake/repo/nonexistent.yaml"))

    def test_config_has_required_keys(self, fs: FakeFilesystem) -> None:
        """Should handle config with all required keys."""
        fs.create_file(
            "/fake/repo/.lint.markdown-restriction.yaml",
            contents=(
                "restricted_dirs:\n  - .\nallowed_files:\n  - README.md\nexclude_dirs:\n  - .venv"
            ),
        )

        config = load_config(Path("/fake/repo/.lint.markdown-restriction.yaml"))

        assert "restricted_dirs" in config
        assert "allowed_files" in config
        assert "exclude_dirs" in config

    def test_load_empty_config(self, fs: FakeFilesystem) -> None:
        """Should return empty dict for empty config file."""
        fs.create_file("/fake/repo/.lint.markdown-restriction.yaml", contents="")

        config = load_config(Path("/fake/repo/.lint.markdown-restriction.yaml"))

        assert config == {}


class TestFindMarkdownFiles:
    """Tests for find_markdown_files function."""

    def test_find_markdown_files(self, fs: FakeFilesystem) -> None:
        """Should find .md files in restricted directories."""
        fs.create_dir("/fake/repo/docs")
        fs.create_file("/fake/repo/README.md", contents="# README")
        fs.create_file("/fake/repo/docs/guide.md", contents="# Guide")

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            files = find_markdown_files([".", "docs"], set())

        relative_paths = [f.relative_to(Path("/fake/repo")).as_posix() for f in files]
        assert "README.md" in relative_paths
        assert "docs/guide.md" in relative_paths

    def test_exclude_configured_directories(self, fs: FakeFilesystem) -> None:
        """Should exclude directories specified in exclude_dirs."""
        fs.create_dir("/fake/repo/docs")
        fs.create_dir("/fake/repo/.venv")
        fs.create_file("/fake/repo/README.md", contents="# README")
        fs.create_file("/fake/repo/.venv/lib.md", contents="# Lib")

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            files = find_markdown_files([".", ".venv"], {".venv"})

        relative_paths = [f.relative_to(Path("/fake/repo")).as_posix() for f in files]
        assert "README.md" in relative_paths
        assert ".venv/lib.md" not in relative_paths

    def test_find_markdown_files_empty(self, fs: FakeFilesystem) -> None:
        """Should return empty list when no markdown files exist."""
        fs.create_dir("/fake/repo/docs")
        fs.create_file("/fake/repo/docs/guide.yaml", contents="key: value")

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            files = find_markdown_files([".", "docs"], set())

        assert files == []

    def test_find_files_nonexistent_directory(self, fs: FakeFilesystem) -> None:
        """Should skip nonexistent directories gracefully."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/README.md", contents="# README")

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            files = find_markdown_files([".", "nonexistent"], set())

        relative_paths = [f.relative_to(Path("/fake/repo")).as_posix() for f in files]
        assert "README.md" in relative_paths

    def test_find_markdown_files_nested(self, fs: FakeFilesystem) -> None:
        """Should find markdown files in nested directories."""
        fs.create_dir("/fake/repo/docs/api")
        fs.create_file("/fake/repo/docs/api/endpoints.md", contents="# Endpoints")

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            files = find_markdown_files(["docs"], set())

        relative_paths = [f.relative_to(Path("/fake/repo")).as_posix() for f in files]
        assert "docs/api/endpoints.md" in relative_paths


class TestValidateMarkdownFiles:
    """Tests for validate_markdown_files function."""

    def test_readme_allowed(self, fs: FakeFilesystem) -> None:
        """Should allow README.md in root."""
        fs.create_file("/fake/repo/README.md", contents="# README")

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            violations = validate_markdown_files(
                [Path("/fake/repo/README.md")],
                {"README.md", "AGENTS.md"},
            )

        assert violations == []

    def test_agents_allowed(self, fs: FakeFilesystem) -> None:
        """Should allow AGENTS.md in root."""
        fs.create_file("/fake/repo/AGENTS.md", contents="# AGENTS")

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            violations = validate_markdown_files(
                [Path("/fake/repo/AGENTS.md")],
                {"README.md", "AGENTS.md"},
            )

        assert violations == []

    def test_docs_readme_forbidden(self, fs: FakeFilesystem) -> None:
        """Should flag docs/README.md as violation."""
        fs.create_dir("/fake/repo/docs")
        fs.create_file("/fake/repo/docs/README.md", contents="# Docs README")

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            violations = validate_markdown_files(
                [Path("/fake/repo/docs/README.md")],
                {"README.md", "AGENTS.md"},
            )

        assert len(violations) == 1
        assert violations[0]["file_path"] == "docs/README.md"
        assert violations[0]["error_type"] == "forbidden_markdown_file"

    def test_scripts_readme_forbidden(self, fs: FakeFilesystem) -> None:
        """Should flag scripts/knowledge/README.md as violation."""
        fs.create_dir("/fake/repo/scripts/knowledge")
        fs.create_file("/fake/repo/scripts/knowledge/README.md", contents="# Knowledge README")

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            violations = validate_markdown_files(
                [Path("/fake/repo/scripts/knowledge/README.md")],
                {"README.md", "AGENTS.md"},
            )

        assert len(violations) == 1
        assert violations[0]["file_path"] == "scripts/knowledge/README.md"

    def test_app_markdown_forbidden(self, fs: FakeFilesystem) -> None:
        """Should flag any .md file in app/ as violation."""
        fs.create_dir("/fake/repo/app")
        fs.create_file("/fake/repo/app/notes.md", contents="# Notes")

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            violations = validate_markdown_files(
                [Path("/fake/repo/app/notes.md")],
                {"README.md", "AGENTS.md"},
            )

        assert len(violations) == 1
        assert violations[0]["file_path"] == "app/notes.md"

    def test_tests_markdown_forbidden(self, fs: FakeFilesystem) -> None:
        """Should flag any .md file in tests/ as violation."""
        fs.create_dir("/fake/repo/tests")
        fs.create_file("/fake/repo/tests/guide.md", contents="# Test Guide")

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            violations = validate_markdown_files(
                [Path("/fake/repo/tests/guide.md")],
                {"README.md", "AGENTS.md"},
            )

        assert len(violations) == 1
        assert violations[0]["file_path"] == "tests/guide.md"

    def test_multiple_violations(self, fs: FakeFilesystem) -> None:
        """Should report multiple violations."""
        fs.create_dir("/fake/repo/docs")
        fs.create_dir("/fake/repo/app")
        fs.create_file("/fake/repo/docs/guide.md", contents="# Guide")
        fs.create_file("/fake/repo/app/notes.md", contents="# Notes")

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            violations = validate_markdown_files(
                [Path("/fake/repo/docs/guide.md"), Path("/fake/repo/app/notes.md")],
                {"README.md", "AGENTS.md"},
            )

        assert len(violations) == 2
        paths = [v["file_path"] for v in violations]
        assert "docs/guide.md" in paths
        assert "app/notes.md" in paths


class TestViolationFormat:
    """Tests for violation formatting and structure."""

    def test_violation_format(self, fs: FakeFilesystem) -> None:
        """Should have correct violation result structure."""
        fs.create_dir("/fake/repo/docs")
        fs.create_file("/fake/repo/docs/guide.md", contents="# Guide")

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            violations = validate_markdown_files(
                [Path("/fake/repo/docs/guide.md")],
                {"README.md", "AGENTS.md"},
            )

        assert len(violations) == 1
        violation = violations[0]
        assert "file_path" in violation
        assert "error_type" in violation
        assert "message" in violation
        assert violation["error_type"] == "forbidden_markdown_file"

    def test_relative_path_normalization(self, fs: FakeFilesystem) -> None:
        """Should use POSIX-style relative paths."""
        fs.create_dir("/fake/repo/docs/nested/path")
        fs.create_file("/fake/repo/docs/nested/path/guide.md", contents="# Nested Guide")

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            violations = validate_markdown_files(
                [Path("/fake/repo/docs/nested/path/guide.md")],
                {"README.md", "AGENTS.md"},
            )

        assert violations[0]["file_path"] == "docs/nested/path/guide.md"

    def test_format_violations_output(self, fs: FakeFilesystem) -> None:
        """Should format violations for display."""
        violations = [
            {
                "file_path": "docs/guide.md",
                "error_type": "forbidden_markdown_file",
                "message": "Test message",
            }
        ]

        output = format_violations(violations)  # type: ignore[arg-type]

        assert "Forbidden markdown files found" in output
        assert "docs/guide.md" in output
        assert "forbidden_markdown_file" in output

    def test_format_violations_empty(self) -> None:
        """Should return empty string for no violations."""
        output = format_violations([])
        assert output == ""


class TestLintMarkdownRestriction:
    """Tests for lint_markdown_restriction function."""

    def test_exit_code_no_violations(self, fs: FakeFilesystem) -> None:
        """Should return exit code 0 when no violations."""
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

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            violations, exit_code = lint_md_restriction_func(
                Path("/fake/repo/.lint.markdown-restriction.yaml")
            )

        assert exit_code == 0
        assert violations == []

    def test_exit_code_with_violations(self, fs: FakeFilesystem) -> None:
        """Should return exit code 1 when violations found."""
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

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            violations, exit_code = lint_md_restriction_func(
                Path("/fake/repo/.lint.markdown-restriction.yaml")
            )

        assert exit_code == 1
        assert len(violations) == 1

    def test_uses_default_config_path(self, fs: FakeFilesystem) -> None:
        """Should use default config path when not specified."""
        fs.create_dir("/fake/repo")
        fs.create_file("/fake/repo/README.md", contents="# README")
        fs.create_file(
            "/fake/repo/.lint.markdown-restriction.yaml",
            contents=(
                "restricted_dirs:\n  - .\nallowed_files:\n"
                "  - README.md\n  - AGENTS.md\nexclude_dirs: []"
            ),
        )

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            _violations, exit_code = lint_md_restriction_func()

        assert exit_code == 0


class TestMain:
    """Tests for main function."""

    def test_main_with_violations(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print violations and return 1 when violations exist."""
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

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            exit_code = main()

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "forbidden_markdown_file" in captured.err
        assert "docs/guide.md" in captured.err

    def test_main_no_violations(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print success message and return 0 when no violations."""
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

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            exit_code = main()

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "No forbidden markdown files found" in captured.out


class TestExcludedDirectories:
    """Tests for excluded directory handling."""

    def test_excluded_dir_ignored(self, fs: FakeFilesystem) -> None:
        """Should ignore markdown files in excluded directories."""
        fs.create_dir("/fake/repo/.venv")
        fs.create_dir("/fake/repo/__pycache__")
        fs.create_file("/fake/repo/.venv/lib.md", contents="# Lib")
        fs.create_file("/fake/repo/__pycache__/cache.md", contents="# Cache")
        fs.create_file("/fake/repo/README.md", contents="# README")

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            files = find_markdown_files([".", ".venv", "__pycache__"], {".venv", "__pycache__"})

        relative_paths = [f.relative_to(Path("/fake/repo")).as_posix() for f in files]
        assert "README.md" in relative_paths
        assert ".venv/lib.md" not in relative_paths
        assert "__pycache__/cache.md" not in relative_paths

    def test_nested_excluded_dir(self, fs: FakeFilesystem) -> None:
        """Should exclude files in nested excluded directories."""
        fs.create_dir("/fake/repo/docs/.venv")
        fs.create_file("/fake/repo/docs/.venv/nested.md", contents="# Nested")
        fs.create_file("/fake/repo/README.md", contents="# README")

        with patch.object(lint_markdown_restriction, "REPO_ROOT", Path("/fake/repo")):
            files = find_markdown_files([".", "docs"], {".venv"})

        relative_paths = [f.relative_to(Path("/fake/repo")).as_posix() for f in files]
        assert "README.md" in relative_paths
        assert "docs/.venv/nested.md" not in relative_paths
