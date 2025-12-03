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

## Artifact Kind Validation

**Command:** `uv run knowledge.validate-artifact-kinds`

**Purpose:** Validate the Artifact Kind Registry (`.knowledge/artifacts/kinds.yml`) to ensure
schema compliance, deterministic structure patterns, and prevent duplicate/overlapping artifact kinds.

**Arguments:**

- `--knowledge-path <path>`: Base knowledge directory (default: `.knowledge`)
- `--strict`: Upgrade warnings to blocking errors
- `--json-report <path>`: Output JSON validation report

**Validation Checks:**

1. **Schema checks (blocking)**: Required fields present, kind_id uniqueness, alias targets exist, render plan references validated
2. **Sample execution (blocking when samples present)**: Loads sample YAML files, extracts FieldFacts using `extract_field_facts`, verifies required fields from structure_pattern exist in element, validates contributor paths from extraction_contract
3. **Determinism checks (blocking)**: root_path syntax validation, sibling_constraint operators, content_sniff regex patterns
4. **Duplicate detection**: Identical patterns (blocking error), near-duplicates using Jaccard similarity (warning at threshold >= 0.8, blocking with `--strict`)

**Exit Codes:**

- 0: Success (or warnings only)
- 1: Blocking errors

**Example Usage:**

```bash
# Validate registry with default settings
uv run knowledge.validate-artifact-kinds

# Strict mode (warnings become errors)
uv run knowledge.validate-artifact-kinds --strict

# Generate JSON report
uv run knowledge.validate-artifact-kinds --json-report validation_report.json
```

**Related Files:**

- Registry: `.knowledge/artifacts/kinds.yml`
- Validation script: `scripts/knowledge/validate_artifact_kinds.py`
- Specification: `docs/plans/fact_redesign.md` lines 341-479

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
3. **artifact_root**: Detected via Artifact Kind Registry using root_path matching, sibling_constraints, and content_sniff patterns
4. **constraint**: Default for other fields

### Constraint Grouping

Default grouping uses scope_path. Known patterns use discriminators:

- `http_method_defaults[*]` → `http_method_defaults::method={method}`
- `sample_code` → `sample_code::language={language}`

### Backward Compatibility

`extract_ids_and_text()` continues to work for existing callers (resolution_tracker.py, candidate_extraction.py) while the FieldFact infrastructure provides structured access for new workflows.

See `docs/plans/fact_redesign.md` lines 143-279 for the complete specification.

## Artifact Detection and Management

The artifact detection system bridges structural FieldFacts and semantic fact extraction
per `docs/plans/fact_redesign.md` lines 282-569.

### Modules

**artifact_manager.py** - CRUD operations for artifact manifests:

- `create_artifact_manifest(artifact, output_dir)`: Create manifest YAML file
- `load_artifact_manifest(artifact_id, artifacts_dir)`: Load manifest from file
- `update_artifact_manifest(artifact_id, updates, artifacts_dir)`: Merge updates
- `list_artifact_manifests(artifacts_dir, filter_v1_only)`: List all manifests
- `delete_artifact_manifest(artifact_id, artifacts_dir)`: Remove manifest file
- `get_manifests_by_source_file(source_file, artifacts_dir)`: Filter by source
- `get_manifests_by_kind(artifact_kind_pattern, artifacts_dir)`: Filter by kind pattern
- `set_validation_result(artifact_id, artifacts_dir, ...)`: Update validation status

### CLI Commands

**detect_artifacts.py** - Detect artifacts from YAML files:

```bash
# Scan directory for artifacts (creates manifests by default)
uv run knowledge.detect-artifacts --source-files 'docs/development/**/*.yml'

# Detection only (no manifest creation)
uv run knowledge.detect-artifacts --source-files docs/**/*.yml --no-create-manifests

# Include non-V1 artifacts (modality != text or extraction_mode != full)
uv run knowledge.detect-artifacts --source-files docs/*.yml --no-v1-only

# Output detected artifacts as JSON
uv run knowledge.detect-artifacts --source-files docs/*.yml --output-format json
```

