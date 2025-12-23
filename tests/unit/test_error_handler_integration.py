"""Integration tests verifying all exception handlers return standardized AppError envelopes.

This module tests that validation errors, domain errors, and internal errors all return
consistent AppError envelope responses with the appropriate code, message, statusCode,
and details fields.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import dependencies as api_dependencies
from app.core import dependencies as core_dependencies
from app.core.errors import (
    DomainError,
    DomainValidationError,
    ResourceNotFoundError,
    UnauthorizedError,
)
from app.core.exceptions import (
    _sanitize_validation_errors,
    domain_exception_handler,
    validation_exception_handler,
)
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

    async def _fake_duckdb_client(_settings: Settings) -> _DummyResource:
        return _DummyResource()

    monkeypatch.setattr("app.core.factory.create_surrealdb_pool", _fake_surreal_pool)
    monkeypatch.setattr(
        "app.core.factory.create_elasticsearch_wrapper", _fake_elasticsearch_wrapper
    )
    monkeypatch.setattr("app.core.factory.create_duckdb_client", _fake_duckdb_client)


def _build_settings() -> Settings:
    return Settings(
        include_error_body=False,
        surrealdb_user=_generate_test_credential("User"),
        surrealdb_pass=_generate_test_credential("Pass"),
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

        error_test_client.app.dependency_overrides[api_dependencies.get_example_service] = (
            lambda: mock_service
        )
        response = error_test_client.post(
            f"{api_prefix}/examples/process",
            json={"message": "test", "type": "info"},
        )

        assert response.status_code == 404
        payload = response.json()

        _assert_app_error_structure(payload)
        assert payload["code"] == "RESOURCE_NOT_FOUND"
        assert payload["statusCode"] == 404

    def test_domain_validation_error_returns_app_error(self, error_test_client: TestClient) -> None:
        """Verify DomainValidationError is wrapped in AppError envelope."""
        api_prefix = error_test_client.app.state.settings.api_prefix

        # Mock the service to raise DomainValidationError
        mock_service = AsyncMock()
        mock_service.process.side_effect = DomainValidationError("Invalid domain state")

        error_test_client.app.dependency_overrides[api_dependencies.get_example_service] = (
            lambda: mock_service
        )
        response = error_test_client.post(
            f"{api_prefix}/examples/process",
            json={"message": "test", "type": "info"},
        )

        assert response.status_code == 400
        payload = response.json()

        _assert_app_error_structure(payload)
        assert payload["code"] == "DOMAIN_VALIDATION_ERROR"
        assert payload["statusCode"] == 400

    def test_unauthorized_error_returns_app_error(self, error_test_client: TestClient) -> None:
        """Verify UnauthorizedError is wrapped in AppError envelope."""
        api_prefix = error_test_client.app.state.settings.api_prefix

        # Mock the service to raise UnauthorizedError
        mock_service = AsyncMock()
        mock_service.process.side_effect = UnauthorizedError("Access denied")

        error_test_client.app.dependency_overrides[api_dependencies.get_example_service] = (
            lambda: mock_service
        )
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

    def test_internal_error_raises_and_is_logged(
        self, error_test_client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Verify unexpected exceptions are caught by handler and logged."""
        api_prefix = error_test_client.app.state.settings.api_prefix

        # Mock the service to raise a generic Exception
        mock_service = AsyncMock()
        mock_service.process.side_effect = RuntimeError("Unexpected internal error")

        error_test_client.app.dependency_overrides[api_dependencies.get_example_service] = (
            lambda: mock_service
        )

        with pytest.raises(RuntimeError, match="Unexpected internal error"):
            error_test_client.post(
                f"{api_prefix}/examples/process",
                json={"message": "test", "type": "info"},
            )

        # Verify the exception handler logged the error with correct code
        assert "INTERNAL_ERROR" in caplog.text
        assert "Unexpected internal error" in caplog.text


class TestAllErrorResponsesHaveConsistentStructure:
    """Tests verifying all error types share the same top-level structure."""

    def test_non_server_error_responses_have_consistent_structure(
        self, error_test_client: TestClient
    ) -> None:
        """Verify validation and domain errors return responses with same top-level fields."""
        api_prefix = error_test_client.app.state.settings.api_prefix

        # Collect responses from different error scenarios (excluding 5xx which re-raise)
        error_responses: list[tuple[str, int, dict[str, Any]]] = []

        # 1. Validation error (400)
        response = error_test_client.post(f"{api_prefix}/examples/process", json={})
        error_responses.append(("validation", response.status_code, response.json()))

        # 2. Domain error - ResourceNotFoundError (404)
        mock_service = AsyncMock()
        mock_service.process.side_effect = ResourceNotFoundError("Not found")
        error_test_client.app.dependency_overrides[api_dependencies.get_example_service] = (
            lambda: mock_service
        )
        response = error_test_client.post(
            f"{api_prefix}/examples/process",
            json={"message": "test", "type": "info"},
        )
        error_responses.append(("resource_not_found", response.status_code, response.json()))

        # 3. Domain error - DomainValidationError (400)
        mock_service.process.side_effect = DomainValidationError("Invalid state")
        response = error_test_client.post(
            f"{api_prefix}/examples/process",
            json={"message": "test", "type": "info"},
        )
        error_responses.append(("domain_validation", response.status_code, response.json()))

        # Verify all responses have the same top-level structure
        required_fields = {"code", "message", "statusCode"}
        for error_type, status_code, payload in error_responses:
            assert required_fields.issubset(payload.keys()), (
                f"{error_type} error (status {status_code}) missing required fields"
            )

            # Verify statusCode uses camelCase alias
            assert "statusCode" in payload, f"{error_type} error should use 'statusCode' alias"
            assert "status_code" not in payload, f"{error_type} error should not have 'status_code'"

            # Verify code is from ErrorCode enum
            valid_codes = {
                "VALIDATION_ERROR",
                "RESOURCE_NOT_FOUND",
                "UNAUTHORIZED",
                "DOMAIN_VALIDATION_ERROR",
                "INTERNAL_ERROR",
                "EXAMPLE_INVALID",
            }
            assert payload["code"] in valid_codes, (
                f"{error_type} error has invalid code: {payload['code']}"
            )


