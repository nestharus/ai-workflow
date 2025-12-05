"""Unit tests for Settings exception classes."""

from __future__ import annotations

from app.core.settings import (
    InvalidElasticsearchUrlError,
    InvalidSurrealUrlError,
    NonNegativeElasticsearchReplicasError,
    PositiveIntegerValidationError,
)


class TestSettingsExceptions:
    """Tests for settings validation exception classes."""

    def test_invalid_surrealdb_url_error_message(self) -> None:
        """Test InvalidSurrealUrlError has correct message."""
        exc = InvalidSurrealUrlError()
        assert "surrealdb_url" in str(exc)
        assert "ws" in str(exc) or "http" in str(exc)

    def test_invalid_elasticsearch_url_error_message(self) -> None:
        """Test InvalidElasticsearchUrlError has correct message."""
        exc = InvalidElasticsearchUrlError()
        assert "elasticsearch_url" in str(exc)
        assert "http" in str(exc)

    def test_positive_integer_validation_error_includes_field_name(self) -> None:
        """Test PositiveIntegerValidationError includes field name in message."""
        exc = PositiveIntegerValidationError("test_field")
        assert "test_field" in str(exc)
        assert "positive" in str(exc).lower()

    def test_non_negative_elasticsearch_replicas_error_message(self) -> None:
        """Test NonNegativeElasticsearchReplicasError has correct message."""
        exc = NonNegativeElasticsearchReplicasError()
        assert "elasticsearch_replicas" in str(exc)
        assert "zero" in str(exc).lower() or "positive" in str(exc).lower()
