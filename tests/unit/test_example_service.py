"""Unit tests for ExampleService configuration-driven behavior.

This module tests that ExampleService correctly derives its message prefix
from the injected Settings, demonstrating configuration-driven behavior via DI.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime

import pytest
from pydantic import ValidationError

from app.contracts.example_contract import EmptyMessageError, ExampleRequest
from app.core.settings import Settings
from app.services.example_service import ExampleService


class FakeExampleRepository:
    """Fake repository for testing ExampleService in isolation.

    Implements ExampleRepositoryProtocol without database dependencies,
    allowing unit tests to run without infrastructure.
    """

    def __init__(self) -> None:
        self.saved: list[tuple[str, str]] = []

    async def save_processed_message(
        self, *, content: str, message_type: str, processed_at: datetime
    ) -> None:
        self.saved.append((content, message_type))


def _generate_test_credential(prefix: str) -> str:
    """Generate a valid credential string for Settings validation."""
    return f"{prefix}Aa1!{secrets.token_hex(4)}"


def _build_settings(*, debug: bool, example_prefix: str = "[PROCESSED]") -> Settings:
    """Build a Settings instance with the specified debug flag."""
    return Settings(
        debug=debug,
        example_prefix=example_prefix,
        surrealdb_user=os.getenv("SURREALDB_USER") or _generate_test_credential("User"),
        surrealdb_pass=os.getenv("SURREALDB_PASS") or _generate_test_credential("Pass"),
    )


@pytest.fixture
def fake_repository() -> FakeExampleRepository:
    """Provide a fake repository for service tests."""
    return FakeExampleRepository()


@pytest.fixture
def settings_debug_false() -> Settings:
    """Provide Settings with debug=False."""
    return _build_settings(debug=False, example_prefix="[CUSTOM]")


@pytest.fixture
def settings_debug_true() -> Settings:
    """Provide Settings with debug=True."""
    return _build_settings(debug=True)


@pytest.mark.asyncio
async def test_process_uses_processed_prefix_when_debug_false(
    fake_repository: FakeExampleRepository,
    settings_debug_false: Settings,
) -> None:
    """ExampleService uses configured prefix when Settings.debug is False."""
    service = ExampleService(repository=fake_repository, settings=settings_debug_false)
    request = ExampleRequest(message="Hello World", type="info")

    response = await service.process(request)

    assert response.result.startswith("[CUSTOM]")
    assert "[INFO]" in response.result
    assert "Hello World" in response.result
    assert fake_repository.saved[0][1] == "info"


@pytest.mark.asyncio
async def test_process_uses_debug_prefix_when_debug_true(
    fake_repository: FakeExampleRepository,
    settings_debug_true: Settings,
) -> None:
    """ExampleService uses [DEBUG] prefix when Settings.debug is True."""
    service = ExampleService(repository=fake_repository, settings=settings_debug_true)
    request = ExampleRequest(message="Test Message", type="warning")

    response = await service.process(request)

    assert response.result.startswith("[DEBUG]")
    assert "[WARNING]" in response.result
    assert "Test Message" in response.result
    assert fake_repository.saved[0][1] == "warning"


def test_example_request_rejects_empty_message() -> None:
    """ExampleRequest surfaces EmptyMessageError for empty message content."""
    with pytest.raises(ValidationError) as excinfo:
        ExampleRequest(message="", type="info")
    errors = excinfo.value.errors()
    assert any(
        err.get("type") == "value_error" and EmptyMessageError._MESSAGE in err.get("msg", "")
        for err in errors
    )


def test_example_request_rejects_whitespace_message() -> None:
    """ExampleRequest surfaces EmptyMessageError for whitespace-only message."""
    with pytest.raises(ValidationError) as excinfo:
        ExampleRequest(message="   ", type="warning")
    errors = excinfo.value.errors()
    assert any(
        err.get("type") == "value_error" and EmptyMessageError._MESSAGE in err.get("msg", "")
        for err in errors
    )


@pytest.mark.asyncio
async def test_process_preserves_original_message_length(
    fake_repository: FakeExampleRepository,
    settings_debug_false: Settings,
) -> None:
    """ExampleService correctly reports original message length."""
    service = ExampleService(repository=fake_repository, settings=settings_debug_false)
    message = "Sample input"
    request = ExampleRequest(message=message, type="error")

    response = await service.process(request)

    assert response.original_length == len(message)