class TestSanitizeValidationErrors:
    """Tests for _sanitize_validation_errors function."""

    def test_sanitize_with_json_serializable_context(self) -> None:
        """Test that JSON-serializable context values are preserved."""
        errors = [
            {
                "loc": ["body", "field"],
                "msg": "Invalid value",
                "type": "value_error",
                "ctx": {"pattern": r"^[a-z]+$", "limit": 100},
            }
        ]

        result = _sanitize_validation_errors(errors)

        assert len(result) == 1
        assert result[0].ctx is not None
        assert result[0].ctx["pattern"] == r"^[a-z]+$"
        assert result[0].ctx["limit"] == 100

    def test_sanitize_with_non_serializable_context_converts_to_string(self) -> None:
        """Test that non-JSON-serializable context values are converted to string."""

        class CustomObject:
            def __str__(self) -> str:
                return "custom_repr"

        errors = [
            {
                "loc": ["body", "field"],
                "msg": "Invalid value",
                "type": "value_error",
                "ctx": {"custom": CustomObject()},
            }
        ]

        result = _sanitize_validation_errors(errors)

        assert len(result) == 1
        assert result[0].ctx is not None
        assert result[0].ctx["custom"] == "custom_repr"

    def test_sanitize_truncates_at_max_validation_errors(self) -> None:
        """Test that sanitization stops at MAX_VALIDATION_ERRORS limit."""
        from app.contracts.example_contract import MAX_VALIDATION_ERRORS

        # Create more errors than the limit
        errors = [
            {"loc": ["body", f"field{i}"], "msg": f"Error {i}", "type": "value_error"}
            for i in range(MAX_VALIDATION_ERRORS + 10)
        ]

        result = _sanitize_validation_errors(errors)

        assert len(result) == MAX_VALIDATION_ERRORS

    def test_sanitize_with_no_context(self) -> None:
        """Test that errors without context are handled correctly."""
        errors = [{"loc": ["body", "field"], "msg": "Field required", "type": "missing"}]

        result = _sanitize_validation_errors(errors)

        assert len(result) == 1
        assert result[0].ctx is None


class TestValidationExceptionHandlerEdgeCases:
    """Tests for validation_exception_handler edge cases."""

    @pytest.mark.asyncio
    async def test_validation_handler_raises_typeerror_for_wrong_exception_type(
        self,
    ) -> None:
        """Test that validation handler raises TypeError for non-RequestValidationError."""
        from unittest.mock import Mock

        mock_request = Mock()

        with pytest.raises(TypeError):
            await validation_exception_handler(mock_request, ValueError("wrong type"))

    @pytest.mark.asyncio
    async def test_validation_handler_with_non_fastapi_app(self) -> None:
        """Test validation handler when app is not FastAPI instance."""
        from unittest.mock import Mock

        from fastapi.exceptions import RequestValidationError

        # Create a mock request with a non-FastAPI app
        mock_app = object()  # Not a FastAPI instance
        mock_request = Mock()
        mock_request.app = mock_app
        mock_request.method = "POST"
        mock_request.url = Mock()
        mock_request.url.path = "/test"

        # Create a RequestValidationError
        exc = RequestValidationError(
            errors=[{"loc": ["body", "field"], "msg": "test error", "type": "value_error"}]
        )

        # Call handler - should not error even with non-FastAPI app
        response = await validation_exception_handler(mock_request, exc)

        assert response.status_code == 400

    def test_validation_error_with_invalid_json_body(self, error_test_client: TestClient) -> None:
        """Verify validation handler handles invalid JSON body gracefully."""
        # Enable error body echoing for this test
        error_test_client.app.state.settings.include_error_body = True
        api_prefix = error_test_client.app.state.settings.api_prefix

        # Send raw bytes that are not valid JSON
        response = error_test_client.post(
            f"{api_prefix}/examples/process",
            content=b"not valid json {{{",
            headers={"Content-Type": "application/json"},
        )

        # Should still return 400 validation error, but body parsing would fail silently
        assert response.status_code == 400
        payload = response.json()
        assert payload["code"] == "VALIDATION_ERROR"


class TestDomainExceptionHandlerEdgeCases:
    """Tests for domain_exception_handler edge cases."""

    def test_domain_handler_raises_typeerror_for_wrong_exception_type(self) -> None:
        """Test that domain handler raises TypeError for non-DomainError."""
        from unittest.mock import Mock

        mock_request = Mock()

        with pytest.raises(TypeError):
            domain_exception_handler(mock_request, ValueError("wrong type"))

    def test_domain_handler_handles_generic_domain_error(
        self, error_test_client: TestClient
    ) -> None:
        """Verify generic DomainError (not a subclass) returns INTERNAL_ERROR."""
        api_prefix = error_test_client.app.state.settings.api_prefix

        # Mock the service to raise a generic DomainError
        mock_service = AsyncMock()
        mock_service.process.side_effect = DomainError("Generic domain error")

        error_test_client.app.dependency_overrides[api_dependencies.get_example_service] = (
            lambda: mock_service
        )
        response = error_test_client.post(
            f"{api_prefix}/examples/process",
            json={"message": "test", "type": "info"},
        )

        assert response.status_code == 500
        payload = response.json()

        assert payload["code"] == "INTERNAL_ERROR"
        assert payload["statusCode"] == 500
