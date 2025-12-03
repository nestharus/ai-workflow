# Knowledge Graph Infrastructure

This directory contains utilities and scripts for the documentation integration pipeline that builds a unified
Knowledge Graph from multiple markdown sources.

## Pipeline Orchestration

The `extract-keywords` command orchestrates the complete keyword extraction pipeline from YAML documentation.

### Full Pipeline

```bash
# Run the complete pipeline (all stages)
uv run extract-keywords

# Run with a specific source directory
uv run extract-keywords --source docs/architecture/

# Dry run mode (show changes without modifying files)
uv run extract-keywords --dry-run
```

### Individual Stages

```bash
# Stage 1: Extract candidates using spaCy NLP
uv run extract-keywords --stage extract

# Stage 2: Score candidates with Qwen3-Reranker (optional)
uv run extract-keywords --stage score

# Stage 3: Classification (prints sub-agent instructions)
uv run extract-keywords --stage classify

# Stage 4: Apply kept keywords to YAML files
uv run extract-keywords --stage apply

# Stage 5: Track and resolve keyword variants
uv run extract-keywords --stage variants
```

### Pipeline Workflow

```
                                    +-----------------+
                                    |  YAML Docs      |
                                    |  (docs/*.yml)   |
                                    +--------+--------+
                                             |
                                             v
+------------------------------------------+-------------------------------------------+
|                              Stage 1: Extract Candidates                             |
|                              (candidate_extraction.py)                               |
|  - spaCy NLP (en_core_web_trf) extracts named entities, noun chunks                 |
|  - Regex patterns extract file paths, CamelCase, snake_case identifiers              |
|  - Output: .knowledge/keywords/candidates.csv                                        |
+------------------------------------------+-------------------------------------------+
                                             |
                                             v
+------------------------------------------+-------------------------------------------+
|                              Stage 2: Score (Optional)                               |
|                              (qwen_scoring.py)                                       |
|  - Qwen3-Reranker-8B scores candidate relevance                                      |
|  - Adds qwen_score column (0.0-1.0) to candidates.csv                               |
+------------------------------------------+-------------------------------------------+
                                             |
                                             v
+------------------------------------------+-------------------------------------------+
|                              Stage 3: Classify (Sub-agent)                           |
|                              (keyword-filter sub-agent)                              |
|  - Query: uv run knowledge.query-keyword-candidates --unclassified                   |
|  - Invoke: Task(subagent_type="keyword-filter", prompt="")                          |
|  - Classifies each candidate as keep='true' or keep='false'                         |
+------------------------------------------+-------------------------------------------+
                                             |
                                             v
+------------------------------------------+-------------------------------------------+
|                              Stage 4: Apply Keywords                                 |
|                              (keyword_store.py)                                      |
|  - Reads kept candidates (keep='true')                                              |
|  - Adds keywords: list to YAML elements                                             |
|  - Updates .knowledge/keywords/keywords.csv index                                    |
+------------------------------------------+-------------------------------------------+
                                             |
                                             v
+------------------------------------------+-------------------------------------------+
|                              Stage 5: Variant Resolution                             |
|                                                                                      |
|  5a: Track Variants (variant_resolver.py)                                           |
|      - Qwen3-Embedding-8B computes keyword embeddings                               |
|      - Cosine similarity finds similar pairs (threshold: 0.85)                      |
|      - Output: .knowledge/keywords/variant_candidates.csv                           |
|                                                                                      |
|  5b: Validate Variants (keyword-synonym-reviewer sub-agent)                         |
|      - Query: uv run knowledge.query-variants --unvalidated                         |
|      - Invoke: Task(subagent_type="keyword-synonym-reviewer", prompt="")            |
|      - Decides merge=true/false and canonical form                                  |
|                                                                                      |
|  5c: Apply Variant Decisions (variant_resolver.py)                                  |
|      - Updates keywords.csv with canonical forms                                    |
|      - Updates YAML files to use canonical keywords                                 |
+------------------------------------------+-------------------------------------------+
```

### Sub-agent Integration

Two sub-agents handle stages that require LLM judgment:

| Sub-agent | Stage | Purpose |
|-----------|-------|---------|
| `keyword-filter` | Stage 3 | Classifies candidates as keywords vs noise |
| `keyword-synonym-reviewer` | Stage 5b | Validates variant merges and canonical forms |

Invoke sub-agents via the Task tool:

```python
Task(subagent_type="keyword-filter", prompt="")
Task(subagent_type="keyword-synonym-reviewer", prompt="")
```

### Scoring Configuration

The pipeline supports configurable Qwen model and batch size for Stage 2:

