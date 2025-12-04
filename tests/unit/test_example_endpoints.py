"""Unit tests for example demo endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.api.v1.endpoints.example import (
    get_processed_message,
    list_processed_messages,
    process_message,
    sample_item,
)
from app.contracts.example_contract import (
    ExampleRequest,
    ExampleResponse,
    ProcessedMessageResponse,
)
from app.contracts.pagination import Paginated
from app.repositories.example_repository import ProcessedMessage


class TestSampleItem:
    """Tests for the sample_item endpoint function."""

    def test_returns_demo_response(self) -> None:
        """Test sample_item returns a hardcoded demo response."""
        result = sample_item()

        assert isinstance(result, ExampleResponse)
        assert result.result == "[DEMO] Sample Result"
        assert result.original_length == 13
        assert result.processed_at is not None

    def test_processed_at_is_recent(self) -> None:
        """Test sample_item returns a recent timestamp."""
        before = datetime.now(UTC)
        result = sample_item()
        after = datetime.now(UTC)

        assert before <= result.processed_at <= after


class TestProcessMessage:
    """Tests for the process_message endpoint function."""

    @pytest.mark.asyncio
    async def test_calls_service_with_request(self) -> None:
        """Test process_message calls service.process with the request."""
        mock_service = AsyncMock()
        mock_service.process.return_value = ExampleResponse(
            result="Processed",
            processed_at=datetime.now(UTC),
            original_length=5,
        )

        request = ExampleRequest(message="Hello", type="info")
        result = await process_message(request, mock_service)

        mock_service.process.assert_called_once_with(request)
        assert result.result == "Processed"


class TestListProcessedMessages:
    """Tests for the list_processed_messages endpoint function."""

    @pytest.mark.asyncio
    async def test_returns_paginated_response(self) -> None:
        """Test list_processed_messages returns paginated response."""
        mock_service = AsyncMock()
        mock_service.list_processed_messages.return_value = Paginated(
            items=[
                ProcessedMessage(
                    id="msg_001",
                    content="Test content",
                    type="info",
                    processed_at=datetime.now(UTC),
                )
            ],
            total=1,
            page=1,
            page_size=10,
        )

        result = await list_processed_messages(mock_service, page=1, page_size=10)

        assert isinstance(result, Paginated)
        assert result.total == 1
        assert result.page == 1
        assert len(result.items) == 1
        assert isinstance(result.items[0], ProcessedMessageResponse)

    @pytest.mark.asyncio
    async def test_passes_pagination_params_to_service(self) -> None:
        """Test pagination params are passed to the service."""
        mock_service = AsyncMock()
        mock_service.list_processed_messages.return_value = Paginated(
            items=[],
            total=0,
            page=3,
            page_size=25,
        )

        await list_processed_messages(mock_service, page=3, page_size=25)

        mock_service.list_processed_messages.assert_called_once_with(3, 25)


class TestGetProcessedMessage:
    """Tests for the get_processed_message endpoint function."""

    @pytest.mark.asyncio
    async def test_returns_message_response(self) -> None:
        """Test get_processed_message returns the message."""
        mock_service = AsyncMock()
        mock_service.get_processed_message.return_value = ProcessedMessage(
            id="msg_001",
            content="Test content",
            type="warning",
            processed_at=datetime.now(UTC),
        )

        result = await get_processed_message("msg_001", mock_service)

        assert isinstance(result, ProcessedMessageResponse)
        assert result.id == "msg_001"
        assert result.content == "Test content"
        assert result.type == "warning"

    @pytest.mark.asyncio
    async def test_passes_message_id_to_service(self) -> None:
        """Test message_id is passed to the service."""
        mock_service = AsyncMock()
        mock_service.get_processed_message.return_value = ProcessedMessage(
            id="test_id",
            content="Content",
            type="info",
            processed_at=datetime.now(UTC),
        )

        await get_processed_message("test_id", mock_service)

        mock_service.get_processed_message.assert_called_once_with("test_id")
