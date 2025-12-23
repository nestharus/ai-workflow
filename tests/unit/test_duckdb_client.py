"""Unit tests for DuckDB client wrapper."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.duckdb.client import DuckDBClient, create_duckdb_client
from app.infrastructure.duckdb.exceptions import (
    DuckDBConnectionError,
    DuckDBNotInitializedError,
    DuckDBQueryError,
)


class _MockSettings:
    """Mock settings for testing."""

    def __init__(self, csv_data_path: str) -> None:
        self.csv_data_path = csv_data_path


class TestDuckDBClient:
    """Tests for DuckDBClient class."""

    def test_init_sets_csv_data_path(self, tmp_path: Path) -> None:
        """Test that DuckDBClient stores the CSV data path."""
        client = DuckDBClient(csv_data_path=tmp_path)
        assert client.csv_data_path == tmp_path

    @pytest.mark.asyncio
    async def test_init_succeeds_with_valid_directory(self, tmp_path: Path) -> None:
        """Test that init() succeeds with a valid directory."""
        client = DuckDBClient(csv_data_path=tmp_path)
        await client.init()
        assert client._initialized is True
        await client.close()

    @pytest.mark.asyncio
    async def test_init_raises_for_nonexistent_directory(self) -> None:
        """Test that init() raises DuckDBConnectionError for missing directory."""
        client = DuckDBClient(csv_data_path=Path("/nonexistent/path"))
        with pytest.raises(DuckDBConnectionError, match="does not exist"):
            await client.init()

    @pytest.mark.asyncio
    async def test_init_raises_for_file_instead_of_directory(self, tmp_path: Path) -> None:
        """Test that init() raises DuckDBConnectionError when path is a file."""
        file_path = tmp_path / "not_a_directory.txt"
        file_path.write_text("content")
        client = DuckDBClient(csv_data_path=file_path)
        with pytest.raises(DuckDBConnectionError, match="not a directory"):
            await client.init()

    @pytest.mark.asyncio
    async def test_init_is_idempotent(self, tmp_path: Path) -> None:
        """Test that calling init() twice does not error."""
        client = DuckDBClient(csv_data_path=tmp_path)
        await client.init()
        await client.init()  # Should not raise
        assert client._initialized is True
        await client.close()

    @pytest.mark.asyncio
    async def test_close_cleans_up_connection(self, tmp_path: Path) -> None:
        """Test that close() cleans up the connection."""
        client = DuckDBClient(csv_data_path=tmp_path)
        await client.init()
        await client.close()
        assert client._initialized is False
        assert client._connection is None

    @pytest.mark.asyncio
    async def test_close_is_safe_when_not_initialized(self, tmp_path: Path) -> None:
        """Test that close() does not error when not initialized."""
        client = DuckDBClient(csv_data_path=tmp_path)
        await client.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_query_raises_when_not_initialized(self, tmp_path: Path) -> None:
        """Test that query() raises DuckDBNotInitializedError if not initialized."""
        client = DuckDBClient(csv_data_path=tmp_path)
        with pytest.raises(DuckDBNotInitializedError):
            await client.query("SELECT 1")

    @pytest.mark.asyncio
    async def test_query_executes_simple_query(self, tmp_path: Path) -> None:
        """Test that query() executes a simple query and returns results."""
        client = DuckDBClient(csv_data_path=tmp_path)
        await client.init()
        try:
            result = await client.query("SELECT 1 AS value")
            assert len(result) == 1
            assert result[0]["value"] == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_query_supports_parameters(self, tmp_path: Path) -> None:
        """Test that query() supports parameter substitution."""
        client = DuckDBClient(csv_data_path=tmp_path)
        await client.init()
        try:
            result = await client.query(
                "SELECT $x AS x, $y AS y",
                params={"x": 10, "y": "hello"},
            )
            assert len(result) == 1
            assert result[0]["x"] == 10
            assert result[0]["y"] == "hello"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_query_raises_for_invalid_sql(self, tmp_path: Path) -> None:
        """Test that query() raises DuckDBQueryError for invalid SQL."""
        client = DuckDBClient(csv_data_path=tmp_path)
        await client.init()
        try:
            with pytest.raises(DuckDBQueryError):
                await client.query("INVALID SQL SYNTAX")
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_query_reads_csv_file(self, tmp_path: Path) -> None:
        """Test that query() can read data from a CSV file."""
        # Create a test CSV file
        csv_file = tmp_path / "test_data.csv"
        csv_file.write_text("id,name,value\n1,foo,100\n2,bar,200\n")

        client = DuckDBClient(csv_data_path=tmp_path)
        await client.init()
        try:
            csv_path = client.get_csv_path("test_data.csv")
            result = await client.query(f"SELECT * FROM read_csv_auto('{csv_path}')")
            assert len(result) == 2
            assert result[0]["id"] == 1
            assert result[0]["name"] == "foo"
            assert result[1]["id"] == 2
        finally:
            await client.close()

    def test_get_csv_path_returns_full_path(self, tmp_path: Path) -> None:
        """Test that get_csv_path returns the full path to a CSV file."""
        client = DuckDBClient(csv_data_path=tmp_path)
        path = client.get_csv_path("test.csv")
        assert path == str(tmp_path / "test.csv")


class TestValidateCsvFilename:
    """Tests for _validate_csv_filename validation."""

    def test_empty_filename_raises_value_error(self, tmp_path: Path) -> None:
        """Test that empty filename raises ValueError."""
        client = DuckDBClient(csv_data_path=tmp_path)
        with pytest.raises(ValueError, match="cannot be empty"):
            client.get_csv_path("")

    def test_path_traversal_with_double_dot_raises_value_error(self, tmp_path: Path) -> None:
        """Test that path traversal with .. raises ValueError."""
        client = DuckDBClient(csv_data_path=tmp_path)
        with pytest.raises(ValueError, match="path traversal detected"):
            client.get_csv_path("../test.csv")

    def test_path_traversal_with_forward_slash_raises_value_error(self, tmp_path: Path) -> None:
        """Test that path with / raises ValueError."""
        client = DuckDBClient(csv_data_path=tmp_path)
        with pytest.raises(ValueError, match="path traversal detected"):
            client.get_csv_path("subdir/test.csv")

    def test_path_traversal_with_backslash_raises_value_error(self, tmp_path: Path) -> None:
        """Test that path with \\ raises ValueError."""
        client = DuckDBClient(csv_data_path=tmp_path)
        with pytest.raises(ValueError, match="path traversal detected"):
            client.get_csv_path("subdir\\test.csv")

    def test_non_csv_extension_raises_value_error(self, tmp_path: Path) -> None:
        """Test that non-.csv extension raises ValueError."""
        client = DuckDBClient(csv_data_path=tmp_path)
        with pytest.raises(ValueError, match=r"must end with \.csv"):
            client.get_csv_path("test.txt")


class TestCreateDuckDBClient:
    """Tests for create_duckdb_client factory function."""

    @pytest.mark.asyncio
    async def test_creates_and_initializes_client(self, tmp_path: Path) -> None:
        """Test that create_duckdb_client creates and initializes a client."""
        settings = _MockSettings(csv_data_path=str(tmp_path))
        client = await create_duckdb_client(settings)  # type: ignore[arg-type]
        try:
            assert client._initialized is True
            assert client.csv_data_path == tmp_path
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_raises_for_invalid_path(self) -> None:
        """Test that create_duckdb_client raises for invalid path."""
        settings = _MockSettings(csv_data_path="/nonexistent/path")
        with pytest.raises(DuckDBConnectionError):
            await create_duckdb_client(settings)  # type: ignore[arg-type]


class TestDuckDBExceptions:
    """Tests for DuckDB exception classes."""

    def test_not_initialized_error_message(self) -> None:
        """Test DuckDBNotInitializedError has correct message."""
        exc = DuckDBNotInitializedError()
        assert "not initialized" in str(exc).lower() or "init" in str(exc).lower()

    def test_connection_error_message(self) -> None:
        """Test DuckDBConnectionError stores custom message."""
        exc = DuckDBConnectionError("Custom error message")
        assert "Custom error message" in str(exc)

    def test_query_error_message(self) -> None:
        """Test DuckDBQueryError stores custom message."""
        exc = DuckDBQueryError("Query failed")
        assert "Query failed" in str(exc)


class TestDuckDBQueryInternalErrors:
    """Tests for internal query error handling paths."""

    @pytest.mark.asyncio
    async def test_query_reraises_duckdb_not_initialized_from_inner_check(
        self, tmp_path: Path
    ) -> None:
        """Test that query re-raises DuckDBNotInitializedError from _query_sync."""
        client = DuckDBClient(csv_data_path=tmp_path)
        # Manually set initialized to True but leave connection None to trigger inner check
        client._initialized = True
        client._connection = None

        with pytest.raises(DuckDBNotInitializedError):
            await client.query("SELECT 1")

    @pytest.mark.asyncio
    async def test_query_wraps_generic_exception_in_query_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that query wraps generic exceptions in DuckDBQueryError."""
        import anyio

        client = DuckDBClient(csv_data_path=tmp_path)
        await client.init()

        # Mock anyio.to_thread.run_sync to raise a generic exception
        async def failing_run_sync(fn: object, *args: object, **kwargs: object) -> None:
            raise RuntimeError("Simulated failure")

        monkeypatch.setattr(anyio.to_thread, "run_sync", failing_run_sync)

        try:
            with pytest.raises(DuckDBQueryError, match="Simulated failure"):
                await client.query("SELECT 1")
        finally:
            # Restore original before close
            monkeypatch.undo()
            await client.close()


class TestDuckDBInitErrors:
    """Tests for initialization error handling paths."""

    @pytest.mark.asyncio
    async def test_init_wraps_generic_exception_in_connection_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that init wraps generic exceptions in DuckDBConnectionError."""
        import duckdb as duckdb_module

        client = DuckDBClient(csv_data_path=tmp_path)

        # Mock duckdb.connect to raise a generic exception
        def failing_connect(*args: object, **kwargs: object) -> None:
            raise RuntimeError("Connection failed unexpectedly")

        monkeypatch.setattr(duckdb_module, "connect", failing_connect)

        with pytest.raises(DuckDBConnectionError, match="Connection failed unexpectedly"):
            await client.init()
