"""SurrealDB connection pool implementation."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Protocol, cast

from surrealdb import AsyncSurreal

from app.infrastructure.surrealdb.exceptions import (
    SurrealDBPoolNotInitializedError,
    UnsupportedSchemaVersionError,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from app.core.settings import Settings


class AsyncSurrealConnection(Protocol):
    """Protocol defining the interface for async SurrealDB connections.

    This protocol captures the subset of methods used by the connection pool,
    decoupling the pool implementation from the concrete connection class
    returned by the surrealdb library's AsyncSurreal factory function.
    """

    async def connect(self) -> None:
        """Establish the connection to SurrealDB."""
        ...

    async def signin(self, credentials: dict[str, Any]) -> None:
        """Authenticate with the provided credentials."""
        ...

    async def use(self, namespace: str, database: str) -> None:
        """Select the namespace and database to use."""
        ...

    async def close(self) -> None:
        """Close the connection."""
        ...

    async def query(self, sql: str, params: dict[str, Any] | None = None) -> list[Any]:
        """Execute a query and return the results."""
        ...


logger = logging.getLogger(__name__)


class SurrealDBPool:
    """Async connection pool for SurrealDB using a bounded queue.

    The pool maintains multiple WebSocket connections to SurrealDB to allow
    concurrent graph operations. Connections are established up front with
    authentication and database selection applied.
    """

    def __init__(
        self,
        dsn: str,
        namespace: str,
        database: str,
        user: str,
        password: str,
        size: int = 5,
        embedding_dimension: int = 768,
        acquire_timeout: float = 10.0,
    ) -> None:
        """Store pool configuration and initialize internal state."""
        self._latest_schema_version = "1"
        self._dsn = dsn
        self._namespace = namespace
        self._database = database
        self._user = user
        self._password = password
        self._size = size
        self._embedding_dimension = embedding_dimension
        self._queue: asyncio.Queue[AsyncSurrealConnection] = asyncio.Queue(maxsize=size)
        self._initialized = False
        self._acquire_timeout = acquire_timeout

    async def init(self) -> None:
        """Create and authenticate pool connections."""
        if self._initialized:
            return

        created: list[AsyncSurrealConnection] = []
        try:
            for _ in range(self._size):
                conn = cast("AsyncSurrealConnection", AsyncSurreal(self._dsn))
                await conn.connect()
                await conn.signin({"username": self._user, "password": self._password})
                await conn.use(self._namespace, self._database)
                created.append(conn)
            for conn in created:
                await self._queue.put(conn)
        except Exception:  # pragma: no cover - defensive guard
            logger.exception("Failed to initialize SurrealDB pool")
            for conn in created:
                try:
                    await conn.close()
                except Exception as exc:  # pragma: no cover - defensive guard
                    logger.warning("Failed to close SurrealDB connection during cleanup: %s", exc)
            raise

        self._initialized = True
        logger.info("SurrealDB pool initialized with %s connections", self._size)

    async def close(self) -> None:
        """Close all connections in the pool."""
        while not self._queue.empty():
            conn = await self._queue.get()
            try:
                await conn.close()
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.warning("Failed to close SurrealDB connection: %s", exc)
        self._initialized = False

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[AsyncSurrealConnection]:
        """Acquire a connection from the pool with timeout handling."""
        if not self._initialized:
            raise SurrealDBPoolNotInitializedError()
        try:
            conn = await asyncio.wait_for(self._queue.get(), timeout=self._acquire_timeout)
        except TimeoutError:
            logger.exception("Timed out waiting for SurrealDB connection")
            raise
        try:
            yield conn
        finally:
            await self._queue.put(conn)

    async def execute_schema(
        self, schema_sql: str, params: dict[str, Any] | None = None
    ) -> list[Any]:
        """Execute schema definition statements."""
        async with self.acquire() as conn:
            return await conn.query(schema_sql, params)

    async def health_check(self) -> bool:
        """Check if the pool is healthy by executing a simple query.

        Returns:
            True if the pool is healthy and can execute queries, False otherwise.
        """
        if not self._initialized:
            return False
        try:
            async with self.acquire() as conn:
                # SurrealQL requires RETURN for simple value evaluation
                await conn.query("RETURN 1")
        except Exception as exc:
            logger.warning("SurrealDB health check failed: %s", exc)
            return False
        else:
            return True

    async def initialize_schema(self) -> None:
        """Define Knowledge Graph tables, relationships, and vector index."""
        await self.execute_schema(self._schema_version_definitions())
        current_version = await self._get_current_schema_version()

        if current_version == self._latest_schema_version:
            logger.info(
                "SurrealDB schema already at version %s for namespace '%s' and database '%s'",
                current_version,
                self._namespace,
                self._database,
            )
            return

        migrations: dict[str | None, tuple[str, Callable[[], Awaitable[None]]]] = {
            None: ("1", self._apply_version_1_schema),
        }

        while current_version != self._latest_schema_version:
            next_step = migrations.get(current_version)
            if next_step is None:
                raise UnsupportedSchemaVersionError(current_version)

            next_version, migration = next_step
            await migration()
            current_version = next_version
            await self._write_schema_version(current_version)
        logger.info(
            "SurrealDB schema migrated to version %s for namespace '%s' and database '%s'",
            self._latest_schema_version,
            self._namespace,
            self._database,
        )

    def _schema_version_definitions(self) -> str:
        return f"""
            DEFINE NAMESPACE IF NOT EXISTS {self._namespace};
            DEFINE DATABASE IF NOT EXISTS {self._database};

            DEFINE TABLE IF NOT EXISTS schema_versions SCHEMAFULL;
            DEFINE FIELD IF NOT EXISTS namespace ON TABLE schema_versions TYPE string;
            DEFINE FIELD IF NOT EXISTS database ON TABLE schema_versions TYPE string;
            DEFINE FIELD IF NOT EXISTS current_version ON TABLE schema_versions TYPE string;
            DEFINE FIELD IF NOT EXISTS applied_at ON TABLE schema_versions TYPE datetime;
            DEFINE INDEX IF NOT EXISTS schema_versions_namespace_database
              ON TABLE schema_versions FIELDS namespace, database UNIQUE;
        """

    async def _apply_version_1_schema(self) -> None:
        schema = f"""
            {self._schema_version_definitions()}

            DEFINE TABLE IF NOT EXISTS facts SCHEMAFULL;
            DEFINE FIELD IF NOT EXISTS text ON TABLE facts TYPE string;
            DEFINE FIELD IF NOT EXISTS standardized_text ON TABLE facts TYPE string;
            DEFINE FIELD IF NOT EXISTS embedding ON TABLE facts TYPE array<float>;
            DEFINE FIELD IF NOT EXISTS source_file ON TABLE facts TYPE string;
            DEFINE FIELD IF NOT EXISTS source_line ON TABLE facts TYPE int;
            DEFINE FIELD IF NOT EXISTS created_at ON TABLE facts TYPE datetime DEFAULT time::now();

            DEFINE TABLE IF NOT EXISTS entities SCHEMAFULL;
            DEFINE FIELD IF NOT EXISTS canonical_name ON TABLE entities TYPE string;
            DEFINE FIELD IF NOT EXISTS aliases ON TABLE entities TYPE array<string>;
            DEFINE FIELD IF NOT EXISTS entity_type ON TABLE entities TYPE string;

            DEFINE TABLE IF NOT EXISTS topics SCHEMAFULL;
            DEFINE FIELD IF NOT EXISTS name ON TABLE topics TYPE string;
            DEFINE FIELD IF NOT EXISTS level ON TABLE topics TYPE int;
            DEFINE FIELD IF NOT EXISTS description ON TABLE topics TYPE string;

            DEFINE TABLE IF NOT EXISTS mentions TYPE RELATION FROM facts TO entities SCHEMALESS;
            DEFINE TABLE IF NOT EXISTS has_subtopic TYPE RELATION FROM topics TO topics SCHEMALESS;
            DEFINE TABLE IF NOT EXISTS concerns TYPE RELATION FROM facts TO topics SCHEMALESS;
            DEFINE TABLE IF NOT EXISTS overlaps_with TYPE RELATION FROM facts TO facts SCHEMALESS;
            DEFINE TABLE IF NOT EXISTS contradicts TYPE RELATION FROM facts TO facts SCHEMALESS;
            DEFINE TABLE IF NOT EXISTS refines TYPE RELATION FROM facts TO facts SCHEMALESS;

            DEFINE INDEX IF NOT EXISTS facts_embedding_hnsw
              ON facts FIELDS embedding
              HNSW DIMENSION {self._embedding_dimension} DIST COSINE;
        """

        await self.execute_schema(schema)

    async def _get_current_schema_version(self) -> str | None:
        query = """
            SELECT current_version FROM schema_versions
            WHERE namespace = $namespace AND database = $database
            LIMIT 1;
        """
        params = {"namespace": self._namespace, "database": self._database}
        result = await self.execute_schema(query, params)
        return self._extract_first_field(result, "current_version")

    @staticmethod
    def _extract_first_field(result: list[Any], field: str) -> str | None:
        if not result:
            return None
        try:
            first = result[0]
            rows = cast("list[dict[str, Any]]", first.get("result", []))
            if rows and isinstance(rows[0], dict):
                value = rows[0].get(field)
                return cast("str | None", value)
        except (AttributeError, IndexError, KeyError, TypeError):
            logger.debug("Failed to parse schema version result", exc_info=True)
        return None

    def _schema_version_record_id(self) -> str:
        return f"{self._namespace}_{self._database}"

    async def _write_schema_version(self, version: str) -> None:
        update_sql = """
            UPDATE type::thing("schema_versions", $record_id) MERGE {
                namespace: $namespace,
                database: $database,
                current_version: $version,
                applied_at: time::now(),
            };
        """
        params = {
            "record_id": self._schema_version_record_id(),
            "namespace": self._namespace,
            "database": self._database,
            "version": version,
        }
        await self.execute_schema(update_sql, params)


async def create_surrealdb_pool(settings: Settings) -> SurrealDBPool:
    """Factory that builds and initializes a SurrealDB pool from settings."""
    pool = SurrealDBPool(
        dsn=settings.surrealdb_url,
        namespace=settings.surrealdb_namespace,
        database=settings.surrealdb_database,
        user=settings.surrealdb_user,
        password=settings.surrealdb_pass,
        size=settings.surrealdb_pool_size,
        embedding_dimension=settings.embedding_dimension,
    )
    await pool.init()
    try:
        await pool.initialize_schema()
    except Exception:
        await pool.close()
        raise
    return pool
