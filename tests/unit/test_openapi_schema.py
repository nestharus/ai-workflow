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
        surrealdb_pass="PassAa1!OpenApi",  # noqa: S106 - safe test credential
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
