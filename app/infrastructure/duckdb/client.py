"""DuckDB client wrapper with async support for CSV querying."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
import duckdb

from app.infrastructure.duckdb.exceptions import (
    DuckDBConnectionError,
    DuckDBNotInitializedError,
    DuckDBQueryError,
)

if TYPE_CHECKING:
    from app.core.settings import Settings

logger = logging.getLogger(__name__)

type DictStrAny = dict[str, Any]


class DuckDBClient:
    """Async-friendly wrapper around DuckDB for CSV-based querying.

    DuckDB is an embedded database that runs in-process and is thread-safe.
    This wrapper provides async methods by offloading blocking operations
    to a thread pool using anyio.to_thread.run_sync.

    The client reads CSV files from a configurable data directory and provides
    a simple query interface with parameter substitution.
    """

    def __init__(self, csv_data_path: Path) -> None:
        """Configure the DuckDB client with the path to CSV data files.

        Args:
            csv_data_path: Path to the directory containing CSV files to query.
        """
        self._csv_data_path = csv_data_path
        self._connection: duckdb.DuckDBPyConnection | None = None
        self._initialized = False

    @property
    def csv_data_path(self) -> Path:
        """Return the configured CSV data directory path."""
        return self._csv_data_path

    def _ensure_initialized(self) -> None:
        """Raise if the client has not been initialized."""
        if not self._initialized:
            raise DuckDBNotInitializedError()

    async def init(self) -> None:
        """Initialize the DuckDB connection and verify CSV directory exists.

        Raises:
            DuckDBConnectionError: If the CSV directory does not exist or
                connection initialization fails.
        """
        if self._initialized:
            return

        def _init_sync() -> duckdb.DuckDBPyConnection:
            if not self._csv_data_path.exists():
                msg = f"CSV data directory does not exist: {self._csv_data_path}"
                raise DuckDBConnectionError(msg)
            if not self._csv_data_path.is_dir():
                msg = f"CSV data path is not a directory: {self._csv_data_path}"
                raise DuckDBConnectionError(msg)
            return duckdb.connect(":memory:")

        try:
            self._connection = await anyio.to_thread.run_sync(_init_sync)
            self._initialized = True
            logger.info("DuckDB client initialized with CSV path: %s", self._csv_data_path)
        except DuckDBConnectionError:
            raise
        except Exception as exc:
            raise DuckDBConnectionError(str(exc)) from exc

    async def close(self) -> None:
        """Close the DuckDB connection."""
        if self._connection is not None:

            def _close_sync() -> None:
                if self._connection is not None:
                    self._connection.close()

            await anyio.to_thread.run_sync(_close_sync)
            self._connection = None
        self._initialized = False

    async def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a SQL query and return results as a list of dictionaries.

        Args:
            sql: SQL query string. Use $param syntax for parameter substitution.
            params: Dictionary of parameter values to substitute in the query.

        Returns:
            List of dictionaries where each dictionary represents a row with
            column names as keys.

        Raises:
            DuckDBNotInitializedError: If init() has not been called.
            DuckDBQueryError: If the query execution fails.
        """
        self._ensure_initialized()

        def _query_sync() -> list[dict[str, Any]]:
            if self._connection is None:
                raise DuckDBNotInitializedError()
            try:
                result = self._connection.execute(sql, params or {})
                columns = [desc[0] for desc in result.description or []]
                rows = result.fetchall()
                return [dict(zip(columns, row, strict=False)) for row in rows]
            except duckdb.Error as exc:
                raise DuckDBQueryError(str(exc)) from exc

        try:
            return await anyio.to_thread.run_sync(_query_sync)
        except DuckDBQueryError:
            raise
        except DuckDBNotInitializedError:
            raise
        except Exception as exc:
            raise DuckDBQueryError(str(exc)) from exc

    def get_csv_path(self, filename: str) -> str:
        """Return the full path to a CSV file in the data directory.

        Args:
            filename: Name of the CSV file (e.g., 'processed_messages.csv').

        Returns:
            Full path to the CSV file as a string suitable for SQL queries.
        """
        return str(self._csv_data_path / filename)


async def create_duckdb_client(settings: Settings) -> DuckDBClient:
    """Factory that builds and initializes a DuckDB client from settings.

    Args:
        settings: Application settings containing csv_data_path configuration.

    Returns:
        An initialized DuckDBClient ready for querying.
    """
    csv_path = Path(settings.csv_data_path)
    client = DuckDBClient(csv_data_path=csv_path)
    await client.init()
    return client
