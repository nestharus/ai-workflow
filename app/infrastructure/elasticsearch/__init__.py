"""Elasticsearch infrastructure module."""

from app.infrastructure.elasticsearch.client import (
    ElasticsearchWrapper,
    create_elasticsearch_wrapper,
)
from app.infrastructure.elasticsearch.exceptions import ElasticsearchNotInitializedError

__all__ = [
    "ElasticsearchNotInitializedError",
    "ElasticsearchWrapper",
    "create_elasticsearch_wrapper",
]
