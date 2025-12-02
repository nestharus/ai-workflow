# Knowledge Directory

This directory stores migration artifacts, comparison results, and resolution tracking
for documentation migrations.

## Directory Structure

```text
.knowledge/
├── originals/      # Timestamped copies of original files referenced by comparison
│                   # and validation commands (referenced in tasks.csv via original_file_ref)
├── migrations/     # Migration task metadata (tasks.csv)
├── comparisons/    # Flattened CSV comparison results (replacing JSON .compare files)
├── resolutions/    # Hash-based resolution tracking (resolved.csv)
├── movements/      # Information movement tracking (records where content moved from/to)
│   ├── movements.csv           # File-level movements during migrations
│   └── iterative_movements.csv # Iterative sentence-level fact movements
├── additions/      # Addition tracking (new IDs in target files not in originals)
├── reports/        # Generated YML review reports for non-identical text comparisons
├── keywords/       # Keyword extraction pipeline data (candidates, keywords, variants)
│   ├── candidates.csv         # Extracted keyword candidates from NLP processing
│   ├── keywords.csv           # Classified and promoted keywords
│   └── variant_candidates.csv # Keyword variant tracking via embeddings
├── facts/          # Fact extraction data
│   └── extractions.csv        # Extracted atomic facts about entities/keywords
└── README.md       # This file
```

## CSV Schemas

### resolutions/resolved.csv

Tracks resolved documentation sections using content hashes and file paths.
Duplicate detection is based on (id, source_file, split_file) for path-level uniqueness.

| Column | Type | Description |
|--------|------|-------------|
| resolution_id | string | Unique identifier for this resolution record (UUID) |
| id | string | YAML element identifier being resolved |
| source_file | string | Relative path to the source YAML file |
| split_file | string | Relative path to the split YAML file |
| original_text_hash | string | SHA-256 hash of original text content |
| split_text_hash | string | SHA-256 hash of split text content |
| source_file_hash | string | SHA-256 hash of source file at resolution time |
| split_file_hash | string | SHA-256 hash of split file at resolution time |
| resolved_at | string | ISO 8601 basic format timestamp (YYYYMMDDTHHMMSSZ) |

### comparisons/*.csv

Flattened comparison results (one file per pattern, e.g., `api-patterns.csv`).

**Note**: Comparison CSVs are regenerated on each run of `uv run knowledge.compare-yml-docs`.
Older data is intentionally discarded to ensure the CSV always reflects the current
state of the YAML files being compared.

| Column | Type | Description |
|--------|------|-------------|
| source_file | string | Path to the source file (original, split, or orphan depending on origin_type) |
| id | string | Section identifier from the source file |
| origin_type | string | Type classification: "original", "split_only", or "orphan" |
| original_text | string | Text content from source_file (see semantics below) |
| split_file | string | Path to the split target file (empty for split_only/orphan entries) |
| split_text | string | Text content in split file (empty for split_only/orphan entries) |

**`original_text` column semantics by `origin_type`**:

- `original`: Text from the original file that differs from or is missing in splits
- `split_only`: Text from a split file for an ID not found in the corresponding original
- `orphan`: Text from a file in a subdirectory with no corresponding original file

For `split_only` and `orphan` entries, `original_text` contains the source text from the
split/orphan file respectively, not from an original file. Query authors should filter by
`origin_type` when the distinction matters.

### migrations/tasks.csv

Migration task metadata for tracking progress.

| Column | Type | Description |
|--------|------|-------------|
| task_id | string | Unique task identifier (UUID) |
| original_file_ref | string | Reference to file in originals/ |
| pattern_name | string | Pattern being migrated (e.g., "api-patterns") |
| status | string | Task status (pending, in_progress, completed, failed) |
| created_at | string | ISO 8601 timestamp of task creation |
| validated_at | string | ISO 8601 timestamp of validation (nullable) |

### movements/movements.csv

Tracks information movements between files during migrations, recording source/target locations, reasons, coverage descriptions, and before/after sentence context for validation.

