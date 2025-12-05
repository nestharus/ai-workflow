"""DuckDB-specific exceptions."""


class DuckDBClientError(RuntimeError):
    """Base class for DuckDB client errors."""


class DuckDBNotInitializedError(DuckDBClientError):
    """Raised when DuckDB client methods are called before init()."""

    MESSAGE = "DuckDB client not initialized; call init() first"

    def __init__(self, message: str | None = None) -> None:
        """Initialize with a fallback message when none provided."""
        super().__init__(message or self.MESSAGE)


class DuckDBConnectionError(DuckDBClientError):
    """Raised when DuckDB connection fails."""

    def __init__(self, message: str) -> None:
        """Initialize with a descriptive connection error message."""
        super().__init__(f"DuckDB connection failed: {message}")


class DuckDBQueryError(DuckDBClientError):
    """Raised when a DuckDB query execution fails."""

    def __init__(self, message: str) -> None:
        """Initialize with a descriptive query error message."""
        super().__init__(f"DuckDB query failed: {message}")
