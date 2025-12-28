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


class TestExceptionClasses:
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

    def test_raises_serialization_error_for_unserializable_data(self, tmp_path: Path) -> None:
        """Test write_schema raises SchemaSerializationError for unserializable data."""
        output_path = tmp_path / "schema.json"
        # Create a schema with a circular reference which orjson cannot serialize
        schema: dict[str, Any] = {"openapi": "3.1.0"}
        schema["self_reference"] = schema  # Circular reference

        with pytest.raises(SchemaSerializationError):
            write_schema(schema, output_path)