**query_artifacts.py** - Query artifact manifests:

```bash
# List all artifacts (table format)
uv run knowledge.query-artifacts

# Filter by artifact_kind pattern
uv run knowledge.query-artifacts --artifact-kind 'diagram/*'

# Filter by source file
uv run knowledge.query-artifacts --source-file docs/architecture/event-flow.yml

# Show validation status
uv run knowledge.query-artifacts --show-validation

# Show aggregate statistics
uv run knowledge.query-artifacts --stats

# Output as JSON/YAML/CSV
uv run knowledge.query-artifacts --output-format json
```

### Artifact Lifecycle

Per `docs/plans/fact_redesign.md` lines 561-569, the current implementation covers:

1. **Detect artifact roots** (implemented): `detect_artifacts_from_field_facts()`
2. **Create/update manifests** (implemented): `artifact_manager.create_artifact_manifest()`
3. **Extract semantic facts** (implemented): `artifact_fact_extractor.extract_artifact_facts()`
4. **Render from facts** (implemented): `artifact_renderer.render_artifact()` with LLM rendering
5. **Validate rendered vs source** (implemented): `artifact_validator.validate_artifact()` with embedding-based similarity
6. **Persist validation results** (implemented): `artifact_manager.set_validation_result()`

The full lifecycle can be executed via `artifact_manager.execute_artifact_lifecycle()`.

### V1 Participation Rule

Per `docs/plans/fact_redesign.md` lines 36-42, only artifacts with:

- `modality == "text"`
- `extraction_mode == "full"`

...participate in current extraction/rendering pipelines. Other combinations are
representable but bypassed. Use `--no-v1-only` in CLI commands to include all artifacts.

### Related Files

- Artifact Kind Registry: `.knowledge/artifacts/kinds.yml`
- Artifact manifests: `.knowledge/artifacts/<artifact_id>.yml`
- Rendered artifacts: `.knowledge/artifacts/rendered/<artifact_id>.<ext>`
- Registry validation: `uv run knowledge.validate-artifact-kinds`

See `.knowledge/README.md` "Artifact Manifests" section for schema details.

## Artifact Rendering and Validation

The artifact rendering system implements lifecycle steps 3-5 per `docs/plans/fact_redesign.md`
lines 561-569: extract semantic facts, render artifacts from facts, and validate
rendered vs source.

### Modules

**render_plan_manager.py** - Render plan CRUD operations:

- `load_render_plan(render_plan_id, render_plans_dir)`: Load render plan YAML
- `list_render_plans(render_plans_dir)`: List all render plans
- `get_render_plan_for_artifact_kind(artifact_kind, render_plans_dir)`: Find plan for kind
- `validate_render_plan_schema(plan_dict)`: Validate render plan schema

**artifact_renderer.py** - Artifact rendering logic:

- `render_artifact(manifest, render_plan, artifacts_dir, rendered_dir)`: Main rendering function
- Follows render plan steps: gather contributor facts, normalize terminology, order by
  determinism rules, render with LLM or none engine, self-check
- Returns Path to rendered artifact file

**artifact_validator.py** - Artifact validation:

- `validate_artifact(manifest, rendered_path, source_text, comparator)`: Main validation
- Validation comparators: normalized_text, normalized_rows_by_discriminator,
  structure_and_leaf_text, normalized_diff
- `write_validation_result(result, validations_csv_path)`: Append to CSV
- Returns ValidationResult with similarity_score, passed flag, mismatch_summary

### CLI Commands

**render_artifacts.py** - Render artifacts from facts:

By default, `render_artifacts.py` uses `execute_artifact_lifecycle()` for full lifecycle
orchestration including semantic fact extraction, LLM rendering, and embedding-based
validation. Use `--legacy-mode` to opt into the legacy `_render_manifest()` behavior.