| Column | Type | Description |
|--------|------|-------------|
| movement_id | string | Unique identifier for this movement record (UUID) |
| element_id | string | YAML element identifier being moved (links to comparisons/resolutions) |
| source_file | string | Relative path to the source file where information originated |
| target_file | string | Relative path to the target file where information was moved |
| reason | string | Explanation of why the information was moved |
| coverage_description | string | Description of what information is being covered/moved |
| before_sentence | string | Original sentence in source file before the move |
| after_sentence_source | string | Sentence in source file after information was removed |
| target_before_sentence | string | Sentence in target file before information was added |
| target_after_sentence | string | Sentence in target file after information was added |
| moved_at | string | ISO 8601 basic format timestamp (YYYYMMDDTHHMMSSZ, UTC) |

**Note**: Movement records link to resolution records via `element_id` to track the complete lifecycle of information changes.

### movements/iterative_movements.csv

Tracks iterative sentence-level fact movements during fact extraction. Each record represents one iteration of fact isolation, linking to the originating fact record via fact_id.

| Column | Type | Description |
|--------|------|-------------|
| iteration_id | string | Unique identifier for this iteration record (UUID) |
| fact_id | string | Links to fact record in facts/extractions.csv |
| source_sentence | string | Sentence before this fact extraction |
| isolated_fact | string | The atomic fact extracted in this iteration |
| residual_sentence | string | Sentence after this fact was removed |
| similarity_score | string | Cosine similarity between source and (fact + residual), 0.0-1.0 |
| reason | string | Explanation for this movement (typically "Fact extraction") |
| moved_at | string | ISO 8601 basic format timestamp (YYYYMMDDTHHMMSSZ, UTC) |

**Note**: Similarity scores are computed using Qwen embeddings. Scores >= 0.95 indicate successful information preservation.

### additions/additions.csv

Tracks new IDs/content appearing in target files that were not present in original files, enabling validation that additions are intentional, in-scope, and meaningful.

| Column | Type | Description |
|--------|------|-------------|
| addition_id | string | Unique identifier for this addition record (UUID) |
| element_id | string | YAML element identifier found in target file (links to comparisons) |
| target_file | string | Relative path to the target file where new content was added |
| added_text | string | Text content of the added element |
| detected_at | string | ISO 8601 basic format timestamp (YYYYMMDDTHHMMSSZ, UTC) when addition was detected |
| validated | string | Whether addition has been reviewed ("true" or "false") |
| in_scope | string | Whether addition is within project scope ("true" or "false") |
| meaningful | string | Whether addition provides meaningful value ("true" or "false") |

**Note**: Additions are detected by querying comparison CSVs for `origin_type='split_only'` entries. Duplicate detection is based on `(element_id, target_file)` pairs.

### reports/<pattern>-review.yml

Stores generated YAML review reports for migration items requiring human review due to non-identical text comparisons.

**Structure**: Each report contains:
- `pattern`: Pattern name (e.g., "api-patterns")
- `generated_at`: ISO 8601 timestamp of report generation
- `total_items`: Count of items requiring review
- `items`: Array of review items with:
  - `element_id`: YAML element identifier
  - `source_file`: Path to source file
  - `source_text`: Text from source
  - `split_file`: Path to target file
  - `target_text`: Text from target
  - `text_similarity_score`: Similarity score (0.0-1.0)
  - `requires_review`: Boolean flag indicating review needed
  - `origin_type`: Origin type (always 'original' for reports)

**Note**: Reports are regenerated on each run and excluded from git tracking. Reports exclude items already marked as resolved, items with identical text (similarity score = 1.0), and items with origin_type 'split_only' or 'orphan'.

### keywords/candidates.csv

Stores keyword candidates extracted from YAML documentation using spaCy NLP processing. Candidates include noun phrases, named entities, and technical terms identified through part-of-speech tagging.

| Column | Type | Description |
|--------|------|-------------|
| candidate_id | string | Unique identifier for this candidate (UUID) |
| term | string | The extracted term or phrase |
| source_file | string | Relative path to the source YAML file |
| source_element_id | string | YAML element ID where term was found |
| extraction_method | string | Method used (noun_phrase, named_entity, technical_term) |
| pos_tags | string | Part-of-speech tags for the term |
| confidence_score | string | Extraction confidence (0.0-1.0) |
| extracted_at | string | ISO 8601 basic format timestamp (YYYYMMDDTHHMMSSZ) |

