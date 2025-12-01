"""Integration tests for example endpoints with DuckDB CSV querying.

These tests verify the full request-response flow through the API endpoints
that query processed messages from CSV data via DuckDB.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.core.factory import create_app
from app.core.settings import Settings


class _DummyResource:
    async def close(self) -> None:
        return None


def _generate_test_credential(prefix: str) -> str:
    return f"{prefix}Aa1!{secrets.token_hex(4)}"


def _mock_external_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_surreal_pool(_settings: Settings) -> _DummyResource:
        return _DummyResource()

    async def _fake_elasticsearch_wrapper(_settings: Settings) -> _DummyResource:
        return _DummyResource()

    monkeypatch.setattr("app.core.factory.create_surrealdb_pool", _fake_surreal_pool)
    monkeypatch.setattr(
        "app.core.factory.create_elasticsearch_wrapper", _fake_elasticsearch_wrapper
    )


def _build_test_settings() -> Settings:
    return Settings(
        surrealdb_user=_generate_test_credential("User"),
        surrealdb_pass=_generate_test_credential("Pass"),
        csv_data_path=str(Path(__file__).parent.parent.parent / "data" / "csv"),
    )


@pytest.fixture
def test_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("SURREALDB_USER", _generate_test_credential("User"))
    monkeypatch.setenv("SURREALDB_PASS", _generate_test_credential("Pass"))
    return _build_test_settings()


@pytest.fixture
def integration_client(
    monkeypatch: pytest.MonkeyPatch, test_settings: Settings
) -> Iterator[TestClient]:
    _mock_external_dependencies(monkeypatch)
    app = create_app(test_settings)
    with TestClient(app) as client:
        yield client


@pytest_asyncio.fixture
async def async_integration_client(
    monkeypatch: pytest.MonkeyPatch, test_settings: Settings
) -> AsyncIterator[httpx.AsyncClient]:
    _mock_external_dependencies(monkeypatch)
    app = create_app(test_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


class TestListProcessedMessages:
    """Tests for GET /api/v1/examples/processed-messages endpoint."""

    def test_list_processed_messages_success(
        self, integration_client: TestClient, test_settings: Settings
    ) -> None:
        api_prefix = test_settings.api_prefix
        response = integration_client.get(f"{api_prefix}/examples/processed-messages")

        assert response.status_code == 200
        payload = response.json()

        assert "items" in payload
        assert "total" in payload
        assert "page" in payload
        assert "page_size" in payload

        assert payload["page"] == 1
        assert payload["page_size"] == 10
        assert payload["total"] == 10
        assert len(payload["items"]) == 10

        first_item = payload["items"][0]
        assert "id" in first_item
        assert "content" in first_item
        assert "type" in first_item
        assert "processed_at" in first_item

    def test_list_processed_messages_pagination(
        self, integration_client: TestClient, test_settings: Settings
    ) -> None:
        api_prefix = test_settings.api_prefix
        response = integration_client.get(
            f"{api_prefix}/examples/processed-messages?page=1&page_size=3"
        )

        assert response.status_code == 200
        payload = response.json()

        assert payload["page"] == 1
        assert payload["page_size"] == 3
        assert payload["total"] == 10
        assert len(payload["items"]) == 3

    def test_list_processed_messages_page_2(
        self, integration_client: TestClient, test_settings: Settings
    ) -> None:
        api_prefix = test_settings.api_prefix
        response = integration_client.get(
            f"{api_prefix}/examples/processed-messages?page=2&page_size=3"
        )

        assert response.status_code == 200
        payload = response.json()

        assert payload["page"] == 2
        assert payload["page_size"] == 3
        assert len(payload["items"]) == 3

    def test_list_processed_messages_validation_error_invalid_page(
        self, integration_client: TestClient, test_settings: Settings
    ) -> None:
        api_prefix = test_settings.api_prefix
        response = integration_client.get(f"{api_prefix}/examples/processed-messages?page=0")

        assert response.status_code == 400
        payload = response.json()

        assert payload["code"] == "VALIDATION_ERROR"
        assert payload["statusCode"] == 400

    def test_list_processed_messages_validation_error_invalid_page_size(
        self, integration_client: TestClient, test_settings: Settings
    ) -> None:
        api_prefix = test_settings.api_prefix
        response = integration_client.get(f"{api_prefix}/examples/processed-messages?page_size=0")

        assert response.status_code == 400
        payload = response.json()

        assert payload["code"] == "VALIDATION_ERROR"
        assert payload["statusCode"] == 400


class TestGetProcessedMessage:
    """Tests for GET /api/v1/examples/processed-messages/{id} endpoint."""

    def test_get_processed_message_success(
        self, integration_client: TestClient, test_settings: Settings
    ) -> None:
        api_prefix = test_settings.api_prefix
        response = integration_client.get(f"{api_prefix}/examples/processed-messages/msg_001")

        assert response.status_code == 200
        payload = response.json()

        assert payload["id"] == "msg_001"
        assert "[PROCESSED]" in payload["content"]
        assert payload["type"] == "info"
        assert "processed_at" in payload

    def test_get_processed_message_not_found(
        self, integration_client: TestClient, test_settings: Settings
    ) -> None:
        api_prefix = test_settings.api_prefix
        response = integration_client.get(
            f"{api_prefix}/examples/processed-messages/nonexistent_id"
        )

        assert response.status_code == 404
        payload = response.json()

        assert payload["code"] == "RESOURCE_NOT_FOUND"
        assert payload["statusCode"] == 404
        assert "nonexistent_id" in payload["message"]

    def test_get_processed_message_different_types(
        self, integration_client: TestClient, test_settings: Settings
    ) -> None:
        api_prefix = test_settings.api_prefix

        info_response = integration_client.get(f"{api_prefix}/examples/processed-messages/msg_001")
        assert info_response.status_code == 200
        assert info_response.json()["type"] == "info"

        warning_response = integration_client.get(
            f"{api_prefix}/examples/processed-messages/msg_002"
        )
        assert warning_response.status_code == 200
        assert warning_response.json()["type"] == "warning"

        error_response = integration_client.get(f"{api_prefix}/examples/processed-messages/msg_003")
        assert error_response.status_code == 200
        assert error_response.json()["type"] == "error"