```bash
# Render all V1 artifacts (default: full lifecycle orchestration)
uv run knowledge.render-artifacts

# Render specific artifact
uv run knowledge.render-artifacts --artifact-id abc123

# Render by artifact kind pattern
uv run knowledge.render-artifacts --artifact-kind 'diagram/*'

# Render by source file
uv run knowledge.render-artifacts --source-file docs/architecture/event-flow.yml

# Include non-V1 artifacts
uv run knowledge.render-artifacts --no-v1-only

# Legacy mode: Use _render_manifest() without lifecycle orchestration
uv run knowledge.render-artifacts --legacy-mode

# Legacy mode with validation
uv run knowledge.render-artifacts --legacy-mode --validate
```

**query_validations.py** - Query validation results:

```bash
# List all validation results
uv run knowledge.query-validations

# Filter by artifact_id
uv run knowledge.query-validations --artifact-id abc123

# Filter by passed status
uv run knowledge.query-validations --passed false

# Filter by minimum similarity
uv run knowledge.query-validations --min-similarity 0.9

# Show aggregate statistics
uv run knowledge.query-validations --stats

# Output as JSON/YAML/CSV
uv run knowledge.query-validations --output-format json
```

### Render Plan Storage

Render plans are stored in `.knowledge/artifacts/render_plans/` as YAML files. Initial plans:

1. **prose.paragraph.v1**: Prose paragraph rendering
2. **table.discriminator-grouped.v1**: Discriminator-grouped table rendering
3. **prose.code-block.v1**: Prose + code block rendering
4. **schema.nested-hierarchy.v1**: Nested YAML hierarchy rendering
5. **diagram.mermaid.sequence.v1**: Mermaid diagram tracking (render_engine=none)

### Validation Results Storage

Validation results are stored in `.knowledge/artifacts/validations.csv` with columns:
validation_id, artifact_id, source_file, source_element_id, field_path, render_plan_id,
projection_version, source_hash, rendered_hash, similarity_score, passed, mismatch_summary,
validated_at.

### Rendered Artifacts Storage

Rendered artifacts are stored in `.knowledge/artifacts/rendered/<artifact_id>.<ext>` where
extension is determined by artifact_format (.md, .yml, .json, .mmd, .txt).

### Current Implementation Status

- **Implemented**: Render plan loading, artifact rendering infrastructure, validation
  comparators, CLI commands, LLM rendering via Claude CLI, terminology normalization via
  variant system, embedding-based semantic similarity via Qwen3, semantic fact extraction
  (Hunter/Surgeon/Auditor pipeline), full artifact lifecycle orchestration
- **Deferred to Task 9**: Entity resolution (correctly deferred per fact_redesign_plan.md)

### Related Files

- Render plans: `.knowledge/artifacts/render_plans/*.yml`
- Rendered artifacts: `.knowledge/artifacts/rendered/<artifact_id>.<ext>`
- Validation results: `.knowledge/artifacts/validations.csv`
- Artifact manifests: `.knowledge/artifacts/<artifact_id>.yml`

See `.knowledge/README.md` "Render Plans" and "Artifact Validation" sections for schema details.

## Fact Store Module

The `fact_store.py` module handles both structural FieldFacts and semantic facts with
multi-domain tagging, JSONL export, and relationship edge tracking.

### Two-Layer Fact Model

Per `docs/plans/fact_redesign.md` lines 1565-1613:

- **Structural facts**: Derived mechanically from YAML structure via FieldFacts. Form the base
  provenance layer for hashing, candidate extraction, and artifact manifests.
- **Semantic facts**: Derived from artifact blobs via fact_extraction.py. Additive layer that
  does not replace structural facts.

### Key Functions

| Function | Description |
|----------|-------------|
| `store_structural_facts()` | Store FieldFacts to domain/pattern YAML |
| `export_facts_to_jsonl()` | Export unified JSONL with domain arrays and edges |
| `query_structural_facts()` | Query structural facts with filters |
| `containment_edges_to_edge_records()` | Convert ContainmentEdge to EdgeRecord |
| `entity_ref_fieldfacts_to_edge_records()` | Extract entity reference edges |
| `determine_primary_domain()` | Get primary domain for filename |
| `fieldfact_to_structural_record()` | Convert FieldFact to storage record |

