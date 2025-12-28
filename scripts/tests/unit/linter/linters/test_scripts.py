from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.linter.linters.scripts import ScriptsLinter


class TestScriptsLinterConfigLoading:
    @patch("scripts.dev.linter.linters.scripts.load_yaml_config")
    def test_run_config_not_dict(
        self,
        mock_load_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when config is not a dict (lines 35-36)."""
        mock_load_config.return_value = None  # Not a dict

        linter = ScriptsLinter()
        result = linter.run()

        assert result.success is False
        captured = capsys.readouterr()
        assert "No prefix_rules defined" in captured.err

    @patch("scripts.dev.linter.linters.scripts.load_yaml_config")
    def test_run_empty_prefix_rules(
        self,
        mock_load_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when prefix_rules is empty (lines 39-41)."""
        mock_load_config.return_value = {"prefix_rules": {}}

        linter = ScriptsLinter()
        result = linter.run()

        assert result.success is False
        captured = capsys.readouterr()
        assert "No prefix_rules defined" in captured.err


class TestScriptsLinterPyprojectMissing:
    @patch("scripts.dev.linter.linters.scripts.REPO_ROOT", Path("/fake/repo"))
    @patch("scripts.dev.linter.linters.scripts.load_yaml_config")
    def test_run_pyproject_not_found(
        self,
        mock_load_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when pyproject.toml not found (lines 44-46)."""
        mock_load_config.return_value = {"prefix_rules": {"scripts.": "dev-"}}

        linter = ScriptsLinter()
        result = linter.run()

        assert result.success is False
        captured = capsys.readouterr()
        assert "pyproject.toml not found" in captured.err


class TestScriptsLinterParsing:
    @patch("scripts.dev.linter.linters.scripts.REPO_ROOT")
    @patch("scripts.dev.linter.linters.scripts.load_yaml_config")
    def test_run_parses_project_scripts_section(
        self,
        mock_load_config: MagicMock,
        mock_repo_root: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run parses [project.scripts] section (lines 52-92)."""
        mock_load_config.return_value = {"prefix_rules": {"scripts.dev.": "dev-"}}

        pyproject_content = """
[project]
name = "test-project"

[project.scripts]
dev-lint = "scripts.dev.lint:main"
run-server = "app.main:start"

[tool.ruff]
line-length = 100
"""
        mock_pyproject = MagicMock()
        mock_pyproject.exists.return_value = True
        mock_pyproject.read_text.return_value = pyproject_content
        mock_repo_root.__truediv__ = lambda self, x: mock_pyproject

        linter = ScriptsLinter()
        result = linter.run()

        assert result.success is True
        captured = capsys.readouterr()
        assert "All script entry points follow naming conventions" in captured.out

    @patch("scripts.dev.linter.linters.scripts.REPO_ROOT")
    @patch("scripts.dev.linter.linters.scripts.load_yaml_config")
    def test_run_detects_violation(
        self,
        mock_load_config: MagicMock,
        mock_repo_root: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run detects naming violations (lines 85-92)."""
        mock_load_config.return_value = {"prefix_rules": {"scripts.dev.": "dev-"}}

        pyproject_content = """
[project.scripts]
bad-name = "scripts.dev.lint:main"
"""
        mock_pyproject = MagicMock()
        mock_pyproject.exists.return_value = True
        mock_pyproject.read_text.return_value = pyproject_content
        mock_repo_root.__truediv__ = lambda self, x: mock_pyproject

        linter = ScriptsLinter()
        result = linter.run()

        assert result.success is False
        captured = capsys.readouterr()
        assert "Script naming convention violations" in captured.err
        assert "bad-name" in captured.err
        assert "should be prefixed with 'dev-'" in captured.err

    @patch("scripts.dev.linter.linters.scripts.REPO_ROOT")
    @patch("scripts.dev.linter.linters.scripts.load_yaml_config")
    def test_run_skips_empty_lines_and_comments(
        self,
        mock_load_config: MagicMock,
        mock_repo_root: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run skips empty lines and comments (lines 65-67)."""
        mock_load_config.return_value = {"prefix_rules": {"scripts.dev.": "dev-"}}

        pyproject_content = """
[project.scripts]
# This is a comment
dev-lint = "scripts.dev.lint:main"

"""
        mock_pyproject = MagicMock()
        mock_pyproject.exists.return_value = True
        mock_pyproject.read_text.return_value = pyproject_content
        mock_repo_root.__truediv__ = lambda self, x: mock_pyproject

        linter = ScriptsLinter()
        result = linter.run()

        assert result.success is True

    @patch("scripts.dev.linter.linters.scripts.REPO_ROOT")
    @patch("scripts.dev.linter.linters.scripts.load_yaml_config")
    def test_run_skips_lines_without_equals(
        self,
        mock_load_config: MagicMock,
        mock_repo_root: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run skips lines without = (lines 69-71)."""
        mock_load_config.return_value = {"prefix_rules": {"scripts.dev.": "dev-"}}

        pyproject_content = """
[project.scripts]
invalid_line_no_equals
dev-lint = "scripts.dev.lint:main"
"""
        mock_pyproject = MagicMock()
        mock_pyproject.exists.return_value = True
        mock_pyproject.read_text.return_value = pyproject_content
        mock_repo_root.__truediv__ = lambda self, x: mock_pyproject

        linter = ScriptsLinter()
        result = linter.run()

        assert result.success is True

    @patch("scripts.dev.linter.linters.scripts.REPO_ROOT")
    @patch("scripts.dev.linter.linters.scripts.load_yaml_config")
    def test_run_handles_quoted_script_names(
        self,
        mock_load_config: MagicMock,
        mock_repo_root: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run handles quoted script names (line 77)."""
        mock_load_config.return_value = {"prefix_rules": {"scripts.dev.": "dev-"}}

        pyproject_content = """
[project.scripts]
"dev-lint" = "scripts.dev.lint:main"
'dev-test' = "scripts.dev.test:main"
"""
        mock_pyproject = MagicMock()
        mock_pyproject.exists.return_value = True
        mock_pyproject.read_text.return_value = pyproject_content
        mock_repo_root.__truediv__ = lambda self, x: mock_pyproject

        linter = ScriptsLinter()
        result = linter.run()

        assert result.success is True

    @patch("scripts.dev.linter.linters.scripts.REPO_ROOT")
    @patch("scripts.dev.linter.linters.scripts.load_yaml_config")
    def test_run_extracts_module_path_before_colon(
        self,
        mock_load_config: MagicMock,
        mock_repo_root: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run extracts module path before colon (lines 80-82)."""
        mock_load_config.return_value = {"prefix_rules": {"scripts.dev.": "dev-"}}

        pyproject_content = """
[project.scripts]
dev-lint = "scripts.dev.lint:main"
"""
        mock_pyproject = MagicMock()
        mock_pyproject.exists.return_value = True
        mock_pyproject.read_text.return_value = pyproject_content
        mock_repo_root.__truediv__ = lambda self, x: mock_pyproject

        linter = ScriptsLinter()
        result = linter.run()

        assert result.success is True

    @patch("scripts.dev.linter.linters.scripts.REPO_ROOT")
    @patch("scripts.dev.linter.linters.scripts.load_yaml_config")
    def test_run_stops_at_next_section(
        self,
        mock_load_config: MagicMock,
        mock_repo_root: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run stops parsing at next section (lines 57-60)."""
        mock_load_config.return_value = {"prefix_rules": {"scripts.dev.": "dev-"}}

        pyproject_content = """
[project.scripts]
dev-lint = "scripts.dev.lint:main"

[tool.ruff]
bad-name = "scripts.dev.shouldnt:check"
"""
        mock_pyproject = MagicMock()
        mock_pyproject.exists.return_value = True
        mock_pyproject.read_text.return_value = pyproject_content
        mock_repo_root.__truediv__ = lambda self, x: mock_pyproject

        linter = ScriptsLinter()
        result = linter.run()

        assert result.success is True  # Should not see violation in [tool.ruff]

    @patch("scripts.dev.linter.linters.scripts.REPO_ROOT")
    @patch("scripts.dev.linter.linters.scripts.load_yaml_config")
    def test_run_continues_after_non_scripts_section(
        self,
        mock_load_config: MagicMock,
        mock_repo_root: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run skips content in non-scripts sections (lines 61-63)."""
        mock_load_config.return_value = {"prefix_rules": {"scripts.dev.": "dev-"}}

        pyproject_content = """
[tool.poetry]
name = "project"

[project.scripts]
dev-lint = "scripts.dev.lint:main"
"""
        mock_pyproject = MagicMock()
        mock_pyproject.exists.return_value = True
        mock_pyproject.read_text.return_value = pyproject_content
        mock_repo_root.__truediv__ = lambda self, x: mock_pyproject

        linter = ScriptsLinter()
        result = linter.run()

        assert result.success is True


class TestScriptsLinterFilesIgnored:
    @patch("scripts.dev.linter.linters.scripts.REPO_ROOT")
    @patch("scripts.dev.linter.linters.scripts.load_yaml_config")
    def test_run_ignores_files_parameter(
        self,
        mock_load_config: MagicMock,
        mock_repo_root: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run ignores files parameter (line 28 docstring)."""
        mock_load_config.return_value = {"prefix_rules": {"scripts.dev.": "dev-"}}

        pyproject_content = """
[project.scripts]
dev-lint = "scripts.dev.lint:main"
"""
        mock_pyproject = MagicMock()
        mock_pyproject.exists.return_value = True
        mock_pyproject.read_text.return_value = pyproject_content
        mock_repo_root.__truediv__ = lambda self, x: mock_pyproject

        linter = ScriptsLinter()
        result = linter.run(files=["some_file.py"])  # Should be ignored

        assert result.success is True
