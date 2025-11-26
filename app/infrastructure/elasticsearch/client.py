"""Elasticsearch client wrapper with async support."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

import anyio
from elasticsearch import Elasticsearch
from elasticsearch import exceptions as es_exceptions

from app.infrastructure.elasticsearch.exceptions import ElasticsearchNotInitializedError

if TYPE_CHECKING:
    from app.core.settings import Settings

logger = logging.getLogger(__name__)

type DictStrAny = dict[str, Any]


class ElasticsearchWrapper:
    """Async-friendly wrapper around the synchronous Elasticsearch client."""

    def __init__(
        self,
        hosts: str | list[str],
        *,
        connections_per_node: int,
        request_timeout: int,
        number_of_shards: int,
        number_of_replicas: int,
        retry_on_timeout: bool = True,
    ) -> None:
        """Configure the underlying Elasticsearch client parameters."""
        self._client = Elasticsearch(
            hosts=hosts,
            connections_per_node=connections_per_node,
            request_timeout=request_timeout,
            retry_on_timeout=retry_on_timeout,
        )
        self._initialized = False
        self._number_of_shards = number_of_shards
        self._number_of_replicas = number_of_replicas

    def _ensure_initialized(self) -> None:
        """Raise if the client has not been initialized."""
        if not self._initialized:
            raise ElasticsearchNotInitializedError()

    async def init(self) -> None:
        """Verify connectivity to Elasticsearch."""
        await anyio.to_thread.run_sync(self._client.ping)
        self._initialized = True
        logger.info("Elasticsearch client initialized")

    async def close(self) -> None:
        """Close the underlying client."""
        await anyio.to_thread.run_sync(self._client.close)
        self._initialized = False

    async def search(self, index: str, query: dict[str, Any]) -> dict[str, Any]:
        """Execute a search request in a worker thread."""
        self._ensure_initialized()

        def _sync_search() -> dict[str, Any]:
            return cast("DictStrAny", self._client.search(index=index, query=query))

        return await anyio.to_thread.run_sync(_sync_search)

    async def index(
        self, index: str, document: dict[str, Any], id: str | None = None
    ) -> dict[str, Any]:
        """Index a document asynchronously."""
        self._ensure_initialized()

        def _sync_index() -> dict[str, Any]:
            return cast("DictStrAny", self._client.index(index=index, document=document, id=id))

        return await anyio.to_thread.run_sync(_sync_index)

    async def bulk(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        """Perform bulk operations asynchronously."""
        self._ensure_initialized()

        def _sync_bulk() -> dict[str, Any]:
            return cast("DictStrAny", self._client.bulk(operations=operations))

        return await anyio.to_thread.run_sync(_sync_bulk)

    async def create_index(
        self, index: str, mappings: dict[str, Any], settings: dict[str, Any]
    ) -> None:
        """Create an index if it does not already exist."""
        self._ensure_initialized()

        def _create_index() -> None:
            try:
                self._client.indices.create(index=index, mappings=mappings, settings=settings)
            except es_exceptions.RequestError as exc:
                error_type = ""
                try:
                    error_type = exc.info.get("error", {}).get("type", "")
                except (AttributeError, KeyError):  # pragma: no cover - defensive
                    error_type = getattr(exc, "error", "") or ""
                if error_type == "resource_already_exists_exception":
                    logger.debug("Index %s already exists; skipping creation", index)
                    return
                raise

        await anyio.to_thread.run_sync(_create_index)

    async def initialize_indices(self) -> None:
        """Initialize Knowledge Graph indices for facts and entity aliases."""
        self._ensure_initialized()
        base_settings = {
            "number_of_shards": self._number_of_shards,
            "number_of_replicas": self._number_of_replicas,
        }

        facts_mappings = {
            "properties": {
                "text": {"type": "text"},
                "standardized_text": {"type": "text"},
                "source_file": {"type": "keyword"},
                "entity_ids": {"type": "keyword"},
                "topic_ids": {"type": "keyword"},
            }
        }

        entity_aliases_mappings = {
            "properties": {
                "canonical_name": {"type": "keyword"},
                "alias": {"type": "text"},
                "entity_type": {"type": "keyword"},
            }
        }

        await self.create_index(
            index="facts_index",
            mappings=facts_mappings,
            settings=base_settings,
        )

        await self.create_index(
            index="entity_aliases_index",
            mappings=entity_aliases_mappings,
            settings=base_settings,
        )


async def create_elasticsearch_wrapper(settings: Settings) -> ElasticsearchWrapper:
    """Factory that builds and initializes an Elasticsearch wrapper from settings."""
    wrapper = ElasticsearchWrapper(
        hosts=settings.elasticsearch_url,
        connections_per_node=settings.elasticsearch_connections_per_node,
        request_timeout=settings.elasticsearch_request_timeout,
        number_of_shards=settings.elasticsearch_shards,
        number_of_replicas=settings.elasticsearch_replicas,
    )
    await wrapper.init()
    try:
        await wrapper.initialize_indices()
    except Exception:
        await wrapper.close()
        raise
    return wrapper
