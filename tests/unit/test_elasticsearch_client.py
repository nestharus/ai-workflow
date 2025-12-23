"""Unit tests for Elasticsearch client wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from elasticsearch import exceptions as es_exceptions

from app.infrastructure.elasticsearch.client import (
    ElasticsearchWrapper,
    create_elasticsearch_wrapper,
)
from app.infrastructure.elasticsearch.exceptions import ElasticsearchNotInitializedError


class _MockSettings:
    """Mock settings for testing."""

    def __init__(self) -> None:
        self.elasticsearch_url = "http://localhost:9200"
        self.elasticsearch_connections_per_node = 10
        self.elasticsearch_request_timeout = 30
        self.elasticsearch_shards = 1
        self.elasticsearch_replicas = 0


class TestElasticsearchWrapper:
    """Tests for ElasticsearchWrapper class."""

    def test_init_creates_client(self) -> None:
        """Test that __init__ creates the underlying Elasticsearch client."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch") as mock_es:
            wrapper = ElasticsearchWrapper(
                hosts="http://localhost:9200",
                connections_per_node=10,
                request_timeout=30,
                number_of_shards=1,
                number_of_replicas=0,
            )
            mock_es.assert_called_once()
            assert wrapper._initialized is False

    def test_ensure_initialized_raises_when_not_initialized(self) -> None:
        """Test that _ensure_initialized raises when client not initialized."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch"):
            wrapper = ElasticsearchWrapper(
                hosts="http://localhost:9200",
                connections_per_node=10,
                request_timeout=30,
                number_of_shards=1,
                number_of_replicas=0,
            )
            with pytest.raises(ElasticsearchNotInitializedError):
                wrapper._ensure_initialized()

    @pytest.mark.asyncio
    async def test_init_marks_as_initialized(self) -> None:
        """Test that init() marks the client as initialized."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch") as mock_es:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_es.return_value = mock_client

            wrapper = ElasticsearchWrapper(
                hosts="http://localhost:9200",
                connections_per_node=10,
                request_timeout=30,
                number_of_shards=1,
                number_of_replicas=0,
            )
            await wrapper.init()
            assert wrapper._initialized is True

    @pytest.mark.asyncio
    async def test_init_not_initialized_when_ping_returns_false(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that init() marks client as not initialized when ping returns False."""
        import logging

        with patch("app.infrastructure.elasticsearch.client.Elasticsearch") as mock_es:
            mock_client = MagicMock()
            mock_client.ping.return_value = False
            mock_es.return_value = mock_client

            wrapper = ElasticsearchWrapper(
                hosts="http://localhost:9200",
                connections_per_node=10,
                request_timeout=30,
                number_of_shards=1,
                number_of_replicas=0,
            )
            with caplog.at_level(logging.WARNING):
                await wrapper.init()

            assert wrapper._initialized is False
            assert "ping returned False" in caplog.text

    @pytest.mark.asyncio
    async def test_close_marks_as_not_initialized(self) -> None:
        """Test that close() marks the client as not initialized."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch") as mock_es:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_es.return_value = mock_client

            wrapper = ElasticsearchWrapper(
                hosts="http://localhost:9200",
                connections_per_node=10,
                request_timeout=30,
                number_of_shards=1,
                number_of_replicas=0,
            )
            await wrapper.init()
            await wrapper.close()
            assert wrapper._initialized is False
            mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_not_initialized(self) -> None:
        """Test that health_check returns False when not initialized."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch"):
            wrapper = ElasticsearchWrapper(
                hosts="http://localhost:9200",
                connections_per_node=10,
                request_timeout=30,
                number_of_shards=1,
                number_of_replicas=0,
            )
            result = await wrapper.health_check()
            assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_true_when_healthy(self) -> None:
        """Test that health_check returns True when ping succeeds."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch") as mock_es:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_es.return_value = mock_client

            wrapper = ElasticsearchWrapper(
                hosts="http://localhost:9200",
                connections_per_node=10,
                request_timeout=30,
                number_of_shards=1,
                number_of_replicas=0,
            )
            await wrapper.init()
            result = await wrapper.health_check()
            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_exception(self) -> None:
        """Test that health_check returns False when ping raises."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch") as mock_es:
            mock_client = MagicMock()
            # First call (init) succeeds
            mock_client.ping.side_effect = [True, Exception("Connection failed")]
            mock_es.return_value = mock_client

            wrapper = ElasticsearchWrapper(
                hosts="http://localhost:9200",
                connections_per_node=10,
                request_timeout=30,
                number_of_shards=1,
                number_of_replicas=0,
            )
            await wrapper.init()
            result = await wrapper.health_check()
            assert result is False

    @pytest.mark.asyncio
    async def test_search_raises_when_not_initialized(self) -> None:
        """Test that search raises when not initialized."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch"):
            wrapper = ElasticsearchWrapper(
                hosts="http://localhost:9200",
                connections_per_node=10,
                request_timeout=30,
                number_of_shards=1,
                number_of_replicas=0,
            )
            with pytest.raises(ElasticsearchNotInitializedError):
                await wrapper.search("test_index", {"match_all": {}})

    @pytest.mark.asyncio
    async def test_search_returns_results(self) -> None:
        """Test that search returns results from Elasticsearch."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch") as mock_es:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_client.search.return_value = {"hits": {"hits": []}}
            mock_es.return_value = mock_client

            wrapper = ElasticsearchWrapper(
                hosts="http://localhost:9200",
                connections_per_node=10,
                request_timeout=30,
                number_of_shards=1,
                number_of_replicas=0,
            )
            await wrapper.init()
            result = await wrapper.search("test_index", {"match_all": {}})
            assert "hits" in result

    @pytest.mark.asyncio
    async def test_index_raises_when_not_initialized(self) -> None:
        """Test that index raises when not initialized."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch"):
            wrapper = ElasticsearchWrapper(
                hosts="http://localhost:9200",
                connections_per_node=10,
                request_timeout=30,
                number_of_shards=1,
                number_of_replicas=0,
            )
            with pytest.raises(ElasticsearchNotInitializedError):
                await wrapper.index("test_index", {"field": "value"})

    @pytest.mark.asyncio
    async def test_index_succeeds(self) -> None:
        """Test that index successfully indexes a document."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch") as mock_es:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_client.index.return_value = {"result": "created"}
            mock_es.return_value = mock_client

            wrapper = ElasticsearchWrapper(
                hosts="http://localhost:9200",
                connections_per_node=10,
                request_timeout=30,
                number_of_shards=1,
                number_of_replicas=0,
            )
            await wrapper.init()
            result = await wrapper.index("test_index", {"field": "value"}, id="doc_1")
            assert result["result"] == "created"

    @pytest.mark.asyncio
    async def test_bulk_raises_when_not_initialized(self) -> None:
        """Test that bulk raises when not initialized."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch"):
            wrapper = ElasticsearchWrapper(
                hosts="http://localhost:9200",
                connections_per_node=10,
                request_timeout=30,
                number_of_shards=1,
                number_of_replicas=0,
            )
            with pytest.raises(ElasticsearchNotInitializedError):
                await wrapper.bulk([])

    @pytest.mark.asyncio
    async def test_bulk_succeeds(self) -> None:
        """Test that bulk performs operations successfully."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch") as mock_es:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_client.bulk.return_value = {"errors": False, "items": []}
            mock_es.return_value = mock_client

            wrapper = ElasticsearchWrapper(
                hosts="http://localhost:9200",
                connections_per_node=10,
                request_timeout=30,
                number_of_shards=1,
                number_of_replicas=0,
            )
            await wrapper.init()
            result = await wrapper.bulk([{"index": {"_index": "test"}}])
            assert result["errors"] is False

    @pytest.mark.asyncio
    async def test_create_index_raises_when_not_initialized(self) -> None:
        """Test that create_index raises when not initialized."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch"):
            wrapper = ElasticsearchWrapper(
                hosts="http://localhost:9200",
                connections_per_node=10,
                request_timeout=30,
                number_of_shards=1,
                number_of_replicas=0,
            )
            with pytest.raises(ElasticsearchNotInitializedError):
                await wrapper.create_index("test_index", {}, {})

    @pytest.mark.asyncio
    async def test_create_index_succeeds(self) -> None:
        """Test that create_index creates an index."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch") as mock_es:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_es.return_value = mock_client

            wrapper = ElasticsearchWrapper(
                hosts="http://localhost:9200",
                connections_per_node=10,
                request_timeout=30,
                number_of_shards=1,
                number_of_replicas=0,
            )
            await wrapper.init()
            await wrapper.create_index("test_index", {"properties": {}}, {"number_of_shards": 1})
            mock_client.indices.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_index_ignores_already_exists_error(self) -> None:
        """Test that create_index ignores 'already exists' errors."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch") as mock_es:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            # Simulate resource_already_exists_exception
            error = es_exceptions.RequestError(
                400, "error", {"error": {"type": "resource_already_exists_exception"}}
            )
            mock_client.indices.create.side_effect = error
            mock_es.return_value = mock_client

            wrapper = ElasticsearchWrapper(
                hosts="http://localhost:9200",
                connections_per_node=10,
                request_timeout=30,
                number_of_shards=1,
                number_of_replicas=0,
            )
            await wrapper.init()
            # Should not raise
            await wrapper.create_index("test_index", {}, {})

    @pytest.mark.asyncio
    async def test_create_index_raises_other_request_errors(self) -> None:
        """Test that create_index raises non-'already exists' errors."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch") as mock_es:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            # Simulate a different error type
            error = es_exceptions.RequestError(
                400, "error", {"error": {"type": "mapper_parsing_exception"}}
            )
            mock_client.indices.create.side_effect = error
            mock_es.return_value = mock_client

            wrapper = ElasticsearchWrapper(
                hosts="http://localhost:9200",
                connections_per_node=10,
                request_timeout=30,
                number_of_shards=1,
                number_of_replicas=0,
            )
            await wrapper.init()
            with pytest.raises(es_exceptions.RequestError):
                await wrapper.create_index("test_index", {}, {})

    @pytest.mark.asyncio
    async def test_initialize_indices_creates_both_indices(self) -> None:
        """Test that initialize_indices creates facts and entity_aliases indices."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch") as mock_es:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_es.return_value = mock_client

            wrapper = ElasticsearchWrapper(
                hosts="http://localhost:9200",
                connections_per_node=10,
                request_timeout=30,
                number_of_shards=1,
                number_of_replicas=0,
            )
            await wrapper.init()
            await wrapper.initialize_indices()
            # Should have been called twice (facts_index and entity_aliases_index)
            assert mock_client.indices.create.call_count == 2


