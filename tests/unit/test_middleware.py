from __future__ import annotations

import os
import secrets

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.factory import create_app
from app.core.settings import Settings


class _DummyResource:
    async def close(self) -> None:  # pragma: no cover - trivial stub
        return None


def _generate_test_credential(prefix: str) -> str:
    return f"{prefix}Aa1!{secrets.token_hex(4)}"


def _build_settings(**overrides: str | bool | int) -> Settings:
    base: dict[str, str | bool | int] = {
        "surrealdb_user": os.getenv("SURREALDB_USER") or _generate_test_credential("User"),
        "surrealdb_pass": os.getenv("SURREALDB_PASS") or _generate_test_credential("Pass"),
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _mock_external_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_surreal_pool(settings: Settings) -> _DummyResource:
        return _DummyResource()

    async def _fake_elasticsearch_wrapper(settings: Settings) -> _DummyResource:
        return _DummyResource()

    monkeypatch.setattr("app.core.factory.create_surrealdb_pool", _fake_surreal_pool)
    monkeypatch.setattr(
        "app.core.factory.create_elasticsearch_wrapper", _fake_elasticsearch_wrapper
    )


def _add_test_route(app: FastAPI) -> None:
    @app.get("/echo")
    async def _echo() -> dict[str, str]:  # pragma: no cover - exercised via TestClient
        return {"status": "ok"}

    @app.get("/large")
    async def _large() -> str:  # pragma: no cover - exercised via TestClient
        return "x" * 2048


def test_security_headers_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_external_dependencies(monkeypatch)
    settings = _build_settings(enforce_https=False)
    app = create_app(settings)
    _add_test_route(app)

    with TestClient(app) as client:
        response = client.get("/echo")

    headers = response.headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "strict-transport-security" not in headers


def test_hsts_added_when_https_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_external_dependencies(monkeypatch)
    settings = _build_settings(enforce_https=True)
    app = create_app(settings)
    _add_test_route(app)

    with TestClient(app, base_url="https://testserver") as client:
        response = client.get("/echo")

    assert response.headers["strict-transport-security"].startswith("max-age=31536000")


def test_gzip_applied_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_external_dependencies(monkeypatch)
    settings = _build_settings(enable_gzip=True)
    app = create_app(settings)
    _add_test_route(app)

    with TestClient(app) as client:
        response = client.get("/large", headers={"Accept-Encoding": "gzip"})

    assert response.headers.get("content-encoding") == "gzip"
