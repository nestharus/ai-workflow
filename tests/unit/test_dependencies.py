"""Unit tests for dependency injection providers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.api.v1.dependencies import (
    get_db_pool,
    get_duckdb_client,
    get_elasticsearch_client,
    get_example_repository,
    get_example_service,
)


class TestGetDbPool:
    """Tests for get_db_pool dependency."""

    def test_returns_pool_from_app_state(self) -> None:
        """Test that get_db_pool returns the pool from request.app.state."""
        mock_pool = MagicMock()
        mock_request = MagicMock()
        mock_request.app.state.surrealdb_pool = mock_pool

        result = get_db_pool(mock_request)

        assert result is mock_pool


class TestGetElasticsearchClient:
    """Tests for get_elasticsearch_client dependency."""

    def test_returns_client_from_app_state(self) -> None:
        """Test that get_elasticsearch_client returns the client from app state."""
        mock_client = MagicMock()
        mock_request = MagicMock()
        mock_request.app.state.elasticsearch_client = mock_client

        result = get_elasticsearch_client(mock_request)

        assert result is mock_client


class TestGetDuckDBClient:
    """Tests for get_duckdb_client dependency."""

    def test_returns_client_from_app_state(self) -> None:
        """Test that get_duckdb_client returns the client from app state."""
        mock_client = MagicMock()
        mock_request = MagicMock()
        mock_request.app.state.duckdb_client = mock_client

        result = get_duckdb_client(mock_request)

        assert result is mock_client


class TestGetExampleRepository:
    """Tests for get_example_repository dependency."""

    def test_creates_repository_with_dependencies(self) -> None:
        """Test that get_example_repository creates a repository with pool and client."""
        mock_pool = MagicMock()
        mock_duckdb = MagicMock()

        result = get_example_repository(pool=mock_pool, duckdb_client=mock_duckdb)

        assert result._pool is mock_pool
        assert result._duckdb_client is mock_duckdb


class TestGetExampleService:
    """Tests for get_example_service dependency."""

    def test_creates_service_with_dependencies(self) -> None:
        """Test that get_example_service creates a service with repo and settings."""
        mock_settings = MagicMock()
        mock_repo = MagicMock()

        result = get_example_service(settings=mock_settings, repo=mock_repo)

        assert result._settings is mock_settings
        assert result._repository is mock_repo
