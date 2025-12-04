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


class _DummyConnection:
    """Dummy connection that simulates SurrealDB connection operations."""

    async def query(self, query: str, params: dict | None = None) -> list:
        """Simulate a query operation, returning empty results."""
        return []


class _DummySurrealDBPool:
    """Dummy SurrealDB pool with working acquire context manager."""

    def __init__(self, healthy: bool = True) -> None:
        """Initialize with configurable health status."""
        self._healthy = healthy

    def acquire(self) -> _DummySurrealDBPoolContext:
        """Return a context manager that yields a dummy connection."""
        return _DummySurrealDBPoolContext()

    async def close(self) -> None:
        """Simulate pool shutdown."""
        return None

    async def health_check(self) -> bool:
        """Return the configured health status."""
        return self._healthy


class _DummySurrealDBPoolContext:
    """Context manager for _DummySurrealDBPool.acquire()."""

    async def __aenter__(self) -> _DummyConnection:
        """Return a dummy connection on enter."""
        return _DummyConnection()

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """No cleanup needed."""
        return None


class _DummyResource:
    """Dummy resource for Elasticsearch client mock."""

    def __init__(self, healthy: bool = True) -> None:
        """Initialize with configurable health status."""
        self._healthy = healthy

    async def close(self) -> None:
        return None

    async def health_check(self) -> bool:
        """Return the configured health status."""
        return self._healthy


def _generate_test_credential(prefix: str) -> str:
    return f"{prefix}Aa1!{secrets.token_hex(4)}"


def _mock_external_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_surreal_pool(_settings: Settings) -> _DummySurrealDBPool:
        return _DummySurrealDBPool()

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

    @pytest.mark.usecase("UC-EXAMPLE-007")
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

    @pytest.mark.usecase("UC-EXAMPLE-008")
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

    @pytest.mark.usecase("UC-EXAMPLE-009")
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

    @pytest.mark.usecase("UC-EXAMPLE-010")
    def test_list_processed_messages_validation_error_invalid_page(
        self, integration_client: TestClient, test_settings: Settings
    ) -> None:
        api_prefix = test_settings.api_prefix
        response = integration_client.get(f"{api_prefix}/examples/processed-messages?page=0")

        assert response.status_code == 400
        payload = response.json()

        assert payload["code"] == "VALIDATION_ERROR"
        assert payload["statusCode"] == 400

    @pytest.mark.usecase("UC-EXAMPLE-011")
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

    @pytest.mark.usecase("UC-EXAMPLE-013")
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

    @pytest.mark.usecase("UC-EXAMPLE-014")
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

    @pytest.mark.usecase("UC-EXAMPLE-015")
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


class TestHealthCheckIntegration:
    """Tests for GET /api/v1/health readiness endpoint."""

    @pytest.mark.usecase("UC-HEALTH-002")
    def test_health_check_ok_when_dependencies_available(
        self, integration_client: TestClient, test_settings: Settings
    ) -> None:
        """Test health returns 'ok' when all dependencies are available."""
        api_prefix = test_settings.api_prefix
        response = integration_client.get(f"{api_prefix}/health")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"

    @pytest.mark.usecase("UC-HEALTH-003")
    def test_health_check_unhealthy_when_surrealdb_missing(
        self, monkeypatch: pytest.MonkeyPatch, test_settings: Settings
    ) -> None:
        """Test health returns 'unhealthy' when SurrealDB pool is missing."""

        async def _fake_surreal_pool_none(_settings: Settings) -> None:
            return None

        async def _fake_elasticsearch_wrapper(_settings: Settings) -> _DummyResource:
            return _DummyResource()

        monkeypatch.setattr("app.core.factory.create_surrealdb_pool", _fake_surreal_pool_none)
        monkeypatch.setattr(
            "app.core.factory.create_elasticsearch_wrapper", _fake_elasticsearch_wrapper
        )

        app = create_app(test_settings)
        with TestClient(app) as client:
            api_prefix = test_settings.api_prefix
            response = client.get(f"{api_prefix}/health")

            assert response.status_code == 200
            payload = response.json()
            assert payload["status"] == "unhealthy"

    @pytest.mark.usecase("UC-HEALTH-004")
    def test_health_check_unhealthy_when_elasticsearch_missing(
        self, monkeypatch: pytest.MonkeyPatch, test_settings: Settings
    ) -> None:
        """Test health returns 'unhealthy' when Elasticsearch client is missing."""

        async def _fake_surreal_pool(_settings: Settings) -> _DummySurrealDBPool:
            return _DummySurrealDBPool()

        async def _fake_elasticsearch_wrapper_none(_settings: Settings) -> None:
            return None

        monkeypatch.setattr("app.core.factory.create_surrealdb_pool", _fake_surreal_pool)
        monkeypatch.setattr(
            "app.core.factory.create_elasticsearch_wrapper", _fake_elasticsearch_wrapper_none
        )

        app = create_app(test_settings)
        with TestClient(app) as client:
            api_prefix = test_settings.api_prefix
            response = client.get(f"{api_prefix}/health")

            assert response.status_code == 200
            payload = response.json()
            assert payload["status"] == "unhealthy"

    @pytest.mark.usecase("UC-HEALTH-005")
    def test_health_check_degraded_on_transient_failures(
        self, monkeypatch: pytest.MonkeyPatch, test_settings: Settings
    ) -> None:
        """Test health returns 'degraded' when dependencies experience transient failures."""

        async def _fake_surreal_pool_unhealthy(_settings: Settings) -> _DummySurrealDBPool:
            return _DummySurrealDBPool(healthy=False)

        async def _fake_elasticsearch_wrapper(_settings: Settings) -> _DummyResource:
            return _DummyResource(healthy=True)

        monkeypatch.setattr("app.core.factory.create_surrealdb_pool", _fake_surreal_pool_unhealthy)
        monkeypatch.setattr(
            "app.core.factory.create_elasticsearch_wrapper", _fake_elasticsearch_wrapper
        )

        app = create_app(test_settings)
        with TestClient(app) as client:
            api_prefix = test_settings.api_prefix
            response = client.get(f"{api_prefix}/health")

            assert response.status_code == 200
            payload = response.json()
            assert payload["status"] == "degraded"


