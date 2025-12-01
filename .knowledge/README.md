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
├── additions/      # Addition tracking (new IDs in target files not in originals)
├── reports/        # Generated YML review reports for non-identical text comparisons
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

**Note**: Comparison CSVs are regenerated on each run of `uv run compare-yml-docs`.
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
```

## Addition Tracking Workflow

The addition tracking system identifies and validates new content (IDs) that appear in target files but weren't present in original files.

### Detecting Additions

```bash
# Track all additions across all patterns
uv run track-additions

# Track additions for a specific pattern
uv run track-additions --pattern api-patterns
```

### Validating Additions

```bash
# Mark an addition as validated, in-scope, and meaningful
uv run validate-addition --id <addition_id> --validated --in-scope --meaningful

# Mark only as validated (leave in-scope/meaningful unchanged)
uv run validate-addition --id <addition_id> --validated
```

### Querying Additions

Use DuckDB to query addition records (see DuckDB Queries section for examples).

## YML Report Generation Workflow

The report generation system creates YAML review reports for migration items that require human review due to non-identical text comparisons.

### Generating Reports

```bash
# Generate reports for all patterns
uv run generate-migration-report

# Generate report for a specific pattern
uv run generate-migration-report --pattern api-patterns
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

## Comparison Workflow with Timestamped Originals

The `compare-yml-docs` command accepts an optional `--original-files` parameter to compare
timestamped original files from the `originals/` directory instead of globbing for
`original.*.yml` files in the base path.

### Manual Usage

```bash
# Compare a specific timestamped original
uv run compare-yml-docs --path docs/development \
    --original-files .knowledge/originals/20251201T134735Z-api-patterns.yml

# Compare multiple timestamped originals
uv run compare-yml-docs --path docs/development \
    --original-files .knowledge/originals/20251201T134735Z-api-patterns.yml \
    .knowledge/originals/20251201T135000Z-docstrings-guide.yml
```

### Automated Usage via validate-migration

The `validate-migration` command automatically passes the original file reference from
`tasks.csv` to the comparison command:

```bash
uv run validate-migration --task-id <uuid>
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
- `README.md` is tracked
- Generated data files (`*.csv`, `*.yml`, `*.yaml`) are ignored via `.gitignore`
- DuckDB database file (`knowledge.duckdb`) is ignored
- Movement and addition CSV files, and generated review reports (YML) are also ignored as environment-specific artifacts that track content validation during migrations
