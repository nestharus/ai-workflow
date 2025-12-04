"""Unit tests for health check endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request

from app.api.v1.endpoints.health import HealthResponse, health_check


class TestHealthCheck:
    """Tests for the health_check endpoint function."""

    @pytest.mark.asyncio
    async def test_returns_ok_when_all_dependencies_healthy(self) -> None:
        """Test returns 'ok' when all dependencies are available and healthy."""
        # Setup mock app state
        mock_surrealdb_pool = AsyncMock()
        mock_surrealdb_pool.health_check.return_value = True

        mock_elasticsearch_client = AsyncMock()
        mock_elasticsearch_client.health_check.return_value = True

        mock_state = MagicMock()
        mock_state.surrealdb_pool = mock_surrealdb_pool
        mock_state.elasticsearch_client = mock_elasticsearch_client

        mock_app = MagicMock()
        mock_app.state = mock_state

        mock_request = MagicMock(spec=Request)
        mock_request.app = mock_app

        result = await health_check(mock_request)

        assert isinstance(result, HealthResponse)
        assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_returns_unhealthy_when_surrealdb_missing(self) -> None:
        """Test returns 'unhealthy' when SurrealDB pool is None."""
        mock_elasticsearch_client = AsyncMock()
        mock_elasticsearch_client.health_check.return_value = True

        mock_state = MagicMock()
        mock_state.surrealdb_pool = None
        mock_state.elasticsearch_client = mock_elasticsearch_client

        mock_app = MagicMock()
        mock_app.state = mock_state

        mock_request = MagicMock(spec=Request)
        mock_request.app = mock_app

        result = await health_check(mock_request)

        assert result.status == "unhealthy"

    @pytest.mark.asyncio
    async def test_returns_unhealthy_when_elasticsearch_missing(self) -> None:
        """Test returns 'unhealthy' when Elasticsearch client is None."""
        mock_surrealdb_pool = AsyncMock()
        mock_surrealdb_pool.health_check.return_value = True

        mock_state = MagicMock()
        mock_state.surrealdb_pool = mock_surrealdb_pool
        mock_state.elasticsearch_client = None

        mock_app = MagicMock()
        mock_app.state = mock_state

        mock_request = MagicMock(spec=Request)
        mock_request.app = mock_app

        result = await health_check(mock_request)

        assert result.status == "unhealthy"

    @pytest.mark.asyncio
    async def test_returns_degraded_when_surrealdb_unhealthy(self) -> None:
        """Test returns 'degraded' when SurrealDB health check fails."""
        mock_surrealdb_pool = AsyncMock()
        mock_surrealdb_pool.health_check.return_value = False

        mock_elasticsearch_client = AsyncMock()
        mock_elasticsearch_client.health_check.return_value = True

        mock_state = MagicMock()
        mock_state.surrealdb_pool = mock_surrealdb_pool
        mock_state.elasticsearch_client = mock_elasticsearch_client

        mock_app = MagicMock()
        mock_app.state = mock_state

        mock_request = MagicMock(spec=Request)
        mock_request.app = mock_app

        result = await health_check(mock_request)

        assert result.status == "degraded"

    @pytest.mark.asyncio
    async def test_returns_degraded_when_elasticsearch_unhealthy(self) -> None:
        """Test returns 'degraded' when Elasticsearch health check fails."""
        mock_surrealdb_pool = AsyncMock()
        mock_surrealdb_pool.health_check.return_value = True

        mock_elasticsearch_client = AsyncMock()
        mock_elasticsearch_client.health_check.return_value = False

        mock_state = MagicMock()
        mock_state.surrealdb_pool = mock_surrealdb_pool
        mock_state.elasticsearch_client = mock_elasticsearch_client

        mock_app = MagicMock()
        mock_app.state = mock_state

        mock_request = MagicMock(spec=Request)
        mock_request.app = mock_app

        result = await health_check(mock_request)

        assert result.status == "degraded"

    @pytest.mark.asyncio
    async def test_returns_degraded_when_both_dependencies_unhealthy(self) -> None:
        """Test returns 'degraded' when both health checks fail."""
        mock_surrealdb_pool = AsyncMock()
        mock_surrealdb_pool.health_check.return_value = False

        mock_elasticsearch_client = AsyncMock()
        mock_elasticsearch_client.health_check.return_value = False

        mock_state = MagicMock()
        mock_state.surrealdb_pool = mock_surrealdb_pool
        mock_state.elasticsearch_client = mock_elasticsearch_client

        mock_app = MagicMock()
        mock_app.state = mock_state

        mock_request = MagicMock(spec=Request)
        mock_request.app = mock_app

        result = await health_check(mock_request)

        assert result.status == "degraded"


class TestHealthResponse:
    """Tests for HealthResponse model."""

    def test_accepts_ok_status(self) -> None:
        """Test HealthResponse accepts 'ok' status."""
        response = HealthResponse(status="ok")
        assert response.status == "ok"

    def test_accepts_degraded_status(self) -> None:
        """Test HealthResponse accepts 'degraded' status."""
        response = HealthResponse(status="degraded")
        assert response.status == "degraded"

    def test_accepts_unhealthy_status(self) -> None:
        """Test HealthResponse accepts 'unhealthy' status."""
        response = HealthResponse(status="unhealthy")
        assert response.status == "unhealthy"
