"""Repository abstraction for example domain data access."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Protocol

if TYPE_CHECKING:
    from app.infrastructure.duckdb import DuckDBClient
    from app.infrastructure.surrealdb import SurrealDBPool

PROCESSED_MESSAGES_TABLE: Final[str] = "processed_messages"
PROCESSED_MESSAGES_CSV: Final[str] = "processed_messages.csv"


@dataclass(frozen=True)
class ProcessedMessage:
    """Domain model representing a processed message record.

    Attributes:
        id: Unique identifier for the message.
        content: The processed message content.
        type: Message category (info, warning, error).
        processed_at: Timestamp when the message was processed.
    """

    id: str
    content: str
    type: str
    processed_at: datetime


class ExampleRepositoryProtocol(Protocol):
    """Protocol defining persistence operations for the example domain."""

    async def save_processed_message(
        self, *, content: str, message_type: str, processed_at: datetime
    ) -> None:
        """Persist a processed message record."""
        ...

    async def get_by_id(self, id: str) -> ProcessedMessage | None:
        """Retrieve a processed message by its unique identifier.

        Args:
            id: The unique identifier of the message to retrieve.

        Returns:
            The ProcessedMessage if found, otherwise None.
        """
        ...

    async def list_paginated(self, offset: int, limit: int) -> tuple[list[ProcessedMessage], int]:
        """Retrieve a paginated list of processed messages.

        Args:
            offset: Number of records to skip from the beginning.
            limit: Maximum number of records to return.

        Returns:
            A tuple containing the list of messages and the total count.
        """
        ...


class ExampleRepository(ExampleRepositoryProtocol):
    """Concrete repository implementation for example domain.

    Uses SurrealDB for write operations (save_processed_message) and
    DuckDB for read operations over CSV data (get_by_id, list_paginated).
    """

    def __init__(self, pool: SurrealDBPool, duckdb_client: DuckDBClient) -> None:
        """Store connection pool and DuckDB client for persistence operations.

        Args:
            pool: SurrealDB connection pool for write operations.
            duckdb_client: DuckDB client for CSV-based read operations.
        """
        self._pool = pool
        self._duckdb_client = duckdb_client

    async def save_processed_message(
        self, *, content: str, message_type: str, processed_at: datetime
    ) -> None:
        """Persist a processed message record to SurrealDB."""
        query = (
            f"CREATE {PROCESSED_MESSAGES_TABLE} SET "
            "content = $content, type = $type, processed_at = $processed_at;"
        )
        params = {
            "content": content,
            "type": message_type,
            "processed_at": processed_at.isoformat(),
        }

        async with self._pool.acquire() as conn:
            await conn.query(query, params)

    async def get_by_id(self, id: str) -> ProcessedMessage | None:
        """Retrieve a processed message by its unique identifier from CSV.

        Args:
            id: The unique identifier of the message to retrieve.

        Returns:
            The ProcessedMessage if found, otherwise None.
        """
        csv_path = self._duckdb_client.get_csv_path(PROCESSED_MESSAGES_CSV)
        sql = f"SELECT * FROM read_csv_auto('{csv_path}') WHERE id = $id"  # noqa: S608
        results = await self._duckdb_client.query(sql, {"id": id})

        if not results:
            return None

        return self._map_to_processed_message(results[0])

    async def list_paginated(self, offset: int, limit: int) -> tuple[list[ProcessedMessage], int]:
        """Retrieve a paginated list of processed messages from CSV.

        Args:
            offset: Number of records to skip from the beginning.
            limit: Maximum number of records to return.

        Returns:
            A tuple containing the list of messages and the total count.
        """
        csv_path = self._duckdb_client.get_csv_path(PROCESSED_MESSAGES_CSV)

        count_sql = f"SELECT COUNT(*) as total FROM read_csv_auto('{csv_path}')"  # noqa: S608
        count_result = await self._duckdb_client.query(count_sql)
        total = count_result[0]["total"] if count_result else 0

        data_sql = (
            f"SELECT * FROM read_csv_auto('{csv_path}') "  # noqa: S608
            f"ORDER BY processed_at DESC LIMIT {limit} OFFSET {offset}"
        )
        results = await self._duckdb_client.query(data_sql)

        messages = [self._map_to_processed_message(row) for row in results]
        return messages, total

    @staticmethod
    def _map_to_processed_message(row: dict[str, Any]) -> ProcessedMessage:
        """Map a database row dictionary to a ProcessedMessage domain object.

        Args:
            row: Dictionary containing column values from the query result.

        Returns:
            ProcessedMessage domain object.
        """
        processed_at = row["processed_at"]
        if isinstance(processed_at, str):
            processed_at = datetime.fromisoformat(processed_at.replace("Z", "+00:00"))

        return ProcessedMessage(
            id=row["id"],
            content=row["content"],
            type=row["type"],
            processed_at=processed_at,
        )