**Note**: Duplicate detection is based on `(term, source_file)` pairs to avoid re-extracting the same term from the same source.

### keywords/keywords.csv

Stores classified keywords that have been promoted from candidates. Keywords are assigned categories and subcategories for organization.

| Column | Type | Description |
|--------|------|-------------|
| keyword_id | string | Unique identifier for this keyword (UUID) |
| term | string | The canonical keyword term |
| category | string | Primary category (domain, pattern, concept, entity) |
| subcategory | string | Subcategory within primary category |
| source_candidate_id | string | Original candidate ID this was promoted from |
| source_file | string | Original source file where term was found |
| classified_at | string | ISO 8601 basic format timestamp (YYYYMMDDTHHMMSSZ) |
| classification_notes | string | Optional notes about classification |

**Note**: Keywords represent the canonical, validated terms extracted from documentation.

### keywords/variant_candidates.csv

Tracks keyword variants (synonyms, abbreviations, alternate spellings) identified using embedding similarity from Qwen models.

| Column | Type | Description |
|--------|------|-------------|
| variant_id | string | Unique identifier for this variant (UUID) |
| keyword_id | string | ID of the canonical keyword this is a variant of |
| variant_term | string | The variant term |
| similarity_score | string | Embedding similarity score (0.0-1.0) |
| source_file | string | File where variant was found |
| detected_at | string | ISO 8601 basic format timestamp (YYYYMMDDTHHMMSSZ) |
| validated | string | Whether variant has been validated ("true" or "false") |
| is_canonical | string | Whether this is the canonical form ("true" or "false") |

**Note**: Variants link to keywords via `keyword_id` and can be validated to confirm they are true synonyms or alternate forms.

### facts/extractions.csv

Stores extracted atomic facts about entities/keywords from sentences. Facts are extracted iteratively, with the sentence rewritten after each extraction until no facts about the target entity remain.

| Column | Type | Description |
|--------|------|-------------|
| fact_id | string | Unique identifier for this fact extraction record (UUID) |
| source_sentence | string | Original sentence before any extraction |
| entity | string | Entity/keyword being extracted |
| fact_text | string | Extracted atomic fact about the entity |
| rewritten_sentence | string | Sentence after this fact was removed |
| iteration | string | Iteration number (1-indexed) |
| confidence | string | Confidence score (0.0-1.0) |
| extracted_at | string | ISO 8601 basic format timestamp (YYYYMMDDTHHMMSSZ) |

**Note**: Facts are extracted using the logic puzzle approach where `original_sentence = fact1 + fact2 + ... + residual_sentence`. Semantic similarity validation ensures no information is lost during extraction.

## Hash Algorithm

All hash fields use **SHA-256** for content hashing.

## Timestamp Format

All timestamps use **ISO 8601** format: `YYYY-MM-DDTHH:MM:SS`

## DuckDB Queries

These CSV files are designed for efficient querying via DuckDB. Example:

```sql
SELECT * FROM read_csv_auto('.knowledge/resolutions/resolved.csv')
WHERE resolved_at > '2025-01-01';
```