### TypedDicts

- `StructuralFactRecord`: Storage format for structural facts
- `EdgeRecord`: Relationship edge for JSONL export (containment/entity_ref)
- `FactStoreRecord`: Updated with optional `domains` field for multi-domain tagging

## Structural Fact Workflow

### Step 1: Extract FieldFacts from YAML

```python
from scripts.knowledge.compare_yaml_docs import extract_field_facts, parse_yaml_file

data = parse_yaml_file("docs/development/example.yml")
facts_by_element = extract_field_facts(data, "docs/development/example.yml")
```

### Step 2: Determine Domains

Determine appropriate domains based on content classification per
`docs/development/domain-definitions.yml`:

```python
# Pure REST protocol
domains = ["rest"]

# FastAPI implementation of REST
domains = ["rest", "fastapi"]

# Python async patterns in FastAPI
domains = ["python", "fastapi"]
```

### Step 3: Store Structural Facts

```python
from scripts.knowledge.fact_store import store_structural_facts

# Flatten FieldFacts to list
all_facts = []
for element_facts in facts_by_element.values():
    all_facts.extend(element_facts)

# Store to domain/pattern YAML
success, total = store_structural_facts(
    all_facts,
    domains=["rest", "fastapi"],
    pattern="api",
    knowledge_path=Path(".knowledge")
)
# Creates: .knowledge/facts/rest.api.facts.yml (uses first domain as primary)
```

### Step 4: Query Structural Facts

```python
from scripts.knowledge.fact_store import query_structural_facts

# Query by domain/pattern
facts = query_structural_facts(
    facts_dir=Path(".knowledge/facts"),
    domain="rest",
    pattern="api"
)

# Query by element_id
facts = query_structural_facts(facts_dir, element_id="elem-1")

# Query by role
facts = query_structural_facts(facts_dir, role="constraint")
```

## JSONL Export Workflow

### Export Function

```python
from scripts.knowledge.fact_store import export_facts_to_jsonl

# Export with edges
output_path = export_facts_to_jsonl(
    knowledge_path=Path(".knowledge"),
    include_edges=True
)
# Creates: .knowledge/facts/facts.jsonl

# Export without edges
output_path = export_facts_to_jsonl(
    knowledge_path=Path(".knowledge"),
    include_edges=False
)

# Custom output path
output_path = export_facts_to_jsonl(
    knowledge_path=Path(".knowledge"),
    output_path=Path("custom/facts.jsonl")
)
```

### JSONL Record Fields

**Fact records** (`record_type: "fact"`):
- `fact_id`: UUID
- `fact_type`: "semantic" or "structural"
- `domains`: Array of domain tags (supports multi-domain)
- `pattern`: Pattern name
- `source_file`, `source_element_id`: Provenance
- For semantic: `fact_text`, `entity`, `confidence`, `source_field_path`, `provenance`
- For structural: `element_id`, `field_path`, `value`, `role`, etc.

**Edge records** (`record_type: "edge"`):
- `edge_id`: UUID
- `edge_type`: "containment" or "entity_ref"
- `source_id`, `target_id`: Element IDs
- `metadata`: Additional context (field_path, key)

### Parsing JSONL

```python
import json

with open(".knowledge/facts/facts.jsonl") as f:
    for line in f:
        record = json.loads(line)
        if record["record_type"] == "fact":
            if record["fact_type"] == "structural":
                print(f"Structural: {record['element_id']}.{record['field_path']}")
            else:
                print(f"Semantic: {record['entity']}: {record['fact_text']}")
        elif record["record_type"] == "edge":
            print(f"Edge: {record['source_id']} -> {record['target_id']}")
```

## CLI Commands

### Store Structural Facts

