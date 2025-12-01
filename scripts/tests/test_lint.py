"""Tests for scripts.lint module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from scripts import lint
from scripts.lint import (
    InvalidCommandError,
    _hadolint,
    _run_checked,
    _uv,
    main,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestInvalidCommandError:
    """Tests for InvalidCommandError exception."""

    def test_has_standard_message(self) -> None:
        """Should have standard validation message."""
        error = InvalidCommandError()
        assert "non-empty list of strings" in str(error)


class TestUv:
    """Tests for _uv function."""

    def test_returns_uv_path_when_found(self) -> None:
        """Should return uv executable path when available."""
        with patch("shutil.which", return_value="/usr/bin/uv"):
            result = _uv()
            assert result == "/usr/bin/uv"

    def test_raises_when_not_found(self) -> None:
        """Should raise RuntimeError when uv not found."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError) as exc_info:
                _uv()
            assert "uv CLI required" in str(exc_info.value)


class TestHadolint:
    """Tests for _hadolint function."""

    def test_returns_hadolint_path_when_found(self) -> None:
        """Should return hadolint executable path when available."""
        with patch("shutil.which", return_value="/usr/bin/hadolint"):
            result = _hadolint()
            assert result == "/usr/bin/hadolint"

    def test_raises_when_not_found(self) -> None:
        """Should raise RuntimeError when hadolint not found."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError) as exc_info:
                _hadolint()
            assert "hadolint CLI required" in str(exc_info.value)


class TestRunChecked:
    """Tests for _run_checked function."""

    def test_calls_subprocess_with_valid_command(self) -> None:
        """Should call subprocess.check_call with valid command."""
        with patch("subprocess.check_call") as mock_check_call:
            _run_checked(["echo", "test"])
            mock_check_call.assert_called_once_with(["echo", "test"])

    def test_raises_for_empty_command(self) -> None:
        """Should raise InvalidCommandError for empty command."""
        with pytest.raises(InvalidCommandError):
            _run_checked([])

    def test_raises_for_non_list_command(self) -> None:
        """Should raise InvalidCommandError for non-list command."""
        with pytest.raises(InvalidCommandError):
            _run_checked("echo test")  # type: ignore[arg-type]

    def test_raises_for_non_string_elements(self) -> None:
        """Should raise InvalidCommandError for non-string elements."""
        with pytest.raises(InvalidCommandError):
            _run_checked(["echo", 123])  # type: ignore[list-item]

    def test_propagates_subprocess_error(self) -> None:
        """Should propagate CalledProcessError from subprocess."""
        with patch("subprocess.check_call") as mock_check_call:
            mock_check_call.side_effect = subprocess.CalledProcessError(1, ["false"])
            with pytest.raises(subprocess.CalledProcessError):
                _run_checked(["false"])


class TestMain:
    """Tests for main function."""

    def test_returns_one_when_uv_not_found(self, capsys: pytest.CaptureFixture) -> None:
        """Should return 1 when uv is not found."""
        with patch("shutil.which", return_value=None):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "uv CLI required" in captured.err

    def test_returns_one_when_openapi_missing(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when OpenAPI schema is missing."""
        # Create minimal repo structure
        fs.create_dir("/fake/repo/openapi")

        with patch.object(lint, "REPO_ROOT", Path("/fake/repo")):
            with patch.object(lint, "OPENAPI_SCHEMA", Path("/fake/repo/openapi/openapi.json")):
                with patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}"):
                    with patch("subprocess.check_call"):
                        # Mock hadolint to find no Dockerfiles
                        with patch.object(lint, "HADOLINT_EXCLUDE_DIRS", set()):
                            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "OpenAPI schema missing" in captured.err

    def test_returns_one_on_subprocess_error(self) -> None:
        """Should return exit code from subprocess error."""
        with patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}"):
            with patch("subprocess.check_call") as mock_check:
                mock_check.side_effect = subprocess.CalledProcessError(42, ["ruff"])
                result = main()

        assert result == 42

    def test_successful_run(self, fs: FakeFilesystem) -> None:
        """Should return 0 on successful run with all checks passing."""
        # Create minimal repo structure with OpenAPI schema
        fs.create_dir("/fake/repo/openapi")
        fs.create_file("/fake/repo/openapi/openapi.json", contents="{}")
        fs.create_file("/fake/repo/.checkov.yaml", contents="")
        fs.create_file("/fake/repo/.hadolint.yaml", contents="")
        fs.create_file("/fake/repo/.pymarkdown.json", contents="{}")
        fs.create_file("/fake/repo/.yamllint.yaml", contents="")

        with patch.object(lint, "REPO_ROOT", Path("/fake/repo")):
            with patch.object(lint, "OPENAPI_SCHEMA", Path("/fake/repo/openapi/openapi.json")):
                with patch.object(lint, "CHECKOV_CONFIG", Path("/fake/repo/.checkov.yaml")):
                    with patch.object(lint, "HADOLINT_CONFIG", Path("/fake/repo/.hadolint.yaml")):
                        with patch.object(lint, "HADOLINT_EXCLUDE_DIRS", set()):
                            with patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}"):
                                with patch("subprocess.check_call"):
                                    result = main()

        assert result == 0

    def test_prints_no_dockerfiles_message(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should print message when no Dockerfiles found."""
        fs.create_dir("/fake/repo/openapi")
        fs.create_file("/fake/repo/openapi/openapi.json", contents="{}")
        fs.create_file("/fake/repo/.checkov.yaml", contents="")
        fs.create_file("/fake/repo/.hadolint.yaml", contents="")
        fs.create_file("/fake/repo/.pymarkdown.json", contents="{}")
        fs.create_file("/fake/repo/.yamllint.yaml", contents="")

        with patch.object(lint, "REPO_ROOT", Path("/fake/repo")):
            with patch.object(lint, "OPENAPI_SCHEMA", Path("/fake/repo/openapi/openapi.json")):
                with patch.object(lint, "CHECKOV_CONFIG", Path("/fake/repo/.checkov.yaml")):
                    with patch.object(lint, "HADOLINT_CONFIG", Path("/fake/repo/.hadolint.yaml")):
                        with patch.object(lint, "HADOLINT_EXCLUDE_DIRS", set()):
                            with patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}"):
                                with patch("subprocess.check_call"):
                                    main()

        captured = capsys.readouterr()
        assert "No Dockerfiles found" in captured.out