```sql
-- Query all movements for a specific element
SELECT * FROM read_csv_auto('.knowledge/movements/movements.csv')
WHERE element_id = 'api_patterns.authentication.jwt_validation';

-- Find movements by source file
SELECT * FROM read_csv_auto('.knowledge/movements/movements.csv')
WHERE source_file = 'docs/development/original.api-patterns.yml';

-- Join movements with resolutions to see complete migration history
SELECT
  m.element_id,
  m.source_file,
  m.target_file,
  m.reason,
  r.resolution_id,
  r.resolved_at
FROM read_csv_auto('.knowledge/movements/movements.csv') m
LEFT JOIN read_csv_auto('.knowledge/resolutions/resolved.csv') r
  ON m.element_id = r.id
  AND m.source_file = r.source_file
  AND m.target_file = r.split_file;

-- Find movements with text modifications (where before != after)
SELECT * FROM read_csv_auto('.knowledge/movements/movements.csv')
WHERE before_sentence != target_after_sentence;

-- Query all unvalidated additions
SELECT * FROM read_csv_auto('.knowledge/additions/additions.csv')
WHERE validated = 'false';

-- Find additions by target file
SELECT * FROM read_csv_auto('.knowledge/additions/additions.csv')
WHERE target_file = 'docs/development/python/api-patterns.yml';

-- Join additions with comparisons to see full context
SELECT
  a.addition_id,
  a.element_id,
  a.target_file,
  a.validated,
  a.in_scope,
  a.meaningful,
  c.origin_type,
  c.original_text
FROM read_csv_auto('.knowledge/additions/additions.csv') a
LEFT JOIN read_csv_auto('.knowledge/comparisons/*.csv') c
  ON a.element_id = c.id
  AND a.target_file = c.source_file
WHERE c.origin_type = 'split_only';

-- Find additions that need review (not validated or not in-scope)
SELECT * FROM read_csv_auto('.knowledge/additions/additions.csv')
WHERE validated = 'false' OR in_scope = 'false' OR meaningful = 'false';

-- Find all generated review reports
SELECT * FROM glob('.knowledge/reports/*-review.yml');

-- Note: Review reports are YAML files; use yaml library in Python for programmatic access
-- Example Python usage:
-- import yaml
-- with open('.knowledge/reports/api-patterns-review.yml') as f:
--     report = yaml.safe_load(f)
--     for item in report['items']:
--         if item['text_similarity_score'] < 0.8:
--             print(f"Low similarity: {item['element_id']}")

-- Query all keyword candidates
SELECT * FROM read_csv_auto('.knowledge/keywords/candidates.csv')
ORDER BY extracted_at DESC;

-- Find candidates by extraction method
SELECT * FROM read_csv_auto('.knowledge/keywords/candidates.csv')
WHERE extraction_method = 'noun_phrase';

-- Find high-confidence candidates
SELECT * FROM read_csv_auto('.knowledge/keywords/candidates.csv')
WHERE CAST(confidence_score AS DOUBLE) >= 0.8;

-- Query all classified keywords
SELECT * FROM read_csv_auto('.knowledge/keywords/keywords.csv')
ORDER BY category, subcategory, term;

-- Find keywords by category
SELECT * FROM read_csv_auto('.knowledge/keywords/keywords.csv')
WHERE category = 'domain';

-- Query keyword variants
SELECT * FROM read_csv_auto('.knowledge/keywords/variant_candidates.csv')
WHERE validated = 'true';

-- Find variants for a specific keyword
SELECT * FROM read_csv_auto('.knowledge/keywords/variant_candidates.csv')
WHERE keyword_id = '<keyword-uuid>';

-- Join keywords with their variants
SELECT
  k.keyword_id,
  k.term AS canonical_term,
  k.category,
  v.variant_term,
  v.similarity_score,
  v.validated
FROM read_csv_auto('.knowledge/keywords/keywords.csv') k
LEFT JOIN read_csv_auto('.knowledge/keywords/variant_candidates.csv') v
  ON k.keyword_id = v.keyword_id
ORDER BY k.term, v.similarity_score DESC;

-- Find unvalidated variants with high similarity
SELECT * FROM read_csv_auto('.knowledge/keywords/variant_candidates.csv')
WHERE validated = 'false'
  AND CAST(similarity_score AS DOUBLE) >= 0.9;

-- Query all extracted facts
SELECT * FROM read_csv_auto('.knowledge/facts/extractions.csv')
ORDER BY extracted_at DESC, iteration;

-- Get all facts about a specific entity
SELECT fact_text, confidence, iteration
FROM read_csv_auto('.knowledge/facts/extractions.csv', ALL_VARCHAR=TRUE)
WHERE entity = 'create_app'
ORDER BY iteration;

-- Get facts with high confidence
SELECT entity, fact_text, confidence
FROM read_csv_auto('.knowledge/facts/extractions.csv', ALL_VARCHAR=TRUE)
WHERE CAST(confidence AS DOUBLE) >= 0.95;

-- Get extraction chains (all facts from same source sentence)
SELECT source_sentence, entity, fact_text, iteration
FROM read_csv_auto('.knowledge/facts/extractions.csv', ALL_VARCHAR=TRUE)
WHERE source_sentence LIKE '%create_app%'
ORDER BY source_sentence, iteration;

-- Find entities with multiple facts extracted
SELECT entity, COUNT(*) as fact_count
FROM read_csv_auto('.knowledge/facts/extractions.csv', ALL_VARCHAR=TRUE)
GROUP BY entity
HAVING COUNT(*) > 1
ORDER BY fact_count DESC;

-- Query all iterative movements
SELECT * FROM read_csv_auto('.knowledge/movements/iterative_movements.csv', ALL_VARCHAR=TRUE)
ORDER BY moved_at DESC;

-- Get all movements for a specific entity
SELECT iteration_id, fact_id, isolated_fact, similarity_score
FROM read_csv_auto('.knowledge/movements/iterative_movements.csv', ALL_VARCHAR=TRUE)
WHERE source_sentence LIKE '%create_app%'
ORDER BY moved_at;

-- Get movements for a specific fact
SELECT * FROM read_csv_auto('.knowledge/movements/iterative_movements.csv', ALL_VARCHAR=TRUE)
WHERE fact_id = '<fact-uuid>';

-- Find movements with low similarity (potential information loss)
SELECT iteration_id, fact_id, isolated_fact, similarity_score
FROM read_csv_auto('.knowledge/movements/iterative_movements.csv', ALL_VARCHAR=TRUE)
WHERE CAST(similarity_score AS DOUBLE) < 0.95;

-- Join iterative movements with fact extractions
SELECT
  m.iteration_id,
  m.isolated_fact,
  m.similarity_score,
  f.entity,
  f.confidence,
  f.extracted_at
FROM read_csv_auto('.knowledge/movements/iterative_movements.csv', ALL_VARCHAR=TRUE) m
LEFT JOIN read_csv_auto('.knowledge/facts/extractions.csv', ALL_VARCHAR=TRUE) f
  ON m.fact_id = f.fact_id
ORDER BY f.extracted_at, CAST(f.iteration AS INTEGER);

-- Validate logic puzzle: original = facts + residual
SELECT
  source_sentence,
  STRING_AGG(isolated_fact, ' ') AS all_facts,
  MAX(residual_sentence) AS final_residual,
  AVG(CAST(similarity_score AS DOUBLE)) AS avg_similarity
FROM read_csv_auto('.knowledge/movements/iterative_movements.csv', ALL_VARCHAR=TRUE)
GROUP BY source_sentence;
```

