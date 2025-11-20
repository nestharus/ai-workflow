# Knowledge Graph Infrastructure

This directory contains utilities and scripts for the documentation integration pipeline that builds a unified
Knowledge Graph from multiple markdown sources.

## Architecture Overview

The Knowledge Graph uses a dual-database architecture:

1. **SurrealDB**: Graph database storing Facts, Entities, Topics, and their relationships. Includes vector search
   support for semantic similarity.
2. **Elasticsearch**: Search engine providing BM25 keyword search on facts and entity aliases for high-recall
   lexical matching.

## Database Connections

`db_connections.py` provides connection pooling utilities:

* **SurrealDBPool**: Custom async connection pool using asyncio.Queue. Manages multiple WebSocket connections to
  SurrealDB for concurrent operations.
* **ElasticsearchWrapper**: Wrapper around the sync Elasticsearch client that integrates with async code using
  thread executors.

## Schema Design

### SurrealDB Schema

**Tables**:
* `facts`: Atomic facts extracted from documentation with embeddings
* `entities`: Canonical entities (tools, concepts, commands) with aliases
* `topics`: Hierarchical topic taxonomy

**Relationships**:
* `MENTIONS`: Links facts to entities they reference
* `HAS_SUBTOPIC`: Builds topic hierarchy
* `CONCERNS`: Tags facts with topics
* `OVERLAPS_WITH`, `CONTRADICTS`, `REFINES`: Fact-to-fact relationships for conflict detection

**Vector Search**:
* HNSW index on `facts.embedding` (4096-dimensional, cosine distance)
* Enables semantic search using `<|k, limit|>` operator

### Elasticsearch Indices

**facts_index**: BM25 search on fact text and standardized text

**entity_aliases_index**: Fast lookup from entity mentions to canonical names

## Usage

```python
from app.core.settings import Settings
from scripts.knowledge.db_connections import (
    create_surrealdb_pool,
    create_elasticsearch_wrapper,
)

# Initialize connections
settings = Settings()
surreal_pool = await create_surrealdb_pool(settings)
es_wrapper = await create_elasticsearch_wrapper(settings)

# Use SurrealDB
async with surreal_pool.acquire() as db:
    result = await db.query("SELECT * FROM facts LIMIT 10")

# Use Elasticsearch
results = await es_wrapper.search(
    index="facts_index",
    query={"match": {"text": "pytest"}}
)

# Cleanup
await surreal_pool.close()
await es_wrapper.close()
```

## Configuration

Database connection parameters are configured via environment variables or `app/core/settings.py`:

* `SURREALDB_URL`: WebSocket URL (default: ws://localhost:8000/rpc)
* `SURREALDB_NAMESPACE`: Namespace (default: knowledge)
* `SURREALDB_DATABASE`: Database name (default: facts)
* `SURREALDB_POOL_SIZE`: Connection pool size (default: 5)
* `ELASTICSEARCH_URL`: HTTP endpoint (default: `http://localhost:9200`)
* `ELASTICSEARCH_MAXSIZE`: Max connections (default: 25)

## Docker Services

The `docker-compose.yml` defines:

* `surrealdb`: SurrealDB server on port 8000 with persistent volume
* `elasticsearch`: Elasticsearch server on port 9200 with persistent volume

Start services: `docker-compose up -d surrealdb elasticsearch`

## Future Scripts

Subsequent phases will add:
* `embeddings.py`: Qwen embedding generation
* `reranker.py`: Qwen reranking
* `staging.py`: DuckDB staging and provenance
* `extraction.py`: Atomic fact extraction with LLMs
* `entities.py`: Entity resolution and normalization
* `topics.py`: Hierarchical topic discovery
* `detection.py`: Conflict detection pipeline
* `questionnaire.py`: Human-readable conflict reports
* `resolve.py`: Conflict resolution integration
* `batch_ingest.py`: Full pipeline orchestration

See the subsequent phases documentation for details on these components.
