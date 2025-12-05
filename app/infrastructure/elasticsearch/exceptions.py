"""Elasticsearch-specific exceptions."""


class ElasticsearchNotInitializedError(RuntimeError):
    """Raised when Elasticsearch client methods are called before init()."""

    MESSAGE = "Elasticsearch client not initialized; call init() first"

    def __init__(self, message: str | None = None) -> None:
        """Initialize with a fallback message when none provided."""
        super().__init__(message or self.MESSAGE)