## Addition Tracking Workflow

The addition tracking system identifies and validates new content (IDs) that appear in target files but weren't present in original files.

### Detecting Additions

```bash
# Track all additions across all patterns
uv run knowledge.track-additions

# Track additions for a specific pattern
uv run knowledge.track-additions --pattern api-patterns
```

### Validating Additions

```bash
# Mark an addition as validated, in-scope, and meaningful
uv run knowledge.validate-addition --id <addition_id> --validated --in-scope --meaningful

# Mark only as validated (leave in-scope/meaningful unchanged)
uv run knowledge.validate-addition --id <addition_id> --validated
```

### Querying Additions

Use DuckDB to query addition records (see DuckDB Queries section for examples).

## YML Report Generation Workflow

The report generation system creates YAML review reports for migration items that require human review due to non-identical text comparisons.

### Generating Reports

```bash
# Generate reports for all patterns
uv run knowledge.generate-migration-report

# Generate report for a specific pattern
uv run knowledge.generate-migration-report --pattern api-patterns
```

### Report Structure

Each generated report (`.knowledge/reports/<pattern>-review.yml`) contains:
- `pattern`: Pattern name
- `generated_at`: ISO 8601 timestamp
- `total_items`: Count of items requiring review
- `items`: Array of review items with:
  - `element_id`: YAML element identifier
  - `source_file`: Path to source file
  - `source_text`: Text from source
  - `split_file`: Path to target file
  - `target_text`: Text from target
  - `text_similarity_score`: Similarity score (0.0-1.0)
  - `requires_review`: Boolean flag
  - `origin_type`: Origin type (always 'original' for reports)

