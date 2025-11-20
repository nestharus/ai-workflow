from __future__ import annotations

import os
import secrets
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

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


def _mock_external_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_surreal_pool(settings: Settings) -> _DummyResource:
        return _DummyResource()

    async def _fake_elasticsearch_wrapper(settings: Settings) -> _DummyResource:
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


@pytest.fixture
def validation_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    _mock_external_dependencies(monkeypatch)
    app = create_app(_build_settings(include_error_body=False))
    with TestClient(app) as client:
        yield client


@pytest.fixture
def validation_client_with_body(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    _mock_external_dependencies(monkeypatch)
    app = create_app(_build_settings(include_error_body=True))
    with TestClient(app) as client:
        yield client


def test_validation_error_body_omitted_when_disabled(validation_client: TestClient) -> None:
    response = validation_client.post("/api/v1/example/process", json={})
    assert response.status_code == 400
    payload = response.json()
    assert "body" not in payload
    assert payload["detail"] == _expected_detail()


def test_validation_error_body_echoed_when_enabled(
    validation_client_with_body: TestClient,
) -> None:
    response = validation_client_with_body.post("/api/v1/example/process", json={"type": "info"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["body"] == {"type": "info"}
    assert payload["detail"] == _expected_detail()
