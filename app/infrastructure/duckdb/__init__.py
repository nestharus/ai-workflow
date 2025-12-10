"""DuckDB infrastructure module for CSV-based querying."""

from app.infrastructure.duckdb.client import DuckDBClient, create_duckdb_client
from app.infrastructure.duckdb.exceptions import (
    DuckDBClientError,
    DuckDBConnectionError,
    DuckDBNotInitializedError,
    DuckDBQueryError,
)

__all__ = [
    "DuckDBClient",
    "DuckDBClientError",
    "DuckDBConnectionError",
    "DuckDBNotInitializedError",
    "DuckDBQueryError",
    "create_duckdb_client",
]