### Filtering Logic

Reports exclude:
- Items already marked as resolved
- Items with identical text (similarity score = 1.0)
- Items with origin_type 'split_only' or 'orphan'

## Keyword Extraction Workflow

The keyword extraction system extracts, classifies, and tracks terminology from YAML documentation using spaCy NLP and Qwen embeddings.

### Extracting Candidates

```bash
# Extract candidates from all YAML docs
uv run knowledge.extract-keyword-candidates

# Extract from specific directory
uv run knowledge.extract-keyword-candidates --source docs/architecture/

# Query extracted candidates
uv run knowledge.query-keyword-candidates --method noun_phrase --min-confidence 0.8
```

### Classifying Keywords

```bash
# Classify a candidate
uv run knowledge.classify-keyword --id <candidate_id> --category domain --subcategory fastapi

# Reject a candidate
uv run knowledge.classify-keyword --id <candidate_id> --reject --reason "too generic"
```

### Scoring with Qwen (Optional)

```bash
# Score unscored candidates with Qwen embeddings
uv run knowledge.score-candidates-with-qwen

# Use specific model
uv run knowledge.score-candidates-with-qwen --model Qwen/Qwen3-Embedding-0.6B
```

### Tracking Variants

```bash
# Track variants for all keywords
uv run knowledge.track-keyword-variants

# Track with custom threshold
uv run knowledge.track-keyword-variants --threshold 0.9

# Query variants
uv run knowledge.query-variants --validated --min-similarity 0.85

# Validate a variant
uv run knowledge.validate-variant --id <variant_id> --accept
```

### Running Full Pipeline

```bash
# Run complete extraction pipeline
uv run knowledge.extract-keywords

# Run specific stage
uv run knowledge.extract-keywords --stage extract
uv run knowledge.extract-keywords --stage classify
```

## Fact Extraction

Iterative extraction of atomic facts about entities from sentences.

### CLI Usage

```bash
# Extract facts about an entity from a sentence
uv run knowledge.extract-facts \
  --sentence "Mount all versioned endpoints under /api/{version} using create_app in app/core/factory.py." \
  --entity "create_app"

# Dry run (show facts without storing)
uv run knowledge.extract-facts --sentence "..." --entity "FastAPI" --dry-run

# Specify custom knowledge path
uv run knowledge.extract-facts --sentence "..." --entity "FastAPI" --knowledge-path .knowledge
```

### Workflow

```
CLI → claude(fact-extractor, haiku) → JSON → validate(Qwen) → CSV
```

1. CLI generates structured prompt for fact-extractor sub-agent
2. CLI invokes `claude --agent fact-extractor --model haiku --prompt ...`
3. Sub-agent iteratively extracts facts, outputs JSON
4. CLI validates with Qwen embeddings (similarity >= 0.95)
5. CLI stores results to `facts/extractions.csv`

### Schema (`facts/extractions.csv`)

| Column | Description |
|--------|-------------|
| fact_id | UUID |
| source_sentence | Original sentence |
| entity | Target entity |
| fact_text | Extracted atomic fact |
| rewritten_sentence | Sentence after fact removal |
| iteration | 1, 2, 3, ... |
| confidence | 0.0-1.0 |
| extracted_at | Timestamp |

### Queries

```sql
-- Facts for an entity
SELECT fact_text, confidence, iteration
FROM read_csv_auto('.knowledge/facts/extractions.csv', ALL_VARCHAR=TRUE)
WHERE entity = 'FastAPI'
ORDER BY iteration;

-- High-confidence facts
SELECT entity, fact_text, confidence
FROM read_csv_auto('.knowledge/facts/extractions.csv', ALL_VARCHAR=TRUE)
WHERE CAST(confidence AS DOUBLE) >= 0.95;
```

### Logic Puzzle Approach

```
original_sentence = fact1 + fact2 + ... + residual_sentence
```

