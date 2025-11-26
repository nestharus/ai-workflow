from __future__ import annotations

import os
import secrets
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import dependencies as api_dependencies
from app.core import dependencies as core_dependencies
from app.core.factory import create_app
from app.core.settings import Settings


class _DummyResource:
    async def close(self) -> None:  # pragma: no cover - trivial stub
        return None


def _expected_detail() -> list[dict[str, str]]:
    return [
        {
            "loc": ["body", "message"],
            "msg": "Field required",
            "type": "missing",
        }
    ]


def _expected_whitespace_detail() -> list[dict[str, Any]]:
    return [
        {
            "loc": ["body", "message"],
            "msg": "Value error, ExampleRequest.message must not be empty or whitespace only",
            "type": "value_error",
            "ctx": {"error": "ExampleRequest.message must not be empty or whitespace only"},
        }
    ]


def _mock_external_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_surreal_pool(_settings: Settings) -> _DummyResource:
        return _DummyResource()

    async def _fake_elasticsearch_wrapper(_settings: Settings) -> _DummyResource:
        return _DummyResource()

    monkeypatch.setattr("app.core.factory.create_surrealdb_pool", _fake_surreal_pool)
    monkeypatch.setattr(
        "app.core.factory.create_elasticsearch_wrapper", _fake_elasticsearch_wrapper
    )


def _generate_test_credential(prefix: str) -> str:
    return f"{prefix}Aa1!{secrets.token_hex(4)}"


def _build_settings(include_error_body: bool) -> Settings:
    return Settings(
        include_error_body=include_error_body,
        surrealdb_user=os.getenv("SURREALDB_USER") or _generate_test_credential("User"),
        surrealdb_pass=os.getenv("SURREALDB_PASS") or _generate_test_credential("Pass"),
    )


def _create_validation_client(
    monkeypatch: pytest.MonkeyPatch, *, include_error_body: bool
) -> Iterator[TestClient]:
    """Factory that builds a TestClient with the given include_error_body setting."""
    _mock_external_dependencies(monkeypatch)
    monkeypatch.setenv("SURREALDB_USER", _generate_test_credential("User"))
    monkeypatch.setenv("SURREALDB_PASS", _generate_test_credential("Pass"))
    settings = _build_settings(include_error_body=include_error_body)
    monkeypatch.setattr("app.core.dependencies.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.v1.dependencies.get_settings", lambda: settings)
    app = create_app(settings)
    app.dependency_overrides[core_dependencies.get_settings] = lambda: settings
    app.dependency_overrides[api_dependencies.get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client


@pytest.fixture
def validation_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    yield from _create_validation_client(monkeypatch, include_error_body=False)


@pytest.fixture
def validation_client_with_body(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    yield from _create_validation_client(monkeypatch, include_error_body=True)


def test_validation_error_body_omitted_when_disabled(validation_client: TestClient) -> None:
    api_prefix = validation_client.app.state.settings.api_prefix
    response = validation_client.post(f"{api_prefix}/examples/process", json={})
    assert response.status_code == 400
    payload = response.json()

    # Verify AppError envelope structure
    assert payload["code"] == "VALIDATION_ERROR"
    assert payload["message"] == "Request validation failed"
    assert payload["statusCode"] == 400

    # Verify validation details in the details field
    assert "details" in payload
    assert "body" not in payload["details"]
    assert payload["details"]["detail"] == _expected_detail()


def test_validation_error_body_echoed_when_enabled(
    validation_client_with_body: TestClient,
) -> None:
    api_prefix = validation_client_with_body.app.state.settings.api_prefix
    response = validation_client_with_body.post(
        f"{api_prefix}/examples/process", json={"type": "info"}
    )
    assert response.status_code == 400
    payload = response.json()

    # Verify AppError envelope structure
    assert payload["code"] == "VALIDATION_ERROR"
    assert payload["message"] == "Request validation failed"
    assert payload["statusCode"] == 400

    # Verify validation details in the details field with body echoed
    assert "details" in payload
    assert payload["details"]["body"] == {"type": "info"}
    assert payload["details"]["detail"] == _expected_detail()


def test_validation_error_for_whitespace_message(validation_client: TestClient) -> None:
    api_prefix = validation_client.app.state.settings.api_prefix
    response = validation_client.post(
        f"{api_prefix}/examples/process", json={"message": "   ", "type": "info"}
    )
    assert response.status_code == 400
    payload = response.json()

    # Verify AppError envelope structure
    assert payload["code"] == "VALIDATION_ERROR"
    assert payload["message"] == "Request validation failed"
    assert payload["statusCode"] == 400

    # Verify validation details in the details field
    assert "details" in payload
    assert payload["details"]["detail"] == _expected_whitespace_detail()
