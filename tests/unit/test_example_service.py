"""Unit tests for ExampleService configuration-driven behavior.

This module tests that ExampleService correctly derives its message prefix
from the injected Settings, demonstrating configuration-driven behavior via DI.
"""

from __future__ import annotations

import os
import secrets

import pytest

from app.contracts.example_contract import ExampleRequest
from app.core.settings import Settings
from app.services.example_service import ExampleService


class FakeExampleRepository:
    """Fake repository for testing ExampleService in isolation.

    Implements ExampleRepositoryProtocol without database dependencies,
    allowing unit tests to run without infrastructure.
    """

    async def get_prefix(self) -> str:
        """Return a stubbed prefix value."""
        return "[FAKE]"


def _generate_test_credential(prefix: str) -> str:
    """Generate a valid credential string for Settings validation."""
    return f"{prefix}Aa1!{secrets.token_hex(4)}"


def _build_settings(*, debug: bool) -> Settings:
    """Build a Settings instance with the specified debug flag."""
    return Settings(
        debug=debug,
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
    return _build_settings(debug=False)


@pytest.fixture
def settings_debug_true() -> Settings:
    """Provide Settings with debug=True."""
    return _build_settings(debug=True)


def test_process_uses_processed_prefix_when_debug_false(
    fake_repository: FakeExampleRepository,
    settings_debug_false: Settings,
) -> None:
    """ExampleService uses [PROCESSED] prefix when Settings.debug is False."""
    service = ExampleService(repository=fake_repository, settings=settings_debug_false)
    request = ExampleRequest(message="Hello World", type="info")

    response = service.process(request)

    assert response.result.startswith("[PROCESSED]")
    assert "[INFO]" in response.result
    assert "Hello World" in response.result


def test_process_uses_debug_prefix_when_debug_true(
    fake_repository: FakeExampleRepository,
    settings_debug_true: Settings,
) -> None:
    """ExampleService uses [DEBUG] prefix when Settings.debug is True."""
    service = ExampleService(repository=fake_repository, settings=settings_debug_true)
    request = ExampleRequest(message="Test Message", type="warning")

    response = service.process(request)

    assert response.result.startswith("[DEBUG]")
    assert "[WARNING]" in response.result
    assert "Test Message" in response.result


def test_process_preserves_original_message_length(
    fake_repository: FakeExampleRepository,
    settings_debug_false: Settings,
) -> None:
    """ExampleService correctly reports original message length."""
    service = ExampleService(repository=fake_repository, settings=settings_debug_false)
    message = "Sample input"
    request = ExampleRequest(message=message, type="error")

    response = service.process(request)

    assert response.original_length == len(message)