- Each iteration extracts exactly ONE atomic fact
- Facts validated using Qwen embeddings (similarity >= 0.95)
- Extraction continues until entity is absent from residual

### Extraction Modes

**Sub-agent mode**: Uses `fact-extractor` Claude sub-agent (haiku model for cost-efficiency) for comprehensive extraction with pattern matching. After sub-agent returns results, CLI re-validates using Qwen embeddings.

**Inline mode (fallback)**: When sub-agent unavailable, uses best-effort heuristics with Qwen embeddings for validation. May not fully extract all entity facts. Check `extraction_complete` field.

Both modes use Qwen embeddings (loaded lazily after extraction) to validate semantic similarity >= 0.95.

### Exit Codes

- `0`: Success - extraction complete
- `1`: Error - CLI or model failure
- `2`: Partial success - facts extracted but entity still present in residual

### Future Enhancements

- `--input-file`: Batch processing from YAML/JSONL file (not yet implemented)

## Fact Isolation Workflow

Orchestrates fact extraction with validation and writes isolation records to CSV.

### CLI Usage

```bash
# Isolate facts about an entity from a sentence
uv run knowledge.isolate-entity-facts \
  --sentence "Mount all versioned endpoints under /api/{version} using create_app in app/core/factory.py." \
  --entity "create_app"

# Dry run (show report without storing)
uv run knowledge.isolate-entity-facts --sentence "..." --entity "FastAPI" --dry-run

# Specify custom knowledge path
uv run knowledge.isolate-entity-facts --sentence "..." --entity "FastAPI" --knowledge-path .knowledge

# Specify custom output CSV for isolation records
uv run knowledge.isolate-entity-facts --sentence "..." --entity "FastAPI" --output custom/isolation.csv
```

### CLI Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--sentence` | Yes | - | The sentence to extract facts from |
| `--entity` | Yes | - | The entity/keyword to extract facts about |
| `--knowledge-path` | No | `.knowledge` | Base knowledge directory |
| `--dry-run` | No | `False` | Show report without storing to CSV |
| `--model` | No | `Qwen/Qwen3-Embedding-0.6B` | HuggingFace model for embeddings |
| `--output` | No | `<knowledge-path>/facts/isolation_records.csv` | Output CSV for isolation records |

### Workflow

```text
CLI -> fact_extraction.extract_facts_main() -> read CSV -> validate -> write isolation CSV -> report
```

1. CLI calls `fact_extraction.extract_facts_main()` directly
2. Reads per-iteration results from `facts/extractions.csv`
3. Validates extraction completeness (entity absence, semantic similarity >= 0.95)
4. Writes isolation records to output CSV with fact linkage
5. Outputs detailed report with validation status and similarity score

### Isolation Records CSV Schema

The `--output` CSV contains isolation records that track sentence changes per iteration:

| Column | Type | Description |
|--------|------|-------------|
| `fact_id` | VARCHAR | UUID linking to the originating fact in `extractions.csv` |
| `iteration` | VARCHAR | Iteration number (1-indexed) |
| `entity` | VARCHAR | The entity being extracted |
| `before_sentence` | VARCHAR | Sentence before this fact extraction |
| `isolated_fact` | VARCHAR | The atomic fact extracted in this iteration |
| `after_sentence` | VARCHAR | Sentence after this fact was removed |

This CSV provides traceability between isolation records and the underlying fact extractions.

### Output Report

The command outputs:

- Extraction results (facts per iteration)
- Residual sentence after all extractions
- Validation status with semantic similarity score
- Isolation records written to CSV path
- Movement record summary with fact IDs

### Semantic Similarity Validation

The validation step computes semantic similarity between:

- **Original**: The source sentence before any extraction
- **Reconstructed**: All extracted fact texts joined with the final residual

Using Qwen embeddings, the cosine similarity must be >= 0.95 for information preservation
to be considered successful. This ensures no semantic content is lost during extraction.

### Exit Codes

- `0`: Success - extraction complete and validated
- `1`: Error - CLI or validation failure
- `2`: Partial success - facts extracted but entity still present in residual

## Iterative Movement Tracking Workflow

The iterative movement tracking system records sentence-level changes during fact extraction, validating semantic similarity at each step.

