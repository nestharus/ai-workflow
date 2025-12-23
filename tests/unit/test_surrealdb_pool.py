"""Unit tests for SurrealDB connection pool."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.infrastructure.surrealdb.exceptions import (
    SurrealDBPoolNotInitializedError,
    UnsupportedSchemaVersionError,
)
from app.infrastructure.surrealdb.pool import SurrealDBPool, create_surrealdb_pool


class _MockSettings:
    """Mock settings for testing."""

    def __init__(self) -> None:
        self.surrealdb_url = "ws://localhost:8000/rpc"
        self.surrealdb_namespace = "test_ns"
        self.surrealdb_database = "test_db"
        self.surrealdb_user = "root"
        self.surrealdb_pass = "root"
        self.surrealdb_pool_size = 2
        self.embedding_dimension = 768


class TestSurrealDBPool:
    """Tests for SurrealDBPool class."""

    def test_init_stores_configuration(self) -> None:
        """Test that __init__ stores the pool configuration."""
        pool = SurrealDBPool(
            dsn="ws://localhost:8000/rpc",
            namespace="test_ns",
            database="test_db",
            user="root",
            password="root",
            size=3,
            embedding_dimension=512,
            acquire_timeout=5.0,
        )
        assert pool._dsn == "ws://localhost:8000/rpc"
        assert pool._namespace == "test_ns"
        assert pool._database == "test_db"
        assert pool._user == "root"
        assert pool._password == "root"
        assert pool._size == 3
        assert pool._embedding_dimension == 512
        assert pool._acquire_timeout == 5.0
        assert pool._initialized is False

    @pytest.mark.asyncio
    async def test_init_creates_connections(self) -> None:
        """Test that init() creates and configures connections."""
        with patch("app.infrastructure.surrealdb.pool.AsyncSurreal") as mock_surreal:
            mock_conn = AsyncMock()
            mock_surreal.return_value = mock_conn

            pool = SurrealDBPool(
                dsn="ws://localhost:8000/rpc",
                namespace="test_ns",
                database="test_db",
                user="root",
                password="root",
                size=2,
            )
            await pool.init()

            assert pool._initialized is True
            assert pool._queue.qsize() == 2
            # Each connection should have been configured
            assert mock_conn.connect.call_count == 2
            assert mock_conn.signin.call_count == 2
            assert mock_conn.use.call_count == 2
            await pool.close()

    @pytest.mark.asyncio
    async def test_init_is_idempotent(self) -> None:
        """Test that calling init() twice does not error."""
        with patch("app.infrastructure.surrealdb.pool.AsyncSurreal") as mock_surreal:
            mock_conn = AsyncMock()
            mock_surreal.return_value = mock_conn

            pool = SurrealDBPool(
                dsn="ws://localhost:8000/rpc",
                namespace="test_ns",
                database="test_db",
                user="root",
                password="root",
                size=1,
            )
            await pool.init()
            await pool.init()  # Should not create more connections
            assert pool._queue.qsize() == 1
            await pool.close()

    @pytest.mark.asyncio
    async def test_close_cleans_up_connections(self) -> None:
        """Test that close() cleans up all connections."""
        with patch("app.infrastructure.surrealdb.pool.AsyncSurreal") as mock_surreal:
            mock_conn = AsyncMock()
            mock_surreal.return_value = mock_conn

            pool = SurrealDBPool(
                dsn="ws://localhost:8000/rpc",
                namespace="test_ns",
                database="test_db",
                user="root",
                password="root",
                size=2,
            )
            await pool.init()
            await pool.close()

            assert pool._initialized is False
            assert pool._queue.empty()
            assert mock_conn.close.call_count == 2

    @pytest.mark.asyncio
    async def test_acquire_raises_when_not_initialized(self) -> None:
        """Test that acquire raises when pool is not initialized."""
        pool = SurrealDBPool(
            dsn="ws://localhost:8000/rpc",
            namespace="test_ns",
            database="test_db",
            user="root",
            password="root",
        )
        with pytest.raises(SurrealDBPoolNotInitializedError):
            async with pool.acquire():
                pass

    @pytest.mark.asyncio
    async def test_acquire_returns_connection(self) -> None:
        """Test that acquire returns a connection and returns it on exit."""
        with patch("app.infrastructure.surrealdb.pool.AsyncSurreal") as mock_surreal:
            mock_conn = AsyncMock()
            mock_surreal.return_value = mock_conn

            pool = SurrealDBPool(
                dsn="ws://localhost:8000/rpc",
                namespace="test_ns",
                database="test_db",
                user="root",
                password="root",
                size=1,
            )
            await pool.init()
            try:
                assert pool._queue.qsize() == 1
                async with pool.acquire() as conn:
                    assert pool._queue.qsize() == 0
                    assert conn is not None
                assert pool._queue.qsize() == 1
            finally:
                await pool.close()

    @pytest.mark.asyncio
    async def test_execute_schema_runs_query(self) -> None:
        """Test that execute_schema executes a query via acquired connection."""
        with patch("app.infrastructure.surrealdb.pool.AsyncSurreal") as mock_surreal:
            mock_conn = AsyncMock()
            mock_conn.query.return_value = [{"result": "ok"}]
            mock_surreal.return_value = mock_conn

            pool = SurrealDBPool(
                dsn="ws://localhost:8000/rpc",
                namespace="test_ns",
                database="test_db",
                user="root",
                password="root",
                size=1,
            )
            await pool.init()
            try:
                result = await pool.execute_schema("DEFINE TABLE test")
                assert result == [{"result": "ok"}]
                mock_conn.query.assert_called_with("DEFINE TABLE test", None)
            finally:
                await pool.close()

    @pytest.mark.asyncio
    async def test_health_check_returns_true_when_healthy(self) -> None:
        """Test that health_check returns True when query succeeds."""
        with patch("app.infrastructure.surrealdb.pool.AsyncSurreal") as mock_surreal:
            mock_conn = AsyncMock()
            mock_conn.query.return_value = [[{"time": "2024-01-01"}]]
            mock_surreal.return_value = mock_conn

            pool = SurrealDBPool(
                dsn="ws://localhost:8000/rpc",
                namespace="test_ns",
                database="test_db",
                user="root",
                password="root",
                size=1,
            )
            await pool.init()
            try:
                result = await pool.health_check()
                assert result is True
            finally:
                await pool.close()

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_not_initialized(self) -> None:
        """Test that health_check returns False when pool not initialized."""
        pool = SurrealDBPool(
            dsn="ws://localhost:8000/rpc",
            namespace="test_ns",
            database="test_db",
            user="root",
            password="root",
        )
        result = await pool.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_query_error(self) -> None:
        """Test that health_check returns False when query fails."""
        with patch("app.infrastructure.surrealdb.pool.AsyncSurreal") as mock_surreal:
            mock_conn = AsyncMock()
            # First queries succeed (init), then health check fails
            mock_conn.query.side_effect = Exception("Query failed")
            mock_surreal.return_value = mock_conn

            pool = SurrealDBPool(
                dsn="ws://localhost:8000/rpc",
                namespace="test_ns",
                database="test_db",
                user="root",
                password="root",
                size=1,
            )
            # Manually set as initialized for testing
            pool._initialized = True
            await pool._queue.put(mock_conn)
            try:
                result = await pool.health_check()
                assert result is False
            finally:
                pool._initialized = False


class TestSurrealDBPoolSchemaOperations:
    """Tests for schema-related operations in SurrealDBPool."""

    def test_schema_version_definitions_includes_namespace_and_database(self) -> None:
        """Test that _schema_version_definitions uses configured namespace/database."""
        pool = SurrealDBPool(
            dsn="ws://localhost:8000/rpc",
            namespace="my_namespace",
            database="my_database",
            user="root",
            password="root",
        )
        schema = pool._schema_version_definitions()
        assert "my_namespace" in schema
        assert "my_database" in schema
        assert "DEFINE TABLE IF NOT EXISTS schema_versions" in schema

    def test_schema_version_record_id_format(self) -> None:
        """Test that _schema_version_record_id returns correct format."""
        pool = SurrealDBPool(
            dsn="ws://localhost:8000/rpc",
            namespace="test_ns",
            database="test_db",
            user="root",
            password="root",
        )
        record_id = pool._schema_version_record_id()
        assert record_id == "test_ns_test_db"

    def test_extract_first_field_returns_none_for_empty_result(self) -> None:
        """Test _extract_first_field returns None for empty result."""
        result = SurrealDBPool._extract_first_field([], "current_version")
        assert result is None

    def test_extract_first_field_returns_value_from_result(self) -> None:
        """Test _extract_first_field extracts value from nested structure."""
        result = [{"result": [{"current_version": "1"}]}]
        value = SurrealDBPool._extract_first_field(result, "current_version")
        assert value == "1"

    def test_extract_first_field_handles_malformed_result(self) -> None:
        """Test _extract_first_field handles malformed data gracefully."""
        # Missing 'result' key
        result1: list = [{}]
        assert SurrealDBPool._extract_first_field(result1, "field") is None

        # Empty result list
        result2 = [{"result": []}]
        assert SurrealDBPool._extract_first_field(result2, "field") is None

        # Non-dict in result
        result3 = [{"result": ["not a dict"]}]
        assert SurrealDBPool._extract_first_field(result3, "field") is None

    @pytest.mark.asyncio
    async def test_initialize_schema_applies_migrations(self) -> None:
        """Test that initialize_schema applies schema migrations."""
        with patch("app.infrastructure.surrealdb.pool.AsyncSurreal") as mock_surreal:
            mock_conn = AsyncMock()
            # First return None (no version), then return "1" (after migration)
            mock_conn.query.side_effect = [
                [{}],  # _schema_version_definitions query
                [{"result": []}],  # _get_current_schema_version - no version
                [{}],  # _apply_version_1_schema
                [{}],  # _write_schema_version
            ]
            mock_surreal.return_value = mock_conn

            pool = SurrealDBPool(
                dsn="ws://localhost:8000/rpc",
                namespace="test_ns",
                database="test_db",
                user="root",
                password="root",
                size=1,
            )
            await pool.init()
            try:
                await pool.initialize_schema()
                # Should have called query for schema operations
                assert mock_conn.query.call_count >= 2
            finally:
                await pool.close()

    @pytest.mark.asyncio
    async def test_initialize_schema_skips_when_up_to_date(self) -> None:
        """Test that initialize_schema skips migration when schema is current."""
        with patch("app.infrastructure.surrealdb.pool.AsyncSurreal") as mock_surreal:
            mock_conn = AsyncMock()
            # Return current version "1"
            mock_conn.query.side_effect = [
                [{}],  # _schema_version_definitions query
                [{"result": [{"current_version": "1"}]}],  # _get_current_schema_version
            ]
            mock_surreal.return_value = mock_conn

            pool = SurrealDBPool(
                dsn="ws://localhost:8000/rpc",
                namespace="test_ns",
                database="test_db",
                user="root",
                password="root",
                size=1,
            )
            await pool.init()
            try:
                await pool.initialize_schema()
                # Should only have called for schema definitions and version check
                assert mock_conn.query.call_count == 2
            finally:
                await pool.close()

    @pytest.mark.asyncio
    async def test_initialize_schema_raises_for_unknown_version(self) -> None:
        """Test that initialize_schema raises for unknown schema version."""
        with patch("app.infrastructure.surrealdb.pool.AsyncSurreal") as mock_surreal:
            mock_conn = AsyncMock()
            # Return an unknown version
            mock_conn.query.side_effect = [
                [{}],  # _schema_version_definitions query
                [{"result": [{"current_version": "999"}]}],  # Unknown version
            ]
            mock_surreal.return_value = mock_conn

            pool = SurrealDBPool(
                dsn="ws://localhost:8000/rpc",
                namespace="test_ns",
                database="test_db",
                user="root",
                password="root",
                size=1,
            )
            await pool.init()
            try:
                with pytest.raises(UnsupportedSchemaVersionError):
                    await pool.initialize_schema()
            finally:
                await pool.close()


class TestCreateSurrealDBPool:
    """Tests for create_surrealdb_pool factory function."""

    @pytest.mark.asyncio
    async def test_creates_and_initializes_pool(self) -> None:
        """Test that factory creates and initializes a pool."""
        with patch("app.infrastructure.surrealdb.pool.AsyncSurreal") as mock_surreal:
            mock_conn = AsyncMock()
            mock_conn.query.side_effect = [
                [{}],  # _schema_version_definitions
                [{"result": [{"current_version": "1"}]}],  # Already at version 1
            ]
            mock_surreal.return_value = mock_conn

            settings = _MockSettings()
            pool = await create_surrealdb_pool(settings)  # type: ignore[arg-type]
            try:
                assert pool._initialized is True
            finally:
                await pool.close()

    @pytest.mark.asyncio
    async def test_uses_settings_values(self) -> None:
        """Test that factory uses settings values for pool configuration."""
        with patch("app.infrastructure.surrealdb.pool.AsyncSurreal") as mock_surreal:
            mock_conn = AsyncMock()
            mock_conn.query.side_effect = [
                [{}],  # _schema_version_definitions
                [{"result": [{"current_version": "1"}]}],  # Already at version 1
            ]
            mock_surreal.return_value = mock_conn

            settings = _MockSettings()
            settings.surrealdb_url = "ws://custom:9000/rpc"
            settings.surrealdb_namespace = "custom_ns"
            settings.surrealdb_database = "custom_db"
            settings.surrealdb_pool_size = 10
            settings.embedding_dimension = 1024

            pool = await create_surrealdb_pool(settings)  # type: ignore[arg-type]
            try:
                assert pool._dsn == "ws://custom:9000/rpc"
                assert pool._namespace == "custom_ns"
                assert pool._database == "custom_db"
                assert pool._size == 10
                assert pool._embedding_dimension == 1024
            finally:
                await pool.close()

    @pytest.mark.asyncio
    async def test_closes_pool_on_schema_error(self) -> None:
        """Test that factory closes pool if schema initialization fails."""
        with patch("app.infrastructure.surrealdb.pool.AsyncSurreal") as mock_surreal:
            mock_conn = AsyncMock()
            # Schema initialization fails
            mock_conn.query.side_effect = Exception("Schema error")
            mock_surreal.return_value = mock_conn

            settings = _MockSettings()
            with pytest.raises(Exception, match="Schema error"):
                await create_surrealdb_pool(settings)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_returns_working_pool_after_migration(self) -> None:
        """Test that factory returns a pool after successful migration."""
        with patch("app.infrastructure.surrealdb.pool.AsyncSurreal") as mock_surreal:
            mock_conn = AsyncMock()
            mock_conn.query.side_effect = [
                [{}],  # _schema_version_definitions
                [{"result": []}],  # No version (needs migration)
                [{}],  # _apply_version_1_schema
                [{}],  # _write_schema_version
            ]
            mock_surreal.return_value = mock_conn

            settings = _MockSettings()
            pool = await create_surrealdb_pool(settings)  # type: ignore[arg-type]
            try:
                assert pool._initialized is True
            finally:
                await pool.close()


class TestSurrealDBExceptions:
    """Tests for SurrealDB exception classes."""

    def test_pool_not_initialized_error_message(self) -> None:
        """Test SurrealDBPoolNotInitializedError has correct message."""
        exc = SurrealDBPoolNotInitializedError()
        assert "initialized" in str(exc).lower() or "init" in str(exc).lower()

    def test_unsupported_schema_version_error(self) -> None:
        """Test UnsupportedSchemaVersionError stores version info."""
        exc = UnsupportedSchemaVersionError(version="99")
        assert "99" in str(exc)
        assert "unsupported" in str(exc).lower() or "schema" in str(exc).lower()


class TestSurrealDBPoolAcquireTimeout:
    """Tests for acquire timeout handling in SurrealDBPool."""

    @pytest.mark.asyncio
    async def test_acquire_raises_timeout_error_when_queue_empty(self) -> None:
        """Test that acquire raises TimeoutError when waiting for connection times out."""

        from app.infrastructure.surrealdb.pool import SurrealDBPool

        pool = SurrealDBPool(
            dsn="ws://localhost:8000/rpc",
            namespace="test_ns",
            database="test_db",
            user="root",
            password="root",
            size=1,
            acquire_timeout=0.1,  # Short timeout for testing
        )
        pool._initialized = True

        # Block the queue.get() to simulate timeout by patching asyncio.wait_for
        with patch("app.infrastructure.surrealdb.pool.asyncio.wait_for") as mock_wait_for:
            # Make wait_for raise TimeoutError immediately
            mock_wait_for.side_effect = TimeoutError("Connection acquire timed out")

            with pytest.raises(TimeoutError, match="Connection acquire timed out"):
                async with pool.acquire():
                    pass
