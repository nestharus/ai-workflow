"""Tests for scripts.app.gen_openapi module."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scripts.app.gen_openapi import (
    OpenAPISchemaTypeError,
    SchemaSerializationError,
    _debug_enabled,
    _is_local_environment,
    build_application,
    generate_schema,
    main,
    normalize_openapi_schema,
    parse_args,
    write_schema,
)


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
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("scripts.app.gen_openapi._is_local_environment", return_value=True),
            patch("scripts.app.gen_openapi._generate_openapi"),
        ):
            main()

            # Check credentials were set inside the context
            assert "SURREALDB_USER" in os.environ
            assert "SURREALDB_PASS" in os.environ

    def test_returns_one_without_credentials_in_ci(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when credentials missing in non-local environment."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("scripts.app.gen_openapi._is_local_environment", return_value=False),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "SURREALDB_USER" in captured.err

    def test_returns_zero_on_success(self) -> None:
        """Should return 0 on successful generation."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("scripts.app.gen_openapi._is_local_environment", return_value=True),
            patch("scripts.app.gen_openapi._generate_openapi"),
        ):
            result = main()

        assert result == 0

    def test_handles_system_exit(self) -> None:
        """Should propagate SystemExit with correct code."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("scripts.app.gen_openapi._is_local_environment", return_value=True),
            patch("scripts.app.gen_openapi._generate_openapi") as mock_gen,
        ):
            mock_gen.side_effect = SystemExit(42)

            with pytest.raises(SystemExit) as exc_info:
                main()

            assert exc_info.value.code == 42

    def test_handles_exception(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 and print error on exception."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("scripts.app.gen_openapi._is_local_environment", return_value=True),
            patch("scripts.app.gen_openapi._generate_openapi") as mock_gen,
        ):
            mock_gen.side_effect = RuntimeError("Generation failed")

            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Generation failed" in captured.err

    def test_prints_traceback_in_debug_mode(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should print traceback when debug is enabled."""
        with (
            patch.dict(os.environ, {"DEBUG": "1"}, clear=True),
            patch("scripts.app.gen_openapi._is_local_environment", return_value=True),
            patch("scripts.app.gen_openapi._generate_openapi") as mock_gen,
        ):
            mock_gen.side_effect = RuntimeError("Generation failed")

            main()

        captured = capsys.readouterr()
        assert "Traceback" in captured.err or "RuntimeError" in captured.err


class TestExceptionClasses:
    """Tests for exception classes."""

    def test_openapi_schema_type_error_message(self) -> None:
        """Test OpenAPISchemaTypeError includes type name."""
        exc = OpenAPISchemaTypeError("str")
        assert "str" in str(exc)
        assert "dict" in str(exc).lower()

    def test_schema_serialization_error_message(self) -> None:
        """Test SchemaSerializationError has correct message."""
        exc = SchemaSerializationError()
        assert "serialize" in str(exc).lower() or "failed" in str(exc).lower()


class TestBuildApplication:
    """Tests for build_application function."""

    def test_imports_and_returns_fastapi_app(self) -> None:
        """Test build_application returns a FastAPI app."""
        # Need to have credentials set for this to work
        with patch.dict(
            os.environ,
            {
                "SURREALDB_USER": "TestUser1!Abc#",
                "SURREALDB_PASS": "TestPass1!Xyz$",
            },
        ):
            app = build_application()
            # Verify it's a FastAPI app
            assert hasattr(app, "openapi")


class TestGenerateSchema:
    """Tests for generate_schema function."""

    def test_returns_schema_dict(self) -> None:
        """Test generate_schema returns the OpenAPI schema dict."""
        mock_app = MagicMock()
        mock_app.openapi.return_value = {"openapi": "3.1.0", "info": {"title": "Test"}}

        result = generate_schema(mock_app)

        assert isinstance(result, dict)
        assert "openapi" in result
        mock_app.openapi.assert_called_once()

    def test_raises_for_non_dict_schema(self) -> None:
        """Test generate_schema raises for non-dict schema."""
        mock_app = MagicMock()
        mock_app.openapi.return_value = "not a dict"

        with pytest.raises(OpenAPISchemaTypeError):
            generate_schema(mock_app)


class TestNormalizeOpenAPISchema:
    """Tests for normalize_openapi_schema function."""

    def test_removes_unsupported_keys(self) -> None:
        """Test that unsupported keys are removed."""
        schema: dict[str, Any] = {
            "openapi": "3.0.0",
            "info": {"title": "Test"},
            "paths": {},
            "unsupported_key": "value",
        }

        result = normalize_openapi_schema(schema)

        assert "unsupported_key" not in result
        assert "info" in result
        assert "paths" in result

    def test_preserves_vendor_extensions(self) -> None:
        """Test that x-* vendor extensions are preserved."""
        schema: dict[str, Any] = {
            "openapi": "3.0.0",
            "info": {"title": "Test"},
            "x-custom-extension": "custom value",
        }

        result = normalize_openapi_schema(schema)

        assert "x-custom-extension" in result
        assert result["x-custom-extension"] == "custom value"

    def test_sets_openapi_version_to_3_1_0(self) -> None:
        """Test that openapi version is set to 3.1.0."""
        schema: dict[str, Any] = {"openapi": "3.0.0", "info": {}}

        result = normalize_openapi_schema(schema)

        assert result["openapi"] == "3.1.0"


class TestWriteSchema:
    """Tests for write_schema function."""

    def test_writes_json_to_file(self, tmp_path: Path) -> None:
        """Test write_schema writes JSON to the specified path."""
        output_path = tmp_path / "output" / "schema.json"
        schema: dict[str, Any] = {"openapi": "3.1.0", "info": {"title": "Test"}}

        write_schema(schema, output_path)

        assert output_path.exists()
        content = output_path.read_text()
        assert "openapi" in content
        assert "3.1.0" in content

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Test write_schema creates parent directories."""
        output_path = tmp_path / "deep" / "nested" / "dir" / "schema.json"
        schema: dict[str, Any] = {"openapi": "3.1.0"}

        write_schema(schema, output_path)

        assert output_path.exists()


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_output_path(self) -> None:
        """Test default output path when no args provided."""
        with patch("sys.argv", ["gen_openapi"]):
            args = parse_args()

        assert args.output == Path("openapi/openapi.json")

    def test_custom_output_path(self) -> None:
        """Test custom output path from command line."""
        with patch("sys.argv", ["gen_openapi", "--output", "custom/path.json"]):
            args = parse_args()

        assert args.output == Path("custom/path.json")