class TestCreateElasticsearchWrapper:
    """Tests for create_elasticsearch_wrapper factory function."""

    @pytest.mark.asyncio
    async def test_creates_and_initializes_wrapper(self) -> None:
        """Test that factory creates and initializes a wrapper."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch") as mock_es:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_es.return_value = mock_client

            settings = _MockSettings()
            wrapper = await create_elasticsearch_wrapper(settings)  # type: ignore[arg-type]
            try:
                assert wrapper._initialized is True
            finally:
                await wrapper.close()

    @pytest.mark.asyncio
    async def test_closes_on_index_initialization_failure(self) -> None:
        """Test that wrapper is closed if initialize_indices fails."""
        with patch("app.infrastructure.elasticsearch.client.Elasticsearch") as mock_es:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_client.indices.create.side_effect = Exception("Index creation failed")
            mock_es.return_value = mock_client

            settings = _MockSettings()
            with pytest.raises(Exception, match="Index creation failed"):
                await create_elasticsearch_wrapper(settings)  # type: ignore[arg-type]
            # Verify close was called
            mock_client.close.assert_called()


class TestElasticsearchExceptions:
    """Tests for Elasticsearch exception classes."""

    def test_not_initialized_error_message(self) -> None:
        """Test ElasticsearchNotInitializedError has correct message."""
        exc = ElasticsearchNotInitializedError()
        assert "initialized" in str(exc).lower() or "init" in str(exc).lower()
