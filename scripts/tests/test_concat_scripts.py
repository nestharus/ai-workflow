"""Tests for concat script modules."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts import (
    concat_app,
    concat_docs,
    concat_scripts,
    concat_tests,
    concat_tools,
    utils,
)
from scripts.concat_app import concatenate_app, main as concat_app_main
from scripts.concat_docs import concatenate_docs, main as concat_docs_main
from scripts.concat_scripts import concatenate_scripts, main as concat_scripts_main
from scripts.concat_tests import concatenate_tests, main as concat_tests_main
from scripts.concat_tools import concatenate_tools, main as concat_tools_main

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestConcatApp:
    """Tests for concat_app module."""

    def test_concatenate_app_writes_output(self, fs: FakeFilesystem) -> None:
        """Should write concatenated app files to output."""
        with (
            patch.object(concat_app, "REPO_ROOT", Path("/fake")),
            patch.object(concat_app, "APP_DIR", Path("/fake/app")),
            patch.object(utils, "REPO_ROOT", Path("/fake")),
        ):
            fs.create_dir("/fake/app")
            fs.create_file("/fake/app/main.py", contents="# main\n")
            fs.create_file("/fake/app/config.py", contents="# config\n")

            output_path = Path("/fake/output.txt")
            concatenate_app(output_path)

            assert output_path.exists()
            content = output_path.read_text()
            assert "main.py" in content

    def test_main_returns_zero(self, fs: FakeFilesystem) -> None:
        """Should return 0 on success."""
        with (
            patch.object(concat_app, "REPO_ROOT", Path("/fake")),
            patch.object(concat_app, "APP_DIR", Path("/fake/app")),
            patch.object(concat_app, "DEFAULT_OUTPUT", Path("/fake/output.txt")),
            patch.object(utils, "REPO_ROOT", Path("/fake")),
        ):
            fs.create_dir("/fake/app")
            fs.create_file("/fake/app/main.py", contents="# main\n")

            result = concat_app_main([])

            assert result == 0


class TestConcatDocs:
    """Tests for concat_docs module."""

    def test_concatenate_docs_writes_output(self, fs: FakeFilesystem) -> None:
        """Should write concatenated docs files to output."""
        with (
            patch.object(concat_docs, "REPO_ROOT", Path("/fake")),
            patch.object(concat_docs, "DOCS_DIR", Path("/fake/docs")),
            patch.object(utils, "REPO_ROOT", Path("/fake")),
        ):
            fs.create_dir("/fake/docs")
            fs.create_file("/fake/docs/README.md", contents="# Docs\n")
            fs.create_file("/fake/docs/guide.md", contents="# Guide\n")

            output_path = Path("/fake/output.txt")
            concatenate_docs(output_path)

            assert output_path.exists()
            content = output_path.read_text()
            assert "README.md" in content or "guide.md" in content

    def test_main_returns_zero(self, fs: FakeFilesystem) -> None:
        """Should return 0 on success."""
        with (
            patch.object(concat_docs, "REPO_ROOT", Path("/fake")),
            patch.object(concat_docs, "DOCS_DIR", Path("/fake/docs")),
            patch.object(concat_docs, "DEFAULT_OUTPUT", Path("/fake/output.txt")),
            patch.object(utils, "REPO_ROOT", Path("/fake")),
        ):
            fs.create_dir("/fake/docs")
            fs.create_file("/fake/docs/README.md", contents="# Docs\n")

            result = concat_docs_main([])

            assert result == 0


class TestConcatScripts:
    """Tests for concat_scripts module."""

    def test_concatenate_scripts_writes_output(self, fs: FakeFilesystem) -> None:
        """Should write concatenated scripts files to output."""
        with (
            patch.object(concat_scripts, "REPO_ROOT", Path("/fake")),
            patch.object(concat_scripts, "SCRIPTS_DIR", Path("/fake/scripts")),
            patch.object(utils, "REPO_ROOT", Path("/fake")),
        ):
            fs.create_dir("/fake/scripts")
            fs.create_file("/fake/scripts/setup.py", contents="# setup\n")
            fs.create_file("/fake/scripts/lint.py", contents="# lint\n")

            output_path = Path("/fake/output.txt")
            concatenate_scripts(output_path)

            assert output_path.exists()
            content = output_path.read_text()
            assert "setup.py" in content or "lint.py" in content

    def test_main_returns_zero(self, fs: FakeFilesystem) -> None:
        """Should return 0 on success."""
        with (
            patch.object(concat_scripts, "REPO_ROOT", Path("/fake")),
            patch.object(concat_scripts, "SCRIPTS_DIR", Path("/fake/scripts")),
            patch.object(concat_scripts, "DEFAULT_OUTPUT", Path("/fake/output.txt")),
            patch.object(utils, "REPO_ROOT", Path("/fake")),
        ):
            fs.create_dir("/fake/scripts")
            fs.create_file("/fake/scripts/setup.py", contents="# setup\n")

            result = concat_scripts_main([])

            assert result == 0


class TestConcatTests:
    """Tests for concat_tests module."""

    def test_concatenate_tests_writes_output(self, fs: FakeFilesystem) -> None:
        """Should write concatenated tests files to output."""
        with (
            patch.object(concat_tests, "REPO_ROOT", Path("/fake")),
            patch.object(concat_tests, "TESTS_DIR", Path("/fake/tests")),
            patch.object(utils, "REPO_ROOT", Path("/fake")),
        ):
            fs.create_dir("/fake/tests")
            fs.create_file("/fake/tests/test_main.py", contents="# test_main\n")
            fs.create_file("/fake/tests/conftest.py", contents="# conftest\n")

            output_path = Path("/fake/output.txt")
            concatenate_tests(output_path)

            assert output_path.exists()
            content = output_path.read_text()
            assert "test_main.py" in content or "conftest.py" in content

    def test_main_returns_zero(self, fs: FakeFilesystem) -> None:
        """Should return 0 on success."""
        with (
            patch.object(concat_tests, "REPO_ROOT", Path("/fake")),
            patch.object(concat_tests, "TESTS_DIR", Path("/fake/tests")),
            patch.object(concat_tests, "DEFAULT_OUTPUT", Path("/fake/output.txt")),
            patch.object(utils, "REPO_ROOT", Path("/fake")),
        ):
            fs.create_dir("/fake/tests")
            fs.create_file("/fake/tests/test_main.py", contents="# test\n")

            result = concat_tests_main([])

            assert result == 0


class TestConcatTools:
    """Tests for concat_tools module."""

    def test_concatenate_tools_writes_output(self, fs: FakeFilesystem) -> None:
        """Should write concatenated tools files to output."""
        with (
            patch.object(concat_tools, "REPO_ROOT", Path("/fake")),
            patch.object(concat_tools, "TOOLS_DIR", Path("/fake/tools")),
            patch.object(utils, "REPO_ROOT", Path("/fake")),
        ):
            fs.create_dir("/fake/tools")
            fs.create_file("/fake/tools/gen_openapi.py", contents="# gen_openapi\n")

            output_path = Path("/fake/output.txt")
            concatenate_tools(output_path)

            assert output_path.exists()
            content = output_path.read_text()
            assert "gen_openapi.py" in content

    def test_main_returns_zero(self, fs: FakeFilesystem) -> None:
        """Should return 0 on success."""
        with (
            patch.object(concat_tools, "REPO_ROOT", Path("/fake")),
            patch.object(concat_tools, "TOOLS_DIR", Path("/fake/tools")),
            patch.object(concat_tools, "DEFAULT_OUTPUT", Path("/fake/output.txt")),
            patch.object(utils, "REPO_ROOT", Path("/fake")),
        ):
            fs.create_dir("/fake/tools")
            fs.create_file("/fake/tools/gen_openapi.py", contents="# tool\n")

            result = concat_tools_main([])

            assert result == 0
