"""Unit tests for ExampleService configuration-driven behavior.

This module tests that ExampleService correctly derives its message prefix
from the injected Settings, demonstrating configuration-driven behavior via DI.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.contracts.example_contract import EmptyMessageError, ExampleRequest
from app.contracts.pagination import Paginated
from app.core.errors import ResourceNotFoundError
from app.core.settings import Settings
from app.repositories.example_repository import ProcessedMessage
from app.services.example_service import ExampleService


class FakeExampleRepository:
    """Fake repository for testing ExampleService in isolation.

    Implements ExampleRepositoryProtocol without database dependencies,
    allowing unit tests to run without infrastructure.
    """

    def __init__(self) -> None:
        self.saved: list[tuple[str, str]] = []
        self._messages: dict[str, ProcessedMessage] = {}
        self._all_messages: list[ProcessedMessage] = []

    async def save_processed_message(
        self, *, content: str, message_type: str, processed_at: datetime
    ) -> None:
        self.saved.append((content, message_type))

    async def get_by_id(self, id: str) -> ProcessedMessage | None:
        return self._messages.get(id)

    async def list_paginated(self, offset: int, limit: int) -> tuple[list[ProcessedMessage], int]:
        total = len(self._all_messages)
        messages = self._all_messages[offset : offset + limit]
        return messages, total

    def set_message(self, message: ProcessedMessage) -> None:
        self._messages[message.id] = message

    def set_messages(self, messages: list[ProcessedMessage]) -> None:
        self._all_messages = messages
        for msg in messages:
            self._messages[msg.id] = msg


def _generate_test_credential(prefix: str) -> str:
    """Generate a valid credential string for Settings validation."""
    return f"{prefix}Aa1!{secrets.token_hex(4)}"


def _build_settings(*, debug: bool, example_prefix: str = "[PROCESSED]") -> Settings:
    """Build a Settings instance with the specified debug flag."""
    return Settings(
        debug=debug,
        example_prefix=example_prefix,
        surrealdb_user=_generate_test_credential("User"),
        surrealdb_pass=_generate_test_credential("Pass"),
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


@pytest.mark.asyncio
async def test_get_processed_message_success(
    fake_repository: FakeExampleRepository,
    settings_debug_false: Settings,
) -> None:
    """ExampleService returns message when found in repository."""
    service = ExampleService(repository=fake_repository, settings=settings_debug_false)
    test_message = ProcessedMessage(
        id="msg_001",
        content="[PROCESSED] Test",
        type="info",
        processed_at=datetime.now(UTC),
    )
    fake_repository.set_message(test_message)

    result = await service.get_processed_message("msg_001")

    assert result == test_message


@pytest.mark.asyncio
async def test_get_processed_message_not_found(
    fake_repository: FakeExampleRepository,
    settings_debug_false: Settings,
) -> None:
    """ExampleService raises ResourceNotFoundError when message not found."""
    service = ExampleService(repository=fake_repository, settings=settings_debug_false)

    with pytest.raises(ResourceNotFoundError) as excinfo:
        await service.get_processed_message("nonexistent")

    assert "nonexistent" in str(excinfo.value)


@pytest.mark.asyncio
async def test_list_processed_messages_returns_paginated_response(
    fake_repository: FakeExampleRepository,
    settings_debug_false: Settings,
) -> None:
    """ExampleService returns correctly structured Paginated response."""
    service = ExampleService(repository=fake_repository, settings=settings_debug_false)
    messages = [
        ProcessedMessage(
            id=f"msg_{i:03d}",
            content=f"[PROCESSED] Message {i}",
            type="info",
            processed_at=datetime.now(UTC),
        )
        for i in range(25)
    ]
    fake_repository.set_messages(messages)

    result = await service.list_processed_messages(page=1, page_size=10)

    assert isinstance(result, Paginated)
    assert result.total == 25
    assert result.page == 1
    assert result.page_size == 10
    assert len(result.items) == 10


@pytest.mark.asyncio
async def test_list_processed_messages_calculates_offset_correctly(
    fake_repository: FakeExampleRepository,
    settings_debug_false: Settings,
) -> None:
    """ExampleService calculates correct offset from page number."""
    service = ExampleService(repository=fake_repository, settings=settings_debug_false)
    messages = [
        ProcessedMessage(
            id=f"msg_{i:03d}",
            content=f"[PROCESSED] Message {i}",
            type="info",
            processed_at=datetime.now(UTC),
        )
        for i in range(30)
    ]
    fake_repository.set_messages(messages)

    result = await service.list_processed_messages(page=3, page_size=10)

    assert result.page == 3
    assert len(result.items) == 10
    assert result.items[0].id == "msg_020"


@pytest.mark.asyncio
async def test_list_processed_messages_empty_results(
    fake_repository: FakeExampleRepository,
    settings_debug_false: Settings,
) -> None:
    """ExampleService handles empty result set correctly."""
    service = ExampleService(repository=fake_repository, settings=settings_debug_false)

    result = await service.list_processed_messages(page=1, page_size=10)

    assert isinstance(result, Paginated)
    assert result.total == 0
    assert result.items == []
