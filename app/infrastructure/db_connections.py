"""Database connection helpers for SurrealDB and Elasticsearch."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, TypeAlias, cast

import anyio
from elasticsearch import Elasticsearch
from elasticsearch import exceptions as es_exceptions
from surrealdb import Surreal

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from app.core.settings import Settings

logger = logging.getLogger(__name__)

DictStrAny: TypeAlias = dict[str, Any]


class ElasticsearchNotInitializedError(RuntimeError):
    """Raised when Elasticsearch client methods are called before init()."""

    MESSAGE = "Elasticsearch client not initialized; call init() first"

    def __init__(self, message: str | None = None) -> None:
        """Initialize with a fallback message when none provided."""
        super().__init__(message or self.MESSAGE)


class SurrealDBPoolNotInitializedError(RuntimeError):
    """Raised when the SurrealDB pool is used before initialization."""

    MESSAGE = "Connection pool not initialized; call init() before acquire()"

    def __init__(self, message: str | None = None) -> None:
        """Initialize with a fallback message when none provided."""
        super().__init__(message or self.MESSAGE)


class UnsupportedSchemaVersionError(RuntimeError):
    """Raised when the stored schema version is unknown to this service."""

    def __init__(self, version: str | None) -> None:
        """Build an error message including the unsupported version."""
        super().__init__(f"Unsupported schema version: {version}")


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
        self._queue: asyncio.Queue[Surreal] = asyncio.Queue(maxsize=size)
        self._initialized = False
        self._acquire_timeout = acquire_timeout

    async def init(self) -> None:
        """Create and authenticate pool connections."""
        if self._initialized:
            return

        created: list[Surreal] = []
        try:
            for _ in range(self._size):
                conn = Surreal(self._dsn)
                await conn.connect()
                await conn.signin({"user": self._user, "pass": self._password})
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
    async def acquire(self) -> AsyncIterator[Surreal]:
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
            result = await conn.query(schema_sql, params)
            return cast("list[Any]", result)

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

            DEFINE TABLE schema_versions SCHEMAFULL IF NOT EXISTS;
            DEFINE FIELD namespace ON TABLE schema_versions TYPE string IF NOT EXISTS;
            DEFINE FIELD database  ON TABLE schema_versions TYPE string IF NOT EXISTS;
            DEFINE FIELD current_version ON TABLE schema_versions TYPE string IF NOT EXISTS;
            DEFINE FIELD applied_at ON TABLE schema_versions TYPE datetime IF NOT EXISTS;
            DEFINE INDEX schema_versions_namespace_database
              ON TABLE schema_versions FIELDS namespace, database UNIQUE;
        """

    async def _apply_version_1_schema(self) -> None:
        schema = f"""
            {self._schema_version_definitions()}

            DEFINE TABLE facts SCHEMAFULL IF NOT EXISTS;
            DEFINE FIELD text ON TABLE facts TYPE string IF NOT EXISTS;
            DEFINE FIELD standardized_text ON TABLE facts TYPE string IF NOT EXISTS;
            DEFINE FIELD embedding ON TABLE facts TYPE array<float> IF NOT EXISTS;
            DEFINE FIELD source_file ON TABLE facts TYPE string IF NOT EXISTS;
            DEFINE FIELD source_line ON TABLE facts TYPE int IF NOT EXISTS;
            DEFINE FIELD created_at ON TABLE facts TYPE datetime DEFAULT time::now() IF NOT EXISTS;

            DEFINE TABLE entities SCHEMAFULL IF NOT EXISTS;
            DEFINE FIELD canonical_name ON TABLE entities TYPE string IF NOT EXISTS;
            DEFINE FIELD aliases        ON TABLE entities TYPE array<string> IF NOT EXISTS;
            DEFINE FIELD entity_type    ON TABLE entities TYPE string IF NOT EXISTS;

            DEFINE TABLE topics SCHEMAFULL IF NOT EXISTS;
            DEFINE FIELD name        ON TABLE topics TYPE string IF NOT EXISTS;
            DEFINE FIELD level       ON TABLE topics TYPE int IF NOT EXISTS;
            DEFINE FIELD description ON TABLE topics TYPE string IF NOT EXISTS;

            DEFINE TABLE mentions TYPE RELATION FROM facts TO entities SCHEMALESS IF NOT EXISTS;
            DEFINE TABLE has_subtopic TYPE RELATION FROM topics TO topics SCHEMALESS IF NOT EXISTS;
            DEFINE TABLE concerns TYPE RELATION FROM facts TO topics SCHEMALESS IF NOT EXISTS;
            DEFINE TABLE overlaps_with TYPE RELATION FROM facts TO facts SCHEMALESS IF NOT EXISTS;
            DEFINE TABLE contradicts TYPE RELATION FROM facts TO facts SCHEMALESS IF NOT EXISTS;
            DEFINE TABLE refines TYPE RELATION FROM facts TO facts SCHEMALESS IF NOT EXISTS;

            DEFINE INDEX facts_embedding_hnsw
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

    def _extract_first_field(self, result: list[Any], field: str) -> str | None:
        if not result:
            return None
        try:
            first = result[0]
            rows = cast("list[dict[str, Any]]", first.get("result", []))
            if rows and isinstance(rows[0], dict):
                value = rows[0].get(field)
                return cast("str | None", value)
        except Exception:
            logger.debug("Failed to parse schema version result", exc_info=True)
        return None

    def _schema_version_record_id(self) -> str:
        return f"{self._namespace}_{self._database}"

    async def _write_schema_version(self, version: str) -> None:
        update_sql = """
            UPDATE schema_versions:$record_id MERGE {
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


class ElasticsearchWrapper:
    """Async-friendly wrapper around the synchronous Elasticsearch client."""

    def __init__(
        self,
        hosts: str | list[str],
        *,
        connections_per_node: int,
        request_timeout: int,
        number_of_shards: int,
        number_of_replicas: int,
        retry_on_timeout: bool = True,
    ) -> None:
        """Configure the underlying Elasticsearch client parameters."""
        self._client = Elasticsearch(
            hosts=hosts,
            connections_per_node=connections_per_node,
            request_timeout=request_timeout,
            retry_on_timeout=retry_on_timeout,
        )
        self._initialized = False
        self._number_of_shards = number_of_shards
        self._number_of_replicas = number_of_replicas

    def _ensure_initialized(self) -> None:
        """Raise if the client has not been initialized."""
        if not self._initialized:
            raise ElasticsearchNotInitializedError()

    async def init(self) -> None:
        """Verify connectivity to Elasticsearch."""
        await anyio.to_thread.run_sync(self._client.ping)
        self._initialized = True
        logger.info("Elasticsearch client initialized")

    async def close(self) -> None:
        """Close the underlying client."""
        await anyio.to_thread.run_sync(self._client.close)
        self._initialized = False

    async def search(self, index: str, query: dict[str, Any]) -> dict[str, Any]:
        """Execute a search request in a worker thread."""
        self._ensure_initialized()

        def _sync_search() -> dict[str, Any]:
            return cast(DictStrAny, self._client.search(index=index, query=query))

        return await anyio.to_thread.run_sync(_sync_search)

    async def index(
        self, index: str, document: dict[str, Any], id: str | None = None
    ) -> dict[str, Any]:
        """Index a document asynchronously."""
        self._ensure_initialized()

        def _sync_index() -> dict[str, Any]:
            return cast(DictStrAny, self._client.index(index=index, document=document, id=id))

        return await anyio.to_thread.run_sync(_sync_index)

    async def bulk(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        """Perform bulk operations asynchronously."""
        self._ensure_initialized()

        def _sync_bulk() -> dict[str, Any]:
            return cast(DictStrAny, self._client.bulk(operations=operations))

        return await anyio.to_thread.run_sync(_sync_bulk)

    async def create_index(
        self, index: str, mappings: dict[str, Any], settings: dict[str, Any]
    ) -> None:
        """Create an index if it does not already exist."""
        self._ensure_initialized()

        def _create_index() -> None:
            try:
                self._client.indices.create(index=index, mappings=mappings, settings=settings)
            except es_exceptions.RequestError as exc:
                error_type = ""
                try:
                    error_type = exc.info.get("error", {}).get("type", "")
                except (AttributeError, KeyError):  # pragma: no cover - defensive
                    error_type = getattr(exc, "error", "") or ""
                if error_type == "resource_already_exists_exception":
                    logger.debug("Index %s already exists; skipping creation", index)
                    return
                raise

        await anyio.to_thread.run_sync(_create_index)

    async def initialize_indices(self) -> None:
        """Initialize Knowledge Graph indices for facts and entity aliases."""
        self._ensure_initialized()
        base_settings = {
            "number_of_shards": self._number_of_shards,
            "number_of_replicas": self._number_of_replicas,
        }

        facts_mappings = {
            "properties": {
                "text": {"type": "text"},
                "standardized_text": {"type": "text"},
                "source_file": {"type": "keyword"},
                "entity_ids": {"type": "keyword"},
                "topic_ids": {"type": "keyword"},
            }
        }

        entity_aliases_mappings = {
            "properties": {
                "canonical_name": {"type": "keyword"},
                "alias": {"type": "text"},
                "entity_type": {"type": "keyword"},
            }
        }

        await self.create_index(
            index="facts_index",
            mappings=facts_mappings,
            settings=base_settings,
        )

        await self.create_index(
            index="entity_aliases_index",
            mappings=entity_aliases_mappings,
            settings=base_settings,
        )


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


async def create_elasticsearch_wrapper(settings: Settings) -> ElasticsearchWrapper:
    """Factory that builds and initializes an Elasticsearch wrapper from settings."""
    wrapper = ElasticsearchWrapper(
        hosts=settings.elasticsearch_url,
        connections_per_node=settings.elasticsearch_connections_per_node,
        request_timeout=settings.elasticsearch_request_timeout,
        number_of_shards=settings.elasticsearch_shards,
        number_of_replicas=settings.elasticsearch_replicas,
    )
    await wrapper.init()
    try:
        await wrapper.initialize_indices()
    except Exception:
        await wrapper.close()
        raise
    return wrapper