```bash
# Store FieldFacts from YAML to structural facts
uv run knowledge.store-structural-facts \
  --yaml-file docs/development/general/general.rest.api-patterns.yml \
  --domains rest fastapi \
  --pattern api

# With custom knowledge path
uv run knowledge.store-structural-facts \
  --yaml-file example.yml \
  --domains python \
  --pattern patterns \
  --knowledge-path .knowledge
```

### Export Facts to JSONL

```bash
# Export all facts with edges
uv run knowledge.export-facts-jsonl --include-edges

# Export without edges
uv run knowledge.export-facts-jsonl --no-edges

# Custom output path
uv run knowledge.export-facts-jsonl --output custom/output.jsonl

# Custom knowledge path
uv run knowledge.export-facts-jsonl --knowledge-path .knowledge
```

## Multi-Domain Tagging

### Domain Selection Guidelines

Per `docs/development/domain-definitions.yml`:

| Content Type | Domains |
|--------------|---------|
| Pure REST protocol patterns | `["rest"]` |
| FastAPI-specific patterns | `["fastapi"]` |
| REST patterns in FastAPI | `["rest", "fastapi"]` |
| Python async patterns | `["python"]` |
| Python async in FastAPI | `["python", "fastapi"]` |
| SurrealDB patterns | `["surrealdb"]` |
| Elasticsearch patterns | `["elasticsearch"]` |

### Primary Domain Rule

- Primary domain = first domain in array
- Used for filename: `<primary_domain>.<pattern>.facts.yml`
- If len == 1: use that domain
- If len > 1: use first domain (not "mixed" for storage)

## Edge List Export

### Edge Types

1. **containment**: Parent→child relationships from `ContainmentEdge`
   - Generated during YAML comparison (`compare_yaml_docs.py`)
   - Stored in `.knowledge/graph/containment_edges.csv`
   - Exported from CSV if exists

2. **entity_ref**: Entity reference edges from FieldFacts
   - Generated from structural facts with `role=="entity_ref"`
   - Target extracted from `$ref` value

### Edge Conversion Functions

```python
from scripts.knowledge.fact_store import (
    containment_edges_to_edge_records,
    entity_ref_fieldfacts_to_edge_records,
)

# Convert containment edges
from scripts.knowledge.compare_yaml_docs import ContainmentEdge

edges = [
    ContainmentEdge(
        parent_id="parent-1",
        child_id="child-1",
        field_path="items[0]",
        source_file="test.yml"
    )
]
edge_records = containment_edges_to_edge_records(edges)

# Convert entity refs from FieldFacts
field_facts = [...]  # FieldFacts with role=="entity_ref"
edge_records = entity_ref_fieldfacts_to_edge_records(field_facts)
```

## Integration Points

### compare_yaml_docs.py

- `extract_field_facts()`: Extracts FieldFact instances from YAML
- `ContainmentEdge`: Dataclass for parent-child relationships
- `FieldFact`: Dataclass for structural field facts

### artifact_manager.py

- Uses structural facts for artifact manifest contributors
- Links artifacts to source via `source_file`, `source_element_id`, `field_path`

### artifact_fact_extractor.py

- Extracts semantic facts from artifact blobs
- Links back to structural layer via provenance fields

### Data Flow

```
YAML → FieldFacts → structural facts → artifact detection → semantic extraction → unified JSONL
                  ↓
            ContainmentEdges → containment_edges.csv → edge list
```

## Testing

Tests are in `scripts/tests/knowledge/test_fact_store.py`:

- `TestDeterminePrimaryDomain`: Primary domain selection
- `TestFieldfactToStructuralRecord`: FieldFact conversion
- `TestStoreStructuralFacts`: Structural fact storage
- `TestContainmentEdgesToEdgeRecords`: Containment edge conversion
- `TestEntityRefFieldfactsToEdgeRecords`: Entity ref edge extraction
- `TestQueryStructuralFacts`: Structural fact queries
- `TestExportFactsToJsonl`: JSONL export
- `TestIntegrationStructuralAndSemanticFacts`: End-to-end workflow

Tests use `tmp_path` fixture for filesystem isolation.