class TestSampleEndpoint:
    """Tests for GET /api/v1/examples/sample endpoint."""

    @pytest.mark.usecase("UC-EXAMPLE-001")
    def test_sample_endpoint_returns_demo_response(
        self, integration_client: TestClient, test_settings: Settings
    ) -> None:
        """Test that sample endpoint returns hardcoded demo response."""
        api_prefix = test_settings.api_prefix
        response = integration_client.get(f"{api_prefix}/examples/sample")

        assert response.status_code == 200
        payload = response.json()

        assert payload["result"] == "[DEMO] Sample Result"
        assert payload["original_length"] == 13
        assert "processed_at" in payload


class TestProcessEndpoint:
    """Tests for POST /api/v1/examples/process endpoint."""

    @pytest.mark.usecase("UC-EXAMPLE-002")
    def test_process_endpoint_success_with_valid_message(
        self, integration_client: TestClient, test_settings: Settings
    ) -> None:
        """Test process endpoint succeeds with valid message."""
        api_prefix = test_settings.api_prefix
        response = integration_client.post(
            f"{api_prefix}/examples/process",
            json={"message": "Hello World", "type": "info"},
        )

        assert response.status_code == 200
        payload = response.json()

        assert "result" in payload
        assert "processed_at" in payload
        assert payload["original_length"] == 11

    @pytest.mark.usecase("UC-EXAMPLE-003")
    def test_process_endpoint_fails_with_whitespace_only_message(
        self, integration_client: TestClient, test_settings: Settings
    ) -> None:
        """Test process endpoint fails with whitespace-only message."""
        api_prefix = test_settings.api_prefix
        response = integration_client.post(
            f"{api_prefix}/examples/process",
            json={"message": "   ", "type": "info"},
        )

        assert response.status_code == 400
        payload = response.json()
        assert payload["code"] == "VALIDATION_ERROR"

    @pytest.mark.usecase("UC-EXAMPLE-004")
    def test_process_endpoint_fails_with_message_too_long(
        self, integration_client: TestClient, test_settings: Settings
    ) -> None:
        """Test process endpoint fails with message exceeding 500 chars."""
        api_prefix = test_settings.api_prefix
        long_message = "x" * 501
        response = integration_client.post(
            f"{api_prefix}/examples/process",
            json={"message": long_message, "type": "info"},
        )

        assert response.status_code == 400
        payload = response.json()
        assert payload["code"] == "VALIDATION_ERROR"

    @pytest.mark.usecase("UC-EXAMPLE-005")
    def test_process_endpoint_fails_with_empty_message(
        self, integration_client: TestClient, test_settings: Settings
    ) -> None:
        """Test process endpoint fails with empty message (0 chars)."""
        api_prefix = test_settings.api_prefix
        response = integration_client.post(
            f"{api_prefix}/examples/process",
            json={"message": "", "type": "info"},
        )

        assert response.status_code == 400
        payload = response.json()
        assert payload["code"] == "VALIDATION_ERROR"

    @pytest.mark.usecase("UC-EXAMPLE-006")
    def test_process_endpoint_fails_with_invalid_message_type(
        self, integration_client: TestClient, test_settings: Settings
    ) -> None:
        """Test process endpoint fails with invalid message type."""
        api_prefix = test_settings.api_prefix
        response = integration_client.post(
            f"{api_prefix}/examples/process",
            json={"message": "Hello", "type": "invalid_type"},
        )

        assert response.status_code == 400
        payload = response.json()
        assert payload["code"] == "VALIDATION_ERROR"


class TestListProcessedMessagesValidation:
    """Additional validation tests for processed messages list endpoint."""

    @pytest.mark.usecase("UC-EXAMPLE-012")
    def test_list_processed_messages_fails_with_page_size_too_large(
        self, integration_client: TestClient, test_settings: Settings
    ) -> None:
        """Test list fails with page_size exceeding MAX_PAGE_SIZE (1000)."""
        api_prefix = test_settings.api_prefix
        response = integration_client.get(
            f"{api_prefix}/examples/processed-messages?page_size=1001"
        )

        assert response.status_code == 400
        payload = response.json()
        assert payload["code"] == "VALIDATION_ERROR"
