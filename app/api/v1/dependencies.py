"""Versioned dependency injection providers for API v1 endpoints.

This module provides HTTP-facing dependency wiring specific to API version 1.
Framework-agnostic providers remain in app/core/dependencies.py.
"""

from typing import Annotated, cast

from fastapi import Depends, Request

from app.core.dependencies import get_settings
from app.core.settings import Settings
from app.infrastructure.duckdb import DuckDBClient
from app.infrastructure.elasticsearch import ElasticsearchWrapper
from app.infrastructure.surrealdb import SurrealDBPool
from app.repositories.example_repository import (
    ExampleRepository,
    ExampleRepositoryProtocol,
)
from app.services.example_service import ExampleService

# ---------------------------------------------------------------------------
# Infrastructure providers (HTTP-facing)
# ---------------------------------------------------------------------------


def get_db_pool(request: Request) -> SurrealDBPool:
    """Retrieve the SurrealDB connection pool from application state.

    Args:
        request: The incoming HTTP request.

    Returns:
        SurrealDBPool: The initialized database connection pool.
    """
    return cast("SurrealDBPool", request.app.state.surrealdb_pool)


def get_elasticsearch_client(request: Request) -> ElasticsearchWrapper:
    """Retrieve the Elasticsearch client from application state.

    Args:
        request: The incoming HTTP request.

    Returns:
        ElasticsearchWrapper: The initialized Elasticsearch client wrapper.
    """
    return cast("ElasticsearchWrapper", request.app.state.elasticsearch_client)


def get_duckdb_client(request: Request) -> DuckDBClient:
    """Retrieve the DuckDB client from application state.

    Args:
        request: The incoming HTTP request.

    Returns:
        DuckDBClient: The initialized DuckDB client for CSV queries.
    """
    return cast("DuckDBClient", request.app.state.duckdb_client)


# ---------------------------------------------------------------------------
# Repository providers
# ---------------------------------------------------------------------------


def get_example_repository(
    pool: Annotated[SurrealDBPool, Depends(get_db_pool)],
    duckdb_client: Annotated[DuckDBClient, Depends(get_duckdb_client)],
) -> ExampleRepositoryProtocol:
    """Provide an ExampleRepository instance with database dependencies.

    Args:
        pool: SurrealDB connection pool for write operations.
        duckdb_client: DuckDB client for CSV-based read operations.

    Returns:
        ExampleRepositoryProtocol: A configured repository instance.
    """
    return ExampleRepository(pool=pool, duckdb_client=duckdb_client)


# ---------------------------------------------------------------------------
# Service providers
# ---------------------------------------------------------------------------


def get_example_service(
    settings: Annotated[Settings, Depends(get_settings)],
    repo: Annotated[ExampleRepositoryProtocol, Depends(get_example_repository)],
) -> ExampleService:
    """Provide an ExampleService instance with repository and settings.

    Args:
        settings: Application settings loaded via dependency injection.
        repo: Repository instance for example domain data access.

    Returns:
        ExampleService: A configured service instance.
    """
    return ExampleService(repository=repo, settings=settings)


# ---------------------------------------------------------------------------
# Annotated aliases for cleaner route signatures
# ---------------------------------------------------------------------------


SettingsDep = Annotated[Settings, Depends(get_settings)]
"""Type alias for injecting Settings via Depends."""

SurrealDBPoolDep = Annotated[SurrealDBPool, Depends(get_db_pool)]
"""Type alias for injecting SurrealDBPool via Depends."""

ElasticsearchWrapperDep = Annotated[ElasticsearchWrapper, Depends(get_elasticsearch_client)]
"""Type alias for injecting ElasticsearchWrapper via Depends."""

DuckDBClientDep = Annotated[DuckDBClient, Depends(get_duckdb_client)]
"""Type alias for injecting DuckDBClient via Depends."""

ExampleRepositoryDep = Annotated[ExampleRepositoryProtocol, Depends(get_example_repository)]
"""Type alias for injecting ExampleRepositoryProtocol via Depends."""

ExampleServiceDep = Annotated[ExampleService, Depends(get_example_service)]
"""Type alias for injecting ExampleService via Depends."""
