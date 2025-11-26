"""Repository abstraction for example domain data access."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from app.infrastructure.surrealdb import SurrealDBPool

PROCESSED_MESSAGES_TABLE: Final[str] = "processed_messages"


class ExampleRepositoryProtocol(Protocol):
    """Protocol defining persistence operations for the example domain."""

    async def save_processed_message(
        self, *, content: str, message_type: str, processed_at: datetime
    ) -> None:
        """Persist a processed message record."""
        ...


class ExampleRepository(ExampleRepositoryProtocol):
    """Concrete repository implementation for example domain using SurrealDB."""

    def __init__(self, pool: SurrealDBPool) -> None:
        """Store connection pool for use during persistence operations."""
        self._pool = pool

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
