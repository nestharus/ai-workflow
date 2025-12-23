"""Unit tests for Settings exception classes."""

from __future__ import annotations

import secrets

import pytest
from pydantic import ValidationError

from app.core.settings import (
    InvalidElasticsearchUrlError,
    InvalidSurrealUrlError,
    NonNegativeElasticsearchReplicasError,
    PositiveIntegerValidationError,
    Settings,
)


def _generate_test_credential(prefix: str) -> str:
    """Generate a valid credential string for testing."""
    return f"{prefix}Aa1!{secrets.token_hex(4)}"


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure SURREALDB_USER and SURREALDB_PASS are set to valid values for testing."""
    monkeypatch.setenv("SURREALDB_USER", _generate_test_credential("TestUser"))
    monkeypatch.setenv("SURREALDB_PASS", _generate_test_credential("TestPass"))


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


class TestSettingsValidation:
    """Tests for Settings field validation."""

    def test_invalid_surrealdb_url_scheme_raises_error(self, clean_env: None) -> None:
        """Test that invalid SurrealDB URL scheme raises InvalidSurrealUrlError."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(surrealdb_url="ftp://localhost:8000/rpc")
        assert "surrealdb_url" in str(exc_info.value).lower()

    def test_invalid_elasticsearch_url_scheme_raises_error(self, clean_env: None) -> None:
        """Test that invalid Elasticsearch URL scheme raises InvalidElasticsearchUrlError."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(elasticsearch_url="ftp://localhost:9200")
        assert "elasticsearch_url" in str(exc_info.value).lower()

    def test_zero_pool_size_raises_error(self, clean_env: None) -> None:
        """Test that zero pool size raises PositiveIntegerValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(surrealdb_pool_size=0)
        assert "positive" in str(exc_info.value).lower()

    def test_negative_pool_size_raises_error(self, clean_env: None) -> None:
        """Test that negative pool size raises PositiveIntegerValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(surrealdb_pool_size=-1)
        assert "positive" in str(exc_info.value).lower()

    def test_negative_elasticsearch_replicas_raises_error(self, clean_env: None) -> None:
        """Test that negative replicas raises NonNegativeElasticsearchReplicasError."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(elasticsearch_replicas=-1)
        assert "elasticsearch_replicas" in str(exc_info.value).lower()

    def test_zero_elasticsearch_replicas_is_valid(self, clean_env: None) -> None:
        """Test that zero replicas is valid (non-negative)."""
        settings = Settings(elasticsearch_replicas=0)
        assert settings.elasticsearch_replicas == 0

    def test_valid_settings_passes(self, clean_env: None) -> None:
        """Test that valid settings pass validation."""
        settings = Settings()
        assert settings.surrealdb_pool_size == 5
        assert settings.elasticsearch_replicas == 0
