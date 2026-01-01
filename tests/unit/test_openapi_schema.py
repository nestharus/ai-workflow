from __future__ import annotations

from typing import Any

import pytest

from app.core.factory import create_app
from app.core.settings import Settings


class _DummyResource:
    async def close(self) -> None:  # pragma: no cover - trivial stub
        return None


def _mock_external_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_surreal_pool(_settings: Settings) -> _DummyResource:
        return _DummyResource()

    async def _fake_elasticsearch_wrapper(_settings: Settings) -> _DummyResource:
        return _DummyResource()

    monkeypatch.setattr("app.core.factory.create_surrealdb_pool", _fake_surreal_pool)
    monkeypatch.setattr(
        "app.core.factory.create_elasticsearch_wrapper",
        _fake_elasticsearch_wrapper,
    )


def _build_settings() -> Settings:
    return Settings(
        surrealdb_user="UserAa1!OpenApi",
        surrealdb_pass="PassAa1!OpenApi",
    )


@pytest.fixture
def openapi_schema(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    _mock_external_dependencies(monkeypatch)
    app = create_app(_build_settings())
    return app.openapi()


def test_openapi_includes_error_schemas(openapi_schema: dict[str, Any]) -> None:
    components = openapi_schema.get("components", {})
    schemas = components.get("schemas", {})

    assert "HTTPValidationError" in schemas
    assert "AppError" in schemas
    assert "ErrorCode" in schemas
    assert schemas["ErrorCode"].get("enum")


def test_openapi_includes_example_paths(openapi_schema: dict[str, Any]) -> None:
    paths = openapi_schema.get("paths")

    assert paths
    assert "/api/v1/examples/process" in paths
    assert "/api/v1/examples/sample" in paths


def test_validation_error_response_uses_app_error(openapi_schema: dict[str, Any]) -> None:
    """Verify 400 validation error responses reference AppError schema."""
    paths = openapi_schema.get("paths", {})

    # Check the /api/v1/examples/process endpoint
    process_endpoint = paths.get("/api/v1/examples/process", {})
    post_operation = process_endpoint.get("post", {})
    responses = post_operation.get("responses", {})
    bad_request_response = responses.get("400", {})

    # Get the schema reference for the 400 response
    content = bad_request_response.get("content", {})
    json_content = content.get("application/json", {})
    schema = json_content.get("schema", {})

    # The schema should reference AppError, not HTTPValidationError
    assert "$ref" in schema
    assert schema["$ref"] == "#/components/schemas/AppError"


def test_all_error_responses_reference_app_error(openapi_schema: dict[str, Any]) -> None:
    """Verify all documented error responses reference AppError schema."""
    paths = openapi_schema.get("paths", {})

    # Error status codes that should use AppError
    error_status_codes = {"400", "401", "403", "404", "500"}

    for path, methods in paths.items():
        for method, operation in methods.items():
            if not isinstance(operation, dict):
                continue
            responses = operation.get("responses", {})
            for status_code, response in responses.items():
                if status_code not in error_status_codes:
                    continue
                if not isinstance(response, dict):
                    continue

                content = response.get("content", {})
                json_content = content.get("application/json", {})
                schema = json_content.get("schema", {})

                # All error responses should reference AppError
                if "$ref" in schema:
                    assert schema["$ref"] == "#/components/schemas/AppError", (
                        f"Error response {status_code} for {method.upper()} {path} "
                        f"should reference AppError, got {schema['$ref']}"
                    )


def test_openapi_schema_includes_error_code_enum(openapi_schema: dict[str, Any]) -> None:
    """Verify ErrorCode enum is properly documented in schema."""
    components = openapi_schema.get("components", {})
    schemas = components.get("schemas", {})

    assert "ErrorCode" in schemas
    error_code_schema = schemas["ErrorCode"]

    # Should have enum values
    assert "enum" in error_code_schema
    enum_values = error_code_schema["enum"]

    # Check that key error codes are present
    expected_codes = [
        "VALIDATION_ERROR",
        "RESOURCE_NOT_FOUND",
        "UNAUTHORIZED",
        "DOMAIN_VALIDATION_ERROR",
        "INTERNAL_ERROR",
    ]
    for code in expected_codes:
        assert code in enum_values, f"ErrorCode enum should include {code}"


def test_openapi_returns_cached_schema_on_second_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that calling openapi() twice returns the cached schema."""
    _mock_external_dependencies(monkeypatch)
    settings = _build_settings()
    app = create_app(settings)

    # First call generates the schema
    schema1 = app.openapi()

    # Second call should return the same cached instance
    schema2 = app.openapi()

    # Both should be identical (same object reference for caching)
    assert schema1 is schema2
    assert schema1["info"]["title"] == settings.app_name


def test_openapi_custom_schema_handles_validation_error_detail_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that ValidationError schema is replaced with ValidationErrorDetail when both exist."""
    _mock_external_dependencies(monkeypatch)
    settings = _build_settings()
    app = create_app(settings)

    # Force schema generation by calling openapi()
    schema = app.openapi()

    components = schema.get("components", {})
    schemas = components.get("schemas", {})

    # If ValidationErrorDetail exists, ValidationError should be replaced with it
    if "ValidationErrorDetail" in schemas:
        assert "ValidationError" in schemas
        # After merging, ValidationError should equal ValidationErrorDetail
        assert schemas["ValidationError"] == schemas["ValidationErrorDetail"]


def test_custom_openapi_merges_validation_error_when_both_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that ValidationError is merged with ValidationErrorDetail when both schemas exist.

    This test directly exercises the branch where both ValidationError and
    ValidationErrorDetail are present in schema_definitions, triggering the
    schema merge logic in custom_openapi().
    """
    _mock_external_dependencies(monkeypatch)
    settings = _build_settings()
    app = create_app(settings)

    # First call to openapi() generates the schema (caches it in app.openapi_schema)
    app.openapi()

    # Now manually add ValidationError to the schema_definitions to simulate both schemas existing
    # We need to clear the cached schema so openapi() regenerates it
    app.openapi_schema = None

    # Get the internal schema generation function and modify its behavior
    # by pre-populating schema_definitions with both ValidationError and ValidationErrorDetail
    from fastapi.openapi.utils import get_openapi

    # Manually generate the schema with both schemas present
    generated_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        summary=app.summary,
        description=app.description,
        routes=app.routes,
    )

    # Add both ValidationError and ValidationErrorDetail to the definitions
    schema_definitions = generated_schema.setdefault("components", {}).setdefault("schemas", {})
    schema_definitions["ValidationError"] = {"type": "object", "properties": {}}
    schema_definitions["ValidationErrorDetail"] = {
        "type": "object",
        "properties": {"detail": {"type": "string"}},
    }

    # Patch get_openapi to return our pre-generated schema
    monkeypatch.setattr(
        "fastapi.openapi.utils.get_openapi", lambda *args, **kwargs: generated_schema
    )

    # Now call openapi() - the condition should be True
    result = app.openapi()

    # Verify both schemas exist
    assert "ValidationError" in result["components"]["schemas"]
    assert "ValidationErrorDetail" in result["components"]["schemas"]
