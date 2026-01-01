"""Unit tests for app factory and lifespan handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI


class _MockSettings:
    """Mock settings for testing."""

    def __init__(self) -> None:
        self.app_name = "test_app"
        self.app_version = "1.0.0"
        self.api_prefix = "/api/v1"
        self.enable_request_logging = False
        self.enable_metrics = False
        self.enable_rate_limiting = False
        self.enable_request_id = False
        self.enable_gzip = False
        self.enforce_https = False
        self.allowed_hosts = None
        self.cors_enabled = False


class TestLifespan:
    """Tests for the lifespan context manager and its error handling paths."""

    @pytest.mark.asyncio
    async def test_lifespan_exception_during_initialization(self) -> None:
        """Test that lifespan re-raises exceptions during resource initialization."""
        from app.core.factory import _lifespan

        settings = _MockSettings()

        # Mock all resource creation functions to raise exceptions
        with (
            patch("app.core.factory.create_surrealdb_pool", new_callable=AsyncMock) as mock_surreal,
            patch("app.core.factory.create_elasticsearch_wrapper", new_callable=AsyncMock),
            patch("app.core.factory.create_duckdb_client", new_callable=AsyncMock),
        ):
            mock_surreal.side_effect = Exception("SurrealDB initialization failed")

            lifespan = _lifespan(settings)
            app = FastAPI()

            with pytest.raises(Exception, match="SurrealDB initialization failed"):
                async with lifespan(app):
                    pass

    @pytest.mark.asyncio
    async def test_lifespan_handles_duckdb_close_failure(self) -> None:
        """Test that lifespan handles DuckDB close failure gracefully."""
        from app.core.factory import _lifespan

        settings = _MockSettings()

        with (
            patch("app.core.factory.create_surrealdb_pool", new_callable=AsyncMock) as mock_surreal,
            patch(
                "app.core.factory.create_elasticsearch_wrapper", new_callable=AsyncMock
            ) as mock_es,
            patch("app.core.factory.create_duckdb_client", new_callable=AsyncMock) as mock_duckdb,
        ):
            mock_surreal_instance = AsyncMock()
            mock_surreal.return_value = mock_surreal_instance

            mock_es_instance = AsyncMock()
            mock_es.return_value = mock_es_instance

            mock_duckdb_instance = AsyncMock()
            mock_duckdb.return_value = mock_duckdb_instance

            # Make DuckDB close raise an exception
            mock_duckdb_instance.close.side_effect = Exception("DuckDB close failed")

            lifespan = _lifespan(settings)
            app = FastAPI()

            # Should not raise, but log the error and continue
            async with lifespan(app):
                pass

            # Verify close was attempted
            mock_duckdb_instance.close.assert_called_once()
            # Verify other resources were also closed
            mock_es_instance.close.assert_called_once()
            mock_surreal_instance.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_handles_elasticsearch_close_failure(self) -> None:
        """Test that lifespan handles Elasticsearch close failure gracefully."""
        from app.core.factory import _lifespan

        settings = _MockSettings()

        with (
            patch("app.core.factory.create_surrealdb_pool", new_callable=AsyncMock) as mock_surreal,
            patch(
                "app.core.factory.create_elasticsearch_wrapper", new_callable=AsyncMock
            ) as mock_es,
            patch("app.core.factory.create_duckdb_client", new_callable=AsyncMock) as mock_duckdb,
        ):
            mock_surreal_instance = AsyncMock()
            mock_surreal.return_value = mock_surreal_instance

            mock_es_instance = AsyncMock()
            mock_es.return_value = mock_es_instance

            mock_duckdb_instance = AsyncMock()
            mock_duckdb.return_value = mock_duckdb_instance

            # Make Elasticsearch close raise an exception
            mock_es_instance.close.side_effect = Exception("Elasticsearch close failed")

            lifespan = _lifespan(settings)
            app = FastAPI()

            # Should not raise, but log the error and continue
            async with lifespan(app):
                pass

            # Verify close was attempted
            mock_es_instance.close.assert_called_once()
            # Verify other resources were also closed
            mock_duckdb_instance.close.assert_called_once()
            mock_surreal_instance.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_handles_surrealdb_close_failure(self) -> None:
        """Test that lifespan handles SurrealDB pool close failure gracefully."""
        from app.core.factory import _lifespan

        settings = _MockSettings()

        with (
            patch("app.core.factory.create_surrealdb_pool", new_callable=AsyncMock) as mock_surreal,
            patch(
                "app.core.factory.create_elasticsearch_wrapper", new_callable=AsyncMock
            ) as mock_es,
            patch("app.core.factory.create_duckdb_client", new_callable=AsyncMock) as mock_duckdb,
        ):
            mock_surreal_instance = AsyncMock()
            mock_surreal.return_value = mock_surreal_instance

            mock_es_instance = AsyncMock()
            mock_es.return_value = mock_es_instance

            mock_duckdb_instance = AsyncMock()
            mock_duckdb.return_value = mock_duckdb_instance

            # Make SurrealDB pool close raise an exception
            mock_surreal_instance.close.side_effect = Exception("SurrealDB close failed")

            lifespan = _lifespan(settings)
            app = FastAPI()

            # Should not raise, but log the error and continue
            async with lifespan(app):
                pass

            # Verify close was attempted
            mock_surreal_instance.close.assert_called_once()
            # Verify other resources were also closed
            mock_duckdb_instance.close.assert_called_once()
            mock_es_instance.close.assert_called_once()


class TestCreateApp:
    """Tests for the create_app function."""

    def test_create_app_returns_configured_app(self) -> None:
        """Test that create_app returns a properly configured FastAPI app."""
        from app.core.factory import create_app

        settings = _MockSettings()
        app = create_app(settings)

        assert isinstance(app, FastAPI)
        assert app.title == "test_app"
        assert app.version == "1.0.0"


class TestLifespanPartialInitialization:
    """Tests for lifespan with partial resource initialization."""

    @pytest.mark.asyncio
    async def test_lifespan_handles_elasticsearch_initialization_failure(
        self,
    ) -> None:
        """Test that lifespan closes SurrealDB when Elasticsearch fails to initialize."""
        from app.core.factory import _lifespan

        settings = _MockSettings()

        with (
            patch("app.core.factory.create_surrealdb_pool", new_callable=AsyncMock) as mock_surreal,
            patch(
                "app.core.factory.create_elasticsearch_wrapper", new_callable=AsyncMock
            ) as mock_es,
            patch("app.core.factory.create_duckdb_client", new_callable=AsyncMock),
        ):
            mock_surreal_instance = AsyncMock()
            mock_surreal.return_value = mock_surreal_instance

            # Make Elasticsearch initialization fail
            mock_es.side_effect = Exception("Elasticsearch initialization failed")

            lifespan = _lifespan(settings)
            app = FastAPI()

            with pytest.raises(Exception, match="Elasticsearch initialization failed"):
                async with lifespan(app):
                    pass

            # Verify SurrealDB was created
            mock_surreal.assert_called_once()
            # Verify SurrealDB was closed during cleanup
            mock_surreal_instance.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_handles_duckdb_initialization_failure(self) -> None:
        """Test that lifespan closes resources when DuckDB fails to initialize."""
        from app.core.factory import _lifespan

        settings = _MockSettings()

        with (
            patch("app.core.factory.create_surrealdb_pool", new_callable=AsyncMock) as mock_surreal,
            patch(
                "app.core.factory.create_elasticsearch_wrapper", new_callable=AsyncMock
            ) as mock_es,
            patch("app.core.factory.create_duckdb_client", new_callable=AsyncMock) as mock_duckdb,
        ):
            mock_surreal_instance = AsyncMock()
            mock_surreal.return_value = mock_surreal_instance

            mock_es_instance = AsyncMock()
            mock_es.return_value = mock_es_instance

            # Make DuckDB initialization fail
            mock_duckdb.side_effect = Exception("DuckDB initialization failed")

            lifespan = _lifespan(settings)
            app = FastAPI()

            with pytest.raises(Exception, match="DuckDB initialization failed"):
                async with lifespan(app):
                    pass

            # Verify SurrealDB and Elasticsearch were created
            mock_surreal.assert_called_once()
            mock_es.assert_called_once()
            # Verify both were closed during cleanup
            mock_surreal_instance.close.assert_called_once()
            mock_es_instance.close.assert_called_once()
