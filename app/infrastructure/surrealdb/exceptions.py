"""SurrealDB-specific exceptions."""


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