```bash
# Use a smaller model for lower memory usage
uv run extract-keywords --score-model Qwen/Qwen3-Reranker-4B

# Reduce batch size for constrained GPU memory
uv run extract-keywords --score-batch-size 8

# Combine both options
uv run extract-keywords --score-model Qwen/Qwen3-Reranker-4B --score-batch-size 16
```

### Per-Document Mode

The pipeline currently operates in batch mode, processing all YAML files in the source
directory. For single-file processing, use the underlying CLI commands directly:

```bash
# Extract candidates from a single file
uv run knowledge.extract-keyword-candidates --path docs/development/python.yml

# The classification sub-agent works on individual candidates regardless of source
# After classification, apply keywords (operates on all kept candidates)
uv run knowledge.apply-keywords-to-yaml
```

Per-document flows follow the same stages but allow targeted extraction. This is useful
for iterative development or when adding documentation incrementally.

### Underlying CLI Commands

The `extract-keywords` command is the primary umbrella CLI that orchestrates all stages.
For advanced usage, debugging, or finer control, you can invoke the underlying commands
directly:

| Stage | Pipeline Command | Underlying CLI |
|-------|-----------------|----------------|
| 1 | `--stage extract` | `uv run knowledge.extract-keyword-candidates` |
| 2 | `--stage score` | `uv run knowledge.score-candidates-with-qwen` |
| 3 | `--stage classify` | Sub-agent + `uv run knowledge.query-keyword-candidates` |
| 4 | `--stage apply` | `uv run knowledge.apply-keywords-to-yaml` |
| 5a | `--stage variants` | `uv run knowledge.track-keyword-variants` |
| 5c | `--stage variants` | `uv run knowledge.apply-variant-decisions` |

**When to use underlying commands:**

- **Debugging**: Inspect intermediate state or test individual stages
- **Custom options**: Access stage-specific flags not exposed by the pipeline
- **Per-file processing**: Target a specific file instead of batch processing
- **Integration**: Call from external scripts or automation

**Note**: The pipeline command does not replace these underlying commands; it orchestrates
them. Both can be used together as needed.

### Troubleshooting

**Missing CSV files:**
- Run stages in order; each stage depends on the previous
- Ensure `.knowledge/keywords/` directory exists

**spaCy model not found:**
```bash
python -m spacy download en_core_web_trf
```

**Qwen model loading errors:**
- Ensure `transformers` and `torch` are installed
- Check GPU memory for large models (8B parameters)
- Use `--score-batch-size 8` for lower memory usage

**No candidates extracted:**
- Verify YAML files have `id` and `text` fields
- Check source path points to valid YAML documentation

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

## compare_yaml_docs.py

Compares YAML documents by extracting IDs and their associated object data, enabling dict-to-dict comparison across versions.

### FieldFact Extraction API

The module provides structured field-level extraction from sliced YAML elements:

```python
from scripts.knowledge.compare_yaml_docs import (
    extract_field_facts,
    extract_ids_and_text,
    FieldFact,
)

# Parse YAML file
data = parse_yaml_file("docs/development/example.yml")

# Get structured FieldFacts
facts_by_element = extract_field_facts(data, "docs/development/example.yml")

for element_id, facts in facts_by_element.items():
    for fact in facts:
        print(f"{element_id}.{fact.field_path}: {fact.value}")
        print(f"  role={fact.role}, group_key={fact.group_key}")

# For backward compatibility, extract_ids_and_text still works
text_by_element = extract_ids_and_text(data)
```

### FieldFact Structure

Each FieldFact captures:

- **element_id**: ID of the element this fact belongs to
- **field_path**: Full path (e.g., "raises[0].status_code")
- **key**: Last segment (e.g., "status_code")
- **scope_path**: Prefix (e.g., "raises[0]")
- **value**: Leaf value or $ref dict
- **value_kind**: scalar-str, scalar-num, scalar-bool, scalar-null, ref, list-scalar, list-object, object
- **role**: constraint, entity_ref, artifact_root, metadata
- **group_key**: Semantic grouping key (uses discriminators for known patterns)
- **group_id**: SHA-256 hash of group_key

### Role Assignment

1. **entity_ref**: $ref values (value_kind == "ref")
2. **metadata**: Known keys (doc_id, id, version_hint, kind, index, category, domain)
3. **artifact_root**: Placeholder (not yet implemented)
4. **constraint**: Default for other fields

### Constraint Grouping

Default grouping uses scope_path. Known patterns use discriminators:

- `http_method_defaults[*]` → `http_method_defaults::method={method}`
- `sample_code` → `sample_code::language={language}`

### Backward Compatibility

`extract_ids_and_text()` continues to work for existing callers (resolution_tracker.py, candidate_extraction.py) while the FieldFact infrastructure provides structured access for new workflows.

See `docs/plans/fact_redesign.md` lines 143-279 for the complete specification.
