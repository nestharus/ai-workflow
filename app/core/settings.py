"""Application settings and validation helpers."""

from urllib.parse import urlsplit

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings

# Deliberately verbose: pydantic-core's Rust regex engine does not support
# lookahead assertions, so this permutation-based pattern explicitly enforces
# uppercase, lowercase, digit, and special characters. Do not "simplify" this
# regex unless you verify the engine can handle lookaheads (see pydantic-core
# regex limitations).
CREDENTIAL_COMPLEXITY_PATTERN = (
    r"^(?:"
    r"(?:[A-Z].*[a-z].*\d.*[^A-Za-z0-9])|"
    r"(?:[A-Z].*\d.*[a-z].*[^A-Za-z0-9])|"
    r"(?:[A-Z].*\d.*[^A-Za-z0-9].*[a-z])|"
    r"(?:[A-Z].*[^A-Za-z0-9].*[a-z].*\d)|"
    r"(?:[A-Z].*[^A-Za-z0-9].*\d.*[a-z])|"
    r"(?:[A-Z].*[a-z].*[^A-Za-z0-9].*\d)|"
    r"(?:[a-z].*[A-Z].*\d.*[^A-Za-z0-9])|"
    r"(?:[a-z].*\d.*[A-Z].*[^A-Za-z0-9])|"
    r"(?:[a-z].*\d.*[^A-Za-z0-9].*[A-Z])|"
    r"(?:[a-z].*[^A-Za-z0-9].*[A-Z].*\d)|"
    r"(?:[a-z].*[^A-Za-z0-9].*\d.*[A-Z])|"
    r"(?:[a-z].*[A-Z].*[^A-Za-z0-9].*\d)|"
    r"(?:\d.*[A-Z].*[a-z].*[^A-Za-z0-9])|"
    r"(?:\d.*[a-z].*[A-Z].*[^A-Za-z0-9])|"
    r"(?:\d.*[a-z].*[^A-Za-z0-9].*[A-Z])|"
    r"(?:\d.*[^A-Za-z0-9].*[A-Z].*[a-z])|"
    r"(?:\d.*[^A-Za-z0-9].*[a-z].*[A-Z])|"
    r"(?:\d.*[A-Z].*[^A-Za-z0-9].*[a-z])|"
    r"(?:[^A-Za-z0-9].*[A-Z].*[a-z].*\d)|"
    r"(?:[^A-Za-z0-9].*[a-z].*[A-Z].*\d)|"
    r"(?:[^A-Za-z0-9].*[a-z].*\d.*[A-Z])|"
    r"(?:[^A-Za-z0-9].*\d.*[A-Z].*[a-z])|"
    r"(?:[^A-Za-z0-9].*\d.*[a-z].*[A-Z])|"
    r"(?:[^A-Za-z0-9].*[A-Z].*\d.*[a-z])"
    r")$"
)


class InvalidSurrealUrlError(ValueError):
    """Raised when the SurrealDB URL uses an unsupported scheme."""

    def __init__(self) -> None:
        """Set a descriptive validation message."""
        super().__init__("surrealdb_url must use ws, wss, http, or https")


class InvalidElasticsearchUrlError(ValueError):
    """Raised when the Elasticsearch URL uses an unsupported scheme."""

    def __init__(self) -> None:
        """Set a descriptive validation message."""
        super().__init__("elasticsearch_url must use http or https")


class PositiveIntegerValidationError(ValueError):
    """Raised when a numeric field is not positive."""

    def __init__(self, field_name: str) -> None:
        """Embed the offending field name in the message."""
        super().__init__(f"{field_name} must be a positive integer")


class NonNegativeElasticsearchReplicasError(ValueError):
    """Raised when Elasticsearch replicas is negative."""

    def __init__(self) -> None:
        """Set a descriptive validation message."""
        super().__init__("elasticsearch_replicas must be zero or a positive integer")


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables.

    Includes Knowledge Graph infrastructure settings for SurrealDB and Elasticsearch.
    """

    app_name: str = "AI Workflow API"
    app_version: str = "0.1.0"
    debug: bool = False
    include_error_body: bool = False

    surrealdb_url: str = "ws://localhost:8000/rpc"
    surrealdb_namespace: str = "knowledge"
    surrealdb_database: str = "facts"
    surrealdb_user: str = Field(
        ...,
        min_length=12,
        pattern=CREDENTIAL_COMPLEXITY_PATTERN,
        repr=False,
        json_schema_extra={"format": "password"},
    )
    surrealdb_pass: str = Field(
        ...,
        min_length=12,
        pattern=CREDENTIAL_COMPLEXITY_PATTERN,
        repr=False,
        json_schema_extra={"format": "password"},
    )
    surrealdb_pool_size: int = 5

    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_connections_per_node: int = 25
    elasticsearch_request_timeout: int = 10
    elasticsearch_shards: int = 1
    elasticsearch_replicas: int = 0
    embedding_dimension: int = 768

    @field_validator("surrealdb_url")
    @classmethod
    def _validate_surrealdb_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"ws", "wss", "http", "https"} or not parsed.netloc:
            raise InvalidSurrealUrlError()
        return value

    @field_validator("elasticsearch_url")
    @classmethod
    def _validate_elasticsearch_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise InvalidElasticsearchUrlError()
        return value

    @field_validator(
        "surrealdb_pool_size",
        "elasticsearch_connections_per_node",
        "elasticsearch_request_timeout",
        "elasticsearch_shards",
        "embedding_dimension",
    )
    @classmethod
    def _validate_positive(cls, value: int, info: ValidationInfo) -> int:
        if value <= 0:
            field_name = info.field_name or "value"
            raise PositiveIntegerValidationError(field_name)
        return value

    @field_validator("elasticsearch_replicas")
    @classmethod
    def _validate_non_negative(cls, value: int) -> int:
        if value < 0:
            raise NonNegativeElasticsearchReplicasError()
        return value
