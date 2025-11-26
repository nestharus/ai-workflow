"""Integration tests verifying all exception handlers return standardized AppError envelopes.

This module tests that validation errors, domain errors, and internal errors all return
consistent AppError envelope responses with the appropriate code, message, statusCode,
and details fields.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import dependencies as api_dependencies
from app.core import dependencies as core_dependencies
from app.core.errors import DomainValidationError, ResourceNotFoundError, UnauthorizedError
from app.core.factory import create_app
from app.core.settings import Settings


class _DummyResource:
    async def close(self) -> None:  # pragma: no cover - trivial stub
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


def _build_settings() -> Settings:
    return Settings(
        include_error_body=False,
        surrealdb_user=os.getenv("SURREALDB_USER") or _generate_test_credential("User"),
        surrealdb_pass=os.getenv("SURREALDB_PASS") or _generate_test_credential("Pass"),
    )


def _create_test_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Factory that builds a TestClient for error handler testing."""
    _mock_external_dependencies(monkeypatch)
    monkeypatch.setenv("SURREALDB_USER", _generate_test_credential("User"))
    monkeypatch.setenv("SURREALDB_PASS", _generate_test_credential("Pass"))
    settings = _build_settings()
    monkeypatch.setattr("app.core.dependencies.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.v1.dependencies.get_settings", lambda: settings)
    app = create_app(settings)
    app.dependency_overrides[core_dependencies.get_settings] = lambda: settings
    app.dependency_overrides[api_dependencies.get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client


@pytest.fixture
def error_test_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    yield from _create_test_client(monkeypatch)


def _assert_app_error_structure(payload: dict[str, Any]) -> None:
    """Assert that the payload has the required AppError fields."""
    assert "code" in payload, "AppError must have 'code' field"
    assert "message" in payload, "AppError must have 'message' field"
    assert "statusCode" in payload, "AppError must have 'statusCode' field (camelCase alias)"
    assert "status_code" not in payload, "AppError should use 'statusCode' alias, not 'status_code'"


class TestValidationErrorReturnsAppError:
    """Tests for validation errors returning AppError envelope."""

    def test_validation_error_returns_app_error(self, error_test_client: TestClient) -> None:
        """Verify validation errors are wrapped in AppError envelope."""
        api_prefix = error_test_client.app.state.settings.api_prefix
        response = error_test_client.post(f"{api_prefix}/examples/process", json={})

        assert response.status_code == 400
        payload = response.json()

        _assert_app_error_structure(payload)
        assert payload["code"] == "VALIDATION_ERROR"
        assert payload["message"] == "Request validation failed"
        assert payload["statusCode"] == 400
        assert "details" in payload
        assert "detail" in payload["details"]

    def test_validation_error_details_contain_field_errors(
        self, error_test_client: TestClient
    ) -> None:
        """Verify validation error details contain proper field-level errors."""
        api_prefix = error_test_client.app.state.settings.api_prefix
        response = error_test_client.post(f"{api_prefix}/examples/process", json={})

        payload = response.json()
        detail_list = payload["details"]["detail"]

        assert len(detail_list) >= 1
        first_error = detail_list[0]
        assert "loc" in first_error
        assert "msg" in first_error
        assert "type" in first_error


class TestDomainErrorReturnsAppError:
    """Tests for domain errors returning AppError envelope."""

    def test_resource_not_found_error_returns_app_error(
        self, error_test_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify ResourceNotFoundError is wrapped in AppError envelope."""
        api_prefix = error_test_client.app.state.settings.api_prefix

        # Mock the service to raise ResourceNotFoundError
        mock_service = AsyncMock()
        mock_service.process.side_effect = ResourceNotFoundError("Example not found")

        with patch(
            "app.api.v1.dependencies.get_example_service",
            return_value=mock_service,
        ):
            error_test_client.app.dependency_overrides[
                api_dependencies.get_example_service
            ] = lambda: mock_service
            response = error_test_client.post(
                f"{api_prefix}/examples/process",
                json={"message": "test", "type": "info"},
            )

        assert response.status_code == 404
        payload = response.json()

        _assert_app_error_structure(payload)
        assert payload["code"] == "RESOURCE_NOT_FOUND"
        assert payload["statusCode"] == 404

    def test_domain_validation_error_returns_app_error(
        self, error_test_client: TestClient
    ) -> None:
        """Verify DomainValidationError is wrapped in AppError envelope."""
        api_prefix = error_test_client.app.state.settings.api_prefix

        # Mock the service to raise DomainValidationError
        mock_service = AsyncMock()
        mock_service.process.side_effect = DomainValidationError("Invalid domain state")

        error_test_client.app.dependency_overrides[
            api_dependencies.get_example_service
        ] = lambda: mock_service
        response = error_test_client.post(
            f"{api_prefix}/examples/process",
            json={"message": "test", "type": "info"},
        )

        assert response.status_code == 400
        payload = response.json()

        _assert_app_error_structure(payload)
        assert payload["code"] == "DOMAIN_VALIDATION_ERROR"
        assert payload["statusCode"] == 400

    def test_unauthorized_error_returns_app_error(
        self, error_test_client: TestClient
    ) -> None:
        """Verify UnauthorizedError is wrapped in AppError envelope."""
        api_prefix = error_test_client.app.state.settings.api_prefix

        # Mock the service to raise UnauthorizedError
        mock_service = AsyncMock()
        mock_service.process.side_effect = UnauthorizedError("Access denied")

        error_test_client.app.dependency_overrides[
            api_dependencies.get_example_service
        ] = lambda: mock_service
        response = error_test_client.post(
            f"{api_prefix}/examples/process",
            json={"message": "test", "type": "info"},
        )

        assert response.status_code == 401
        payload = response.json()

        _assert_app_error_structure(payload)
        assert payload["code"] == "UNAUTHORIZED"
        assert payload["statusCode"] == 401


class TestInternalErrorReturnsAppError:
    """Tests for internal errors returning AppError envelope."""

    def test_internal_error_returns_app_error(
        self, error_test_client: TestClient
    ) -> None:
        """Verify unexpected exceptions are wrapped in AppError envelope."""
        api_prefix = error_test_client.app.state.settings.api_prefix

        # Mock the service to raise a generic Exception
        mock_service = AsyncMock()
        mock_service.process.side_effect = RuntimeError("Unexpected internal error")

        error_test_client.app.dependency_overrides[
            api_dependencies.get_example_service
        ] = lambda: mock_service
        response = error_test_client.post(
            f"{api_prefix}/examples/process",
            json={"message": "test", "type": "info"},
        )

        assert response.status_code == 500
        payload = response.json()

        _assert_app_error_structure(payload)
        assert payload["code"] == "INTERNAL_ERROR"
        assert payload["statusCode"] == 500
        assert payload["message"] == "Unexpected error while processing request"


class TestAllErrorResponsesHaveConsistentStructure:
    """Tests verifying all error types share the same top-level structure."""

    def test_all_error_responses_have_consistent_structure(
        self, error_test_client: TestClient
    ) -> None:
        """Verify all error types return responses with the same top-level fields."""
        api_prefix = error_test_client.app.state.settings.api_prefix

        # Collect responses from different error scenarios
        error_responses: list[dict[str, Any]] = []

        # 1. Validation error
        response = error_test_client.post(f"{api_prefix}/examples/process", json={})
        error_responses.append(("validation", response.status_code, response.json()))

        # 2. Domain error (ResourceNotFoundError)
        mock_service = AsyncMock()
        mock_service.process.side_effect = ResourceNotFoundError("Not found")
        error_test_client.app.dependency_overrides[
            api_dependencies.get_example_service
        ] = lambda: mock_service
        response = error_test_client.post(
            f"{api_prefix}/examples/process",
            json={"message": "test", "type": "info"},
        )
        error_responses.append(("domain", response.status_code, response.json()))

        # 3. Internal error
        mock_service.process.side_effect = RuntimeError("Internal failure")
        response = error_test_client.post(
            f"{api_prefix}/examples/process",
            json={"message": "test", "type": "info"},
        )
        error_responses.append(("internal", response.status_code, response.json()))

        # Verify all responses have the same top-level structure
        required_fields = {"code", "message", "statusCode"}
        for error_type, status_code, payload in error_responses:
            assert required_fields.issubset(
                payload.keys()
            ), f"{error_type} error (status {status_code}) missing required fields"

            # Verify statusCode uses camelCase alias
            assert (
                "statusCode" in payload
            ), f"{error_type} error should use 'statusCode' alias"
            assert (
                "status_code" not in payload
            ), f"{error_type} error should not have 'status_code'"

            # Verify code is from ErrorCode enum
            valid_codes = {
                "VALIDATION_ERROR",
                "RESOURCE_NOT_FOUND",
                "UNAUTHORIZED",
                "DOMAIN_VALIDATION_ERROR",
                "INTERNAL_ERROR",
                "EXAMPLE_INVALID",
            }
            assert (
                payload["code"] in valid_codes
            ), f"{error_type} error has invalid code: {payload['code']}"
