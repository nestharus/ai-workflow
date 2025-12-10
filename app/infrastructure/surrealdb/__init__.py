"""SurrealDB infrastructure module."""

from app.infrastructure.surrealdb.exceptions import (
    SurrealDBPoolNotInitializedError,
    UnsupportedSchemaVersionError,
)
from app.infrastructure.surrealdb.pool import SurrealDBPool, create_surrealdb_pool

__all__ = [
    "SurrealDBPool",
    "SurrealDBPoolNotInitializedError",
    "UnsupportedSchemaVersionError",
    "create_surrealdb_pool",
]
