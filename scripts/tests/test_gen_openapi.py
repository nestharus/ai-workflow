"""Tests for scripts.gen_openapi module."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from scripts.gen_openapi import (
    _debug_enabled,
    _is_local_environment,
    main,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestDebugEnabled:
    """Tests for _debug_enabled function."""

    def test_returns_true_for_debug_1(self) -> None:
        """Should return True when DEBUG=1."""
        with patch.dict(os.environ, {"DEBUG": "1"}, clear=True):
            assert _debug_enabled() is True

    def test_returns_true_for_debug_true(self) -> None:
        """Should return True when DEBUG=true."""
        with patch.dict(os.environ, {"DEBUG": "true"}, clear=True):
            assert _debug_enabled() is True

    def test_returns_true_for_verbose_yes(self) -> None:
        """Should return True when VERBOSE=yes."""
        with patch.dict(os.environ, {"VERBOSE": "yes"}, clear=True):
            assert _debug_enabled() is True

    def test_returns_false_when_not_set(self) -> None:
        """Should return False when env vars not set."""
        with patch.dict(os.environ, {}, clear=True):
            assert _debug_enabled() is False

    def test_returns_false_for_invalid_value(self) -> None:
        """Should return False for invalid value."""
        with patch.dict(os.environ, {"DEBUG": "invalid"}, clear=True):
            assert _debug_enabled() is False


class TestIsLocalEnvironment:
    """Tests for _is_local_environment function."""

    def test_returns_true_for_empty_env(self) -> None:
        """Should return True when ENV is empty."""
        with patch.dict(os.environ, {}, clear=True):
            assert _is_local_environment() is True

    def test_returns_true_for_local_env(self) -> None:
        """Should return True when ENV=local."""
        with patch.dict(os.environ, {"ENV": "local"}, clear=True):
            assert _is_local_environment() is True

    def test_returns_true_for_dev_env(self) -> None:
        """Should return True when ENV=dev."""
        with patch.dict(os.environ, {"ENV": "dev"}, clear=True):
            assert _is_local_environment() is True

    def test_returns_false_for_ci(self) -> None:
        """Should return False when CI=true."""
        with patch.dict(os.environ, {"CI": "true"}, clear=True):
            assert _is_local_environment() is False

    def test_returns_false_for_production(self) -> None:
        """Should return False when ENV=production."""
        with patch.dict(os.environ, {"ENV": "production"}, clear=True):
            assert _is_local_environment() is False


class TestMain:
    """Tests for main function."""

    def test_sets_default_credentials_locally(self) -> None:
        """Should set default credentials in local environment."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("scripts.gen_openapi._is_local_environment", return_value=True):
                with patch("scripts.gen_openapi.generate_openapi") as mock_gen:
                    main()

                    # Check credentials were set inside the context
                    assert "SURREALDB_USER" in os.environ
                    assert "SURREALDB_PASS" in os.environ

    def test_returns_one_without_credentials_in_ci(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when credentials missing in non-local environment."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("scripts.gen_openapi._is_local_environment", return_value=False):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "SURREALDB_USER" in captured.err

    def test_returns_zero_on_success(self) -> None:
        """Should return 0 on successful generation."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("scripts.gen_openapi._is_local_environment", return_value=True):
                with patch("scripts.gen_openapi.generate_openapi"):
                    result = main()

        assert result == 0

    def test_handles_system_exit(self) -> None:
        """Should propagate SystemExit with correct code."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("scripts.gen_openapi._is_local_environment", return_value=True):
                with patch("scripts.gen_openapi.generate_openapi") as mock_gen:
                    mock_gen.side_effect = SystemExit(42)

                    with pytest.raises(SystemExit) as exc_info:
                        main()

                    assert exc_info.value.code == 42

    def test_handles_exception(self, capsys: pytest.CaptureFixture) -> None:
        """Should return 1 and print error on exception."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("scripts.gen_openapi._is_local_environment", return_value=True):
                with patch("scripts.gen_openapi.generate_openapi") as mock_gen:
                    mock_gen.side_effect = RuntimeError("Generation failed")

                    result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Generation failed" in captured.err

    def test_prints_traceback_in_debug_mode(self, capsys: pytest.CaptureFixture) -> None:
        """Should print traceback when debug is enabled."""
        with patch.dict(os.environ, {"DEBUG": "1"}, clear=True):
            with patch("scripts.gen_openapi._is_local_environment", return_value=True):
                with patch("scripts.gen_openapi.generate_openapi") as mock_gen:
                    mock_gen.side_effect = RuntimeError("Generation failed")

                    main()

        captured = capsys.readouterr()
        assert "Traceback" in captured.err or "RuntimeError" in captured.err
