"""Unit tests for ExampleRepository query methods.

These tests verify the repository's query operations using mocked DuckDB client,
ensuring correct SQL generation and result mapping.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories.example_repository import (
    ExampleRepository,
    ProcessedMessage,
)


@pytest.fixture
def mock_pool() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_duckdb_client() -> AsyncMock:
    client = AsyncMock()
    client.get_csv_path = MagicMock(return_value="/test/data/csv/processed_messages.csv")
    return client


@pytest.fixture
def repository(mock_pool: MagicMock, mock_duckdb_client: AsyncMock) -> ExampleRepository:
    return ExampleRepository(pool=mock_pool, duckdb_client=mock_duckdb_client)


class TestGetById:
    """Tests for ExampleRepository.get_by_id method."""

    @pytest.mark.asyncio
    async def test_get_by_id_found(
        self, repository: ExampleRepository, mock_duckdb_client: AsyncMock
    ) -> None:
        mock_duckdb_client.query.return_value = [
            {
                "id": "msg_001",
                "content": "[PROCESSED] [INFO] Hello World",
                "type": "info",
                "processed_at": "2024-01-15T10:30:00+00:00",
            }
        ]

        result = await repository.get_by_id("msg_001")

        assert result is not None
        assert isinstance(result, ProcessedMessage)
        assert result.id == "msg_001"
        assert result.content == "[PROCESSED] [INFO] Hello World"
        assert result.type == "info"
        assert result.processed_at.year == 2024

        mock_duckdb_client.query.assert_called_once()
        call_args = mock_duckdb_client.query.call_args
        assert "WHERE id = $id" in call_args[0][0]
        assert call_args[0][1] == {"id": "msg_001"}

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(
        self, repository: ExampleRepository, mock_duckdb_client: AsyncMock
    ) -> None:
        mock_duckdb_client.query.return_value = []

        result = await repository.get_by_id("nonexistent")

        assert result is None
        mock_duckdb_client.query.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_by_id_handles_z_suffix_timestamp(
        self, repository: ExampleRepository, mock_duckdb_client: AsyncMock
    ) -> None:
        mock_duckdb_client.query.return_value = [
            {
                "id": "msg_001",
                "content": "[PROCESSED] Test",
                "type": "info",
                "processed_at": "2024-01-15T10:30:00Z",
            }
        ]

        result = await repository.get_by_id("msg_001")

        assert result is not None
        assert result.processed_at.tzinfo is not None


class TestListPaginated:
    """Tests for ExampleRepository.list_paginated method."""

    @pytest.mark.asyncio
    async def test_list_paginated_returns_messages_and_total(
        self, repository: ExampleRepository, mock_duckdb_client: AsyncMock
    ) -> None:
        mock_duckdb_client.query.side_effect = [
            [{"total": 10}],
            [
                {
                    "id": "msg_001",
                    "content": "[PROCESSED] [INFO] Hello",
                    "type": "info",
                    "processed_at": "2024-01-15T10:30:00Z",
                },
                {
                    "id": "msg_002",
                    "content": "[PROCESSED] [WARNING] Warning",
                    "type": "warning",
                    "processed_at": "2024-01-15T11:30:00Z",
                },
            ],
        ]

        messages, total = await repository.list_paginated(offset=0, limit=2)

        assert total == 10
        assert len(messages) == 2
        assert all(isinstance(m, ProcessedMessage) for m in messages)
        assert messages[0].id == "msg_001"
        assert messages[1].id == "msg_002"

    @pytest.mark.asyncio
    async def test_list_paginated_uses_correct_offset_and_limit(
        self, repository: ExampleRepository, mock_duckdb_client: AsyncMock
    ) -> None:
        mock_duckdb_client.query.side_effect = [
            [{"total": 100}],
            [],
        ]

        await repository.list_paginated(offset=20, limit=10)

        assert mock_duckdb_client.query.call_count == 2
        data_query = mock_duckdb_client.query.call_args_list[1][0][0]
        assert "LIMIT 10 OFFSET 20" in data_query

    @pytest.mark.asyncio
    async def test_list_paginated_empty_results(
        self, repository: ExampleRepository, mock_duckdb_client: AsyncMock
    ) -> None:
        mock_duckdb_client.query.side_effect = [
            [{"total": 0}],
            [],
        ]

        messages, total = await repository.list_paginated(offset=0, limit=10)

        assert total == 0
        assert len(messages) == 0

    @pytest.mark.asyncio
    async def test_list_paginated_orders_by_processed_at_desc(
        self, repository: ExampleRepository, mock_duckdb_client: AsyncMock
    ) -> None:
        mock_duckdb_client.query.side_effect = [
            [{"total": 1}],
            [],
        ]

        await repository.list_paginated(offset=0, limit=10)

        data_query = mock_duckdb_client.query.call_args_list[1][0][0]
        assert "ORDER BY processed_at DESC" in data_query


class TestSaveProcessedMessage:
    """Tests for ExampleRepository.save_processed_message method."""

    @pytest.mark.asyncio
    async def test_save_processed_message_executes_query(
        self, mock_pool: MagicMock, mock_duckdb_client: AsyncMock
    ) -> None:
        """Test that save_processed_message executes correct query."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        repository = ExampleRepository(pool=mock_pool, duckdb_client=mock_duckdb_client)
        dt = datetime(2024, 6, 15, 14, 0, 0, tzinfo=UTC)

        await repository.save_processed_message(
            content="Test content",
            message_type="info",
            processed_at=dt,
        )

        mock_conn.query.assert_called_once()
        call_args = mock_conn.query.call_args
        assert "CREATE processed_messages SET" in call_args[0][0]
        assert call_args[0][1]["content"] == "Test content"
        assert call_args[0][1]["type"] == "info"

    @pytest.mark.asyncio
    async def test_save_processed_message_includes_timestamp_iso_format(
        self, mock_pool: MagicMock, mock_duckdb_client: AsyncMock
    ) -> None:
        """Test that timestamp is saved in ISO format."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        repository = ExampleRepository(pool=mock_pool, duckdb_client=mock_duckdb_client)
        dt = datetime(2024, 6, 15, 14, 30, 45, tzinfo=UTC)

        await repository.save_processed_message(
            content="Test",
            message_type="warning",
            processed_at=dt,
        )

        call_args = mock_conn.query.call_args
        assert call_args[0][1]["processed_at"] == "2024-06-15T14:30:45+00:00"


class TestMapToProcessedMessage:
    """Tests for the _map_to_processed_message static method."""

    def test_maps_dict_to_processed_message(self) -> None:
        row = {
            "id": "test_id",
            "content": "Test content",
            "type": "error",
            "processed_at": "2024-06-15T14:00:00+00:00",
        }

        result = ExampleRepository._map_to_processed_message(row)

        assert isinstance(result, ProcessedMessage)
        assert result.id == "test_id"
        assert result.content == "Test content"
        assert result.type == "error"
        assert result.processed_at.year == 2024
        assert result.processed_at.month == 6

    def test_handles_datetime_object_in_row(self) -> None:
        dt = datetime(2024, 3, 20, 12, 0, 0, tzinfo=UTC)
        row = {
            "id": "test_id",
            "content": "Test content",
            "type": "info",
            "processed_at": dt,
        }

        result = ExampleRepository._map_to_processed_message(row)

        assert result.processed_at == dt