### Recording Iterative Movements

```bash
# Record an iterative movement with validation
uv run knowledge.record-iterative-movement \
  --fact-id <uuid> \
  --before "Original sentence" \
  --fact "Extracted fact" \
  --after "Residual sentence"

# Specify custom reason
uv run knowledge.record-iterative-movement \
  --fact-id <uuid> \
  --before "..." \
  --fact "..." \
  --after "..." \
  --reason "Custom reason"

# Use heavier model for higher precision
uv run knowledge.record-iterative-movement \
  --fact-id <uuid> \
  --before "..." \
  --fact "..." \
  --after "..." \
  --model Qwen/Qwen3-Embedding-8B
```

**Exit Codes for `record-iterative-movement`:**

- `0`: Success - similarity >= 0.95, validation passed
- `1`: Error - model loading failure or file I/O error
- `2`: Validation failure - similarity < 0.95 (record still persisted for debugging)

### Querying Iterative Movements

```bash
# Query by entity (searches source_sentence) - compact view
uv run knowledge.query-iterative-movements --entity "create_app"

# Query by fact ID - compact view
uv run knowledge.query-iterative-movements --fact-id <uuid>

# Verbose mode - show full extraction chain details
uv run knowledge.query-iterative-movements --entity "create_app" --verbose
uv run knowledge.query-iterative-movements --fact-id <uuid> -v
```

The compact view shows truncated sentences for readability. Use `--verbose` or `-v` to see the complete source sentence, isolated fact, and residual sentence for each record.

### Validation Logic

Each iterative movement is validated using Qwen embeddings to ensure semantic similarity >= 0.95 between the original sentence and the reconstructed sentence (fact + residual). This implements the logic puzzle constraint: `original_sentence = fact1 + fact2 + ... + residual_sentence`.

Records with similarity < 0.95 are still persisted for debugging purposes, but the CLI returns exit code `2` to indicate validation failure. Callers should treat this as a non-successful validation outcome.

## Comparison Workflow with Timestamped Originals

The `compare-yml-docs` command accepts an optional `--original-files` parameter to compare
timestamped original files from the `originals/` directory instead of globbing for
`original.*.yml` files in the base path.

### Manual Usage

```bash
# Compare a specific timestamped original
uv run knowledge.compare-yml-docs --path docs/development \
    --original-files .knowledge/originals/20251201T134735Z-api-patterns.yml

# Compare multiple timestamped originals
uv run knowledge.compare-yml-docs --path docs/development \
    --original-files .knowledge/originals/20251201T134735Z-api-patterns.yml \
    .knowledge/originals/20251201T135000Z-docstrings-guide.yml
```

### Automated Usage via validate-migration

The `validate-migration` command automatically passes the original file reference from
`tasks.csv` to the comparison command:

```bash
uv run knowledge.validate-migration --task-id <uuid>
```

This reads the `original_file_ref` column from the task record and constructs the
full path to the timestamped original file in `.knowledge/originals/`.

### Backward Compatibility

When `--original-files` is not provided, the script falls back to globbing for
`original.*.yml` files in the base path, maintaining backward compatibility with
existing workflows.

## Git Tracking

- Directory structure (via `.gitkeep` files) is tracked:
  - `.knowledge/originals/.gitkeep`
  - `.knowledge/migrations/.gitkeep`
  - `.knowledge/comparisons/.gitkeep`
  - `.knowledge/resolutions/.gitkeep`
  - `.knowledge/movements/.gitkeep`
  - `.knowledge/additions/.gitkeep`
  - `.knowledge/reports/.gitkeep`
  - `.knowledge/keywords/.gitkeep`
  - `.knowledge/facts/.gitkeep`
- `README.md` is tracked
- Generated data files (`*.csv`, `*.yml`, `*.yaml`) are ignored via `.gitignore`
- DuckDB database file (`knowledge.duckdb`) is ignored
- Movement, addition, keyword, and fact CSV files, and generated review reports (YML) are also ignored as environment-specific artifacts that track content validation during migrations
- Iterative movement CSV files (`movements/iterative_movements.csv`) are also ignored
