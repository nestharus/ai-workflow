"""Repository abstraction for example domain data access.

This module defines the repository protocol and concrete implementation
for example domain operations, following patterns from repository-patterns.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.infrastructure.db_connections import SurrealDBPool


class ExampleRepositoryProtocol(Protocol):
    """Protocol defining the repository interface for example domain.

    Services depend on this protocol rather than concrete implementations,
    enabling easy substitution and testing.
    """

    async def get_prefix(self) -> str:
        """Retrieve the configured prefix for message processing.

        Returns:
            str: The prefix string to use for message processing.
        """
        ...


class ExampleRepository:
    """Concrete repository implementation for example domain using SurrealDB.

    This repository provides data access for the example domain, demonstrating
    the pattern of constructor-injected database pools. The implementation is
    intentionally stubbed to serve as an illustrative example; methods return
    hardcoded values rather than querying the database.

    For production repositories, replace stubbed methods with actual database
    queries following the patterns shown in the commented code blocks and
    documented in ``docs/repository-patterns.md``.

    Attributes:
        _pool: The injected SurrealDB connection pool for data operations.
    """

    def __init__(self, pool: SurrealDBPool) -> None:
        """Initialize the repository with a SurrealDB connection pool.

        Args:
            pool: The SurrealDB connection pool for data operations.
        """
        self._pool = pool

    async def get_prefix(self) -> str:
        """Retrieve the configured prefix for message processing.

        This implementation is intentionally hardcoded to demonstrate the
        repository pattern without requiring database infrastructure. The
        commented block below shows the recommended pattern for real queries:
        acquire a connection from the pool, execute a parameterized query,
        and map the result to the return type.

        Recommended pattern for actual database access::

            async with self._pool.acquire() as conn:
                result = await conn.query(
                    "SELECT prefix FROM config WHERE id = $id LIMIT 1;",
                    {"id": "default"},
                )
                rows = result[0].get("result", [])
                if rows:
                    return rows[0]["prefix"]
                return "[DEFAULT]"

        Returns:
            str: The prefix string to use for message processing.
        """
        return "[PROCESSED]"
